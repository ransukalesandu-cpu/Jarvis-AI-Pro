# JARVIS Remote Tablet Setup Guide (Wi-Fi & USB Connections)

This guide explains how to connect an Android tablet to your Windows laptop as a remote Heads-Up Display (HUD) and controller using either **Same-Wi-Fi Network Access** or **Direct USB Cable (ADB Reverse Port Forwarding)**.

---

## Connection Options Overview

| Feature | Option A: Same-Wi-Fi (LAN Mode) | Option B: USB Cable (ADB Tunnel) |
|---|---|---|
| **Primary Connection** | Wi-Fi Local Area Network (Same Subnet) | USB Data Cable |
| **Tablet Browser Address** | `https://<LAPTOP_LAN_IP>:8000` | `http://127.0.0.1:8000` |
| **Wi-Fi Required?** | Yes (both laptop and tablet on same Wi-Fi) | No |
| **Configuration Opt-in** | `JARVIS_ALLOW_LAN=true` | None (Loopback `127.0.0.1` default) |
| **ADB Required?** | No | Yes |

---

## Option A: Same-Wi-Fi Network Access (LAN Mode)

Use this mode when your laptop and Android tablet are connected to the same Wi-Fi router/network.

### 1. Enable LAN Access Opt-in on Laptop
By default, JARVIS binds only to loopback (`127.0.0.1`) for maximum privacy and safety. To allow same-Wi-Fi access from your tablet, set the environment variable on your laptop before starting JARVIS:

**PowerShell**:
```powershell
$env:JARVIS_ALLOW_LAN = "true"
python run.py
```

LAN mode refuses to bind to the network unless the dashboard has a usable TLS certificate. The certificate is generated locally and may need to be installed/trusted on the tablet. Do not transmit the pairing PIN or commands over a connection whose certificate you do not trust.

**Command Prompt (CMD)**:
```cmd
set JARVIS_ALLOW_LAN=true
python run.py
```

### 2. Find Your Laptop's Local IP Address
1. Open PowerShell/CMD and run: `ipconfig`
2. Look for **IPv4 Address** under your Wi-Fi adapter (e.g., `192.168.1.15`).

### 3. Open Dashboard on Tablet Browser
1. Connect tablet to the same Wi-Fi network as the laptop.
2. Open Chrome/Firefox on tablet and navigate to:
   ```
   https://<LAPTOP_LAN_IP>:8000
   ```
   *(e.g., `https://192.168.1.15:8000`)*
3. Enter your 6-character JARVIS remote session key or scan the QR code from the JARVIS desktop app (**Remote Control** button).

---

## Option B: USB Cable Access (ADB Reverse Port Forwarding)

Use this mode when Wi-Fi is unavailable or when you prefer a direct wired USB connection. The tablet browser accesses `http://127.0.0.1:8000`, which resolves through the ADB reverse tunnel to JARVIS on your laptop.

### 1. Install or Verify ADB on Laptop
1. Download Android SDK Platform-Tools for Windows if not already present.
2. Extract to `C:\platform-tools` or add `adb.exe` to system `PATH`.
3. Verify in PowerShell/CMD:
   ```cmd
   adb version
   ```

### 2. Enable USB Debugging on Tablet
1. Go to **Settings > About Tablet** and tap **Build Number** 7 times.
2. Go to **Settings > System > Developer Options** and enable **USB Debugging**.

### 3. Connect USB Cable and Authorize Laptop
1. Connect tablet to laptop via USB data cable.
2. Accept the pop-up on tablet: **"Allow USB debugging?"** -> Select **"Always allow from this computer"** -> **Allow**.
3. Verify connection:
   ```cmd
   adb devices
   ```
   Your device serial should display status `device` (not `unauthorized` or `offline`).

### 4. Start JARVIS
Launch JARVIS normally (LAN opt-in is not required for loopback USB tunnel):
```cmd
python run.py
```

### 5. Start the Windows ADB Connection Manager
Open PowerShell and run the persistent connection manager:
```powershell
.\scripts\windows\start_adb_bridge.ps1
```
*(Or double-click `scripts\windows\start_adb_bridge.cmd`)*

The script discovers `adb.exe`, verifies authorized device status, applies `adb reverse tcp:8000 tcp:8000`, and automatically restores forwarding after cable disconnections or laptop sleep.

### 6. Open Dashboard on Tablet Browser
Open Chrome/Firefox on tablet and navigate to:
```
http://127.0.0.1:8000
```
Enter your session key or scan the QR code to connect!

---

## Configuring Automatic Startup via Windows Task Scheduler

To start the ADB USB Connection Manager automatically upon Windows user log in:

1. Open **Task Scheduler** (`Win + R` -> `taskschd.msc`).
2. Click **Create Task...**.
3. **General**: Name: `JARVIS ADB USB Bridge`. Account: Standard user account ("Run only when user is logged on").
4. **Triggers**: **At log on** for your user account.
5. **Actions**: Program: `powershell.exe`. Add arguments: `-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "C:\path\to\Jarvis-AI-Pro\scripts\windows\start_adb_bridge.ps1"`.
6. Click **OK**.

---

## Troubleshooting Guide

| Issue | Cause | Resolution |
|---|---|---|
| **"Connection Refused" in Option A** | Laptop and tablet are on different Wi-Fi subnets or `JARVIS_ALLOW_LAN=true` was not set. | Ensure both devices are on the same Wi-Fi and restart JARVIS with `JARVIS_ALLOW_LAN=true`. |
| **"Connection Refused" in Option B** | ADB reverse port forwarding is missing or dashboard is stopped. | Verify JARVIS is running and `start_adb_bridge.ps1` reports active reverse forwarding. |
| **"Device Unauthorized" in script logs** | USB debugging prompt not accepted on tablet. | Unlock tablet, reconnect USB cable, and select "Always allow from this computer". |
| **Port 8000 conflict** | Another local process is occupying port 8000. | Stop the competing process on laptop and restart JARVIS. |

---

## Testing & Verification Status

- **Automated / CI Verified**:
  - Dashboard server startup, GET `/health` endpoint checks, and 401 protection on sensitive routes.
  - Cross-origin / CSRF origin validation middleware.
  - ADB device status parsing, authorized selection, and reverse rule checking in `services/adb_bridge.py`.
- **Physical Hardware Verification Required**:
  - Physical USB cable connection and accepting Android OS USB debugging authorization pop-up.
  - Real Wi-Fi network subnet routing between laptop and tablet.
