@echo off
REM Closes a running RF Noise Map (and stops any logging in progress).
set "PYCMD=@@PYCMD@@"
cd /d "%~dp0"
%PYCMD% "%~dp0app\rfmap_app.py" --stop
timeout /t 3 >nul
