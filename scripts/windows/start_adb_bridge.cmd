@echo off
REM Batch wrapper script to launch start_adb_bridge.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_adb_bridge.ps1"
