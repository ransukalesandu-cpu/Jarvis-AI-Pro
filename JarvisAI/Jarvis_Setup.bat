@echo off
setlocal EnableExtensions EnableDelayedExpansion
title JARVIS AI PRO - Setup
chcp 65001 >nul 2>&1

REM ---------------------------------------------------------------------------
REM  JARVIS AI PRO - smart installer
REM
REM  Keep this file beside main.py (in the JarvisAI folder).
REM  All decision logic lives in tools\windows_setup.py so it can be tested;
REM  this file only finds a bootstrap Python, shows the menu, and relays exit
REM  codes. It never deletes user data and never needs administrator rights.
REM ---------------------------------------------------------------------------

REM Resolve this script's own folder, including paths with spaces or "&".
set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
REM A project at a drive root ("D:\") loses its backslash above; put it back so
REM `cd /d` lands in the root instead of the drive's current folder.
if "%PROJECT_DIR:~-1%"==":" set "PROJECT_DIR=%PROJECT_DIR%\"
cd /d "%PROJECT_DIR%" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Could not open the project folder:
    echo         "%PROJECT_DIR%"
    echo         Move the whole JarvisAI folder somewhere you can write to, then retry.
    goto :fail
)

set "SETUP_PY=%PROJECT_DIR%\tools\windows_setup.py"
set "PYTHON_CMD="

REM PYTHON_CMD is a command prefix such as `py -3.12`, not a single path, so it
REM is expanded without surrounding quotes; every path argument stays quoted.

REM Sanity-check the checkout before doing anything else.
for %%F in (main.py setup.py requirements.txt tools\windows_setup.py) do (
    if not exist "%PROJECT_DIR%\%%F" (
        echo [ERROR] Required project file not found: %%F
        echo         Extract the whole archive and run this BAT from the JarvisAI folder.
        goto :fail
    )
)

call :banner
call :find_python
if not defined PYTHON_CMD goto :no_python

:menu
echo.
echo   ==========================================================
echo             J A R V I S   A I   P R O   -   S E T U P
echo   ==========================================================
echo.
echo     1.  Install / Repair JARVIS
echo     2.  Verify installation
echo     3.  Launch JARVIS
echo     4.  Exit
echo.
set "CHOICE="
set /p "CHOICE=  Select an option [1-4]: "
if not defined CHOICE set "CHOICE=1"
if "%CHOICE%"=="1" goto :do_install
if "%CHOICE%"=="2" goto :do_verify
if "%CHOICE%"=="3" goto :do_launch
if "%CHOICE%"=="4" goto :done
echo.
echo   [WARN] Please type 1, 2, 3 or 4.
goto :menu

REM ---------------------------------------------------------------------------
REM  1) Install / Repair
REM ---------------------------------------------------------------------------
:do_install
echo.
echo   [1/3] Looking for a supported Python (3.11 - 3.13, 3.12 preferred)...
%PYTHON_CMD% "%SETUP_PY%" interpreters
if errorlevel 1 (
    echo.
    echo   [ERROR] No supported Python was found.
    echo           Install Python 3.12 from https://www.python.org/downloads/
    echo           and tick "Add python.exe to PATH" / "Python Launcher".
    goto :fail
)

REM Optional feature: local Voice ID (torch). Never installed silently - it is
REM several hundred MB and the app works without it.
set "INSTALL_FLAGS="
echo.
echo   Optional feature - local Voice ID (speaker verification with torch).
echo   It is a large download and JARVIS works without it; it can be added later.
set "VOICE_ID="
set /p "VOICE_ID=  Install it as well? [y/N]: "
if /i "!VOICE_ID!"=="y" set "INSTALL_FLAGS=--with-voice-id"

echo.
echo   [2/3] Preparing the isolated .venv (existing files are never deleted; a
echo         broken .venv is renamed to .venv.broken-^(timestamp^), not removed).
echo   [3/3] Installing dependencies (needs internet; several minutes the first time)...
%PYTHON_CMD% "%SETUP_PY%" install %INSTALL_FLAGS%
if errorlevel 1 goto :install_failed
goto :after_action

:install_failed
echo.
echo   [ERROR] Installation did not complete. Nothing was launched.
echo           - Check the internet connection (pip must reach the package index).
echo           - Scroll up for the first pip error; it names the failing package.
echo           - Then run "Install / Repair JARVIS" again.
goto :fail

REM ---------------------------------------------------------------------------
REM  2) Verify
REM ---------------------------------------------------------------------------
:do_verify
echo.
%PYTHON_CMD% "%SETUP_PY%" verify
if errorlevel 1 (
    echo.
    echo   [ERROR] Verification found problems. Run "Install / Repair JARVIS".
    goto :after_action
)
echo.
echo   [OK] Verification passed. Configuration and cloud services are reported
echo        separately above - a green check never means an API key works.
goto :after_action

REM ---------------------------------------------------------------------------
REM  3) Launch
REM ---------------------------------------------------------------------------
:do_launch
echo.
%PYTHON_CMD% "%SETUP_PY%" status >nul 2>&1
if errorlevel 1 (
    echo   [WARN] JARVIS is not installed yet in this folder.
    set "ANSWER="
    set /p "ANSWER=          Install it now? [Y/n]: "
    if /i "!ANSWER!"=="n" goto :menu
    goto :do_install
)
%PYTHON_CMD% "%SETUP_PY%" launch
set "JARVIS_EXIT=%ERRORLEVEL%"
echo.
if not "%JARVIS_EXIT%"=="0" (
    echo   [ERROR] JARVIS closed with exit code %JARVIS_EXIT%.
    echo           Read the Python messages above; they name the real cause.
    goto :after_action
)
echo   [OK] JARVIS closed normally.
goto :after_action

REM ---------------------------------------------------------------------------
:after_action
echo.
set "AGAIN="
set /p "AGAIN=  Return to the menu? [Y/n]: "
if /i "!AGAIN!"=="n" goto :done
goto :menu

REM ---------------------------------------------------------------------------
REM  Python discovery - any 3.11-3.13 works for the bootstrap; windows_setup.py
REM  then picks the best one for .venv (3.12 first, never "the newest").
REM ---------------------------------------------------------------------------
:find_python
call :probe py -3.12
if defined PYTHON_CMD goto :find_python_done
call :probe py -3.13
if defined PYTHON_CMD goto :find_python_done
call :probe py -3.11
if defined PYTHON_CMD goto :find_python_done
call :probe python
if defined PYTHON_CMD goto :find_python_done
call :probe py -3
:find_python_done
if defined PYTHON_CMD echo   [OK] Bootstrap Python: !PYTHON_CMD!
exit /b 0

:probe
REM %* is the candidate command, e.g. "py -3.12". Quoted, so -c stays one arg.
%* -c "import sys; raise SystemExit(0 if (3,11) <= sys.version_info[:2] <= (3,13) else 1)" >nul 2>&1
if errorlevel 1 exit /b 0
set "PYTHON_CMD=%*"
exit /b 0

:no_python
echo.
echo   [ERROR] No supported Python (3.11 - 3.13) was found on this PC.
echo.
echo   Install Python 3.12 for your user account, then run this file again:
echo.
echo       winget install --id Python.Python.3.12 --exact --scope user ^
echo              --accept-package-agreements --accept-source-agreements
echo.
echo   Or download it from https://www.python.org/downloads/
echo   During installation, tick "Add python.exe to PATH" and, if offered,
echo   "Python Launcher". No administrator rights are required.
echo.
echo   JARVIS was NOT installed and nothing on this PC was changed.
goto :fail

:banner
echo.
echo   JARVIS AI PRO  -  Windows setup and launcher
echo   Folder: %PROJECT_DIR%
exit /b 0

:done
echo.
echo   Done. This window can be closed.
endlocal
exit /b 0

:fail
echo.
pause
endlocal
exit /b 1
