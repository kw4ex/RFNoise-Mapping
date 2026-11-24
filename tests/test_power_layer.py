"""Power layer: lines, poles, substations from (mocked) OpenStreetMap data; reload button."""
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
        pg.route("**/*.tile.openstreetmap.org/**",lambda r:r.fulfill(status=200,content_type="image/png",body=PNG))
        pg.route("**/server.arcgisonline.com/**",lambda r:r.fulfill(status=200,content_type="image/png",body=PNG))
        calls=[]
        def op(route):
            calls.append(route.request.post_data)
            la,lo=pg.evaluate("[map.getCenter().lat,map.getCenter().lng]")
            els=[{"type":"way","tags":{"power":"minor_line","voltage":"12470"},"geometry":[{"lat":la,"lon":lo},{"lat":la+.001,"lon":lo+.001}]},
                 {"type":"way","tags":{"power":"substation","name":"Test Sub"},"geometry":[{"lat":la,"lon":lo},{"lat":la+.0005,"lon":lo},{"lat":la+.0005,"lon":lo+.0005}]},
                 {"type":"node","lat":la,"lon":lo,"tags":{"power":"pole","ref":"P1"}},{"type":"node","lat":la+.0002,"lon":lo,"tags":{"man_made":"utility_pole"}}]
            route.fulfill(status=200,content_type="application/json",headers={"Access-Control-Allow-Origin":"*"},body=json.dumps({"elements":els}))
        pg.route("**/overpass-api.de/**",op)
        pg.goto("http://127.0.0.1:%d/maps/%s?t=tok"%(port,m)); pg.wait_for_timeout(2500)
        pg.evaluate("document.getElementById('tgPower').click()"); pg.wait_for_timeout(2500)
        msg=pg.evaluate("document.getElementById('powerMsg').textContent"); print(msg[:120])
        assert "1 line" in msg and "2 pole" in msg and "1 substation" in msg, msg
        import urllib.parse as U; q0=U.unquote(calls[0]); assert "man_made" in q0 and "utility_pole" in q0 and "substation" in q0, q0
        assert pg.evaluate("document.getElementById('pwHere').style.display")=="" 
        n=len(calls); pg.evaluate("document.getElementById('pwHere').click()"); pg.wait_for_timeout(2000)
        assert len(calls)==n+1, "Load for this view did not query again"
        assert not errs, errs
        b.close()
    print("PASS power layer shows lines, poles and substations")
finally: pr.terminate()
