@echo off
title RF Noise Map - switching test
REM ======================================================================
REM  Switch_Test.bat  -  checks that the radio reads the right level right after it
REM  changes frequency (the program does this many times a second while driving).
REM  Needs the real radio. Close RF Noise Map and other SDR programs first.
REM  Takes about a minute. Nothing is changed. Report: switch_test_report.txt
REM ======================================================================
set "PYCMD=@@PYCMD@@"
cd /d "%~dp0"
%PYCMD% "%~dp0app\device_guard.py"
echo.
%PYCMD% -u "%~dp0app\diag_switch.py" --report "%~dp0switch_test_report.txt"
echo.
echo The report is saved in: %~dp0switch_test_report.txt
pause
