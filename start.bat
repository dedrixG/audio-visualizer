@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PORT=8765"
if exist "%~dp0AudioVisualizer.exe" (
  "%~dp0AudioVisualizer.exe" --port %PORT% --open
  exit /b %ERRORLEVEL%
)
if exist "%~dp0python\python.exe" (
  "%~dp0python\python.exe" "%~dp0server.py" --port %PORT% --open
  exit /b %ERRORLEVEL%
)
where py >nul 2>&1
if not errorlevel 1 (
  py -3 "%~dp0server.py" --port %PORT% --open
  exit /b %ERRORLEVEL%
)
where python >nul 2>&1
if not errorlevel 1 (
  python "%~dp0server.py" --port %PORT% --open
  exit /b %ERRORLEVEL%
)
echo No Audio Visualizer runtime in this folder.
echo Double-click install.bat first. It downloads Python into .\python.
pause
exit /b 1
