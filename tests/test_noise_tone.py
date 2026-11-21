"""0.7.0n: Noise tone 'All' option is the default and beeps for the biggest rise of any running slot (needs playwright + chrome)."""
import os, sys, json, time, subprocess, tempfile, socket, re
APP=os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","app")
data=tempfile.mkdtemp(); s=socket.socket(); s.bind(("127.0.0.1",0)); port=s.getsockname()[1]; s.close()
env=dict(os.environ,NT_DATA=data,PYTHONPATH=APP); os.makedirs(data+"/Settings",exist_ok=True)
for p in (data+"/config.json",data+"/Settings/config.json"): json.dump({"token":"tok","use_sdrplay":False},open(p,"w"))
proc=subprocess.Popen([sys.executable,APP+"/nt_app.py","--no-browser","--port",str(port)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,cwd=APP)
from playwright.sync_api import sync_playwright
try:
    time.sleep(4)
    src=open(APP+"/panel.html").read()
    m=re.search(r'(const sel=\$\("toneSlot"\)\.value.*?beep\(380\+Math\.min\(best,24\)\*38,0\.16,0\.22\);)',src,re.S); assert m, "tone logic not found"
    logic=m.group(1)
    with sync_playwright() as pw:
        b=pw.chromium.launch(executable_path="/usr/bin/google-chrome",args=["--no-sandbox"]); pg=b.new_page(); errs=[]
        pg.on("pageerror",lambda e:errs.append(str(e))); pg.goto("http://127.0.0.1:%d/?t=tok"%port); time.sleep(3)
        d=pg.evaluate("[$('toneSlot').value,[...$('toneSlot').options].map(o=>o.textContent).join(',')]"); print(d); assert d[0]=="all" and d[1]=="All,1,2,3,4", d
        res=pg.evaluate("""(logic)=>{ const out=[]; const run=(sel,thr,hist)=>{ let got=null; const beep=(f)=>{got=f;}; const slotCh=k=>hist[k]?k:-1; const SLH=hist;
              const g=(id)=>({value:id==="toneSlot"?sel:String(thr)}); const $=g; new Function("$","beep","slotCh","SLH",logic)($,beep,slotCh,SLH); return got; };
            const flat=Array.from({length:14},()=>({v:-90})), jump=flat.slice(0,13).concat([{v:-80}]); // +10 dB in the last reading
            out.push(run("all",6,[flat,flat,jump,null]));      // one slot jumps 10 dB -> beep at its pitch
            out.push(run("all",6,[flat,flat,flat,null]));      // nothing rises -> no beep
            out.push(run("1",6,[flat,flat,jump,null]));        // slot 1 only, slot 3 jumped -> no beep
            out.push(run("3",6,[flat,flat,jump,null]));        // slot 3 only -> beep
            out.push(run("all",12,[flat,flat,jump,null]));     // threshold higher than the rise -> no beep
            return out; }""",logic)
        print(res)
        assert res[0]==380+10*38 and res[1] is None and res[2] is None and res[3]==380+10*38 and res[4] is None, res
        print("PASS Noise tone: All is the default, beeps for the biggest rise of any slot, and the single-slot choice still works"); print("errors",errs[:3])
finally: proc.terminate()
