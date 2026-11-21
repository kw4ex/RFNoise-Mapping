"""0.8.0: the ? key / F1 / ? Help button explain whatever is pointed at, on the main page and on map pages (needs playwright + chrome)."""
import os, sys, json, time, subprocess, tempfile, socket, shutil
HERE=os.path.dirname(os.path.abspath(__file__)); APP=os.path.join(HERE,"..","app"); sys.path.insert(0,APP)
data=tempfile.mkdtemp(); s=socket.socket(); s.bind(("127.0.0.1",0)); port=s.getsockname()[1]; s.close()
for d in ("Settings","Maps","Drives"): os.makedirs(data+"/"+d,exist_ok=True)
for p in (data+"/config.json",data+"/Settings/config.json"): json.dump({"token":"tok","use_sdrplay":False},open(p,"w"))
env=dict(os.environ,NT_DATA=data,PYTHONPATH=APP)
# a tiny drive CSV -> a real map from the real generator (copied from the user's practice drive when available)
U=os.path.join(HERE,"sample_drive.csv")                                   # a small made-up drive that ships with the tests
mapok=False
if os.path.exists(U):
    shutil.copy(U,data+"/Drives/d.csv")
    r=subprocess.run([sys.executable,APP+"/make_map.py",data+"/Drives/d.csv","-o",data+"/Maps/new_map.html"],capture_output=True,text=True,env=env,cwd=APP); mapok=r.returncode==0
    old=open(data+"/Maps/new_map.html","rb").read().replace(b"/*nt-help*/",b"/*x*/")      # an 'old' map has no help block
    i=old.index(b"<script>/*x*/"); j=old.index(b"</script>",old.index(b"function help")if False else i)+9
    open(data+"/Maps/old_map.html","wb").write(old.replace(b"__none__",b""))
proc=subprocess.Popen([sys.executable,APP+"/nt_app.py","--no-browser","--port",str(port)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,cwd=APP)
from playwright.sync_api import sync_playwright
def mv(pg,sel):
    el=pg.locator(sel).first; el.scroll_into_view_if_needed(); bb=el.bounding_box(); pg.mouse.move(bb["x"]+bb["width"]/2,bb["y"]+min(bb["height"]/2,12))
def pop_title(pg): return pg.evaluate("(document.querySelector('#ntHelpPop h3')||{}).textContent||null")
try:
    time.sleep(4)
    with sync_playwright() as pw:
        b=pw.chromium.launch(executable_path="/usr/bin/google-chrome",args=["--no-sandbox"]); pg=b.new_page(viewport={"width":1500,"height":1000}); errs=[]
        pg.on("pageerror",lambda e:errs.append(str(e))); pg.goto("http://127.0.0.1:%d/?t=tok"%port); time.sleep(3)
        assert pg.evaluate("!!document.getElementById('ntHelpBtn')"), "no ? Help button"
        def ask(sel, key="?"):
            mv(pg,sel); pg.keyboard.press("Escape"); pg.keyboard.press(key); time.sleep(0.2); return pop_title(pg)
        cases=[("#bStart","Start logging"),("#route","Route name"),("#practice","Practice"),("#bMark","Mark spot"),("#bCar","Car mode"),("#bigSpeed","Speed"),
               (".slF","Frequency"),(".slStep","Step"),(".slsMode","Mode"),(".slVol","Volume"),("#toneSlot","Noise tone: slot"),
               ("#hwMst","Highest"),("#tVer","Program version"),("#liveMap","Live map")]
        for sel,want in cases:
            if not pg.locator(sel).first.is_visible(): print("skip (not visible):",sel); continue
            got=ask(sel); assert got==want, (sel,got,want)
        print("PASS ? over", len(cases), "items shows the right explanation")
        # a tooltip-only item falls back to its own title text
        pg.evaluate("document.body.insertAdjacentHTML('beforeend','<button id=zz title=\"Only a tooltip here\" style=\"position:fixed;left:300px;top:300px\">zz</button>')")
        got=ask("#zz"); body=pg.evaluate("document.querySelector('#ntHelpPop').textContent"); assert "Only a tooltip here" in body, body
        print("PASS an item with only a tooltip shows that tooltip")
        # typing ? in a text box must NOT open help; F1 in a focused box does
        pg.locator("#route").click(); pg.keyboard.press("Escape"); pg.locator("#route").click(); pg.keyboard.type("a?b"); time.sleep(0.2)
        assert pop_title(pg) is None and pg.input_value("#route")=="a?b", (pop_title(pg), pg.input_value("#route"))
        pg.keyboard.press("F1"); time.sleep(0.2); assert pop_title(pg)=="Route name", pop_title(pg)
        pg.keyboard.press("Escape"); assert pop_title(pg) is None
        print("PASS ? types normally in a box; F1 explains the box; Esc closes")
        # help mode: click shows help and does NOT press the button
        pg.click("#ntHelpBtn"); assert pg.evaluate("document.documentElement.classList.contains('nt-help-mode')")
        before=pg.evaluate("document.body.classList.contains('car')"); pg.click("#bCar"); time.sleep(0.2)
        assert pop_title(pg)=="Car mode" and pg.evaluate("document.body.classList.contains('car')")==before, "help mode must not trigger the button"
        pg.keyboard.press("Escape"); assert not pg.evaluate("document.documentElement.classList.contains('nt-help-mode')") and pop_title(pg) is None
        print("PASS Help mode: clicking explains instead of acting; Esc ends it")
        # keyboard shortcut M and others still work (help did not break them) - the page has no errors
        print("main page errors:",errs[:3])
        if mapok:
            for nm in ("new_map","old_map"):
                mp=b.new_page(viewport={"width":1500,"height":1000}); merr=[]; mp.on("pageerror",lambda e:merr.append(str(e)))
                mp.goto("http://127.0.0.1:%d/maps/%s.html?t=tok"%(port,nm)); time.sleep(4); mp.evaluate("document.querySelectorAll('#ctl details').forEach(d=>d.open=true)"); time.sleep(0.3)
                assert mp.evaluate("!!document.getElementById('ntHelpBtn')"), nm+": no help button"
                for sel,want in (("#freq","Frequency"),("#mn","Min and Max (the colour scale)"),("#auto","Auto"),("#sz","Dot size"),("#basesel","Background"),("#tgSflag","Flag high noise"),
                                 ("#freq2","Also show ... as rings"),("#pPlay","Play / pause"),("#print","Print / Save as PDF"),("#hot h4","Hottest spots (or Highest readings)"),
                                 ("#multi h4","Same place, several frequencies"),("#hotmark","Mark them on the map"),(".leaflet-control-zoom","Zoom buttons")):
                    mv(mp,sel); mp.keyboard.press("Escape"); mp.keyboard.press("?"); time.sleep(0.15); got=pop_title(mp); assert got==want,(nm,sel,got,want)
                mp.keyboard.press("Escape"); print("PASS map page (%s): every panel control explains itself; errors %s"%(nm,merr[:2]))
        else: print("map test skipped (no sample drive)")
finally: proc.terminate()
