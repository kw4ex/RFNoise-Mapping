@echo off
title RF Noise Map - full test
REM ======================================================================
REM  Test_Everything.bat  -  checks the whole system automatically (about 1 minute)
REM ======================================================================
REM  WHAT THIS FILE DOES
REM    Tests Python and its libraries, the SDRplay radio (real readings on your
REM    frequencies), the USB GPS (it finds the port and speed by itself), and then
REM    runs a pretend drive with the real radio and builds a map from it.
REM    You do not have to click anything. The result is also saved in the file
REM    full_test_report.txt next to this file.
REM
REM  BEFORE YOU RUN IT
REM    - Plug in the radio (with antenna) and the GPS puck. Put the puck near a window.
REM    - Close RF Noise Map (Stop_RFNoise.bat) and any other SDR or GPS program.
REM    - If you use the iPhone GPS instead, run:  Test_Everything.bat --iphone
REM    - To wait for a GPS position (take the puck outside first):  Test_Everything.bat --gps-wait 120
REM
set "PYCMD=@@PYCMD@@"
REM
cd /d "%~dp0"
%PYCMD% "%~dp0app\device_guard.py"
echo.
%PYCMD% -u "%~dp0app\full_test.py" --report "%~dp0full_test_report.txt" %*
echo.
echo The report is saved in: %~dp0full_test_report.txt
pause
