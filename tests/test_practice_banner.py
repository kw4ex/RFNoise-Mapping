"""0.9.0a: the red PRACTICE MODE banner shows exactly when Practice is ticked; its button turns practice off."""
import os, sys, json, time, subprocess, tempfile, socket
APP=os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","app")
data=tempfile.mkdtemp(); s=socket.socket(); s.bind(("127.0.0.1",0)); port=s.getsockname()[1]; s.close()
for d in ("Settings","Maps","Drives"): os.makedirs(data+"/"+d,exist_ok=True)
for p in (data+"/config.json",data+"/Settings/config.json"): json.dump({"token":"tok","practice":True},open(p,"w"))
env=dict(os.environ,NT_DATA=data,PYTHONPATH=APP)
pr=subprocess.Popen([sys.executable,APP+"/nt_app.py","--no-browser","--port",str(port)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,cwd=APP)
from playwright.sync_api import sync_playwright
try:
    time.sleep(4)
    with sync_playwright() as pw:
        b=pw.chromium.launch(executable_path="/usr/bin/google-chrome",args=["--no-sandbox"]); pg=b.new_page(viewport={"width":1400,"height":900}); errs=[]
        pg.on("pageerror",lambda e:errs.append(str(e))); pg.goto("http://127.0.0.1:%d/?t=tok"%port); time.sleep(3)
        vis=lambda:pg.evaluate("getComputedStyle(document.getElementById('pracBanner')).display!=='none'")
        assert vis() and "[PRACTICE]" in pg.title(), "banner should show when practice is saved on"
        pg.screenshot(path="/tmp/banner.png",clip={"x":0,"y":0,"width":1400,"height":260})
        pg.click("#pracOff"); time.sleep(1.5)
        assert not vis() and not pg.is_checked("#practice") and "[PRACTICE]" not in pg.title()
        assert json.load(open(data+"/config.json")).get("practice") is False or json.load(open(data+"/Settings/config.json")).get("practice") is False
        pg.check("#practice"); time.sleep(1.2); assert vis()
        pg.uncheck("#practice"); time.sleep(1.2); assert not vis()
        print("PASS banner follows the Practice tick; button turns it off and saves; errors:",errs[:2]); assert not errs
finally: pr.terminate()
