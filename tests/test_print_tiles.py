"""printing a map waits for the street pictures (tiles) before the print dialog opens."""
import os, sys, json, time, subprocess, tempfile, socket, base64
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); APP=os.path.join(ROOT,"app")
data=tempfile.mkdtemp(); s=socket.socket(); s.bind(("127.0.0.1",0)); port=s.getsockname()[1]; s.close()
os.makedirs(data+"/Settings",exist_ok=True)
for p in (data+"/config.json",data+"/Settings/config.json"): json.dump({"token":"tok","practice":True}, open(p,"w"))
pr=subprocess.Popen([sys.executable, APP+"/nt_app.py","--no-browser","--port",str(port)], env=dict(os.environ,NT_DATA=data,PYTHONPATH=APP), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=APP)
import urllib.request
from playwright.sync_api import sync_playwright
PNG=base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
try:
    time.sleep(4)
    r=urllib.request.Request("http://127.0.0.1:%d/api/demo"%port,data=b"{}",headers={"X-NT":"1","Content-Type":"application/json"})
    m=json.loads(urllib.request.urlopen(r,timeout=120).read())["map"]
    with sync_playwright() as pw:
        b=pw.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"]); pg=b.new_page(viewport={"width":1300,"height":800}); pg.on("console",lambda m:print("console:",m.text[:200])); pg.on("pageerror",lambda e:print("pageerror:",e))
        def tile(route):
            time.sleep(0.15); route.fulfill(status=200,content_type="image/png",body=PNG)     # slow street pictures
        pg.route("**/*.tile.openstreetmap.org/**",tile); pg.route("**/server.arcgisonline.com/**",tile); pg.route("**/*basemaps.cartocdn.com/**",tile)
        pg.goto("http://127.0.0.1:%d/maps/%s?t=tok"%(port,m)); pg.wait_for_timeout(3000)
        pg.evaluate("window.__p=null; window.__h=[]; window.print=function(){ window.__h.push([document.body.className, tilesPending(), new Error().stack.split('\\n').slice(1,4).join('|')]); window.__p={pending:tilesPending(), tiles:document.querySelectorAll('#map .leaflet-tile-loaded').length, cls:document.body.className, h:document.getElementById('map').getBoundingClientRect().height}; }; 0")
        pg.evaluate("document.getElementById(\"print\").click()"); 
        pg.wait_for_timeout(12000)
        print("state:",pg.evaluate("[document.body.className, typeof tilesPending, printing, tilesPending()]"))
        print("history:",pg.evaluate("window.__h"))
        p=pg.evaluate("window.__p"); print("at print time:",p)
        assert p and p["pending"]==0 and p["tiles"]>0 and "prepping" in p["cls"], p
        assert "prepping" not in pg.evaluate("document.body.className")
        b.close()
    print("PASS print waits for the street pictures")
finally:
    pr.terminate()
