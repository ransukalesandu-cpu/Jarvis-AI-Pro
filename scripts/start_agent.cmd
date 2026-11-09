@echo off
rem Start the JARVIS laptop agent. Pair once first: python -m jarvis.laptop_agent pair URL
cd /d "%~dp0.."
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
"%PY%" -m jarvis.laptop_agent %*
