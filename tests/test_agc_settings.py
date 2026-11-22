"""2.0.0a: the sound settings (AGC-off volume, AGC strength, AGC recovery speed). Plain script."""
import os, sys, tempfile, threading, collections
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "app"))
home = tempfile.mkdtemp()
os.environ["HOME"] = home
os.environ["USERPROFILE"] = home
import numpy as np
import nt_common as C
import hl2_audio as A

# defaults, clamping, saving
assert C.audio_tune()["agc_off_db"] == 66.0
v = C.audio_tune_save({"agc_off_db": 500, "agc_strength_db": -3, "agc_recovery": 99})
assert v == {"agc_off_db": 90.0, "agc_strength_db": 0.0, "agc_recovery": 4.0}, v
assert C.audio_tune_save({})["agc_off_db"] == 66.0


def demod(agc):
    d = A._SliceDemod.__new__(A._SliceDemod)
    d.rate = 96000; d.decim = 8; d.agc = agc
    d.set_mode("AM", 8000, agc)
    d.tail = np.zeros(0, np.complex64); d.phase = 0; d.car = 0j
    d.peak = 1e-3; d.hang = 0.0; d.dc = 0.0; d.prev = 0j
    return d


def run(agc, blocks):
    d = demod(agc); outs = []
    for amp in blocks:
        n = 96000 // 25
        t = np.arange(n) / 96000.0
        x = (amp * (1 + 0.5 * np.sin(2 * np.pi * 400 * t))).astype(np.complex64)
        o = d._process(x)
        outs.append(np.zeros(1) if o is None else o.astype(np.float32))
    return outs


def level(o):
    return float(np.sqrt(np.mean(np.concatenate(o) ** 2)))


quiet = [1e-4] * 30
# AGC off: raising the volume setting makes it louder
C.audio_tune_save({"agc_off_db": 60}); lo = level(run("off", quiet)[10:])
C.audio_tune_save({"agc_off_db": 72}); hi = level(run("off", quiet)[10:])
assert hi > lo * 1.5, (lo, hi)
# recovery speed: after a burst, a faster recovery brings the volume back sooner
burst = [1e-4] * 6 + [1e-1] * 2 + [1e-4] * 40


def after(rec):
    C.audio_tune_save({"agc_recovery": rec}); o = run("medium", burst)
    return level(o[12:30])


slow, fast = after(0.5), after(4.0)
assert fast > slow, (slow, fast)
# strength: a weaker setting (1 dB) dips less than a strong one (12 dB) right after a burst
def dip(db):
    C.audio_tune_save({"agc_strength_db": db}); o = run("medium", [1e-4] * 6 + [1e-1] * 2 + [1e-4] * 6)
    return level(o[9:14])
assert dip(1.0) >= dip(12.0) * 0.99, (dip(1.0), dip(12.0))
C.audio_tune_save({})
print("agc settings OK", round(lo, 1), round(hi, 1), round(slow, 1), round(fast, 1))
