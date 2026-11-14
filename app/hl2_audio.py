"""
hl2_audio.py - sound from the Hermes Lite 2 while it is measuring.

The Hermes Lite 2 streams every receiver all the time, whether anyone listens or not. So while a
drive is being logged, the samples for each of its frequency slots are already arriving; this file
turns them into audio (AM, SAM, USB, LSB, narrow FM) and can record each slot to its own small
WAV file. None of this touches the measurements - it only reads the same stream.

One SliceSound object manages the audio of all slots in one program. Listening streams the sound
to the control panel; recording writes a mono 12,000 samples/second WAV into the Recordings folder.
Several slots can record at the same time; the panel listens to one slot at a time.
"""

import collections
import math
import os
import threading
import time

import numpy as np

AUDIO_RATE = 12000                    # audio samples per second (all Hermes rates divide evenly into it)
MODES = ("AM", "SAM", "USB", "LSB", "NFM")
BW_DEF = {"AM": 8000.0, "SAM": 8000.0, "USB": 2800.0, "LSB": 2800.0, "NFM": 12000.0}
# volume levelling ("AGC"): how fast the volume recovers after a loud peak. Off = a fixed gain, so the
# background noise keeps its true level next to the signals (best for hunting noise).
AGC_DECAY = {"slow": 0.995, "medium": 0.95, "fast": 0.80, "off": None}
AGC_DEF = "medium"
FIXED_GAIN = 400.0                    # AGC off: audio = tanh(sample * this), so loud signals are limited, not clipped
REC_MAX_S = 3600                      # a recording stops itself after an hour (about 83 MB would be 1 h; see below)


def _lp_taps(n, cut_hz, rate):
    k = np.arange(n) - (n - 1) / 2.0
    h = np.sinc(2.0 * cut_hz / rate * k) * np.kaiser(n, 7.0)
    return (h / np.sum(h)).astype(np.complex64)


class WavRecorder:
    """A plain mono 16-bit WAV file at AUDIO_RATE. The header is kept valid as it grows,
    so even a file from a crash or power loss plays."""

    def __init__(self, path):
        self.path = path
        self.n = 0
        self.f = open(path, "wb")
        self._header()

    def _header(self):
        n = self.n * 2
        hd = b"RIFF" + (36 + n).to_bytes(4, "little") + b"WAVE"
        hd += b"fmt " + (16).to_bytes(4, "little") + (1).to_bytes(2, "little") + (1).to_bytes(2, "little")
        hd += AUDIO_RATE.to_bytes(4, "little") + (AUDIO_RATE * 2).to_bytes(4, "little")
        hd += (2).to_bytes(2, "little") + (16).to_bytes(2, "little")
        hd += b"data" + n.to_bytes(4, "little")
        self.f.seek(0)
        self.f.write(hd)
        self.f.seek(44 + n)

    def feed(self, a):                 # a = int16 numpy array
        if self.f is None:
            return
        self.f.write(a.tobytes())
        old = self.n
        self.n += len(a)
        if self.n // AUDIO_RATE != old // AUDIO_RATE:      # refresh the header about once a second
            self._header()
            self.f.flush()

    def seconds(self):
        return self.n / float(AUDIO_RATE)

    def close(self):
        if self.f is None:
            return
        self._header()
        self.f.close()
        self.f = None


class _SliceDemod:
    """Turns one receiver's sample stream into audio. Runs in its own small thread."""

    def __init__(self, client, rx, rate, mode, bw, agc=None):
        self.client, self.rx, self.rate = client, rx, int(rate)
        self.decim = max(1, self.rate // AUDIO_RATE)
        self.agc = AGC_DEF
        self.set_mode(mode, bw, agc)
        self.count = client.count[rx]              # start from "now", not from old samples
        self.tail = np.zeros(0, np.complex64)
        self.phase = 0
        self.car = 0.0 + 0.0j                      # SAM carrier tracker
        self.peak = 1e-3                           # simple volume leveller
        self.dc = 0.0
        self.prev = 0.0 + 0.0j                     # NFM phase memory
        self.audio = collections.deque(maxlen=30)  # (seq, bytes)
        self.aseq = 0
        self.rec = None
        self.lock = threading.Lock()
        self.listen = False
        self.stop_flag = threading.Event()
        self.th = threading.Thread(target=self._loop, daemon=True)
        self.th.start()

    def set_mode(self, mode, bw=None, agc=None):
        if agc in AGC_DECAY:
            self.agc = agc
        mode = mode if mode in MODES else "AM"
        bw = float(bw or BW_DEF[mode])
        bw = min(max(bw, 200.0), min(16000.0, self.rate * 0.8))
        self.mode, self.bw = mode, bw
        cut = min(bw / 2.0 if mode in ("AM", "SAM", "NFM") else bw, AUDIO_RATE * 0.48, self.rate * 0.45)
        self.taps = _lp_taps(161, max(cut, 300.0), self.rate)
        if mode in ("USB", "LSB"):
            # a one-sided filter at the final rate: lowpass moved up (USB) or down (LSB)
            n = np.arange(129)
            centre = (150.0 + bw) / 2.0 * (1 if mode == "USB" else -1)
            half = max((bw - 150.0) / 2.0, 150.0)
            self.taps2 = (_lp_taps(129, half, AUDIO_RATE) * np.exp(2j * np.pi * centre / AUDIO_RATE * n)).astype(np.complex64)
        else:
            self.taps2 = None
        self.tail2 = np.zeros(0, np.complex64)

    def _pull(self):
        c = self.client.count[self.rx]
        n = c - self.count
        if n <= 0:
            return None
        ring = self.client.ring[self.rx]
        if n > ring.size - 8192:                   # fell behind (busy computer): skip ahead
            self.count = c - ring.size // 2
            n = c - self.count
        idx = np.arange(self.count, c) % ring.size
        x = ring[idx].copy()
        self.count = c
        return x

    def _loop(self):
        while not self.stop_flag.is_set():
            time.sleep(0.09)
            try:
                x = self._pull()
                if x is None or x.size < self.decim * 4:
                    continue
                a = self._process(x)
                if a is None or not len(a):
                    continue
                with self.lock:
                    if self.listen:
                        self.aseq += 1
                        self.audio.append((self.aseq, a.tobytes()))
                    if self.rec is not None:
                        self.rec.feed(a)
                        if self.rec.seconds() >= REC_MAX_S:
                            self.rec.close()
                            self.rec = None
            except Exception:
                time.sleep(0.3)

    def _process(self, x):
        # 1. lowpass with memory across blocks, then take every Dth sample
        ntaps = len(self.taps)
        xc = np.concatenate((self.tail, x))
        if xc.size < ntaps:
            self.tail = xc
            return None
        y = np.convolve(xc, self.taps, "valid")
        self.tail = xc[-(ntaps - 1):]
        start = (-self.phase) % self.decim
        y = y[start::self.decim]
        self.phase = (self.phase + (xc.size - ntaps + 1)) % self.decim
        if not y.size:
            return None
        # 2. demodulate at AUDIO_RATE
        m = self.mode
        if m in ("USB", "LSB"):
            n2 = len(self.taps2)
            yc = np.concatenate((self.tail2, y))
            if yc.size < n2:
                self.tail2 = yc
                return None
            z = np.convolve(yc, self.taps2, "valid")
            self.tail2 = yc[-(n2 - 1):]
            a = z.real.astype(np.float32)
        elif m == "NFM":
            yy = np.concatenate(([self.prev], y))
            self.prev = y[-1]
            a = np.angle(yy[1:] * np.conj(yy[:-1])).astype(np.float32) * (1.0 / math.pi)
        elif m == "SAM":
            # follow the carrier with a slow filter, then use it to straighten the signal
            k = math.exp(-2.0 * math.pi * 40.0 / AUDIO_RATE)
            car = np.empty(len(y), np.complex64)
            c = self.car
            for i, v in enumerate(y):
                c = k * c + (1.0 - k) * v
                car[i] = c
            self.car = c
            mag = np.abs(car) + 1e-9
            a = (y * np.conj(car) / mag).real.astype(np.float32)
        else:                                       # AM
            a = np.abs(y).astype(np.float32)
        # 3. remove the slow average (hum/dc), level the volume, make int16
        k = 0.995
        dc = self.dc
        out = np.empty(len(a), np.float32)
        for i, v in enumerate(a):
            dc = k * dc + (1 - k) * v
            out[i] = v - dc
        self.dc = dc
        decay = AGC_DECAY.get(self.agc)
        if decay is None:                           # AGC off: fixed gain, true background level
            return (np.tanh(out * FIXED_GAIN) * 0.8 * 32767.0).astype(np.int16)
        pk = float(np.max(np.abs(out))) if out.size else 0.0
        self.peak = max(self.peak * decay, pk, 1e-4)
        return np.clip(out / self.peak * 0.5 * 32767.0, -32767, 32767).astype(np.int16)

    def get_audio(self, after):
        with self.lock:
            chunks = [b for s, b in self.audio if s > after]
            last = self.aseq
        return b"".join(chunks[-15:]), last

    def close(self):
        self.stop_flag.set()
        self.th.join(timeout=1.0)
        with self.lock:
            if self.rec is not None:
                self.rec.close()
                self.rec = None


class SliceSound:
    """All the slice audio of one program. lookup(ch) must return (client, rx, rate) for a
    Hermes Lite 2 slot, or None for a slot on another radio."""

    def __init__(self):
        self.lookup = None
        self.rec_dir = ""
        self.slices = {}
        self.lock = threading.Lock()

    def attach(self, lookup, rec_dir):
        self.stop_all()
        self.lookup = lookup
        self.rec_dir = rec_dir

    def _get(self, ch, mode=None, bw=None, agc=None):
        with self.lock:
            d = self.slices.get(ch)
            if d is None:
                if self.lookup is None:
                    raise ValueError("The radio is not running.")
                got = self.lookup(ch)
                if not got:
                    raise ValueError("Sound works on the Hermes Lite 2 slots only. This slot is measured by "
                                     "the SDRplay, which cannot stream sound while it is measuring.")
                client, rx, rate = got
                d = _SliceDemod(client, rx, rate, mode or "AM", bw, agc)
                self.slices[ch] = d
        if mode:
            d.set_mode(mode, bw, agc)
        return d

    def listen(self, ch, on, mode=None, bw=None, agc=None):
        if not on:
            with self.lock:
                d = self.slices.get(ch)
                if d:
                    d.listen = False
                    self._reap(ch)
            return
        for k, d in list(self.slices.items()):     # one listener at a time
            if k != ch:
                d.listen = False
                self._reap(k)
        self._get(ch, mode, bw, agc).listen = True

    def set_mode(self, ch, mode, bw=None, agc=None):
        with self.lock:
            d = self.slices.get(ch)
        if d:
            d.set_mode(mode, bw, agc)

    def record(self, ch, on, label="slice", mode=None, bw=None, agc=None):
        if not on:
            with self.lock:
                d = self.slices.get(ch)
                out = ""
                if d and d.rec is not None:
                    out = os.path.basename(d.rec.path)
                    d.rec.close()
                    d.rec = None
                self._reap(ch)
                return out
        d = self._get(ch, mode, bw, agc)
        with d.lock:
            if d.rec is None:
                os.makedirs(self.rec_dir, exist_ok=True)
                name = "%s_%s.wav" % (label, time.strftime("%Y%m%d_%H%M%S"))
                d.rec = WavRecorder(os.path.join(self.rec_dir, name))
        return os.path.basename(d.rec.path)

    def _reap(self, ch):               # inside self.lock: drop a slice nobody uses any more
        d = self.slices.get(ch)
        if d and not d.listen and d.rec is None:
            self.slices.pop(ch, None)
            threading.Thread(target=d.close, daemon=True).start()

    def audio(self, ch, after):
        with self.lock:
            d = self.slices.get(ch)
        if d is None:
            return b"", int(after)
        data, last = d.get_audio(int(after))
        return data, last

    def status(self):
        out = {}
        with self.lock:
            for ch, d in self.slices.items():
                st = {"listen": d.listen, "mode": d.mode, "bw": d.bw, "agc": d.agc}
                if d.rec is not None:
                    st["rec_file"] = os.path.basename(d.rec.path)
                    st["rec_s"] = round(d.rec.seconds(), 1)
                out[str(ch)] = st
        return out

    def stop_all(self):
        with self.lock:
            ds = list(self.slices.values())
            self.slices = {}
        for d in ds:
            d.close()


SND = SliceSound()
