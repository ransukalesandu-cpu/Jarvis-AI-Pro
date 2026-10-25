@echo off
setlocal
title Jarvis AI Pro Launcher
cd /d "%~dp0"

echo.
echo  ======================================
echo          JARVIS AI PRO LAUNCHER
echo  ======================================
echo.

REM This launcher belongs in the JarvisAI folder beside main.py.
if not exist "main.py" (
    echo [ERROR] main.py was not found.
    echo Place this file inside the JarvisAI folder beside main.py.
    echo.
    pause
    exit /b 1
)

REM The project currently targets Python 3.12.
py -3.12 --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 3.12 was not found.
    echo Install Python 3.12 from:
    echo https://www.python.org/downloads/release/python-31210/
    echo Then run this launcher again.
    echo.
    pause
    exit /b 1
)

REM Create the virtual environment only once.
if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Creating the Jarvis virtual environment...
    py -3.12 -m venv .venv
    if errorlevel 1 goto :failed
)

REM Install project dependencies on the first launch. If setup fails, try again next time.
if not exist ".jarvis_setup_complete" (
    echo.
    echo [2/3] Installing Jarvis dependencies. This can take several minutes...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    if errorlevel 1 goto :failed
    ".venv\Scripts\python.exe" setup.py
    if errorlevel 1 goto :failed
    >".jarvis_setup_complete" echo setup completed
)

echo.
echo [3/3] Starting Jarvis AI Pro...
echo Keep this window open while Jarvis is running.
echo.
".venv\Scripts\python.exe" main.py
set "JARVIS_EXIT=%ERRORLEVEL%"

echo.
if not "%JARVIS_EXIT%"=="0" (
    echo Jarvis closed with error code %JARVIS_EXIT%.
    echo Take a screenshot of the error messages above if you need help.
) else (
    echo Jarvis has closed.
)
echo.
pause
exit /b %JARVIS_EXIT%

:failed
echo.
echo [ERROR] Setup failed. Fix the issue shown above and run this file again.
echo.
pause
exit /b 1
