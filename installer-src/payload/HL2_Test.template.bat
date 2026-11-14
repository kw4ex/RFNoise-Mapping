@echo off
title RF Noise Map - Hermes Lite 2 test
REM ======================================================================
REM  HL2_Test.bat  -  checks the Hermes Lite 2 radio: is it found on the network, does it
REM  stream cleanly, do the four receivers agree, does the gain work, is anything overloaded.
REM  Needs the real radio on the network cable. Close Thetis / SDR Console and RF Noise Map first.
REM  Takes about 40 seconds. Nothing is changed. Report: hl2_test_report.txt
REM ======================================================================
set "PYCMD=@@PYCMD@@"
cd /d "%~dp0"
echo.
%PYCMD% -u "%~dp0app\diag_hl2.py" --report "%~dp0hl2_test_report.txt"
echo.
echo The report is saved in: %~dp0hl2_test_report.txt
pause
