"""RTL-SDR dongle check: plain-English answers for the usual failures, the one-click fixes, and the report file."""
import os, sys, json, time, subprocess, tempfile, socket, urllib.request
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); APP=os.path.join(ROOT,"app")
os.environ["NT_DATA"]=tempfile.mkdtemp(); sys.path.insert(0,APP)
import rtl_diag as D

DONGLE={"name":"Bulk-In, Interface","vendor":0x0bda,"product":0x2838,"serial":"00000001","vendor_name":"Realtek"}
def scenario(usb, rt, su, cfg, tools=True, py=None):
    D.usb_devices=lambda: usb
    D._which=lambda n: ("/opt/homebrew/bin/"+n) if (tools or n=="brew") and n!="brew" or n=="brew" else None
    def run(cmd,timeout=10):
        if "rtl_test" in cmd[0]: return 0, rt
        if "SoapySDRUtil" in cmd[0]: return 0, su
        return 0, ""
    D._run=run
    D.C.find_soapy=lambda: (py, "no soapy" if py is None else "")
    return D.run(cfg, other_programs=False)
OKRT="Found 1 device(s):\n  0:  Generic RTL2832U OEM\nNo E4000 tuner found, aborting.\n"
OKSU="Found device 0\n  driver = rtlsdr\n  label = Generic RTL2832U\n"
class FakeS: pass
# 1. nothing on USB
r=scenario([{"name":"Keyboard","vendor":1,"product":2}],"No supported devices found.\n","No devices found!",{})
assert "does not see a dongle" in r["answer"], r["answer"]
# 2. drivers missing
r=scenario([DONGLE],"","",{},tools=False)
assert "drivers are not installed" in r["answer"] and any(f["id"]=="install_drivers" for f in r["fixes"]), r
# 3. busy
r=scenario([DONGLE],"Found 1 device(s)\nusb_claim_interface error -6\nFailed to open rtlsdr device #0.\n",OKSU,{})
assert "another program" in r["answer"], r["answer"]
# 4. works, but RTL not ticked and SDRplay ticked -> one-click 'use my dongle'
import types
sentinel=types.SimpleNamespace(); 
import nt_logger
nt_logger.rtl_list=lambda: ([{"serial":"1","label":"Generic RTL2832U","pos":0}],"")
r=scenario([DONGLE],OKRT,OKSU,{"use_rtl":False,"use_sdrplay":True},py=sentinel)
assert r["dongle_ok"] and any(f["id"]=="use_dongle" for f in r["fixes"]) and "Use my dongle" in r["answer"], r
# 5. already set up
r=scenario([DONGLE],OKRT,OKSU,{"use_rtl":True,"use_sdrplay":False},py=sentinel)
assert "working and set up" in r["answer"], r["answer"]
# 5b. a dongle by a less common id is recognised; ps lists other SDR programs
assert D.rtl_on_usb([{"name":"Generic","vendor":0x1d19,"product":0x1101}]) and not D.rtl_on_usb([{"name":"Keyboard","vendor":0x05ac,"product":0x0250}])
# 5c. permission error counts as busy
r=scenario([DONGLE],"Found 1 device(s)\nusb_open error -3\nPlease fix the device permissions\nFailed to open rtlsdr device #0. permission denied",OKSU,{})
assert "another program" in r["answer"], r["answer"]
# 6. report saved
assert os.path.isfile(r["report"]) and "ANSWER" in open(r["report"]).read()
assert os.path.dirname(r["report"]).endswith("Reports")
# 7. endpoints
import importlib
data=os.environ["NT_DATA"]; os.makedirs(data+"/Settings",exist_ok=True)
for p in (data+"/config.json",data+"/Settings/config.json"): json.dump({"token":"tok","practice":True,"use_sdrplay":True}, open(p,"w"))
s=socket.socket(); s.bind(("127.0.0.1",0)); port=s.getsockname()[1]; s.close()
pr=subprocess.Popen([sys.executable, APP+"/nt_app.py","--no-browser","--port",str(port)], env=dict(os.environ,PYTHONPATH=APP), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=APP)
try:
    time.sleep(4)
    def post(path,body): 
        rq=urllib.request.Request("http://127.0.0.1:%d%s"%(port,path),data=json.dumps(body).encode(),headers={"X-NT":"1","Content-Type":"application/json"}); return json.loads(urllib.request.urlopen(rq,timeout=90).read())
    j=post("/api/rtl_diag",{}); assert j["ok"] and j["answer"] and isinstance(j["checks"],list), j
    j=post("/api/rtl_fix",{"fix":"use_dongle"}); assert j["set"]["use_rtl"] is True and j["set"]["use_sdrplay"] is False, j
    cfg=json.loads(urllib.request.urlopen("http://127.0.0.1:%d/api/state"%port,timeout=20).read())["cfg"]
    assert cfg["use_rtl"] is True and cfg["use_sdrplay"] is False, cfg
    st=json.loads(urllib.request.urlopen("http://127.0.0.1:%d/api/rtl_install"%port,timeout=20).read()); assert "running" in st
finally: pr.terminate()
print("PASS dongle check gives the right plain answer for each failure, fixes work, report saved")
