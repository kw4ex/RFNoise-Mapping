@echo off
title RF Noise Map
REM ======================================================================
REM  Start_RFNoise.bat  -  starts RF Noise Map
REM ======================================================================
REM
REM  WHAT THIS FILE DOES
REM    1. Starts the RF Noise Map program in this window.
REM    2. Opens the control panel in your web browser (http://localhost:8780).
REM    3. If it is already running, it just opens the panel again.
REM
REM  Keep this window open while you work: closing it stops the program (and
REM  any logging in progress). To finish normally, press "Quit RF Noise Map"
REM  in the panel, or double-click Stop_RFNoise.bat.
REM
REM  Put this file in the same folder as the "app" folder (normally
REM  C:\RadioScripts\RFNoise). Your drives, maps and settings are kept in the
REM  folders Drives, Maps, Exports, Backups and Settings next to it.
REM
REM  SETTINGS - the Python command the installer found on this PC
set "PYCMD=@@PYCMD@@"
REM
cd /d "%~dp0"
echo Starting RF Noise Map...
%PYCMD% -u "%~dp0app\rfmap_app.py" %*
if errorlevel 1 (
  echo.
  echo RF Noise Map stopped with an error - please read the messages above.
  echo If you need help, send the file install_log.txt and a copy of these messages to Claude.
  pause
)
