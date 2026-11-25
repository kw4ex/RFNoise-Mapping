"""2.0.0j: on a map page the three boxes fold up to their title (and stay folded), and the colour bar is a two-handle slider that sets Min and Max."""
import os, sys, subprocess, tempfile, shutil, time
HERE=os.path.dirname(os.path.abspath(__file__)); APP=os.path.join(HERE,"..","app")
d=tempfile.mkdtemp(); shutil.copy(os.path.join(HERE,"sample_drive.csv"),d+"/d.csv")
r=subprocess.run([sys.executable,APP+"/make_map.py",d+"/d.csv","-o",d+"/m.html"],capture_output=True,text=True,env=dict(os.environ,PYTHONPATH=APP),cwd=APP); assert r.returncode==0, r.stderr[-400:]
from playwright.sync_api import sync_playwright
errs=[]
with sync_playwright() as pw:
    b=pw.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox","--allow-file-access-from-files"])
    pg=b.new_page(viewport={"width":1300,"height":800}); pg.on("pageerror",lambda e:errs.append(str(e)))
    pg.goto("file://"+d+"/m.html"); time.sleep(1.5)
    # folding
    for pid in ("ctl","hot","multi"):
        h0=pg.evaluate("document.getElementById('%s').getBoundingClientRect().height"%pid)
        pg.click("#%s > h4"%pid); h1=pg.evaluate("document.getElementById('%s').getBoundingClientRect().height"%pid)
        assert h1<45 and h1<h0, (pid,h0,h1)
        vis=pg.evaluate("[...document.getElementById('%s').children].filter(e=>e.tagName!=='H4'&&e.offsetParent!==null).length"%pid); assert vis==0,(pid,vis)
    pg.reload(); time.sleep(1.2)
    assert pg.evaluate("document.getElementById('ctl').classList.contains('shut')"), "fold state not remembered"
    for pid in ("ctl","hot","multi"): pg.click("#%s > h4"%pid)
    assert pg.evaluate("document.getElementById('ctl').getBoundingClientRect().height")>150
    # slider
    m0=(pg.evaluate("+mn.value"),pg.evaluate("+mx.value"))
    pg.evaluate("(()=>{const c=document.getElementById('cmin'); c.value=+c.value+120; c.dispatchEvent(new Event('input',{bubbles:true}));})()"); time.sleep(.4)
    m1=(pg.evaluate("+mn.value"),pg.evaluate("+mx.value"))
    assert m1[0]>m0[0] and m1[1]==m0[1], (m0,m1)
    pg.evaluate("(()=>{const c=document.getElementById('cmax'); c.value=0; c.dispatchEvent(new Event('input',{bubbles:true}));})()"); time.sleep(.4)
    m2=(pg.evaluate("+mn.value"),pg.evaluate("+mx.value")); assert m2[1]>m2[0], m2
    assert "linear-gradient" in pg.evaluate("document.getElementById('bar').style.background"), "bar not coloured"
    assert pg.evaluate("document.getElementById('bticks').children.length")>=2, "no S-unit ticks"
    pg.click("#auto"); time.sleep(.3)
    assert (pg.evaluate("+mn.value"),pg.evaluate("+mx.value"))==m0, "Auto did not restore the range"
    b.close()
print("PASS boxes fold and stay folded; colour slider sets Min/Max; errors:",errs); assert not errs
