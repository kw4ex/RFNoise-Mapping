@echo off
REM Opens the folder with the install logs and the problem log (program_errors.log).
if not exist "%~dp0..\Logs" mkdir "%~dp0..\Logs"
start "" explorer "%~dp0..\Logs"
REM %PYCMD% is not needed here; the line below is only so the installer can fill in the same setting for every file
set "PYCMD=@@PYCMD@@"
