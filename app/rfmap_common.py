"""
rfmap_common.py - small helpers shared by every part of RF Noise Map.

  * where the program lives and where YOUR data lives
  * finding the SoapySDR radio library on Mac / Windows / Linux
"""
import glob
import os
import re
import sys

APP_NAME = "RF Noise Map"
VERSION = "1.2.1"
IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform.startswith("win")


def app_dir():
    """Folder holding the program files."""
    return os.path.dirname(os.path.abspath(__file__))


def install_dir():
    """
    The folder that holds app/ when installed by the Windows installer (C:\\RadioScripts\\RFNoise by
    default). It is recognised by a small marker file the installer writes there. None otherwise.
    """
    parent = os.path.dirname(app_dir())
    return parent if os.path.exists(os.path.join(parent, "rfnoise_install.flag")) else None


def data_dir():
    """
    Folder holding YOUR data (drives, maps, exports, backups, settings).
      * Windows installer: the same folder as the program (e.g. C:\\RadioScripts\\RFNoise)
      * Mac:               "RF Noise Map" in your home folder (NOT Documents: macOS blocks programs from Documents)
    The RFMAP_DATA variable overrides both (used for tests).
    """
    home = os.path.expanduser("~")
    default = os.path.join(home, APP_NAME) if IS_MAC else os.path.join(home, "Documents", APP_NAME)
    base = os.environ.get("RFMAP_DATA") or install_dir() or default
    for sub in ("Drives", "Maps", "Exports", "Backups", "Settings", "Recordings", "Logs"):
        os.makedirs(os.path.join(base, sub), exist_ok=True)
    if IS_MAC and base == default:          # carry settings over from the old Documents location, if it can be read
        new_cfg = os.path.join(base, "Settings", "config.json")
        old_cfg = os.path.join(home, "Documents", APP_NAME, "Settings", "config.json")
        try:
            if not os.path.exists(new_cfg) and os.path.exists(old_cfg):
                import shutil
                shutil.copyfile(old_cfg, new_cfg)
        except Exception:
            pass
    return base


def sub_dir(name):
    return os.path.join(data_dir(), name)


# ----------------------------------------------------------------------------
# Finding SoapySDR (the library that talks to the SDRplay)
# ----------------------------------------------------------------------------
def _candidate_dirs():
    dirs = []
    if IS_WIN:
        for root in filter(None, [os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432"),
                                  os.environ.get("SOAPY_SDR_ROOT")]):
            base = root if os.path.basename(root).lower() == "pothossdr" else os.path.join(root, "PothosSDR")
            dirs += [os.path.join(base, "lib", "site-packages"), os.path.join(base, "bin")]
            dirs += glob.glob(os.path.join(base, "lib", "python*", "site-packages"))
    elif IS_MAC:
        for pre in ("/opt/homebrew", "/usr/local", "/opt/local"):
            dirs += glob.glob(os.path.join(pre, "lib", "python3*", "site-packages"))
            dirs += glob.glob(os.path.join(pre, "lib", "python3*", "dist-packages"))
    else:
        dirs += glob.glob("/usr/lib/python3*/dist-packages") + glob.glob("/usr/local/lib/python3*/dist-packages")
    return [d for d in dirs if os.path.isdir(d)]


PRELOAD_NOTE = ""


def _pothos_root(d):
    """The PothosSDR folder (the one that holds both 'bin' and 'lib') above a site-packages folder."""
    p = d
    for _ in range(6):
        if os.path.isdir(os.path.join(p, "bin")) and os.path.isdir(os.path.join(p, "lib")):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    return None


def _prepare_windows(d):
    """
    Windows only: let Python find the SoapySDR DLLs and the SDRplay plugin.
    PothosSDR's own folder must be named in SOAPY_SDR_ROOT (so the plugins are found), and its 'bin'
    folder and the SDRplay API folder must be on this program's search path.
    """
    root = _pothos_root(d)
    dirs = [d]
    if root:
        os.environ["SOAPY_SDR_ROOT"] = root
        dirs.append(os.path.join(root, "bin"))
    pf = os.environ.get("ProgramFiles") or r"C:\Program Files"
    api = os.path.join(pf, "SDRplay", "API", "x64" if sys.maxsize > 2 ** 32 else "x86")
    dirs.append(api)
    # Windows: load the helper DLLs ourselves, by full path, before SoapySDR looks for its plugins.
    # (Plugins are loaded with a plain LoadLibrary that ignores add_dll_directory; a DLL that is already
    # loaded in this program is found by name, so pre-loading them makes the plugins load.)
    if sys.platform == "win32":
        global PRELOAD_NOTE
        try:
            import ctypes
            bindir = os.path.join(root, "bin") if root else None
            try:
                if bindir and os.path.isdir(bindir):
                    ctypes.windll.kernel32.SetDllDirectoryW(bindir)
            except Exception:
                pass
            todo = []
            # Use the SDRplay API copy that ships inside PothosSDR\bin (the one its plugin was built with,
            # and the one SoapySDRUtil uses). Loading the newer system-wide copy first breaks the plugin.
            bin_api = os.path.join(bindir, "sdrplay_api.dll") if bindir else ""
            if bin_api and os.path.isfile(bin_api):
                todo.append(bin_api)
            elif os.path.isfile(os.path.join(api, "sdrplay_api.dll")):
                todo.append(os.path.join(api, "sdrplay_api.dll"))
            if bindir and os.path.isdir(bindir):
                todo += sorted(glob.glob(os.path.join(bindir, "*.dll")))
            failed = []
            for _ in range(3):                         # a few passes: some DLLs need others loaded first
                failed = []
                for full in todo:
                    try:
                        ctypes.WinDLL(full)
                    except OSError:
                        failed.append(os.path.basename(full))
                todo = [f for f in todo if os.path.basename(f) in failed]
                if not failed:
                    break
            PRELOAD_NOTE = ("Helper files that would not load: " + ", ".join(failed) + ". ") if failed else ""
            if not (bin_api and os.path.isfile(bin_api)) and not os.path.isfile(os.path.join(api, "sdrplay_api.dll")):
                PRELOAD_NOTE += "sdrplay_api.dll was not found in " + api + ". "
        except Exception as e:
            PRELOAD_NOTE = "Preload problem: " + str(e) + ". "
    current = os.environ.get("PATH", "").lower().split(os.pathsep)
    for extra in dirs:
        if not os.path.isdir(extra):
            continue
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(extra)
            except OSError:
                pass
        if extra.lower() not in current and len(os.environ.get("PATH", "")) + len(extra) < 30000:
            os.environ["PATH"] = extra + os.pathsep + os.environ.get("PATH", "")


def find_soapy():
    """
    Try to import SoapySDR. If it is not on Python's normal path, look in the usual
    install places (Homebrew on Mac, PothosSDR on Windows).
    Returns (module_or_None, plain_english_note).
    """
    first = ""
    if IS_WIN:      # set up the DLL search BEFORE the first import, even if Python can already see SoapySDR
        for d in _candidate_dirs():
            if glob.glob(os.path.join(d, "SoapySDR.py")) or glob.glob(os.path.join(d, "_SoapySDR*")):
                _prepare_windows(d)
                break
    try:
        import SoapySDR
        return SoapySDR, ("found. " + PRELOAD_NOTE).strip()
    except ImportError:
        pass
    except Exception as e:                      # installed but broken (wrong Python version etc.)
        first = str(e)
    for d in _candidate_dirs():
        has = glob.glob(os.path.join(d, "SoapySDR.py")) or glob.glob(os.path.join(d, "_SoapySDR*"))
        if not has:
            continue
        if d not in sys.path:
            sys.path.append(d)
        if IS_WIN:
            _prepare_windows(d)
        try:
            import SoapySDR
            return SoapySDR, f"found in {d}. {PRELOAD_NOTE}".strip()
        except Exception as e:
            first = f"{e} (looked in {d})"
            m = re.search(r"python(\d)\.?(\d+)", d.replace("\\", "/"), re.I)
            if m and (int(m.group(1)), int(m.group(2))) != sys.version_info[:2]:
                first += (f" The radio library there is made for Python {m.group(1)}.{m.group(2)}, "
                          f"but this program runs on Python {sys.version_info[0]}.{sys.version_info[1]}.")
    return None, ("SoapySDR is not installed or does not match this Python. " + first).strip()
