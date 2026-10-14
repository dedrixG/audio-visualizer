@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo Audio Visualizer
echo Installing into this folder only:
echo   %~dp0
echo.
if not exist "%~dp0AudioVisualizer.exe" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\setup-python.ps1" -Root "%~dp0."
  if errorlevel 1 (
    echo.
    echo Setup stopped. This folder was not registered.
    pause
    exit /b 1
  )
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\shortcuts.ps1" -Root "%~dp0." -Action Install
if errorlevel 1 (
  echo Could not create the shortcuts.
  pause
  exit /b 1
)
echo.
echo Installed. Everything stays in this folder.
echo Start Menu and Desktop shortcuts open start.bat here.
echo Remove them later with uninstall.bat in this same folder.
echo.
pause
exit /b 0
