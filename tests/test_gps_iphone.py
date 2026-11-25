"""GPS2IP (iPhone) test: find_iphone() reads a pretend GPS2IP server and explains the result; a closed port gives plain advice; the button exists.
Run: python3 tests/test_gps_iphone.py"""
import os, sys, socket, threading, time
_app = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
sys.path.insert(0, _app)
import gps_detect as G
def mk(s):
    cs = 0
    for ch in s: cs ^= ord(ch)
    return "$%s*%02X\r\n" % (s, cs)
srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(5); port = srv.getsockname()[1]
mode = {"nofix": False, "silent": False}
def serve():
    while True:
        try: c, _ = srv.accept()
        except OSError: return
        for i in range(14):
            if mode["silent"]: time.sleep(0.3); continue
            a = "V" if mode["nofix"] else "A"
            c.sendall(mk("GPRMC,123519,%s,3519.000,N,08312.000,W,5.0,84.4,230394,003.1,W" % a).encode())
            c.sendall(mk("GPGGA,123519,3519.000,N,08312.000,W,%d,08,0.9,545.4,M,46.9,M,," % (0 if mode["nofix"] else 1)).encode()); time.sleep(0.3)
        c.close()
threading.Thread(target=serve, daemon=True).start()
r = G.find_iphone("127.0.0.1", port, scan=False)
assert r["ok"] and r["host"] == "127.0.0.1" and r["sats"] == 8 and r["fix"] and abs(r["lat"] - 35.3167) < 0.001 and "RMC" in r["types"], r
assert "Position fix OK" in r["summary"] and "8 satellites" in r["summary"], r["summary"]
mode["nofix"] = True
r = G.find_iphone("127.0.0.1", port, scan=False)
assert r["ok"] and r["problem"] and "no position fix yet" in r["summary"], r["summary"]
mode["nofix"] = False; mode["silent"] = True
r = G.find_iphone("127.0.0.1", port, scan=False)
assert not r["ok"] and "no GPS lines arrived" in r["summary"] and "RMC" in r["summary"], r["summary"]
html = open(os.path.join(_app, "panel.html"), encoding="utf-8").read()
assert 'id="btnFindIph"' in html and "/api/gps_iphone" in html
assert G._local_ips() is not None
print("PASS GPS2IP: good link described, no-fix and silent link explained, button present")
