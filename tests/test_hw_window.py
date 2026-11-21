"""0.9.0: Hardware window - status line, Ready check, hide-what-is-not-found, Flex message, calibration colours, saved setups."""
import os, sys, json, time, subprocess, tempfile, socket
APP=os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","app")
data=tempfile.mkdtemp(); s=socket.socket(); s.bind(("127.0.0.1",0)); port=s.getsockname()[1]; s.close()
for d in ("Settings","Maps","Drives"): os.makedirs(data+"/"+d,exist_ok=True)
for p in (data+"/config.json",data+"/Settings/config.json"): json.dump({"token":"tok","use_sdrplay":False,"use_anan":True,"gps_mode":"usb"},open(p,"w"))
env=dict(os.environ,NT_DATA=data,PYTHONPATH=APP)
pr=subprocess.Popen([sys.executable,APP+"/nt_app.py","--no-browser","--port",str(port)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,cwd=APP)
from playwright.sync_api import sync_playwright
try:
    time.sleep(4)
    with sync_playwright() as pw:
        b=pw.chromium.launch(executable_path="/usr/bin/google-chrome",args=["--no-sandbox"]); pg=b.new_page(viewport={"width":1400,"height":1000}); errs=[]
        pg.on("pageerror",lambda e:errs.append(str(e))); names=["Test A"]
        pg.on("dialog",lambda d:(d.accept(names[0]) if d.type=="prompt" else d.accept()))
        pg.goto("http://127.0.0.1:%d/?t=tok"%port); time.sleep(3)
        pg.evaluate("hwOpen()"); time.sleep(1.5)
        st=pg.inner_text("#hwStatus"); print("status:",st.replace("\n"," | ")); assert "GPS" in st and "Radios" in st and "ANAN" in st and "Slots" in st, st
        pg.click("#btnReady"); time.sleep(0.3); rd=pg.inner_text("#hwReadyOut"); print("ready:",rd.replace("\n"," | ")[:300]); assert "GPS" in rd and "Max speed test" in rd
        # fill slot 1 frequency in the table and check calibration state colour
        pg.fill("#hwSlotT tr:nth-child(2) input[type=number] >> nth=0","7.3"); pg.keyboard.press("Tab"); time.sleep(0.5); time.sleep(1.2)
        cs=pg.inner_text("#hwCs0"); print("slot1 state:",cs); assert "Not calibrated" in cs, cs
        pg.fill("#hwCc0","3.5"); pg.keyboard.press("Tab"); time.sleep(1.3); cs=pg.inner_text("#hwCs0"); assert cs.strip()=="Calibrated", cs
        assert "Slot is off" in pg.inner_text("#hwCs3")
        print("PASS status line, Ready check, calibration states")
        # hide what is not found: scan, then unticked radios with nothing found should be hidden, show-all link works
        pg.evaluate("document.getElementById('practice').checked=false"); pg.click("#btnScan"); pg.wait_for_function("HW&&HW.drivers&&HW.drivers.some(d=>d.scan)",timeout=90000); time.sleep(1.5)
        print("SC:",pg.evaluate("JSON.stringify((HW.drivers||[]).map(d=>[d.id,d.scan?d.scan.found.length:null]))")); note=pg.inner_text("#hwHideNote"); print("hide note:",note); vis=pg.evaluate("[...document.querySelectorAll('#radioBox label.chk')].map(l=>l.style.display!=='none'&&l.offsetParent!==null)")
        print("tile visible:",vis); assert "Show all radio types" in note, note
        assert pg.evaluate("document.getElementById('useAnan').closest('label').style.display!=='none'"), "ticked ANAN must stay visible"
        pg.click("#hwHideNote a"); time.sleep(0.5); assert all(pg.evaluate("[...document.querySelectorAll('#radioBox label.chk')].map(l=>l.style.display!=='none')")), "show all"
        assert "Show only what was found" in pg.inner_text("#hwHideNote"); print("PASS hide / show all")
        fm=pg.inner_text("#flexMsg") if pg.evaluate("!!document.getElementById('flexMsg')") else ""; print("flex msg:",fm[:120])
        # saved setups
        pg.click("#btnProfSave"); time.sleep(1.2); opts=pg.evaluate("[...document.querySelectorAll('#hwProf option')].map(o=>o.textContent)"); print("profiles:",opts); assert "Test A" in opts, opts
        cfg=json.load(open(data+"/Settings/config.json")) if os.path.exists(data+"/Settings/config.json") else {}
        saved=json.load(open(data+"/config.json")).get("hw_profiles") or cfg.get("hw_profiles"); print("saved in config:",bool(saved)); assert saved and saved[0]["name"]=="Test A" and saved[0]["cfg"]["use_anan"] is True
        pg.fill("#hwCc0","9"); pg.keyboard.press("Tab")
        pg.select_option("#hwProf",index=1); pg.click("#btnProfLoad"); time.sleep(4); pg.wait_for_load_state()
        pg.evaluate("hwOpen()"); time.sleep(1.5); v=pg.input_value("#hwCc0"); print("cal after load:",v); assert float(v)==3.5, v
        pg.select_option("#hwProf",index=1); pg.click("#btnProfDel"); time.sleep(1); assert "Test A" not in pg.evaluate("[...document.querySelectorAll('#hwProf option')].map(o=>o.textContent)")
        print("PASS saved setups: save, load, delete"); print("page errors:",errs[:3]); assert not errs
        pg.screenshot(path="/tmp/hw090.png")
finally: pr.terminate()
