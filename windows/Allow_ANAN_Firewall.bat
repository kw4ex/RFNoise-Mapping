@echo off
rem Lets RFI Trail receive data from network radios (ANAN, Hermes Lite 2, FlexRadio) through the Windows firewall.
rem Only from this computer's own network (remoteip=localsubnet), so nothing from the internet can reach it.
setlocal
set "QUIET="
if /i "%~1"=="/fromsetup" set "QUIET=1"
net session >nul 2>&1
if not %errorlevel%==0 goto :elevate
for %%I in ("%~dp0..\venv\Scripts") do set "V=%%~fI"
rem the real Python that runs the program (a Windows venv starts the original Python behind its own launcher)
set "BH="
if exist "%V%\..\pyvenv.cfg" for /f "tokens=1,* delims==" %%A in ('findstr /b /i "home" "%V%\..\pyvenv.cfg"') do set "BH=%%B"
if defined BH for /f "tokens=* delims= " %%A in ("%BH%") do set "BH=%%A"
echo Removing any old RFI Trail firewall rules...
netsh advfirewall firewall delete rule name="RFI Trail (Python)" >nul 2>&1
netsh advfirewall firewall delete rule name="RFI Trail (Pythonw)" >nul 2>&1
netsh advfirewall firewall delete rule name="RFI Trail (radio data)" >nul 2>&1
netsh advfirewall firewall delete rule name="RFI Trail (base Python)" >nul 2>&1
echo Adding the rules...
netsh advfirewall firewall add rule name="RFI Trail (radio data)" dir=in action=allow protocol=UDP remoteip=localsubnet profile=any
netsh advfirewall firewall add rule name="RFI Trail (Python)" dir=in action=allow program="%V%\python.exe" enable=yes profile=any remoteip=localsubnet
netsh advfirewall firewall add rule name="RFI Trail (Pythonw)" dir=in action=allow program="%V%\pythonw.exe" enable=yes profile=any remoteip=localsubnet
if defined BH if exist "%BH%\python.exe" netsh advfirewall firewall add rule name="RFI Trail (base Python)" dir=in action=allow program="%BH%\python.exe" enable=yes profile=any remoteip=localsubnet
echo.
echo Done. RFI Trail may now receive data from network radios on this network.
echo Close RFI Trail and start it again, then press Scan for radios.
if defined QUIET (
  echo This window closes by itself in a few seconds...
  timeout /t 5 /nobreak >nul
  exit /b 0
)
pause
exit /b 0
:elevate
echo Windows will ask for permission to change the firewall. Please answer Yes.
if defined QUIET (
  powershell -NoProfile -Command "try { Start-Process -FilePath '%~f0' -ArgumentList '/fromsetup' -Verb RunAs -Wait } catch { Write-Host 'Permission was not given, so the firewall was not changed. You can run Tools\Allow_ANAN_Firewall.bat later.' }"
) else (
  powershell -NoProfile -Command "try { Start-Process -FilePath '%~f0' -Verb RunAs -Wait } catch { Write-Host 'Permission was not given, so the firewall was not changed.' }"
)
exit /b 0
