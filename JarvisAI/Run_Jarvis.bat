@echo off
setlocal EnableExtensions
title Jarvis AI Pro Launcher
cd /d "%~dp0"

echo.
echo  ======================================
echo          JARVIS AI PRO LAUNCHER
echo  ======================================
echo.

REM Keep this file in JarvisAI, beside main.py, setup.py and requirements.txt.
for %%F in (main.py setup.py requirements.txt) do (
    if not exist "%%F" (
        echo [ERROR] Required project file %%F was not found.
        echo Make sure this BAT file is inside the JarvisAI project folder.
        echo.
        pause
        exit /b 1
    )
)

REM The project is tested on Python 3.11-3.13; use Python 3.12 on Windows.
set "PY_LAUNCHER="
for /f "delims=" %%P in ('where py 2^>nul') do if not defined PY_LAUNCHER set "PY_LAUNCHER=%%P"

if defined PY_LAUNCHER (
    "%PY_LAUNCHER%" -3.12 --version >nul 2>&1
    if not errorlevel 1 goto :python_ready
)

echo [INFO] Python 3.12 was not found. Checking Windows Package Manager...
where winget >nul 2>&1
if errorlevel 1 goto :python_manual

echo.
echo [1/4] Installing Python 3.12 for this Windows user...
winget install --id Python.Python.3.12 --exact --scope user --silent --accept-package-agreements --accept-source-agreements
REM Verify the interpreter instead of trusting winget's exit code.
set "PY_LAUNCHER="
for /f "delims=" %%P in ('where py 2^>nul') do if not defined PY_LAUNCHER set "PY_LAUNCHER=%%P"
if defined PY_LAUNCHER (
    "%PY_LAUNCHER%" -3.12 --version >nul 2>&1
    if not errorlevel 1 goto :python_ready
)

if exist "%LocalAppData%\Programs\Python\Launcher\py.exe" (
    "%LocalAppData%\Programs\Python\Launcher\py.exe" -3.12 --version >nul 2>&1
    if not errorlevel 1 (
        set "PY_LAUNCHER=%LocalAppData%\Programs\Python\Launcher\py.exe"
        goto :python_ready
    )
)

if exist "%LocalAppData%\Programs\Python\Python312\python.exe" (
    "%LocalAppData%\Programs\Python\Python312\python.exe" --version >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python312\python.exe"
        goto :python_ready_direct
    )
)

goto :python_manual

:python_ready
set PYTHON_COMMAND="%PY_LAUNCHER%" -3.12
goto :python_verified

:python_ready_direct
set PYTHON_COMMAND="%PYTHON_EXE%"

:python_verified
echo [OK] Supported Python interpreter found.

REM Create a project-local environment; do not modify system Python packages.
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo [2/4] Creating the isolated Jarvis environment...
    %PYTHON_COMMAND% -m venv .venv
    if errorlevel 1 goto :failed
)

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment creation did not produce its Python executable.
    goto :failed
)

REM Re-run setup when setup.py or requirements.txt changes.
set "CURRENT_SETUP_HASH="
for /f "usebackq delims=" %%H in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$r=(Get-FileHash -Algorithm SHA256 -LiteralPath 'requirements.txt').Hash; $s=(Get-FileHash -Algorithm SHA256 -LiteralPath 'setup.py').Hash; [Console]::Write($r + $s)"`) do set "CURRENT_SETUP_HASH=%%H"

if not defined CURRENT_SETUP_HASH (
    echo [ERROR] Could not check setup file hashes. Make sure Windows PowerShell is available.
    goto :failed
)

set "SAVED_SETUP_HASH="
if exist ".jarvis_setup_hash" set /p "SAVED_SETUP_HASH="<".jarvis_setup_hash"

if not exist ".jarvis_setup_hash" goto :install_requirements
if not "%CURRENT_SETUP_HASH%"=="%SAVED_SETUP_HASH%" goto :install_requirements

REM Check the environment each run; repair it if pip detects missing/broken packages.
echo.
echo [3/4] Checking the installed Python environment...
".venv\Scripts\python.exe" -m pip --version
if errorlevel 1 goto :install_requirements
".venv\Scripts\python.exe" -m pip check
if errorlevel 1 goto :install_requirements
goto :launch_jarvis

:install_requirements
echo.
echo [3/4] Installing or repairing Jarvis dependencies and browser components.
echo An internet connection is required. This may take several minutes.
".venv\Scripts\python.exe" -m ensurepip --upgrade
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" setup.py
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" -m pip check
if errorlevel 1 goto :failed

REM Save the fingerprint only after setup and pip checks succeed.
>".jarvis_setup_hash" echo %CURRENT_SETUP_HASH%
if errorlevel 1 goto :failed

:launch_jarvis
echo.
echo [4/4] Starting Jarvis AI Pro...
echo Keep this window open while Jarvis is running.
echo.
".venv\Scripts\python.exe" main.py --hologram-hud
set "JARVIS_EXIT=%ERRORLEVEL%"

echo.
if not "%JARVIS_EXIT%"=="0" (
    echo [ERROR] Jarvis closed with error code %JARVIS_EXIT%.
    echo Review the messages above. A valid provider API key is needed for AI features.
) else (
    echo Jarvis has closed.
)
echo.
pause
exit /b %JARVIS_EXIT%

:python_manual
echo.
echo [ERROR] Could not find or install Python 3.12 automatically.
echo Install Python 3.12 from:
echo https://www.python.org/downloads/release/python-31210/
echo Enable the Python Launcher option if offered, then run this BAT again.
echo.
pause
exit /b 1

:failed
echo.
echo [ERROR] Jarvis setup or environment verification failed.
echo Read the error messages above, check your internet connection, and run this BAT again.
echo The setup marker was not updated, so setup will be retried.
echo.
pause
exit /b 1
