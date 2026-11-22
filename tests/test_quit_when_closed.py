"""2.0.0c: the program closes itself when its browser window is closed (a Settings option, on by default)."""
import json, os, subprocess, sys, tempfile, time, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__)); APP = os.path.join(os.path.dirname(HERE), "app")
sys.path.insert(0, APP)
os.environ.setdefault("NT_DATA", tempfile.mkdtemp())
import nt_app as A

# ---- the rules, with made-up clocks
A.QC_GRACE, A.QC_STALE, A.QC_NOPAGE = 20.0, 300.0, 300.0
A.CLIENTS.clear(); A._CL.update(seen=False, gone_at=0.0)
t0 = 1000.0
assert not A.quit_when_closed_due(t0 + 100, t0, False), "no page yet, still inside the first 5 minutes"
assert A.quit_when_closed_due(t0 + 301, t0, False), "no page ever opened"
A.note_client("pageA"); A.note_client("pageB")
assert not A.quit_when_closed_due(time.time() + 1, t0, False), "pages are open"
A.drop_client("pageA")
assert not A.quit_when_closed_due(time.time() + 1, t0, False), "one page is still open"
A.drop_client("pageB"); gone = A._CL["gone_at"]
assert not A.quit_when_closed_due(gone + 5, t0, False), "a reload must be able to come back"
assert A.quit_when_closed_due(gone + 21, t0, False), "last page closed and grace over"
assert not A.quit_when_closed_due(gone + 99, t0, True), "never while a drive or audio recording is running"
A.note_client("pageC")                                    # a reload brings a new page id
assert not A.quit_when_closed_due(time.time() + 1, t0, False)
assert A.quit_when_closed_due(time.time() + 301 + 20, t0, False), "a page that went silent for 5 minutes is treated as gone"
assert A.APP.cfg.get("quit_when_closed") is True, "on by default"

# ---- a real program: open a page, close it, the program must stop; the setting off must keep it running
def start(port, off=False):
    d = tempfile.mkdtemp(); env = dict(os.environ, NT_DATA=d, NT_QC_GRACE="2", NT_QC_NOPAGE="9999", NT_NO_CLEANUP="1")
    if off:
        os.makedirs(os.path.join(d, "Settings"), exist_ok=True)
        json.dump({"quit_when_closed": False}, open(os.path.join(d, "Settings", "config.json"), "w"))
    p = subprocess.Popen([sys.executable, os.path.join(APP, "nt_app.py"), "--no-browser", "--port", str(port)], env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=APP)
    for _ in range(60):
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/api/ping" % port, timeout=1).read(); return p
        except Exception: time.sleep(0.5)
    p.kill(); raise SystemExit("program did not start")
def call(port, path, cid, post=False):
    rq = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=b"{}" if post else None, method="POST" if post else "GET",
                                headers={"X-NT": "1", "X-NT-Client": cid, "Content-Type": "application/json"})
    return urllib.request.urlopen(rq, timeout=3).read()

p = start(8871)
call(8871, "/api/live", "page1"); time.sleep(4)
assert p.poll() is None, "stayed up while a page is open"
call(8871, "/api/bye", "page1", post=True)
for _ in range(20):
    if p.poll() is not None: break
    time.sleep(1)
assert p.poll() is not None, "program should close after the last page said goodbye"
# reload: goodbye then a new page within the grace time
p = start(8872); call(8872, "/api/live", "x1"); call(8872, "/api/bye", "x1", post=True); time.sleep(0.5); call(8872, "/api/live", "x2"); time.sleep(6)
assert p.poll() is None, "a reload must not close the program"
p.terminate(); p.wait(5)
# setting off
p = start(8873, off=True); call(8873, "/api/live", "y1"); call(8873, "/api/bye", "y1", post=True); time.sleep(8)
assert p.poll() is None, "with the setting off the program keeps running"
p.terminate(); p.wait(5)
print("quit-when-closed tests passed")
