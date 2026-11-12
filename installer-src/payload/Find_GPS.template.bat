@echo off
title RF Noise Map - find my GPS
REM ======================================================================
REM  Find_GPS.bat  -  finds a USB GPS puck and its speed by itself
REM ======================================================================
REM  Plug the puck in first. It tries the likely COM ports at the common speeds
REM  (4800, 9600, 38400, 115200) and, when it finds the puck, saves the port and
REM  speed so RF Noise Map is already set up for it.
REM
set "PYCMD=@@PYCMD@@"
REM
cd /d "%~dp0"
%PYCMD% -u "%~dp0app\gps_detect.py" --save %*
echo.
pause
