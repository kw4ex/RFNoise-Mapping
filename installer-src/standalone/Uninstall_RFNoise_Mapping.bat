@echo off
setlocal
title Uninstall RF Noise Map
REM ======================================================================
REM  Uninstall_RFNoise_Mapping.bat  -  removes RF Noise Map
REM  This copy lives in the download folder. It finds where RF Noise Map is
REM  installed (Windows remembers it) and starts the uninstaller kept there.
REM  You then choose what happens to your drives and maps.
REM  Extra words are passed on:  /silent   /mode=1   /mode=2   /mode=3
REM ======================================================================
set "RFN_DIR="
for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "try{(Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\RFNoiseMap' -ErrorAction Stop).InstallLocation}catch{}"`) do set "RFN_DIR=%%D"
if defined RFN_DIR if not exist "%RFN_DIR%\Uninstall_RFNoise.bat" set "RFN_DIR="
if not defined RFN_DIR if exist "C:\RadioScripts\RFNoise_Mapping\Uninstall_RFNoise.bat" set "RFN_DIR=C:\RadioScripts\RFNoise_Mapping"
if not defined RFN_DIR if exist "C:\RadioScripts\RFNoise\Uninstall_RFNoise.bat" set "RFN_DIR=C:\RadioScripts\RFNoise"
if not defined RFN_DIR (
  echo RF Noise Map was not found on this PC, so there is nothing to remove.
  echo If it is in a folder of your own, open that folder and double-click
  echo Uninstall_RFNoise.bat there.
  pause
  exit /b 1
)
echo Found RF Noise Map in: %RFN_DIR%
echo.
call "%RFN_DIR%\Uninstall_RFNoise.bat" %*
exit /b
