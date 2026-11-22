"""2.0.0d: phone/tablet access is on by default; the QR box is on the main screen and can be hidden and brought back."""
import os, sys, json, time, subprocess, tempfile, socket, urllib.request
APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
data = tempfile.mkdtemp(); s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
for d in ("Settings", "Maps", "Drives"): os.makedirs(data + "/" + d, exist_ok=True)
# an older install: its saved file says phone_access False (only because that used to be the default)
for p in (data + "/config.json", data + "/Settings/config.json"): json.dump({"token": "tok", "practice": True, "phone_access": False}, open(p, "w"))
env = dict(os.environ, NT_DATA=data, PYTHONPATH=APP, NT_QC_NOPAGE="9999")
pr = subprocess.Popen([sys.executable, APP + "/nt_app.py", "--no-browser", "--port", str(port)], env=env,
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=APP)
from playwright.sync_api import sync_playwright
try:
    time.sleep(4)
    st = json.loads(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:%d/api/state" % port, headers={"X-NT": "1"}), timeout=5).read())
    assert st["cfg"]["phone_access"] is True, "carried over to on"
    assert st["phone_url"].startswith("http://") and "?t=tok" in st["phone_url"] and st["phone_qr"].lstrip().startswith("<svg"), st["phone_url"]
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        pg = b.new_page(viewport={"width": 1400, "height": 900}); errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto("http://127.0.0.1:%d/?t=tok" % port); time.sleep(3)
        vis = lambda i: pg.evaluate("getComputedStyle(document.getElementById('%s')).display" % i)
        assert vis("phoneBox2") == "flex", "QR box shows on the main screen"
        assert pg.evaluate("document.querySelector('#phoneQr2 svg') !== null"), "QR drawn"
        assert vis("bPhone") == "none", "while phone access is on the top button is not needed"
        pg.screenshot(path="/tmp/phone_card.png", clip={"x": 0, "y": 0, "width": 1400, "height": 330})
        pg.click("#phoneBox2 button:has-text('How?')"); time.sleep(0.5)
        assert pg.evaluate("document.getElementById('dlgPhone').open") is True and "Android" in pg.evaluate("document.getElementById('dlgPhone').textContent"), "instructions popup"
        assert pg.evaluate("document.querySelector('#phoneQr3 svg') !== null"), "big QR in the popup"
        pg.screenshot(path="/tmp/phone_popup.png"); pg.click("#dlgPhone button:has-text('Close')"); time.sleep(0.3)
        assert pg.evaluate("document.getElementById('dlgPhone').open") is False
        # closing the box turns phone access off (at once), the top button turns it back on
        pg.click("#phoneBox2 button:has-text('Off')"); time.sleep(2)
        assert vis("phoneBox2") == "none" and vis("bPhone") != "none", "closing the box shows the 'turn on' button"
        st = json.loads(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:%d/api/state" % port, headers={"X-NT": "1"}), timeout=5).read())
        assert st["cfg"]["phone_access"] is False and st["phone_url"] == "", "setting saved as off"
        pg.reload(); time.sleep(3); assert vis("phoneBox2") == "none", "off is remembered"
        pg.click("#bPhone"); time.sleep(2)
        assert vis("phoneBox2") == "flex" and vis("bPhone") == "none", "the top button turns it back on"
        print("PASS phone card; errors:", errs[:2]); assert not errs
    # a phone (not this computer) is refused straight away when access is off, and let in with the key when on
    sys.path.insert(0, APP); os.environ["NT_DATA"] = tempfile.mkdtemp()
    import nt_app as A
    class H:                                          # stands in for one request
        headers = {"Host": "192.168.1.20:8790", "Cookie": ""}; path = "/?t=" + str(A.APP.cfg["token"]); _loopback = lambda self: False
    A.APP.cfg["phone_access"] = True;  assert A.Handler._authorized(H()) is True,  "phone with the key is let in when on"
    H.path = "/?t=wrong"; assert A.Handler._authorized(H()) is False, "wrong key refused"
    H.path = "/?t=" + str(A.APP.cfg["token"]); A.APP.cfg["phone_access"] = False
    assert A.Handler._authorized(H()) is False, "off = refused at once, even with the right key"
    print("PASS refusal when off")
finally:
    pr.terminate()
