"""0.6.0: Flex sound. A listened slot gets its own DAX stream, the tone arrives at the panel's 12 kHz rate, recording writes a WAV,
the other slot has no stream until asked, and everything is removed on close. Run: python3 tests/test_flex_audio.py"""
import os, sys, time, glob, tempfile, wave
import numpy as np
_app = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
sys.path.insert(0, _app); sys.path.insert(0, os.path.join(_app, "radios"))
from radios import cat_sim, cat_engine as E
import hl2_audio

fx = cat_sim.FakeFlex(slices=0, no_pan_slice=True, gui_pan=True); fx.start()
r = E.CatRadio({"model": "flex6700", "port": "127.0.0.1:%d" % fx.port, "mode": "control"})
for slot in (1, 2):
    r.cur = slot; r.want_mode = "AM"; r.want_filt = 0
    r.measure(7.1e6 + slot * 1e5, 5e3, 0, 0, {})
rec = tempfile.mkdtemp()
snd = hl2_audio.SliceSound()
class FakeSdr: pass
snd.attach(lambda ch: ("flex", r.audio_for(ch + 1)) if r.audio_for(ch + 1) else None, rec)
assert not fx.streams, "a stream was opened before anyone listened"
snd.listen(0, True)
time.sleep(1.5)
assert len(fx.streams) == 1, fx.streams
data, last = snd.audio(0, 0)
a = np.frombuffer(data, dtype=np.int16).astype(np.float32)
assert a.size > 3000, "only %d samples of sound arrived" % a.size
zc = np.sum(np.diff((a > 0).astype(np.int8)) != 0) / 2.0
hz = zc / (a.size / float(hl2_audio.AUDIO_RATE))
assert 900 < hz < 1100, "the tone came out at %.0f Hz instead of 1000" % hz
assert np.abs(a).max() > 5000, "the sound is far too quiet"
print("PASS slot 1 listened: own stream, %d samples, tone %.0f Hz at %d Hz sample rate" % (a.size, hz, hl2_audio.AUDIO_RATE))
snd.record(1, True, "flex_test")
time.sleep(1.2)
name = snd.record(1, False)
w = wave.open(os.path.join(rec, name)); assert w.getframerate() == hl2_audio.AUDIO_RATE and w.getnframes() > 5000; w.close()
print("PASS slot 2 recorded to a WAV (%s)" % name)
assert len(fx.streams) == 2
snd.stop_all(); r.close(); time.sleep(0.3)
assert not fx.streams, "streams left on the radio: %s" % fx.streams
print("PASS streams removed from the radio on close")
fx.stop()
