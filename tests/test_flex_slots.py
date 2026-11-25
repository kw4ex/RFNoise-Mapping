"""Two slots on one Flex in Control mode (added in 0.4.0e): each slot has its own slice and panadapter, nothing is retuned
between pictures, and the loop runs fast. Run:  python3 tests/test_flex_slots.py"""
import os, sys, time
_app = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
sys.path.insert(0, _app); sys.path.insert(0, os.path.join(_app, "radios"))
from radios import cat_sim, cat_engine as E

fx = cat_sim.FakeFlex(slices=2, no_pan_slice=True, gui_pan=True); fx.start()
r = E.CatRadio({"model": "flex6700", "port": "127.0.0.1:%d" % fx.port, "mode": "control"})
freqs = {0: 7.143e6, 1: 7.300e6}

def one_round():
    out = {}
    for slot in (0, 1):
        r.cur = slot
        lv = r.measure(freqs[slot], 5e3, 0, 0, {})
        out[slot] = (lv, r.last_frame())
    return out

for _ in range(30):                       # warm-up: slices made, tuned, first pictures arrive
    res = one_round()
    if all(res[k][1] for k in res):
        break
    time.sleep(0.1)
assert all(res[k][1] for k in res), "a slot has no picture: %s" % res
assert abs(res[0][1][0] - 7.143e6) < 1 and abs(res[1][1][0] - 7.3e6) < 1, "pictures are centred on the wrong frequencies: %s" % [res[k][1][0] for k in res]
tunes0 = sum(1 for l in fx.log if "slice tune" in l)
t0 = time.time(); n = 0
while time.time() - t0 < 3:
    res = one_round(); n += 1
    assert all(res[k][1] for k in res) and all(res[k][0] == res[k][0] for k in res), "a picture or level dropped out"
per_s = n / 3.0
tunes1 = sum(1 for l in fx.log if "slice tune" in l)
assert tunes1 == tunes0, "slots were retuned while running (%d new tunes)" % (tunes1 - tunes0)
assert per_s >= 8, "only %.1f rounds per second" % per_s
print("PASS two slots: own slice + panadapter each, centred on their own frequencies, no retuning, %.0f rounds per second" % per_s)
creates = [l for l in fx.log if "slice create" in l]
assert len(creates) == 2, creates
print("PASS exactly two slices made for two slots")
# a slot's frequency is typed to something new: only that slot is retuned
freqs[1] = 7.200e6
for _ in range(10):
    res = one_round()
    if res[1][1] and abs(res[1][1][0] - 7.200e6) < 1:
        break
    time.sleep(0.1)
assert abs(res[1][1][0] - 7.200e6) < 1 and abs(res[0][1][0] - 7.143e6) < 1, "retune of one slot disturbed the other"
assert sum(1 for l in fx.log if "slice tune" in l) == tunes0 + 1
print("PASS changing one slot's frequency retunes only that slot")
r.close(); fx.stop()
