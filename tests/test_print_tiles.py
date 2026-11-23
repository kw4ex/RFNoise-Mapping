"""Printing a map waits for the street pictures (tiles) before the print dialog opens."""
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
        b=pw.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"]); pg=b.new_page(viewport={"width":1300,"height":800}); errs=[]; pg.on("pageerror",lambda e:errs.append(str(e)))
        def tile(route):
            time.sleep(0.15); route.fulfill(status=200,content_type="image/png",body=PNG)     # slow street pictures
        pg.route("**/*.tile.openstreetmap.org/**",tile); pg.route("**/server.arcgisonline.com/**",tile); pg.route("**/*basemaps.cartocdn.com/**",tile)
        pg.goto("http://127.0.0.1:%d/maps/%s?t=tok"%(port,m)); pg.wait_for_timeout(3000)
        pg.evaluate("window.__p=null; window.__h=[]; window.__ap=0; window.print=function(){ window.__h.push([document.body.className, tilesPending(), new Error().stack.split('\\n').slice(1,4).join('|')]); window.__p={ready:(function(){var i=document.getElementById('snapimg'); return !!(i&&i.complete&&i.naturalWidth>100)})(), snap:document.body.classList.contains('snap'), img:(document.getElementById('snapimg')||{}).src?document.getElementById('snapimg').src.length:0, pending:tilesPending(), tiles:document.querySelectorAll('#map .leaflet-tile-loaded').length, cls:document.body.className, h:document.getElementById('map').getBoundingClientRect().height}; }; 0")
        pg.evaluate("document.getElementById(\"print\").click()"); 
        pg.wait_for_timeout(12000)
        p=pg.evaluate("window.__p");         assert p and p["ready"], ("picture not ready when print opened", p)
        assert p["snap"] and p["img"]>5000, ("no flat picture of the map at print time", p)
        assert p["pending"]==0 and p["tiles"]>0 and "prepping" in p["cls"], p
        pg.wait_for_timeout(3000)   # the print window is still open: the flat picture must still be there
        assert "snap" in pg.evaluate("document.body.className") and pg.evaluate("!!document.getElementById('snapimg')"), "picture removed while the print window was open"
        pg.evaluate("window.dispatchEvent(new Event('afterprint')); 0"); pg.wait_for_timeout(300)
        assert "snap" not in pg.evaluate("document.body.className") and "prepping" not in pg.evaluate("document.body.className")
        # the page now switches to the printed layout: the street pictures must still cover the whole map
        pg.set_viewport_size({"width":720,"height":1000}); pg.emulate_media(media="print"); pg.wait_for_timeout(60)   # paper is narrower than the screen
        cov=pg.evaluate("""(()=>{const m=document.getElementById('map').getBoundingClientRect(); const T=[...document.querySelectorAll('#map .leaflet-tile-loaded')].map(t=>t.getBoundingClientRect());
          let miss=0,n=0; for(let i=1;i<6;i++)for(let j=1;j<6;j++){ const x=m.left+m.width*i/6,y=m.top+m.height*j/6; n++; if(!T.some(r=>x>=r.left&&x<=r.right&&y>=r.top&&y<=r.bottom)) miss++; }
          return {miss,n,pending:tilesPending(),w:m.width,h:m.height}; })()""")
        assert cov["miss"]==0 and cov["pending"]==0, cov
        assert not errs, errs
        b.close()
    print("PASS print waits for the street pictures")
finally:
    pr.terminate()
