@echo off
setlocal EnableExtensions
title RFI Trail - uninstall
cd /d "%~dp0"
set "D=%~dp0"
if "%D:~-1%"=="\" set "D=%D:~0,-1%"
if not exist "%D%\rfitrail_install.flag" goto :wrongplace
echo ============================================================
echo    RFI TRAIL  -  uninstall
echo ============================================================
echo Folder: %D%
echo.
echo   1) Remove the program only  (your drives, maps, recordings and settings are KEPT)
echo   2) Remove everything, including my drives, maps and settings  (cannot be undone)
echo   3) Cancel
echo.
set /p "C=Type 1, 2 or 3 and press Enter [3]: "
if "%C%"=="1" goto :prog
if "%C%"=="2" goto :all
exit /b 0
:prog
"%D%\venv\Scripts\python.exe" "%D%\app\nt_app.py" --stop >nul 2>&1
rmdir /s /q "%D%\app" 2>nul
rmdir /s /q "%D%\app_previous" 2>nul
rmdir /s /q "%D%\venv" 2>nul
del /q "%D%\Start_RFI_Trail.bat" "%D%\Stop_RFI_Trail.bat" "%D%\rfitrail_install.flag" 2>nul
del /q "%USERPROFILE%\Desktop\RFI Trail.lnk" 2>nul
echo The program is removed. Your data is still in %D%
pause
(goto) 2>nul & del "%~f0"
:all
set /p "Y=Type YES (capital letters) to delete EVERYTHING in %D%: "
if not "%Y%"=="YES" exit /b 0
del /q "%USERPROFILE%\Desktop\RFI Trail.lnk" 2>nul
cd /d "%TEMP%"
rmdir /s /q "%D%"
echo Everything is removed.
pause
exit /b 0

:wrongplace
echo This file must be run from the RFI Trail folder, the one that has Start_RFI_Trail.bat in it.
pause
exit /b 1
