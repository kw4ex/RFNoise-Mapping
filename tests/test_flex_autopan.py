"""A real Flex makes its own panadapter when a slice is created, and only tells a client that asked with 'sub pan all'.
Control mode must then draw a real spectrum picture (added in 0.4.0a). Run:  python3 tests/test_flex_autopan.py"""
import os, sys, time
_app = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
sys.path.insert(0, _app); sys.path.insert(0, os.path.join(_app, "radios"))
from radios import cat_sim, cat_engine as E

def run(auto_pan, slices=0, need_pan=False, no_pan_slice=False, gui_pan=False, mode="control"):
    fx = cat_sim.FakeFlex(slices=slices, auto_pan=auto_pan, need_pan=need_pan, no_pan_slice=no_pan_slice, gui_pan=gui_pan); fx.start()
    r = E.CatRadio({"model": "flex6700", "port": "127.0.0.1:%d" % fx.port, "mode": mode})
    lv = fr = None
    t0 = time.time()
    while time.time() - t0 < 6:
        lv = r.measure(7.147e6, 5e3, 0, 0, {})
        fr = r.last_frame()
        if fr:
            break
        time.sleep(0.2)
    log = list(fx.log); slices0 = dict(fx.slices)
    r.close(); fx.stop()
    return lv, fr, log, slices0

def main():
    lv, fr, log, sl = run(auto_pan=True)
    assert lv == lv, "no level reading"
    assert fr, "no spectrum picture although the radio made a panadapter for our slice"
    centre, span, power = fr[0], fr[1], fr[2]
    assert abs(centre - 7.147e6) < 1, centre
    assert len(power) == 1024, len(power)
    assert any("sub pan all" in l for l in log), "never asked for panadapter news"
    print("PASS auto-pan radio: spectrum picture arrived (%d bins, centre %.4f MHz)" % (len(power), centre / 1e6))
    lv, fr, log, sl = run(auto_pan=False, need_pan=True)        # the older kind of radio (needs 'panafall create') still works
    assert fr, "older radio: no picture"
    print("PASS older radio: spectrum picture arrived")
    lv, fr, log, sl = run(auto_pan=True, slices=1)          # a slice somebody else already opened: leave it alone, make our own
    assert lv == lv and fr, "existing slice: no picture from our own slice"
    assert sl.get(0) == 7.1, "the slice that was already open was retuned: %s" % sl
    print("PASS existing slice: left alone (still 7.1 MHz), own slice and spectrum picture made")
    lv, fr, log, sl = run(auto_pan=False, slices=2, no_pan_slice=True)   # your real Flex 6700: slices 0 and 1 open, 'slice create' alone gives pan=0x00000000
    assert lv == lv and fr, "real-Flex behaviour: no picture"
    assert sl.get(0) == 7.1 and sl.get(1) == 7.1, "slices that were already open were touched: %s" % sl
    assert not any(l.split("|", 1)[1].startswith("display pan set 0x00000000") for l in log), "tried to set up the empty panadapter"
    print("PASS real-Flex behaviour (slices 0 and 1 open, slice made without a pan gets 0x0): own panadapter first, picture arrived")
    lv, fr, log, sl = run(auto_pan=False, slices=5, no_pan_slice=True, gui_pan=True)   # your real Flex 6700 as probed: GUI client needed, comma reply, slices 0-4 present
    assert lv == lv and fr, "probe-proven behaviour: no picture"
    assert any(l.split("|", 1)[1] == "client gui" for l in log), "never registered as a GUI client"
    assert all(sl.get(i) == 7.1 for i in range(5)), "slices that were already open were touched: %s" % sl
    print("PASS probe-proven Flex behaviour: GUI client, own panadapter from a comma reply, picture arrived, other slices untouched")
    lv, fr, log, sl = run(auto_pan=False, slices=1, gui_pan=True, mode="follow")        # Follow mode must never register as GUI or make anything
    assert not any("client gui" in l or "slice create" in l or "panafall" in l for l in log), "Follow mode changed the radio: %s" % log
    print("PASS Follow mode reads only (no client gui, no slice, no panadapter)")

main()
