@echo off
rem TG Sales CRM - one-time setup for running from the source code (developers and testers).
rem Release ZIPs already contain everything; salespeople only need launch.bat.
rem Needs: Python 3.13 (python.org) and Node.js 22+ (nodejs.org). Internet access for downloads.
setlocal
cd /d "%~dp0"

where py >nul 2>nul && (set "PYLAUNCH=py -3.13") || (set "PYLAUNCH=python")
%PYLAUNCH% --version >nul 2>nul
if errorlevel 1 (
    echo Python 3.13 was not found. Install it from https://www.python.org/downloads/ and run setup.bat again.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating the Python environment...
    %PYLAUNCH% -m venv .venv || goto :failed
)
echo Installing Python packages...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install --require-hashes -r requirements.lock || goto :failed
".venv\Scripts\python.exe" -m pip install --no-deps -e . || goto :failed

echo Setting up the database runtime...
".venv\Scripts\python.exe" scripts\setup_postgres.py || goto :failed

where npm >nul 2>nul
if errorlevel 1 (
    echo Node.js was not found, so the web app cannot be built. Install Node.js 22+ from https://nodejs.org and run setup.bat again.
    pause
    exit /b 1
)
echo Building the web app...
pushd web
call npm ci --no-fund --no-audit || (popd & goto :failed)
call npm run build || (popd & goto :failed)
popd

echo.
echo Setup complete. Start TG Sales CRM with launch.bat.
pause
exit /b 0

:failed
echo.
echo Setup did not finish. Read the messages above, fix the problem, and run setup.bat again.
pause
exit /b 1
