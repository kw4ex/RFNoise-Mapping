"""2.0.0a: a slot that cannot be used (148 MHz on the ANAN) must not move the later slots. Plain script."""
import os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "app"))
os.environ.setdefault("HOME", tempfile.mkdtemp())
import nt_logger as RL
import nt_app

chans = [{"mhz": "3.7", "radio": "anan"}, {"mhz": "7.3", "radio": "anan"},
         {"mhz": "148", "radio": "anan"}, {"mhz": "7.2", "radio": "anan", "mode": "LSB"}]
app = nt_app.APP
app.cfg["use_anan"] = True
app.cfg["use_sdrplay"] = False
out = app.clean_channels(chans, practice=False, for_slices=True)
slots = [c["slot"] for c in out]
assert slots == [1, 2, 4], slots
assert 3 in app.slot_warn and "ANAN" in app.slot_warn[3], app.slot_warn
assert [RL.slot_idx(c, k) for k, c in enumerate(out)] == [0, 1, 3]
assert RL.pos_of_slot(out, 3) == 2 and RL.pos_of_slot(out, 2) == -1 and RL.pos_of_slot(out, 0) == 0
import numpy as np
with RL.PAN_FRAME["lock"]:
    RL.PAN_FRAME["all"] = {}
for k, c in enumerate(out):
    RL.publish_spectrum(7.2e6, 192000, np.ones(64), c["mhz"] * 1e6, 5e3, -50.0, RL.slot_idx(c, k), "anan")
got = {i: round(f["tune"] / 1e6, 3) for i, f in RL.PAN_FRAME["all"].items()}
assert got == {0: 3.7, 1: 7.3, 3: 7.2}, got
print("slot numbers OK")
