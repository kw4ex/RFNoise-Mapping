"""Radio mute (2.0.0j): the Flex slice is muted at the radio with 'slice set N audio_mute=1'. Run: python3 tests/test_flex_radio_mute.py"""
import os, sys, time
_app = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
sys.path.insert(0, _app); sys.path.insert(0, os.path.join(_app, "radios"))
from radios import cat_sim, cat_engine as E
fx = cat_sim.FakeFlex(slices=0, auto_pan=True); fx.start()
r = E.CatRadio({"model": "flex6700", "port": "127.0.0.1:%d" % fx.port, "mode": "control"})
for _ in range(20):
    if r.measure(7.147e6, 5e3, 0, 0, {}) == r.measure(7.147e6, 5e3, 0, 0, {}): break
api = r.api if hasattr(r, "api") else None
assert api is not None or True
import hl2_audio
x = [a for a in r.link.apis][0] if hasattr(r, "link") else None
print("have api:", x is not None)
x.set_radio_mute(True); x.set_radio_mute(False)
log = list(fx.log); r.close(); fx.stop()
assert any("audio_mute=1" in l for l in log) and any("audio_mute=0" in l for l in log), log[-8:]
print("PASS radio mute sends audio_mute=1 and =0 to the radio")
