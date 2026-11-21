"""Clicking on a signal retunes ONE slot and must not restart the radio or disturb the other slot.
Runs the real control panel against a pretend Flex and counts how many times the program connects/registers.
Run: python3 tests/test_click_retune.py"""
import os, sys, json, time, subprocess, tempfile, urllib.request, socket, threading
HERE = os.path.dirname(os.path.abspath(__file__)); APP = os.path.join(HERE, "..", "app")
sys.path.insert(0, APP); sys.path.insert(0, os.path.join(APP, "radios"))
from radios import cat_sim

class Counting(cat_sim.FakeFlex):
    gui_count = 0
    def _cmd(self, line):
        if line.split("|", 1)[-1] == "client gui": self.gui_count += 1
        return cat_sim.FakeFlex._cmd(self, line)

fx = Counting(slices=0, no_pan_slice=True, gui_pan=True); fx.start()
data = tempfile.mkdtemp(prefix="nt_test_")
s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
env = dict(os.environ, NT_DATA=data, PYTHONPATH=APP)
cfg = {"token": "tok", "use_sdrplay": False, "use_cat": True, "use_anan": True, "practice": False,
       "cat_radios": [{"model": "flex6700", "port": "127.0.0.1:%d" % fx.port, "mode": "control"}],
       "channels": [{"mhz": 7.147, "bw_khz": 5, "cal_db": 0, "radio": "cat1", "mode": "LSB"},
                    {"mhz": 7.300, "bw_khz": 5, "cal_db": 0, "radio": "cat1", "mode": "AM"},
                    {"mhz": "", "bw_khz": 5, "cal_db": 0, "radio": "auto"}, {"mhz": 14.2, "bw_khz": 5, "cal_db": 0, "radio": "anan"}]}      # slot 4: an ANAN that is not there (as on the real bench)
os.makedirs(os.path.join(data, "Settings"), exist_ok=True)
for p in (os.path.join(data, "config.json"), os.path.join(data, "Settings", "config.json")):
    json.dump(cfg, open(p, "w"))
proc = subprocess.Popen([sys.executable, os.path.join(APP, "nt_app.py"), "--no-browser", "--port", str(port)], env=env,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=APP)
def call(path, body=None):
    req = urllib.request.Request("http://127.0.0.1:%d%s?t=tok" % (port, path), data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", "X-NT": "1", "Cookie": "nt=tok"})
    return json.loads(urllib.request.urlopen(req, timeout=15).read() or b"{}")
try:
    for _ in range(60):
        try: call("/api/state"); break
        except Exception: time.sleep(0.25)
    else:
        raise SystemExit("the program did not start:\n" + (proc.stdout.read(3000).decode() if proc.poll() is not None else ""))
    call("/api/config", cfg)
    print("start:", call("/api/slices/start", {}))
    for _ in range(160):
        j = call("/api/slices"); fr = j.get("frames") or []
        if len([f for f in fr if f.get("channel") in (0, 1)]) >= 2 and all(f.get("rate", 0) > 0 for f in fr if f.get("channel") in (0, 1)): break
        time.sleep(0.25)
    print("slices on radio:", sorted(fx.slices), "panadapters:", fx.pans, "gui registrations:", fx.gui_count)
    assert len(fx.slices) == 2 and len(fx.pans) == 2, "more slices or panadapters than slots: %s %s" % (sorted(fx.slices), fx.pans)
    print("pictures before click:", [(f.get("channel"), round(f.get("tune", 0) / 1e6, 4), f.get("rate")) for f in j.get("frames", [])])
    g0 = fx.gui_count; slices0 = sorted(fx.slices)
    cfg["channels"][0]["mhz"] = 7.1523                          # a click on a signal in slot 1
    call("/api/config", cfg); r = call("/api/slices/set", {"channels": cfg["channels"]})
    print("set reply:", r)
    time.sleep(3)
    j = call("/api/slices"); fr = {f.get("channel"): f for f in j.get("frames", [])}
    print("pictures after click:", [(k, round(v.get("tune", 0) / 1e6, 4), v.get("rate")) for k, v in sorted(fr.items())])
    assert fx.gui_count == g0, "the radio was restarted by the click (%d new registrations)" % (fx.gui_count - g0)
    assert sorted(fx.slices) == slices0, "slices changed: %s -> %s" % (slices0, sorted(fx.slices))
    assert r.get("restarted") is None
    assert all(fr.get(k, {}).get("rate", 0) > 0 for k in (0, 1)), "a slot lost its picture"
    assert abs(fr[0]["tune"] - 7.1523e6) < 1 and abs(fr[1]["tune"] - 7.3e6) < 1, "the other slot moved"
    print("PASS a click retunes one slot; no restart, the other slot keeps its picture")
finally:
    try: call("/api/quit", {})
    except Exception: pass
    time.sleep(0.5); proc.kill(); fx.stop()
