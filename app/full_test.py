"""
full_test.py - the automatic "is everything working?" test. About one minute. Nothing for you to click.

  1. Software     Python, the math library, the USB-GPS library, the radio library
  2. Radio        opens the SDRplay, takes real readings on your frequencies, checks the gain control
  3. GPS          looks for a USB GPS puck by itself (port and speed) and checks for a position fix
  4. Mock drive   runs a pretend drive with the REAL radio, saves it, and builds a map from it

Run it:   Test_Everything.bat   (or press 'Full test' in the RF Noise Map window)
Options:  --gps-wait 120   wait up to 120 s for the GPS to get a position (take the puck outside first)
          --iphone         you use the iPhone GPS: do not treat 'no USB GPS' as a problem
          --json           machine-readable output (used by the RF Noise Map window)
"""

import argparse
import copy
import gc
import glob
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time

import rfmap_common as C

HERE = os.path.dirname(os.path.abspath(__file__))


class Report:
    def __init__(self, emit=None):
        self.items = []
        self.emit = emit

    def add(self, step, status, message):
        """status: ok | warn | fix | info"""
        self.items.append({"step": step, "status": status, "message": message})
        if self.emit:
            self.emit(step, status, message)


def _free_port(start=8900):
    import socket
    for p in range(start, start + 60):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return start


def _python_exe():
    exe = sys.executable
    if C.IS_WIN and exe.lower().endswith("pythonw.exe"):
        alt = exe[:-len("pythonw.exe")] + "python.exe"
        if os.path.exists(alt):
            return alt
    return exe


# ---------------------------------------------------------------- 1. software
def test_software(r):
    py = ".".join(map(str, sys.version_info[:3]))
    r.add("Software", "ok" if sys.version_info >= (3, 8) else "fix", f"Python {py}")
    try:
        import numpy
        r.add("Software", "ok", f"numpy {numpy.__version__} (math library)")
    except ImportError:
        r.add("Software", "fix", "numpy is missing. Run Install_RFNoise.bat again.")
    try:
        import serial
        r.add("Software", "ok", f"pyserial {getattr(serial, '__version__', '?')} (USB GPS library)")
    except ImportError:
        r.add("Software", "warn", "pyserial is missing, so a USB GPS cannot be used (iPhone GPS still works). "
                                  "Run Install_RFNoise.bat again.")
    soapy, note = C.find_soapy()
    if soapy is None:
        r.add("Software", "fix", "Radio library (SoapySDR) not usable. " + note)
        return None
    r.add("Software", "ok", "Radio library (SoapySDR) loads. " + (C.PRELOAD_NOTE or ""))
    # Python version vs PothosSDR's Python folder (Windows)
    if C.IS_WIN:
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        libs = glob.glob(os.path.join(pf, "PothosSDR", "lib", "python*"))
        want = [os.path.basename(x)[6:] for x in libs]
        have = f"{sys.version_info[0]}.{sys.version_info[1]}"
        if want and have not in want:
            r.add("Software", "warn", f"PothosSDR was built for Python {', '.join(want)} but this is Python {have}.")
    return soapy


# ---------------------------------------------------------------- 2. radio
def test_radio(r, soapy):
    if soapy is None:
        r.add("Radio", "fix", "Skipped: the radio library is not available (see above).")
        return False
    try:
        devs = [dict(d) for d in soapy.Device.enumerate("driver=sdrplay")]
    except Exception as e:
        r.add("Radio", "fix", f"Could not ask for the radio: {e}")
        return False
    if not devs:
        r.add("Radio", "fix", "No SDRplay found. Is it plugged in directly? Is the 'SDRplay API Service' running "
                              "(Windows Services)? Is another program (SDRuno, SDRconnect, SDR Console) using it?")
        return False
    r.add("Radio", "ok", "Found " + str(devs[0].get("label", "SDRplay")))
    import rf_logger
    settings = copy.deepcopy(rf_logger.DEFAULT_SETTINGS)
    # use the saved frequencies if there are any
    for cand in (os.path.join(C.data_dir(), "Settings", "settings.json"),
                 os.path.join(C.data_dir(), "Settings", "logger_settings.json")):
        try:
            with open(cand) as f:
                settings.update(json.load(f))
            break
        except Exception:
            pass
    try:
        sdr = rf_logger.SoapySdr(settings)
    except SystemExit as e:
        r.add("Radio", "fix", "Could not open the radio: " + str(e).strip()[:200])
        return False
    except Exception as e:
        r.add("Radio", "fix", f"Could not open the radio: {e}")
        return False
    ok = True
    try:
        for ch in settings["channels"][:4]:
            hz, bw = ch["mhz"] * 1e6, ch["bw_khz"] * 1e3
            vals = [sdr.measure(hz, bw, 0, 0, settings) for _ in range(3)]
            if any(math.isnan(v) for v in vals):
                r.add("Radio", "fix", f"{ch['mhz']} MHz: the radio stopped delivering data (try unplugging it).")
                ok = False
                continue
            lo, hi = min(vals), max(vals)
            txt = f"{ch['mhz']} MHz: {sum(vals)/3:.1f} dBFS (3 readings, {lo:.1f} to {hi:.1f})"
            if hi > -12:
                r.add("Radio", "warn", txt + " - very strong: the radio may be overloaded. Raise 'IF gain reduction'.")
            elif hi < -108:
                r.add("Radio", "warn", txt + " - extremely low. Is the antenna connected? (Normal on a very quiet channel.)")
            else:
                r.add("Radio", "ok", txt)
        # does the gain control do anything?
        ch = settings["channels"][0]
        hz, bw = ch["mhz"] * 1e6, ch["bw_khz"] * 1e3
        s_lo = dict(settings, if_gain_db=25)
        s_hi = dict(settings, if_gain_db=55)
        a = sum(sdr.measure(hz, bw, 0, 0, s_lo) for _ in range(3)) / 3
        b = sum(sdr.measure(hz, bw, 0, 0, s_hi) for _ in range(3)) / 3
        if a - b > 8:
            r.add("Radio", "ok", f"Gain control works (readings drop {a-b:.0f} dB when the gain is lowered).")
        else:
            r.add("Radio", "warn", f"Gain control changed the reading by only {a-b:.0f} dB (expected about 30). "
                                   "Readings may still be usable; tell Claude if this repeats.")
    finally:
        try:
            sdr.close()
            sdr.dev = None
        except Exception:
            pass
        gc.collect()
        time.sleep(1.0)               # let go of the radio so the mock drive can open it
    return ok


# ---------------------------------------------------------------- 3. GPS
def test_gps(r, gps_wait, iphone):
    import gps_detect
    res = gps_detect.find_gps(budget_s=45, listen=2.5)
    if not res["found"]:
        status = "info" if iphone else "warn"
        r.add("GPS", status, res["note"] + ("  (You use the iPhone GPS, so this is fine.)" if iphone else
              "  If you use the iPhone with GPS2IP, ignore this."))
        return None
    f = res["found"][0]
    r.add("GPS", "ok", f"USB GPS found: {f['port']} at speed {f['baud']} ({f['desc'] or 'serial device'}).")
    fix, sats = f["fix"], f["sats"]
    t0 = time.time()
    while not fix and gps_wait and time.time() - t0 < gps_wait:
        time.sleep(1)
        p = gps_detect.probe(f["port"], f["baud"], 2.0)
        fix, sats = p["fix"], p["sats"] if p["sats"] is not None else sats
    if fix:
        r.add("GPS", "ok", f"Position fix OK ({sats if sats is not None else '?'} satellites).")
    else:
        r.add("GPS", "warn", "The puck talks but has no position fix yet. Take it outside (or to a window) and run "
                             "the test again; a first fix can take up to 5 minutes.")
    return {"port": f["port"], "baud": f["baud"], "fix": fix}


# ---------------------------------------------------------------- 4. mock drive
def test_drive(r, radio_ok, seconds=25):
    tmp = tempfile.mkdtemp(prefix="rfmap_test_")
    try:
        port = _free_port()
        sdr_kind = "sdrplay" if radio_ok else "sim"
        cmd = [_python_exe(), "-u", os.path.join(HERE, "rf_logger.py"), "--gps", "sim", "--sdr", sdr_kind,
               "--outdir", tmp, "--settings", os.path.join(tmp, "s.json"), "--port", str(port),
               "--local-only", "--name", "Self-test", "--sim-speed", "20"]
        kw = {"creationflags": 0x08000000} if C.IS_WIN else {}
        log = open(os.path.join(tmp, "logger.txt"), "w")
        p = subprocess.Popen(cmd, cwd=HERE, stdout=log, stderr=subprocess.STDOUT, **kw)
        t0 = time.time()
        while time.time() - t0 < seconds and p.poll() is None:
            time.sleep(0.5)
        died = p.poll() is not None and p.returncode not in (0, None)
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=8)
            except subprocess.TimeoutExpired:
                p.kill()
        log.close()
        csvs = glob.glob(os.path.join(tmp, "*.csv"))
        if not csvs:
            tail = open(os.path.join(tmp, "logger.txt")).read()[-300:]
            r.add("Mock drive", "fix", "The logger did not start. " + tail.strip())
            return False
        import csv
        rows = list(csv.DictReader(open(csvs[0], newline="")))
        levels = []
        for row in rows:
            try:
                v = float(row["level_dbfs"])
                if not math.isnan(v):
                    levels.append(v)
            except (ValueError, KeyError):
                pass
        what = "the real radio" if radio_ok else "a pretend radio (the real one was not usable)"
        if died and not rows:
            r.add("Mock drive", "fix", "The logger stopped early.")
            return False
        if len(rows) < 10:
            r.add("Mock drive", "fix", f"Only {len(rows)} readings were saved in {seconds} seconds with {what}.")
            return False
        spread = (max(levels) - min(levels)) if levels else 0
        r.add("Mock drive", "ok", f"Saved {len(rows)} readings using {what}; levels from "
                                  f"{min(levels):.1f} to {max(levels):.1f} dBFS.")
        import make_map
        out, counts = make_map.build_map(csvs, os.path.join(tmp, "test_map.html"), "Self-test")
        size = os.path.getsize(out)
        r.add("Mock drive", "ok" if size > 20000 else "warn",
              f"Map built ({size//1024} KB, dots per frequency: " +
              ", ".join(f"{k} MHz: {v}" for k, v in sorted(counts.items(), key=lambda kv: float(kv[0]))) + ").")
        return True
    except Exception as e:
        r.add("Mock drive", "fix", f"The mock drive failed: {e}")
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_all(emit=None, gps_wait=0, iphone=False, skip_drive=False):
    r = Report(emit)
    soapy = test_software(r)
    radio_ok = test_radio(r, soapy)
    test_gps(r, gps_wait, iphone)
    if not skip_drive:
        test_drive(r, radio_ok)
    bad = [i for i in r.items if i["status"] == "fix"]
    warn = [i for i in r.items if i["status"] == "warn"]
    if not bad and not warn:
        verdict = "READY. Everything works. You can go for a real drive."
    elif not bad:
        verdict = "NEARLY READY. Everything essential works; see the notes marked WARN above."
    else:
        verdict = f"NOT READY. {len(bad)} problem(s) marked FIX above need attention."
    r.add("Result", "ok" if not bad else "fix", verdict)
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gps-wait", type=int, default=0)
    ap.add_argument("--iphone", action="store_true")
    ap.add_argument("--no-drive", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--report", help="also save the text report to this file")
    a = ap.parse_args()
    tag = {"ok": "[ OK ]", "warn": "[WARN]", "fix": "[FIX ]", "info": "[ -- ]"}
    lines = []

    def emit(step, status, msg):
        line = f"{tag[status]} {step}: {msg}"
        lines.append(line)
        if not a.json:
            print(line, flush=True)

    if not a.json:
        print("RF Noise Map full test - about one minute. Please wait...\n", flush=True)
    r = run_all(emit, a.gps_wait, a.iphone, a.no_drive)
    if a.json:
        print(json.dumps(r.items))
    if a.report:
        try:
            with open(a.report, "w", encoding="utf-8") as f:
                f.write(f"RF Noise Map full test  {time.strftime('%Y-%m-%d %H:%M:%S')}  version {C.VERSION}\n\n")
                f.write("\n".join(lines) + "\n")
        except OSError:
            pass
    return 0 if r.items[-1]["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
