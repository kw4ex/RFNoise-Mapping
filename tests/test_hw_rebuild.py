"""0.7.0: 'Scan and set up for me' drops radios that are not there, keeps the one that answers, renames slot references, unticks absent types.
Run: python3 tests/test_hw_rebuild.py"""
import os, sys, json, time, subprocess, tempfile, urllib.request, socket
HERE = os.path.dirname(os.path.abspath(__file__)); APP = os.path.join(HERE, "..", "app")
sys.path.insert(0, APP); sys.path.insert(0, os.path.join(APP, "radios"))
from radios import cat_sim
fx = cat_sim.FakeFlex(slices=0, no_pan_slice=True, gui_pan=True); fx.start()
data = tempfile.mkdtemp(prefix="nt_test_")
s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
env = dict(os.environ, NT_DATA=data, PYTHONPATH=APP)
cfg = {"token": "tok", "use_sdrplay": True, "use_cat": True, "use_anan": True, "use_hl2": False, "practice": False,
       "cat_radios": [{"model": "ic7300", "port": "/dev/cu.usbserial-NOPE1", "baud": 19200, "mode": "follow"},
                      {"model": "ic7300", "port": "", "baud": 19200, "mode": "follow"},
                      {"model": "flex6700", "port": "127.0.0.1:%d" % fx.port, "mode": "control"}],
       "channels": [{"mhz": 3.85, "bw_khz": 5, "cal_db": 0, "radio": "cat3", "mode": "LSB"},
                    {"mhz": 7.147, "bw_khz": 5, "cal_db": 0, "radio": "cat1", "mode": "LSB"},
                    {"mhz": 14.2, "bw_khz": 5, "cal_db": 0, "radio": "anan"}, {"mhz": "", "bw_khz": 5, "cal_db": 0, "radio": "auto"}]}
os.makedirs(os.path.join(data, "Settings"), exist_ok=True)
for p in (os.path.join(data, "config.json"), os.path.join(data, "Settings", "config.json")):
    json.dump(cfg, open(p, "w"))
proc = subprocess.Popen([sys.executable, os.path.join(APP, "nt_app.py"), "--no-browser", "--port", str(port)], env=env,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=APP)
def call(path, body=None, t=60):
    req = urllib.request.Request("http://127.0.0.1:%d%s?t=tok" % (port, path), data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", "X-NT": "1", "Cookie": "nt=tok"})
    return json.loads(urllib.request.urlopen(req, timeout=t).read() or b"{}")
try:
    for _ in range(60):
        try: call("/api/state"); break
        except Exception: time.sleep(0.25)
    else:
        raise SystemExit("the program did not start")
    r = call("/api/hardware/rebuild", {}, t=90)
    assert r.get("ok"), r
    for l in r["summary"]: print("  ", l)
    c = json.load(open(os.path.join(data, "Settings", "config.json")))
    assert [e["model"] for e in c["cat_radios"]] == ["flex6700"], c["cat_radios"]
    assert [ch["radio"] for ch in c["channels"]][:2] == ["cat1", "auto"], [ch["radio"] for ch in c["channels"]]
    assert c["channels"][2]["radio"] == "auto" and c["use_anan"] is False and c["use_sdrplay"] is False, c
    print("PASS two absent IC-7300 cards removed, the Flex kept and renamed cat1, its slot re-pointed, the dead ANAN slot set to auto, absent types unticked")
finally:
    try: call("/api/quit", {})
    except Exception: pass
    time.sleep(0.5); proc.kill(); fx.stop()
