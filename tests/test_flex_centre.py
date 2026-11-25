"""Flex picture centring: tuning inside the picture leaves it where it is; tuning off the edge, 'Keep centred' or the Centre button move it.
Run: python3 tests/test_flex_centre.py"""
import os, sys, time
_app = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
sys.path.insert(0, _app); sys.path.insert(0, os.path.join(_app, "radios"))
from radios import cat_sim, cat_engine as E
def centers(fx):
    return [float(l.split("center=")[1].split()[0]) for l in fx.log if "center=" in l and "display pan set" in l]
fx = cat_sim.FakeFlex(slices=0, auto_pan=True); fx.start()
r = E.CatRadio({"model": "flex6700", "port": "127.0.0.1:%d" % fx.port, "mode": "control"})
r.want_mode = "AM"; r.want_filt = 0
r.measure(7.225e6, 6e3, 0, 0, {})                      # first tune: picture centred on 7.225
n0 = len(centers(fx)); assert abs(centers(fx)[-1] - 7.225) < 1e-9, centers(fx)
for f in (7.230e6, 7.240e6, 7.215e6):                  # inside the middle 80% of 200 kHz: the picture stays
    r.measure(f, 6e3, 0, 0, {})
assert len(centers(fx)) == n0, ("picture moved while tuning inside it", centers(fx))
r.measure(7.400e6, 6e3, 0, 0, {})                      # off the edge: it re-centres
assert abs(centers(fx)[-1] - 7.4) < 1e-9, centers(fx)
r.measure(7.410e6, 6e3, 0, 0, {})
n1 = len(centers(fx))
r.want_ctr = 5                                         # the Centre button
r.measure(7.410e6, 6e3, 0, 0, {}); time.sleep(0.3)
assert len(centers(fx)) > n1 and abs(centers(fx)[-1] - 7.41) < 1e-9, centers(fx)
r.want_follow = True                                   # Keep centred
r.measure(7.420e6, 6e3, 0, 0, {})
assert abs(centers(fx)[-1] - 7.42) < 1e-9, centers(fx)
r.close(); fx.stop()
print("PASS Flex centring: stays put inside, moves off the edge, Centre button, Keep centred")
