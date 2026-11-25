"""'Mute radio speaker' (2.0.0j): the setting file makes the Flex link send mixer mute commands, independent of the computer's sound.
Run: python3 tests/test_flex_jacks_mute.py"""
import os, sys, time, json, tempfile
d = tempfile.mkdtemp(); os.environ["NT_DATA"] = d
_app = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
sys.path.insert(0, _app); sys.path.insert(0, os.path.join(_app, "radios"))
from radios import cat_sim, cat_engine as E
import nt_common
fx = cat_sim.FakeFlex(slices=0, auto_pan=True); fx.start()
r = E.CatRadio({"model": "flex6700", "port": "127.0.0.1:%d" % fx.port, "mode": "control"})
r.measure(7.147e6, 5e3, 0, 0, {})
os.makedirs(nt_common.sub_dir("Settings"), exist_ok=True)
json.dump({"mute": True}, open(os.path.join(nt_common.sub_dir("Settings"), "flex_jacks_mute.json"), "w"))
t0 = time.time()
while time.time() - t0 < 6 and not (any("mixer lineout mute 1" in l for l in fx.log) and any("mixer headphone mute 1" in l for l in fx.log)):
    time.sleep(0.2)
log = list(fx.log); r.close(); fx.stop()
assert any("mixer lineout mute 1" in l for l in log) and any("mixer headphone mute 1" in l for l in log), log[-6:]
print("PASS radio speaker mute sends the mixer mute commands")
