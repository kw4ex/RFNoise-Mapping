"""RTL-SDR dongle diagnostics ("Check my dongle" in Hardware setup).

Looks at the whole chain a dongle needs, in the order things usually go wrong:
  1. is the dongle visible on the USB ports at all?          (cable, hub, power)
  2. are the driver programs installed?                       (brew: soapysdr, soapyrtlsdr, librtlsdr)
  3. does rtl_test see it, and is it free?                    (another program may be holding it)
  4. does SoapySDR (the library RFI Trail uses) see it?
  5. does RFI Trail's own Python reach SoapySDR?              (the Python versions must match on a Mac)
  6. are 'Your radios' ticked the way a dongle-only user needs? (RTL-SDR ticked, SDRplay unticked)
and gives ONE plain-English answer, a list of one-click fixes, and saves a text report in <data>/Reports.
Nothing here opens the dongle for longer than a second or two, and nothing needs a password.
"""
import glob, json, os, re, shutil, subprocess, sys, time

import nt_common as C

# USB ids of RTL-SDR dongles (vendor, product), taken from the rtl-sdr / librtlsdr list of known dongles.
KNOWN_RTL = {
    (0x0bda, 0x2832), (0x0bda, 0x2838), (0x0413, 0x6680), (0x0413, 0x6f0f), (0x0458, 0x707f),
    (0x0ccd, 0x00a9), (0x0ccd, 0x00b3), (0x0ccd, 0x00b4), (0x0ccd, 0x00b5), (0x0ccd, 0x00b7),
    (0x0ccd, 0x00b8), (0x0ccd, 0x00b9), (0x0ccd, 0x00c0), (0x0ccd, 0x00c6), (0x0ccd, 0x00d3),
    (0x0ccd, 0x00d7), (0x0ccd, 0x00e0), (0x1554, 0x5020), (0x15f4, 0x0131), (0x15f4, 0x0133),
    (0x185b, 0x0620), (0x185b, 0x0650), (0x185b, 0x0680), (0x1b80, 0xd393), (0x1b80, 0xd394),
    (0x1b80, 0xd395), (0x1b80, 0xd397), (0x1b80, 0xd398), (0x1b80, 0xd39d), (0x1b80, 0xd3a4),
    (0x1b80, 0xd3a8), (0x1b80, 0xd3af), (0x1b80, 0xd3b0), (0x1d19, 0x1101), (0x1d19, 0x1102),
    (0x1d19, 0x1103), (0x1d19, 0x1104), (0x1f4d, 0xa803), (0x1f4d, 0xb803), (0x1f4d, 0xc803),
    (0x1f4d, 0xd286), (0x1f4d, 0xd803),
}
RTL_NAME_HINTS = ("rtl2832", "rtl2838", "rtl-sdr", "rtlsdr", "nesdr", "bulk-in, interface", "dvb-t")
OTHER_SDR_PROGRAMS = (("gqrx", "Gqrx"), ("cubicsdr", "CubicSDR"), ("sdrangel", "SDRangel"), ("rtl_tcp", "rtl_tcp"),
    ("rtl_fm", "rtl_fm"), ("rtl_sdr", "rtl_sdr"), ("rtl_433", "rtl_433"), ("rtl_power", "rtl_power"), ("rtl_adsb", "rtl_adsb"),
    ("rtl_test", "rtl_test"), ("dump1090", "dump1090"), ("readsb", "readsb"), ("openwebrx", "OpenWebRX"),
    ("soapysdrserver", "SoapySDRServer"), ("sdr++", "SDR++"), ("sdrpp", "SDR++"), ("sdrsharp", "SDR#"),
    ("sdrconsole", "SDR Console"), ("cutesdr", "CuteSDR"), ("welle", "welle.io"), ("sdruno", "SDRuno"))
BREW_PKGS = ["soapysdr", "soapyrtlsdr", "librtlsdr"]
BREW_DIRS = ["/opt/homebrew/bin", "/usr/local/bin", "/opt/homebrew/sbin", "/usr/local/sbin"]

INSTALL = {"running": False, "done": False, "ok": None, "log": "", "t0": 0.0}


def _env():
    e = dict(os.environ)
    e["PATH"] = ":".join(BREW_DIRS) + ":" + e.get("PATH", "")
    return e


def _run(cmd, timeout=10):
    """(returncode, text) of a command; never raises. Missing program -> (None, '')."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=_env())
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except FileNotFoundError:
        return None, ""
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        err = e.stderr.decode("utf-8", "replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
        return -9, (out + err)
    except Exception as e:
        return None, str(e)


def _which(name):
    return shutil.which(name, path=_env()["PATH"])


def _hex(v):
    m = re.search(r"0x([0-9a-fA-F]+)", str(v or ""))
    return int(m.group(1), 16) if m else None


def _walk(items, out):
    for it in items or []:
        if not isinstance(it, dict):
            continue
        vid, pid = _hex(it.get("vendor_id")), _hex(it.get("product_id"))
        if vid is not None or pid is not None:
            out.append({"name": it.get("_name", "") or "", "vendor": vid, "product": pid, "serial": it.get("serial_num", "") or "",
                        "vendor_name": str(it.get("manufacturer", "") or "")})
        _walk(it.get("_items"), out)


def _ioreg(text):
    out = []
    for blk in re.split(r"\+-o ", text or ""):
        v = re.search(r'"idVendor"\s*=\s*(\d+)', blk); p = re.search(r'"idProduct"\s*=\s*(\d+)', blk)
        if not (v and p):
            continue
        nm = re.search(r'"USB Product Name"\s*=\s*"([^"]*)"', blk) or re.search(r'"kUSBProductString"\s*=\s*"([^"]*)"', blk)
        sn = re.search(r'"USB Serial Number"\s*=\s*"([^"]*)"', blk) or re.search(r'"kUSBSerialNumberString"\s*=\s*"([^"]*)"', blk)
        out.append({"name": (nm.group(1) if nm else blk.split("<")[0].strip().split("@")[0].strip()), "vendor": int(v.group(1)),
                    "product": int(p.group(1)), "serial": sn.group(1) if sn else "", "vendor_name": ""})
    return out


def usb_quick():
    """The fast list (ioreg): used while you plug and unplug. Mac only; [] if nothing could be read."""
    if sys.platform != "darwin":
        return usb_devices()
    rc, txt = _run(["ioreg", "-r", "-c", "IOUSBHostDevice", "-l", "-w0"], 15)
    devs = _ioreg(txt) if rc == 0 else []
    if not devs:
        rc, txt = _run(["ioreg", "-p", "IOUSB", "-l", "-w0"], 15)
        devs = _ioreg(txt) if rc == 0 else []
    return devs


def usb_devices():
    """The USB devices this computer can see: list of dicts (name, vendor, product, serial). Mac, Linux; Windows is not covered."""
    out = []
    if sys.platform == "darwin":
        for dtype in ("SPUSBDataType", "SPUSBHostDataType"):       # newer macOS lists devices under the second name
            rc, txt = _run(["system_profiler", dtype, "-json", "-detailLevel", "mini"], 40)
            try:
                data = json.loads(txt)
            except Exception:
                data = None
            if data:
                for val in data.values():
                    if isinstance(val, list):
                        _walk(val, out)
            if out:
                return out
        return usb_quick()
    if sys.platform.startswith("linux"):
        rc, txt = _run(["lsusb"], 8)
        for ln in txt.splitlines():
            m = re.search(r"ID ([0-9a-f]{4}):([0-9a-f]{4})\s*(.*)", ln, re.I)
            if m:
                out.append({"name": m.group(3), "vendor": int(m.group(1), 16), "product": int(m.group(2), 16), "serial": "", "vendor_name": ""})
    return out


def rtl_on_usb(devs):
    hits = []
    for d in devs:
        text = ((d.get("name") or "") + " " + (d.get("vendor_name") or "")).lower()
        if ((d.get("vendor"), d.get("product")) in KNOWN_RTL) or any(k in text for k in RTL_NAME_HINTS):
            hits.append(d)
    return hits


def watch_usb():
    """One look for the 'Watch the USB ports' mode: is a dongle visible right now?"""
    devs = usb_quick()
    hits = rtl_on_usb(devs)
    return {"ok": True, "seen": bool(hits), "count": len(devs), "dongles": [h.get("name") or "RTL-SDR" for h in hits], "time": time.strftime("%H:%M:%S")}


def lib_state():
    """What Homebrew's folders hold (only looks at files, so it works even when the programs are not on the PATH)."""
    st = {"prefix": "", "rtl_module": False, "librtlsdr": False, "soapy_lib": False}
    for base in ("/opt/homebrew", "/usr/local"):
        if os.path.isdir(base + "/lib"):
            st["rtl_module"] = st["rtl_module"] or bool(glob.glob(base + "/lib/SoapySDR/modules*/librtlsdrSupport.*"))
            st["librtlsdr"] = st["librtlsdr"] or bool(glob.glob(base + "/lib/librtlsdr*.dylib"))
            st["soapy_lib"] = st["soapy_lib"] or bool(glob.glob(base + "/lib/libSoapySDR*.dylib"))
            if st["soapy_lib"] and not st["prefix"]:
                st["prefix"] = base
    return st


# ---------------------------------------------------------------- Python / Soapy match
def soapy_python_dirs():
    """Where Homebrew put the SoapySDR Python module: list of (python 'X.Y', folder)."""
    res = []
    for base in ("/opt/homebrew", "/usr/local"):
        for f in glob.glob(base + "/lib/python3.*/site-packages/SoapySDR.py") + glob.glob(base + "/lib/python3.*/site-packages/_SoapySDR*"):
            m = re.search(r"/python(3\.\d+)/", f)
            if m:
                res.append((m.group(1), os.path.dirname(f)))
    return sorted(set(res))


def python_match():
    mine = "%d.%d" % sys.version_info[:2]
    found = soapy_python_dirs()
    versions = sorted({v for v, _ in found})
    return {"mine": mine, "brew_versions": versions, "match": (not versions) or (mine in versions), "exe": sys.executable}


# ---------------------------------------------------------------- the checks
def run(cfg=None, other_programs=True):
    """Runs every check. Returns {ok, checks:[{name,status,detail}], answer, fixes:[{id,label,note}], report}."""
    cfg = cfg or {}
    checks = []
    fixes = []

    def add(name, status, detail):          # status: ok | fix | info
        checks.append({"name": name, "status": status, "detail": detail})

    mac = sys.platform == "darwin"
    # 1. USB
    devs = usb_devices()
    hits = rtl_on_usb(devs)
    if not devs and sys.platform == "win32":
        add("USB", "info", "On Windows this check cannot list USB devices. The tests below still run.")
        usb_state = "unknown"
    elif hits:
        add("USB", "ok", "Found on the USB ports: " + "; ".join("%s (id %04x:%04x)" % (h["name"] or "RTL-SDR", h["vendor"] or 0, h["product"] or 0) for h in hits) + ".")
        usb_state = "seen"
    else:
        others = [d["name"] for d in devs if d.get("name")][:12]
        add("USB", "fix", "No RTL-SDR dongle is visible on the USB ports. Plug it straight into the Mac (or a powered hub), try another port and another cable, and press Check again. "
                           "USB devices that are visible: " + (", ".join(others) if others else "none") + ".")
        usb_state = "absent"

    # 2. driver programs
    tools = {n: _which(n) for n in ("rtl_test", "SoapySDRUtil")}
    brew = _which("brew")
    missing = [n for n, p in tools.items() if not p]
    if missing:
        add("Driver programs", "fix", "Not installed: %s. These are the RTL-SDR drivers%s." % (", ".join(missing), " (Homebrew is installed, so one button can add them)" if brew else (" (Homebrew is not installed; run the RFI Trail installer again)" if mac else "")))
        if brew:
            fixes.append({"id": "install_drivers", "label": "Install the RTL-SDR drivers", "note": "Runs  brew install soapysdr soapyrtlsdr librtlsdr  (a few minutes; no password needed)."})
    else:
        add("Driver programs", "ok", "rtl_test and SoapySDRUtil are installed (%s)." % os.path.dirname(tools["rtl_test"]))
    ls = lib_state()
    if ls["soapy_lib"] and not ls["rtl_module"] and not missing:
        add("SoapySDR RTL module", "fix", "SoapySDR is installed but its RTL-SDR module (soapyrtlsdr) is not, so RFI Trail cannot use the dongle even though rtl_test may work.")
        if brew:
            fixes.append({"id": "install_drivers", "label": "Install the RTL-SDR drivers", "note": "Runs  brew install soapysdr soapyrtlsdr librtlsdr  (a few minutes; no password needed)."})
    elif ls["soapy_lib"] and ls["rtl_module"]:
        add("SoapySDR RTL module", "ok", "The SoapySDR RTL-SDR module (soapyrtlsdr) is installed.")

    # 3. rtl_test
    rt_state = "skip"
    rt_text = ""
    if tools["rtl_test"]:
        rc, rt_text = _run([tools["rtl_test"], "-t"], 12)
        low = rt_text.lower()
        if re.search(r"usb_claim_interface error|failed to open rtlsdr|libusb_error_access|libusb_error_busy|resource busy|permission denied|operation not permitted|kernel driver is active|cannot open", low):
            rt_state = "busy"
            add("rtl_test", "fix", "The dongle is there but something else is using it (rtl_test could not take it). Close SDR programs (SDR++, CubicSDR, gqrx, SDRuno, rtl_tcp...) and RFI Trail's own preview, then check again.")
        elif "no supported devices found" in low or "no devices found" in low:
            rt_state = "none"
            add("rtl_test", "fix", "rtl_test sees no dongle. " + ("The USB list above did show one, so the driver or the cable/power is the problem: try another USB port and replug." if usb_state == "seen" else "Check the cable and port first."))
        elif "found" in low and "device" in low:
            rt_state = "ok"
            note = " (the line 'No E4000 tuner found, aborting' is normal for the common R820T dongles)" if "no e4000 tuner found" in low else ""
            pll = " Warning: it reported 'PLL not locked' on some frequencies; that is usually only a weak or hot dongle." if "pll not locked" in low else ""
            add("rtl_test", "ok", "rtl_test found the dongle and can open it" + note + "." + pll)
        else:
            rt_state = "unknown"
            add("rtl_test", "info", "rtl_test gave an answer I do not recognise: " + " ".join(rt_text.split())[:240])
    else:
        add("rtl_test", "info", "Skipped (the driver programs are not installed).")

    # 4. SoapySDRUtil
    su_state = "skip"
    if tools["SoapySDRUtil"]:
        rc, su_text = _run([tools["SoapySDRUtil"], "--find=driver=rtlsdr"], 20)
        if "driver=rtlsdr" in su_text.lower() and "found 0" not in su_text.lower() and "no devices found" not in su_text.lower() and re.search(r"found device", su_text, re.I):
            su_state = "ok"
            add("SoapySDR", "ok", "SoapySDR sees the dongle (the library RFI Trail uses).")
        elif "no devices found" in su_text.lower() or "found 0" in su_text.lower() or su_text.strip():
            su_state = "none"
            add("SoapySDR", "fix" if (usb_state == "seen" or rt_state == "ok") else "info",
                "SoapySDR does not see a dongle" + (" even though rtl_test does: the SoapySDR RTL module (soapyrtlsdr) is missing or broken. Reinstall the drivers." if rt_state == "ok" else "."))
            if rt_state == "ok" and brew:
                fixes.append({"id": "install_drivers", "label": "Reinstall the RTL-SDR drivers", "note": "Runs  brew reinstall soapysdr soapyrtlsdr librtlsdr."})
        else:
            add("SoapySDR", "info", "SoapySDRUtil gave no output.")
    else:
        add("SoapySDR", "info", "Skipped (SoapySDRUtil is not installed).")

    # 5. RFI Trail's own Python
    pm = python_match()
    soapy_note = ""
    try:
        S, soapy_note = C.find_soapy()
    except Exception as e:
        S, soapy_note = None, str(e)
    py_state = "ok" if S is not None else "none"
    if S is not None:
        try:
            import nt_logger as RL
            dl, dnote = RL.rtl_list()
        except Exception as e:
            dl, dnote = [], str(e)
        if dl:
            add("RFI Trail's Python", "ok", "RFI Trail itself sees %d dongle(s): %s." % (len(dl), "; ".join("%s (serial %s)" % (d["label"], d["serial"] or "none") for d in dl)))
            py_state = "sees"
        else:
            add("RFI Trail's Python", "info", "RFI Trail can use SoapySDR but sees no dongle. " + (dnote or ""))
    else:
        if pm["brew_versions"] and not pm["match"]:
            add("RFI Trail's Python", "fix", "RFI Trail runs on Python %s, but the SoapySDR module was built for Python %s. They must match. Run the RFI Trail installer again: it picks the matching Python." % (pm["mine"], " / ".join(pm["brew_versions"])))
            fixes.append({"id": "python_note", "label": "How to fix the Python match", "note": "Run Install_RFI_Trail.command again; it rebuilds RFI Trail's Python to match the radio library."})
        else:
            add("RFI Trail's Python", "fix", "RFI Trail cannot load the radio library (SoapySDR). " + str(soapy_note or "")[:200])
    if pm["brew_versions"] and S is not None and not pm["match"]:
        add("Python versions", "info", "RFI Trail's Python is %s; Homebrew's SoapySDR is for %s. It works for now because the library was found another way." % (pm["mine"], " / ".join(pm["brew_versions"])))

    # 6. other programs holding it
    holders = []
    if other_programs:
        rc, ps = _run(["ps", "-axo", "pid=,args="], 6) if sys.platform != "win32" else (None, "")
        for ln in ps.splitlines():
            low = ln.lower()
            if "rfi trail" in low or "nt_app" in low or "rtl_diag" in low:
                continue
            for key, label in OTHER_SDR_PROGRAMS:
                if key in low and label not in holders:
                    holders.append(label); break
        if holders:
            add("Other programs", "fix" if rt_state in ("busy", "none") else "info", "These may be using the dongle: " + "; ".join(holders[:5]) + ". Close them before measuring.")

    # 7. 'Your radios' ticks
    use_r, use_s = bool(cfg.get("use_rtl")), bool(cfg.get("use_sdrplay", True))
    use_other = any(cfg.get(k) for k in ("use_hl2", "use_anan", "use_cat"))
    dongle_ok = (py_state == "sees") or (su_state == "ok" and rt_state == "ok")
    if dongle_ok and not use_r:
        add("Your radios", "fix", "The dongle works, but 'RTL-SDR dongles' is not ticked in Hardware setup, so slots on Auto never use it.")
        fixes.append({"id": "use_dongle", "label": "Use my dongle (tick RTL-SDR" + (", untick SDRplay)" if use_s and not use_other else ")"),
                      "note": "Ticks RTL-SDR dongles" + (" and unticks SDRplay (you have no SDRplay)." if use_s and not use_other else ".")})
    elif dongle_ok and use_r and use_s and not use_other:
        add("Your radios", "info", "Both RTL-SDR and SDRplay are ticked. Slots on Auto pick the SDRplay first, so with only a dongle you would see 'No SDRplay found'.")
        fixes.append({"id": "use_dongle", "label": "Use my dongle only (untick SDRplay)", "note": "Unticks SDRplay so Auto slots use the dongle."})
    elif use_r:
        add("Your radios", "ok", "RTL-SDR dongles is ticked.")

    # ---- the one plain-English answer
    if dongle_ok and (use_r and (not use_s or use_other)):
        answer = "Your dongle is working and set up. Pick RTL-SDR 1 (or Auto) in a slot's Radio chooser."
    elif dongle_ok:
        answer = "Your dongle works. Press the 'Use my dongle' button below so the slots use it."
    elif usb_state == "absent":
        answer = "The Mac does not see a dongle on its USB ports. Plug it in directly, try another port or cable, then check again."
    elif rt_state == "busy":
        answer = "The dongle is there but another program is using it. Close it (see the list), then check again."
    elif missing:
        answer = "The RTL-SDR drivers are not installed. Press 'Install the RTL-SDR drivers' below."
    elif py_state == "none" and pm["brew_versions"] and not pm["match"]:
        answer = "The drivers work, but RFI Trail's Python does not match the radio library's. Run the RFI Trail installer again."
    elif rt_state == "ok" and su_state != "ok":
        answer = "The dongle works with rtl_test, but SoapySDR cannot see it. Reinstall the drivers (button below)."
    else:
        answer = "I could not find a clear cause. Press 'Save report' and send the report file from the Reports folder."
    fixes = [f for i, f in enumerate(fixes) if f["id"] not in [g["id"] for g in fixes[:i]]]

    res = {"ok": True, "answer": answer, "checks": checks, "fixes": fixes, "dongle_ok": bool(dongle_ok)}
    res["report"] = save_report(res, devs, rt_text)
    return res


def save_report(res, devs, rt_text):
    try:
        d = os.path.join(C.data_dir(), "Reports")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "dongle_check_%s.txt" % time.strftime("%Y%m%d_%H%M%S"))
        lines = ["RFI Trail %s - RTL-SDR dongle check, %s" % (C.VERSION, time.strftime("%Y-%m-%d %H:%M:%S")),
                 "Python %s at %s on %s" % (sys.version.split()[0], sys.executable, sys.platform), "", "ANSWER: " + res["answer"], ""]
        for c in res["checks"]:
            lines.append("[%s] %s: %s" % (c["status"].upper(), c["name"], c["detail"]))
        lines += ["", "USB devices seen:"] + ["  %s  %s:%s" % (x.get("name", ""), "%04x" % x["vendor"] if x.get("vendor") is not None else "?", "%04x" % x["product"] if x.get("product") is not None else "?") for x in devs]
        lines += ["", "rtl_test output:", (rt_text or "(not run)")[:2000]]
        with open(p, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return p
    except Exception:
        return ""


# ---------------------------------------------------------------- one-click driver install (background)
def install_start():
    if INSTALL["running"]:
        return INSTALL
    brew = _which("brew")
    if not brew:
        INSTALL.update(running=False, done=True, ok=False, log="Homebrew is not installed. Run the RFI Trail installer again.")
        return INSTALL
    INSTALL.update(running=True, done=False, ok=None, log="Installing (a few minutes)...\n", t0=time.time())

    def work():
        try:
            e = _env(); e["HOMEBREW_NO_AUTO_UPDATE"] = "1"; e["HOMEBREW_NO_INSTALL_CLEANUP"] = "1"
            p = subprocess.Popen([brew, "install"] + BREW_PKGS, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=e)
            for ln in p.stdout:
                INSTALL["log"] = (INSTALL["log"] + ln)[-4000:]
            p.wait()
            INSTALL.update(ok=(p.returncode == 0))
        except Exception as ex:
            INSTALL.update(ok=False, log=INSTALL["log"] + "\n%s" % ex)
        INSTALL.update(running=False, done=True)
    import threading
    threading.Thread(target=work, daemon=True).start()
    return INSTALL
