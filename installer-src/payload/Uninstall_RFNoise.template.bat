@echo off
setlocal EnableDelayedExpansion
title Uninstall RF Noise Map
cd /d "%~dp0"
echo ===========================================================
echo   Uninstall RF Noise Map
echo ===========================================================
echo.
echo This removes, one step at a time:
echo   1. the running program (it is closed for you)
echo   2. the shortcuts (Desktop and Windows startup)
echo   3. the program's own files in this folder
echo   4. your recorded data - ONLY if you say yes (the default is to keep it)
echo.
echo Python and numpy/pyserial are NOT removed (other programs may use them).
echo The SDRplay driver and PothosSDR are not changed.
echo.
pause

echo.
echo --- Step 1: closing the program ---
set "PY=@@PYCMD@@"
if exist "app\rfmap_app.py" %PY% "app\rfmap_app.py" --stop >nul 2>&1
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { ($_.CommandLine -like '*rfmap_app.py*' -or $_.CommandLine -like '*rf_logger.py*') -and $_.Name -match '^(python|pythonw|py|pyw)' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1
echo Done.

echo.
echo --- Step 2: shortcuts ---
powershell -NoProfile -Command "foreach($f in 'Desktop','Programs','Startup'){ $p=[Environment]::GetFolderPath($f); if($p){ Get-ChildItem -LiteralPath $p -Filter 'RF Noise Map*.lnk' -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue } }" >nul 2>&1
echo Shortcuts removed (Desktop, Start menu, Startup).

echo.
echo --- Step 3: the program's own files ---
echo This folder also holds your data (Drives, Maps, Exports, Backups, Settings).
echo Those are NOT touched in this step.
set /p DEL=Delete the program's own files (program, help, launchers, logs)? (y/N): 
if /i not "%DEL%"=="y" goto keep
for %%F in (Start_RFNoise.bat Stop_RFNoise.bat Open_Panel.bat README_RFNoise.txt RFNoise_Help.html RFNoise_User_Guide.pdf install_log.txt rfnoise_install.flag) do del "%~dp0%%F" 2>nul
del "%~dp0Start_RFNoise.bat.*.bak" 2>nul
rmdir /s /q "%~dp0app" 2>nul
rmdir /s /q "%~dp0app_previous" 2>nul

echo.
echo --- Step 4: your recorded data ---
set "HAVE=0"
for %%D in (Drives Maps Exports Backups Settings) do if exist "%~dp0%%D" set "HAVE=1"
if "%HAVE%"=="0" goto nodata
echo The folders Drives, Maps, Exports, Backups and Settings hold everything you recorded.
echo If you may want those drives or maps again, answer N.
set /p DELD=Delete ALL of your recorded data too? This cannot be undone. (y/N): 
if /i not "%DELD%"=="y" goto keepdata
for %%D in (Drives Maps Exports Backups Settings) do rmdir /s /q "%~dp0%%D" 2>nul
echo Your data was deleted.
goto nodata
:keepdata
echo Your data was kept in:  %~dp0
:nodata
echo.
echo The program files are deleted.
echo This uninstaller removes itself now (and the folder if it is empty).
pause
start "" cmd /c "timeout /t 2 >nul & del ""%~f0"" & rmdir ""%~dp0."" 2>nul"
exit /b
:keep
echo.
echo Files kept. You can delete them yourself later.
pause
