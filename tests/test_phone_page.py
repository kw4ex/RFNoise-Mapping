"""2.0.0g: the separate phone page (/phone): live readout, Start/Stop/Mark, the map, the slot pictures, and phone clients."""
import os, sys, json, time, subprocess, tempfile, socket, urllib.request
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); APP=os.path.join(ROOT,"app")
sys.path.insert(0,APP)
data=tempfile.mkdtemp(); s=socket.socket(); s.bind(("127.0.0.1",0)); port=s.getsockname()[1]; s.close()
chs=[{"mhz":"7.1","bw_khz":5,"cal_db":0,"radio":"auto","mode":"AM"},{"mhz":"14.2","bw_khz":5,"cal_db":0,"radio":"auto","mode":"AM"},{"mhz":"21.2","bw_khz":5,"cal_db":0,"radio":"auto","mode":"AM"},{"mhz":"28.4","bw_khz":5,"cal_db":0,"radio":"auto","mode":"AM"}]
os.makedirs(data+"/Settings",exist_ok=True)
for p in (data+"/config.json",data+"/Settings/config.json"): json.dump({"token":"tok","practice":True,"channels":chs}, open(p,"w"))
pr=subprocess.Popen([sys.executable, APP+"/nt_app.py","--no-browser","--port",str(port)], env=dict(os.environ,NT_DATA=data,PYTHONPATH=APP), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=APP)
from playwright.sync_api import sync_playwright
errs=[]
try:
    time.sleep(4)
    with sync_playwright() as pw:
        b=pw.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        pg=b.new_context(viewport={"width":390,"height":780},device_scale_factor=2,has_touch=True,is_mobile=True).new_page()
        pg.on("pageerror",lambda e:errs.append(str(e)))
        pg.goto("http://127.0.0.1:%d/phone?t=tok"%port); time.sleep(2)
        assert pg.inner_text("#tState")=="ready", pg.inner_text("#tState")
        pg.click("#bGo"); time.sleep(5)
        assert pg.inner_text("#tState")=="logging", (pg.inner_text("#tState"), pg.inner_text("#msg"))
        s_=pg.inner_text("#mS"); assert s_.startswith("S"), s_
        assert pg.locator("#rows .row").count()==4, pg.locator("#rows .row").count()
        assert pg.is_enabled("#bMark"); pg.click("#bMark"); time.sleep(2); assert "marked" in pg.inner_text("#msg"), pg.inner_text("#msg")
        pg.screenshot(path="/tmp/ph_live.png")
        pg.once("dialog",lambda d:d.accept()); pg.click("#bStop"); time.sleep(4)
        assert pg.inner_text("#tState")=="ready", pg.inner_text("#tState")
        pg.click("#bGo"); time.sleep(4)
        pg.click("#nav button[data-v=vMap]"); time.sleep(3)
        n=pg.evaluate("TR.pts.length"); assert n>5, (n, pg.evaluate("[!!window.L,!!TR.map,TR.loading,TR.seq,LOGGING]"), pg.inner_text("#mapInfo"))
        pg.screenshot(path="/tmp/ph_map.png")
        pg.click("#nav button[data-v=vSlots]"); time.sleep(3)
        assert pg.locator("#slots .slot").count()==4
        drawn=pg.evaluate("SLN.cards.filter(c=>c.sm).length"); assert drawn==4, drawn
        pg.screenshot(path="/tmp/ph_slots.png")
        b.close()
    # phone clients are named ph- and get a longer silent time than a computer page
    import nt_app as A
    A.CLIENTS.clear(); A.note_client("ph-abc"); A.note_client("pc1")
    now=time.time()+A.QC_STALE+5
    assert A.quit_when_closed_due(now,0,False) is False and "ph-abc" in A.CLIENTS and "pc1" not in A.CLIENTS
    print("PASS phone page; errors:",errs)
    assert not errs
finally:
    pr.terminate()
