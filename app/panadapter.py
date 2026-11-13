"""
Panadapter: a live picture of a band of frequencies (spectrum + waterfall) with a
built-in receiver (AM, USB, LSB, CW, narrow FM) so you can listen to what you see.

It is used from the control panel (rfmap_app.py). It talks to the SDRplay through
SoapySDR, exactly like the logger does, or makes up fake signals in practice mode.

The radio can only do ONE job at a time, so the panel stops the panadapter before
logging starts, and refuses to start it while logging is running.
"""
import base64
import collections
import math
import os
import sys
import threading
import time

import numpy as np

import rfmap_common as C

FFT_N = 4096                    # spectrum resolution (bins across the whole span)
AUDIO_RATE = 62500              # samples per second of the audio sent to the browser
BLOCK_S = 0.04                  # one block of radio samples = 40 ms
SPANS = [250_000, 500_000, 1_000_000, 2_000_000, 4_000_000, 8_000_000]
MODES = ("AM", "USB", "LSB", "CW", "NFM")
DB_LO, DB_HI = -120.0, 0.0      # spectrum is sent as bytes: DB_LO -> 0, DB_HI -> 255
CW_PITCH = 700.0                # the tone you hear in CW mode
AUDIO_NFFT = 1024               # audio spectrum: 0 to AUDIO_RATE/2 in 1024-point FFT
AUDIO_BINS = 128                # we show the lowest 128 bins = 0 to about 7.8 kHz
IDLE_STOP_S = 25                # free the radio if the browser stops asking for frames
HW_BW = [200_000, 300_000, 600_000, 1_536_000, 5_000_000, 6_000_000, 7_000_000, 8_000_000]


def _dbfs_to_byte(db):
    return np.clip((db - DB_LO) * (255.0 / (DB_HI - DB_LO)), 0, 255).astype(np.uint8)


# ----------------------------------------------------------------------------
# Radio sources
# ----------------------------------------------------------------------------
class MockSource:
    """Pretend radio: a handful of fake stations so every control can be tried without hardware."""
    name = "Practice radio (fake signals)"

    STATIONS = [
        # (absolute Hz, kind, amplitude)
        (1_010_000, "AM", 0.05), (1_080_000, "AM", 0.03),
        (3_700_000, "BUZZ", 0.004), (3_850_000, "LSB", 0.02),
        (7_040_000, "CW", 0.02), (7_150_000, "AM", 0.01), (7_200_000, "USB", 0.02),
        (7_255_000, "AM", 0.03), (7_285_000, "USB", 0.012),
        (14_250_000, "USB", 0.02), (14_030_000, "CW", 0.015),
        (28_400_000, "USB", 0.01),
        (127_000_000, "AM", 0.03), (146_520_000, "NFM", 0.04), (146_940_000, "NFM", 0.02),
    ]

    def __init__(self, center, rate, **kw):
        self.center, self.rate = float(center), int(rate)
        self.t = 0.0
        self._next = time.time()
        self.rng = np.random.default_rng(1)

    def set_center(self, hz):
        self.center = float(hz)

    def set_rate(self, rate):
        self.rate = int(rate)
        self._next = time.time()

    def set_gain(self, **kw):
        pass

    def read(self, n):
        fs = self.rate
        self._next += n / fs
        wait = self._next - time.time()
        if wait > 0:
            time.sleep(wait)
        elif wait < -1.0:
            self._next = time.time()
        t = self.t + np.arange(n) / fs
        self.t += n / fs
        x = (self.rng.standard_normal(n) + 1j * self.rng.standard_normal(n)) * 7e-4
        half = fs * 0.48
        for f, kind, amp in self.STATIONS:
            off = f - self.center
            if abs(off) > half:
                continue
            carrier = np.exp(2j * np.pi * off * t)
            if kind == "AM":
                msg = 0.5 * np.sin(2 * np.pi * (400 + 200 * (f % 7)) * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 0.3 * t))
                x += amp * (1 + msg) * carrier
            elif kind in ("USB", "LSB"):
                s = 1 if kind == "USB" else -1
                # a real audio tone at frequency fa above (USB) or below (LSB) the carrier frequency
                sig = np.zeros(n, dtype=np.complex128)
                for k, fa in enumerate((500, 900, 1400, 2000)):
                    env = 0.5 + 0.5 * np.sin(2 * np.pi * (0.7 + 0.3 * k) * t + k)
                    sig += env * np.exp(2j * np.pi * s * fa * t)
                x += amp * 0.5 * sig * carrier
            elif kind == "CW":
                # about 12 words per minute: dit dah dit pause pattern, 0.5 s per cycle
                ph = (t * 2.0) % 2.0
                key = ((ph < 0.1) | ((ph > 0.3) & (ph < 0.6)) | ((ph > 0.8) & (ph < 0.9))).astype(float)
                x += amp * key * carrier
            elif kind == "NFM":
                dev = 3000.0
                x += amp * np.exp(2j * np.pi * off * t + 2j * np.pi * np.cumsum(dev * np.sin(2 * np.pi * 1000 * t)) / fs)
            elif kind == "BUZZ":
                # powerline-style noise: 120 Hz bursts of wideband hash
                bursts = ((t * 120.0) % 1.0 < 0.15).astype(float)
                noise = self.rng.standard_normal(n) + 1j * self.rng.standard_normal(n)
                x += amp * bursts * noise * 6
        return x.astype(np.complex64)

    def close(self):
        pass


class SdrplaySource:
    """Real SDRplay through SoapySDR."""

    def __init__(self, center, rate, auto_gain=True, if_gain=40, rf_state=0, **kw):
        SoapySDR, note = C.find_soapy()
        if SoapySDR is None:
            raise ValueError("The radio library (SoapySDR) is not available. " + str(note) +
                             " Press 'Check setup' for help, or tick Practice mode.")
        from SoapySDR import SOAPY_SDR_RX, SOAPY_SDR_CF32
        self.S, self.RX, self.CF32 = SoapySDR, SOAPY_SDR_RX, SOAPY_SDR_CF32
        devs = SoapySDR.Device.enumerate("driver=sdrplay")
        if not devs:
            raise ValueError("No SDRplay found. Is it plugged in directly, and is another program "
                             "(or a second copy of this one) using it? Press 'Check setup' for help.")
        d0 = dict(devs[0])
        self.name = "SDRplay " + str(d0.get("label", d0.get("serial", "")))
        self.dev = SoapySDR.Device(devs[0])
        self.stream = None
        self.rate = int(rate)
        self.center = float(center)
        self._buf = np.zeros(1, np.complex64)
        self._apply_rate(self.rate)
        try:
            self.dev.setDCOffsetMode(self.RX, 0, True)
        except Exception:
            pass
        self.set_gain(auto_gain=auto_gain, if_gain=if_gain, rf_state=rf_state)
        self.dev.setFrequency(self.RX, 0, self.center)
        self.stream = self.dev.setupStream(self.RX, self.CF32)
        self.dev.activateStream(self.stream)

    def _apply_rate(self, rate):
        self.dev.setSampleRate(self.RX, 0, float(rate))
        for bw in HW_BW:
            if bw >= 0.75 * rate:
                try:
                    self.dev.setBandwidth(self.RX, 0, float(bw))
                except Exception:
                    pass
                break

    def set_center(self, hz):
        self.center = float(hz)
        self.dev.setFrequency(self.RX, 0, self.center)

    def set_rate(self, rate):
        try:
            self.dev.deactivateStream(self.stream)
            self.dev.closeStream(self.stream)
        except Exception:
            pass
        self.rate = int(rate)
        self._apply_rate(self.rate)
        self.dev.setFrequency(self.RX, 0, self.center)
        self.stream = self.dev.setupStream(self.RX, self.CF32)
        self.dev.activateStream(self.stream)

    def set_gain(self, auto_gain=True, if_gain=40, rf_state=0, **kw):
        try:
            self.dev.setGainMode(self.RX, 0, bool(auto_gain))
        except Exception:
            pass
        if not auto_gain:
            for name, val in (("IFGR", if_gain), ("RFGR", rf_state)):
                try:
                    self.dev.setGain(self.RX, 0, name, float(val))
                except Exception:
                    pass

    def read(self, n):
        if self._buf.size != n:
            self._buf = np.zeros(n, np.complex64)
        got, tries = 0, 0
        while got < n:
            sr = self.dev.readStream(self.stream, [self._buf[got:]], n - got, timeoutUs=500_000)
            if sr.ret > 0:
                got += sr.ret
                tries = 0
            else:
                tries += 1
                if tries > 6:
                    raise RuntimeError("The radio stopped sending data (error %s). Was it unplugged?" % sr.ret)
        return self._buf.copy()

    def close(self):
        try:
            self.dev.deactivateStream(self.stream)
            self.dev.closeStream(self.stream)
        except Exception:
            pass
        self.dev = None


# ----------------------------------------------------------------------------
# Receiver (mixer -> decimate -> filter -> demodulate)
# ----------------------------------------------------------------------------
def _half_decimate(x, state):
    """Low-pass with [1 4 6 4 1]/16 and keep every second sample. Block length must be even."""
    xx = np.concatenate((state, x))
    n = xx.size
    y = (xx[0:n - 4] + 4 * xx[1:n - 3] + 6 * xx[2:n - 2] + 4 * xx[3:n - 1] + xx[4:n]) * (1.0 / 16.0)
    return y[::2], xx[-4:]


def _design(mode, bw, block):
    """Channel filter at AUDIO_RATE. Returns (complex taps FFT, ntaps, fft size, shift_hz)."""
    bw = float(max(bw, 50.0))
    shift = 0.0
    if mode in ("AM", "NFM"):
        lo, hi = -bw / 2, bw / 2
    elif mode == "USB":
        lo, hi = 250.0, 250.0 + bw
    elif mode == "LSB":
        lo, hi = -(250.0 + bw), -250.0
    else:                                   # CW: filter around the carrier, then shift to a pitch
        lo, hi = -bw / 2, bw / 2
        shift = CW_PITCH
    cutoff, fc = (hi - lo) / 2.0, (hi + lo) / 2.0
    trans = max(0.3 * bw, 120.0)
    ntaps = int(3.6 * AUDIO_RATE / trans) | 1
    ntaps = min(max(ntaps, 63), 4001)
    n = np.arange(ntaps) - (ntaps - 1) / 2.0
    h = np.kaiser(ntaps, 6.0) * np.sinc(2.0 * cutoff / AUDIO_RATE * n) * (2.0 * cutoff / AUDIO_RATE)
    h = h * np.exp(2j * np.pi * fc * n / AUDIO_RATE)
    m = 1
    while m < block + ntaps:
        m *= 2
    return np.fft.fft(h, m).astype(np.complex64), ntaps, m, shift


class Receiver:
    """Turns a block of radio samples into audio. Keeps its filter memory between blocks."""

    def __init__(self, rate):
        self.set_rate(rate)
        self.mode, self.bw = "AM", 6000.0
        self._design_key = None
        self.mix_phase = 0.0
        self.cw_phase = 0.0
        self.prev_fm = np.complex64(0)
        self.dc = 0.0
        self.agc_gain = 1.0
        self.lvl = 1e-4
        self.smeter = -120.0

    def set_rate(self, rate):
        self.rate = int(rate)
        self.nstages = int(round(math.log2(self.rate / AUDIO_RATE)))
        self.states = [np.zeros(4, np.complex64) for _ in range(self.nstages)]
        self.tail = None
        self._design_key = None

    def process(self, x, off_hz, mode, bw, squelch_db):
        n = x.size
        # 1) shift the wanted signal down to 0 Hz
        w = -2 * np.pi * off_hz / self.rate
        ph = self.mix_phase + w * np.arange(n)
        self.mix_phase = (self.mix_phase + w * n) % (2 * np.pi)
        y = x * np.exp(1j * ph).astype(np.complex64)
        # 2) bring the sample rate down to AUDIO_RATE
        for i in range(self.nstages):
            y, self.states[i] = _half_decimate(y, self.states[i])
        L = y.size
        # 3) sharp channel filter for the chosen mode and bandwidth
        key = (mode, round(float(bw)), L)
        if key != self._design_key:
            self.H, self.ntaps, self.M, self.shift = _design(mode, bw, L)
            self._design_key = key
            self.tail = np.zeros(self.ntaps - 1, np.complex64)
        buf = np.concatenate((self.tail, y))
        yf = np.fft.ifft(np.fft.fft(buf, self.M) * self.H)[self.ntaps - 1: self.ntaps - 1 + L].astype(np.complex64)
        self.tail = buf[-(self.ntaps - 1):]
        # signal strength inside the filter, in dB relative to full scale
        p = float(np.mean(np.abs(yf) ** 2)) + 1e-20
        db = 10.0 * math.log10(p)
        self.smeter = db if self.smeter < -119 else 0.6 * self.smeter + 0.4 * db
        # 4) demodulate
        if mode == "AM":
            a = np.abs(yf)
            m = float(a.mean())
            dc0 = self.dc if self.dc else m
            self.dc = dc0 + 0.25 * (m - dc0)             # follows the carrier level, ramped to avoid clicks
            a = a - np.linspace(dc0, self.dc, L, dtype=np.float32)
        elif mode == "NFM":
            z = np.concatenate(([self.prev_fm], yf))
            self.prev_fm = yf[-1]
            a = np.angle(z[1:] * np.conj(z[:-1])).astype(np.float32)
            a *= AUDIO_RATE / (2 * np.pi * max(bw / 4.0, 1000.0))
        elif mode == "CW":
            wc = 2 * np.pi * self.shift / AUDIO_RATE
            pc = self.cw_phase + wc * np.arange(L)
            self.cw_phase = (self.cw_phase + wc * L) % (2 * np.pi)
            a = (yf * np.exp(1j * pc)).real
        else:                                  # USB / LSB
            a = yf.real
        a = a.astype(np.float32)
        # 5) squelch, then automatic audio level (AGC)
        if squelch_db > -119 and self.smeter < squelch_db:
            self.agc_gain = max(self.agc_gain * 0.9, 1.0)
            return np.zeros(L, np.int16), p
        pk = float(np.max(np.abs(a))) + 1e-9
        self.lvl = max(pk, self.lvl * 0.97)         # fast attack, slow decay
        target = 0.35 / max(self.lvl, 1e-6)
        g1 = min(target, 3e4)
        ramp = np.linspace(self.agc_gain, g1, L, dtype=np.float32)
        self.agc_gain = g1
        out = np.clip(a * ramp, -1.0, 1.0)
        return (out * 32000).astype(np.int16), p


# ----------------------------------------------------------------------------
# The panadapter itself (runs in its own thread)
# ----------------------------------------------------------------------------
DEFAULTS = {"center": 7_150_000.0, "rate": 2_000_000, "tune": 7_150_000.0, "mode": "AM", "bw": 6000.0,
            "squelch": -120.0, "auto_gain": False, "if_gain": 40, "rf_state": 0}


# ----------------------------------------------------------------------------
# Audio recorder: saves what you hear as a small, universal WAV file
# (8,000 samples a second, 8-bit mu-law = about 29 MB per hour, plays in every
# browser, QuickTime, Windows Media Player, VLC, phones...). Good for voice and CW.
# ----------------------------------------------------------------------------
REC_RATE = 8000
REC_MAX_S = 4 * 3600
REC_HEADER = 58


def _ulaw_encode(x):
    x = np.clip(np.round(x), -32767, 32767).astype(np.int32)
    sign = np.where(x < 0, 0x80, 0).astype(np.int32)
    mag = np.minimum(np.abs(x), 32635) + 132
    ex = np.floor(np.log2(mag)).astype(np.int32) - 7
    man = (mag >> (ex + 3)) & 0x0F
    return ((~(sign | (ex << 4) | man)) & 0xFF).astype(np.uint8)


def _ulaw_decode(b):
    b = (~np.asarray(b, np.uint8)).astype(np.int32) & 0xFF
    sign = b & 0x80
    ex = (b >> 4) & 7
    man = b & 15
    mag = (((man << 3) + 0x84) << ex) - 0x84
    return np.where(sign != 0, -mag, mag).astype(np.int32)


class Recorder:
    def __init__(self):
        self.lock = threading.Lock()
        self.f = None
        self.path = ""
        self.t0 = 0.0
        self.n = 0
        taps = 255
        fc = 3600.0 / AUDIO_RATE
        k = np.arange(taps) - (taps - 1) / 2.0
        h = np.sinc(2 * fc * k) * np.kaiser(taps, 8.0)
        self.h = (h / np.sum(h)).astype(np.float32)
        self.step = AUDIO_RATE / float(REC_RATE)

    def active(self):
        return self.f is not None

    def status(self):
        with self.lock:
            if self.f is None:
                return {"on": False}
            return {"on": True, "file": os.path.basename(self.path), "seconds": round(self.n / float(REC_RATE), 1)}

    def start(self, path):
        with self.lock:
            if self.f is not None:
                raise ValueError("Already recording.")
            self.f = open(path, "wb")
            self.path = path
            self.n = 0
            self.t0 = time.time()
            self.tail = np.zeros(len(self.h) - 1, np.float32)
            self.pos = 0.0
            self._header()

    def _header(self):
        n = self.n
        hd = b"RIFF" + (REC_HEADER - 8 + n).to_bytes(4, "little") + b"WAVE"
        hd += b"fmt " + (18).to_bytes(4, "little") + (7).to_bytes(2, "little") + (1).to_bytes(2, "little")
        hd += REC_RATE.to_bytes(4, "little") + REC_RATE.to_bytes(4, "little")
        hd += (1).to_bytes(2, "little") + (8).to_bytes(2, "little") + (0).to_bytes(2, "little")
        hd += b"fact" + (4).to_bytes(4, "little") + n.to_bytes(4, "little")
        hd += b"data" + n.to_bytes(4, "little")
        pos = self.f.tell()
        self.f.seek(0)
        self.f.write(hd)
        self.f.seek(pos)

    def feed(self, audio):
        if self.f is None:
            return
        with self.lock:
            if self.f is None:
                return
            x = np.concatenate((self.tail, audio.astype(np.float32)))
            y = np.convolve(x, self.h, "valid")
            self.tail = x[-(len(self.h) - 1):]
            n = max(0, int(math.ceil((len(y) - 1 - self.pos) / self.step)))
            if n:
                idx = self.pos + np.arange(n) * self.step
                i0 = idx.astype(np.int64)
                fr = (idx - i0).astype(np.float32)
                out = y[i0] * (1 - fr) + y[np.minimum(i0 + 1, len(y) - 1)] * fr
                self.f.write(_ulaw_encode(out).tobytes())
                self.n += n
            self.pos = self.pos + n * self.step - len(y)
            if self.n // REC_RATE != (self.n - n) // REC_RATE:     # keep the header valid about once a second
                self._header()
                self.f.flush()
            if self.n >= REC_MAX_S * REC_RATE:
                self._close()

    def _close(self):
        try:
            self._header()
            self.f.close()
        except Exception:
            pass
        self.f = None

    def stop(self):
        with self.lock:
            if self.f is None:
                return None
            name, secs = os.path.basename(self.path), self.n / float(REC_RATE)
            self._close()
            return {"file": name, "seconds": round(secs, 1)}


REC = Recorder()


class Panadapter:
    def __init__(self):
        self.lock = threading.Lock()
        self.thread = None
        self.src = None
        self.running = False
        self.error = ""
        self.params = dict(DEFAULTS)
        self.practice = False
        self.seq = 0
        self.frame = None
        self.audio = collections.deque(maxlen=40)       # (seq, bytes)
        self.aseq = 0
        self.last_poll = time.time()
        self.name = ""
        self._pending = set()

    # ---- control from the web server
    def start(self, params, practice):
        if self.running:
            self.stop()
        p = dict(DEFAULTS)
        p.update(self._clean(params))
        self.practice = bool(practice)
        self.error = ""
        if practice:
            src = MockSource(p["center"], p["rate"])
        else:
            src = SdrplaySource(p["center"], p["rate"], auto_gain=p["auto_gain"],
                                if_gain=p["if_gain"], rf_state=p["rf_state"])
        with self.lock:
            self.params = p
            self.src = src
            self.name = getattr(src, "name", "")
            self.running = True
            self.seq = 0
            self.aseq = 0
            self.frame = None
            self.audio.clear()
            self._pending = set()
            self.last_poll = time.time()
        self.thread = threading.Thread(target=self._loop, name="panadapter", daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        t = self.thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=4)
        self.thread = None

    def set(self, params):
        c = self._clean(params)
        with self.lock:
            for k, v in c.items():
                if self.params.get(k) != v:
                    self.params[k] = v
                    if k in ("center", "rate", "auto_gain", "if_gain", "rf_state"):
                        self._pending.add(k)

    def _clean(self, b):
        o = {}
        try:
            if "center" in b:
                o["center"] = float(min(max(float(b["center"]), 10_000.0), 2_000_000_000.0))
            if "rate" in b:
                r = int(b["rate"])
                o["rate"] = r if r in SPANS else 2_000_000
            if "tune" in b:
                o["tune"] = float(b["tune"])
            if "mode" in b:
                m = str(b["mode"]).upper()
                if m not in MODES:
                    raise ValueError("Unknown mode.")
                o["mode"] = m
            if "bw" in b:
                o["bw"] = float(min(max(float(b["bw"]), 50.0), 20_000.0))
            if "squelch" in b:
                o["squelch"] = float(min(max(float(b["squelch"]), -120.0), 0.0))
            if "auto_gain" in b:
                o["auto_gain"] = bool(b["auto_gain"])
            if "if_gain" in b:
                o["if_gain"] = int(min(max(int(b["if_gain"]), 20), 59))
            if "rf_state" in b:
                o["rf_state"] = int(min(max(int(b["rf_state"]), 0), 27))
        except (TypeError, ValueError) as e:
            raise ValueError("Bad panadapter setting: %s" % e)
        return o

    # ---- data for the browser
    def get_frame(self, after=-1):
        self.last_poll = time.time()
        with self.lock:
            f = self.frame
            base = {"ok": True, "running": self.running, "error": self.error, "practice": self.practice,
                    "radio": self.name}
            if f is None or f["seq"] == after:
                base["same"] = True
                base["seq"] = after if f is None else f["seq"]
                return base
            out = dict(base)
            out.update(f)
            return out

    def get_audio(self, after=0):
        self.last_poll = time.time()
        with self.lock:
            chunks = [b for s, b in self.audio if s > after]
            last = self.aseq
        chunks = chunks[-15:]                   # never send more than 0.6 s (stay close to live)
        return b"".join(chunks), last

    # ---- the worker
    def _loop(self):
        src = self.src
        rate = self.params["rate"]
        rx = Receiver(rate)
        win = np.hanning(FFT_N).astype(np.float32)
        win_pow = float(np.sum(win ** 2))
        avg = None
        nblock = int(rate * BLOCK_S)
        discard = 2
        awin = np.hanning(AUDIO_NFFT).astype(np.float32)
        abuf = np.zeros(AUDIO_NFFT, np.float32)
        try:
            while self.running:
                if time.time() - self.last_poll > IDLE_STOP_S:
                    break
                with self.lock:
                    p = dict(self.params)
                    pend, self._pending = self._pending, set()
                if "rate" in pend:
                    src.set_rate(p["rate"])
                    rate = p["rate"]
                    rx.set_rate(rate)
                    nblock = int(rate * BLOCK_S)
                    avg = None
                    discard = 3
                if "center" in pend:
                    src.set_center(p["center"])
                    discard = 3
                if pend & {"auto_gain", "if_gain", "rf_state"}:
                    src.set_gain(auto_gain=p["auto_gain"], if_gain=p["if_gain"], rf_state=p["rf_state"])
                x = src.read(nblock)
                if discard > 0:
                    discard -= 1
                    continue
                # ---- spectrum
                nseg = x.size // FFT_N
                step = max(1, nseg // 12)
                segs = x[: nseg * FFT_N].reshape(nseg, FFT_N)[::step] * win
                spec = (np.abs(np.fft.fftshift(np.fft.fft(segs, axis=1), axes=1)) ** 2).mean(axis=0)
                spec = spec / (FFT_N * win_pow)
                avg = spec if avg is None else 0.55 * avg + 0.45 * spec
                db = 10.0 * np.log10(avg + 1e-12)
                # ---- receiver
                off = p["tune"] - p["center"]
                if abs(off) < 0.47 * rate:
                    audio, _pw = rx.process(x, off, p["mode"], p["bw"], p["squelch"])
                else:
                    audio = np.zeros(nblock // (rate // AUDIO_RATE), np.int16)
                    rx.smeter = -120.0
                # ---- audio spectrum (what you hear)
                a = audio.astype(np.float32) / 32000.0
                abuf = np.concatenate((abuf, a))[-AUDIO_NFFT:]
                aspec = np.abs(np.fft.rfft(abuf * awin)) ** 2 / (AUDIO_NFFT * float(np.sum(awin ** 2)))
                adb = 10.0 * np.log10(aspec[:AUDIO_BINS] + 1e-10)
                with self.lock:
                    self.seq += 1
                    self.aseq += 1
                    self.frame = {
                        "seq": self.seq,
                        "center": p["center"], "rate": rate, "tune": p["tune"],
                        "mode": p["mode"], "bw": p["bw"],
                        "db_lo": DB_LO, "db_hi": DB_HI,
                        "spec": base64.b64encode(_dbfs_to_byte(db).tobytes()).decode(),
                        "aspec": base64.b64encode(np.clip((adb + 100) * 2.5, 0, 255).astype(np.uint8).tobytes()).decode(),
                        "smeter": round(float(rx.smeter), 1),
                        "audio_rate": AUDIO_RATE,
                    }
                    self.audio.append((self.aseq, audio.tobytes()))
                REC.feed(audio)
        except Exception as e:
            self.error = "%s: %s" % (type(e).__name__, e)
            print("Panadapter stopped:", self.error, file=sys.stderr)
        finally:
            self.running = False
            REC.stop()
            try:
                src.close()
            except Exception:
                pass
            self.src = None


PAN = Panadapter()
