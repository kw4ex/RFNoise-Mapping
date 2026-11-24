"""Car mode: the live map shows a 'You are here' dot at the GPS position and centres on it (even before recording)."""
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
        b=pw.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"]); pg=b.new_page(viewport={"width":1300,"height":900})
        errs=[]; pg.on("pageerror",lambda e:errs.append(str(e)))
        pg.route("**/*tile.openstreetmap.org/**",lambda r:r.abort())
        pg.goto("http://127.0.0.1:%d/?t=tok"%port); pg.wait_for_timeout(2500)
        # a real fix, like the USB GPS gives (practice mode has none)
        pg.evaluate("gpsShow({state:'fix',lat:35.92001,lon:-83.34863,sats:6,hdop:1.4,speed_mph:0,age_s:0,source:'monitor'}); 0")
        pg.evaluate("carMode(true); 0"); pg.wait_for_timeout(2500)
        pg.evaluate("gpsShow({state:'fix',lat:35.92001,lon:-83.34863,sats:6,hdop:1.4,speed_mph:0,age_s:0,source:'monitor'}); 0"); pg.wait_for_timeout(500)
        r=pg.evaluate("({me:!!TR.me, c:TR.map?[TR.map.getCenter().lat,TR.map.getCenter().lng]:null, ll:TR.me?[TR.me.getLatLng().lat,TR.me.getLatLng().lng]:null})")
        assert r["me"] and abs(r["c"][0]-35.92001)<0.001 and abs(r["c"][1]+83.34863)<0.001, r
        r2=pg.evaluate("(()=>{ gpsShow({state:'fix',lat:35.9215,lon:-83.3486,sats:6,hdop:1.4,speed_mph:20,age_s:0,source:'monitor'}); return [TR.me.getLatLng().lat, TR.map.getBounds().contains(TR.me.getLatLng())]; })()")
        assert abs(r2[0]-35.9215)<1e-6 and r2[1], r2
        assert not errs, errs
        b.close()
    print("PASS car mode shows 'You are here' at the GPS position")
finally:
    pr.terminate()
