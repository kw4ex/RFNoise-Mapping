"""
device_guard.py - finds (and, with your permission, closes) programs that keep the radio or the GPS busy.

Only one program at a time can use the SDRplay radio, and only one can open a COM (serial) port.
Two kinds of programs are handled:

  * LEFTOVERS FROM THIS PROGRAM (an old logger or test still running): closed automatically at launch.
  * OTHER PROGRAMS from a fixed list of well-known SDR / GPS programs (SDRuno, SDRconnect, SDR Console,
    HDSDR, SDRSharp, u-center ...): never closed silently. RF Noise Map shows them in a yellow box and
    closes them only when you press the button. It asks them to close politely first.

It never touches the SDRplay API Service (the radio needs that), your browser, or anything not on the list.
"""

import json
import os
import subprocess
import sys

IS_WIN = sys.platform == "win32"

# program file name (lower case) -> what to call it
OTHER_SDR_GPS = {
    "sdruno.exe": "SDRuno", "sdrconnect.exe": "SDRconnect", "sdr-console.exe": "SDR Console",
    "sdrconsole.exe": "SDR Console", "sdr console.exe": "SDR Console", "hdsdr.exe": "HDSDR",
    "sdrsharp.exe": "SDR#", "sdr#.exe": "SDR#", "cubicsdr.exe": "CubicSDR", "gqrx": "Gqrx",
    "u-center.exe": "u-center (GPS)", "ucenter.exe": "u-center (GPS)", "gpsinfo.exe": "GPSInfo",
    "gpsgate.exe": "GpsGate", "gpsgateclient.exe": "GpsGate", "gpsmon.exe": "GPS Monitor",
    "gpsd.exe": "gpsd", "gpsd": "gpsd", "sdr_server.exe": "SDR server", "rtl_tcp.exe": "rtl_tcp",
}
# scripts that belong to this program (matched on the command line of python processes)
OWN_SCRIPTS = ("rf_logger.py", "gps_speed_test.py", "diag_radio.py", "full_test.py", "check_setup.py",
               "gps_detect.py")


def _processes():
    """[{pid, name, cmd}] for every running process (best effort)."""
    out = []
    flags = 0x08000000 if IS_WIN else 0
    try:
        if IS_WIN:
            ps = ("Get-CimInstance Win32_Process | Select-Object ProcessId,Name,CommandLine | "
                  "ConvertTo-Json -Compress")
            r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                               capture_output=True, text=True, timeout=25, creationflags=flags)
            data = json.loads(r.stdout or "[]")
            if isinstance(data, dict):
                data = [data]
            for d in data:
                out.append({"pid": int(d.get("ProcessId") or 0), "name": str(d.get("Name") or ""),
                            "cmd": str(d.get("CommandLine") or "")})
        else:
            r = subprocess.run(["ps", "-axo", "pid=,comm=,args="], capture_output=True, text=True, timeout=10)
            for line in r.stdout.splitlines():
                parts = line.strip().split(None, 2)
                if len(parts) >= 2 and parts[0].isdigit():
                    out.append({"pid": int(parts[0]), "name": os.path.basename(parts[1]),
                                "cmd": parts[2] if len(parts) > 2 else ""})
    except Exception:
        pass
    return out


def _my_family():
    """This process and its parents (never close those)."""
    keep = {os.getpid(), os.getppid()}
    return keep


def find_blockers():
    """
    Returns {"own": [{pid,name,label}], "other": [{pid,name,label}]}.
    'own' = leftovers of this program, 'other' = well-known SDR/GPS programs.
    """
    keep = _my_family()
    own, other = [], []
    for p in _processes():
        if p["pid"] in keep or p["pid"] <= 4:
            continue
        name = p["name"].lower()
        cmd = p["cmd"].lower().replace("\\", "/")
        if name.startswith("python") and any(s in cmd for s in OWN_SCRIPTS):
            label = next(s for s in OWN_SCRIPTS if s in cmd)
            own.append({"pid": p["pid"], "name": p["name"], "label": f"RF Noise Map helper ({label})"})
        elif name in OTHER_SDR_GPS:
            other.append({"pid": p["pid"], "name": p["name"], "label": OTHER_SDR_GPS[name]})
    return {"own": own, "other": other}


def _alive(pid):
    for p in _processes():
        if p["pid"] == pid:
            return True
    return False


def close_pids(pids, allowed=None, force=False):
    """
    Close the given process ids. Only ids that find_blockers() lists right now are accepted
    (so nothing else can be closed through this). Polite first; force only if asked and still running.
    Returns [{pid, label, closed}].
    """
    import time
    cur = find_blockers()
    ok = {b["pid"]: b["label"] for b in cur["own"] + cur["other"]}
    res = []
    flags = 0x08000000 if IS_WIN else 0
    for pid in pids:
        if pid not in ok:
            continue
        try:
            if IS_WIN:
                subprocess.run(["taskkill", "/PID", str(pid)], capture_output=True, timeout=10, creationflags=flags)
            else:
                os.kill(pid, 15)
        except Exception:
            pass
    time.sleep(2.5)
    still = {p["pid"] for p in _processes()}
    for pid in pids:
        if pid not in ok:
            continue
        if pid in still and force:
            try:
                if IS_WIN:
                    subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=10,
                                   creationflags=flags)
                else:
                    os.kill(pid, 9)
            except Exception:
                pass
        res.append({"pid": pid, "label": ok[pid]})
    time.sleep(1.0)
    still = {p["pid"] for p in _processes()}
    for r in res:
        r["closed"] = r["pid"] not in still
    return res


def cleanup_own_leftovers():
    """Close old helper processes of this program. Safe to call at every launch."""
    b = find_blockers()["own"]
    if b:
        return close_pids([x["pid"] for x in b], force=True)
    return []


def describe(blockers):
    names = sorted({b["label"] for b in blockers["own"] + blockers["other"]})
    return ", ".join(names)


if __name__ == "__main__":
    b = find_blockers()
    if "--list" in sys.argv:              # used by the installer
        for x in b["own"] + b["other"]:
            print(f"PROGRAM:{x['pid']}:{x['label']}")
    elif "--close" in sys.argv:           # polite close of everything listed
        res = close_pids([x["pid"] for x in b["own"] + b["other"]], force=False)
        for r in res:
            print(("Closed: " if r["closed"] else "Still open (close it yourself): ") + r["label"])
        if not res:
            print("Nothing to close.")
    else:
        names = describe(b)
        if names:
            print("Programs that may be using the radio or GPS: " + names)
            print("(RF Noise Map can close them for you: yellow box in its window, or the installer.)")
        else:
            print("No other SDR or GPS programs are open. Good.")
