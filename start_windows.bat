@echo off
title SportsArbFinder Pro
cd /d %~dp0

echo ============================================
echo   SportsArbFinder Pro - Windows Launcher
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python is not installed or not on your PATH.
    echo.
    echo   Go to https://www.python.org/downloads/ and download Python.
    echo   IMPORTANT: tick the box "Add Python to PATH" during install,
    echo   then close this window and double-click this file again.
    echo.
    pause
    exit /b 1
)

echo [1/2] Installing required packages (first run only)...
pip install -r requirements.txt

echo.
echo [2/2] Starting the dashboard...
echo   Open your browser at  http://localhost:8000
echo   Close this window to stop the app.
echo.
python app.py
pause
