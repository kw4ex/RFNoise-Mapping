"""Flex zoom: a slot's panadapter width (span_khz) is sent to the radio as 'display pan set ... bandwidth=', and clamped.
Run: python3 tests/test_flex_zoom.py"""
import os, sys, time
_app = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
sys.path.insert(0, _app); sys.path.insert(0, os.path.join(_app, "radios"))
from radios import cat_sim, cat_engine as E
fx = cat_sim.FakeFlex(slices=0, auto_pan=True); fx.start()
r = E.CatRadio({"model": "flex6700", "port": "127.0.0.1:%d" % fx.port, "mode": "control"})
r.want_mode = "AM"; r.want_filt = 0
for k in range(3):
    r.measure(7.225e6, 6e3, 0, 0, {})
r.want_span = 25.0                      # zoom in to 25 kHz
for k in range(4):
    r.measure(7.225e6, 6e3, 0, 0, {})
time.sleep(0.5)
r.want_span = 5000.0                    # far too wide: the program asks for at most 1.6 MHz
for k in range(3):
    r.measure(7.225e6, 6e3, 0, 0, {})
time.sleep(0.5)
log = list(fx.log); r.close(); fx.stop()
bws = [float(l.split("bandwidth=")[1].split()[0]) for l in log if "bandwidth=" in l]
assert any(abs(b - 0.025) < 1e-9 for b in bws), bws
assert any(abs(b - 1.6) < 1e-9 for b in bws) and max(bws) <= 1.6 + 1e-9, bws
print("PASS Flex zoom: 25 kHz and the 1.6 MHz limit reach the radio", bws[-4:])
