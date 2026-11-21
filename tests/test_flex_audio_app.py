"""0.6.0: Flex sound through the real control panel. Run: python3 tests/test_flex_audio_app.py"""
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
    call("/api/slices/start", {})
    for _ in range(120):
        j = call("/api/slices"); fr = j.get("frames") or []
        if len([f for f in fr if f.get("channel") in (0, 1)]) >= 2: break
        time.sleep(0.25)
    r = call("/api/slices/listen", {"channel": 1, "on": True, "mode": "AM"})
    assert r.get("ok"), r
    time.sleep(2.0)
    req = urllib.request.Request("http://127.0.0.1:%d/api/slices/audio?ch=1&after=0&t=tok" % port, headers={"X-NT": "1", "Cookie": "nt=tok"})
    resp = urllib.request.urlopen(req, timeout=10); data = resp.read()
    import numpy as np
    a = np.frombuffer(data, dtype=np.int16).astype(float)
    assert a.size > 3000 and np.abs(a).max() > 3000, "no sound reached the page (%d samples)" % a.size
    assert len(fx.streams) == 1, "only the listened slot should have a sound stream: %s" % fx.streams
    st = call("/api/slices").get("sound", {})
    assert st.get("1", {}).get("listen"), st
    print("PASS Flex slot 2 sound reached the page through the real program (%d samples); slot 1 has no stream" % a.size)
    call("/api/slices/listen", {"channel": 1, "on": False}); time.sleep(0.5)
finally:
    try: call("/api/quit", {})
    except Exception: pass
    time.sleep(0.5); proc.kill(); fx.stop()
