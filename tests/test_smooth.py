"""2.0.0i: 'Picture smoothness' makes the slot trace smoother (drawing only), in the panel and on the phone page."""
import os, sys, json, time, subprocess, tempfile, socket
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); APP=os.path.join(ROOT,"app")
data=tempfile.mkdtemp(); s=socket.socket(); s.bind(("127.0.0.1",0)); port=s.getsockname()[1]; s.close()
chs=[{"mhz":"7.1","bw_khz":5,"cal_db":0,"radio":"auto","mode":"AM"},{"mhz":"14.2","bw_khz":5,"cal_db":0,"radio":"auto","mode":"AM"}]
os.makedirs(data+"/Settings",exist_ok=True)
for p in (data+"/config.json",data+"/Settings/config.json"): json.dump({"token":"tok","practice":True,"channels":chs}, open(p,"w"))
pr=subprocess.Popen([sys.executable, APP+"/nt_app.py","--no-browser","--port",str(port)], env=dict(os.environ,NT_DATA=data,PYTHONPATH=APP), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=APP)
from playwright.sync_api import sync_playwright
errs=[]
def rough(pg,sel):
    return pg.evaluate("""(sel)=>{const c=document.querySelector(sel); const g=c.getContext('2d'); const W=c.width,H=c.height; const d=g.getImageData(0,0,W,Math.floor(H*0.7)).data;
      let tot=0,cols=0; let prev=null; for(let x=Math.floor(W*0.1);x<W;x+=1){ let y=-1; for(let r=0;r<Math.floor(H*0.7);r++){ const o=(r*W+x)*4; if(d[o]<120&&d[o+1]>170&&d[o+2]>220){ y=r; break; } } if(y>=0){ if(prev!==null){ tot+=Math.abs(y-prev); cols++; } prev=y; } } return cols?tot/cols:-1; }""",sel)
try:
    time.sleep(4)
    with sync_playwright() as pw:
        b=pw.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        pg=b.new_page(viewport={"width":1400,"height":1000}); pg.on("pageerror",lambda e:errs.append(str(e)))
        pg.goto("http://127.0.0.1:%d/?t=tok"%port); time.sleep(2)
        assert pg.evaluate("document.getElementById('picSmooth').value")=="0"
        pg.evaluate("fetch('/api/start',{method:'POST',headers:{'X-NT':'1','Content-Type':'application/json'},body:JSON.stringify({practice:true,channels:%s})})"%json.dumps(chs)); time.sleep(6)
        sel=".slsp"; r0=rough(pg,sel)
        pg.evaluate("(()=>{const e=document.getElementById(\"picSmooth\"); e.value=\"3\"; e.onchange();})()"); time.sleep(4); r3=rough(pg,sel)
        print("roughness normal %.2f strong %.2f"%(r0,r3))
        assert r0>0 and r3>=0 and r3<r0, (r0,r3)
        assert pg.evaluate("localStorage.getItem('ntSmooth')")=="3"
        b.close()
    print("PASS picture smoothness; errors:",errs); assert not errs
finally:
    pr.terminate()
