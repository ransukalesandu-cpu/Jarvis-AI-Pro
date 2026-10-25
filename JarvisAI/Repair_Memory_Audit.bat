@echo off
setlocal
cd /d "%~dp0"
title JARVIS Memory Audit Recovery

echo.
echo  ==========================================
echo       JARVIS MEMORY AUDIT RECOVERY
echo  ==========================================
echo.
echo IMPORTANT:
echo   1. Close JARVIS completely before continuing.
echo   2. This utility makes a local backup first.
echo   3. A broken old audit chain cannot be retroactively verified after repair.
echo.
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Jarvis virtual environment was not found.
    echo Run Run_Jarvis.bat once to complete setup, then close JARVIS and retry.
    echo.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" repair_memory_audit.py
set "RECOVERY_EXIT=%ERRORLEVEL%"
echo.
if not "%RECOVERY_EXIT%"=="0" (
    echo [ERROR] Memory audit recovery did not complete.
    echo Do not delete memory or config files. Read the error above.
) else (
    echo [OK] Memory audit recovery completed and verified.
)
echo.
pause
exit /b %RECOVERY_EXIT%
