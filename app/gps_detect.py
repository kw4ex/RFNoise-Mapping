"""
gps_detect.py - finds a USB GPS puck by itself.

What it does, in plain words:
  1. Lists the serial (COM) ports on this computer.
  2. Puts the ones whose names look like a GPS first (u-blox, GPS, USB Serial, Prolific ...).
  3. Listens on each one at the common speeds (4800, 9600, 38400, 115200) for a few seconds.
  4. A GPS puck sends lines that start with "$GP", "$GN" ... and end with a checksum. When it
     hears real lines like that, it has found the puck AND the right speed.

Run it by itself:      python gps_detect.py
or press 'Find my GPS' in the RF Noise Map window.
"""

import sys
import time

BAUDS = (4800, 9600, 38400, 115200)

# Words in a port's name that suggest a GPS or a USB-serial chip that GPS pucks use.
LIKELY = ("gps", "gnss", "u-blox", "ublox", "sirf", "garmin", "navigation", "globalsat", "bu-353",
          "usb serial", "usb-serial", "prolific", "ftdi", "silicon labs", "cp210", "ch340", "ch341",
          "qinheng", "cdc", "acm", "ttyusb", "usbmodem", "usbserial")
# Ports that are never a puck, or hang when probed.
SKIP = ("bluetooth", "standard serial over", "modem", "voicemeeter", "virtual", "com0com", "eltima",
        "vspe", "hub4com")


def nmea_ok(line):
    """True if this is a well-formed NMEA sentence with a correct checksum."""
    if not (line.startswith("$") and "*" in line):
        return False
    body, _, cs = line[1:].partition("*")
    cs = cs.strip()[:2]
    if len(cs) != 2:
        return False
    calc = 0
    for ch in body:
        calc ^= ord(ch)
    try:
        return calc == int(cs, 16)
    except ValueError:
        return False


def list_ports():
    """[(device, description)] for every serial port, or [] if pyserial is missing."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    out = []
    for p in list_ports.comports():
        desc = " ".join(x for x in (p.description, p.manufacturer, p.hwid) if x)
        out.append((p.device, desc))
    return out


def _score(desc):
    d = desc.lower()
    if any(k in d for k in SKIP):
        return -1
    return 2 if any(k in d for k in LIKELY) else 0


def probe(port, baud, listen=2.5):
    """
    Listen on one port at one speed.
    Returns dict: ok (heard real NMEA), busy (port in use), error, lines, fix, sats, sample.
    """
    res = {"port": port, "baud": baud, "ok": False, "busy": False, "error": "", "lines": 0,
           "fix": False, "sats": None, "sample": ""}
    try:
        import serial
    except ImportError:
        res["error"] = "pyserial is not installed"
        return res
    try:
        ser = serial.Serial(port, baud, timeout=0.4)
    except Exception as e:
        msg = str(e)
        res["error"] = msg
        res["busy"] = ("denied" in msg.lower() or "permission" in msg.lower() or "busy" in msg.lower()
                       or "in use" in msg.lower())
        return res
    try:
        t0 = time.time()
        buf = b""
        while time.time() - t0 < listen:
            buf += ser.read(512)
            while b"\n" in buf:
                raw, _, buf = buf.partition(b"\n")
                line = raw.decode("ascii", "ignore").strip()
                if nmea_ok(line):
                    res["lines"] += 1
                    if not res["sample"]:
                        res["sample"] = line[:60]
                    f = line.split("*")[0].split(",")
                    kind = f[0][3:]
                    if kind == "RMC" and len(f) > 2 and f[2] == "A":
                        res["fix"] = True
                    if kind == "GGA" and len(f) > 7:
                        try:
                            if int(f[6] or 0) > 0:
                                res["fix"] = True
                            res["sats"] = int(f[7] or 0)
                        except ValueError:
                            pass
            if res["lines"] >= 3:
                break
    finally:
        try:
            ser.close()
        except Exception:
            pass
    res["ok"] = res["lines"] >= 2
    return res


def find_gps(budget_s=60, listen=2.5, progress=None, only_port=None):
    """
    Look for a GPS. Returns
      {"found": [ {port, baud, fix, sats, desc, sample} ...],
       "busy":  [ports that are in use by another program],
       "tried": [ports tried], "ports": [all ports seen], "note": plain-English summary}
    """
    say = progress or (lambda m: None)
    t_start = time.time()
    ports = list_ports()
    if not ports:
        try:
            import serial  # noqa
            note = "No serial ports were found on this computer."
        except ImportError:
            note = "pyserial is not installed, so USB GPS cannot be used. Run the installer again."
        return {"found": [], "busy": [], "tried": [], "ports": [], "note": note}
    if only_port:
        ports = [(d, ds) for d, ds in ports if d.lower() == only_port.lower()] or [(only_port, "")]
    ranked = sorted(ports, key=lambda p: (-_score(p[1]), p[0]))
    likely = [p for p in ranked if _score(p[1]) >= 2]
    others = [p for p in ranked if _score(p[1]) == 0]
    found, busy, tried = [], [], []
    for group in (likely, others):
        if found:
            break
        for dev, desc in group:
            if time.time() - t_start > budget_s:
                break
            tried.append(dev)
            hit = None
            for baud in BAUDS:
                if time.time() - t_start > budget_s:
                    break
                say(f"Listening on {dev} at {baud} ...")
                r = probe(dev, baud, listen)
                if r["busy"]:
                    busy.append(dev)
                    break
                if r["error"] and not r["ok"]:
                    break                              # cannot open: no point trying other speeds
                if r["ok"]:
                    hit = r
                    break
            if hit:
                found.append({"port": dev, "baud": hit["baud"], "fix": hit["fix"], "sats": hit["sats"],
                              "desc": desc, "sample": hit["sample"]})
                break
    if found:
        f = found[0]
        fixtxt = ("and it has a position fix" if f["fix"] else
                  "but it has no position yet (take it outdoors or to a window and give it a few minutes)")
        note = f"Found a GPS on {f['port']} at speed {f['baud']}, {fixtxt}."
    elif busy:
        note = ("Port(s) " + ", ".join(busy) + " are in use by another program, so I could not listen. "
                "Close any other GPS or mapping program (and RF Noise Map's own logging), "
                "or unplug the puck, wait 5 seconds and plug it in again.")
    else:
        note = ("No GPS was heard on: " + (", ".join(tried) if tried else "any port") + ". "
                "Is the puck plugged in? Some pucks send nothing until they can see the sky.")
    return {"found": found, "busy": busy, "tried": tried,
            "ports": [d for d, _ in ports], "note": note}


def save_to_settings(port, baud):
    """Remember the GPS in RF Noise Map's settings so the panel is already set up."""
    import json
    import os
    import rfmap_common as C
    path = os.path.join(C.sub_dir("Settings"), "config.json")
    cfg = {}
    try:
        with open(path) as f:
            cfg = json.load(f)
    except Exception:
        pass
    cfg.update({"gps_mode": "usb", "gps_serial": port, "gps_baud": int(baud)})
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)
    return path


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    only = args[0] if args else None
    res = find_gps(budget_s=120, progress=lambda m: print("  " + m), only_port=only)
    print()
    print(res["note"])
    for f in res["found"]:
        print(f"  Port {f['port']}  speed {f['baud']}  fix: {'yes' if f['fix'] else 'not yet'}  "
              f"satellites: {f['sats'] if f['sats'] is not None else '?'}   ({f['desc']})")
    if res["found"] and "--save" in sys.argv:
        try:
            p = save_to_settings(res["found"][0]["port"], res["found"][0]["baud"])
            print(f"Saved to RF Noise Map's settings ({p}). The panel will already be set to USB GPS.")
        except Exception as e:
            print("Could not save the settings:", e)
    return 0 if res["found"] else 1


if __name__ == "__main__":
    sys.exit(main())
