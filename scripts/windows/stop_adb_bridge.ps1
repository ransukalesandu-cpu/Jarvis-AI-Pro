# ==============================================================================
# stop_adb_bridge.ps1
# Stops the persistent ADB Connection Manager and removes reverse port forwards
# ==============================================================================

[CmdletBinding()]
param(
    [int]$RemotePort = 8000
)

Write-Host "[ADB Bridge] Stopping JARVIS ADB Connection Manager..." -ForegroundColor Yellow

# Find and stop PowerShell processes running start_adb_bridge.ps1
$runningProcesses = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*start_adb_bridge.ps1*"
}

if ($runningProcesses) {
    foreach ($proc in $runningProcesses) {
        Write-Host "[ADB Bridge] Terminating process ID $($proc.ProcessId)..." -ForegroundColor Cyan
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    }
} else {
    Write-Host "[ADB Bridge] No active start_adb_bridge.ps1 processes found." -ForegroundColor Gray
}

# Discover adb executable
function Find-AdbExecutable {
    $cmd = Get-Command "adb.exe" -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidates = @(
        "$env:ANDROID_HOME\platform-tools\adb.exe",
        "$env:ANDROID_SDK_ROOT\platform-tools\adb.exe",
        "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe",
        "$env:USERPROFILE\AppData\Local\Android\Sdk\platform-tools\adb.exe",
        "$env:USERPROFILE\scoop\shims\adb.exe",
        "$env:ProgramData\chocolatey\bin\adb.exe",
        "C:\platform-tools\adb.exe"
    )
    foreach ($path in $candidates) {
        if ($path -and (Test-Path -Path $path -PathType Leaf)) { return $path }
    }
    return $null
}

$adbPath = Find-AdbExecutable
if ($adbPath) {
    Write-Host "[ADB Bridge] Removing reverse port forwarding rule (tcp:$RemotePort)..." -ForegroundColor Cyan
    & $adbPath reverse --remove "tcp:$RemotePort" 2>&1 | Out-Null
    Write-Host "[ADB Bridge] Reverse port forwarding removed." -ForegroundColor Green
}

Write-Host "[ADB Bridge] Clean stop complete." -ForegroundColor Green
