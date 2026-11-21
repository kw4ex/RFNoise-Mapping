"""0.4.0f: a Flex with all 8 slices used up by dead programs. RFI Trail removes the orphans (and only the orphans),
makes its own slices, and a failure is reported once, not hundreds of times.  Run: python3 tests/test_flex_sweep.py"""
import os, sys, time
_app = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
sys.path.insert(0, _app); sys.path.insert(0, os.path.join(_app, "radios"))
from radios import cat_sim, cat_engine as E

def radio(fx):
    return E.CatRadio({"model": "flex6700", "port": "127.0.0.1:%d" % fx.port, "mode": "control"})

def run_slots(r, n=2, secs=3):
    t0 = time.time(); res = None
    while time.time() - t0 < secs:
        res = []
        for k in range(n):
            r.cur = k; lv = r.measure(7.1e6 + k * 1e5, 5e3, 0, 0, {}); res.append((lv, r.last_frame()))
        if all(x[1] for x in res): break
        time.sleep(0.1)
    return res

# 1. five dead slices (owner DEAD0001, not connected) + one slice of SmartSDR (BEEF0002, connected) + two more dead ones = 8 of 8
owners = {i: "DEAD0001" for i in range(8)}; owners[5] = "BEEF0002"
fx = cat_sim.FakeFlex(slices=8, max_slices=8, no_pan_slice=True, gui_pan=True, owners=owners, other_clients=["BEEF0002"]); fx.start()
r = radio(fx); res = run_slots(r)
assert all(x[1] for x in res), "no pictures although the dead slices should have been cleaned: %s" % res
assert 5 in fx.slices and fx.owners.get(5) == "BEEF0002", "a slice that belongs to a connected program was touched"
dead = [i for i in fx.slices if fx.owners.get(i) == "DEAD0001"]
assert not dead, "dead slices still there: %s" % dead
print("PASS dead programs' slices removed, a connected program's slice left alone, our two slices made")
r.close(); fx.stop()

# 2. full of slices that BELONG to connected programs: nothing is removed, one clear message, no flood of commands
owners = {i: "BEEF0002" for i in range(8)}
fx = cat_sim.FakeFlex(slices=8, max_slices=8, no_pan_slice=True, gui_pan=True, owners=owners, other_clients=["BEEF0002"]); fx.start()
r = radio(fx)
t0 = time.time(); n = 0
while time.time() - t0 < 3:
    r.cur = 0; r.measure(7.1e6, 5e3, 0, 0, {}); n += 1; time.sleep(0.01)
assert len(fx.slices) == 8, "something was removed that belongs to a connected program"
creates = [l for l in fx.log if "slice create" in l]
assert len(creates) <= 4, "the radio was hammered with %d slice create commands" % len(creates)
assert "no room" in r.last_error, r.last_error
print("PASS no room: nothing removed, %d create attempts in 3 s, message: %s" % (len(creates), r.last_error[:70]))
r.close(); fx.stop()
