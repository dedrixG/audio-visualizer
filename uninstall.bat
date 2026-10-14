@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "ROOT=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\shortcuts.ps1" -Root "%~dp0." -Action Uninstall
if errorlevel 1 (
  echo Could not remove the shortcuts.
  pause
  exit /b 1
)
echo Removed the Start Menu shortcut, the Desktop shortcut,
echo the Settings app entry, and the firewall rule.
echo.
echo This folder is still here:
echo   %ROOT%
choice /C YN /N /M "Delete this folder too? [Y/N] "
if errorlevel 2 goto done
cd /d "%TEMP%"
start "" cmd /c "ping -n 3 127.0.0.1 >nul & rmdir /s /q \"%ROOT%\""
echo The folder will be removed in a moment. You can close this window.
goto done
:done
pause
exit /b 0
