# ==============================================================================
# start_adb_bridge.ps1
# Persistent ADB Reverse Port Forwarding Manager for JARVIS Android Tablet HUD
# ==============================================================================

[CmdletBinding()]
param(
    [int]$LocalPort = 8000,
    [int]$RemotePort = 8000,
    [int]$PollIntervalSeconds = 4
)

$ErrorActionPreference = "Continue"

# Single-instance lock using a system Mutex
$mutexName = "Global\JARVIS_ADB_BRIDGE_MUTEX"
$createdNew = $false
$mutex = New-Object System.Threading.Mutex($true, $mutexName, [ref]$createdNew)

if (-not $createdNew) {
    Write-Host "[ADB Bridge] Another instance of JARVIS ADB Connection Manager is already running." -ForegroundColor Yellow
    exit 0
}

function Find-AdbExecutable {
    # 1. Check system PATH
    $cmd = Get-Command "adb.exe" -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    # 2. Check environment variables & standard Android SDK / tool installation locations
    $candidates = @(
        "$env:ANDROID_HOME\platform-tools\adb.exe",
        "$env:ANDROID_SDK_ROOT\platform-tools\adb.exe",
        "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe",
        "$env:USERPROFILE\AppData\Local\Android\Sdk\platform-tools\adb.exe",
        "$env:USERPROFILE\scoop\shims\adb.exe",
        "$env:ProgramData\chocolatey\bin\adb.exe",
        "C:\platform-tools\adb.exe",
        "C:\Program Files\Android\android-sdk\platform-tools\adb.exe",
        "C:\Program Files (x86)\Android\android-sdk\platform-tools\adb.exe"
    )

    foreach ($path in $candidates) {
        if ($path -and (Test-Path -Path $path -PathType Leaf)) {
            return $path
        }
    }

    return $null
}

$adbPath = Find-AdbExecutable

if (-not $adbPath) {
    Write-Host "[ADB Bridge] ERROR: Could not find 'adb.exe' executable." -ForegroundColor Red
    Write-Host "[ADB Bridge] Please install Android Platform Tools or add adb.exe to your PATH." -ForegroundColor Red
    [System.Threading.Mutex]::OpenExisting($mutexName).ReleaseMutex() | Out-Null
    exit 1
}

Write-Host "[ADB Bridge] Using ADB executable: $adbPath" -ForegroundColor Green
Write-Host "[ADB Bridge] Target port forwarding: Android tcp:$RemotePort -> Laptop tcp:$LocalPort" -ForegroundColor Cyan

# Start ADB server if not running
& $adbPath start-server | Out-Null

$lastConnectedSerial = $null
$lastForwardedState = $false

try {
    Write-Host "[ADB Bridge] Monitoring USB connection for Android tablet... (Press Ctrl+C to stop)" -ForegroundColor Yellow

    while ($true) {
        # Query connected devices
        $rawDevices = & $adbPath devices
        $deviceLines = $rawDevices | Where-Object { $_ -match "\t(device|unauthorized|offline)$" }

        if (-not $deviceLines) {
            if ($lastForwardedState) {
                Write-Host "[ADB Bridge] Tablet disconnected or USB cable removed. Retrying..." -ForegroundColor Yellow
                $lastForwardedState = $false
                $lastConnectedSerial = $null
            }
            Start-Sleep -Seconds $PollIntervalSeconds
            continue
        }

        # Parse first available device
        $firstLine = $deviceLines[0]
        $parts = $firstLine -split "\t"
        $serial = $parts[0].Trim()
        $state = $parts[1].Trim()

        if ($state -eq "unauthorized") {
            Write-Host "[ADB Bridge] WARNING: Device '$serial' is connected but UNAUTHORIZED." -ForegroundColor Yellow
            Write-Host "[ADB Bridge] Please unlock your tablet and accept 'Allow USB debugging' prompt." -ForegroundColor Yellow
            $lastForwardedState = $false
            Start-Sleep -Seconds $PollIntervalSeconds
            continue
        }

        if ($state -eq "offline") {
            Write-Host "[ADB Bridge] WARNING: Device '$serial' is OFFLINE. Re-checking..." -ForegroundColor Yellow
            $lastForwardedState = $false
            Start-Sleep -Seconds $PollIntervalSeconds
            continue
        }

        if ($state -eq "device") {
            # Device is connected and authorized
            if (-not $lastForwardedState -or ($lastConnectedSerial -ne $serial)) {
                Write-Host "[ADB Bridge] Detected authorized tablet: $serial" -ForegroundColor Green
                Write-Host "[ADB Bridge] Applying ADB reverse port forwarding (tcp:$RemotePort -> tcp:$LocalPort)..." -ForegroundColor Cyan

                $reverseOutput = & $adbPath -s $serial reverse "tcp:$RemotePort" "tcp:$LocalPort" 2>&1
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "[ADB Bridge] SUCCESS: Reverse port forwarding active!" -ForegroundColor Green
                    Write-Host "[ADB Bridge] Tablet browser can now access JARVIS dashboard at: http://127.0.0.1:$RemotePort" -ForegroundColor Green
                    $lastForwardedState = $true
                    $lastConnectedSerial = $serial
                } else {
                    Write-Host "[ADB Bridge] ERROR applying reverse port forwarding: $reverseOutput" -ForegroundColor Red
                    $lastForwardedState = $false
                }
            } else {
                # Verify forwarding rule is still present
                $currentReverses = & $adbPath -s $serial reverse --list
                $ruleMatch = "tcp:$RemotePort tcp:$LocalPort"
                if (-not ($currentReverses -match "tcp:$RemotePort")) {
                    Write-Host "[ADB Bridge] Forwarding rule lost. Re-applying ADB reverse port forwarding..." -ForegroundColor Yellow
                    & $adbPath -s $serial reverse "tcp:$RemotePort" "tcp:$LocalPort" | Out-Null
                }
            }
        }

        Start-Sleep -Seconds $PollIntervalSeconds
    }
}
finally {
    Write-Host "[ADB Bridge] Shutting down connection manager..." -ForegroundColor Yellow
    if ($mutex) {
        $mutex.ReleaseMutex()
        $mutex.Dispose()
    }
}
