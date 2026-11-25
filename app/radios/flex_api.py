"""
flex_api.py - FlexRadio 6000 / 8000 series, read over the radio's own network interface (the SmartSDR API).

How it works, in plain words
  * The radio listens on TCP port 4992. We connect, send plain-text commands ("C12|slice tune 0 7.100000")
    and the radio sends plain-text news back ("S<handle>|slice 0 RF_frequency=7.100000 ...").
  * We ask for news about slices, meters and panadapters ("sub slice all", "sub meter all", "sub pan all").
    Without "sub pan all" the radio never says which panadapter our slice sits on, so no spectrum picture can be asked for.
  * The meter VALUES do not come over the TCP line. The radio sends them as small UDP packets to a port we
    announce with "client udpport N". Each packet holds pairs of (meter number, value); for dBm meters the
    value is a signed 16-bit number in 1/128 dB steps.
  * The meter named LEVEL whose source is SLC and number equals the slice number is that slice's signal
    strength in dBm, already calibrated by the radio. So no S-meter table is needed.

Follow mode  : we only read the slice's frequency and level. Nothing is changed in SmartSDR.
Control mode : we register as a GUI client ("client gui"), make our own panadapter and slice and tune that one ("slice tune"); a slice that SmartSDR or an
               earlier run left open is not touched. We remove ours again when the program closes.

This file also finds radios on the network (find_radios) from the broadcast every Flex sends once a second.
NOT YET TRIED ON A REAL FLEX: it is tested against a pretend radio (cat_sim.FakeFlex).
"""
import collections
import os
import socket
import struct
import threading
import time

PORT = 4992


def _hnorm(h):
    """A client handle written the same way everywhere: upper case, no 0x, no leading zeros."""
    h = str(h).strip().upper()
    if h.startswith("0X"):
        h = h[2:]
    return h.lstrip("0") or "0"


def _log(level, msg):
    """Write a line to the program log (Logs/program_errors.log) when the logger is available."""
    try:
        import nt_log
        getattr(nt_log, level)(msg)
    except Exception:
        pass


class FlexError(Exception):
    pass


def parse_kv(text):
    out = {}
    for tok in text.replace("\x00", " ").split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            out[k] = v
    return out


def find_radios(seconds=3.0, port=PORT, stats=None):
    """Listen for the radios' once-a-second broadcast. Returns [{"ip","model","nickname","serial","version","status"}].
    stats (a dict, optional) is filled with {"heard": number of UDP packets seen at all}."""
    found = {}
    heard = 0
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass
        s.bind(("", port))
    except OSError as e:
        s.close()
        raise FlexError("Could not listen for Flex radios on this computer (UDP %d is busy or blocked: %s). "
                        "Type the radio's address by hand instead." % (port, e))
    end = time.time() + seconds
    try:
        while time.time() < end:
            s.settimeout(max(0.1, end - time.time()))
            try:
                data, addr = s.recvfrom(4096)
            except socket.timeout:
                break
            heard += 1
            kv = parse_kv(data.decode("latin-1", "ignore"))        # the whole packet: the text part holds the key=value words
            if "model" in kv or "serial" in kv or "discovery_protocol_version" in kv:
                ip = kv.get("ip") or addr[0]
                found[ip] = {"ip": ip, "model": kv.get("model", ""), "nickname": kv.get("nickname", "").replace("_", " "),
                             "serial": kv.get("serial", ""), "version": kv.get("version", ""),
                             "status": kv.get("status", "")}
    finally:
        s.close()
    if stats is not None:
        stats["heard"] = heard
    return sorted(found.values(), key=lambda r: r["ip"])


def why_none(heard):
    if heard:
        return ("Heard %d network message(s) on the Flex port, but none from a Flex radio." % heard)
    return ("Heard nothing from any Flex. Usual causes: the Mac firewall blocking RFI Trail/Python (System Settings > Network > "
            "Firewall), the radio and Mac on different networks (Wi-Fi vs the radio's cable/router), a VPN, or the radio is only "
            "reachable through SmartLink. You can still type the radio's address (SmartSDR shows it) and press Test.")


_SHARED = {}
_SHARED_LOCK = threading.Lock()


def shared_link(host, gui=False):
    """One connection per radio and mode, shared by whoever asks (a Flex allows only a few connected programs, and a restart of the
    preview that overlapped the old one used to open a second connection and be refused). Give it back with release_link()."""
    key = (str(host).strip(), bool(gui))
    with _SHARED_LOCK:
        e = _SHARED.get(key)
        if e and not e[0].closed:
            e[1] += 1
            return e[0]
        link = FlexLink(host, gui=gui)
        _SHARED[key] = [link, 1]
        return link


def release_link(link, apis=()):
    """Let go of a shared connection; it is closed when the last user lets go."""
    with _SHARED_LOCK:
        for key, e in list(_SHARED.items()):
            if e[0] is link:
                for a in apis:
                    try:
                        link.apis.remove(a)
                    except ValueError:
                        pass
                e[1] -= 1
                if e[1] <= 0:
                    del _SHARED[key]
                    link.close()
                return
    link.close()


class FlexLink:
    """The connection: TCP for commands and news, UDP for meter values."""

    def __init__(self, host, port=PORT, timeout=3.0, gui=False):
        self.host, self.port = str(host).strip(), port
        self.is_gui = False            # True once the radio has accepted us as a GUI client (needed to make our own panadapter)
        if self.host.count(":") == 1:                      # "192.168.1.50:4992"
            h, _, pt = self.host.partition(":")
            if pt.isdigit():
                self.host, self.port = h, int(pt)
        self.lock = threading.Lock()
        self.slices = {}              # index -> {"freq_mhz": float, "mode": str, "active": bool}
        self.meters = {}              # meter id -> {"src","num","nam","unit"}
        self.values = {}              # meter id -> (dbm, time)
        self.replies = {}             # seq -> (code, message)
        self.seq = 0
        self.handle = ""
        self.version = ""
        self.mk_lock = threading.RLock()
        self.created = []             # slices this program made (removed again on close)
        self.clients = set()          # handles of the programs connected to the radio right now (from 'sub client all')
        self.pan_owner = {}           # panadapter id -> handle of the program that owns it
        self.swept = False
        self.audio = {}               # stream id (int) -> deque of mono float32 blocks at 24 kHz, from the radio's DAX audio streams
        self.audio_pkts = 0
        self.audio_cls = {}           # packet class -> count (for the log when no sound arrives)
        self.streams = []             # streams this program made (removed again on close)
        self.next_dax = 1
        self.fail_until = 0.0
        self.fail_msg = ""
        self.told_open = False
        self.pans = set()             # panadapters the radio has told us about
        self.made_pans = []           # panadapters this program made (removed again on close)
        self.pan_set = {}             # pan id -> {"x","y","min","max","center","bw"} as we set them (needed to turn pixels into dBm)
        self.pan_bins = {}            # pan id -> {"frame": n, "bins": array, "got": count, "total": n}
        self.frames = {}              # pan id -> (time, numpy array of dBm)
        self.fft_sids = {}            # panadapter id -> spectrum packets seen for it (for the log)
        self.fft_done = {}            # panadapter id -> complete pictures built
        self.fft_shape = {}           # panadapter id -> (bins in a picture, bins per packet) of the newest packet
        self.audio_sids = {}          # stream id -> sound packets seen for it
        self.apis = []                # every FlexApi on this link (for the log)
        self.fft_packets = 0          # spectrum packets that arrived from the radio (for the log)
        self.fft_error = ""           # the first problem met while reading a spectrum packet
        self.closed = False
        self.buf = b""
        try:
            self.tcp = socket.create_connection((self.host, self.port), timeout=timeout)
        except OSError as e:
            raise FlexError("Could not connect to the Flex at %s (%s). Check the address, that the radio is on, "
                            "and that this computer is on the same network." % (self.host, e))
        self.tcp.settimeout(0.5)
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.bind(("", 0))
        self.udp.settimeout(0.5)
        self.udp_port = self.udp.getsockname()[1]
        threading.Thread(target=self._tcp_loop, daemon=True).start()
        threading.Thread(target=self._udp_loop, daemon=True).start()
        threading.Thread(target=self._diag_loop, daemon=True).start()
        threading.Thread(target=self._jacks_loop, daemon=True).start()
        t0 = time.time()
        while not self.handle and time.time() - t0 < timeout:
            time.sleep(0.02)
        if not self.handle:
            self.close()
            raise FlexError("The Flex at %s did not say hello. Is that really a FlexRadio?" % self.host)
        self.cmd("client program RFI_Trail", wait=False)
        self.cmd("client udpport %d" % self.udp_port)
        self.cmd("sub slice all")
        self.cmd("sub pan all")                       # new in 0.4.0a: the radio then tells us which panadapter each slice is on
        self.cmd("sub meter all")
        try:
            self.cmd("sub client all")                  # lists who is connected, so slices left behind by dead programs can be told apart
        except FlexError:
            pass
        if gui:
            # Control mode: register as a GUI client. Only a GUI client may make its own panadapter on a real Flex, and
            # everything a GUI client makes belongs to it (it goes away with it) instead of being left behind. (probe, 2026-11-19)
            try:
                code, msg = self.cmd("client gui", timeout=3.0)
                self.is_gui = True
                _log("info", "Flex: registered as a GUI client (%s)." % (msg or code))
            except FlexError as e:
                _log("warn", "Flex: the radio would not take RFI Trail as a GUI client (%s), so there will be no spectrum picture. "
                             "(A Flex allows only a few GUI programs at once: close one you do not need.)" % e)
        t0 = time.time()
        while not self.meters and time.time() - t0 < 1.5:       # the meter list arrives right after "sub meter all"
            time.sleep(0.02)

    # ---- receiving ----
    def _tcp_loop(self):
        while not self.closed:
            try:
                d = self.tcp.recv(4096)
                if not d:
                    break
            except socket.timeout:
                continue
            except OSError:
                break
            self.buf += d
            while b"\n" in self.buf:
                line, self.buf = self.buf.split(b"\n", 1)
                try:
                    self._line(line.decode("latin-1").strip())
                except Exception:
                    pass
        self.closed = True

    def _line(self, s):
        if not s:
            return
        c = s[0]
        if c == "V":
            self.version = s[1:]
        elif c == "H":
            self.handle = s[1:]
        elif c == "R":
            parts = s[1:].split("|", 2)
            try:
                seq = int(parts[0])
            except ValueError:
                return
            with self.lock:
                self.replies[seq] = (parts[1] if len(parts) > 1 else "", parts[2] if len(parts) > 2 else "")
        elif c == "S":
            body = s.split("|", 1)[1] if "|" in s else ""
            self._status(body)

    def _status(self, body):
        if body.startswith("slice "):
            rest = body[6:].split(" ", 1)
            try:
                idx = int(rest[0])
            except ValueError:
                return
            kv = parse_kv(rest[1] if len(rest) > 1 else "")
            with self.lock:
                if "in_use" in kv and kv["in_use"] == "0":
                    self.slices.pop(idx, None)
                    return
                sl = self.slices.setdefault(idx, {})
                sl.setdefault("kv", {}).update(kv)
                if "RF_frequency" in kv:
                    sl["freq_mhz"] = float(kv["RF_frequency"])
                if "mode" in kv:
                    sl["mode"] = kv["mode"]
                if "active" in kv:
                    sl["active"] = kv["active"] == "1"
                if "pan" in kv:
                    sl["pan"] = kv["pan"]
                if "client_handle" in kv:
                    sl["client"] = _hnorm(kv["client_handle"])
        elif body.startswith("client "):
            tok = body[7:].split()
            if len(tok) >= 2 and tok[0].startswith("0x"):
                with self.lock:
                    if tok[1] == "connected":
                        self.clients.add(_hnorm(tok[0]))
                    elif tok[1] == "disconnected":
                        self.clients.discard(_hnorm(tok[0]))
        elif body.startswith("display pan "):
            parts = body[12:].split()
            if parts and parts[0].startswith("0x"):
                with self.lock:
                    self.pans.add(parts[0])
                    for kvp in parts[1:]:
                        if kvp.startswith("client_handle="):
                            self.pan_owner[parts[0]] = _hnorm(kvp[14:])
        elif body.startswith("meter ") and body.strip().endswith("removed"):
            try:
                mid = int(body.split()[1])
            except (ValueError, IndexError):
                return
            with self.lock:
                self.meters.pop(mid, None)
                self.values.pop(mid, None)
        elif body.startswith("meter "):
            # "meter 5.src=SLC#5.num=0#5.nam=LEVEL#5.unit=dBm#6.src=..."
            with self.lock:
                for item in body[6:].replace(" ", "#").split("#"):
                    if "." not in item or "=" not in item:
                        continue
                    key, val = item.split("=", 1)
                    mid, field = key.split(".", 1)
                    try:
                        mid = int(mid)
                    except ValueError:
                        continue
                    self.meters.setdefault(mid, {})[field] = val

    def _jacks_path(self):
        try:
            import nt_common
            return os.path.join(nt_common.sub_dir("Settings"), "flex_jacks_mute.json")
        except Exception:
            return ""

    def _jacks_loop(self):
        """The radio's own speaker / headphone / line-out jacks: muted or not as the 'Mute radio speaker' setting says (a small file both programs
        read). Nothing is sent until the setting has been used once. The sound sent to this computer is not affected."""
        last = None
        while not self.closed:
            time.sleep(1.5)
            try:
                p = self._jacks_path()
                if not p or not os.path.exists(p):
                    continue
                import json
                with open(p, "r", encoding="utf-8") as f:
                    want = bool(json.load(f).get("mute"))
                if want == last:
                    continue
                self.set_jacks_mute(want)
                last = want
            except Exception as e:
                _log("warn", "Flex: could not set the radio's own speaker mute (%s)." % e)
                last = None
                time.sleep(10)

    def set_jacks_mute(self, on):
        v = 1 if on else 0
        got = []
        for c in ("mixer lineout mute %d" % v, "mixer headphone mute %d" % v):
            try:
                got.append("%s -> %s" % (c, self.cmd(c, timeout=2.0)))
            except FlexError as e:
                got.append("%s -> refused (%s)" % (c, e))
        _log("info", "Flex: radio speaker/headphone mute %s. Radio answered: %s" % ("ON" if on else "off", "; ".join(got)))

    def _diag_loop(self):
        """0.6.0b: three times after connecting (20, 60 and 150 s) write one line saying what the radio and this program each think."""
        t0 = time.time()
        for at in (20, 60, 150):
            while time.time() - t0 < at:
                if self.closed:
                    return
                time.sleep(0.5)
            try:
                with self.lock:
                    now = time.time()
                    ap = []
                    for a in self.apis:
                        f = self.frames.get(a.pid) if a.pid else None
                        ap.append("slot-reader idx=%s pid=%s pan_set=%s centre=%s frame_age=%s frame_calls=%d tuned_age=%.1f" % (
                            a.idx, a.pid, bool(self.pan_set.get(a.pid)), (self.pan_set.get(a.pid) or {}).get("center"),
                            ("%.1f" % (now - f[0])) if f else None, a.fcalls, now - a.tuned_at if a.tuned_at else -1))
                    sl = {i: (v.get("pan"), v.get("client"), v.get("freq_mhz")) for i, v in self.slices.items()}
                    _log("warn", "Flex check at %ds: spectrum packets per panadapter %s; pictures completed %s; packet shape %s; read error %r; "
                                 "panadapters known %s; sizes set %s; made by us %s; slices (pan, owner, MHz) %s; our handle %s; programs %s; "
                                 "readers: %s; sound packets per stream %s." % (
                                 at, dict(self.fft_sids), dict(self.fft_done), dict(self.fft_shape), self.fft_error, sorted(self.pans),
                                 sorted(self.pan_set), list(self.made_pans), sl, self.handle, sorted(self.clients), " | ".join(ap), dict(self.audio_sids)))
            except Exception as e:
                _log("warn", "Flex check failed: %s" % e)
        while not self.closed:                       # then, for as long as we are connected: say so whenever a slot's picture stops
            time.sleep(5.0)
            now = time.time()
            for a in list(self.apis):
                try:
                    if a.pid and now - a.last_good > 6.0 and now - a.wd_logged > 30.0:
                        a.wd_logged = now
                        with self.lock:
                            f = self.frames.get(a.pid); st = dict(self.pan_set.get(a.pid) or {})
                        _log("warn", "Flex: slot reader (slice %s, panadapter %s) has had no picture for %.0f s. Last reason: %s. Picture age %s s; "
                                     "asked for a picture %s s ago (a large number means the measuring loop is stuck); retuned %.0f s ago; panadapter centre %s Hz, "
                                     "span %.0f Hz, sizes %s; spectrum packets for it so far %s, pictures completed %s; sound stream %s." % (
                                     a.idx, a.pid, now - a.last_good, a.why, ("%.1f" % (now - f[0])) if f else None,
                                     ("%.1f" % (now - a.last_call)) if a.last_call else "never", now - a.tuned_at if a.tuned_at else -1,
                                     st.get("center"), a.span_hz, {k: st.get(k) for k in ("x", "y", "min", "max")},
                                     self.fft_sids.get(a.pid), self.fft_done.get(a.pid), getattr(a, "audio_sid", None)))
                except Exception as e:
                    _log("warn", "Flex watchdog failed: %s" % e)

    def _udp_loop(self):
        while not self.closed:
            try:
                d, _ = self.udp.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if len(d) < 32:
                continue
            cls = struct.unpack(">I", d[12:16])[0] & 0xFFFF
            if cls == 0x8003:                                              # a panadapter (spectrum) packet
                self.fft_packets += 1
                try:
                    self._fft(d)
                except Exception as e:
                    if not self.fft_error:
                        self.fft_error = "%s: %s" % (type(e).__name__, e)
                continue
            if cls in (0x03E3, 0x0123):                                    # DAX audio: 0x03E3 = float32 stereo, 0x0123 = int16 mono (reduced bandwidth)
                self.audio_pkts += 1
                self.audio_cls[cls] = self.audio_cls.get(cls, 0) + 1
                try:
                    import numpy as np
                    sid = struct.unpack(">I", d[4:8])[0]
                    self.audio_sids["0x%X" % sid] = self.audio_sids.get("0x%X" % sid, 0) + 1
                    body = d[28:]
                    if cls == 0x03E3:
                        self._probe_audio(sid, np.frombuffer(body[:len(body) // 8 * 8], dtype=">f4").astype(np.float32).reshape(-1, 2))
                        a = np.frombuffer(body[:len(body) // 8 * 8], dtype=">f4").astype(np.float32).reshape(-1, 2).mean(axis=1)
                    else:
                        a = np.frombuffer(body[:len(body) // 2 * 2], dtype=">i2").astype(np.float32) / 32768.0
                    q = self.audio.get(sid)
                    if q is not None:
                        q.append(a)
                except Exception as e:
                    if not self.fft_error:
                        self.fft_error = "audio: %s: %s" % (type(e).__name__, e)
                continue
            if cls != 0x8002:                                              # not a meter packet
                continue
            now = time.time()
            body = d[28:]
            with self.lock:
                for i in range(0, len(body) - 3, 4):
                    mid, v = struct.unpack(">Hh", body[i:i + 4])
                    self.values[mid] = (v / 128.0, now)

    def _probe_audio(self, sid, st):
        """Keep the first 10 s of the radio's raw stereo sound for each stream and save it as a WAV in the Logs folder (so it can be examined)."""
        if not os.environ.get("NT_FLEX_DIAG"):                       # support checks: off unless asked for
            return
        pr = self.__dict__.setdefault("probe", {})
        e = pr.setdefault(sid, {"n": 0, "chunks": [], "done": False})
        if e["done"]:
            return
        e["chunks"].append(st.copy()); e["n"] += len(st)
        if e["n"] >= 240000:
            e["done"] = True
            try:
                import numpy as np, wave, nt_common
                x = np.concatenate(e["chunks"]); e["chunks"] = []
                os.makedirs(nt_common.sub_dir("Logs"), exist_ok=True)
                fn = os.path.join(nt_common.sub_dir("Logs"), "flex_audio_probe_0x%X.wav" % sid)
                w = wave.open(fn, "wb"); w.setnchannels(2); w.setsampwidth(2); w.setframerate(24000)
                w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes()); w.close()
                _log("info", "Flex: saved 10 s of the radio's raw sound for stream 0x%X to %s (for checking)." % (sid, fn))
            except Exception as ex:
                _log("warn", "Flex: could not save the sound sample (%s)." % ex)

    def _fft(self, d):
        """One piece of a spectrum picture: header (start bin, number of bins, bytes per bin, total bins, frame number), then the bins."""
        import numpy as np
        pid = "0x%X" % struct.unpack(">I", d[4:8])[0]
        self.fft_sids[pid] = self.fft_sids.get(pid, 0) + 1
        st = self.pan_set.get(pid)
        if not st:
            return
        start, num, size, total, frame = struct.unpack(">HHHHI", d[28:40])
        self.fft_shape[pid] = (total, num, size)
        vals = np.frombuffer(d[40:40 + 2 * num], dtype=">u2").astype(np.float64)
        if len(vals) < num:
            return
        a = self.pan_bins.get(pid)
        if not a or a["frame"] != frame or a["total"] != total:
            a = self.pan_bins[pid] = {"frame": frame, "total": total, "bins": np.zeros(total), "got": 0}
        a["bins"][start:start + num] = vals
        a["got"] += num
        if a["got"] >= total:
            y = float(st["y"])
            dbm = st["max"] - (a["bins"] / y) * (st["max"] - st["min"])          # pixel 0 = top of the picture = max dBm
            self.frames[pid] = (time.time(), dbm)
            self.fft_done[pid] = self.fft_done.get(pid, 0) + 1
            self.pan_bins.pop(pid, None)

    # ---- sending ----
    def cmd(self, text, wait=True, timeout=2.0):
        with self.lock:
            self.seq += 1
            seq = self.seq
        try:
            self.tcp.sendall(("C%d|%s\n" % (seq, text)).encode())
        except OSError as e:
            raise FlexError("Lost the connection to the Flex (%s)." % e)
        if not wait:
            return ("0", "")
        t0 = time.time()
        while time.time() - t0 < timeout:
            with self.lock:
                if seq in self.replies:
                    code, msg = self.replies.pop(seq)
                    break
            time.sleep(0.01)
        else:
            raise FlexError("The Flex did not answer the command '%s'." % text)
        if code not in ("0", "00000000"):
            raise FlexError("The Flex refused '%s' (code %s%s)." % (text, code, (": " + msg) if msg else ""))
        return (code, msg)

    def sweep_orphans(self):
        """Remove slices and panadapters whose owner is no longer connected (left behind by programs that were stopped hard).
        Only done when the radio's client list is readable AND lists us, so a slice that belongs to somebody connected
        (SmartSDR on another computer, say) is never touched."""
        with self.lock:
            me = _hnorm(self.handle)
            ok = bool(self.clients) and me in self.clients
            sl = {i: dict(v) for i, v in self.slices.items()}
            po = dict(self.pan_owner)
            alive = set(self.clients)
        if not ok:
            if not self.swept:
                _log("info", "Flex: could not read the radio's list of connected programs, so slices left behind by old runs are not cleaned up.")
            self.swept = True
            return 0
        self.swept = True
        gone_s = [i for i, v in sl.items() if v.get("client") and v["client"] not in alive]
        gone_p = [p for p, h in po.items() if h not in alive]
        for i in gone_s:
            try:
                self.cmd("slice remove %d" % i, timeout=1.5)
            except FlexError:
                pass
        for p in gone_p:
            try:
                self.cmd("display panafall remove %s" % p, timeout=1.5)
            except FlexError:
                pass
        if gone_s or gone_p:
            _log("info", "Flex: removed %d slice(s) and %d panadapter(s) left behind by programs that are no longer connected." % (len(gone_s), len(gone_p)))
            time.sleep(0.4)
        return len(gone_s) + len(gone_p)

    def close(self):
        if self.closed and not self.created:
            pass
        if self.is_gui:                                  # also anything the radio says is ours that we lost track of (a reply that came too late)
            me = _hnorm(self.handle)
            with self.lock:
                for i, v in self.slices.items():
                    if v.get("client") == me and i not in self.created:
                        self.created.append(i)
                for pid, h in self.pan_owner.items():
                    if h == me and pid not in self.made_pans:
                        self.made_pans.append(pid)
        for idx in list(self.created):
            try:
                self.tcp.sendall(("C%d|slice remove %d\n" % (self.seq + 1, idx)).encode())
                time.sleep(0.1)
            except Exception:
                pass
        self.created = []
        for sid in list(self.streams):
            try:
                self.tcp.sendall(("C%d|stream remove 0x%X\n" % (self.seq + 3, sid)).encode())
                time.sleep(0.05)
            except Exception:
                pass
        self.streams = []
        for pid in list(self.made_pans):
            try:
                self.tcp.sendall(("C%d|display panafall remove %s\n" % (self.seq + 2, pid)).encode())
                time.sleep(0.1)
            except Exception:
                pass
        self.made_pans = []
        self.closed = True
        for s in (self.tcp, self.udp):
            try:
                s.close()
            except Exception:
                pass


class FlexApi:
    """The same three calls the CAT dialects have: read_freq(), set_freq(hz), read_meter() (here in dBm)."""

    def __init__(self, link, model):
        self.link = link
        self.model = model
        self.idx = None
        self.tuned_at = 0.0
        self.pid = None
        self.span_hz = 200000.0
        self.pan_follow = False               # False: the picture stays put while you tune inside it; True: it keeps the tuned signal centred
        self.center_nonce = 0                 # the panel's "Centre" button: a newer number means "centre the picture on the tuned frequency now"
        self.full_hz = 0.0                    # the band centre last asked for
        self.diag_t0 = 0.0
        self.diag_done = 0
        self.fcalls = 0
        self.last_good = time.time()          # when frame() last gave a picture
        self.last_call = 0.0                  # when frame() was last asked (the measuring loop asks every round)
        self.why = ""                         # why frame() last gave none
        self.wd_logged = 0.0
        link.apis.append(self)

    def _slice(self, make=False):
        L = self.link
        if L.closed:
            raise FlexError("The connection to the Flex was lost.")
        with L.lock:
            have = sorted(i for i, s in L.slices.items() if "freq_mhz" in s)
        t0 = time.time()
        while not have and time.time() - t0 < 1.0:               # the first news may still be arriving
            time.sleep(0.05)
            with L.lock:
                have = sorted(i for i, s in L.slices.items() if "freq_mhz" in s)
        if self.idx in have:
            return self.idx
        if have and not make:                                    # Follow mode reads a slice somebody else opened
            self.idx = have[0]
            return self.idx
        if have and not L.told_open:
            L.told_open = True
            _log("info", "Flex: slice(s) %s were already open on the radio; Control mode leaves them alone and makes its own slice." % have)
        if not make:
            raise FlexError("No slice is open on the Flex. Follow mode needs a slice that something else (SmartSDR) has open. To run without SmartSDR, set this radio to Control mode in Hardware setup: the program then makes its own slice.")
        if time.time() < L.fail_until:                           # a recent attempt failed: say so again without hammering the radio
            raise FlexError(L.fail_msg)
        with L.mk_lock:
            return self._slice_make_locked(L, have)

    def _slice_make_locked(self, L, have):
        if self.idx is not None and self.idx in L.slices:
            return self.idx
        got = self._adopt_own()                                  # the radio gives every new GUI client a slice of its own (14.1 MHz): use it before asking for more
        if got is not None:
            return got
        if not L.swept:
            L.sweep_orphans()
            with L.lock:
                have = sorted(i for i, s in L.slices.items() if "freq_mhz" in s)
        try:
            return self._make_slice()
        except FlexError as e:
            got = self._adopt_own()
            if got is not None:
                return got
            if L.sweep_orphans() > 0:                            # that freed room: try once more
                try:
                    return self._make_slice()
                except FlexError as e2:
                    e = e2
            msg = str(e)
            if "50000003" in msg or "50000009" in msg or "did not say which slice" in msg or "did not answer" in msg:
                me_h = _hnorm(L.handle) if L.handle else None
                mine = len([i for i in have if i in L.created or (me_h and L.slices.get(i, {}).get('client') == me_h)])
                others = len(have) - mine
                nm = str((self.model or {}).get("name", "") if isinstance(self.model, dict) else self.model or "").upper().replace("FLEX-", "")
                lim = 2 if nm[:4] in ("6100", "6300", "6400") else 4 if nm[:4] in ("6500", "6600", "8400") else 8 if nm[:4] in ("6700", "8600") else 0
                if lim and mine >= 1 and others == 0:
                    msg = ("The FLEX-%s has no room for another slice: it can run only %d slices (receivers) at once, and RFI Trail already has %d open for your other slots, so this slot cannot "
                           "have one. Give the Flex at most %d slots: change this slot's Radio (in its header) to SDRplay, Hermes Lite 2 or RTL-SDR, or to Off. "
                           "The other slots keep running. (%s)" % (nm, lim, mine, lim, e))
                elif lim and others > 0:
                    msg = ("The FLEX-%s has no room for another slice: it can run only %d slices at once and %d are open (%d made by another program, such as SmartSDR, and %d by RFI Trail). "
                           "Close the other program's slices, or give the Flex fewer slots, then press Start again. (%s)" % (nm, lim, len(have), others, mine, e))
                else:
                    msg = ("The Flex has no room for another slice or panadapter (%d slice(s) are open on it). Close slices you are not using "
                           "(in SmartSDR, or by restarting the radio's software), then press Start again. (%s)" % (len(have), e))
            L.fail_msg = msg
            L.fail_until = time.time() + 10.0
            _log("warn", "Flex: " + msg)
            raise FlexError(msg)

    def _adopt_own(self):
        """A real Flex (6300, 2026-11-25) makes a slice on its own for each GUI client that connects. It is listed under OUR handle,
        so it is ours: take one that no other slot is using instead of counting it as 'another program's' and running out of room."""
        L = self.link
        if not L.is_gui or not L.handle:
            return None
        me = _hnorm(L.handle)
        with L.lock:
            used = set(a.idx for a in L.apis if a is not self and a.idx is not None)
            mine = sorted(i for i, s in L.slices.items() if "freq_mhz" in s and s.get("client") == me and i not in used and i not in L.created and str(s.get("pan", "")).startswith("0x") and int(s.get("pan"), 16) != 0)
            if not mine:
                return None
            idx = mine[0]
            pid = L.slices[idx].get("pan", "")
        if idx not in L.created:
            L.created.append(idx)
        self.idx = idx
        if pid.startswith("0x") and int(pid, 16) != 0:
            self.pid = pid
            if pid not in L.made_pans:
                L.made_pans.append(pid)
        _log("info", "Flex: using slice %d that the radio opened for this program (panadapter %s)." % (idx, pid or "none"))
        return idx

    def _make_slice(self):
        L = self.link
        # Make our OWN panadapter first, then the slice on it. (A slice made without one gets pan=0x00000000 on a real
        # Flex: no picture, and every 'display pan set' on it is refused.) The panadapter id comes from the radio's
        # reply to our own command, so we can never pick up somebody else's panadapter by mistake.
        pid = ""
        if L.is_gui:
            try:
                code, pmsg = L.cmd("display panafall create x=800 y=400", timeout=8.0)          # reply: "0x40000005,0x42000005" (panadapter, waterfall)
                for tok in (pmsg or "").replace("|", " ").replace(",", " ").split():
                    if tok.startswith("pan="):
                        pid = tok[4:]
                    elif tok.startswith("0x") and not pid:
                        pid = tok
            except FlexError as e:
                _log("warn", "Flex: the radio would not make a panadapter (%s); trying a slice without one (level reading only)." % e)
        else:
            _log("warn", "Flex: not registered as a GUI client, so no panadapter can be made; making a slice without one (level reading only).")
        if pid and int(pid, 16) == 0:
            pid = ""
        if pid:
            L.made_pans.append(pid)
            self.pid = pid
            try:
                code, msg = L.cmd("slice create pan=%s freq=7.100000 mode=am" % pid, timeout=8.0)
            except FlexError as e:
                _log("warn", "Flex: the slice would not go on our panadapter %s (%s); trying a slice without one." % (pid, e))
                self.pid = None
                code, msg = L.cmd("slice create freq=7.100000 mode=am", timeout=8.0)
        else:
            code, msg = L.cmd("slice create freq=7.100000 mode=am", timeout=8.0)
        try:
            idx = int(msg.strip().split()[0])
        except (ValueError, IndexError):
            raise FlexError("The Flex did not say which slice it made. Open a slice in SmartSDR and use Follow mode instead.")
        L.created.append(idx)
        t0 = time.time()
        while time.time() - t0 < 1.5:
            with L.lock:
                if "freq_mhz" in L.slices.get(idx, {}):
                    break
            time.sleep(0.05)
        self.idx = idx
        if not self.pid:                                         # the radio made a panadapter for the new slice: its status names it
            with L.lock:
                pid = L.slices.get(idx, {}).get("pan", "")
            if pid.startswith("0x") and int(pid, 16) != 0:
                self.pid = pid
                if pid not in L.made_pans:
                    L.made_pans.append(pid)
                _log("info", "Flex: slice %d made, on panadapter %s." % (idx, pid))
        if not self.pid:
            _log("warn", "Flex: slice %d made, but the radio did not say which panadapter it is on, so there will be no spectrum picture." % idx)
        return idx

    def read_freq(self):
        i = self._slice()
        with self.link.lock:
            return float(self.link.slices[i]["freq_mhz"]) * 1e6

    def set_freq(self, hz, dial_hz=None):
        """hz = centre of the band to measure (the picture is centred on it); dial_hz = where the slice itself is tuned (its carrier / dial frequency)."""
        t0 = time.time()
        full_hz = hz
        if dial_hz is not None:
            hz = dial_hz
        self.full_hz = full_hz
        i = self._slice(make=True)
        with self.link.lock:
            cur = self.link.slices.get(i, {}).get("freq_mhz")
            st0 = self.link.pan_set.get(self.pid) if self.pid else None
        if cur is not None and abs(float(cur) * 1e6 - hz) < 1.0 and (not self.pid or (st0 and abs(st0.get("center", -1) - self._pan_target(full_hz)) < 1.0)):
            return                                               # already there: do not retune (a retune blanks the picture for a moment)
        fast = getattr(self, "tune_ok", False)                   # after the first tune the radio has answered, do not wait for each answer: that is what made tuning feel sluggish
        rep = self.link.cmd("slice tune %d %.6f" % (i, hz / 1e6), wait=not fast)
        self.tune_ok = True
        if not self._wait_freq(i, hz, 0.25) and time.time() - getattr(self.link, "tune_told", 0) > 60:      # a short look only: never slow the tuning down
            self.link.tune_told = time.time()
            with self.link.lock:
                now_f = self.link.slices.get(i, {}).get("freq_mhz")
            _log("warn", "Flex: slice %d still reports %s MHz a moment after 'slice tune' to %.6f MHz (the radio answered %r)." % (i, now_f, hz / 1e6, rep))
        self._diag_tune(i, hz)
        t1 = time.time()
        self._pan(full_hz)
        if time.time() - t0 > 1.0:
            _log("warn", "Flex: retuning slice %d to %.4f MHz was slow: %.1f s for the slice, %.1f s for the panadapter." % (i, hz / 1e6, t1 - t0, time.time() - t1))

    def _diag_tune(self, i, hz):
        """For the first 12 tunes: after a moment, say what the radio reports for the slice, and again after asking it to list the slice afresh."""
        if not os.environ.get("NT_FLEX_DIAG"):                       # support checks: off unless asked for
            return
        n = getattr(self.link, "tune_diag", 0)
        if n >= 40:
            return
        self.link.tune_diag = n + 1
        def go():
            try:
                time.sleep(1.0)
                with self.link.lock:
                    f1 = self.link.slices.get(i, {}).get("freq_mhz")
                try:
                    self.link.cmd("sub slice %d" % i, wait=False)
                except Exception:
                    pass
                time.sleep(1.0)
                with self.link.lock:
                    f2 = self.link.slices.get(i, {}).get("freq_mhz")
                with self.link.lock:
                    kv = dict(self.link.slices.get(i, {}).get("kv", {}))
                ex = " ".join("%s=%s" % (k, kv[k]) for k in ("mode", "filter_lo", "filter_hi", "rxant", "agc_mode", "agc_threshold", "audio_mute", "audio_level", "dax", "lock", "squelch", "squelch_level", "nr", "nb", "anf", "rit_on", "xit_on", "step") if k in kv)
                _log("info", "Flex tune check #%d: slice %d asked for %.6f MHz; the radio reports %s after 1 s and %s after asking again. Slice settings: %s" % (n + 1, i, hz / 1e6, f1, f2, ex or "(none reported)"))
            except Exception:
                pass
        threading.Thread(target=go, daemon=True).start()

    def _wait_freq(self, i, hz, t):
        t0 = time.time()
        while True:
            with self.link.lock:
                cur = self.link.slices.get(i, {}).get("freq_mhz")
            if cur is not None and abs(float(cur) * 1e6 - hz) < 1.0:
                return True
            if time.time() - t0 > t:
                return False
            time.sleep(0.03)

    FLEX_MODES = {"AM": "am", "SAM": "sam", "USB": "usb", "LSB": "lsb", "NFM": "nfm", "FM": "fm", "CW": "cw"}
    DEFAULT_FILT = {"AM": 5000, "SAM": 5000, "USB": 2800, "LSB": 2800, "NFM": 12000, "FM": 12000, "CW": 500}

    def set_mode(self, mode, width_hz=0):
        """The slice's mode and receive filter. width_hz 0 = a sensible width for the mode. USB sits above the frequency,
        LSB below it, the others are centred on it."""
        i = self._slice(make=True)
        m = str(mode or "AM").upper()
        self.link.cmd("slice set %d mode=%s" % (i, self.FLEX_MODES.get(m, "am")))
        w = int(width_hz) if width_hz and width_hz > 0 else self.DEFAULT_FILT.get(m, 3000)
        if m == "USB":
            lo, hi = 100, 100 + w
        elif m == "LSB":
            lo, hi = -(100 + w), -100
        else:
            lo, hi = -w // 2, w // 2
        try:
            self.link.cmd("filt %d %d %d" % (i, lo, hi))
        except FlexError as e:
            _log("warn", "Flex: the filter %d to %d Hz was refused (%s)." % (lo, hi, e))
        self.tuned_at = time.time()

    def audio_start(self):
        """Ask the radio for this slice's sound: the slice gets its own DAX channel and we open a DAX audio stream for it.
        Returns the stream id. Safe to call again (it returns the same stream)."""
        L = self.link
        if getattr(self, "audio_sid", None):
            return self.audio_sid
        i = self._slice(make=True)
        ch = L.next_dax
        L.next_dax += 1
        L.cmd("slice set %d dax=%d" % (i, ch))
        if not getattr(self, "radio_muted", False):
            try:
                L.cmd("slice set %d audio_mute=0" % i, timeout=1.5)          # a slice the radio opened itself may start muted
            except FlexError:
                pass
        code, msg = L.cmd("stream create type=dax_rx dax_channel=%d" % ch, timeout=8.0)
        tok = (msg or "").replace("|", " ").replace(",", " ").split()
        sid = None
        for t in tok:
            try:
                sid = int(t, 16) if t.lower().startswith("0x") else int(t, 16)
                break
            except ValueError:
                continue
        if sid is None:
            raise FlexError("The Flex did not say which audio stream it made.")
        with L.lock:
            L.audio[sid] = collections.deque(maxlen=400)
        L.streams.append(sid)
        self.audio_sid = sid
        _log("info", "Flex: sound stream 0x%X for slice %d (DAX channel %d)." % (sid, i, ch))
        return sid

    def set_radio_mute(self, on):
        """Mute (or unmute) the slice at the radio itself, as the slice's speaker button does in SmartSDR. The sound stream to this computer is separate."""
        i = self._slice(make=True)
        self.radio_muted = bool(on)
        self.link.cmd("slice set %d audio_mute=%d" % (i, 1 if on else 0), timeout=3.0)
        return self.radio_muted

    def audio_pull(self):
        """The sound that has arrived since the last call, as one float32 array at 24 kHz (empty if none)."""
        import numpy as np
        sid = getattr(self, "audio_sid", None)
        q = self.link.audio.get(sid) if sid else None
        if not q:
            return np.zeros(0, np.float32)
        out = []
        while q:
            try:
                out.append(q.popleft())
            except IndexError:
                break
        return np.concatenate(out) if out else np.zeros(0, np.float32)

    def _pan_target(self, full_hz):
        """Where the picture should be centred: on the tuned band when 'keep centred' is on, when it was never set, or when the tuned band
        has moved out of the middle 80 % of the picture; otherwise where it already is (so clicking or dragging does not make it scroll)."""
        st = self.link.pan_set.get(self.pid) if self.pid else None
        c = (st or {}).get("center")
        if self.pan_follow or c is None or abs(full_hz - c) > 0.40 * self.span_hz:
            return full_hz
        return c

    def set_pan_mode(self, follow, nonce):
        """The slot's centring choice: follow = keep the tuned signal centred; a newer nonce = centre it once, now."""
        self.pan_follow = bool(follow)
        if nonce and nonce > self.center_nonce:
            self.center_nonce = nonce
            if self.pid and self.full_hz:
                try:
                    self._pan(self.full_hz, force=True)
                except Exception:
                    pass

    def _pan(self, hz, force=False):
        """Our own panadapter (made in Control mode) follows the slot: centre it on the frequency and ask for a spectrum stream."""
        L = self.link
        if not self.pid:
            return
        st = L.pan_set.get(self.pid)
        if not force:
            hz = self._pan_target(hz)
            if st and st.get("center") is not None and abs(st["center"] - hz) < 1.0:
                return                                   # the picture is already where it should be
        try:
            if not st:
                st = {"x": 1024, "y": 700, "min": -140.0, "max": -20.0}
                L.cmd("display pan set %s xpixels=%d ypixels=%d min_dbm=%.1f max_dbm=%.1f"
                      % (self.pid, st["x"], st["y"], st["min"], st["max"]), timeout=1.5)
                L.pan_set[self.pid] = st                  # remembered only once the radio has accepted it
                try:
                    L.cmd("display pan set %s fps=15" % self.pid, timeout=1.5)          # nice to have; the picture works without it
                except FlexError:
                    pass
            self.tuned_at = time.time()                  # the pictures in flight are centred on the old place: skip them for a moment
            L.cmd("display pan set %s center=%.6f bandwidth=%.6f" % (self.pid, hz / 1e6, self.span_hz / 1e6), timeout=1.5, wait=("center" not in st))
            st["center"] = hz
        except FlexError as e:
            _log("warn", "Flex: the panadapter could not be set up (%s). The level reading still works, but there is no spectrum picture." % e)

    def set_span(self, hz):
        """Zoom: ask the radio's own panadapter for a different width (narrower = more detail, like SmartSDR's zoom). Does not wait for the reply."""
        hz = float(min(max(hz, 5000.0), 1600000.0))
        if abs(hz - self.span_hz) < 1.0:
            return
        self.span_hz = hz
        self.tuned_at = time.time()                      # the pictures in flight still have the old width: skip them for a moment
        L = self.link
        st = L.pan_set.get(self.pid) if self.pid else None
        if st and st.get("center"):
            ctr = st["center"]
            if self.full_hz and abs(self.full_hz - ctr) > 0.40 * hz:
                ctr = self.full_hz                       # zooming in would push the tuned signal off the picture: centre on it instead
            try:
                L.cmd("display pan set %s center=%.6f bandwidth=%.6f" % (self.pid, ctr / 1e6, hz / 1e6), timeout=1.5, wait=False)
                st["center"] = ctr
            except FlexError as e:
                _log("warn", "Flex: the zoom could not be set (%s)." % e)

    def frame(self):
        """(centre Hz, span Hz, linear power per bin) of the newest spectrum picture, or None."""
        import numpy as np
        L = self.link
        self.fcalls += 1
        self.last_call = time.time()
        if not self.pid:
            self.why = "no panadapter for this slot"
            return None
        with L.lock:
            f = L.frames.get(self.pid)
            st = L.pan_set.get(self.pid)
        if not f or not st or time.time() - f[0] > 1.5 or "center" not in st or time.time() - self.tuned_at < 0.3:
            self.why = ("no picture yet" if not f else "picture %.1f s old" % (time.time() - f[0]) if time.time() - f[0] > 1.5 else
                        "panadapter not set up" if not st else "centre not set" if "center" not in st else "just retuned")
            self._why_no_frame(st)
            return None
        self.last_good = time.time()
        return (st["center"], self.span_hz, np.power(10.0, f[1] / 10.0))

    def _why_no_frame(self, st):
        """Once, about 8 seconds after the panadapter was set up: say in the log why no picture is arriving."""
        L = self.link
        if self.diag_done >= 3 or not st or "center" not in st:
            return
        if not self.diag_t0:
            self.diag_t0 = time.time()
            return
        if time.time() - self.diag_t0 < (8.0 if self.diag_done == 0 else 30.0 * self.diag_done):
            return
        self.diag_done += 1
        if L.fft_packets == 0:
            _log("warn", "Flex: panadapter %s is set up but no spectrum packets have arrived. A firewall may be blocking UDP from the radio "
                         "(allow Python / RFI Trail for incoming connections), or the radio is not streaming this panadapter." % self.pid)
        elif L.fft_error:
            _log("warn", "Flex: %d spectrum packets arrived but could not be read (%s)." % (L.fft_packets, L.fft_error))
        else:
            with L.lock:
                sl = {i: (v.get("pan"), v.get("client"), v.get("freq_mhz")) for i, v in L.slices.items()}
                _log("warn", "Flex: no fresh picture for our panadapter %s. Packets per panadapter: %s; pictures completed: %s; packet shape (bins, per packet, bytes): %s; "
                             "panadapters known: %s; sizes set: %s; our pans: %s; slices (pan, owner, MHz): %s; connected programs: %s; our handle: %s; "
                             "sound packets per stream: %s." % (self.pid, dict(L.fft_sids), dict(L.fft_done), dict(L.fft_shape), sorted(L.pans),
                             sorted(L.pan_set), list(L.made_pans), sl, sorted(L.clients), L.handle, dict(L.audio_sids)))

    def _meter_id(self, i):
        """The level meter of slice i. The radio can remove and re-make a slice's meters, so of several matches the one with the newest reading wins."""
        best = None; best_t = -1.0
        with self.link.lock:
            for mid, m in self.link.meters.items():
                if m.get("src") == "SLC" and m.get("nam") == "LEVEL" and str(m.get("num")) == str(i):
                    t = (self.link.values.get(mid) or (0, 0.0))[1]
                    if best is None or t > best_t:
                        best, best_t = mid, t
        return best

    def read_meter(self):
        """Signal strength of the slice in dBm; waits for a packet newer than the last tune."""
        i = self._slice()
        t0 = time.time()
        after = max(self.tuned_at + 0.15, t0 - 0.4)          # a reading up to 0.4 s old is fine unless we have just retuned
        while time.time() - t0 < 2.0:
            mid = self._meter_id(i)
            if mid is not None:
                with self.link.lock:
                    v = self.link.values.get(mid)
                if v and v[1] >= after:
                    return v[0]
            time.sleep(0.01)
        if self._meter_id(i) is None:
            raise FlexError("The Flex did not list a signal-level meter for its slice %d." % i)
        L = self.link
        if time.time() - getattr(L, "meter_told", 0) > 60:
            L.meter_told = time.time()
            with L.lock:
                age = {m: round(time.time() - v[1], 1) for m, v in L.values.items()}
                lv = {m: (d.get("src"), d.get("num"), d.get("nam")) for m, d in L.meters.items() if d.get("nam") == "LEVEL"}
            _log("warn", "Flex: no fresh meter reading for slice %s. Level meters: %s; seconds since each meter's last reading: %s; UDP packets so far: spectrum %d, sound %d." % (i, lv, age, L.fft_packets, L.audio_pkts))
        raise FlexError("No meter readings are arriving from the Flex. A firewall may be blocking UDP to this "
                        "computer (allow RFI Trail / Python for incoming connections).")
