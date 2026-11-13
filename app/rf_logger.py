#!/usr/bin/env python3
"""
rf_logger.py  -  Drive-route RF noise logger
=============================================

WHAT IT DOES
  1. Reads your position from a GPS (iPhone via the GPS2IP app, or a USB GPS puck).
  2. Reads the radio signal level from an SDRplay receiver at up to 4 frequencies,
     taking turns: tune to freq 1, measure, tune to freq 2, measure, ...
  3. Every time you have moved about 10 ft, it writes one line per frequency
     into a CSV file (latitude, longitude, level).
  4. Run make_map.py afterwards to turn that CSV into a street map with colored dots.

HOW THE PROGRAM FLOWS (read this top to bottom and you have the whole program)
  main()  ->  start the GPS reader (a background thread)
          ->  open the SDR
          ->  start the little settings web page (another background thread)
          ->  loop forever:
                 take one measurement cycle (all frequencies)
                 if we moved far enough since the last saved spot -> save rows
                 handle Ctrl+C by closing the file cleanly

TEST WITHOUT HARDWARE:
  python3 rf_logger.py --gps sim --sdr sim
"""

import argparse
import csv
import json
import math
import os
import re
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

import rfmap_common as C
import rfmap_log as L

FT_PER_M = 3.28084
MPH_PER_MPS = 2.23694
KNOTS_TO_MPS = 0.514444

# ----------------------------------------------------------------------------
# SETTINGS  (shared between the measuring loop and the settings web page)
# ----------------------------------------------------------------------------
# "channels" is the list of frequencies measured in turn.
#   mhz    = center frequency to measure
#   bw_khz = width of the slice we measure (narrow = ignores nearby stations)
#   cal_db = number added to the raw reading (see README, "Calibration")
DEFAULT_SETTINGS = {
    "channels": [
        {"mhz": 3.700, "bw_khz": 5.0, "cal_db": 0.0},
        {"mhz": 7.300, "bw_khz": 5.0, "cal_db": 0.0},
        {"mhz": 148.000, "bw_khz": 10.0, "cal_db": 0.0},
    ],
    "spacing_ft": 10.0,       # save a new row each time we move this far
    "sample_mode": "distance",  # "distance" = every spacing_ft; "time" = every interval_s seconds (even standing still)
    "interval_s": 5.0,        # seconds between readings in "time" mode
    "paused": False,          # pause button on the settings page
    "if_gain_db": 40,         # SDRplay "IF gain reduction" (higher = less gain)
    "rf_gain_state": 0,       # SDRplay "RF gain reduction" (0 = most gain)
    "pan_channel": -1,        # which frequency (0-3) to show as a live spectrum; -1 = none
}
MAX_CHANNELS = 4


PAN_DB_LO, PAN_DB_HI = -120.0, 0.0
PAN_FRAME = {"seq": 0, "f": None, "lock": threading.Lock()}


def publish_spectrum(lo_hz, rate, spec, tune_hz, bw_hz, level_db, idx):
    """Keep the newest band picture so the control panel can show it while logging."""
    import base64
    db = 10.0 * np.log10(np.asarray(spec, dtype=np.float64) + 1e-12)
    b = np.clip((db - PAN_DB_LO) * (255.0 / (PAN_DB_HI - PAN_DB_LO)), 0, 255).astype(np.uint8)
    with PAN_FRAME["lock"]:
        PAN_FRAME["seq"] += 1
        PAN_FRAME["f"] = {"seq": PAN_FRAME["seq"], "center": float(lo_hz), "rate": int(rate), "tune": float(tune_hz),
                          "bw": float(bw_hz), "channel": int(idx), "smeter": round(float(level_db), 1),
                          "db_lo": PAN_DB_LO, "db_hi": PAN_DB_HI, "spec": base64.b64encode(b.tobytes()).decode()}


class Settings:
    """Thread-safe holder for the settings dictionary."""

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.data = json.loads(json.dumps(DEFAULT_SETTINGS))
        if os.path.exists(path):
            try:
                with open(path) as f:
                    self.data.update(json.load(f))
            except Exception as e:
                print(f"[settings] could not read {path}: {e} (using defaults)")

    def get(self):
        with self.lock:
            return json.loads(json.dumps(self.data))

    def update(self, new):
        with self.lock:
            self.data.update(new)
            try:
                with open(self.path, "w") as f:
                    json.dump(self.data, f, indent=2)
            except Exception as e:
                print(f"[settings] could not save {self.path}: {e}")


# ----------------------------------------------------------------------------
# GPS
# ----------------------------------------------------------------------------
class Fix:
    """One GPS position report."""

    def __init__(self, lat, lon, speed_mps, course_deg, t_rx, sats=None, hdop=None):
        self.lat, self.lon = lat, lon
        self.speed_mps = speed_mps
        self.course_deg = course_deg
        self.t_rx = t_rx          # time the Mac received it
        self.sats, self.hdop = sats, hdop


def nmea_checksum_ok(line):
    """NMEA lines look like  $GPRMC,....*5A   -  the part after * is a checksum."""
    if "*" not in line or not line.startswith("$"):
        return True  # be forgiving: some apps omit it
    body, _, cs = line[1:].partition("*")
    calc = 0
    for ch in body:
        calc ^= ord(ch)
    try:
        return calc == int(cs.strip()[:2], 16)
    except ValueError:
        return False


def nmea_to_degrees(value, hemi):
    """NMEA gives ddmm.mmmm - convert to plain decimal degrees."""
    if not value:
        return None
    dot = value.index(".")
    deg = float(value[: dot - 2])
    minutes = float(value[dot - 2:])
    d = deg + minutes / 60.0
    return -d if hemi in ("S", "W") else d


class NmeaGps(threading.Thread):
    """
    Background thread. Reads NMEA text lines from either
      - a TCP address   (iPhone running GPS2IP)      -> "tcp:192.168.1.5:11123"
      - a serial port   (USB GPS puck)               -> "serial:/dev/cu.usbmodem1101:9600"
    and keeps the newest position in self.fix.
    """

    def __init__(self, spec):
        super().__init__(daemon=True)
        self.spec = spec
        self.fix = None
        self.sats = None
        self.hdop = None
        self.status = "starting"
        self.lines = 0
        self.lock = threading.Lock()
        self._halt = threading.Event()

    def stop(self):
        """Stop listening and let go of the serial port / network connection."""
        self._halt.set()

    # -- open the right kind of connection and yield text lines forever
    def _lines(self):
        kind, _, rest = self.spec.partition(":")
        if kind == "tcp":
            host, _, port = rest.rpartition(":")
            while not self._halt.is_set():
                s = None
                try:
                    self.status = f"connecting to {host}:{port}"
                    s = socket.create_connection((host, int(port)), timeout=10)
                    s.settimeout(5)
                    self.status = f"connected {host}:{port}"
                    buf = b""
                    while not self._halt.is_set():
                        try:
                            chunk = s.recv(4096)
                        except socket.timeout:
                            continue
                        if not chunk:
                            raise ConnectionError("GPS app closed the connection")
                        buf += chunk
                        while b"\n" in buf:
                            line, _, buf = buf.partition(b"\n")
                            yield line.decode("ascii", "ignore").strip()
                except Exception as e:
                    self.status = f"GPS link lost ({e}); retrying"
                    time.sleep(2)
                finally:
                    try:
                        if s is not None:
                            s.close()
                    except Exception:
                        pass
        elif kind == "serial":
            port, _, baud = rest.partition(":")
            baud = int(baud) if baud else 9600
            try:
                import serial  # pip install pyserial
            except ImportError:
                self.status = "pyserial not installed (pip3 install pyserial)"
                print("ERROR:", self.status)
                return
            while not self._halt.is_set():
                try:
                    self.status = f"opening {port} @ {baud}"
                    with serial.Serial(port, baud, timeout=1) as ser:
                        self.status = f"connected {port}"
                        while not self._halt.is_set():
                            raw = ser.readline()
                            if raw:
                                yield raw.decode("ascii", "ignore").strip()
                except Exception as e:
                    self.status = f"serial error ({e}); retrying"
                    time.sleep(2)
        else:
            self.status = f"unknown GPS spec '{self.spec}'"

    def run(self):
        for line in self._lines():
            if self._halt.is_set():
                break
            if not line.startswith("$") or not nmea_checksum_ok(line):
                continue
            self.lines += 1
            f = line.split("*")[0].split(",")
            kind = f[0][3:]  # "RMC", "GGA" ... (ignores GP/GN/GL prefix)
            try:
                if kind == "GGA" and len(f) > 8:
                    self.sats = int(f[7]) if f[7] else None
                    self.hdop = float(f[8]) if f[8] else None
                elif kind == "RMC" and len(f) > 8 and f[2] == "A":
                    lat = nmea_to_degrees(f[3], f[4])
                    lon = nmea_to_degrees(f[5], f[6])
                    spd = float(f[7]) * KNOTS_TO_MPS if f[7] else 0.0
                    crs = float(f[8]) if f[8] else 0.0
                    if lat is not None and lon is not None:
                        with self.lock:
                            self.fix = Fix(lat, lon, spd, crs, time.time(),
                                           self.sats, self.hdop)
                        self.status = "fix OK"
                elif kind == "RMC" and len(f) > 2 and f[2] != "A":
                    self.status = "no GPS fix yet (move the antenna to open sky)"
            except (ValueError, IndexError):
                pass

    def latest(self):
        with self.lock:
            return self.fix


# Demo route used by --gps sim: a loop around a few blocks (local x,y in meters).
SIM_ORIGIN = (39.7700, -86.1600)
SIM_ROUTE_M = [(0, 0), (900, 0), (900, 700), (200, 700), (200, 300), (-400, 300),
               (-400, -400), (500, -400), (500, 0)]
SIM_NOISE_SOURCE_M = (880, 420)   # pretend leaky power pole, east side of route


def m_to_latlon(x, y, origin=SIM_ORIGIN):
    lat = origin[0] + y / 111320.0
    lon = origin[1] + x / (111320.0 * math.cos(math.radians(origin[0])))
    return lat, lon


class SimGps:
    """Pretend GPS that drives the demo route at 40 mph, 10 position updates/second."""

    def __init__(self):
        self.t = 0.0
        self.speed = 40.0 / MPH_PER_MPS
        segs, total = [], 0.0
        for a, b in zip(SIM_ROUTE_M[:-1], SIM_ROUTE_M[1:]):
            d = math.dist(a, b)
            segs.append((a, b, d, total))
            total += d
        self.segs, self.total = segs, total
        self.status = "simulated GPS"
        self.finished = False
        self.lines = 0

    def latest(self):
        self.t += 0.1
        dist = self.speed * self.t
        if dist >= self.total:
            self.finished = True
            dist = self.total - 0.01
        for a, b, d, start in self.segs:
            if dist <= start + d:
                f = (dist - start) / d
                x, y = a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])
                course = (math.degrees(math.atan2(b[0] - a[0], b[1] - a[1]))) % 360
                lat, lon = m_to_latlon(x, y)
                self.lines += 1
                return Fix(lat, lon, self.speed, course, time.time(), 12, 0.9)
        return None


# ----------------------------------------------------------------------------
# SDR
# ----------------------------------------------------------------------------
class SimSdr:
    """Pretend radio. Noise floor plus a 'noisy pole' that is stronger on low bands."""
    name = "simulated SDR"

    def __init__(self):
        self.rng = np.random.default_rng(1)

    def measure(self, freq_hz, bw_hz, lat, lon, settings):
        sx, sy = SIM_NOISE_SOURCE_M
        px = (lon - SIM_ORIGIN[1]) * 111320.0 * math.cos(math.radians(SIM_ORIGIN[0]))
        py = (lat - SIM_ORIGIN[0]) * 111320.0
        d = max(math.hypot(px - sx, py - sy), 5.0)
        mhz = freq_hz / 1e6
        strength = 45.0 if mhz < 10 else 30.0           # low bands carry farther
        reach = 250.0 if mhz < 10 else 80.0             # VHF is more local
        floor = -92.0 if mhz < 10 else -100.0
        level = floor + strength * math.exp(-d / reach) + self.rng.normal(0, 1.2)
        self._last = self._make_spec(freq_hz, bw_hz, level)
        return float(level)

    def _make_spec(self, freq_hz, bw_hz, level):
        n, rate = 4096, 2_000_000
        lo = freq_hz - 200_000
        hz = (np.arange(n) / n - 0.5) * rate + lo
        floor = 10 ** (-10.4) * (1 + 0.35 * self.rng.standard_normal(n)).clip(0.2, None)
        hump = 10 ** (level / 10.0) / max(bw_hz / (rate / n), 1) * np.exp(-0.5 * ((hz - freq_hz) / max(bw_hz, 3000.0)) ** 2)
        carriers = np.zeros(n)
        for off, amp in ((-450_000, 3e-9), (350_000, 1.2e-9), (120_000, 6e-10)):
            carriers[int((off + 200_000 + rate / 2) / rate * n) % n] += amp * 1e1
        return lo, rate, floor + hump + carriers, level

    def spectrum(self, freq_hz, bw_hz, lat, lon, settings):
        level = self.measure(freq_hz, bw_hz, lat, lon, settings)
        return self._last

    def last_frame(self):
        return getattr(self, "_last", None)


class SoapySdr:
    """Real SDRplay through the SoapySDR library."""

    OFFSET_HZ = 200_000     # tune this far below the target to dodge the DC spike
    SAMPLE_RATE = 2_000_000
    NSAMP = 32768           # samples per measurement (about 16 ms)
    FFT_N = 4096

    def __init__(self, settings):
        SoapySDR, note = C.find_soapy()
        if SoapySDR is None:
            L.error("radio library (SoapySDR) not available: %s" % note)
            sys.exit(
                "\nERROR: the radio library (SoapySDR) is not available.\n"
                f"       {note}\n"
                "       In the RF Noise Map window, press 'Check setup' for plain-English help,\n"
                "       or tick 'Practice mode' to try everything without the radio.\n")
        from SoapySDR import SOAPY_SDR_RX, SOAPY_SDR_CF32
        self.S = SoapySDR
        self.RX, self.CF32 = SOAPY_SDR_RX, SOAPY_SDR_CF32
        devs = SoapySDR.Device.enumerate("driver=sdrplay")
        if not devs:
            L.error("no SDRplay found by SoapySDR (radio unplugged, SDRplay API service not running, or another program is using it)")
            sys.exit("\nERROR: no SDRplay found. Is it plugged in, and is the SDRplay "
                     "API service installed and running? (see README step 2)\n")
        self.dev = SoapySDR.Device(devs[0])
        _d = dict(devs[0])
        self.name = "SDRplay " + str(_d.get("label", _d.get("serial", "")))
        d = self.dev
        d.setSampleRate(self.RX, 0, self.SAMPLE_RATE)
        try:
            d.setBandwidth(self.RX, 0, 1_536_000)
        except Exception:
            pass
        # Turn the automatic gain OFF so readings are comparable along the route
        try:
            d.setGainMode(self.RX, 0, False)
        except Exception:
            pass
        self.apply_gain(settings)
        self.stream = d.setupStream(self.RX, self.CF32)
        d.activateStream(self.stream)
        self.buf = np.zeros(self.NSAMP, np.complex64)
        self.window = np.hanning(self.FFT_N).astype(np.float32)
        self.win_pow = float(np.sum(self.window ** 2))

    def apply_gain(self, settings):
        key = (settings["if_gain_db"], settings["rf_gain_state"])
        if key == getattr(self, "_gain_key", None):
            return
        for name, val in (("IFGR", settings["if_gain_db"]), ("RFGR", settings["rf_gain_state"])):
            try:
                self.dev.setGain(self.RX, 0, name, float(val))
            except Exception:
                pass
        self._gain_key = key

    def _read(self, n):
        got = 0
        while got < n:
            sr = self.dev.readStream(self.stream, [self.buf[got:]], n - got, timeoutUs=500_000)
            if sr.ret > 0:
                got += sr.ret
            elif sr.ret < 0:
                return False
        return True

    def measure(self, freq_hz, bw_hz, lat, lon, settings):
        self.apply_gain(settings)
        offset = min(self.OFFSET_HZ, max(freq_hz - 1_000, 0))
        lo = freq_hz - offset
        self.dev.setFrequency(self.RX, 0, lo)
        # throw away the first buffer after retuning (it contains the retune glitch)
        self._read(4096)
        if not self._read(self.NSAMP):
            return float("nan")
        x = self.buf
        nseg = self.NSAMP // self.FFT_N
        segs = x[: nseg * self.FFT_N].reshape(nseg, self.FFT_N) * self.window
        spec = np.abs(np.fft.fftshift(np.fft.fft(segs, axis=1), axes=1)) ** 2
        spec = spec.mean(axis=0) / (self.FFT_N * self.win_pow)   # power per bin, full-scale = 1
        binw = self.SAMPLE_RATE / self.FFT_N
        centre = self.FFT_N // 2 + int(round(offset / binw))
        half = max(int(round(bw_hz / binw / 2)), 1)
        band = spec[centre - half: centre + half + 1]
        level = 10.0 * math.log10(float(band.sum()) + 1e-20)    # dBFS
        self._last = (lo, self.SAMPLE_RATE, spec, level)
        return level

    def last_frame(self):
        return getattr(self, "_last", None)

    def spectrum(self, freq_hz, bw_hz, lat, lon, settings):
        """A fresh capture used to keep the live picture moving between dots."""
        self.measure(freq_hz, bw_hz, lat, lon, settings)
        return self._last

    def close(self):
        try:
            self.dev.deactivateStream(self.stream)
            self.dev.closeStream(self.stream)
        except Exception:
            pass


# ----------------------------------------------------------------------------
# Position helpers
# ----------------------------------------------------------------------------
def distance_m(lat1, lon1, lat2, lon2):
    """Flat-earth distance - plenty accurate over a few feet to a few miles."""
    kx = 111320.0 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot((lon2 - lon1) * kx, (lat2 - lat1) * 111320.0)


def extrapolate(fix, now):
    """
    A 1-per-second GPS (like an iPhone) is up to 1 s old. At 45 mph that is 66 ft.
    We slide the position forward along the direction of travel by the fix's age.
    On a straight road this is very good; in a sharp turn it can be off by a few feet.
    """
    age = max(0.0, min(now - fix.t_rx, 1.5))
    d = fix.speed_mps * age
    if d < 0.2:
        return fix.lat, fix.lon
    brg = math.radians(fix.course_deg)
    lat = fix.lat + (d * math.cos(brg)) / 111320.0
    lon = fix.lon + (d * math.sin(brg)) / (111320.0 * math.cos(math.radians(fix.lat)))
    return lat, lon


# ----------------------------------------------------------------------------
# Little settings web page (open http://<this-Mac>:8765 in Safari)
# ----------------------------------------------------------------------------
PAGE = """<!doctype html><html><head><meta name=viewport content="width=device-width,initial-scale=1">
<title>RF logger</title>
<style>
body{font-family:-apple-system,Helvetica,Arial,sans-serif;margin:14px;max-width:640px}
h1{font-size:20px} .box{border:1px solid #ccc;border-radius:8px;padding:10px;margin:10px 0}
input{font-size:16px;padding:4px;width:90px} button{font-size:17px;padding:8px 14px;margin:4px 2px}
table{border-collapse:collapse} td,th{padding:3px 8px;text-align:left} .big{font-size:22px;font-weight:600}
.warn{color:#b00}
</style></head><body>
<h1>RF noise logger</h1>
<div class=box id=status>loading...</div>
<div class=box><b>Frequencies (up to 4)</b>
<form id=f><table id=ch><tr><th>MHz</th><th>Width kHz</th><th>Cal dB</th></tr></table>
<p>Save a dot every <input id=sp size=4> ft</p>
<button type=submit>Save changes</button> <button type=button id=pause>Pause / Resume</button>
</form><div id=msg></div></div>
<script>
const $=id=>document.getElementById(id);
let cfg=null;
function row(c,i){return `<tr><td><input name=mhz step=any value="${c.mhz}"></td>`+
 `<td><input name=bw step=any value="${c.bw_khz}"></td><td><input name=cal step=any value="${c.cal_db}"></td></tr>`}
function build(c){
  let h='<tr><th>MHz</th><th>Width kHz</th><th>Cal dB</th></tr>';
  for(let i=0;i<4;i++)h+=row(c.channels[i]||{mhz:'',bw_khz:'',cal_db:0},i);
  $('ch').innerHTML=h;$('sp').value=c.spacing_ft;}
async function poll(){
  try{const r=await fetch('/status');const s=await r.json();
   if(!cfg){cfg=s.settings;build(cfg);}
   let h='<div class=big>'+(s.settings.paused?'PAUSED':'Logging')+' &mdash; '+s.rows+' dots saved</div>';
   h+='GPS: '+s.gps_status+(s.speed_mph!=null?' &mdash; '+s.speed_mph.toFixed(0)+' mph':'')+
      (s.sats!=null?', '+s.sats+' satellites':'')+'<br>';
   h+='Radio: '+s.sdr+'<br>File: '+s.file+'<br><table>';
   for(const l of s.last){h+='<tr><td>'+l.mhz+' MHz</td><td><b>'+l.level.toFixed(1)+' dB</b></td></tr>';}
   h+='</table>'; $('status').innerHTML=h;
  }catch(e){$('status').innerHTML='<span class=warn>lost contact with logger</span>';}
}
$('f').onsubmit=async e=>{e.preventDefault();
  const m=[...document.getElementsByName('mhz')],b=[...document.getElementsByName('bw')],c=[...document.getElementsByName('cal')];
  const ch=[];for(let i=0;i<m.length;i++){if(m[i].value!=='')ch.push({mhz:+m[i].value,bw_khz:+(b[i].value||5),cal_db:+(c[i].value||0)});}
  const r=await fetch('/set',{method:'POST',body:JSON.stringify({channels:ch,spacing_ft:+$('sp').value})});
  $('msg').textContent=r.ok?'Saved.':'Could not save.';cfg=null;};
$('pause').onclick=async()=>{await fetch('/pause',{method:'POST'});};
setInterval(poll,1000);poll();
</script></body></html>"""


def make_handler(settings, state, stop_event):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json"):
            data = body.encode() if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path.startswith("/status"):
                self._send(200, json.dumps(dict(state, settings=settings.get())))
            elif self.path.startswith("/spectrum"):
                try:
                    after = int(self.path.split("after=")[1].split("&")[0])
                except Exception:
                    after = -1
                with PAN_FRAME["lock"]:
                    f = PAN_FRAME["f"]
                if f is None or f["seq"] == after:
                    self._send(200, json.dumps({"same": True, "seq": after if f is None else f["seq"]}))
                else:
                    self._send(200, json.dumps(f))
            else:
                self._send(200, PAGE, "text/html; charset=utf-8")

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(n).decode() if n else ""
            try:
                if self.path == "/stop":
                    stop_event.set()
                elif self.path == "/pause":
                    cur = settings.get()
                    settings.update({"paused": not cur["paused"]})
                elif self.path == "/pan":
                    req = json.loads(body)
                    ch = int(req.get("channel", -1))
                    settings.update({"pan_channel": ch if 0 <= ch < MAX_CHANNELS else -1})
                    if ch < 0:
                        with PAN_FRAME["lock"]:
                            PAN_FRAME["f"] = None
                elif self.path == "/set":
                    req = json.loads(body)
                    upd = {}
                    if "channels" in req:
                        chans = []
                        for c in req.get("channels", [])[:MAX_CHANNELS]:
                            mhz = float(c["mhz"])
                            if not (0.001 <= mhz <= 2000):
                                raise ValueError("frequency must be 0.001 to 2000 MHz")
                            chans.append({"mhz": mhz,
                                          "bw_khz": max(0.5, float(c.get("bw_khz", 5))),
                                          "cal_db": float(c.get("cal_db", 0))})
                        if not chans:
                            raise ValueError("need at least one frequency")
                        upd["channels"] = chans
                    if "sample_mode" in req:
                        upd["sample_mode"] = "time" if str(req["sample_mode"]) == "time" else "distance"
                    if "interval_s" in req:
                        upd["interval_s"] = min(max(0.5, float(req["interval_s"])), 3600.0)
                    if "spacing_ft" in req:
                        upd["spacing_ft"] = min(max(2.0, float(req["spacing_ft"])), 5280.0)
                    if "if_gain_db" in req:
                        upd["if_gain_db"] = int(min(max(int(req["if_gain_db"]), 20), 59))
                    if "rf_gain_state" in req:
                        upd["rf_gain_state"] = int(min(max(int(req["rf_gain_state"]), 0), 27))
                    if upd:
                        settings.update(upd)
                self._send(200, "{}")
            except Exception as e:
                self._send(400, json.dumps({"error": str(e)}))
    return H


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# ----------------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Drive-route RF noise logger")
    ap.add_argument("--gps", required=True,
                    help="GPS source:  tcp:IP:PORT (iPhone GPS2IP) | "
                         "serial:/dev/cu.usbmodemXXXX[:baud] (USB GPS) | sim")
    ap.add_argument("--sdr", default="sdrplay", choices=["sdrplay", "sim"],
                    help="radio: sdrplay (default) or sim (fake data for testing)")
    ap.add_argument("--outdir", default="logs", help="folder for CSV files")
    ap.add_argument("--settings", default="settings.json", help="saved frequency settings")
    ap.add_argument("--port", type=int, default=8765, help="settings web page port")
    ap.add_argument("--local-only", action="store_true",
                    help="settings page reachable only from this Mac")
    ap.add_argument("--name", default="", help="route name (goes into the file name)")
    ap.add_argument("--sim-speed", type=float, default=0,
                    help="practice mode only: play the drive this many times faster than real time "
                         "(0 = as fast as possible)")
    ap.add_argument("--no-extrapolate", action="store_true",
                    help="use raw GPS positions (no sliding forward by fix age)")
    args = ap.parse_args()
    L.setup("logger")

    settings = Settings(args.settings)

    # --- GPS
    if args.gps == "sim":
        gps = SimGps()
    else:
        gps = NmeaGps(args.gps)
        gps.start()

    # --- Radio
    sdr = SimSdr() if args.sdr == "sim" else SoapySdr(settings.get())

    # --- Output file
    os.makedirs(args.outdir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", args.name).strip("-")[:40]
    base = f"drive_{stamp}" + (f"_{slug}" if slug else "") + ("_PRACTICE" if args.gps == "sim" else "")
    path = os.path.join(args.outdir, base + ".csv")
    meta_path = os.path.join(args.outdir, base + ".meta.json")
    meta = {"name": args.name or base, "notes": "", "started_local": datetime.now().isoformat(timespec="seconds"),
            "gps": args.gps if args.gps == "sim" else args.gps.split(":")[0],
            "radio": sdr.name, "channels": settings.get()["channels"]}
    try:
        with open(meta_path, "w") as mf:
            json.dump(meta, mf, indent=2)
    except OSError:
        pass
    fh = open(path, "w", newline="")
    w = csv.writer(fh)
    w.writerow(["time_utc", "lat", "lon", "speed_mph", "freq_mhz", "bw_khz",
                "level_dbfs", "level_cal", "sats", "hdop"])
    fh.flush()

    # --- Shared status for the web page
    state = {"rows": 0, "gps_status": "starting", "speed_mph": None, "sats": None,
             "sdr": sdr.name, "file": path, "last": []}
    stop_event = threading.Event()
    srv = ThreadingHTTPServer(("127.0.0.1" if args.local_only else "0.0.0.0", args.port),
                              make_handler(settings, state, stop_event))
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    print("=" * 62)
    print(f" Logging to   : {path}")
    print(f" Radio        : {sdr.name}")
    print(f" Settings page: http://localhost:{args.port}   (iPhone/iPad: "
          f"http://{lan_ip()}:{args.port})")
    print(" Press Ctrl+C to stop. The CSV is saved as it goes.")
    print("=" * 62)

    # Keep the computer awake while logging (a sleeping computer stops the log)
    try:
        if C.IS_MAC:
            subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])
        elif C.IS_WIN:
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)   # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
    except Exception:
        pass

    pan_state = {"t": 0.0}

    def pan_idle(cfg, lat, lon):
        """While waiting for the next dot, keep the live band picture moving. True if we did work."""
        ci = cfg.get("pan_channel", -1)
        chans = cfg["channels"][:MAX_CHANNELS]
        if not (0 <= ci < len(chans)) or not hasattr(sdr, "spectrum"):
            return False
        if time.time() - pan_state["t"] < 0.04:
            return False
        pan_state["t"] = time.time()
        ch = chans[ci]
        try:
            lo, rate, spec, level = sdr.spectrum(ch["mhz"] * 1e6, ch["bw_khz"] * 1e3, lat, lon, cfg)
            publish_spectrum(lo, rate, spec, ch["mhz"] * 1e6, ch["bw_khz"] * 1e3, level, ci)
        except Exception:
            return False
        return True

    last_lat = last_lon = None
    last_t = None
    dots = 0
    last_print = 0.0
    try:
        while not stop_event.is_set():
            cfg = settings.get()
            fix = gps.latest()
            if args.gps == "sim" and args.sim_speed > 0:
                time.sleep(0.1 / args.sim_speed)
            state["gps_status"] = getattr(gps, "status", "")
            if getattr(gps, "finished", False):
                print("Simulated route finished.")
                break
            if fix is None or cfg["paused"]:
                pan_idle(cfg, 0.0, 0.0)
                time.sleep(0.05)
                continue

            now = time.time()
            if args.gps == "sim" or args.no_extrapolate:
                lat, lon = fix.lat, fix.lon
            else:
                lat, lon = extrapolate(fix, now)

            moved = (distance_m(last_lat, last_lon, lat, lon) * FT_PER_M
                     if last_lat is not None else 1e9)
            if cfg.get("sample_mode") == "time":
                # time mode: one reading every interval_s seconds, even when standing still
                wait_more = (last_t is not None and
                             (time.time() - last_t) < float(cfg.get("interval_s", 5.0)))
            else:
                wait_more = moved < cfg["spacing_ft"]
            if wait_more:
                if not pan_idle(cfg, lat, lon) and args.gps != "sim":
                    time.sleep(0.01)
                continue

            # --- one measurement cycle: every frequency in turn
            t_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            last = []
            for ci, ch in enumerate(cfg["channels"][:MAX_CHANNELS]):
                level = sdr.measure(ch["mhz"] * 1e6, ch["bw_khz"] * 1e3, lat, lon, cfg)
                if math.isnan(level):
                    continue
                if ci == cfg.get("pan_channel", -1):
                    lf = sdr.last_frame() if hasattr(sdr, "last_frame") else None
                    if lf:
                        publish_spectrum(lf[0], lf[1], lf[2], ch["mhz"] * 1e6, ch["bw_khz"] * 1e3, lf[3], ci)
                w.writerow([t_iso, f"{lat:.7f}", f"{lon:.7f}", f"{fix.speed_mps*MPH_PER_MPS:.1f}",
                            f"{ch['mhz']:.4f}", f"{ch['bw_khz']:.1f}",
                            f"{level:.2f}", f"{level + ch['cal_db']:.2f}",
                            "" if fix.sats is None else fix.sats,
                            "" if fix.hdop is None else fix.hdop])
                last.append({"ch": ci, "mhz": ch["mhz"], "level": level + ch["cal_db"]})
            fh.flush()
            last_lat, last_lon = lat, lon
            last_t = time.time()
            dots += 1
            state.update(rows=dots, speed_mph=fix.speed_mps * MPH_PER_MPS,
                         sats=fix.sats, last=last)
            if time.time() - last_print > 2:
                last_print = time.time()
                txt = "  ".join(f"{x['mhz']:g}MHz={x['level']:.1f}" for x in last)
                print(f"\r dots={dots:5d}  {fix.speed_mps*MPH_PER_MPS:3.0f} mph  {txt}   ",
                      end="", flush=True)
    except KeyboardInterrupt:
        pass
    except Exception:
        L.exception("the logging loop crashed")
        raise
    finally:
        fh.close()
        try:
            meta["rows_saved"] = dots
            meta["ended_local"] = datetime.now().isoformat(timespec="seconds")
            with open(meta_path) as mf:                       # keep any notes edited meanwhile
                old = json.load(mf)
            old.update({k: meta[k] for k in ("rows_saved", "ended_local")})
            with open(meta_path, "w") as mf:
                json.dump(old, mf, indent=2)
        except Exception:
            pass
        if hasattr(sdr, "close"):
            sdr.close()
        srv.shutdown()
        print(f"\nDone. {dots} positions saved to {path}")
        print(f"Next:  python3 make_map.py {path}")


if __name__ == "__main__":
    main()
