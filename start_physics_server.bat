@echo off
setlocal
title Gravity Simulator - physics server
cd /d "%~dp0physics_server"

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo  The physics server is not set up yet.
    echo  Please double-click setup_physics_server.bat first.
    echo.
    pause
    exit /b 1
)

echo.
echo  Gravity Simulator physics server - keep this window open while you play.
echo  Close it (or press Ctrl+C) to stop the server.
echo.
".venv\Scripts\python.exe" server.py %*
echo.
pause
