@echo off
setlocal EnableExtensions
title Jarvis AI Pro Launcher
cd /d "%~dp0"

echo.
echo  ======================================
echo          JARVIS AI PRO LAUNCHER
echo  ======================================
echo.

REM Keep this file inside JarvisAI, beside main.py, setup.py and requirements.txt.
for %%F in (main.py setup.py requirements.txt) do (
    if not exist "%%F" (
        echo [ERROR] Required project file %%F was not found.
        echo Extract the ZIP fully and run this BAT from the JarvisAI folder.
        echo.
        pause
        exit /b 1
    )
)

REM Use Python 3.12, which is tested for this Windows project.
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
set "PYTHON_EXE=%PY_LAUNCHER%"
set "PYTHON_ARGS=-3.12"
goto :python_verified

:python_ready_direct
set "PYTHON_ARGS="

:python_verified
echo [OK] Supported Python interpreter found.

REM Recreate stale or incomplete environments instead of reusing an unsupported Python.
REM This prevents an old Python 3.15 venv from surviving after the launcher selects 3.12.
if exist ".venv" (
    if not exist ".venv\Scripts\python.exe" (
        echo [WARN] Existing virtual environment is incomplete; rebuilding it...
        rmdir /s /q ".venv"
    ) else (
        ".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>&1
        if errorlevel 1 (
            echo [WARN] Existing virtual environment is not Python 3.12; rebuilding it...
            rmdir /s /q ".venv"
        )
    )
)

REM Create an isolated environment so system Python packages are untouched.
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo [2/4] Creating the isolated Jarvis environment...
    "%PYTHON_EXE%" %PYTHON_ARGS% -m venv .venv
    if errorlevel 1 goto :failed
)
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment creation did not produce its Python executable.
    goto :failed
)

REM Ensure pip exists and is current before dependency repair.
echo.
echo [3/4] Installing or repairing ALL declared dependencies...
echo This check runs every launch so newly added or missing packages are repaired.
echo An internet connection is required; the first setup may take several minutes.
".venv\Scripts\python.exe" -m ensurepip --upgrade
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed

REM setup.py installs requirements.txt and attempts to install Playwright browsers.
".venv\Scripts\python.exe" setup.py
if errorlevel 1 goto :failed

echo.
echo [VERIFY] Checking installed package consistency...
".venv\Scripts\python.exe" -m pip check
if errorlevel 1 (
    echo [ERROR] Package conflicts or missing dependencies were detected.
    echo The setup did not pass verification. Check the error above and run this BAT again.
    goto :failed
)

echo.
echo [4/4] Starting Jarvis AI Pro...
echo Keep this window open while Jarvis is running.
echo.
REM Explicitly request the hologram HUD so the launcher uses the upgraded interface.
".venv\Scripts\python.exe" main.py --hologram-hud
set "JARVIS_EXIT=%ERRORLEVEL%"

echo.
if not "%JARVIS_EXIT%"=="0" (
    echo [ERROR] Jarvis closed with error code %JARVIS_EXIT%.
    echo Review the messages above. A valid Gemini API key is required for Live voice.
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
echo [ERROR] Jarvis setup or dependency verification failed.
echo Check your internet connection and the first error shown above, then run this BAT again.
echo The app was not launched because setup did not pass.
echo.
pause
exit /b 1
