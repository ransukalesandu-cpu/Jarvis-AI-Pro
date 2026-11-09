@echo off
rem Start the JARVIS worker node on the dedicated device (Windows).
rem Settings: JARVIS_NODE_* environment variables; see docs\architecture\MULTI_DEVICE.md.
cd /d "%~dp0.."
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
"%PY%" -m jarvis.node serve %*
