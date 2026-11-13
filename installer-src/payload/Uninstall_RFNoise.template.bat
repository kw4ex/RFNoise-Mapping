@echo off
setlocal
title Uninstall RF Noise Map
cd /d "%~dp0"
REM ======================================================================
REM  Uninstall_RFNoise.bat  -  removes RF Noise Map
REM  It copies its helper (Uninstall_RFNoise.ps1) to a temporary place first,
REM  so that the helper can safely delete this whole folder.
REM  Extra words are passed on:  /silent   /mode=1 (program only, default)
REM                              /mode=2 (program + data, backup first)  /mode=3 (everything)
REM ======================================================================
set "RFN_SILENT="
set "RFN_MODE="
for %%A in (%*) do (
  if /i "%%~A"=="/silent" set "RFN_SILENT=1"
  echo %%~A| findstr /b /i "/mode=" >nul && for /f "tokens=2 delims==" %%M in ("%%~A") do set "RFN_MODE=%%M"
)
set "HELPER=%TEMP%\rfnoise_uninstall_%RANDOM%.ps1"
if not exist "%~dp0Uninstall_RFNoise.ps1" (
  echo The file Uninstall_RFNoise.ps1 is missing from this folder.
  echo Download the newest Install_RFNoise_Windows.bat and run it again - it repairs the install.
  pause
  exit /b 1
)
copy /y "%~dp0Uninstall_RFNoise.ps1" "%HELPER%" >nul
if defined RFN_SILENT set "RFNOISE_UNINSTALL_SILENT=1"
powershell -NoProfile -ExecutionPolicy Bypass -File "%HELPER%" -Dir "%~dp0." -Mode "%RFN_MODE%"
del "%HELPER%" >nul 2>&1
if not defined RFN_SILENT pause
REM remove this file, the helper copy and the folder if nothing is left in it
if not exist "%~dp0app" (
  start "" /min cmd /c "timeout /t 2 >nul & del /q ""%~dp0Uninstall_RFNoise.ps1"" >nul 2>&1 & del /q ""%~f0"" & rmdir ""%~dp0."" 2>nul"
)
exit /b
