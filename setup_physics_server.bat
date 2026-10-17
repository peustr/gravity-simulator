@echo off
setlocal
title Gravity Simulator - physics server setup
cd /d "%~dp0physics_server"

echo.
echo  ============================================================
echo   Gravity Simulator - one-time setup of the physics server
echo  ============================================================
echo.

rem --- 1. Find Python 3 ------------------------------------------------------
rem Prefer versions that REBOUND has ready-made Windows packages for.
set "PY="
where py >nul 2>nul
if not errorlevel 1 (
    for %%V in (3.13 3.12 3.14 3.11 3.10) do (
        if not defined PY (
            py -%%V -c "import sys" >nul 2>nul && set "PY=py -%%V"
        )
    )
    if not defined PY (
        py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
    )
)
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY goto :nopython

%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 goto :badpython
%PY% -c "import sys; sys.exit(1 if sys.version_info >= (3, 15) else 0)" >nul 2>nul
if errorlevel 1 (
    echo  NOTE: this Python is newer than the newest version REBOUND has
    echo  ready-made Windows packages for ^(3.14^). If the install below fails,
    echo  install Python 3.13 as well and run this file again - see README.md.
    echo.
)
for /f "delims=" %%v in ('%PY% -c "import sys; print(sys.version.split()[0])"') do set "PYVER=%%v"
echo  [1/4] Found Python %PYVER%

rem --- 2. Create a private virtual environment ------------------------------
if exist ".venv\Scripts\python.exe" (
    echo  [2/4] Virtual environment already exists in physics_server\.venv
) else (
    echo  [2/4] Creating a virtual environment in physics_server\.venv ...
    %PY% -m venv .venv
    if errorlevel 1 goto :venvfail
)

rem --- 3. Install REBOUND and NumPy ------------------------------------------
echo  [3/4] Installing REBOUND and NumPy (this can take a minute) ...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :pipfail

rem --- 4. Self-test ---------------------------------------------------------
echo.
echo  [4/4] Running the physics self-test ...
echo.
".venv\Scripts\python.exe" server.py --selftest
if errorlevel 1 goto :testfail

echo.
echo  ============================================================
echo   All set!  Next: open the "godot" folder in Godot and press
echo   Play (F5). Godot starts the physics server automatically.
echo  ============================================================
echo.
pause
exit /b 0

:nopython
echo  Python 3 was not found on this computer.
echo.
echo  Install it from https://www.python.org/downloads/windows/
echo  and on the first installer screen tick "Add python.exe to PATH".
echo  Then run this file again.
echo.
pause
exit /b 1

:badpython
echo  Python was found but did not run, or it is older than 3.10.
echo.
echo  If a Microsoft Store window opened, close it and install Python from
echo  https://www.python.org/downloads/windows/ instead (tick "Add python.exe
echo  to PATH"). You can also turn off the Store shortcut in Windows Settings
echo  ^> Apps ^> Advanced app settings ^> App execution aliases.
echo.
pause
exit /b 1

:venvfail
echo  Could not create the virtual environment. See README.md, "Troubleshooting".
pause
exit /b 1

:pipfail
echo.
echo  Installing the packages failed. The two usual causes:
echo    - no internet connection (or a company proxy blocking pip), or
echo    - a very new Python with no ready-made REBOUND package yet. Install
echo      Python 3.13 from python.org, delete the physics_server\.venv folder,
echo      and run this file again.
echo  See README.md, "Troubleshooting", for more help.
pause
exit /b 1

:testfail
echo.
echo  The self-test reported a problem (see the FAIL lines above).
echo  The simulator may still work - see README.md, "Troubleshooting".
pause
exit /b 1
