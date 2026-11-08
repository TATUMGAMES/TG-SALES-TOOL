@echo off
rem TG Sales CRM - start the app on this computer and open it in your browser.
rem Keep this window open while you use tg_sales. Close it (or run stop.bat) to quit.
setlocal
cd /d "%~dp0"
title TG Sales CRM

if exist "%~dp0tg_sales.exe" (
    "%~dp0tg_sales.exe" start %*
    goto :done
)
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" -m tg_sales.launcher start %*
    goto :done
)
echo.
echo TG Sales CRM is not set up on this computer yet.
echo Run setup.bat first, then run launch.bat again.
echo.
pause
exit /b 1

:done
if errorlevel 1 (
    echo.
    echo TG Sales CRM could not start. Read the message above for what to do next.
    echo The log file is in %%LOCALAPPDATA%%\TatumGames\tg_sales\logs
    echo.
    pause
    exit /b 1
)
endlocal
