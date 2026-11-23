# Phone control from anywhere (ADB over Tailscale)

Wireless debugging only works while the phone and laptop are on the same Wi-Fi, and Android turns it off on
mobile data. With Tailscale and a fixed ADB port the laptop agent can control the phone on any network.

## One-time setup
1. Tailscale on the laptop and the phone, same account (see README "Multi-device setup").
2. In the Tailscale app on the phone, note its address (`100.x.y.z`), or use its MagicDNS name.
3. In `devices.json` (hub), add it next to the home address:
   ```json
   {"name": "phone", "kind": "android", "client": true,
    "adb": {"address": "192.168.1.50:37123", "remote_address": "100.101.102.103:5555", "via": "laptop"}}
   ```
4. With the phone at home (wireless debugging) or on USB, say **"Jarvis, turn on remote access for my phone"**
   (tool `remote_access`, runs `adb tcpip 5555`). Restart the hub after editing `devices.json`.

The agent tries the home address first and the Tailscale address when that fails; `which devices are online?`
shows `transport: tailscale` when it is used.

## Limits
- `adb tcpip` is lost when the phone **restarts**: say "turn on remote access" again from home/USB.
- Port 5555 then listens on every network the phone joins. Only computers whose ADB key you already
  approved on the phone can control it; never accept an unknown "Allow USB debugging?" prompt.
  Turn it off with `adb usb` (or restart the phone).
- Some carriers' mobile networks are slow; screenshots and UI-tree reads take longer than at home.
- The laptop agent must be running (laptop on and awake).
