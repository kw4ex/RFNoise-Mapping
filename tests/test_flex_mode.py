"""0.5.0: a Flex slot's mode and receive-filter width go to the radio (slice mode + filt), once, and again only when changed.
Run: python3 tests/test_flex_mode.py"""
import os, sys, time
_app = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
sys.path.insert(0, _app); sys.path.insert(0, os.path.join(_app, "radios"))
from radios import cat_sim, cat_engine as E

fx = cat_sim.FakeFlex(slices=0, no_pan_slice=True, gui_pan=True, other_clients=[]); fx.start()
r = E.CatRadio({"model": "flex6700", "port": "127.0.0.1:%d" % fx.port, "mode": "control"})
def go(mode, filt, k=0, f=7.147e6):
    r.cur = k; r.want_mode = mode; r.want_filt = filt
    return r.measure(f, 2.4e3, 0, 0, {})
def cmds(pat): return [l.split("|", 1)[1] for l in fx.log if pat in l]
go("LSB", 2400)
assert any(c.endswith("mode=lsb") for c in cmds("slice set")), cmds("slice set")
assert any(c.split()[0] == "filt" and c.split()[2:] == ["-2500", "-100"] for c in cmds("filt")), cmds("filt")
print("PASS LSB 2.4 kHz -> mode=lsb, filter -2500..-100")
n = len(cmds("filt")); go("LSB", 2400); go("LSB", 2400)
assert len(cmds("filt")) == n, "the same mode/filter was sent again"
print("PASS unchanged mode and filter are not sent again")
go("USB", 0)
assert any(c.endswith("mode=usb") for c in cmds("slice set"))
assert any(c.split()[0] == "filt" and c.split()[2:] == ["100", "2900"] for c in cmds("filt")), cmds("filt")
go("AM", 6000)
assert any(c.split()[0] == "filt" and c.split()[2:] == ["-3000", "3000"] for c in cmds("filt")), cmds("filt")
print("PASS USB automatic width and AM 6 kHz are right")
r.close(); fx.stop()
