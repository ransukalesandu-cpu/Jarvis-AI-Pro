@echo off
rem One command: hub and laptop agent on this laptop (each in its own window).
start "JARVIS hub" cmd /k "%~dp0start_hub.cmd"
timeout /t 4 /nobreak >nul
start "JARVIS agent" cmd /k "%~dp0start_agent.cmd"
