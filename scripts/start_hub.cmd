@echo off
rem Start the JARVIS hub. Settings come from environment variables or JARVIS_HUB_CONFIG.
cd /d "%~dp0..\JarvisAI"
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
"%PY%" -m hub %*
