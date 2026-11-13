@echo off
title RF Noise Map - make a support file
cd /d "%~dp0"
REM ======================================================================
REM  Make_Support_File.bat
REM  Packs the install log, the problem log, your settings (without the
REM  private key) and a list of your PC's details into ONE zip file, so you
REM  can send it to Claude or a helper. Nothing is changed or uploaded.
REM ======================================================================
set "PYCMD=@@PYCMD@@"
echo Making the support file...
%PYCMD% "%~dp0app\rfmap_log.py" --bundle
if errorlevel 1 (
  echo.
  echo The program could not make it, so the plain log folder is zipped instead.
  powershell -NoProfile -Command "$z=Join-Path $env:USERPROFILE ('RFNoise_support_'+(Get-Date -Format yyyyMMdd_HHmmss)+'.zip'); Compress-Archive -Path '%~dp0Logs\*','%~dp0install_log.txt' -DestinationPath $z -Force; Write-Host ('Saved: '+$z)"
)
echo.
echo Send that zip file to Claude (attach it to your message).
pause
