"""
gps_detect.py - finds a USB GPS puck by itself.

What it does, in plain words:
  1. Lists the serial (COM) ports on this computer.
  2. Puts the ones whose names look like a GPS first (u-blox, GPS, USB Serial, Prolific ...).
  3. Listens on each one at the common speeds (4800, 9600, 38400, 115200) for a few seconds.
  4. A GPS puck sends lines that start with "$GP", "$GN" ... and end with a checksum. When it
     hears real lines like that, it has found the puck AND the right speed.

Run it by itself:      python gps_detect.py
or press 'Find my GPS' in the RFI Trail window.
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
                "Close any other GPS or mapping program (and RFI Trail's own logging), "
                "or unplug the puck, wait 5 seconds and plug it in again.")
    else:
        note = ("No GPS was heard on: " + (", ".join(tried) if tried else "any port") + ". "
                "Is the puck plugged in? Some pucks send nothing until they can see the sky.")
    return {"found": found, "busy": busy, "tried": tried,
            "ports": [d for d, _ in ports], "note": note}


def save_to_settings(port, baud):
    """Remember the GPS in RFI Trail's settings so the panel is already set up."""
    import json
    import os
    import nt_common as C
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
            print(f"Saved to RFI Trail's settings ({p}). The panel will already be set to USB GPS.")
        except Exception as e:
            print("Could not save the settings:", e)
    return 0 if res["found"] else 1


if __name__ == "__main__":
    sys.exit(main())


# ----------------------------------------------------------------------------
# iPhone running GPS2IP (or GPS2IP Lite): it sends NMEA lines over the network (a TCP address and port, 11123 by default)
# ----------------------------------------------------------------------------
def _local_ips():
    """This computer's own IPv4 addresses on real networks (Wi-Fi, hotspot, cable)."""
    import re
    import socket
    import subprocess
    ips = []
    try:
        if sys.platform.startswith("win"):
            out = subprocess.run(["ipconfig"], capture_output=True, text=True, timeout=5, creationflags=0x08000000).stdout
            ips += re.findall(r"IPv4[^:]*:\s*(\d+\.\d+\.\d+\.\d+)", out)
        else:
            out = subprocess.run(["ifconfig"], capture_output=True, text=True, timeout=5).stdout
            ips += re.findall(r"inet (\d+\.\d+\.\d+\.\d+)", out)
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))                     # sends nothing; only asks which address would be used
        ips.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    out = []
    for ip in ips:
        if ip.startswith(("127.", "169.254.", "0.")) or ip in out:
            continue
        out.append(ip)
    return out


def _probe_port(host, port, t=0.4):
    import socket
    try:
        s = socket.create_connection((host, port), timeout=t)
        s.close()
        return True
    except Exception:
        return False


def _scan(port, ips, budget_s=8.0):
    """Which addresses next to this computer's own (the same /24 network) have the GPS2IP port open."""
    import concurrent.futures as cf
    cand = []
    for ip in ips:
        a = ip.rsplit(".", 1)[0]
        cand += ["%s.%d" % (a, i) for i in range(1, 255) if "%s.%d" % (a, i) != ip]
    found = []
    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=96) as ex:
        futs = {ex.submit(_probe_port, h, port): h for h in cand}
        for f in cf.as_completed(futs, timeout=budget_s + 5):
            try:
                if f.result():
                    found.append(futs[f])
            except Exception:
                pass
            if time.time() - t0 > budget_s:
                break
    return found


def _listen_nmea(host, port, seconds=4.0):
    """Connect to GPS2IP and listen. Returns (error_text_or_None, list_of_good_lines, n_bad_lines, seconds_listened)."""
    import socket
    try:
        s = socket.create_connection((host, port), timeout=3.0)
    except socket.timeout:
        return "timeout", [], 0, 0.0
    except ConnectionRefusedError:
        return "refused", [], 0, 0.0
    except OSError as e:
        return "oserror:%s" % e, [], 0, 0.0
    s.settimeout(1.0)
    good, bad, buf, t0 = [], 0, b"", time.time()
    try:
        while time.time() - t0 < seconds:
            try:
                chunk = s.recv(4096)
            except socket.timeout:
                continue
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, _, buf = buf.partition(b"\n")
                line = line.decode("ascii", "ignore").strip()
                if not line:
                    continue
                if nmea_ok(line):
                    good.append((time.time() - t0, line))
                else:
                    bad += 1
    finally:
        s.close()
    return None, good, bad, time.time() - t0


def _deg(v, hemi):
    try:
        x = float(v)
    except ValueError:
        return None
    d = int(x // 100)
    r = d + (x - d * 100) / 60.0
    return -r if hemi in ("S", "W") else r


def describe_nmea(good):
    """What the lines say: which sentence types, whether there is a fix, satellites, accuracy, position, speed, update rate."""
    types, fix, sats, hdop, lat, lon, speed_mph, qual = {}, None, None, None, None, None, None, None
    stamps = []
    for t, line in good:
        f = line[1:].split("*")[0].split(",")
        kind = f[0][-3:]
        types[kind] = types.get(kind, 0) + 1
        try:
            if kind == "RMC" and len(f) > 7:
                fix = (f[2] == "A") if fix is None or f[2] == "A" else fix
                stamps.append(t)
                if f[2] == "A":
                    lat, lon = _deg(f[3], f[4]), _deg(f[5], f[6])
                    if f[7]:
                        speed_mph = float(f[7]) * 1.15078
            elif kind == "GGA" and len(f) > 8:
                qual = int(f[6] or 0)
                sats = int(f[7] or 0)
                hdop = float(f[8]) if f[8] else None
                if qual > 0:
                    fix = True
                    lat, lon = _deg(f[2], f[3]), _deg(f[4], f[5])
        except (ValueError, IndexError):
            pass
    rate = None
    if len(stamps) >= 2 and stamps[-1] > stamps[0]:
        rate = (len(stamps) - 1) / (stamps[-1] - stamps[0])
    return {"types": types, "fix": bool(fix), "sats": sats, "hdop": hdop, "lat": lat, "lon": lon,
            "speed_mph": speed_mph, "rate_hz": rate, "sample": good[-1][1] if good else ""}


def find_iphone(host="", port=11123, scan=True, budget_s=20.0):
    """Test the iPhone GPS-app connection and say, in plain words, what was found and what to do if it was not.
    Tries the address in the box, the iPhone Personal Hotspot address, then (if asked) every address on this computer's network."""
    import socket
    port = int(port or 11123)
    t0 = time.time()
    tried, found_via = [], None
    cand = []
    typed = str(host or "").strip()
    loop_note = ""
    if typed.lower() in ("127.0.0.1", "localhost", "::1", "0.0.0.0"):
        loop_note = ("%s means 'this computer itself', so it can only reach a GPS source running on this computer, never the iPhone. "
                     "For the iPhone use its hotspot address (usually 172.20.10.1)." % typed)
    for h in (str(host or "").strip(), "172.20.10.1"):
        if h and h not in cand:
            cand.append(h)
    use, why, refused_hosts = None, "", []
    for h in cand:
        err, good, bad, secs = _listen_nmea(h, port, 4.0)
        tried.append(h)
        if err is None:
            use, found_via = (h, good, bad, secs), ("the address in the box" if h == str(host or "").strip() else "the iPhone's Personal Hotspot address")
            break
        if err == "refused":
            refused_hosts.append(h)
    if use is None and scan:
        ips = _local_ips()
        hits = _scan(port, ips, min(8.0, max(2.0, budget_s - (time.time() - t0)))) if ips else []
        for h in hits:
            err, good, bad, secs = _listen_nmea(h, port, 4.0)
            if err is None:
                use, found_via = (h, good, bad, secs), "found by looking on your network"
                break
    out = {"ok": False, "host": "", "port": port, "tried": tried, "steps": [], "problem": "", "summary": ""}
    if use is None:
        if refused_hosts:
            out["problem"] = ("The iPhone at %s answered, but the GPS app is not sending. Open the GPS app on the iPhone, switch its network sharing (server) on, "
                              "and check that its Port is %d." % (refused_hosts[0], port))
        else:
            out["problem"] = ("No iPhone sharing its GPS position was found. 1) Put the iPhone and this computer on the same network: either turn on the iPhone's "
                              "Personal Hotspot and join this computer to it, or use the same Wi-Fi. 2) Open the GPS app on the iPhone (NMEA Gps, GPS2IP and similar) and switch its network sharing on. "
                              "3) Keep the app on the screen (most of these apps stop sending when the screen locks unless a background setting is on). "
                              "4) If you know the address the app shows, type it in the box and press the button again.")
        if loop_note:
            out["problem"] = loop_note + " " + out["problem"]
        out["summary"] = out["problem"]
        return out
    h, good, bad, secs = use
    d = describe_nmea(good)
    out.update({"ok": True, "host": h, "port": port, "found_via": found_via, "lines": len(good), "bad_lines": bad, **d})
    steps = ([loop_note] if (loop_note and h == typed) else []) + ["Found the iPhone at %s, port %d (%s)." % (h, port, found_via)]
    if not good:
        out["ok"] = False
        out["problem"] = ("Connected to %s:%d but no GPS lines arrived in %.0f seconds. In the GPS app's settings turn on the "
                          "RMC and GGA sentences (and any 'send when not moving' option), make sure Location Services are on for the app, and keep it open." % (h, port, secs))
        steps.append(out["problem"])
    else:
        steps.append("GPS lines are arriving: %s%s." % (", ".join("%s x%d" % (k, v) for k, v in sorted(d["types"].items())),
                     (", about %.1f updates a second" % d["rate_hz"]) if d["rate_hz"] else ""))
        if "RMC" not in d["types"]:
            out["problem"] = "The GPS app is not sending the RMC sentence, which RFI Trail needs for position and speed. In the app's settings turn on RMC (GPRMC)."
            out["ok"] = False
        if d["fix"]:
            steps.append("Position fix OK%s%s." % ((", %d satellites" % d["sats"]) if d["sats"] is not None else "",
                         (", accuracy (HDOP) %.1f" % d["hdop"]) if d["hdop"] is not None else ""))
            if d["lat"] is not None:
                steps.append("Position %.5f, %.5f%s." % (d["lat"], d["lon"], (", moving at %.0f mph" % d["speed_mph"]) if d["speed_mph"] else ""))
        else:
            out["problem"] = out["problem"] or "The iPhone is connected but has no position fix yet. Go where the phone can see the sky, and check Settings > Privacy > Location Services > (this GPS app) is on."
            steps.append(out["problem"])
    out["steps"] = steps
    out["summary"] = " ".join(steps)
    return out
