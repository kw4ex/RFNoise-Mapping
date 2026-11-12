"""Builds Install_RFNoise.bat: stub + readable PowerShell + base64 zip payload (same layout as the KPA installer)."""
import base64, io, os, sys, zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
PAYLOAD = os.path.join(ROOT, "payload")
APP = os.path.join(os.path.dirname(ROOT), "app")
REPO = os.path.dirname(ROOT)
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO, "Install_RFNoise.bat")

STUB = r'''@echo off
setlocal
title RF Noise Map Installer
REM ======================================================================
REM  RF Noise Map - one-click installer
REM  Just double-click this file. It is plain text: open it in Notepad to
REM  see exactly what it does. The program files are packed (base64) at the
REM  very bottom; the installer logic is the readable PowerShell section.
REM  If Windows SmartScreen warns you: More info > Run anyway.
REM ======================================================================
set "RFNOISE_INSTALLER=%~f0"
set "RFNOISE_PS1=%TEMP%\rfnoise_installer_run.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$t=[IO.File]::ReadAllText($env:RFNOISE_INSTALLER); $i=$t.IndexOf([string][char]10+'#PS1-BEGIN')+11; $j=$t.IndexOf([string][char]10+'#PS1-END'); [IO.File]::WriteAllText($env:RFNOISE_PS1,$t.Substring($i,$j-$i))"
if not exist "%RFNOISE_PS1%" (
  echo Could not unpack the installer. Is PowerShell disabled on this PC?
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%RFNOISE_PS1%"
set "RFNOISE_RC=%ERRORLEVEL%"
del "%RFNOISE_PS1%" >nul 2>&1
echo.
if not "%RFNOISE_RC%"=="0" (
  echo The installer stopped - please read the messages above.
  pause
  exit /b
)
echo Installer finished. This window closes by itself in 60 seconds (or press any key).
timeout /t 60 >nul
exit /b
'''

def crlf(s):
    return s.replace("\r\n", "\n").replace("\n", "\r\n")

# --- zip payload
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
    for name in sorted(os.listdir(PAYLOAD)):
        p = os.path.join(PAYLOAD, name)
        if os.path.isfile(p):
            data = open(p, "rb").read()
            if name.endswith((".bat", ".txt")):          # Windows text files need CRLF line ends
                data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            z.writestr(name, data)
    # the help page and the printable guide are built from app/guide.html and docs/guides
    z.write(os.path.join(APP, "guide.html"), "RFNoise_Help.html")
    pdf = os.path.join(REPO, "docs", "guides", "RFNoise-Mapping-guide.pdf")
    if os.path.exists(pdf):
        z.write(pdf, "RFNoise_User_Guide.pdf")
    for dp, dn, fn in os.walk(APP):
        dn[:] = [d for d in dn if d != "__pycache__"]
        for f in sorted(fn):
            if f.endswith((".pyc", ".pyo")):
                continue
            full = os.path.join(dp, f)
            z.write(full, "app/" + os.path.relpath(full, APP).replace(os.sep, "/"))
b64 = base64.b64encode(buf.getvalue()).decode("ascii")
lines = [b64[i:i + 76] for i in range(0, len(b64), 76)]

ps = open(os.path.join(ROOT, "installer.ps1"), encoding="ascii").read()
ps = ps.strip("\n")
out = crlf(STUB) + "#PS1-BEGIN\r\n" + crlf(ps) + "\r\n#PS1-END\r\n#PAYLOAD-BEGIN\r\n" + "\r\n".join(lines) + "\r\n#PAYLOAD-END\r\n"
with open(OUT, "w", encoding="ascii", newline="") as f:
    f.write(out)
print(OUT, len(out), "bytes; zip", len(buf.getvalue()))
