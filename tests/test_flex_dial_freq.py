"""The Flex slice is tuned to the DIAL frequency (what the slot shows), not the middle of the measured band; the picture stays centred on the band.
LSB: band lies below the dial, USB: above. Run: python3 tests/test_flex_dial_freq.py"""
import os, sys, time
_app = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
sys.path.insert(0, _app); sys.path.insert(0, os.path.join(_app, "radios"))
from radios import cat_sim, cat_engine as E
for mode, band_c in (("LSB", 7.225e6 - 3000), ("USB", 14.2e6 + 3000)):
    fx = cat_sim.FakeFlex(slices=0, auto_pan=True); fx.start()
    r = E.CatRadio({"model": "flex6700", "port": "127.0.0.1:%d" % fx.port, "mode": "control"})
    r.want_mode = mode; r.want_filt = 0
    dial = 7.225e6 if mode == "LSB" else 14.2e6
    for _ in range(6):
        r.measure(band_c, 6e3, 0, 0, {})
    log = list(fx.log); r.close(); fx.stop()
    tunes = [l for l in log if "slice tune" in l]
    assert any(abs(float(t.split()[-1]) - dial / 1e6) < 1e-6 for t in tunes), (mode, tunes)
    pans = [l for l in log if "center=" in l]
    assert any(abs(float(l.split("center=")[1].split()[0]) - band_c / 1e6) < 1e-6 for l in pans), (mode, pans)
    print("PASS %s: slice on the dial %.4f MHz, picture centred on the band %.4f MHz" % (mode, dial / 1e6, band_c / 1e6))
