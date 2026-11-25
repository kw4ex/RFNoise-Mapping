"""A real FLEX-6300 (2026-11-25) opens a slice for each GUI client that connects, listed under OUR handle, and its limit is 2.
The program must use those slices as its own instead of calling them 'another program's' and running out of room.
Run:  python3 tests/test_flex_own_default.py"""
import os, sys, time
_app = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
sys.path.insert(0, _app); sys.path.insert(0, os.path.join(_app, "radios"))
from radios import cat_sim, cat_engine as E

fx = cat_sim.FakeFlex(slices=2, max_slices=2, auto_pan=True, freq_mhz=14.1); fx.start()
fx.slice_pan = {0: "0x40000000", 1: "0x40000001"}      # both slices already sit on panadapters, owned by us (default owner 12345678)
r = E.CatRadio({"model": "flex6300", "port": "127.0.0.1:%d" % fx.port, "mode": "control"})
got = None
for _ in range(25):
    lv = r.measure(7.143e6, 5e3, 0, 0, {})
    if lv == lv:
        got = lv; break
    time.sleep(0.2)
tuned = [l for l in fx.log if "slice tune" in l or "RF_frequency" in l]
r.close(); fx.stop()
assert got is not None, "no reading: the slices the radio opened for us were not used"
assert not any("slice create" in l for l in fx.log), "asked for a new slice although two of ours were open: %s" % fx.log
print("PASS own default slices are used (no new slice asked for, no 'no room' error)")
