"""2.0.0a: the Settings 'Sound: AGC and volume' section loads, saves on change, and Reset puts the defaults back."""
import os, sys, json, time, subprocess, tempfile, socket
APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app")
data = tempfile.mkdtemp(); s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
for d in ("Settings", "Maps", "Drives"): os.makedirs(data + "/" + d, exist_ok=True)
for p in (data + "/config.json", data + "/Settings/config.json"): json.dump({"token": "tok", "practice": True}, open(p, "w"))
env = dict(os.environ, NT_DATA=data, PYTHONPATH=APP)
pr = subprocess.Popen([sys.executable, APP + "/nt_app.py", "--no-browser", "--port", str(port)], env=env,
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=APP)
from playwright.sync_api import sync_playwright
try:
    time.sleep(4)
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        pg = b.new_page(viewport={"width": 1400, "height": 900}); errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto("http://127.0.0.1:%d/?t=tok" % port); time.sleep(3)
        assert pg.evaluate("document.getElementById('aboutVer').textContent") == "v2.0.0j"
        assert pg.evaluate("document.getElementById('agcOff').value") == "66"
        assert "normal" in pg.evaluate("document.getElementById('agcOffV').textContent")
        pg.evaluate("(()=>{const e=document.getElementById('agcOff'); e.value=78; e.dispatchEvent(new Event('input'));})()")
        pg.evaluate("(()=>{const e=document.getElementById('agcRec'); e.value=2; e.dispatchEvent(new Event('input'));})()")
        assert pg.evaluate("document.getElementById('audioMsg').textContent") == "Saving..."
        time.sleep(1.5)
        assert "Saved" in pg.evaluate("document.getElementById('audioMsg').textContent")
        f = json.load(open(data + "/Settings/audio_tune.json"))
        assert f["agc_off_db"] == 78 and f["agc_recovery"] == 2, f
        pg.screenshot(path="/tmp/audio_ui.png", clip={"x": 0, "y": 0, "width": 1400, "height": 900}, full_page=False)
        pg.evaluate("audioReset()"); time.sleep(1.2)
        f = json.load(open(data + "/Settings/audio_tune.json"))
        assert f == {"agc_off_db": 66.0, "agc_strength_db": 0.0, "agc_recovery": 1.0}, f
        assert "defaults are back" in pg.evaluate("document.getElementById('audioMsg').textContent")
        print("PASS sound settings load, save and reset; errors:", errs[:2]); assert not errs
finally:
    pr.terminate()
