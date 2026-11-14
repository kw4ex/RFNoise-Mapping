#!/usr/bin/env python3
"""
rfmap_app.py - the RF Noise Map control panel.

Double-click the "RF Noise Map" icon and this program starts a small web page on your own
computer and opens it in your browser. Every button on that page ends up in a function here.

HOW THE PROGRAM FLOWS
  main()  -> find a free port, start the little web server, open the browser
  Browser -> asks the server for information (/api/state, /api/live) and sends button
             presses (/api/start, /api/stop, /api/map, /api/email ...)
  Start   -> launches rf_logger.py as a separate program that writes the CSV
  Make map-> calls make_map.build_map() and shows the finished HTML map

Your data lives next to the program (Windows install: C:\\RadioScripts\\RFNoise) or, on a Mac,
in the "RF Noise Map" folder in your home folder (Mac) - in the folders {Drives, Maps, Exports, Backups, Settings}
"""
import argparse
import csv
import json
import math
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
import zipfile
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

import rfmap_common as C
import rfmap_log as L
import check_setup
import gps_detect
import device_guard
import make_map
from panadapter import PAN, REC, REC_RATE, REC_HEADER
from slices import SLICES
import hl2

DEFAULT_PORT = 8780
LOGGER_PORT = 8765
HERE = C.app_dir()
from panadapter import AUDIO_RATE as C_AUDIO_RATE

DEFAULT_CONFIG = {
    "route_name": "",
    "practice": False,
    "gps_mode": "iphone",            # iphone | usb
    "gps_host": "172.20.10.1",       # the iPhone's usual address on its own Personal Hotspot
    "gps_port": 11123,               # GPS2IP's usual port
    "gps_serial": "",
    "gps_baud": 9600,
    "auto_map": True,
    "spacing_ft": 10,
    "sample_mode": "distance",
    "interval_s": 5,
    "if_gain_db": 40,
    "rf_gain_state": 0,
    "use_sdrplay": True,             # the radios you have; each frequency slot picks one of them
    "use_hl2": False,
    "hl2_ip": "",                    # empty = search the network
    "hl2_rate": 96000,               # samples per second per receiver: 48000, 96000, 192000 or 384000
    "hl2_gain_db": 15,               # Hermes Lite 2 low-noise-amplifier gain, -12 to +48
    "channels": [
        {"mhz": 3.700, "bw_khz": 5.0, "cal_db": 0.0, "radio": "auto"},
        {"mhz": 7.300, "bw_khz": 5.0, "cal_db": 0.0, "radio": "auto"},
        {"mhz": 148.000, "bw_khz": 10.0, "cal_db": 0.0, "radio": "auto"},
        {"mhz": "", "bw_khz": 5.0, "cal_db": 0.0, "radio": "auto"},
    ],
    "pan_mem": None,                 # saved panadapter memory frequencies (None = show the starter list)
    "phone_access": False,           # let an iPhone/iPad open this window too (needs restart)
    "token": "",
}


# ----------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------
def python_exe():
    """The Python to launch helpers with (on Windows the window-less pythonw.exe is swapped for python.exe)."""
    exe = sys.executable
    if C.IS_WIN and exe.lower().endswith("pythonw.exe"):
        alt = exe[:-len("pythonw.exe")] + "python.exe"
        if os.path.exists(alt):
            return alt
    return exe


def free_port(start):
    import socket
    for p in range(start, start + 50):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return start


def safe_name(name, folder, exts):
    """Accept only a plain file name that really exists in `folder`."""
    name = os.path.basename(name or "")
    path = os.path.join(folder, name)
    if not name or not name.lower().endswith(exts) or not os.path.isfile(path):
        raise ValueError("File not found: " + name)
    return path


def open_path(path, reveal=False):
    """Open a folder/file with the computer's normal program (or show it in Finder/Explorer)."""
    try:
        if C.IS_MAC:
            subprocess.Popen(["open", "-R", path] if reveal else ["open", path])
        elif C.IS_WIN:
            if reveal:
                subprocess.Popen(["explorer", f"/select,{os.path.normpath(path)}"])
            else:
                os.startfile(path)  # noqa
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path) if reveal else path],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def dist_m(a, b):
    kx = 111320.0 * math.cos(math.radians((a[0] + b[0]) / 2))
    return math.hypot((b[1] - a[1]) * kx, (b[0] - a[0]) * 111320.0)


# ----------------------------------------------------------------------------
def close_browser_tabs(port):
    """After Quit: ask the Mac's browser to close the RF Noise Map tab(s) so no dead window is left behind.
    Only browsers that are already running are asked (never started), and any failure is ignored."""
    if not C.IS_MAC:
        return
    import subprocess
    for app in ("Safari", "Google Chrome", "Microsoft Edge", "Brave Browser", "Arc", "Chromium"):
        try:
            if subprocess.run(["pgrep", "-x", app], capture_output=True, timeout=2).returncode != 0:
                continue
            for host in ("localhost", "127.0.0.1"):
                url = "http://%s:%d" % (host, port)
                script = ('tell application "%s"\nrepeat with w in (every window)\ntry\n'
                          'close (every tab of w whose URL starts with "%s")\nend try\nend repeat\nend tell') % (app, url)
                subprocess.run(["osascript", "-e", script], capture_output=True, timeout=4)
        except Exception:
            pass


# The application state (one instance)
# ----------------------------------------------------------------------------
class App:
    def __init__(self):
        self.data = C.data_dir()
        self.drives_dir = C.sub_dir("Drives")
        self.maps_dir = C.sub_dir("Maps")
        self.exports_dir = C.sub_dir("Exports")
        self.backups_dir = C.sub_dir("Backups")
        self.rec_dir = C.sub_dir("Recordings")
        self.settings_dir = C.sub_dir("Settings")
        self.cfg_path = os.path.join(self.settings_dir, "config.json")
        self.cfg = json.loads(json.dumps(DEFAULT_CONFIG))
        raw = {}
        if os.path.exists(self.cfg_path):
            try:
                with open(self.cfg_path) as f:
                    raw = json.load(f)
                self.cfg.update(raw)
            except Exception:
                pass
        # Earlier versions had ONE radio picker ("radio": sdrplay|hl2). Carry that choice over once.
        old = self.cfg.pop("radio", None)
        if old is not None and "use_hl2" not in raw:
            self.cfg["use_hl2"] = (old == "hl2")
            self.cfg["use_sdrplay"] = (old != "hl2")
        for ch in self.cfg.get("channels", []):
            ch.setdefault("radio", "auto")
        if not self.cfg.get("token"):
            self.cfg["token"] = secrets.token_urlsafe(12)
        self.save_cfg()
        self.lock = threading.Lock()
        self.proc = None
        self.logger_port = LOGGER_PORT
        self.logger_log = os.path.join(self.settings_dir, "logger.log")
        self.active_csv = None
        self._cache = {}
        self.port = DEFAULT_PORT
        self.server = None

    # ---- config
    def save_cfg(self):
        with open(self.cfg_path, "w") as f:
            json.dump(self.cfg, f, indent=2)

    def recordings(self):
        out = []
        for fn in sorted(os.listdir(self.rec_dir), reverse=True):
            if not fn.lower().endswith(".wav"):
                continue
            p = os.path.join(self.rec_dir, fn)
            try:
                size = os.path.getsize(p)
                out.append({"file": fn, "size_kb": round(size / 1024),
                            "seconds": round(max(0, size - REC_HEADER) / float(REC_RATE), 1),
                            "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(p)))})
            except OSError:
                pass
        return out

    def update_cfg(self, new):
        allowed = set(DEFAULT_CONFIG) - {"token"}
        with self.lock:
            for k, v in new.items():
                if k in allowed:
                    self.cfg[k] = v
            self.save_cfg()

    # ---- logger process control
    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def gps_spec(self):
        c = self.cfg
        if c["practice"]:
            return "sim"
        if c["gps_mode"] == "usb":
            if not c["gps_serial"]:
                raise ValueError("Pick the USB GPS port first (or choose iPhone / Practice mode).")
            return f"serial:{c['gps_serial']}:{int(c['gps_baud'])}"
        if not c["gps_host"]:
            raise ValueError("Type the iPhone address shown in the GPS2IP app.")
        return f"tcp:{c['gps_host']}:{int(c['gps_port'])}"

    HL2_MAX_MHZ = 38.0

    def resolve_radio(self, mhz, want, practice=False):
        """Which radio measures this frequency slot. want = auto | hl2 | sdrplay (the slot's choice)."""
        if practice:
            return "sdrplay"                       # practice mode simulates everything anyway
        use_s = bool(self.cfg.get("use_sdrplay", True))
        use_h = bool(self.cfg.get("use_hl2", False))
        if not use_s and not use_h:
            raise ValueError("Tick at least one radio in 'Your radios' (or tick Practice mode).")
        w = want if want in ("hl2", "sdrplay") else "auto"
        if w == "hl2":
            if not use_h:
                raise ValueError(f"The {mhz:g} MHz slot is set to the Hermes Lite 2, but that radio is not "
                                 "ticked in 'Your radios'. Tick it, or set the slot's Radio to Auto.")
            if mhz > self.HL2_MAX_MHZ:
                raise ValueError(f"{mhz:g} MHz is above what the Hermes Lite 2 can receive (about "
                                 f"{self.HL2_MAX_MHZ:g} MHz). Set that slot's Radio to SDRplay or Auto.")
            return "hl2"
        if w == "sdrplay":
            if not use_s:
                raise ValueError(f"The {mhz:g} MHz slot is set to the SDRplay, but that radio is not "
                                 "ticked in 'Your radios'. Tick it, or set the slot's Radio to Auto.")
            return "sdrplay"
        # Auto: the Hermes Lite 2 takes everything it can hear (its receivers all run at once);
        # the SDRplay takes the rest.
        if use_h and mhz <= self.HL2_MAX_MHZ:
            return "hl2"
        if use_s:
            return "sdrplay"
        raise ValueError(f"{mhz:g} MHz needs the SDRplay radio (the Hermes Lite 2 stops at about "
                         f"{self.HL2_MAX_MHZ:g} MHz), but only the Hermes Lite 2 is ticked in 'Your radios'.")

    def clean_channels(self, chans, practice=None):
        """Checks the frequency slots and works out each slot's radio. Returns the list the logger uses."""
        if practice is None:
            practice = bool(self.cfg.get("practice"))
        out = []
        for ch in chans[:4]:
            if str(ch.get("mhz", "")).strip() == "":
                continue
            mhz = float(ch["mhz"])
            if not (0.001 <= mhz <= 2000):
                raise ValueError(f"{mhz} MHz is outside the radio's range (0.001 to 2000 MHz).")
            out.append({"mhz": mhz, "bw_khz": max(0.5, float(ch.get("bw_khz") or 5)),
                        "cal_db": float(ch.get("cal_db") or 0),
                        "radio": self.resolve_radio(mhz, str(ch.get("radio") or "auto"), practice)})
        if not out:
            raise ValueError("Enter at least one frequency.")
        return out

    def start(self):
        if self.running():
            raise ValueError("Already logging.")
        PAN.stop(); SLICES.stop()                          # the radio can only do one job: close the panadapter first
        c = self.cfg
        spec = self.gps_spec()
        chans = self.clean_channels(c["channels"])
        self.active_radios = sorted({ch["radio"] for ch in chans})
        settings_file = os.path.join(self.settings_dir, "logger_settings.json")
        with open(settings_file, "w") as f:
            json.dump({"channels": chans, "spacing_ft": max(2.0, float(c["spacing_ft"])), "paused": False,
                       "sample_mode": "time" if c.get("sample_mode") == "time" else "distance",
                       "interval_s": min(max(0.5, float(c.get("interval_s", 5))), 3600.0),
                       "if_gain_db": int(c["if_gain_db"]), "rf_gain_state": int(c["rf_gain_state"]),
                       "hl2_gain_db": int(c.get("hl2_gain_db", 15))}, f)
        self.logger_port = free_port(LOGGER_PORT)
        cmd = [python_exe(), "-u", os.path.join(HERE, "rf_logger.py"),
               "--gps", spec, "--sdr", "sim" if c["practice"] else "multi",
               "--outdir", self.drives_dir, "--settings", settings_file,
               "--port", str(self.logger_port), "--local-only", "--name", c.get("route_name", "")]
        if c["practice"]:
            cmd += ["--sim-speed", os.environ.get("RFMAP_SIM_SPEED", "20")]
        elif "hl2" in self.active_radios:
            rate = int(c.get("hl2_rate", 96000))
            cmd += ["--hl2-ip", str(c.get("hl2_ip", "")).strip(),
                    "--hl2-rate", str(rate if rate in (48000, 96000, 192000, 384000) else 96000)]
        log = open(self.logger_log, "w")
        kw = {}
        if C.IS_WIN:
            kw["creationflags"] = 0x08000000        # CREATE_NO_WINDOW
        self.proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=HERE, **kw)
        # wait for it to come up (or die with a message)
        t0 = time.time()
        while time.time() - t0 < 12:
            if self.proc.poll() is not None:
                raise ValueError(self.log_tail() or "The logger stopped right away.")
            st = self.logger_status()
            if st:
                self.active_csv = os.path.basename(st.get("file", ""))
                return
            time.sleep(0.25)
        raise ValueError("The logger did not start in time. " + self.log_tail())

    def logger_raw(self, path, timeout=1.5):
        """GET raw bytes (plus X-Seq/X-Rate) from the logger process."""
        r = urllib.request.urlopen("http://127.0.0.1:%d%s" % (self.logger_port, path), timeout=timeout)
        return r.read(), dict(r.headers)

    def logger_call(self, path, body=None, timeout=1.5):
        url = f"http://127.0.0.1:{self.logger_port}{path}"
        req = urllib.request.Request(url, data=(None if body is None else json.dumps(body).encode()),
                                     method="GET" if body is None else "POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")

    def logger_status(self):
        if not self.running():
            return None
        try:
            st = self.logger_call("/status", timeout=0.8)
            if st.get("file"):
                self.active_csv = os.path.basename(st["file"])
            return st
        except Exception:
            return None

    def log_tail(self, n=12):
        try:
            with open(self.logger_log, errors="replace") as f:
                lines = [l.rstrip() for l in f.readlines() if l.strip()]
            return "\n".join(lines[-n:])
        except Exception:
            return ""

    def stop(self):
        csv_name = self.active_csv
        if self.running():
            try:
                self.logger_call("/stop", {}, timeout=2)
            except Exception:
                pass
            try:
                self.proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.proc.terminate()
        self.proc = None
        self.active_csv = None
        return csv_name

    # ---- drives
    def meta_path(self, csv_path):
        return csv_path[:-4] + ".meta.json"

    def read_meta(self, csv_path):
        try:
            with open(self.meta_path(csv_path)) as f:
                return json.load(f)
        except Exception:
            return {}

    def drive_info(self, path):
        st = os.stat(path)
        key = (st.st_mtime, st.st_size)
        hit = self._cache.get(path)
        if hit and hit[0] == key:
            return hit[1]
        times, pts, freqs = [], [], set()
        last_t = None
        try:
            with open(path, newline="") as f:
                for r in csv.DictReader(f):
                    try:
                        t = r["time_utc"]
                        freqs.add(float(r["freq_mhz"]))
                        if t != last_t:
                            last_t = t
                            times.append(t)
                            pts.append((float(r["lat"]), float(r["lon"])))
                    except (KeyError, ValueError):
                        continue
        except Exception:
            pass
        meters = sum(dist_m(a, b) for a, b in zip(pts, pts[1:]))
        info = {"dots": len(pts), "freqs": sorted(freqs), "miles": round(meters / 1609.344, 2),
                "first": times[0] if times else "", "size_kb": round(st.st_size / 1024, 1)}
        self._cache[path] = (key, info)
        return info

    def drives(self):
        out = []
        files = [f for f in os.listdir(self.drives_dir) if f.lower().endswith(".csv")]
        for fn in sorted(files, reverse=True):
            path = os.path.join(self.drives_dir, fn)
            meta = self.read_meta(path)
            recording = self.running() and fn == self.active_csv
            info = ({"dots": None, "freqs": [], "miles": None, "first": "", "size_kb": round(os.path.getsize(path) / 1024, 1)}
                    if recording else self.drive_info(path))
            out.append(dict(info, file=fn, name=meta.get("name") or fn[:-4], notes=meta.get("notes", ""),
                            recording=recording, practice=fn.endswith("_PRACTICE.csv"),
                            modified=datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")))
        return out

    def maps(self):
        out = []
        for fn in sorted(os.listdir(self.maps_dir), key=lambda f: os.path.getmtime(os.path.join(self.maps_dir, f)),
                         reverse=True):
            if fn.lower().endswith(".html"):
                p = os.path.join(self.maps_dir, fn)
                out.append({"file": fn, "size_kb": round(os.path.getsize(p) / 1024),
                            "modified": datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M")})
        return out

    def exports(self):
        return [{"file": fn, "size_kb": round(os.path.getsize(os.path.join(self.exports_dir, fn)) / 1024)}
                for fn in sorted(os.listdir(self.exports_dir), reverse=True)]

    # ---- actions
    def make_map(self, files, title=None, spacing_ft=None, pick="peak"):
        paths = [safe_name(f, self.drives_dir, (".csv",)) for f in files]
        if not paths:
            raise ValueError("Choose at least one drive.")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if len(paths) == 1:
            base = os.path.basename(paths[0])[:-4]
            meta = self.read_meta(paths[0])
            title = title or meta.get("name") or base
        else:
            base = f"combined_{stamp}"
            title = title or f"Combined map ({len(paths)} drives)"
        sp = self._clean_spacing(spacing_ft)
        pick = "average" if pick == "average" else "peak"
        out = os.path.join(self.maps_dir, base + (("_%gft" % sp) if sp else "") + "_map.html")
        out, counts = make_map.build_map(paths, out, title, sp, pick)
        return {"map": os.path.basename(out), "counts": counts}

    @staticmethod
    def _clean_spacing(v):
        """Map-time dot spacing in feet (None = show every reading as recorded)."""
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        if v <= 0:
            return None
        return min(max(v, 2.0), 5280.0)

    def make_kml(self, fname, spacing_ft=None, pick="peak"):
        path = safe_name(fname, self.drives_dir, (".csv",))
        sp = self._clean_spacing(spacing_ft)
        out = os.path.join(self.exports_dir, os.path.basename(path)[:-4] + (("_%gft" % sp) if sp else "") + ".kml")
        make_map.export_kml([path], out, title=self.read_meta(path).get("name") or os.path.basename(path),
                            spacing_ft=sp, pick="average" if pick == "average" else "peak")
        return out

    def backup(self):
        out = os.path.join(self.backups_dir, "rfmap_backup_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".zip")
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for folder in ("Drives", "Maps", "Exports"):
                for root, _, fs in os.walk(C.sub_dir(folder)):
                    for fn in fs:
                        p = os.path.join(root, fn)
                        z.write(p, os.path.relpath(p, self.data))
        return out

    def delete_drive(self, fname):
        path = safe_name(fname, self.drives_dir, (".csv",))
        if self.running() and fname == self.active_csv:
            raise ValueError("Stop logging before deleting this drive.")
        os.remove(path)
        mp = self.meta_path(path)
        if os.path.exists(mp):
            os.remove(mp)
        self._cache.pop(path, None)

    def set_meta(self, fname, name, notes):
        path = safe_name(fname, self.drives_dir, (".csv",))
        meta = self.read_meta(path)
        meta["name"], meta["notes"] = name, notes
        with open(self.meta_path(path), "w") as f:
            json.dump(meta, f, indent=2)

    def demo(self):
        """Run the simulated drive to completion at full speed and make a map from it."""
        settings_file = os.path.join(self.settings_dir, "practice_settings.json")
        port = free_port(LOGGER_PORT + 5)
        cmd = [python_exe(), "-u", os.path.join(HERE, "rf_logger.py"), "--gps", "sim", "--sdr", "sim",
               "--outdir", self.drives_dir, "--settings", settings_file, "--port", str(port),
               "--local-only", "--name", "Demo drive"]
        kw = {"creationflags": 0x08000000} if C.IS_WIN else {}
        r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, timeout=120, **kw)
        csvs = sorted((f for f in os.listdir(self.drives_dir) if "Demo-drive" in f and f.endswith(".csv")), reverse=True)
        if r.returncode != 0 or not csvs:
            raise ValueError("The practice drive failed: " + (r.stderr or r.stdout)[-300:])
        res = self.make_map([csvs[0]], "PRACTICE - simulated drive (not real data)")
        res["drive"] = csvs[0]
        return res

    # ---- email
    def email(self, fname, to, zip_it=True, subject=None, body=None):
        path = safe_name(fname, self.maps_dir, (".html",))
        attach = path
        if zip_it:
            attach = os.path.join(self.exports_dir, os.path.basename(path)[:-5] + ".zip")
            with zipfile.ZipFile(attach, "w", zipfile.ZIP_DEFLATED) as z:
                z.write(path, os.path.basename(path))
        subject = subject or "RF noise map: " + os.path.basename(path)[:-9]
        body = body or ("Attached is an RF noise map. Open the file in any web browser "
                        "(Safari, Chrome, Edge). Blue dots are weak signal, red dots are strong. "
                        "Tap a dot for details." + (" Unzip it first." if zip_it else ""))
        ok = False
        try:
            if C.IS_MAC:
                script = ('on run argv\n'
                          'tell application "Mail"\n'
                          'set m to make new outgoing message with properties {subject:item 1 of argv, '
                          'content:(item 2 of argv) & return & return, visible:true}\n'
                          'tell m\n'
                          'if (item 3 of argv) is not "" then make new to recipient at end of to recipients '
                          'with properties {address:item 3 of argv}\n'
                          'tell content to make new attachment with properties {file name:(POSIX file (item 4 of argv))} '
                          'at after the last paragraph\n'
                          'end tell\nactivate\nend tell\nend run')
                r = subprocess.run(["osascript", "-e", script, subject, body, to or "", attach],
                                   capture_output=True, text=True, timeout=30)
                ok = r.returncode == 0
            elif C.IS_WIN:
                ps = os.path.join(self.settings_dir, "mail_outlook.ps1")
                with open(ps, "w") as f:
                    f.write("$o = New-Object -ComObject Outlook.Application\n$m = $o.CreateItem(0)\n"
                            "$m.Subject = $args[0]\n$m.Body = $args[1]\nif ($args[2]) { $m.To = $args[2] }\n"
                            "$m.Attachments.Add($args[3]) | Out-Null\n$m.Display()\n")
                r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps,
                                    subject, body, to or "", attach], capture_output=True, text=True, timeout=40,
                                   creationflags=0x08000000)
                ok = r.returncode == 0
        except Exception:
            ok = False
        if ok:
            return {"method": "mail-app", "file": os.path.basename(attach),
                    "message": "A new email opened with the file attached. Check it and press Send."}
        # Fallback that always works: open a blank draft and show the file so it can be dragged in
        from urllib.parse import quote
        webbrowser.open(f"mailto:{quote(to or '')}?subject={quote(subject)}&body={quote(body)}")
        open_path(attach, reveal=True)
        return {"method": "fallback", "file": os.path.basename(attach),
                "message": "Your email program could not be controlled automatically. A blank email was "
                           "opened and the file is shown in a folder window: drag the file into the email."}


APP = App()


# ----------------------------------------------------------------------------
# Web server
# ----------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "RFNoiseMap"

    def log_message(self, *a):
        pass

    # --- security: only this computer, or a phone that has the secret link
    def _loopback(self):
        return self.client_address[0] in ("127.0.0.1", "::1")

    def _authorized(self):
        host = (self.headers.get("Host") or "").split(":")[0].lower()
        if self._loopback():
            return host in ("localhost", "127.0.0.1", "[::1]", "")
        cookie = self.headers.get("Cookie") or ""
        q = parse_qs(urlparse(self.path).query)
        return (f"rfmap={APP.cfg['token']}" in cookie) or (q.get("t", [""])[0] == APP.cfg["token"])

    def _send(self, code, body, ctype="application/json", extra=None):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj))

    def _fail(self, msg, code=400):
        self._json({"ok": False, "error": str(msg)}, code)

    # --- GET
    def do_GET(self):
        if not self._authorized():
            return self._send(403, "Forbidden. Open the link shown in the RF Noise Map window.", "text/plain")
        u = urlparse(self.path)
        path = u.path
        q = parse_qs(u.query)
        extra = {}
        if q.get("t", [""])[0] == APP.cfg["token"]:
            extra["Set-Cookie"] = f"rfmap={APP.cfg['token']}; Path=/; SameSite=Strict"
        try:
            if path == "/":
                with open(os.path.join(HERE, "panel.html"), encoding="utf-8") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8", extra)
            if path == "/help":
                with open(os.path.join(HERE, "guide.html"), encoding="utf-8") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8", extra)
            if path == "/favicon.ico":
                return self._send(204, b"", "image/x-icon")
            if path == "/api/ping":
                return self._json({"app": "rfmap", "version": C.VERSION})
            if path == "/api/state":
                return self._json(self.full_state())
            if path == "/api/live":
                return self._json(self.live_state())
            if path == "/api/drives":
                return self._json({"drives": APP.drives(), "maps": APP.maps(), "exports": APP.exports()})
            if path == "/api/pan/frame":
                after = int((q.get("after") or ["-1"])[0] or -1)
                if APP.running():                      # logging: show the logger's own band picture
                    try:
                        j = APP.logger_call("/spectrum?after=%d" % after, timeout=1.0)
                    except Exception:
                        j = {"same": True, "seq": after}
                    out = {"ok": True, "running": True, "viewonly": True, "logging": True,
                           "practice": bool(APP.cfg.get("practice")), "error": ""}
                    out.update(j)
                    return self._json(out)
                return self._json(PAN.get_frame(after))
            if path == "/api/slices/audio":
                ch = int((q.get("ch") or ["0"])[0] or 0)
                after = int((q.get("after") or ["0"])[0] or 0)
                if APP.running():
                    try:
                        data, hd = APP.logger_raw("/slice_audio?ch=%d&after=%d" % (ch, after), timeout=1.0)
                    except Exception:
                        data, hd = b"", {}
                    return self._send(200, data, "application/octet-stream",
                                      {"X-Seq": str(hd.get("X-Seq", after)), "X-Rate": str(hd.get("X-Rate", 12000))})
                import hl2_audio
                data, last = hl2_audio.SND.audio(ch, after)
                return self._send(200, data, "application/octet-stream",
                                  {"X-Seq": str(last), "X-Rate": str(hl2_audio.AUDIO_RATE)})
            if path == "/api/slices":
                if APP.running():                      # logging: the logger supplies every channel's picture
                    try:
                        j = APP.logger_call("/slices", timeout=1.0)
                    except Exception:
                        j = {"frames": [], "health": {}}
                    return self._json(dict({"ok": True, "running": True, "logging": True, "error": ""}, **j))
                return self._json(SLICES.get())
            if path == "/api/logs/tail":
                return self._json({"ok": True, "lines": L.tail(int((q.get("n") or ["60"])[0] or 60)), "dir": L.log_dir()})
            if path == "/api/rec/list":
                return self._json({"ok": True, "recording": REC.status(), "files": APP.recordings()})
            if path.startswith("/recordings/"):
                name = unquote(path[len("/recordings/"):])
                p = safe_name(name, APP.rec_dir, (".wav",))
                with open(p, "rb") as f:
                    data = f.read()
                total = len(data)
                hdr = {"Accept-Ranges": "bytes"}
                if q.get("download"):
                    hdr["Content-Disposition"] = f'attachment; filename="{os.path.basename(p)}"'
                rng = self.headers.get("Range", "")
                if rng.startswith("bytes=") and total:
                    a, _, b2 = rng[6:].partition("-")
                    try:
                        start = int(a) if a else max(0, total - int(b2))
                        end = int(b2) if (a and b2) else total - 1
                    except ValueError:
                        start, end = 0, total - 1
                    end = min(end, total - 1)
                    if start > end:
                        return self._send(416, "", "text/plain", {"Content-Range": "bytes */%d" % total})
                    hdr["Content-Range"] = "bytes %d-%d/%d" % (start, end, total)
                    return self._send(206, data[start:end + 1], "audio/wav", hdr)
                return self._send(200, data, "audio/wav", hdr)
            if path == "/api/pan/audio":
                data, last = PAN.get_audio(int((q.get("after") or ["0"])[0] or 0))
                return self._send(200, data, "application/octet-stream",
                                  {"X-Seq": str(last), "X-Rate": str(C_AUDIO_RATE)})
            if path == "/api/blockers":
                return self._json(device_guard.find_blockers())
            if path == "/api/ports":
                return self._json({"ports": check_setup.list_serial_ports()})
            if path.startswith("/maps/"):
                name = unquote(path[len("/maps/"):])
                p = safe_name(name, APP.maps_dir, (".html",))
                with open(p, "rb") as f:
                    data = f.read()
                hdr = {}
                if q.get("download"):
                    hdr["Content-Disposition"] = f'attachment; filename="{os.path.basename(p)}"'
                return self._send(200, data, "text/html; charset=utf-8", hdr)
            if path.startswith("/exports/"):
                name = unquote(path[len("/exports/"):])
                p = safe_name(name, APP.exports_dir, (".kml", ".zip", ".csv"))
                with open(p, "rb") as f:
                    data = f.read()
                return self._send(200, data, "application/octet-stream",
                                  {"Content-Disposition": f'attachment; filename="{os.path.basename(p)}"'})
            if path.startswith("/drives/"):
                name = unquote(path[len("/drives/"):])
                p = safe_name(name, APP.drives_dir, (".csv",))
                with open(p, "rb") as f:
                    data = f.read()
                return self._send(200, data, "text/csv",
                                  {"Content-Disposition": f'attachment; filename="{os.path.basename(p)}"'})
            return self._send(404, "Not found", "text/plain")
        except ValueError as e:
            return self._fail(e, 404)
        except (ConnectionError, BrokenPipeError, TimeoutError):
            return                      # the browser closed or reloaded the page mid-answer: nothing to report
        except Exception as e:
            L.exception("request %s" % self.path.split("?")[0])
            return self._fail(e, 500)

    # --- POST
    def do_POST(self):
        if not self._authorized() or self.headers.get("X-RFMap") != "1":
            return self._send(403, "Forbidden", "text/plain")
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        except ValueError:
            return self._fail("bad request")
        path = urlparse(self.path).path
        try:
            return self._json(self.route_post(path, body))
        except ValueError as e:
            return self._fail(e)
        except (ConnectionError, BrokenPipeError, TimeoutError):
            return                      # the browser closed or reloaded the page mid-answer: nothing to report
        except Exception as e:
            L.exception("request %s" % path)
            return self._fail(f"{type(e).__name__}: {e}", 500)

    def route_post(self, path, b):
        if path == "/api/config":
            APP.update_cfg(b)
            return {"ok": True}
        if path == "/api/pan/start":
            if APP.running():
                raise ValueError("Stop logging first. The radio can only do one job at a time.")
            SLICES.stop()
            if not APP.cfg.get("use_sdrplay", True) and not APP.cfg.get("practice"):
                raise ValueError("The listening panadapter uses the SDRplay radio, which is not ticked in 'Your radios'. "
                                 "Use the Slices view above to watch your frequencies (or Thetis / SDR Console to listen).")
            PAN.start(b, bool(APP.cfg.get("practice")))
            return {"ok": True, "radio": PAN.name}
        if path == "/api/pan/watch":              # while logging: choose which frequency to watch (-1 = none)
            if not APP.running():
                raise ValueError("Start logging first. (To listen, use Start panadapter instead.)")
            APP.logger_call("/pan", {"channel": int(b.get("channel", -1))}, timeout=3)
            return {"ok": True}
        if path == "/api/gain":                   # attenuation, also while driving
            a = int(min(max(int(b.get("if_gain_db", 40)), 20), 59))
            r = int(min(max(int(b.get("rf_gain_state", 0)), 0), 27))
            h = int(min(max(int(b.get("hl2_gain_db", APP.cfg.get("hl2_gain_db", 15))), -12), 48))
            APP.update_cfg({"if_gain_db": a, "rf_gain_state": r, "hl2_gain_db": h})
            if APP.running():
                APP.logger_call("/set", {"if_gain_db": a, "rf_gain_state": r, "hl2_gain_db": h}, timeout=3)
            elif SLICES.running:
                SLICES.set(gain={"if_gain_db": a, "rf_gain_state": r, "hl2_gain_db": h})
            return {"ok": True, "if_gain_db": a, "rf_gain_state": r, "hl2_gain_db": h}
        if path == "/api/spacing":                # dot spacing, also while driving
            sp = min(max(2.0, float(b.get("spacing_ft", 10))), 5280.0)
            mode = "time" if b.get("sample_mode") == "time" else "distance"
            iv = min(max(0.5, float(b.get("interval_s", 5))), 3600.0)
            APP.update_cfg({"spacing_ft": sp, "sample_mode": mode, "interval_s": iv})
            if APP.running():
                APP.logger_call("/set", {"spacing_ft": sp, "sample_mode": mode, "interval_s": iv}, timeout=3)
            return {"ok": True, "spacing_ft": sp, "sample_mode": mode, "interval_s": iv}
        if path == "/api/pan/set":
            PAN.set(b)
            return {"ok": True}
        if path == "/api/clientlog":
            msg = str(b.get("msg", ""))[:600]
            if msg:
                L.error("browser window: %s%s" % (msg, ("  at " + str(b.get("where", ""))[:200]) if b.get("where") else ""))
            return {"ok": True}
        if path == "/api/logs/bundle":
            out = L.make_bundle()
            open_path(out, reveal=True)
            return {"ok": True, "file": os.path.basename(out), "dir": os.path.dirname(out)}
        if path == "/api/rec/start":
            if APP.running() or not PAN.running:
                raise ValueError("Start the panadapter first (recording saves what you hear, and you cannot listen while logging).")
            if REC.active():
                raise ValueError("Already recording.")
            p = PAN.params
            mode = str(p.get("mode", "AM"))
            name = "%s_%.4fMHz_%s.wav" % (time.strftime("%Y-%m-%d_%H%M%S"), float(p.get("tune", 0)) / 1e6, mode)
            REC.start(os.path.join(APP.rec_dir, name))
            return {"ok": True, "file": name}
        if path == "/api/rec/stop":
            r = REC.stop()
            return {"ok": True, "result": r}
        if path == "/api/rec/delete":
            name = os.path.basename(str(b.get("file", "")))
            if REC.active() and REC.status().get("file") == name:
                raise ValueError("Stop recording first.")
            os.remove(safe_name(name, APP.rec_dir, (".wav",)))
            return {"ok": True}
        if path == "/api/radio/find":             # look for a Hermes Lite 2 on the network
            ip = str(b.get("ip", "")).strip()
            found = hl2.discover(ip or None, timeout=3.0)
            if found:
                APP.update_cfg({"hl2_ip": found[0]["ip"]})
            return {"ok": True, "found": found}
        if path == "/api/slices/start":
            if APP.running():
                raise ValueError("Logging is running, so the slices are already shown below from the logger.")
            PAN.stop()
            c = APP.cfg
            SLICES.start(bool(c.get("practice")), APP.clean_channels(b.get("channels") or c["channels"]),
                         c.get("hl2_ip", ""), int(c.get("hl2_rate", 96000)),
                         {"if_gain_db": int(c["if_gain_db"]), "rf_gain_state": int(c["rf_gain_state"]),
                          "hl2_gain_db": int(c.get("hl2_gain_db", 15))})
            return {"ok": True, "radio": SLICES.name}
        if path == "/api/slices/set":
            if SLICES.running and b.get("channels"):
                chans = APP.clean_channels(b["channels"])
                opened = getattr(getattr(SLICES, "sdr", None), "radios", None)      # radios opened at Start
                if opened and not APP.cfg.get("practice"):
                    for ch in chans:
                        if ch["radio"] not in opened:
                            raise ValueError("That slice needs the %s, which was not opened when the preview started. "
                                             "Click Stop, then Preview slices again." %
                                             ("Hermes Lite 2" if ch["radio"] == "hl2" else "SDRplay"))
                SLICES.set(channels=chans)
            return {"ok": True}
        if path == "/api/slices/listen":
            ch = int(b.get("channel", 0))
            if APP.running():
                APP.logger_call("/slice_listen", b, timeout=3)
            else:
                if not SLICES.running:
                    raise ValueError("Start the slices preview (or logging) first.")
                import hl2_audio
                hl2_audio.SND.listen(ch, bool(b.get("on")), b.get("mode"), b.get("bw"))
            return {"ok": True}
        if path == "/api/slices/sound_mode":
            if APP.running():
                APP.logger_call("/slice_mode", b, timeout=3)
            else:
                import hl2_audio
                hl2_audio.SND.set_mode(int(b.get("channel", 0)), b.get("mode"), b.get("bw"))
            return {"ok": True}
        if path == "/api/slices/rec":
            ch = int(b.get("channel", 0))
            if APP.running():
                j = APP.logger_call("/slice_rec", b, timeout=3)
                return {"ok": True, "file": (j or {}).get("file", "")}
            if not SLICES.running:
                raise ValueError("Start the slices preview (or logging) first.")
            import hl2_audio
            chans = APP.cfg.get("channels", [])
            mhz = chans[ch]["mhz"] if 0 <= ch < len(chans) else 0
            name = hl2_audio.SND.record(ch, bool(b.get("on")), "slice%d_%sMHz" % (ch + 1, mhz),
                                        b.get("mode"), b.get("bw"))
            return {"ok": True, "file": name or ""}
        if path == "/api/slices/stop":
            SLICES.stop()
            return {"ok": True}
        if path == "/api/pan/stop":
            PAN.stop(); SLICES.stop()
            return {"ok": True}
        if path == "/api/start":
            APP.update_cfg(b)
            APP.start()
            return {"ok": True}
        if path == "/api/apply":                 # change frequencies while logging
            APP.update_cfg(b)
            chans = APP.clean_channels(APP.cfg["channels"])
            if APP.running():
                need = sorted({ch["radio"] for ch in chans})
                have = getattr(APP, "active_radios", need)
                missing = [r for r in need if r not in have]
                if missing and not APP.cfg.get("practice"):
                    raise ValueError("That change needs the %s, which was not in use when this drive started. "
                                     "Stop logging, then start again." %
                                     ("Hermes Lite 2" if missing[0] == "hl2" else "SDRplay"))
                APP.logger_call("/set", {"channels": chans, "spacing_ft": float(APP.cfg["spacing_ft"]),
                                         "sample_mode": APP.cfg.get("sample_mode", "distance"),
                                         "interval_s": float(APP.cfg.get("interval_s", 5))}, timeout=3)
            return {"ok": True}
        if path == "/api/pause":
            if APP.running():
                APP.logger_call("/pause", {}, timeout=3)
            return {"ok": True}
        if path == "/api/stop":
            name = APP.stop()
            res = {"ok": True, "drive": name}
            if name and APP.cfg.get("auto_map"):
                try:
                    res.update(APP.make_map([name]))
                except ValueError as e:
                    res["map_error"] = str(e)
            return res
        if path == "/api/map":
            return dict(ok=True, **APP.make_map(b.get("files", []), b.get("title"), b.get("spacing_ft"), b.get("pick", "peak")))
        if path == "/api/kml":
            out = APP.make_kml(b.get("file", ""), b.get("spacing_ft"), b.get("pick", "peak"))
            return {"ok": True, "file": os.path.basename(out)}
        if path == "/api/drive/meta":
            APP.set_meta(b.get("file", ""), str(b.get("name", ""))[:80], str(b.get("notes", ""))[:2000])
            return {"ok": True}
        if path == "/api/drive/delete":
            APP.delete_drive(b.get("file", ""))
            return {"ok": True}
        if path == "/api/open_folder":
            folder = {"data": APP.data, "drives": APP.drives_dir, "maps": APP.maps_dir,
                      "exports": APP.exports_dir, "backups": APP.backups_dir,
                      "recordings": APP.rec_dir, "logs": L.log_dir()}.get(b.get("which"), APP.data)
            return {"ok": open_path(folder)}
        if path == "/api/reveal":
            kind = b.get("kind")
            folder = {"map": APP.maps_dir, "drive": APP.drives_dir, "export": APP.exports_dir,
                      "rec": APP.rec_dir}.get(kind)
            if not folder:
                raise ValueError("unknown kind")
            p = os.path.join(folder, os.path.basename(b.get("file", "")))
            if not os.path.exists(p):
                raise ValueError("File not found")
            return {"ok": open_path(p, reveal=True)}
        if path == "/api/email":
            return dict(ok=True, **APP.email(b.get("file", ""), str(b.get("to", "")).strip(),
                                             bool(b.get("zip", True))))
        if path == "/api/backup":
            out = APP.backup()
            open_path(out, reveal=True)
            return {"ok": True, "file": os.path.basename(out)}
        if path == "/api/demo":
            return dict(ok=True, **APP.demo())
        if path in ("/api/check", "/api/fulltest", "/api/gps_detect"):
            PAN.stop(); SLICES.stop()
        if path == "/api/check":
            if APP.running():
                return {"ok": True, "results": [{"name": "Logging", "status": "info",
                        "message": "Stop logging first, then run the check (the radio is busy while logging)."}]}
            spec = None
            if b.get("test_gps"):
                try:
                    spec = APP.gps_spec()
                except ValueError as e:
                    return {"ok": True, "results": [{"name": "GPS", "status": "fix", "message": str(e)}]}
            return {"ok": True, "results": check_setup.run_checks(spec)}
        if path == "/api/free_devices":
            if APP.running():
                return {"ok": True, "closed": [], "note": "Stop logging first."}
            pids = [int(x) for x in b.get("pids", []) if str(x).isdigit()]
            return {"ok": True, "closed": device_guard.close_pids(pids, force=bool(b.get("force")))}
        if path == "/api/fulltest":
            if APP.running():
                return {"ok": True, "results": [{"step": "Full test", "status": "info",
                        "message": "Stop logging first; the radio is busy while logging."}]}
            cmd = [python_exe(), "-u", os.path.join(HERE, "full_test.py"), "--json"]
            if APP.cfg.get("gps_mode") == "iphone":
                cmd.append("--iphone")
            kw = {"creationflags": 0x08000000} if C.IS_WIN else {}
            try:
                r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, timeout=170, **kw)
                items = json.loads(r.stdout.strip().splitlines()[-1])
            except Exception as e:
                items = [{"step": "Full test", "status": "fix", "message": f"The test could not run: {e}"}]
            return {"ok": True, "results": items}
        if path == "/api/gps_detect":
            if APP.running():
                return {"ok": True, "found": [], "note": "Stop logging first, then press Find my GPS."}
            res = gps_detect.find_gps(budget_s=45, listen=2.5)
            return {"ok": True, **res}
        if path == "/api/quit":
            PAN.stop(); SLICES.stop()
            APP.stop()
            port = APP.port
            def _finish():
                close_browser_tabs(port)
                time.sleep(0.4)
                os._exit(0)
            threading.Thread(target=_finish, daemon=True).start()
            threading.Timer(12.0 if C.IS_MAC else 0.4, lambda: os._exit(0)).start()   # safety net
            return {"ok": True}
        raise ValueError("unknown request")

    # --- state
    def live_state(self):
        st = APP.logger_status()
        dead = APP.proc is not None and APP.proc.poll() is not None
        if dead and getattr(APP, "_crash_logged", None) is not APP.proc:
            APP._crash_logged = APP.proc
            L.error("The logger stopped unexpectedly (exit code %s). Its last messages:\n%s" % (APP.proc.poll(), APP.log_tail(12)))
        return {"logging": APP.running(), "logger": st,
                "log_tail": APP.log_tail(6) if (dead or not st) and APP.proc else "",
                "crashed": dead}

    def full_state(self):
        warns = []

        def safe(label, fn, default):
            try:
                return fn()
            except Exception as e:                       # never let one part blank the whole page
                msg = str(e)
                if isinstance(e, PermissionError) and C.IS_MAC:
                    msg += (" (macOS is blocking this program from that folder. Documents, Desktop and Downloads are protected. "
                            "Open System Settings > Privacy & Security > Full Disk Access and switch on Terminal, "
                            "or tell KW4EX.)")
                if isinstance(e, ImportError) and "numpy" in str(e):
                    import platform
                    msg += (f" [This program is running as '{platform.machine()}'. On an Apple-silicon Mac it must run as arm64; "
                            "close RF Noise Map and open it again from the Desktop icon, or run the installer again.]")
                L.warn(f"{label}: {msg}")
                warns.append(f"{label}: {msg}")
                return default

        phone = safe("phone address", lambda: f"http://{__import__('rf_logger').lan_ip()}:{APP.port}/?t={APP.cfg['token']}", "")
        return {"version": C.VERSION, "platform": "mac" if C.IS_MAC else "windows" if C.IS_WIN else "linux",
                "data_dir": APP.data, "cfg": {k: v for k, v in APP.cfg.items() if k != "token"},
                "ports": safe("USB ports", check_setup.list_serial_ports, []),
                "phone_url": phone if APP.cfg.get("phone_access") else "",
                "drives": safe("recorded drives", APP.drives, []), "maps": safe("maps", APP.maps, []),
                "exports": safe("exports", APP.exports, []),
                "live": safe("status", self.live_state, {"logging": False, "logger": None, "log_tail": "", "crashed": False}),
                "warnings": warns}


def serve(port):
    host = "0.0.0.0" if APP.cfg.get("phone_access") else "127.0.0.1"
    srv = ThreadingHTTPServer((host, port), Handler)
    APP.server, APP.port = srv, port
    return srv


def main():
    ap = argparse.ArgumentParser(description="RF Noise Map control panel")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--stop", action="store_true", help="close a running RF Noise Map and exit")
    args = ap.parse_args()

    if args.stop:                         # used by Stop_RFNoise.bat and the uninstaller
        found = False
        for p in range(args.port, args.port + 10):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{p}/api/ping", timeout=1) as r:
                    if json.loads(r.read()).get("app") != "rfmap":
                        continue
                req = urllib.request.Request(f"http://127.0.0.1:{p}/api/quit", data=b"{}", method="POST",
                                             headers={"Content-Type": "application/json", "X-RFMap": "1"})
                urllib.request.urlopen(req, timeout=3).read()
                found = True
                print(f"RF Noise Map on port {p} was closed.")
            except Exception:
                continue
        if not found:
            print("RF Noise Map is not running.")
        return

    L.setup("panel")

    # Started without a console window (Windows double-click)? Send messages to a log file instead.
    if sys.stdout is None or sys.stderr is None:
        logf = open(os.path.join(C.sub_dir("Settings"), "app.log"), "a", buffering=1)
        sys.stdout = sys.stdout or logf
        sys.stderr = sys.stderr or logf

    # Already running? Just show it.
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{args.port}/api/ping", timeout=1) as r:
            if json.loads(r.read()).get("app") == "rfmap":
                if not args.no_browser:
                    webbrowser.open(f"http://localhost:{args.port}/")
                print("RF Noise Map is already running; opened it.")
                return
    except Exception:
        pass

    try:                                   # close leftovers of this program that may be holding the radio/GPS
        gone = [] if os.environ.get("RFMAP_NO_CLEANUP") else device_guard.cleanup_own_leftovers()
        if gone:
            print("Closed " + str(len(gone)) + " leftover RF Noise Map helper program(s).", flush=True)
    except Exception:
        pass
    port = free_port(args.port)
    srv = serve(port)
    url = f"http://localhost:{port}/"
    print(f"RF Noise Map {C.VERSION} is running at {url}\nData folder: {APP.data}\nLeave this running; "
          "use the Quit button in the window (or close this) when finished.", flush=True)
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        APP.stop()


if __name__ == "__main__":
    main()
