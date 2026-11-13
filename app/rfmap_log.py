"""
rfmap_log.py - the program's error log, and the "support file" you can send for help.

Every part of RF Noise Map (the control panel, the logger, the panadapter, and errors seen in your
browser window) writes problems into ONE plain-text file:

    <your data folder>/Logs/program_errors.log

It records errors and warnings with the date, time and which part reported them, plus a one-line
"started" note each time the program opens. Nothing is sent anywhere. If something goes wrong,
press "Make a support file" in the panel (or run Make_Support_File) and send the zip it makes.

Command line:   python rfmap_log.py --tail      show the end of the log
                python rfmap_log.py --bundle    make the support zip and print where it is
"""
import glob
import os
import platform
import sys
import threading
import time
import traceback
import zipfile

import rfmap_common as C

LOG_NAME = "program_errors.log"
MAX_BYTES = 1_500_000          # the log is trimmed (old part moved aside) when it grows past this at start-up
_lock = threading.Lock()
_component = "program"
_recent = {}                   # message -> (time of first, count suppressed)
_ready = False


def log_dir():
    p = C.sub_dir("Logs")
    try:
        os.makedirs(p, exist_ok=True)
    except OSError:
        pass
    return p


def log_path():
    return os.path.join(log_dir(), LOG_NAME)


def _write(level, msg):
    line = "%s [%s] %s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), _component, level, msg.rstrip())
    try:
        with _lock:
            with open(log_path(), "a", encoding="utf-8", errors="replace") as f:     # open/append/close: safe for several programs at once
                f.write(line)
    except Exception:
        pass                                                                          # logging must never break the program


def _dedupe(level, msg):
    """The same message repeated within a minute is written once, with a count later, so a fault cannot flood the log."""
    key = level + msg[:200]
    now = time.time()
    t0, n = _recent.get(key, (0, 0))
    if now - t0 < 60:
        _recent[key] = (t0, n + 1)
        return False
    if n:
        _write("INFO", "(the previous message repeated %d more times)" % n)
    _recent[key] = (now, 0)
    return True


def info(msg):
    _write("INFO", msg)


def warn(msg):
    if _dedupe("WARN", msg):
        _write("WARN", msg)


def error(msg, exc=None):
    if exc is not None:
        msg = "%s: %s: %s\n%s" % (msg, type(exc).__name__, exc,
                                  "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).rstrip())
    if _dedupe("ERROR", msg.split("\n")[0]):
        _write("ERROR", msg)


def exception(where):
    """Call inside an `except` block: records the problem with its full traceback."""
    error(where, sys.exc_info()[1])


def setup(component):
    """Start logging for this program part; also catches any crash that nothing else handles."""
    global _component, _ready
    _component = component
    if _ready:
        return
    _ready = True
    try:
        p = log_path()
        if os.path.exists(p) and os.path.getsize(p) > MAX_BYTES and component == "panel":
            old = p + ".1"
            if os.path.exists(old):
                os.remove(old)
            os.replace(p, old)
    except Exception:
        pass
    _write("INFO", "---- %s started: RF Noise Map %s, Python %s, %s ----" % (component, C.VERSION, platform.python_version(), platform.platform()))

    prev = sys.excepthook

    def hook(et, ev, tb):
        try:
            _write("ERROR", "UNHANDLED CRASH\n" + "".join(traceback.format_exception(et, ev, tb)).rstrip())
        finally:
            prev(et, ev, tb)
    sys.excepthook = hook
    if hasattr(threading, "excepthook"):
        def thook(a):
            _write("ERROR", "UNHANDLED ERROR in thread %s\n%s" % (getattr(a.thread, "name", "?"),
                   "".join(traceback.format_exception(a.exc_type, a.exc_value, a.exc_traceback)).rstrip()))
        threading.excepthook = thook


def tail(n=60):
    try:
        with open(log_path(), encoding="utf-8", errors="replace") as f:
            return [l.rstrip("\n") for l in f.readlines()[-n:]]
    except OSError:
        return []


def system_info():
    out = ["RF Noise Map %s" % C.VERSION, "Time: %s" % time.strftime("%Y-%m-%d %H:%M:%S %z"),
           "Computer: %s" % platform.platform(), "Machine: %s" % platform.machine(),
           "Python: %s (%s)" % (platform.python_version(), sys.executable),
           "Program folder: %s" % C.app_dir(), "Data folder: %s" % C.data_dir()]
    for mod in ("numpy", "serial", "SoapySDR"):
        try:
            m = __import__(mod)
            out.append("%s: %s" % (mod, getattr(m, "__version__", None) or getattr(m, "VERSION", None) or "present"))
        except Exception as e:
            out.append("%s: NOT AVAILABLE (%s: %s)" % (mod, type(e).__name__, str(e)[:160]))
    try:
        import shutil
        du = shutil.disk_usage(C.data_dir())
        out.append("Disk space free where your data is: %.1f GB" % (du.free / 1e9))
    except Exception:
        pass
    return "\n".join(out) + "\n"


def make_bundle():
    """Zip the logs and settings (without the private access key) into Logs/. Returns the zip's path."""
    data = C.data_dir()
    ld = log_dir()
    out = os.path.join(ld, "RFNoise_support_%s.zip" % time.strftime("%Y%m%d_%H%M%S"))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("system_info.txt", system_info())
        names = glob.glob(os.path.join(ld, "program_errors.log*")) + glob.glob(os.path.join(ld, "install_log*.txt"))
        names += [os.path.join(data, "install_log.txt"), os.path.join(data, "full_test_report.txt"),
                  os.path.join(data, "Settings", "logger.log"), os.path.join(data, "Settings", "app.log")]
        seen = set()
        for p in sorted(names)[-40:]:
            if os.path.isfile(p) and p not in seen:
                seen.add(p)
                z.write(p, os.path.basename(p))
        cfg = os.path.join(data, "Settings", "config.json")
        if os.path.isfile(cfg):
            try:
                import json
                d = json.load(open(cfg))
                d.pop("token", None)
                z.writestr("config_without_key.json", json.dumps(d, indent=2))
            except Exception:
                pass
        mac_log = os.path.expanduser("~/Library/Logs/RFNoiseMap.log")
        if os.path.isfile(mac_log):
            try:
                with open(mac_log, errors="replace") as f:
                    z.writestr("RFNoiseMap_mac_launcher_log_last_600_lines.txt", "".join(f.readlines()[-600:]))
            except Exception:
                pass
    return out


if __name__ == "__main__":
    if "--bundle" in sys.argv:
        print(make_bundle())
    else:
        print("\n".join(tail(80)) or "(the error log is empty: no problems have been recorded)")
