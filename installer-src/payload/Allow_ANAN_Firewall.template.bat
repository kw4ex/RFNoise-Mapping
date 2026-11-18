@echo off
title RF Noise Map - allow the ANAN radio data through the Windows Firewall
REM ======================================================================
REM  Allow_ANAN_Firewall.bat  -  one small Windows Firewall rule for the ANAN
REM ======================================================================
REM  WHY: the ANAN sends its signal data to a port on this PC (UDP 1025 to 1042). Windows blocks that
REM  for Python unless a rule allows it. This adds ONE rule: inbound UDP, for the Python program that
REM  RF Noise Map uses, and only from computers on your own network (local subnet).
REM  It needs administrator permission: Windows asks you once.
REM  To take the rule away again:  Allow_ANAN_Firewall.bat remove
REM
set "PYCMD=@@PYCMD@@"
set "RULE=RF Noise Map - ANAN radio data (Python)"
REM
net session >nul 2>&1
if errorlevel 1 (
  echo This needs administrator permission. Windows will ask you; choose Yes.
  echo If no question appears, close this window, right-click Allow_ANAN_Firewall.bat and choose "Run as administrator".
  if "%~1"=="" (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  ) else (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%~1' -Verb RunAs"
  )
  if errorlevel 1 ( echo Could not ask Windows for permission. & pause )
  timeout /t 4 >nul
  exit /b
)
set "PYEXE="
for /f "usebackq delims=" %%P in (`%PYCMD% -c "import sys;print(sys.executable)"`) do set "PYEXE=%%P"
if /i "%~1"=="remove" goto :remove
if not defined PYEXE (
  echo Could not find the Python program. Nothing was changed.
  pause
  exit /b 1
)
echo.
echo About to add this Windows Firewall rule:
echo   Name:     %RULE%
echo   Allows:   incoming UDP data
echo   Program:  %PYEXE%
echo   From:     computers on your own network only (local subnet)
echo.
choice /c YN /m "Add the rule"
if errorlevel 2 (
  echo Nothing was changed.
  pause
  exit /b
)
netsh advfirewall firewall delete rule name="%RULE%" >nul 2>&1
netsh advfirewall firewall add rule name="%RULE%" dir=in action=allow protocol=UDP program="%PYEXE%" profile=any remoteip=localsubnet
if errorlevel 1 ( echo The rule could not be added. ) else ( echo. & echo Done. Now restart RF Noise Map and use the ANAN in a slot. )
pause
exit /b

:remove
echo Removing the rule "%RULE%" ...
netsh advfirewall firewall delete rule name="%RULE%"
pause
exit /b
