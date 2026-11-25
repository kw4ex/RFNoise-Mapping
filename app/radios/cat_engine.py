"""
cat_engine.py - reads the signal level of an ordinary radio over its USB / serial CAT cable.

One shared engine for every CAT radio. What differs between radios is only (a) the "dialect" (Icom's
binary CI-V frames, or the text commands ending in a semicolon used by Kenwood, Elecraft and Yaesu),
and (b) the table that turns the radio's S-meter number into dB. Both come from cat_models.json, so a
new radio of a known kind is a few lines of data.

Two ways of working (set per radio):
  follow   the program never changes the radio. You tune the radio; the program only asks it what it is
           hearing. If the radio is not on the frequency of the slot, that slot gives no reading (and says why).
  control  the program tunes the radio to the slot's frequency before it reads the meter.

Nothing here transmits, and nothing here writes any radio setting except the frequency (control mode).
"""
import json
import math
import os
import re
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS_FILE = os.path.join(HERE, "cat_models.json")
AUTO_BAUDS = (115200, 38400, 19200, 9600, 4800, 57600)


class CatError(Exception):
    """A readable problem (shown to the person as it is)."""


def is_flex(model):
    return bool(model) and model.get("dialect") == "flex_api"


def load_models():
    with open(MODELS_FILE, encoding="utf-8") as f:
        return json.load(f)


def model_by_id(mid):
    for m in load_models()["models"]:
        if m["id"] == mid:
            return m
    return None


def interp(table, raw):
    """Straight-line interpolation in a [[raw, dB], ...] table (clamped at both ends)."""
    t = sorted((float(a), float(b)) for a, b in table)
    if raw <= t[0][0]:
        return t[0][1]
    if raw >= t[-1][0]:
        return t[-1][1]
    for (x0, y0), (x1, y1) in zip(t, t[1:]):
        if x0 <= raw <= x1:
            return y0 + (y1 - y0) * (raw - x0) / (x1 - x0) if x1 != x0 else y1
    return t[-1][1]


def s9_dbm(mhz):
    """dBm of S9: -73 dBm up to 30 MHz, -93 dBm above (the IARU values)."""
    return -73.0 if mhz < 30.0 else -93.0


# ----------------------------------------------------------------------------
# the serial link (a tiny wrapper so tests can plug in a fake)
# ----------------------------------------------------------------------------
class Link:
    def __init__(self, port, baud, timeout=0.35):
        try:
            import serial
        except ImportError:
            raise CatError("The serial-port helper (pyserial) is not installed. Run the installer again.")
        try:
            self.ser = serial.Serial(port, int(baud), timeout=timeout, write_timeout=1.0)
        except Exception as e:
            msg = str(e)
            if "busy" in msg.lower() or "denied" in msg.lower() or "access" in msg.lower() or "in use" in msg.lower():
                raise CatError("Could not open %s: another program is using it (a logging program, Thetis or a "
                               "port tool?). Only one program can use a USB CAT cable at a time." % port)
            raise CatError("Could not open %s (%s). Check the cable, the port name and that the radio is on." % (port, msg))
        self.lock = threading.Lock()

    def drain(self):
        try:
            self.ser.reset_input_buffer()
        except Exception:
            pass

    def write(self, data):
        self.ser.write(data)
        self.ser.flush()

    def read_until(self, terminator, deadline):
        buf = b""
        while time.time() < deadline:
            b = self.ser.read(1 if not self.ser.in_waiting else self.ser.in_waiting)
            if b:
                buf += b
                if terminator in buf:
                    return buf
        return buf

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass


# ----------------------------------------------------------------------------
# dialect 1: Icom CI-V
# ----------------------------------------------------------------------------
def bcd_to_hz(b):
    """CI-V frequency: five bytes, least significant first, two digits per byte."""
    v = 0
    for i, x in enumerate(b[:5]):
        v += ((x >> 4) * 10 + (x & 15)) * (100 ** i)
    return v


def hz_to_bcd(hz):
    hz = int(round(hz))
    out = []
    for _ in range(5):
        two = hz % 100
        out.append(((two // 10) << 4) | (two % 10))
        hz //= 100
    return bytes(out)


class IcomCiv:
    CTRL = 0xE0

    def __init__(self, link, model):
        self.link = link
        self.addr = int(str(model.get("civ_addr", "0x94")), 16)

    def _frames(self, data):
        """Cut a byte string into CI-V frames (FE FE to from cmd ... FD)."""
        out, i = [], 0
        while True:
            s = data.find(b"\xfe\xfe", i)
            if s < 0:
                break
            e = data.find(b"\xfd", s + 2)
            if e < 0:
                break
            out.append(data[s + 2:e])
            i = e + 1
        return out

    def _ask(self, payload, want_cmd, timeout=0.5):
        """Send one command and return the data bytes of the radio's answer (None if it said 'no good')."""
        L = self.link
        with L.lock:
            L.drain()
            L.write(b"\xfe\xfe" + bytes([self.addr, self.CTRL]) + payload + b"\xfd")
            end = time.time() + timeout
            got = b""
            while time.time() < end:
                got += L.read_until(b"\xfd", min(end, time.time() + 0.15))
                for fr in self._frames(got):
                    if len(fr) < 3:
                        continue
                    to, frm, cmd = fr[0], fr[1], fr[2]
                    if frm == self.CTRL:
                        continue                                  # our own command, echoed back
                    if to == self.CTRL and frm == self.addr:
                        if cmd == 0xFA:
                            return None                           # the radio said "no good"
                        if cmd == want_cmd:
                            return bytes(fr[3:])
                    # frames meant for somebody else, or "transceive" broadcasts: ignore
        raise CatError("The radio did not answer (CI-V address %02Xh). Check the address, the baud rate and the cable." % self.addr)

    def read_freq(self):
        d = self._ask(b"\x03", 0x03)
        if not d or len(d) < 5:
            raise CatError("The radio gave no frequency.")
        return float(bcd_to_hz(d))

    def set_freq(self, hz):
        self._ask(b"\x05" + hz_to_bcd(hz), 0xFB)

    def read_meter(self):
        d = self._ask(b"\x15\x02", 0x15)
        if not d or len(d) < 3:
            raise CatError("The radio gave no S-meter reading.")
        b0, b1 = d[1], d[2]
        return float((b0 >> 4) * 1000 + (b0 & 15) * 100 + (b1 >> 4) * 10 + (b1 & 15))


# ----------------------------------------------------------------------------
# dialect 2: text commands ending in ";"  (Kenwood, Elecraft, Yaesu)
# ----------------------------------------------------------------------------
class TextCat:
    def __init__(self, link, model):
        self.link = link
        self.digits = int(model.get("freq_digits", 11))
        self.mcmd = model.get("meter_cmd", "SM0;")
        self.mpre = model.get("meter_prefix", "SM0")

    def _ask(self, cmd, prefix, timeout=0.5):
        L = self.link
        with L.lock:
            L.drain()
            L.write(cmd.encode("ascii"))
            end = time.time() + timeout
            buf = b""
            while time.time() < end:
                buf += L.read_until(b";", min(end, time.time() + 0.15))
                for part in buf.decode("ascii", "ignore").split(";"):
                    part = part.strip()
                    if part == "?":
                        raise CatError("The radio did not understand '%s' (it answered '?'). Is the model right?" % cmd.strip(";"))
                    if part.startswith(prefix) and part[len(prefix):].lstrip("+-").isdigit():
                        return part[len(prefix):]
        raise CatError("The radio did not answer '%s'. Check the baud rate (it must match the radio's menu), the cable and the model." % cmd)

    def read_freq(self):
        return float(int(self._ask("FA;", "FA")))

    def set_freq(self, hz):
        L = self.link
        with L.lock:
            L.write(("FA%0*d;" % (self.digits, int(round(hz)))).encode("ascii"))

    def read_meter(self):
        return float(int(self._ask(self.mcmd, self.mpre)))


DIALECTS = {"icom_civ": IcomCiv, "text_cat": TextCat}


# ----------------------------------------------------------------------------
# the radio as the rest of the program sees it
# ----------------------------------------------------------------------------
class CatRadio:
    """Reader with the same calls the other radios have: measure(...), last_frame(), health(), close()."""
    multi = False
    settle_s = 0.06

    def __init__(self, entry, link=None):
        self.entry = dict(entry)
        model = model_by_id(entry.get("model"))
        if model is None:
            raise CatError("Unknown radio model '%s'." % entry.get("model"))
        self.model = model
        self.mode = "control" if str(entry.get("mode")) == "control" else "follow"
        self.name = "%s %s" % (model["maker"], model["name"])
        self.settle_s = float(model.get("settle_s", self.settle_s))
        if link is None:
            port = str(entry.get("port") or "").strip()
            if is_flex(model):
                if not port:
                    raise CatError("%s: no network address yet. Press 'Find on network' or type the radio's address." % self.name)
                import radios.flex_api as FX
                try:
                    link = FX.shared_link(port, gui=(self.mode == "control"))
                except FX.FlexError as e:
                    raise CatError(str(e))
            else:
                if not port:
                    raise CatError("%s: no USB port chosen yet." % self.name)
                link = Link(port, int(entry.get("baud") or model.get("baud") or 19200))
        self.link = link
        em = dict(model)
        if entry.get("civ_addr"):
            em["civ_addr"] = entry["civ_addr"]
        if is_flex(model):
            import radios.flex_api as FX
            self.d = FX.FlexApi(link, em)
        else:
            self.d = DIALECTS[model["dialect"]](link, em)
        self._freqs = {}                 # per slot: the frequency its slice was last tuned to (Flex Control mode has one slice per slot)
        self._em = em
        self._apis = {}                  # slot -> its own FlexApi (own slice and panadapter), so nothing is retuned between pictures
        self._lastd = self.d
        self.want_mode = "AM"            # mode and receive-filter width the slot asks for (set by the logger before each measure())
        self.want_filt = 0
        self.want_follow = False         # Flex: keep the tuned signal centred in the picture
        self.want_ctr = 0                # Flex: a newer number = centre the picture once (the Centre button)
        self.want_span = 0.0             # Flex zoom: the width (kHz) of the slot's panadapter, 0 = leave it alone
        self._mf = {}                    # slot -> (mode, filter) last sent to the radio
        self.cur = 0                     # the slot being measured; the logger sets it before each measure()
        self.mismatch = None             # follow mode: the frequency the radio is really on, when it is not the slot's
        self.last_raw = None
        self.last_error = ""
        self.last_actual_hz = None
        self.last_dbm = None

    # one meter number -> dBm for the frequency it was read on
    def to_dbm(self, raw, freq_hz):
        if is_flex(self.model):
            return raw                    # the Flex reports calibrated dBm itself
        return interp(self.model["meter"], raw) + s9_dbm(freq_hz / 1e6)

    def probe(self):
        """Used by the Test button: what is the radio on, and what does it hear now?"""
        if is_flex(self.model) and self.mode == "control":
            self.d._slice(make=True)          # Control mode: the test makes its own slice (and removes it again when it closes)
        f = self.d.read_freq()
        raw = self.d.read_meter()
        if is_flex(self.model):
            return {"freq_hz": f, "raw": raw, "rel_s9_db": 0.0, "dbm": raw}
        rel = interp(self.model["meter"], raw)
        return {"freq_hz": f, "raw": raw, "rel_s9_db": rel, "dbm": rel + s9_dbm(f / 1e6)}

    def _api_for(self):
        """The reader for the slot being measured. A Flex in Control mode keeps one slice + panadapter per slot, so a slot is only
        retuned when its own frequency changes and the spectrum can stream at the radio's full rate (it was about 1 per second
        when the slots shared one slice). Every other radio has one reader."""
        if self.mode == "control" and is_flex(self.model):
            key = self.cur
            d = self._apis.get(key)
            if d is None:
                import radios.flex_api as FX
                d = self.d if not self._apis else FX.FlexApi(self.link, self._em)
                self._apis[key] = d
            return key, d
        return None, self.d

    def measure(self, freq_hz, bw_hz, lat, lon, settings):
        """dBm at the slot's frequency; NaN (and a reason in last_error) when the radio cannot give one."""
        key = None
        try:
            self.last_error = ""
            self.mismatch = None
            key, d = self._api_for()
            self._lastd = d
            if self.mode == "control" and is_flex(self.model) and self.want_span > 0 and hasattr(d, "set_span"):
                d.set_span(self.want_span * 1e3)
            if self.mode == "control" and is_flex(self.model) and hasattr(d, "set_pan_mode"):
                d.set_pan_mode(self.want_follow, self.want_ctr)
            if self.mode == "control":
                last = self._freqs.get(key)
                dial = freq_hz                                    # the slice must sit on the DIAL frequency (the carrier); the band measured is centred freq_hz
                if is_flex(self.model):
                    wm = str(self.want_mode or "AM").upper()
                    dial = freq_hz + bw_hz / 2.0 if wm == "LSB" else (freq_hz - bw_hz / 2.0 if wm == "USB" else freq_hz)
                if last is None or abs(last - freq_hz) > 0.5:
                    d.set_freq(freq_hz, dial) if is_flex(self.model) else d.set_freq(freq_hz)
                    time.sleep(self.settle_s)
                    self._freqs[key] = freq_hz
                mf = (self.want_mode, self.want_filt)
                if self._mf.get(key) != mf and hasattr(d, "set_mode"):
                    d.set_mode(self.want_mode, self.want_filt)          # the slot's mode and filter width go to the radio's slice
                    self._mf[key] = mf
                f = freq_hz
            else:
                f = d.read_freq()
                self.last_actual_hz = f
                tol = max(1000.0, bw_hz / 2.0)
                if abs(f - freq_hz) > tol:
                    self.mismatch = f
                    self.last_error = ("The radio is on %.4f MHz but this slot is %.4f MHz. Tune the radio, or press "
                                       "'Use the radio's frequency' for this slot." % (f / 1e6, freq_hz / 1e6))
                    return float("nan")
            vals = []
            for _ in range(3):
                vals.append(d.read_meter())
            raw = sorted(vals)[len(vals) // 2]                 # the middle of three: ignores a single odd reading
            self.last_raw = raw
            self.last_dbm = self.to_dbm(raw, f)
            return self.last_dbm
        except CatError as e:
            self.last_error = str(e)
            self._freqs.pop(key, None); self._mf.pop(key, None)
            return float("nan")
        except Exception as e:
            self.last_error = str(e) if type(e).__name__ == "FlexError" else "Radio problem: %s" % e
            self._freqs.pop(key, None); self._mf.pop(key, None)
            return float("nan")

    def audio_for(self, key):
        """The Flex slice's sound source for slot `key`, or None when this radio cannot give sound (not a Flex in Control mode,
        or the slot has not been measured yet)."""
        if self.mode != "control" or not is_flex(self.model):
            return None
        return self._apis.get(key)

    def last_frame(self):
        """A Flex in Control mode (its own panadapter) gives a real spectrum picture; every other CAT radio gives none."""
        if is_flex(self.model) and self.mode == "control":
            try:
                fr = self._lastd.frame()
            except Exception:
                fr = None
            if fr and getattr(self, "last_dbm", None) is not None:
                return (fr[0], fr[1], fr[2], self.last_dbm)
        return None

    def health(self):
        return {"cat": {"name": self.name, "mode": self.mode, "raw": self.last_raw, "error": self.last_error}}

    def close(self):
        try:
            if is_flex(self.model):
                import radios.flex_api as FX
                FX.release_link(self.link, [self.d] + list(self._apis.values()))
            else:
                self.link.close()
        except Exception:
            pass


def test_radio(entry):
    """Try to talk to a radio from the setup window. Returns {"ok": bool, "message": str, ...}.
    If the baud rate does not work, other common rates are tried and the one that works is reported."""
    model = model_by_id(entry.get("model"))
    if model is None:
        return {"ok": False, "message": "Pick the radio model first."}
    port = str(entry.get("port") or "").strip()
    if is_flex(model):
        try:
            r = CatRadio(entry)
            p = r.probe()
            r.close()
            return {"ok": True, "freq_hz": p["freq_hz"], "dbm": p["dbm"], "raw": p["raw"],
                    "message": "Connected to the Flex. Its slice is on %.4f MHz and the signal reads %.0f dBm." % (p["freq_hz"] / 1e6, p["dbm"])}
        except Exception as ex:
            return {"ok": False, "message": str(ex)}
    if not port:
        return {"ok": False, "message": "Pick the USB port first."}
    first = int(entry.get("baud") or model.get("baud") or 19200)
    bauds = [first] + [b for b in AUTO_BAUDS if b != first]
    last = ""
    for b in bauds:
        try:
            e = dict(entry)
            e["baud"] = b
            r = CatRadio(e)
        except CatError as ex:
            return {"ok": False, "message": str(ex)}
        try:
            p = r.probe()
            r.close()
            note = "" if b == first else " The baud rate that works is %d; it has been filled in for you." % b
            return {"ok": True, "baud": b, "freq_hz": p["freq_hz"], "raw": p["raw"], "dbm": p["dbm"],
                    "message": "Connected. The radio is on %.4f MHz and the signal reads %.0f dBm (meter number %d).%s"
                               % (p["freq_hz"] / 1e6, p["dbm"], p["raw"], note)}
        except CatError as ex:
            last = str(ex)
            r.close()
            if "?" in last and "answered" in last:
                break
    return {"ok": False, "message": last or "The radio did not answer."}
