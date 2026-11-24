"""Compact view keeps the top bar on one line; the master Mute silences the slots, the alert and the voice."""
import os, sys, json, time, subprocess, tempfile, socket
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); APP=os.path.join(ROOT,"app")
data=tempfile.mkdtemp(); s=socket.socket(); s.bind(("127.0.0.1",0)); port=s.getsockname()[1]; s.close()
os.makedirs(data+"/Settings",exist_ok=True)
for p in (data+"/config.json",data+"/Settings/config.json"): json.dump({"token":"tok","practice":True}, open(p,"w"))
pr=subprocess.Popen([sys.executable, APP+"/nt_app.py","--no-browser","--port",str(port)], env=dict(os.environ,NT_DATA=data,PYTHONPATH=APP), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=APP)
from playwright.sync_api import sync_playwright
ROWS="""(()=>{ const tops=sel=>{ const e=document.querySelector(sel); if(!e) return null; const k=[...e.children].filter(c=>c.offsetParent!==null&&c.getBoundingClientRect().height>0).map(c=>Math.round(c.getBoundingClientRect().top)); return k.length?Math.max(...k)-Math.min(...k):0; };
  return {row1:tops('#drvRow1'), hw:tops('#barHw'), scrollW:document.documentElement.scrollWidth, innerW:innerWidth}; })()"""
try:
    time.sleep(4)
    with sync_playwright() as pw:
        b=pw.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        errs=[]
        for w in (1100,1280,1440):
            pg=b.new_page(viewport={"width":w,"height":850}); pg.on("pageerror",lambda e:errs.append(str(e)))
            pg.goto("http://127.0.0.1:%d/?t=tok"%port); pg.wait_for_timeout(2500)
            pg.evaluate("if(!COMPACT) viewToggle(); 0"); pg.wait_for_timeout(700)
            r=pg.evaluate(ROWS); print("compact",w,r)
            assert r["row1"]<=8 and r["hw"]<=8, ("top bar wrapped in compact view", w, r)
            pg.close()
        pg=b.new_page(viewport={"width":1300,"height":850}); pg.on("pageerror",lambda e:errs.append(str(e)))
        pg.goto("http://127.0.0.1:%d/?t=tok"%port); pg.wait_for_timeout(2500)
        pg.evaluate("if(COMPACT) viewToggle(); 0"); pg.wait_for_timeout(500)
        assert pg.evaluate("document.getElementById('bView').textContent")=="View: Normal"
        cols=lambda: pg.evaluate("getComputedStyle(document.getElementById('slGrid')).gridTemplateColumns.split(' ').length")
        assert cols()==1, "Normal view should show one slot per row"
        pg.evaluate("viewToggle(); 0"); pg.wait_for_timeout(500)
        assert cols()==2, "Compact view should show two slots across"
        pg.reload(); pg.wait_for_timeout(2500)
        assert pg.evaluate("document.body.classList.contains('compact')") and cols()==2, "compact view was not remembered"
        pg.evaluate("viewToggle(); viewToggle(); 0")
        # master mute
        pg.evaluate("slsChan(1); 0")
        pg.evaluate("window.__beeps=0; const o=AudioContext.prototype.createOscillator; AudioContext.prototype.createOscillator=function(){ window.__beeps++; return o.apply(this,arguments); }; window.__said=0; window.speechSynthesis.speak=function(){ window.__said++; }; 0")
        pg.evaluate("muteAllToggle(); 0")
        r=pg.evaluate("({m:MUTE_ALL, g:Object.values(SLS.ch).map(o=>o.gain.gain.value), txt:document.getElementById('bMuteAll').textContent})")
        assert r["m"] and all(v==0 for v in r["g"]) and "MUTED" in r["txt"], r
        pg.evaluate("alPlay('beep',80); beep(600,0.1,0.2); AL.vol=80; say('test',true); 0")
        assert pg.evaluate("[__beeps,__said]")==[0,0], pg.evaluate("[__beeps,__said]")
        pg.evaluate("muteAllToggle(); alPlay('beep',80); say('test',true); 0")
        assert pg.evaluate("__beeps")>0 and pg.evaluate("__said")==1
        # Sound / Voice checkboxes in the alert area
        pg.evaluate("document.getElementById('alSndM').click(); 0")
        assert pg.evaluate("ALSND")==False
        pg.evaluate("window.__beeps=0; alPlay('beep',80); 0"); assert pg.evaluate("__beeps")==0
        pg.evaluate("document.getElementById('alVoiceM').click(); 0")
        assert pg.evaluate("AL.voice")==True and pg.evaluate("document.getElementById('alVoice').checked")==True
        pg.reload(); pg.wait_for_timeout(2000)
        assert pg.evaluate("[document.getElementById('alSndM').checked,document.getElementById('alVoiceM').checked]")==[False,True]
        # a second tab (e.g. another browser) follows the master mute
        pg2=b.new_page(viewport={"width":1300,"height":850}); pg2.goto("http://127.0.0.1:%d/?t=tok"%port); pg2.wait_for_timeout(2000)
        pg.evaluate("muteAllToggle(); 0"); pg2.wait_for_timeout(3500)
        assert pg2.evaluate("MUTE_ALL")==True, "other tab did not follow the mute"
        pg.evaluate("muteAllToggle(); 0"); pg2.wait_for_timeout(3500)
        assert pg2.evaluate("MUTE_ALL")==False
        assert not errs, errs
        b.close()
    print("PASS compact view fits on one line; master mute silences everything")
finally:
    pr.terminate()
