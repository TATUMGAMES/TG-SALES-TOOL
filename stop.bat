@echo off
rem TG Sales CRM - stop the app and its database.
setlocal
cd /d "%~dp0"
if exist "%~dp0tg_sales.exe" (
    "%~dp0tg_sales.exe" stop %*
) else if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" -m tg_sales.launcher stop %*
) else (
    echo TG Sales CRM is not set up on this computer.
)
"%SystemRoot%\System32\timeout.exe" /t 3 >nul 2>nul
endlocal
