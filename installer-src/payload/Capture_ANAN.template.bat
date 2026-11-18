@echo off
title RF Noise Map - record how Thetis talks to the ANAN
REM ======================================================================
REM  Capture_ANAN.bat  -  records the network conversation between this PC and the ANAN
REM ======================================================================
REM  WHY: to copy exactly how Thetis starts the radio. It records ONLY packets to and from the
REM  radio's address, with Windows' own built-in tool (pktmon). Nothing is installed, nothing is sent,
REM  and the recording stays on this PC in the Reports folder until you send it.
REM  It needs administrator permission: Windows asks you once.
REM
set "RIP=192.168.0.51"
set "OUT=%~dp0..\Reports\anan_thetis_capture"
REM
net session >nul 2>&1
if errorlevel 1 (
  echo This needs administrator permission. Windows will ask you; choose Yes.
  echo If no question appears, close this window, right-click Capture_ANAN.bat and choose "Run as administrator".
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  if errorlevel 1 ( echo Could not ask Windows for permission. & pause )
  timeout /t 4 >nul
  exit /b
)
echo.
echo ANAN radio address: %RIP%
set /p RIP="Press Enter to use it, or type another address: " 
if "%RIP%"=="" set "RIP=192.168.0.51"
echo.
pktmon stop >nul 2>&1
pktmon filter remove >nul 2>&1
pktmon filter add ANAN -i %RIP%
if errorlevel 1 ( echo Could not set the recording filter. & pause & exit /b 1 )
echo.
echo Starting the recording...
pktmon start --capture --comp nics --pkt-size 0 --file-name "%OUT%.etl" --file-size 300
if errorlevel 1 ( echo Could not start the recording. & pause & exit /b 1 )
echo.
echo ================================================================
echo  RECORDING NOW. Do these steps, then come back to this window:
echo    1. Start Thetis.
echo    2. Press the POWER button in Thetis so the radio starts and you hear/see the receiver.
echo    3. Wait about 5 seconds. Tune to 10.000 MHz (or any frequency).
echo    4. Press the POWER button again to switch it OFF.
echo    5. Come back to this window.
echo ================================================================
echo.
pause
echo Stopping the recording...
pktmon stop
echo Converting it to a file I can read...
pktmon etl2pcap "%OUT%.etl" --out "%OUT%.pcapng"
pktmon filter remove >nul 2>&1
echo.
if exist "%OUT%.pcapng" ( echo Done. The recording is in the Reports folder: anan_thetis_capture.pcapng ) else ( echo The recording is in the Reports folder as anan_thetis_capture.etl but could not be converted. Tell Claude. )
pause
