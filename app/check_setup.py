#!/usr/bin/env python3
"""
check_setup.py - Tells you, in plain English, what is working and what is missing.
The 'Check setup' button in the RF Noise Map window runs run_checks() below.

Command line:
  python3 check_setup.py
  python3 check_setup.py --gps tcp:172.20.10.1:11123
  python3 check_setup.py --gps serial:/dev/cu.usbmodem1101:9600
"""
import argparse
import glob
import sys
import time

import rfmap_common as C


def run_checks(gps_spec=None, listen_seconds=5):
    """Returns a list of {"name", "status": ok|fix|info, "message"}."""
    out = []

    def add(name, status, msg):
        out.append({"name": name, "status": status, "message": msg})

    # Python + numpy
    add("Python", "ok" if sys.version_info >= (3, 8) else "fix",
        f"Python {sys.version.split()[0]}" if sys.version_info >= (3, 8) else "Need Python 3.8 or newer")
    try:
        import numpy
        add("Math library", "ok", f"numpy {numpy.__version__}")
    except ImportError:
        add("Math library", "fix", "numpy is missing. Run the installer again.")

    # Radio
    soapy, note = C.find_soapy()
    if soapy is None:
        add("Radio library", "fix",
            "The SDRplay radio library (SoapySDR) is not available. " + note +
            "  You can still use Practice mode and make maps from existing logs. "
            "See the guide, 'Radio driver', for the steps.")
    else:
        add("Radio library", "ok", "SoapySDR found")
        try:
            devs = soapy.Device.enumerate("driver=sdrplay")
        except Exception as e:
            devs = []
            add("SDRplay", "fix", f"Could not ask for the radio: {e}")
        else:
            if devs:
                for d in devs:
                    dd = dict(d)
                    label = dd.get("label") or dd.get("serial") or "SDRplay"
                    add("SDRplay", "ok", f"Found: {label}")
            else:
                try:
                    import device_guard
                    who = device_guard.describe(device_guard.find_blockers())
                except Exception:
                    who = ""
                add("SDRplay", "fix",
                    ("These programs may be using the radio: " + who + ". Close them (the yellow box in the window has a button). " if who else "") +
                    "The library works but no SDRplay was found. Check: radio plugged in directly "
                    "(not through a weak hub)? SDRplay API installed from sdrplay.com and the computer "
                    "restarted afterward? On Windows, is the 'SDRplay API Service' running?")

    # USB GPS ports
    try:
        import serial  # noqa
        have_serial = True
    except ImportError:
        have_serial = False
        add("USB GPS software", "fix", "pyserial is missing (only matters for a USB GPS). Run the installer again.")
    ports = list_serial_ports()
    if ports:
        add("USB devices", "info", "Seen: " + ", ".join(ports))
    else:
        add("USB devices", "info", "No USB serial devices seen right now (fine if you use the iPhone GPS).")

    # GPS test
    if gps_spec and gps_spec != "sim":
        import rf_logger
        g = rf_logger.NmeaGps(gps_spec)
        g.start()
        t0 = time.time()
        while time.time() - t0 < listen_seconds and not g.latest():
            time.sleep(0.3)
        fx = g.latest()
        status = str(g.status)
        g.stop()                      # let go of the port so the logger (or the next check) can use it
        serial_gps = gps_spec.startswith("serial:")
        if fx:
            add("GPS", "ok", f"Position {fx.lat:.5f}, {fx.lon:.5f}, {fx.speed_mps*2.237:.0f} mph, "
                             f"{g.sats if g.sats is not None else '?'} satellites")
        elif g.lines:
            add("GPS", "fix", "The GPS is talking but has no position yet. Take it outside or near a window "
                              "and wait a minute or two (a cold start can take up to 5 minutes).")
        elif "denied" in status.lower() or "permission" in status.lower():
            add("GPS", "fix", "The GPS port is in use by another program (or an earlier check). Close any other "
                              "GPS or mapping program, quit and restart RF Noise Map, or unplug the puck for 5 "
                              "seconds and plug it back in.")
        elif serial_gps and "could not open" in status.lower():
            add("GPS", "fix", "That COM port does not exist or cannot be opened. Press 'Find my GPS' to look for the puck.")
        elif serial_gps:
            add("GPS", "fix", "The port opened but no GPS messages arrived. The speed (baud) may be wrong "
                              "(many pucks use 4800, others 9600). Press 'Find my GPS' to find the right port and speed.")
        else:
            add("GPS", "fix", f"Nothing received ({status}). iPhone: is GPS2IP running, is the computer on the "
                              "phone's hotspot, and are the address and port exactly as the app shows?")
    return out


def list_serial_ports():
    return sorted(glob.glob("/dev/cu.usb*") + glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")) or _win_ports()


def _win_ports():
    if not C.IS_WIN:
        return []
    try:
        import serial.tools.list_ports
        return [p.device for p in serial.tools.list_ports.comports()]
    except Exception:
        return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gps", help="tcp:IP:PORT or serial:PORT[:baud]")
    args = ap.parse_args()
    tag = {"ok": "[ OK ]", "fix": "[FIX ]", "info": "[ -- ]"}
    print()
    for r in run_checks(args.gps):
        print(f"  {tag[r['status']]}  {r['name']}: {r['message']}")
    print()


if __name__ == "__main__":
    main()
