"""2.0.0j: the top bar stays on one line (normal and compact), and the compact Highest meter box does not change size or move its words when the reading passes S9."""
import os, sys, json, time, subprocess, tempfile, socket
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); APP=os.path.join(ROOT,"app")
data=tempfile.mkdtemp(); s=socket.socket(); s.bind(("127.0.0.1",0)); port=s.getsockname()[1]; s.close()
os.makedirs(data+"/Settings",exist_ok=True)
for p in (data+"/config.json",data+"/Settings/config.json"): json.dump({"token":"tok","practice":True}, open(p,"w"))
pr=subprocess.Popen([sys.executable, APP+"/nt_app.py","--no-browser","--port",str(port)], env=dict(os.environ,NT_DATA=data,PYTHONPATH=APP), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=APP)
from playwright.sync_api import sync_playwright
errs=[]
try:
    time.sleep(4)
    with sync_playwright() as pw:
        b=pw.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        for w in (1100,1460,1728):
            pg=b.new_page(viewport={"width":w,"height":900}); pg.on("pageerror",lambda e:errs.append(str(e)))
            pg.goto("http://127.0.0.1:%d/?t=tok"%port); time.sleep(2)
            h=pg.evaluate("document.querySelector('header').getBoundingClientRect().height")
            assert h<45, ("top bar wrapped", w, h)
            if w>=1450:
                pg.evaluate("document.body.classList.add('compact')")
                res=[]
                for t,pk in (("S4",""),("S9+16","peak S9+16 · slot 2"),("S9+60","peak S9+60 · slot 2")):
                    pg.evaluate("(a)=>{mstS.textContent=a[0];mstW.textContent='slot 2 · 7.146 MHz';mstP.textContent=a[1]||' ';}",[t,pk])
                    res.append(pg.evaluate("[hwMst.getBoundingClientRect().height, mstW.getBoundingClientRect().left, mstP.getBoundingClientRect().left, mstS.scrollWidth<=mstS.clientWidth+1]"))
                assert all(abs(r[0]-res[0][0])<1 and abs(r[1]-res[0][1])<1 and abs(r[2]-res[0][2])<1 and r[3] for r in res), res
            pg.close()
        b.close()
    print("PASS top bar on one line; Highest box steady; errors:",errs); assert not errs
finally: pr.terminate()
