@echo off
setlocal EnableExtensions
title RFI Trail - Windows installer
rem ============================================================================
rem  RFI Trail - Windows installer.  Double-click it.  Safe to run again (it updates).
rem  It tells you what it is about to do before each step.  No administrator password needed.
rem ============================================================================
cd /d "%~dp0"
set "HERE=%~dp0"
set "SRC=%HERE%app"
if not exist "%SRC%\nt_app.py" set "SRC=%HERE%..\app"
set "VER=__VER__"

cls
echo ============================================================
echo    NOISE TRAIL  -  installer for Windows   (version %VER%)
echo ============================================================
echo.
if not exist "%SRC%\nt_app.py" goto :nosrc
echo This will:
echo   1. Ask which folder to use (the usual answer is C:\RadioScripts)
echo   2. Copy the program into a folder called RFI_Trail inside it
echo   3. Find Python, or offer to install it (your own account only)
echo   4. Set up a private Python for the program and add two small helper libraries
echo      (numpy and pyserial; the internet is needed for this step)
echo   5. Make Start, Stop and Uninstall files, and a Desktop shortcut
echo   6. Run a quick self-test
echo   7. Keep a copy of this download in a KW4EX_Downloads folder next to RFI_Trail
echo.
echo Your drives, maps and settings are never touched when you update.
echo Nothing is sent anywhere. Everything is written to a log file.
echo.
set /p "GO=Ready to start? [Y/n] "
if /i "%GO%"=="n" exit /b 0

rem ---- 1. folder ---------------------------------------------------------------
echo.
echo ------------------------------------------------------------
echo STEP 1 - the folder
echo I am about to ask where to put RFI Trail.
set "BASE=C:\RadioScripts"
set /p "BASE=Press Enter to use C:\RadioScripts, or type another folder: "
if "%BASE%"=="" set "BASE=C:\RadioScripts"
set "DEST=%BASE%\RFI_Trail"
if not exist "%BASE%" mkdir "%BASE%" 2>nul
if not exist "%DEST%" mkdir "%DEST%" 2>nul
if not exist "%DEST%" goto :nofolder
if not exist "%DEST%\Logs" mkdir "%DEST%\Logs"
set "LOG=%DEST%\Logs\install_log.txt"
>"%LOG%" echo RFI Trail %VER% installer - %date% %time%
>>"%LOG%" echo Installing into %DEST%
echo Using the folder %DEST%

rem ---- 2. copy the program ------------------------------------------------------
echo.
echo ------------------------------------------------------------
echo STEP 2 - copy the program
echo I am about to copy the program files into %DEST%\app
if exist "%DEST%\app\nt_app.py" (
  echo An older copy is there. I keep it as app_previous in case you want to go back.
  if exist "%DEST%\app_previous" rmdir /s /q "%DEST%\app_previous"
  move "%DEST%\app" "%DEST%\app_previous" >> "%LOG%" 2>&1
)
robocopy "%SRC%" "%DEST%\app" /E /XD __pycache__ /NFL /NDL /NJH /NJS /NP >> "%LOG%" 2>&1
if errorlevel 8 goto :copyfail
if exist "%HERE%LICENSE" copy /y "%HERE%LICENSE" "%DEST%\LICENSE.txt" >nul
if exist "%HERE%README_Windows.txt" copy /y "%HERE%README_Windows.txt" "%DEST%\README_RFI_Trail.txt" >nul
if exist "%HERE%RFI_Trail_User_Guide.pdf" copy /y "%HERE%RFI_Trail_User_Guide.pdf" "%DEST%\RFI_Trail_User_Guide.pdf" >nul
if exist "%HERE%RFI_Trail_Help.html" copy /y "%HERE%RFI_Trail_Help.html" "%DEST%\RFI_Trail_Help.html" >nul
for %%d in (Drives Maps Exports Backups Settings Recordings Logs) do if not exist "%DEST%\%%d" mkdir "%DEST%\%%d"
>"%DEST%\rfitrail_install.flag" echo RFI Trail install folder
echo Program copied.

rem ---- 3. Python ------------------------------------------------------------------
echo.
echo ------------------------------------------------------------
echo STEP 3 - Python
echo I am about to look for Python 3 on this computer.
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info[:2]>=(3,8) else 1)" >nul 2>&1 && set "PY=py -3"
if not defined PY python -c "import sys; sys.exit(0 if sys.version_info[:2]>=(3,8) else 1)" >nul 2>&1 && set "PY=python"
if defined PY goto :havepy
echo Python 3.8 or newer was not found.
echo I can install Python 3.12 for you with Windows' own installer tool (winget). It needs the internet and no password.
set /p "PYGO=Install Python now? [Y/n] "
if /i "%PYGO%"=="n" goto :nopy
winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements >> "%LOG%" 2>&1
set "PYX=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if exist "%PYX%" set PY="%PYX%"
if not defined PY py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
if not defined PY goto :nopy
:havepy
echo Found Python: %PY%
>>"%LOG%" echo Python: %PY%

rem ---- 4. private Python + helper libraries ---------------------------------------
echo.
echo ------------------------------------------------------------
echo STEP 4 - the program's private Python
echo I am about to create it in %DEST%\venv and download numpy and pyserial. This takes a minute or two.
if not exist "%DEST%\venv\Scripts\python.exe" %PY% -m venv "%DEST%\venv" >> "%LOG%" 2>&1
if not exist "%DEST%\venv\Scripts\python.exe" goto :venvfail
"%DEST%\venv\Scripts\python.exe" -m pip install --upgrade pip numpy pyserial >> "%LOG%" 2>&1
if errorlevel 1 goto :pipfail
"%DEST%\venv\Scripts\python.exe" -c "import numpy, serial; print('numpy', numpy.__version__)"
if errorlevel 1 goto :pipfail

rem ---- 5. launch files and shortcut -------------------------------------------------
echo.
echo ------------------------------------------------------------
echo STEP 5 - Start, Stop and Uninstall files, and the Desktop shortcut
> "%DEST%\Start_RFI_Trail.bat" echo @echo off
>> "%DEST%\Start_RFI_Trail.bat" echo cd /d "%%~dp0"
>> "%DEST%\Start_RFI_Trail.bat" echo start "" "venv\Scripts\pythonw.exe" "app\nt_app.py"
> "%DEST%\Stop_RFI_Trail.bat" echo @echo off
>> "%DEST%\Stop_RFI_Trail.bat" echo cd /d "%%~dp0"
>> "%DEST%\Stop_RFI_Trail.bat" echo "venv\Scripts\python.exe" "app\nt_app.py" --stop
>> "%DEST%\Stop_RFI_Trail.bat" echo pause
if not exist "%DEST%\Tools" mkdir "%DEST%\Tools"
if exist "%HERE%Allow_ANAN_Firewall.bat" copy /y "%HERE%Allow_ANAN_Firewall.bat" "%DEST%\Tools\Allow_ANAN_Firewall.bat" >nul
if exist "%HERE%Uninstall_RFI_Trail_Windows.bat" copy /y "%HERE%Uninstall_RFI_Trail_Windows.bat" "%DEST%\Uninstall_RFI_Trail.bat" >nul
set /p "SC=Put an RFI Trail icon on your Desktop? [Y/n] "
if /i "%SC%"=="n" goto :noshortcut
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\RFI Trail.lnk'); $s.TargetPath='%DEST%\Start_RFI_Trail.bat'; $s.WorkingDirectory='%DEST%'; $s.IconLocation='%DEST%\app\icon.ico'; $s.WindowStyle=7; $s.Save()" >> "%LOG%" 2>&1
echo Desktop shortcut made.
:noshortcut

rem ---- 6. self-test -------------------------------------------------------------------
echo.
echo ------------------------------------------------------------
echo STEP 6 - self-test
echo I am about to check that the program loads (nothing is recorded).
"%DEST%\venv\Scripts\python.exe" -c "import sys; sys.path.insert(0, r'%DEST%\app'); import nt_common, make_map; print('RFI Trail', nt_common.VERSION, 'loads fine')"
if errorlevel 1 goto :testfail

rem ---- 6b. firewall for network radios ------------------------------------------------
echo.
echo ------------------------------------------------------------
echo Network radios (ANAN, Hermes Lite 2, FlexRadio) need Windows to let their data through.
echo I am about to open the small firewall helper. Windows will ask permission: answer Yes.
set /p "FW=Allow the radio data through the firewall now? [Y/n] "
if /i "%FW%"=="n" goto :fwdone
if exist "%DEST%\Tools\Allow_ANAN_Firewall.bat" start "" "%DEST%\Tools\Allow_ANAN_Firewall.bat"
:fwdone

rem ---- 6c. bring data over from the earlier test version ("Noise Trail") ----------------------
if not exist "%BASE%\NoiseTrail\noisetrail_install.flag" goto :nodata
if exist "%DEST%\Drives\*.csv" goto :nodata
echo.
echo ------------------------------------------------------------
echo I found the earlier test version (Noise Trail) in %BASE%\NoiseTrail.
echo I am about to COPY its drives, maps and settings into %DEST% (the old folder is left alone).
set /p "MV=Copy them now? [Y/n] "
if /i "%MV%"=="n" goto :nodata
for %%D in (Drives Maps Exports Recordings Settings Backups) do if exist "%BASE%\NoiseTrail\%%D" robocopy "%BASE%\NoiseTrail\%%D" "%DEST%\%%D" /E /NFL /NDL /NJH /NJS /NP >nul
echo Copied your data. You can remove the old Noise Trail with its own Uninstall file when you like.
:nodata

rem ---- 7. keep a copy of this download ------------------------------------------------
echo.
echo ------------------------------------------------------------
echo STEP 7 - keep a copy of this download
set "KEEP=%BASE%\KW4EX_Downloads\RFI_Trail_Windows_v%VER%"
echo I am about to copy this download folder to %KEEP%
echo so you always have the installer for this version (a few seconds).
if /i "%HERE%"=="%KEEP%\" goto :keepdone
robocopy "%HERE%." "%KEEP%" /E /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto :keepfail
echo Saved: %KEEP%
goto :keepdone
:keepfail
echo Could not copy the download. That is only a spare copy, and RFI Trail is installed fine.
:keepdone

echo.
echo ============================================================
echo  DONE.  RFI Trail %VER% is installed in %DEST%
echo ============================================================
echo  To start it: double-click the Desktop icon, or Start_RFI_Trail.bat in that folder.
echo  It opens in your web browser (Google Chrome is best for sound).
echo  First try: press Settings, then "Try a practice drive + map". No radio needed.
echo  The guide is in that folder too: RFI_Trail_User_Guide.pdf (to print) and RFI_Trail_Help.html.
echo  Real radios: see README_RFI_Trail.txt in that folder. Hermes Lite 2, ANAN and FlexRadio
echo  need no driver (run Tools\Allow_ANAN_Firewall.bat once); SDRplay needs extra setup.
echo  The install log is %LOG%
echo.
set /p "ST=Start RFI Trail now? [Y/n] "
if /i not "%ST%"=="n" start "" "%DEST%\Start_RFI_Trail.bat"
exit /b 0

:nosrc
echo I can't find the "app" folder next to this file.
echo Unzip the whole download first, and keep this file together with the "app" folder.
goto :stop
:nofolder
echo I could not create %DEST%. Choose another folder (for example C:\Users\YourName\RFI_Trail) and run this again.
goto :stop
:copyfail
echo Copying the program failed. See %LOG%
goto :stop
:nopy
echo Python could not be found or installed. Install Python 3.12 from https://www.python.org/downloads/windows/
echo (tick "Add python.exe to PATH"), then run this installer again.
goto :stop
:venvfail
echo I could not make the program's private Python. See %LOG%
goto :stop
:pipfail
echo The helper libraries (numpy, pyserial) did not install. Is the internet connected? Turn off any VPN for a few minutes and run this again. See %LOG%
goto :stop
:testfail
echo The self-test failed. See %LOG% and send it to KW4EX.
:stop
echo.
pause
exit /b 1
