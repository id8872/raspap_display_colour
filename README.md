# RaspAP Touch Panel – Kivy Edition

A full-screen, touch-friendly control panel for Raspberry Pi that manages Wi‑Fi, OpenVPN, and shows system status. Designed for a 3.5" landscape display (480×320) and integrates optionally with RaspAP to display connected AP clients.

- Built with Kivy
- Works headless (KMS/DRM) or under X11
- Uses system tools (wpa_cli/nmcli/openvpn) for Wi‑Fi and VPN control
- Clean exit: paints the screen black when the app closes
- Smart GeoIP updates: on start, when connectivity or VPN changes, and periodically

---

## Features

- Main dashboard with:
  - Internet SSID, VPN status/name, connected AP clients (via RaspAP API), CPU temperature, GeoIP location, uptime
  - Quick nav buttons for Wi‑Fi, VPN, System, Info
- Wi‑Fi screen:
  - Scans for saved networks in range and allows connecting
  - Disconnect button
- VPN screen:
  - One-tap connect to profiles (ovpn files in assets/ovpn)
  - Disconnect button
- Info screen:
  - Internet/AP details, hostname, uptime, CPU, GeoIP
  - Optional speed test via one of: Python speedtest module / Ookla CLI / speedtest-cli
- System screen:
  - Reboot / Shutdown
- GeoIP refresh:
  - On start, when Wi‑Fi/VPN state changes, and every geoip_interval seconds
- Exit behavior:
  - Paints black on on_request_close and on_stop to leave the screen clean

---

## Requirements

- Raspberry Pi with a 3.5" display (SPI/DSI/HDMI). Target resolution: 480×320 landscape.
- OS: Raspberry Pi OS (Bullseye/Bookworm) or similar Debian-based.
- Python 3.9+ recommended.

System tools:
- wpa_cli (wpasupplicant)
- NetworkManager’s nmcli (optional; used if present)
- openvpn
- iproute2 (ip)
- systemd (for reboot/shutdown)

Python packages:
- kivy
- requests
- Optional: speedtest (Python module) and/or speedtest-cli and/or Ookla’s speedtest

Assets (in assets/):
- DejaVuSans.ttf, DejaVuSans-Bold.ttf
- fontawesome.otf
- raspAP-logo.png, qr.png, loading.png
- VPN profiles in assets/ovpn/*.ovpn

---

## Installation

Install system packages:
```bash
sudo apt update
sudo apt install -y python3 python3-pip \
    python3-kivy # or install Kivy via pip if you prefer
sudo apt install -y wpasupplicant iproute2 openvpn
# Optional:
sudo apt install -y network-manager  # for nmcli usage
```

Install Python deps (if Kivy not installed via apt, you can use pip — on Pi, apt is usually easier/stabler for Kivy):
```bash
pip3 install --upgrade requests
# Optional speed test backends:
pip3 install speedtest-cli  # CLI variant
pip3 install speedtest      # Python module (by sivel)
# Ookla CLI (optional): see https://www.speedtest.net/apps/cli for repo & install
```

Clone/copy this project so that:
```
project/
  raspap_touch.py
  assets/
    DejaVuSans.ttf
    DejaVuSans-Bold.ttf
    fontawesome.otf
    raspAP-logo.png
    qr.png
    loading.png
    ovpn/
      your-profile.ovpn
  config.json   # optional
```

---

## Configuration

The app loads config.json from the script directory if present. Otherwise, it uses defaults baked in the script.

Example config.json:
```json
{
  "update_interval": 2,
  "default_screen": "main",
  "geoip_interval": 300,
  "theme": {
    "primary_color": "#3498DB",
    "accent_color": "#2ECC71",
    "background_color": "#ECF0F1",
    "text_light": "#FFFFFF",
    "text_dark": "#2C3E50",
    "button_normal": "#34495E",
    "button_pressed": "#5D6D7E",
    "button_off": "#C0392B"
  },
  "fonts": {
    "title": "42sp",
    "header": "26sp",
    "normal": "22sp",
    "small": "16sp"
  },
  "vpn_profiles": [
    { "display_name": "My VPN", "file": "myvpn.ovpn" },
    { "display_name": "Work VPN", "file": "work.ovpn" }
  ]
}
```

Notes:
- Place your .ovpn files under assets/ovpn/.
- If your .ovpn requires credentials, configure them as the profile expects (e.g., auth-user-pass with an external file).
- Colors are hex strings; font sizes accept Kivy “sp” units.

---

## Environment Variables

- RASPAP_API_KEY: Token for the RaspAP REST API. If not set, the app still runs but “Connected Clients” will show 0.
- RASPAP_API_BASE_URL: Base URL to reach the RaspAP API. Default: http://localhost:8081

Example:
```bash
export RASPAP_API_KEY="your_token_here"
export RASPAP_API_BASE_URL="http://127.0.0.1:8081"
```

RaspAP use:
- The app calls GET /clients/{ap_iface} expecting JSON with active_clients.
- ap_iface is inferred from /etc/hostapd/hostapd.conf (interface=). The other wlan is treated as the client interface.
- If hostapd.conf doesn’t exist or lacks interface, defaults are used (ap_iface=wlan1, host_iface=wlan0).

---

## Running

From the project directory:
```bash
python3 raspap_touch.py
```

The app opens fullscreen at 480×320, repaints the screen black on exit, and restores GeoIP periodically.

---

## Systemd Service (optional)

Run as a service on boot:

Create /etc/systemd/system/raspap-touch.service
```ini
[Unit]
Description=RaspAP Touch Panel (Kivy)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
Group=pi
WorkingDirectory=/home/pi/raspap-touch
Environment=RASPAP_API_KEY=your_token_here
Environment=RASPAP_API_BASE_URL=http://127.0.0.1:8081
ExecStart=/usr/bin/python3 /home/pi/raspap-touch/raspap_touch.py
Restart=on-failure

# If using KMS/DRM, ensure a session exists; under X11 you may need DISPLAY=:0
# Environment=DISPLAY=:0

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable raspap-touch
sudo systemctl start raspap-touch
```

---

## Sudo permissions

This app runs system commands with sudo:
- wpa_cli (connect/select/enable/save)
- nmcli (connect/disconnect)
- openvpn (start/kill)
- ip addr flush (on disconnect)
- systemctl reboot/poweroff (from System screen)

Recommended: run as a normal user and grant passwordless sudo for only the required commands.

Find paths with which:
```bash
which wpa_cli nmcli openvpn ip systemctl killall
```

Example sudoers (edit with sudo visudo):
```
pi ALL=(root) NOPASSWD: /usr/sbin/wpa_cli, /usr/bin/nmcli, /usr/sbin/openvpn, /usr/bin/killall, /sbin/ip, /bin/systemctl
```

Adjust paths to match your system. Without sudoers, the app may prompt or fail to perform actions.

---

## How things work

- Interface detection:
  - Reads /etc/hostapd/hostapd.conf: interface=wlanX → ap_iface
  - host_iface is set to the other wlan (“client” Wi‑Fi)
- Wi‑Fi scanning:
  - Uses nmcli if available and wpa_cli (scan_results) to merge best signals
  - Displays only saved networks that are in range; saved-but-out-of-range are shown separately
- VPN control:
  - Connect: sudo openvpn --daemon --config assets/ovpn/<file>
  - Disconnect: sudo killall openvpn
- GeoIP:
  - Uses http://ip-api.com/json/?fields=status,message,country,city
  - Updates on start, when net/vpn changes (debounced), and every geoip_interval seconds
- Speed Test:
  - Tries Python speedtest module → Ookla CLI → speedtest-cli (first available)
- Exit behavior:
  - Paints a full-screen black rectangle on close so the display looks clean

---

## Troubleshooting

- “Connected Clients” always 0:
  - Set RASPAP_API_KEY and RASPAP_API_BASE_URL; ensure RaspAP API is enabled and reachable; ap_iface matches hostapd interface.
- Wi‑Fi list is empty or can’t connect:
  - Ensure saved networks exist (wpa_cli list_networks or NetworkManager)
  - Ensure sudo permissions for wpa_cli/nmcli; check host_iface is correct
- VPN doesn’t connect:
  - Check that assets/ovpn/<profile>.ovpn exists and is valid; logs in journalctl -u raspap-touch or run in terminal for debug
- Speed test fails:
  - Install at least one backend: pip install speedtest or speedtest-cli or Ookla CLI
- Fonts missing:
  - Ensure DejaVuSans.ttf, DejaVuSans-Bold.ttf, fontawesome.otf are present in assets/
- Display not fullscreen or won’t start:
  - On a plain console (no X), Kivy uses SDL/KMS; on X11, set DISPLAY=:0 in the service.
  - Verify Kivy is installed properly (apt install python3-kivy or pip install kivy with its dependencies).

---

## Customization

- Theme and fonts in config.json
- Default screen via default_screen (“main”, “wifi”, “vpn”, “sys”, “info”)
- Poll intervals: update_interval (general UI/state), geoip_interval (GeoIP)
- Add VPN profiles in config.json with display names that map to ovpn files in assets/ovpn/

---

## Notes

- The “blank on exit” paints black but does not power off the backlight. If you need to truly switch off the panel, you can add platform-specific backlight/DPMS control (e.g., via /sys/class/backlight, vcgencmd, fb blank, or xset).
- RaspAP integration is optional; the app works without it.

---

## License

Choose a license for your project (e.g., MIT). Example:
- MIT License — see LICENSE file.

---

## Acknowledgements

- [Kivy](https://kivy.org/)
- [RaspAP](https://raspap.com/)
- Speed test tools: [sivel/speedtest](https://github.com/sivel/speedtest-cli), Ookla CLI

---

## Screenshots

Add your own photos/screens under docs/ or assets/ and reference them here.

```markdown
![Main screen](docs/main.jpg)
![Wi‑Fi screen](docs/wifi.jpg)
![VPN screen](docs/vpn.jpg)
![Info screen](docs/info.jpg)
```

---

## Development

- Run in a terminal to see logs:
```bash
LOG_LEVEL=DEBUG python3 raspap_touch.py
```
- Tweak KV rules in the build() method (kv_string) for quick UI changes.
- PRs/issues welcome!
