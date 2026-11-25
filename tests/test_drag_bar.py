"""2.0.0j: dragging the green tuning bar on a slot picture: the bar follows the cursor at once (it does not wait for the radio's report)."""
import os, sys, json, time, subprocess, tempfile, socket
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); APP=os.path.join(ROOT,"app")
data=tempfile.mkdtemp(); s=socket.socket(); s.bind(("127.0.0.1",0)); port=s.getsockname()[1]; s.close()
chs=[{"mhz":"7.1","bw_khz":5,"cal_db":0,"radio":"hl2","mode":"AM"}]
os.makedirs(data+"/Settings",exist_ok=True)
for p in (data+"/config.json",data+"/Settings/config.json"): json.dump({"token":"tok","practice":True,"use_hl2":True,"channels":chs}, open(p,"w"))
pr=subprocess.Popen([sys.executable, APP+"/nt_app.py","--no-browser","--port",str(port)], env=dict(os.environ,NT_DATA=data,PYTHONPATH=APP), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=APP)
from playwright.sync_api import sync_playwright
errs=[]
try:
    time.sleep(4)
    with sync_playwright() as pw:
        b=pw.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        pg=b.new_page(viewport={"width":1400,"height":1000}); pg.on("pageerror",lambda e:errs.append(str(e)))
        pg.goto("http://127.0.0.1:%d/?t=tok"%port); time.sleep(2)
        pg.evaluate("fetch('/api/start',{method:'POST',headers:{'X-NT':'1','Content-Type':'application/json'},body:JSON.stringify({practice:true,channels:%s})})"%json.dumps(chs)); time.sleep(6)
        m=pg.evaluate("(()=>{const c=document.querySelector('.slsp'); const r=c.getBoundingClientRect(); const mp=c._map; return {l:r.left,t:r.top,w:r.width,h:r.height,bx0:mp&&mp.bx0,bx1:mp&&mp.bx1};})()")
        assert m["bx0"] is not None, m
        x=m["l"]+(m["bx0"]+m["bx1"])/2*m["w"]; y=m["t"]+m["h"]*0.4
        f0=pg.evaluate("document.querySelector('.slF').value")
        pg.mouse.move(x,y); pg.mouse.down(); pg.mouse.move(x+30,y,steps=3); pg.mouse.move(x+90,y,steps=4)
        mid=pg.evaluate("(()=>{const c=document.querySelector('.slsp'); const mp=c._map; return {bx0:mp.bx0,ov:!!document.querySelector('.slbox')._tuneOv,f:document.querySelector('.slF').value};})()")
        pg.mouse.up()
        print("before",f0,m["bx0"],"during",mid)
        assert mid["ov"] and mid["f"]!=f0, mid
        assert abs((mid["bx0"]-m["bx0"])*m["w"]-90)<14, ("the bar did not follow the cursor", mid, m)
        b.close()
    print("PASS the tuning bar follows the cursor; errors:",errs); assert not errs
finally:
    pr.terminate()
