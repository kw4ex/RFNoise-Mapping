@echo off
REM Opens the RF Noise Map panel of the program that is already running.
REM If it is not running yet, it is started for you.
curl -s -m 2 http://127.0.0.1:8780/api/ping >nul 2>&1
if errorlevel 1 (
  start "" "%~dp0Start_RFNoise.bat"
) else (
  start "" "http://localhost:8780/"
)
