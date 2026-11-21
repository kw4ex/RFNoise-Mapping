"""0.6.0e: tapping a Flex slot must not blank its picture (needs playwright + google-chrome; skipped where missing)."""
import os, sys, json, time, subprocess, tempfile, socket
HERE=os.path.dirname(os.path.abspath(__file__)); APP=os.path.join(HERE,"..","app"); sys.path.insert(0,APP); sys.path.insert(0,APP+"/radios")
from radios import cat_sim
fx=cat_sim.FakeFlex(slices=0,no_pan_slice=True,gui_pan=True); fx.start()
data=tempfile.mkdtemp(prefix="nt_h_"); s=socket.socket(); s.bind(("127.0.0.1",0)); port=s.getsockname()[1]; s.close()
env=dict(os.environ,NT_DATA=data,PYTHONPATH=APP)
cfg={"token":"tok","use_sdrplay":False,"use_cat":True,"use_anan":False,"practice":False,
 "cat_radios":[{"model":"flex6700","port":"127.0.0.1:%d"%fx.port,"mode":"control"}],
 "channels":[{"mhz":3.85,"bw_khz":5,"cal_db":0,"radio":"cat1","mode":"LSB"},{"mhz":7.147,"bw_khz":5,"cal_db":0,"radio":"cat1","mode":"LSB"},
  {"mhz":"","bw_khz":5,"cal_db":0,"radio":"auto"},{"mhz":"","bw_khz":5,"cal_db":0,"radio":"auto"}]}
os.makedirs(data+"/Settings",exist_ok=True)
for p in (data+"/config.json",data+"/Settings/config.json"): json.dump(cfg,open(p,"w"))
proc=subprocess.Popen([sys.executable,APP+"/nt_app.py","--no-browser","--port",str(port)],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,cwd=APP)
from playwright.sync_api import sync_playwright
try:
    time.sleep(4)
    with sync_playwright() as pw:
        b=pw.chromium.launch(executable_path="/usr/bin/google-chrome",args=["--no-sandbox"])
        pg=b.new_page(viewport={"width":1500,"height":1000}); errs=[]
        pg.on("pageerror",lambda e:errs.append(str(e))); pg.on("console",lambda m:errs.append(m.text) if m.type=="error" else None)
        pg.goto("http://127.0.0.1:%d/?t=tok"%port); time.sleep(3)
        print("title",pg.title())
        pg.screenshot(path="/tmp/h/a0.png")
        # start live view
        try:
            pg.evaluate("slStart && slStart()")
        except Exception as e: print("slStart",e)
        time.sleep(6); pg.screenshot(path="/tmp/h/a1.png")
        box=pg.locator(".slsp").nth(0).bounding_box(); print(box)
        pg.mouse.click(box["x"]+box["width"]*0.7, box["y"]+box["height"]*0.4)
        for k in range(6):
            time.sleep(1.5); pg.screenshot(path="/tmp/h/b%d.png"%k)
            print(k, pg.evaluate("[SLR[0]&&JSON.stringify(SLR[0]), document.querySelectorAll('.slF')[0].value]"))
        # a click lands on the nearest multiple of the Step
        v=float(pg.evaluate("document.querySelectorAll('.slF')[0].value")); assert abs(v*1e3-round(v*1e3))<1e-6, "1 kHz step: click did not snap to a whole kHz: %s" % v
        pg.select_option(".slbox >> nth=0 >> .slStep", "0.01"); box=pg.locator(".slsp").nth(0).bounding_box()
        pg.mouse.click(box["x"]+box["width"]*0.31, box["y"]+box["height"]*0.4); time.sleep(0.5)
        v2=float(pg.evaluate("document.querySelectorAll('.slF')[0].value")); assert abs(v2*1e5-round(v2*1e5))<1e-6 and v2!=v, "10 Hz step: %s" % v2
        print("PASS clicks snap to the Step (1 kHz -> %s MHz, 10 Hz -> %s MHz)" % (v, v2))
        # the big VFO readout: present, shows the frequency, drags, resizes, hides
        n=pg.evaluate("document.querySelectorAll('.vfobox').length"); assert n==5, "expected 5 VFO readouts (4 slots + main), got %d" % n
        txt=pg.evaluate("document.querySelectorAll('.slbox')[0].querySelector('.vfon').textContent"); assert int(txt.replace(".",""))==round(v2*1e6), (txt, v2)
        vb=pg.locator(".slbox").nth(0).locator(".vfobox"); b0=vb.bounding_box(); vb.hover()
        pg.mouse.down(); pg.mouse.move(b0["x"]+b0["width"]/2+90, b0["y"]+b0["height"]/2+50, steps=5); pg.mouse.up(); b1=vb.bounding_box()
        assert abs(b1["x"]-b0["x"])>40 and abs(b1["y"]-b0["y"])>25, ("did not drag", b0, b1)
        g=vb.locator(".vfog").bounding_box(); pg.mouse.move(g["x"]+8,g["y"]+8); pg.mouse.down(); pg.mouse.move(g["x"]+130,g["y"]+8,steps=5); pg.mouse.up(); b2=vb.bounding_box()
        assert b2["width"]>b1["width"]*1.3, ("did not resize", b1, b2)
        pg.locator(".slbox").nth(0).locator(".slVfo").click(); assert not vb.is_visible(), "Big VFO button did not hide it"
        print("PASS the big VFO readout shows the frequency, drags, resizes and hides (%d px wide after resize)" % b2["width"])
        # the S-meter box: drags, can be lost and found again
        sl=pg.locator(".slbox").nth(1); mt=sl.locator(".slmtr"); assert mt.is_visible()
        sl.locator(".slMtrBtn").click(); assert not mt.is_visible(), "Meter button should hide it"
        sl.locator(".slMtrBtn").click(); assert mt.is_visible(), "Meter button should bring it back"
        pg.evaluate("document.querySelectorAll('.slmtr')[1].style.left='9000px'; slp(1).mtr.x=9; document.querySelectorAll('.slmtr')[1]._laid=1"); time.sleep(0.6)
        pg.evaluate("window.dispatchEvent(new Event('resize'))"); time.sleep(0.6)
        hb=sl.bounding_box(); mb=mt.bounding_box(); assert mb["x"]<hb["x"]+hb["width"] and mb["x"]+mb["width"]>hb["x"], ("meter lost outside its slot", hb, mb)
        print("PASS the S-meter box hides, comes back with the Meter button, and stays inside its slot")
        r=json.loads(pg.evaluate("JSON.stringify(SLR[0])")); assert r["lo"] is not None and r["hi"] is not None, "the scale went blank after a tap: %s" % r
        print("PASS a tap on a Flex slot keeps its picture (scale %.0f..%.0f dB)" % (r["lo"], r["hi"])); print("errors",errs[:5])
        b.close()
finally:
    try: proc.kill()
    except Exception: pass
    fx.stop()
