"""diag_radio.py - writes a plain-text report about why the radio library cannot see the SDRplay. Safe: it only reads."""
import os, sys, struct, glob, io, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
out = io.StringIO()
def say(*a):
    print(*a); print(*a, file=out)

def imports(path):
    """Names of the DLLs a .dll/.exe needs (reads the file's import table)."""
    d = open(path, "rb").read()
    pe = struct.unpack_from("<I", d, 0x3C)[0]
    nsec = struct.unpack_from("<H", d, pe + 6)[0]
    opt = struct.unpack_from("<H", d, pe + 20)[0]
    base = pe + 24
    magic = struct.unpack_from("<H", d, base)[0]
    ddoff = base + (112 if magic == 0x20B else 96)
    rva = struct.unpack_from("<I", d, ddoff + 8)[0]
    secs = []
    so = base + opt
    for i in range(nsec):
        vs, va, rs, ro = struct.unpack_from("<IIII", d, so + i * 40 + 8)
        secs.append((va, max(vs, rs), ro))
    def off(r):
        for va, sz, ro in secs:
            if va <= r < va + sz:
                return r - va + ro
        return None
    names = []
    o = off(rva)
    while o:
        nm = struct.unpack_from("<I", d, o + 12)[0]
        if nm == 0:
            break
        n = off(nm); e = d.index(b"\0", n)
        names.append(d[n:e].decode("ascii", "replace"))
        o += 20
    return names

try:
    import rfmap_common as C
    say("Program version:", C.VERSION, "| Python", sys.version.split()[0], "| 64-bit" if sys.maxsize > 2**32 else "| 32-bit")
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pothos = os.path.join(pf, "PothosSDR"); api = os.path.join(pf, "SDRplay", "API", "x64")
    say("PothosSDR folder exists:", os.path.isdir(pothos), "| SDRplay API x64 folder exists:", os.path.isdir(api))
    say("sdrplay_api.dll:", glob.glob(os.path.join(api, "*.dll")))
    say("sdrplay_api.dll elsewhere (System32):", os.path.isfile(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "sdrplay_api.dll")))
    mods = os.path.join(pothos, "lib", "SoapySDR", "modules0.8")
    say("Plugin folder:", mods)
    say("Plugins:", [os.path.basename(x) for x in glob.glob(os.path.join(mods, "*.dll"))])
    soapy, note = C.find_soapy()
    say("find_soapy ->", "OK" if soapy else "NONE", "|", note)
    say("PRELOAD_NOTE:", repr(getattr(C,"PRELOAD_NOTE","(missing)")))
    for plug in ("sdrPlaySupport.dll", "volkConverters.dll"):
        p = os.path.join(mods, plug)
        if os.path.isfile(p):
            say("\n", plug, "needs:")
            for n in imports(p):
                where = [x for x in (os.path.join(pothos, "bin"), api, os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")) if os.path.isfile(os.path.join(x, n))]
                if n.lower().startswith("api-ms-win"):
                    where = ["(Windows built-in)"]
                say("   ", n, "->", where if where else "NOT FOUND ANYWHERE")
    if soapy:
        say("\nSoapySDR version:", soapy.getAPIVersion(), "| ABI:", soapy.getABIVersion())
        say("Modules loaded:", soapy.listModules())
        say("Devices (all):", [dict(x) for x in soapy.Device.enumerate()])
        try:
            soapy.setLogLevel(soapy.SOAPY_SDR_DEBUG)
        except Exception:
            pass
        say("Devices (driver=sdrplay):", [dict(x) for x in soapy.Device.enumerate("driver=sdrplay")])
    import subprocess
    exe = os.path.join(pothos, "bin", "SoapySDRUtil.exe")
    if os.path.isfile(exe):
        say("\n--- SoapySDRUtil --find=driver=sdrplay (for comparison) ---")
        r = subprocess.run([exe, "--find=driver=sdrplay"], capture_output=True, text=True, timeout=60)
        say(r.stdout); say(r.stderr)
    say("\n--- Programs that may be holding the radio ---")
    r = subprocess.run(["tasklist"], capture_output=True, text=True)
    for line in r.stdout.splitlines():
        l = line.lower()
        if any(k in l for k in ("python", "sdr", "hdsdr", "sdrplay", "gqrx", "cubic")):
            say(line)
except Exception:
    say(traceback.format_exc())
f = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "diag_radio.txt")
open(f, "w", encoding="utf-8").write(out.getvalue())
print("\nReport saved to", f)
