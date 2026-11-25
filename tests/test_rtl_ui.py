"""Hardware setup shows 'Check my dongle' and 'Install the RTL-SDR drivers' and renders the answer."""
import os, sys, json, time, subprocess, tempfile, socket
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); APP=os.path.join(ROOT,"app")
data=tempfile.mkdtemp(); s=socket.socket(); s.bind(("127.0.0.1",0)); port=s.getsockname()[1]; s.close()
os.makedirs(data+"/Settings",exist_ok=True)
for p in (data+"/config.json",data+"/Settings/config.json"): json.dump({"token":"tok","practice":True}, open(p,"w"))
pr=subprocess.Popen([sys.executable, APP+"/nt_app.py","--no-browser","--port",str(port)], env=dict(os.environ,NT_DATA=data,PYTHONPATH=APP), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=APP)
from playwright.sync_api import sync_playwright
try:
    time.sleep(4)
    with sync_playwright() as pw:
        b=pw.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"]); pg=b.new_page(viewport={"width":1300,"height":900}); errs=[]; pg.on("pageerror",lambda e:errs.append(str(e)))
        pg.goto("http://127.0.0.1:%d/?t=tok"%port); pg.wait_for_timeout(2500)
        pg.evaluate("hwOpen(); 0"); pg.wait_for_timeout(800)
        assert pg.evaluate("!!document.getElementById('btnRtl') && !!document.getElementById('btnRtlInst')")
        pg.evaluate("document.getElementById('btnRtl').click(); 0"); pg.wait_for_timeout(12000)
        txt=pg.evaluate("document.getElementById('rtlOut').textContent"); print(txt[:200])
        assert "USB" in txt and len(txt)>40, txt
        pg.evaluate("rtlWatch(); 0"); pg.wait_for_timeout(2500)
        w=pg.evaluate("document.getElementById('rtlOut').textContent"); print(w[:120])
        assert "USB device" in w, w
        pg.evaluate("rtlWatch(); 0")
        assert not errs, errs
        b.close()
    print("PASS Check my dongle shows its answer in Hardware setup")
finally: pr.terminate()
