@echo off
title RF Noise Map - ANAN read test (receive only)
REM ======================================================================
REM  ANAN_Read_Test.bat  -  starts ONE receiver of an ANAN for a few seconds and reports what it hears
REM ======================================================================
REM  RECEIVE ONLY: it never keys the transmitter (PTT off, drive zero, amplifier off) and it
REM  tells the radio to stop when it finishes. CLOSE Thetis (or any other program using the radio) first.
REM
REM  Usage:   ANAN_Read_Test.bat                      finds the radio and tunes 10.000 MHz
REM           ANAN_Read_Test.bat 7.2                   tunes 7.2 MHz
REM           ANAN_Read_Test.bat 192.168.0.51 7.2      uses that radio address
REM  The report is saved in the Reports folder as anan_read_test.txt.
REM
set "PYCMD=@@PYCMD@@"
REM
cd /d "%~dp0.."
echo.
echo What this does: it starts one receiver for about 2 seconds, twice, and shows the signal level.
echo Close Thetis first. Nothing is transmitted.
echo.
%PYCMD% -u "%~dp0..\app\anan.py" %*
echo.
pause
