@echo off
setlocal EnableExtensions EnableDelayedExpansion
title JARVIS AI PRO
chcp 65001 >nul 2>&1

REM ---------------------------------------------------------------------------
REM  JARVIS AI PRO - launcher
REM
REM  Double-click this after Jarvis_Setup.bat has installed the environment.
REM  It used to re-run the whole dependency install on every start (slow, and
REM  pointless when nothing changed). Now it launches immediately and only hands
REM  off to the installer when the .venv is missing or unusable.
REM  Keep this file beside main.py (in the JarvisAI folder).
REM ---------------------------------------------------------------------------

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

for %%F in (main.py setup.py requirements.txt tools\windows_setup.py) do (
    if not exist "%PROJECT_DIR%\%%F" (
        echo [ERROR] Required project file not found: %%F
        echo         Extract the whole archive and run this BAT from the JarvisAI folder.
        goto :fail
    )
)

echo.
echo   ======================================
echo          JARVIS AI PRO LAUNCHER
echo   ======================================
echo.

if not exist "%PROJECT_DIR%\.venv\Scripts\python.exe" goto :not_installed

"%PROJECT_DIR%\.venv\Scripts\python.exe" "%SETUP_PY%" status >nul 2>&1
if errorlevel 1 goto :venv_broken

REM Launch with the project's own interpreter; output stays in this window so a
REM Python traceback is readable instead of vanishing with the console.
"%PROJECT_DIR%\.venv\Scripts\python.exe" "%SETUP_PY%" launch
set "JARVIS_EXIT=%ERRORLEVEL%"

echo.
if not "%JARVIS_EXIT%"=="0" (
    echo   [ERROR] JARVIS closed with exit code %JARVIS_EXIT%.
    echo           The messages above are JARVIS's own diagnostics.
    echo           If it failed during setup, run Jarvis_Setup.bat and choose
    echo           "Install / Repair JARVIS".
) else (
    echo   [OK] JARVIS closed normally.
)
echo.
pause
exit /b %JARVIS_EXIT%

:not_installed
echo   [INFO] JARVIS has not been installed in this folder yet.
echo          (.venv is missing - no Python packages were installed.)
echo.
goto :offer_install

:venv_broken
echo   [WARN] The existing .venv cannot be used as it is.
if exist "%PROJECT_DIR%\.venv" (
    echo          Nothing has been deleted. The installer will move it aside
    echo          to .venv.broken-^(timestamp^) and build a fresh one.
)
echo.
goto :offer_install

:offer_install
set "ANSWER="
set /p "ANSWER=  Run the installer now? [Y/n]: "
if /i "!ANSWER!"=="n" (
    echo.
    echo   Nothing was changed. Run Jarvis_Setup.bat when you are ready.
    goto :fail
)
if not exist "%PROJECT_DIR%\Jarvis_Setup.bat" (
    echo   [ERROR] Jarvis_Setup.bat is missing from this folder.
    echo           Re-extract the archive; both BAT files belong side by side.
    goto :fail
)
call "%PROJECT_DIR%\Jarvis_Setup.bat"
exit /b %ERRORLEVEL%

:fail
echo.
pause
exit /b 1
