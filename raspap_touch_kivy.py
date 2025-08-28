#!/usr/bin/env python3
"""
RaspAP Touch Panel – Kivy Edition
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A Kivy-based touch panel UI for managing a RaspAP instance on a 3.5-inch
(480x320) landscape display.
"""
import os
import json
import subprocess
import logging
import threading
import time
import shutil
from pathlib import Path
from functools import partial
from contextlib import contextmanager

import requests

# ------------------------------------------------------------
# Logging early, globals, HTTP session
# ------------------------------------------------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger("RaspAPTouch")

HTTP = requests.Session()
HTTP.headers.update({"accept": "application/json"})

# ------------------------------------------------------------
# Kivy imports (Config first)
# ------------------------------------------------------------
from kivy.config import Config
Config.set('graphics', 'fullscreen', '1')
Config.set('graphics', 'width', '480')
Config.set('graphics', 'height', '320')

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.animation import Animation
from kivy.core.text import LabelBase
from kivy.uix.button import Button, ButtonBehavior
from kivy.uix.label import Label
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.screenmanager import ScreenManager, Screen, FadeTransition
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.properties import StringProperty, NumericProperty, ListProperty
from kivy.lang import Builder
from kivy.utils import get_color_from_hex
from kivy.uix.image import Image
from kivy.event import EventDispatcher
from kivy.uix.floatlayout import FloatLayout

# ------------------------------------------------------------
# Config / constants
# ------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
ASSETS_DIR = SCRIPT_DIR / "assets"
OVPN_DIR = ASSETS_DIR / "ovpn"
HOSTAPD_CONF = Path("/etc/hostapd/hostapd.conf")
WPA_SUPPLICANT_CONF = Path("/etc/wpa_supplicant/wpa_supplicant.conf")

CONFIG = {}
DEFAULT_CONFIG = {
    "update_interval": 2,
    "default_screen": "main",
    "geoip_interval": 300,  # seconds; periodic GeoIP refresh
    "theme": {
        "primary_color": "#3498DB", "accent_color": "#2ECC71",
        "background_color": "#ECF0F1", "text_light": "#FFFFFF",
        "text_dark": "#2C3E50", "button_normal": "#34495E",
        "button_pressed": "#5D6D7E", "button_off": "#C0392B"
    },
    "fonts": {
        "title": "42sp", "header": "26sp", "normal": "22sp", "small": "16sp"
    }
}

try:
    with open(SCRIPT_DIR / 'config.json', 'r') as f:
        CONFIG = json.load(f)
        log.info("Successfully loaded config.json")
except (FileNotFoundError, json.JSONDecodeError) as e:
    log.warning(f"Could not load or parse config.json: {e}. Using default values.")
    CONFIG = DEFAULT_CONFIG

Window.clearcolor = get_color_from_hex("#2C3E50")

RASPAP_API_KEY = os.environ.get("RASPAP_API_KEY")
RASPAP_BASE_URL = os.environ.get("RASPAP_API_BASE_URL", "http://localhost:8081")

# Font Awesome
FA_FONT_FILE = str(ASSETS_DIR / "fontawesome.otf")

# --- FONT REGISTRATION ---
try:
    LabelBase.register(
        name='Roboto',
        fn_regular=str(ASSETS_DIR / 'DejaVuSans.ttf'),
        fn_bold=str(ASSETS_DIR / 'DejaVuSans-Bold.ttf'),
    )
    LabelBase.register(name="FontAwesome", fn_regular=FA_FONT_FILE)
    log.info("Successfully registered fonts.")
except Exception as e:
    log.error(f"Could not register fonts: {e}")
# --- END REGISTRATION ---


# ------------------------------------------------------------
# Theme Definitions
# ------------------------------------------------------------
class ThemeManager:
    def __init__(self, config):
        theme_config = config.get("theme", DEFAULT_CONFIG["theme"])
        font_config = config.get("fonts", DEFAULT_CONFIG["fonts"])

        self.PRIMARY_COLOR = get_color_from_hex(theme_config.get("primary_color", "#3498DB"))
        self.ACCENT_COLOR = get_color_from_hex(theme_config.get("accent_color", "#2ECC71"))
        self.BACKGROUND_COLOR = get_color_from_hex(theme_config.get("background_color", "#ECF0F1"))
        self.TEXT_COLOR_LIGHT = get_color_from_hex(theme_config.get("text_light", "#FFFFFF"))
        self.TEXT_COLOR_DARK = get_color_from_hex(theme_config.get("text_dark", "#2C3E50"))
        self.BUTTON_BG_NORMAL = get_color_from_hex(theme_config.get("button_normal", "#34495E"))
        self.BUTTON_BG_PRESSED = get_color_from_hex(theme_config.get("button_pressed", "#5D6D7E"))
        self.BUTTON_BG_OFF = get_color_from_hex(theme_config.get("button_off", "#C0392B"))

        self.FONT_SIZE_TITLE = font_config.get("title", "42sp")
        self.FONT_SIZE_HEADER = font_config.get("header", "26sp")
        self.FONT_SIZE_NORMAL = font_config.get("normal", "22sp")
        self.FONT_SIZE_SMALL = font_config.get("small", "16sp")

        self.BUTTON_HEIGHT = 45
        self.PADDING = 10
        self.SPACING = 8

THEME = ThemeManager(CONFIG)

# ------------------------------------------------------------
# Helpers: subprocess, raspap api, busy/toast overlays, threading
# ------------------------------------------------------------
def run_cmd(cmd, timeout=10, shell=False) -> str:
    try:
        if shell:
            completed = subprocess.run(
                cmd, shell=True, check=True, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, timeout=timeout, text=True
            )
        else:
            import shlex as _sh
            if isinstance(cmd, str):
                cmd = _sh.split(cmd)
            completed = subprocess.run(
                cmd, check=True, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, timeout=timeout, text=True
            )
        return completed.stdout.strip()
    except subprocess.TimeoutExpired:
        log.warning("Command timed-out: %s", cmd)
        return ""
    except subprocess.CalledProcessError:
        return ""


def raspap_api(endpoint: str, method: str = "GET", *, json_body=None, timeout=5):
    if not RASPAP_API_KEY:
        log.debug("RASPAP_API_KEY not set. Skipping API call.")
        return None
    url = f"{RASPAP_BASE_URL}/{endpoint.lstrip('/')}"
    headers = {"access_token": RASPAP_API_KEY}
    try:
        r = HTTP.request(method, url, headers=headers, json=json_body, timeout=timeout)
        r.raise_for_status()
        if not r.content:
            return None
        try:
            return r.json()
        except ValueError:
            return None
    except requests.RequestException as exc:
        log.debug("RaspAP API error [%s]: %s", endpoint, exc)
        return None


# ------------- Busy indicator (non-dimming overlay) -------------
class BusyOverlay(FloatLayout):
    def on_touch_down(self, touch): return True
    def on_touch_move(self, touch): return True
    def on_touch_up(self, touch): return True

BUSY_OVERLAY = None
BUSY_DEPTH = 0

def show_busy_indicator():
    global BUSY_OVERLAY, BUSY_DEPTH
    BUSY_DEPTH += 1
    if BUSY_OVERLAY:
        return
    overlay = BusyOverlay(size_hint=(1, 1))
    spinner = Image(source=str(ASSETS_DIR / 'loading.png'),
                    size_hint=(None, None), size=(120, 120),
                    pos_hint={'center_x': 0.5, 'center_y': 0.5})
    from kivy.graphics import PushMatrix, PopMatrix, Rotate
    with spinner.canvas.before:
        PushMatrix()
        spinner.rot = Rotate(angle=0, axis=(0, 0, 1))
    with spinner.canvas.after:
        PopMatrix()
    def update_origin(instance, value):
        instance.rot.origin = instance.center
    spinner.bind(center=update_origin)
    anim = Animation(angle=-360, duration=1.0)
    anim.repeat = True
    anim.start(spinner.rot)
    overlay.spinner = spinner
    overlay.anim = anim
    overlay.add_widget(spinner)
    BUSY_OVERLAY = overlay
    Window.add_widget(overlay)

def hide_busy_indicator():
    global BUSY_OVERLAY, BUSY_DEPTH
    BUSY_DEPTH = max(0, BUSY_DEPTH - 1)
    if BUSY_OVERLAY and BUSY_DEPTH == 0:
        try:
            if getattr(BUSY_OVERLAY, "spinner", None) and hasattr(BUSY_OVERLAY.spinner, "rot"):
                Animation.cancel_all(BUSY_OVERLAY.spinner.rot)
            Window.remove_widget(BUSY_OVERLAY)
        finally:
            BUSY_OVERLAY = None

@contextmanager
def busy():
    show_busy_indicator()
    try:
        yield
    finally:
        hide_busy_indicator()
# ---------------------------------------------------------------

# ------------- Toast message (non-dimming overlay) -------------
TOAST_OVERLAY = None

def show_message(title, message, duration=2, is_error=False, position='center'):
    global TOAST_OVERLAY
    if TOAST_OVERLAY is not None:
        try:
            Window.remove_widget(TOAST_OVERLAY)
        except Exception:
            pass
        TOAST_OVERLAY = None
    overlay = FloatLayout(size_hint=(1, 1))
    container = BoxLayout(orientation='vertical', padding=THEME.PADDING, spacing=THEME.SPACING,
                          size_hint=(None, None))
    container.size = (int(Window.width * 0.8), 110)
    container.pos_hint = {'center_x': 0.5, 'center_y': 0.5} if position != 'bottom' else {'center_x': 0.5, 'y': 0.05}
    title_color = THEME.BUTTON_BG_OFF if is_error else THEME.PRIMARY_COLOR
    text_color = THEME.TEXT_COLOR_DARK
    title_label = Label(text=title, halign='center', valign='middle',
                        font_size=THEME.FONT_SIZE_HEADER, color=title_color, size_hint=(1, 0.5))
    title_label.bind(size=lambda w, _: setattr(w, 'text_size', w.size))
    message_label = Label(text=message, halign='center', valign='middle',
                          font_size=THEME.FONT_SIZE_NORMAL, color=text_color, size_hint=(1, 0.5))
    message_label.bind(size=lambda w, _: setattr(w, 'text_size', w.size))
    container.add_widget(title_label); container.add_widget(message_label)
    from kivy.graphics import Color, RoundedRectangle
    with container.canvas.before:
        Color(*THEME.BACKGROUND_COLOR)
        bg_rect = RoundedRectangle(pos=container.pos, size=container.size, radius=[6,])
    container.bind(pos=lambda i, _: setattr(bg_rect, 'pos', i.pos),
                   size=lambda i, _: setattr(bg_rect, 'size', i.size))
    overlay.add_widget(container)
    TOAST_OVERLAY = overlay
    Window.add_widget(overlay)
    def _dismiss(dt):
        global TOAST_OVERLAY
        try:
            Window.remove_widget(overlay)
        except Exception:
            pass
        if TOAST_OVERLAY is overlay:
            TOAST_OVERLAY = None
    Clock.schedule_once(_dismiss, duration)
# ---------------------------------------------------------------

# ------------- Paint screen black right now -------------
def paint_black_now():
    try:
        from kivy.graphics import Color, Rectangle
        from kivy.base import EventLoop
        Window.canvas.clear()
        with Window.canvas:
            Color(0, 0, 0, 1)
            Rectangle(pos=(0, 0), size=Window.size)
        # Ensure it actually renders before we exit
        Window.canvas.ask_update()
        if EventLoop and EventLoop.window:
            EventLoop.idle()  # flush one frame
        time.sleep(0.05)  # tiny pause to let the scanout catch it
        log.info("Screen painted black on exit.")
    except Exception as e:
        log.error(f"Could not paint black on exit: {e}")
# ---------------------------------------------------------------

def run_bg(fn, on_done=None):
    def _worker():
        result = None
        err = None
        try:
            result = fn()
        except Exception as e:
            err = e
            log.debug("Background task error: %s", e)
        def _after(dt):
            if on_done:
                on_done(result, err)
        Clock.schedule_once(_after, 0)
    threading.Thread(target=_worker, daemon=True).start()


def parse_hostapd_conf():
    ssid = iface = None
    try:
        with HOSTAPD_CONF.open("r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("ssid="):
                    ssid = line.split("=", 1)[1]
                elif line.startswith("interface="):
                    iface = line.split("=", 1)[1]
    except Exception as e:
        log.debug("hostapd.conf parse error: %s", e)
    return ssid, iface


# ------------------------------------------------------------
# Wi-Fi utils (saved networks + scan + connect)
# ------------------------------------------------------------
def has_cmd(name: str) -> bool:
    return shutil.which(name) is not None

def dbm_to_percent(dbm: int) -> int:
    if dbm is None:
        return 0
    pct = 2 * (dbm + 100)
    return max(0, min(100, pct))

def get_saved_networks_wpa_cli(iface: str):
    out = run_cmd(["sudo", "wpa_cli", "-i", iface, "list_networks"], timeout=5)
    ssids = set()
    ssid_to_id = {}
    if not out:
        return ssids, ssid_to_id
    for line in out.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) >= 2:
            nid, ssid = parts[0], parts[1]
            if ssid:
                s = ssid.strip()
                ssids.add(s)
                ssid_to_id.setdefault(s, nid)
    return ssids, ssid_to_id

def get_saved_networks_from_conf():
    ssids = set()
    if not WPA_SUPPLICANT_CONF.exists():
        return ssids
    try:
        content = WPA_SUPPLICANT_CONF.read_text(errors="ignore")
    except Exception:
        return ssids
    block = False
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("network={"):
            block = True
        elif block and line.startswith("}"):
            block = False
        elif block and line.startswith("ssid="):
            val = line.split("=", 1)[1].strip()
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            if val:
                ssids.add(val.strip())
    return ssids

def get_saved_networks_nmcli():
    if not has_cmd("nmcli"):
        return set()
    ssids = set()
    try:
        cp = subprocess.run(
            ["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=6
        )
        if cp.returncode != 0 or not cp.stdout:
            return ssids
        names = []
        for line in cp.stdout.splitlines():
            if not line:
                continue
            name, _, typ = line.partition(":")
            if typ in ("wifi", "802-11-wireless"):
                names.append(name)
        for name in names:
            ssid = run_cmd(["nmcli", "-s", "-g", "802-11-wireless.ssid", "connection", "show", name], timeout=4)
            if ssid:
                ssids.add(ssid.strip())
    except Exception as e:
        log.debug("get_saved_networks_nmcli error: %s", e)
    return ssids

def scan_nmcli(iface: str):
    _ = run_cmd(["nmcli", "device", "wifi", "rescan", "ifname", iface], timeout=6)
    out = run_cmd(["nmcli", "-t", "--escape", "no", "-f", "SSID,SIGNAL,SECURITY",
                   "device", "wifi", "list", "ifname", iface], timeout=10)
    results = {}
    if not out:
        return results
    for line in out.splitlines():
        if not line:
            continue
        parts = line.split(":")
        if len(parts) < 2:
            continue
        ssid = parts[0].strip()
        if not ssid:
            continue
        try:
            signal = int(parts[1])
        except Exception:
            signal = 0
        security = parts[2] if len(parts) > 2 else ""
        if ssid not in results or signal > results[ssid]["signal"]:
            results[ssid] = {"signal": signal, "security": security}
    return results

def scan_wpa_cli(iface: str):
    _ = run_cmd(["sudo", "wpa_cli", "-i", iface, "scan"], timeout=5)
    results = {}
    for _ in range(4):
        time.sleep(0.8)
        out = run_cmd(["sudo", "wpa_cli", "-i", iface, "scan_results"], timeout=8)
        if not out:
            continue
        lines = out.splitlines()
        for line in lines[1:]:
            parts = line.split("\t")
            if len(parts) >= 5:
                try:
                    level_dbm = int(parts[2])
                except Exception:
                    level_dbm = -90
                flags = parts[3]
                ssid = parts[4].strip()
                if not ssid:
                    continue
                pct = dbm_to_percent(level_dbm)
                sec = flags or ""
                if ssid not in results or pct > results[ssid]["signal"]:
                    results[ssid] = {"signal": pct, "security": sec}
        if results:
            break
    return results

def connect_wpa_cli(iface: str, ssid: str) -> bool:
    out = run_cmd(["sudo", "wpa_cli", "-i", iface, "list_networks"], timeout=6)
    if not out:
        return False
    nid = None
    for line in out.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) >= 2 and parts[1] == ssid:
            nid = parts[0]
            break
    if not nid:
        return False
    _ = run_cmd(["sudo", "wpa_cli", "-i", iface, "select_network", nid], timeout=6)
    _ = run_cmd(["sudo", "wpa_cli", "-i", iface, "enable_network", nid], timeout=6)
    _ = run_cmd(["sudo", "wpa_cli", "-i", iface, "save_config"], timeout=6)
    return True

def connect_nmcli(iface: str, ssid: str) -> bool:
    cp = subprocess.run(["sudo", "nmcli", "device", "wifi", "connect", ssid, "ifname", iface],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=35)
    if cp.returncode != 0:
        log.debug("nmcli connect failed: %s", cp.stderr.strip() if cp.stderr else "")
        return False
    return True

def disconnect_client_wifi(iface: str):
    if has_cmd("nmcli"):
        try:
            subprocess.run(["sudo", "nmcli", "device", "disconnect", iface],
                           check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        except Exception as e:
            log.debug("nmcli device disconnect failed: %s", e)
    else:
        try:
            run_cmd(["sudo", "wpa_cli", "-i", iface, "disconnect"], timeout=5)
            out = run_cmd(["sudo", "wpa_cli", "-i", iface, "list_networks"], timeout=5)
            if out:
                for line in out.splitlines()[1:]:
                    parts = line.split("\t")
                    if parts and parts[0].isdigit():
                        run_cmd(["sudo", "wpa_cli", "-i", iface, "disable_network", parts[0]], timeout=3)
            run_cmd(["sudo", "wpa_cli", "-i", iface, "save_config"], timeout=3)
        except Exception as e:
            log.debug("wpa_cli disconnect failed: %s", e)
    try:
        run_cmd(["sudo", "ip", "addr", "flush", "dev", iface], timeout=5)
    except Exception as e:
        log.debug("ip addr flush failed: %s", e)


# ------------------------------------------------------------
# State object – shared between screens
# ------------------------------------------------------------
class UiState(EventDispatcher):
    net_status = StringProperty("INIT")
    vpn_status = StringProperty("OFF")
    vpn_name = StringProperty("None")
    ap_status = StringProperty("OFF")
    cpu_temp = NumericProperty(0.0)
    geoip = StringProperty("Unknown")
    ap_ssid = StringProperty("N/A")
    ip_address = StringProperty("N/A")
    connected_clients = NumericProperty(0)
    uptime = StringProperty("N/A")
    hostname = StringProperty("N/A")
    client_ssid = StringProperty("N/A")
    host_iface = StringProperty("wlan0")
    ap_iface = StringProperty("wlan1")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._hostapd_cache = {'mtime': 0, 'ssid': None, 'iface': None}
        self._determine_interfaces()

    def _read_hostapd_cached(self):
        try:
            st = HOSTAPD_CONF.stat()
            if st.st_mtime <= self._hostapd_cache['mtime']:
                return self._hostapd_cache['ssid'], self._hostapd_cache['iface']
            ssid, iface = parse_hostapd_conf()
            self._hostapd_cache.update(mtime=st.st_mtime, ssid=ssid, iface=iface)
            return ssid, iface
        except FileNotFoundError:
            return None, None

    def _determine_interfaces(self):
        ssid, ap_interface = self._read_hostapd_cached()
        if ap_interface in ("wlan0", "wlan1"):
            self.ap_iface = ap_interface
            self.host_iface = "wlan1" if ap_interface == "wlan0" else "wlan0"
            log.info("Detected AP Interface: %s, Client Interface: %s", self.ap_iface, self.host_iface)
        else:
            log.warning("Could not determine AP interface from hostapd.conf, using defaults.")

    def collect_snapshot(self):
        snap = {}
        host_ip = self._get_ip(self.host_iface)
        snap['net_status'] = "ON" if host_ip else "OFF"
        snap['client_ssid'] = run_cmd(f"iwgetid {self.host_iface} -r") if snap['net_status'] == "ON" else "Disconnected"
        status = run_cmd(["systemctl", "is-active", "hostapd"])
        snap['ap_status'] = "ON" if status == "active" else "OFF"
        raw = run_cmd(["cat", "/sys/class/thermal/thermal_zone0/temp"])
        if raw:
            snap['cpu_temp'] = int(raw)/1000
        snap['hostname'] = run_cmd(["hostname"]) or "N/A"
        uptime_output = run_cmd(["uptime", "-p"])
        snap['uptime'] = uptime_output.replace("up ", "") if uptime_output else "N/A"
        data = raspap_api(f"clients/{self.ap_iface}")
        if isinstance(data, dict) and "active_clients" in data:
            active = data["active_clients"]
            snap['connected_clients'] = len(active) if isinstance(active, (list, dict)) else 0
        else:
            snap['connected_clients'] = 0
        ssid, _ = self._read_hostapd_cached()
        snap['ap_ssid'] = ssid or "N/A"
        snap['ip_address'] = self._get_ip(self.ap_iface) or "N/A"
        pid = run_cmd(["pgrep", "-x", "openvpn"])
        if pid:
            snap['vpn_status'] = "ON"
            snap['vpn_name'] = self.vpn_name if self.vpn_name != "None" else "ON"
        else:
            snap['vpn_status'] = "OFF"
            snap['vpn_name'] = "None"
        return snap

    def apply_snapshot(self, snap: dict):
        for k, v in snap.items():
            setattr(self, k, v)

    def update_async(self):
        def _work():
            s = self.collect_snapshot()
            Clock.schedule_once(lambda dt: self.apply_snapshot(s), 0)
        threading.Thread(target=_work, daemon=True).start()

    def update_geoip_async(self):
        def _task():
            url = "http://ip-api.com/json/?fields=status,message,country,city"
            r = HTTP.get(url, timeout=5)
            r.raise_for_status()
            data = r.json()
            if data.get('status') == 'success':
                city = data.get('city', 'N/A')
                country = data.get('country', 'N/A')
                return f"{city}, {country}"
            return "API Error"
        def _done(result, err):
            if err:
                log.warning("GeoIP lookup failed: %s", err)
                self.geoip = "Unknown"
            else:
                self.geoip = result
                log.info("GeoIP updated: %s", result)
        run_bg(_task, _done)

    @staticmethod
    def _get_ip(iface):
        out = run_cmd(["ip", "-j", "-4", "addr", "show", iface])
        if not out:
            return None
        try:
            data = json.loads(out)
            if data and isinstance(data, list):
                addr_info = data[0].get('addr_info')
                if addr_info and isinstance(addr_info, list):
                    return addr_info[0].get('local')
        except (json.JSONDecodeError, IndexError, KeyError) as e:
            log.debug("Could not parse IP address from JSON for %s: %s", iface, e)
        return None


STATE = UiState()


# ------------------------------------------------------------
# UI widgets
# ------------------------------------------------------------
class ThemedButton(Button):
    bg_color = ListProperty(THEME.BUTTON_BG_NORMAL)

class NavButton(ThemedButton):
    pass

class HeaderLayout(BoxLayout):
    pass

class VpnButton(ButtonBehavior, BoxLayout):
    pass


# ------------------------------------------------------------
# Screens
# ------------------------------------------------------------
class MainScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        overall_layout = BoxLayout(orientation='vertical', padding=THEME.PADDING, spacing=THEME.SPACING)
        overall_layout.canvas.before.clear()
        from kivy.graphics import Color, Rectangle
        with overall_layout.canvas.before:
            Color(*THEME.BACKGROUND_COLOR)
            self.rect = Rectangle(pos=overall_layout.pos, size=overall_layout.size)
            overall_layout.bind(pos=self.update_rect, size=self.update_rect)

        header_layout = HeaderLayout(orientation='horizontal', size_hint_y=None, height=THEME.BUTTON_HEIGHT + 10, spacing=5, padding=(0, 5))
        logo_image = Image(source=str(ASSETS_DIR / 'raspAP-logo.png'), size_hint_x=0.2, allow_stretch=True, keep_ratio=True)
        title_label = Label(text="[b]RaspAP[/b]", font_size=THEME.FONT_SIZE_TITLE, markup=True, color=THEME.TEXT_COLOR_DARK,
                            halign='center', valign='middle', size_hint_x=0.6)
        title_label.bind(size=title_label.setter('text_size'))
        qr_code_image = Image(source=str(ASSETS_DIR / 'qr.png'), size_hint_x=0.2, allow_stretch=True, keep_ratio=True)
        header_layout.add_widget(logo_image); header_layout.add_widget(title_label); header_layout.add_widget(qr_code_image)
        overall_layout.add_widget(header_layout)

        content_area = BoxLayout(orientation='horizontal', spacing=THEME.SPACING)

        label_col = GridLayout(cols=1, size_hint_x=0.2, spacing=THEME.SPACING)
        value_col = GridLayout(cols=1, size_hint_x=0.55, spacing=THEME.SPACING)
        btn_col = BoxLayout(orientation='vertical', size_hint_x=0.25, spacing=THEME.SPACING)

        labels_left = ["Net:", "VPN:", "Clients:", "CPU°:", "GeoIP:", "Uptime:"]
        self.value_labels = {}
        for text in labels_left:
            key_label = Label(text=text, font_size=THEME.FONT_SIZE_NORMAL, color=THEME.TEXT_COLOR_DARK,
                              halign='left', valign='middle')
            key_label.bind(size=key_label.setter('text_size'))
            label_col.add_widget(key_label)

            value_label = Label(text="...", font_size=THEME.FONT_SIZE_NORMAL, color=THEME.TEXT_COLOR_DARK,
                                halign='left', valign='middle')
            value_label.bind(size=value_label.setter('text_size'))
            self.value_labels[text] = value_label
            value_col.add_widget(value_label)

        # Set initial values to avoid '---'
        self.value_labels["VPN:"].text = "Disconnected"
        self.value_labels["Clients:"].text = "0"

        content_area.add_widget(label_col)
        content_area.add_widget(value_col)

        self.wifi_button = NavButton(text=u"\uf1eb", on_press=self.on_net)
        btn_col.add_widget(self.wifi_button)

        self.vpn_button = NavButton(text=u"\uf3ed", on_press=self.on_vpn)
        btn_col.add_widget(self.vpn_button)

        btn_col.add_widget(NavButton(text=u"\uf011", on_press=self.on_sys))
        btn_col.add_widget(NavButton(text=u"\uf05a", on_press=self.on_info))

        content_area.add_widget(btn_col)
        overall_layout.add_widget(content_area)
        self.add_widget(overall_layout)

        self._bind_state_to_ui()
        # Removed old one-off geoip refresh; app-level triggers handle it

    def _bind_state_to_ui(self):
        def set_value(key, value):
            if key in self.value_labels:
                self.value_labels[key].text = str(value)

        STATE.bind(client_ssid=lambda i, v: set_value("Net:", v))

        def on_vpn_change(*_):
            set_value("VPN:", STATE.vpn_name if STATE.vpn_status == "ON" else "Disconnected")
            self.vpn_button.bg_color = THEME.ACCENT_COLOR if STATE.vpn_status == "ON" else THEME.BUTTON_BG_NORMAL

        STATE.bind(vpn_status=lambda *a: on_vpn_change(), vpn_name=lambda *a: on_vpn_change())
        STATE.bind(connected_clients=lambda i, v: set_value("Clients:", v))
        STATE.bind(cpu_temp=lambda i, v: set_value("CPU°:", f"{v:.1f} °C"))
        STATE.bind(geoip=lambda i, v: set_value("GeoIP:", v))
        STATE.bind(uptime=lambda i, v: set_value("Uptime:", v))

        # Wi-Fi button: green when connected, red when disconnected
        STATE.bind(net_status=lambda i, v: setattr(self.wifi_button, "bg_color", THEME.ACCENT_COLOR if v == "ON" else THEME.BUTTON_BG_OFF))

    def update_rect(self, instance, value):
        self.rect.pos = instance.pos
        self.rect.size = instance.size

    def on_pre_enter(self, *_):
        self._sync_once()

    def _sync_once(self):
        self.wifi_button.bg_color = THEME.ACCENT_COLOR if STATE.net_status == "ON" else THEME.BUTTON_BG_OFF
        self.vpn_button.bg_color = THEME.ACCENT_COLOR if STATE.vpn_status == "ON" else THEME.BUTTON_BG_NORMAL
        self.value_labels["VPN:"].text = STATE.vpn_name if STATE.vpn_status == "ON" else "Disconnected"
        self.value_labels["Clients:"].text = str(getattr(STATE, "connected_clients", 0) or 0)

    def on_net(self, *_):
        self.manager.current = "wifi"

    def on_vpn(self, *_):
        self.manager.current = "vpn"

    def on_sys(self, *_):
        self.manager.current = "sys"

    def on_info(self, *_):
        self.manager.current = "info"


class SystemScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        root = BoxLayout(orientation='vertical', padding=THEME.PADDING, spacing=THEME.SPACING)
        root.canvas.before.clear()
        from kivy.graphics import Color, Rectangle
        with root.canvas.before:
            Color(*THEME.BACKGROUND_COLOR)
            self.rect = Rectangle(pos=root.pos, size=root.size)
            root.bind(pos=self.update_rect, size=self.update_rect)

        title = Label(text="[b]System Control[/b]", font_size=THEME.FONT_SIZE_TITLE, color=THEME.TEXT_COLOR_DARK,
                      size_hint_y=None, height=THEME.BUTTON_HEIGHT * 1.5, markup=True)
        root.add_widget(title)

        center_layout = GridLayout(cols=1, spacing=THEME.SPACING, size_hint_y=1)
        center_layout.add_widget(ThemedButton(text="Reboot", on_release=self.on_reboot))
        center_layout.add_widget(ThemedButton(text="Shutdown", on_release=self.on_shutdown))
        root.add_widget(center_layout)

        back_button_layout = BoxLayout(size_hint_y=None, height=THEME.BUTTON_HEIGHT)
        back_button_layout.add_widget(ThemedButton(text="Back", on_release=lambda *_: setattr(self.manager, 'current', 'main')))
        root.add_widget(back_button_layout)

        self.add_widget(root)

    def update_rect(self, instance, value):
        self.rect.pos = instance.pos
        self.rect.size = instance.size

    def on_reboot(self, *_):
        self._confirm_and_run("REBOOT", "Are you sure?", ["sudo", "systemctl", "reboot"], "Rebooting Pi...")

    def on_shutdown(self, *_):
        self._confirm_and_run("SHUTDOWN", "Are you sure?", ["sudo", "systemctl", "poweroff"], "Shutting down Pi...")

    def _confirm_and_run(self, title, message, cmd, progress_message):
        content = BoxLayout(orientation='vertical', padding=THEME.PADDING, spacing=THEME.SPACING)
        content.add_widget(Label(text=title, font_size=THEME.FONT_SIZE_HEADER, color=THEME.TEXT_COLOR_DARK))
        content.add_widget(Label(text=message, font_size=THEME.FONT_SIZE_NORMAL, color=THEME.TEXT_COLOR_DARK))

        button_layout = BoxLayout(size_hint_y=None, height=THEME.BUTTON_HEIGHT, spacing=THEME.SPACING)
        ok_button = ThemedButton(text="OK")
        cancel_button = ThemedButton(text="CANCEL")
        button_layout.add_widget(ok_button); button_layout.add_widget(cancel_button)
        content.add_widget(button_layout)

        popup = Popup(title='', content=content, size_hint=(0.7, 0.6), auto_dismiss=False,
                      separator_height=0, background_color=THEME.BACKGROUND_COLOR, background='')

        def _do(*args):
            popup.dismiss()
            show_busy_indicator()
            run_bg(lambda: subprocess.run(cmd, check=False))
            Clock.schedule_once(lambda dt: hide_busy_indicator(), 15)

        ok_button.bind(on_release=_do)
        cancel_button.bind(on_release=lambda *_: popup.dismiss())
        popup.open()


class InfoScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        root = BoxLayout(orientation='vertical', padding=THEME.PADDING, spacing=THEME.SPACING)
        root.canvas.before.clear()
        from kivy.graphics import Color, Rectangle
        with root.canvas.before:
            Color(*THEME.BACKGROUND_COLOR)
            self.rect = Rectangle(pos=root.pos, size=root.size)
            root.bind(pos=self.update_rect, size=self.update_rect)

        # 3-column grid: Label | Value | Action (button/blank)
        self.grid = GridLayout(cols=3, spacing=(THEME.SPACING, 2), size_hint_y=None, size_hint_x=1)
        self.grid.bind(minimum_height=self.grid.setter('height'))
        self.grid.row_force_default = True
        self.grid.row_default_height = 28

        self.info_labels = {}
        self.info_key_labels = []
        self.info_value_labels = []
        self.info_action_widgets = []

        self.info_keys_base = [
            "Internet SSID", "Internet IP", "AP Status", "AP SSID",
            "AP IP", "Connected Clients", "Hostname", "Uptime",
            "CPU°", "GeoIP", "VPN Status"
        ]

        # Speed row
        speed_key_label = Label(text="Speed:", font_size=THEME.FONT_SIZE_NORMAL, color=THEME.TEXT_COLOR_DARK,
                                halign='left', valign='middle', size_hint_x=None)
        speed_key_label.bind(size=speed_key_label.setter('text_size'))
        self.speed_value = Label(text="Tap Test", font_size=THEME.FONT_SIZE_NORMAL, color=THEME.TEXT_COLOR_DARK,
                                 halign='left', valign='middle', size_hint_x=None)
        self.speed_value.bind(size=self.speed_value.setter('text_size'))

        self.speed_btn = ThemedButton(text="Test", size_hint_x=None)
        self.speed_btn.bind(on_release=self.run_speed_test)

        self.grid.add_widget(speed_key_label)
        self.grid.add_widget(self.speed_value)
        self.grid.add_widget(self.speed_btn)

        self.info_key_labels.append(speed_key_label)
        self.info_value_labels.append(self.speed_value)
        self.info_action_widgets.append(self.speed_btn)

        # Base rows
        for key in self.info_keys_base:
            key_label = Label(text=f"{key}:", font_size=THEME.FONT_SIZE_NORMAL, color=THEME.TEXT_COLOR_DARK,
                              halign='left', valign='middle', size_hint_x=None)
            value_label = Label(text="...", font_size=THEME.FONT_SIZE_NORMAL, color=THEME.TEXT_COLOR_DARK,
                                halign='left', valign='middle', size_hint_x=None)
            key_label.bind(size=key_label.setter('text_size'))
            value_label.bind(size=value_label.setter('text_size'))

            self.grid.add_widget(key_label)
            self.grid.add_widget(value_label)
            placeholder = Label(text="", size_hint_x=None)
            self.grid.add_widget(placeholder)

            self.info_key_labels.append(key_label)
            self.info_value_labels.append(value_label)
            self.info_action_widgets.append(placeholder)

            self.info_labels[key] = value_label

        bar_inactive = (THEME.BUTTON_BG_PRESSED[0], THEME.BUTTON_BG_PRESSED[1], THEME.BUTTON_BG_PRESSED[2], 0.3)
        self.scroll_view = ScrollView(size_hint=(1, 1), do_scroll_x=False, do_scroll_y=True,
                                      scroll_type=['bars', 'content'], bar_width=6,
                                      bar_color=THEME.BUTTON_BG_PRESSED, bar_inactive_color=bar_inactive)
        self.scroll_view.add_widget(self.grid)
        root.add_widget(self.scroll_view)

        back_button_layout = BoxLayout(size_hint_y=None, height=THEME.BUTTON_HEIGHT)
        back_button_layout.add_widget(ThemedButton(text="Back", on_release=lambda *_: setattr(self.manager, 'current', 'main')))
        root.add_widget(back_button_layout)

        self.add_widget(root)

        self.scroll_view.bind(width=lambda *_: self._update_info_col_widths())
        self.grid.bind(width=lambda *_: self._update_info_col_widths())
        Clock.schedule_once(lambda dt: self._update_info_col_widths(), 0)

        self._refresh_ev = None
        self._speedtest_running = False

    def _update_info_col_widths(self):
        total = max(1, self.grid.width)
        spacing_total = self.grid.spacing[0] * 2 if isinstance(self.grid.spacing, (list, tuple)) else self.grid.spacing
        action_w = max(70, int(total * 0.10))
        left_w = max(160, int(total * 0.50))
        right_w = max(120, total - left_w - action_w - spacing_total)

        for lbl in self.info_key_labels:
            lbl.size_hint_x = None
            lbl.width = left_w
        for lbl in self.info_value_labels:
            lbl.size_hint_x = None
            lbl.width = right_w
        for w in self.info_action_widgets:
            w.size_hint_x = None
            try:
                w.width = action_w
            except Exception:
                pass

    def on_pre_enter(self, *_):
        self._refresh_ev = Clock.schedule_interval(lambda dt: self.refresh(), CONFIG.get("update_interval", 2))
        self.refresh()

    def on_leave(self, *_):
        if self._refresh_ev:
            self._refresh_ev.cancel()
            self._refresh_ev = None

    def update_rect(self, instance, value):
        self.rect.pos = instance.pos
        self.rect.size = instance.size

    def refresh(self):
        ip_host = STATE._get_ip(STATE.host_iface) or "N/A"
        info_data = {
            "AP Status": STATE.ap_status,
            "AP SSID": STATE.ap_ssid,
            "AP IP": STATE.ip_address,
            "Connected Clients": str(STATE.connected_clients),
            "Hostname": STATE.hostname,
            "Uptime": STATE.uptime,
            "CPU°": f"{STATE.cpu_temp:.1f} °C",
            "GeoIP": STATE.geoip,
            "VPN Status": STATE.vpn_name if STATE.vpn_status == 'ON' else "OFF",
            "Internet SSID": STATE.client_ssid,
            "Internet IP": ip_host,
        }
        for key, label in self.info_labels.items():
            label.text = str(info_data.get(key, "N/A"))

    def run_speed_test(self, *_):
        if self._speedtest_running:
            show_message("Speed Test", "A test is already running.")
            return

        host_iface = STATE.host_iface
        host_ip = STATE._get_ip(host_iface)
        if not host_ip:
            show_message("Speed Test", f"Client Wi‑Fi ({host_iface}) is offline.", is_error=True)
            self.speed_value.text = "No Wi‑Fi"
            return

        self._speedtest_running = True
        self.speed_btn.disabled = True
        self.speed_value.text = f"Testing on {host_iface}..."
        show_busy_indicator()

        def _task():
            # 1) Python module
            try:
                import speedtest as speedtest_mod
                st = speedtest_mod.Speedtest(source_address=host_ip)
                st.get_servers()
                st.get_best_server()
                down_bps = st.download()
                up_bps = st.upload(pre_allocate=False)
                ping_ms = getattr(st.results, 'ping', None)
                if ping_ms is None:
                    try:
                        ping_ms = st.results.dict().get('ping')
                    except Exception:
                        pass
                return {"down_bps": down_bps, "up_bps": up_bps, "ping_ms": ping_ms, "src": "py", "iface": host_iface}
            except Exception as e_py:
                log.debug("Python speedtest module failed: %s", e_py)

            # 2) Ookla CLI
            try:
                cp = subprocess.run(
                    ["speedtest", "--accept-license", "--accept-gdpr", "--ip-protocol=ipv4", "-f", "json", "--interface", host_iface],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120
                )
                if cp.returncode == 0 and cp.stdout:
                    data = json.loads(cp.stdout)
                    down_bps = data.get("download", {}).get("bandwidth")
                    up_bps = data.get("upload", {}).get("bandwidth")
                    ping_ms = data.get("ping", {}).get("latency")
                    if down_bps is not None: down_bps *= 8
                    if up_bps is not None: up_bps *= 8
                    return {"down_bps": down_bps, "up_bps": up_bps, "ping_ms": ping_ms, "src": "ookla", "iface": host_iface}
                else:
                    log.debug("Ookla CLI failed rc=%s err=%s", cp.returncode, (cp.stderr or "").strip())
            except Exception as e_ook:
                log.debug("Ookla CLI speedtest failed: %s", e_ook)

            # 3) speedtest-cli
            try:
                cp = subprocess.run(
                    ["speedtest-cli", "--json", "--source", host_ip],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120
                )
                if cp.returncode == 0 and cp.stdout:
                    data = json.loads(cp.stdout)
                    return {
                        "down_bps": data.get("download"),
                        "up_bps": data.get("upload"),
                        "ping_ms": data.get("ping"),
                        "src": "cli",
                        "iface": host_iface
                    }
                else:
                    log.debug("speedtest-cli failed rc=%s err=%s", cp.returncode, (cp.stderr or "").strip())
            except Exception as e_cli:
                log.debug("speedtest-cli failed: %s", e_cli)

            raise RuntimeError(f"No speedtest backend available or network/DNS issue on {host_iface}")

        def _done(result, err):
            hide_busy_indicator()
            self._speedtest_running = False
            self.speed_btn.disabled = False
            if err:
                show_message("Speed Test", str(err), is_error=True, position='center')
                self.speed_value.text = "Failed"
                return
            def fmt_pair(down_bps, up_bps):
                return f"{(down_bps or 0)/1e6:.2f}↓ / {(up_bps or 0)/1e6:.2f}↑ Mbps"
            ping = f"{result.get('ping_ms', 0):.0f} ms" if result.get('ping_ms') is not None else "N/A"
            self.speed_value.text = f"[{result.get('iface','?')}/{result.get('src','?')}] {ping}, {fmt_pair(result.get('down_bps'), result.get('up_bps'))}"

        run_bg(_task, _done)


class WifiScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self._connecting = False
        self._auto_jobs = []

        root = BoxLayout(orientation='vertical', padding=THEME.PADDING, spacing=THEME.SPACING)
        root.canvas.before.clear()
        from kivy.graphics import Color, Rectangle
        with root.canvas.before:
            Color(*THEME.BACKGROUND_COLOR)
            self.rect = Rectangle(pos=root.pos, size=root.size)
            root.bind(pos=self.update_rect, size=self.update_rect)

        title = Label(text="[b]Wi‑Fi Networks[/b]", markup=True, font_size=THEME.FONT_SIZE_TITLE,
                      color=THEME.TEXT_COLOR_DARK, size_hint_y=None, height=THEME.BUTTON_HEIGHT * 1.1)
        root.add_widget(title)

        toolbar = BoxLayout(orientation='horizontal', size_hint_y=None, height=THEME.BUTTON_HEIGHT, spacing=THEME.SPACING)
        self.current_lbl = Label(text="Current: —", font_size=THEME.FONT_SIZE_NORMAL, color=THEME.TEXT_COLOR_DARK,
                                 halign='left', valign='middle')
        self.current_lbl.bind(size=self.current_lbl.setter('text_size'))
        toolbar.add_widget(self.current_lbl)

        refresh_btn = ThemedButton(text="Refresh", on_release=lambda *_: self.refresh_networks())
        refresh_btn.size_hint_x = None
        refresh_btn.width = 110
        toolbar.add_widget(refresh_btn)

        disconnect_btn = ThemedButton(text="Disconnect", on_release=self.on_disconnect)
        disconnect_btn.size_hint_x = None
        disconnect_btn.width = 130
        toolbar.add_widget(disconnect_btn)

        root.add_widget(toolbar)

        self.list_grid = GridLayout(cols=1, spacing=4, size_hint_y=None)
        self.list_grid.bind(minimum_height=self.list_grid.setter('height'))
        self.list_grid.row_force_default = True
        self.list_grid.row_default_height = 40

        scroll = ScrollView(size_hint=(1, 1), do_scroll_x=False, do_scroll_y=True,
                            scroll_type=['bars', 'content'], bar_width=6)
        scroll.add_widget(self.list_grid)
        root.add_widget(scroll)

        back_bar = BoxLayout(size_hint_y=None, height=THEME.BUTTON_HEIGHT)
        back_bar.add_widget(ThemedButton(text="Back", on_release=lambda *_: setattr(self.manager, 'current', 'main')))
        root.add_widget(back_bar)

        self.add_widget(root)

        STATE.bind(client_ssid=self._update_current_ssid)
        self._update_current_ssid(STATE, STATE.client_ssid)

    def on_enter(self, *_):
        self.refresh_networks()
        self._schedule_auto_refresh(1.5)
        self._schedule_auto_refresh(3.0)

    def on_leave(self, *_):
        for ev in self._auto_jobs:
            try:
                ev.cancel()
            except Exception:
                pass
        self._auto_jobs.clear()

    def _schedule_auto_refresh(self, delay):
        ev = Clock.schedule_once(lambda dt: self.refresh_networks(), delay)
        self._auto_jobs.append(ev)

    def update_rect(self, instance, value):
        self.rect.pos = instance.pos
        self.rect.size = instance.size

    def _update_current_ssid(self, instance, ssid):
        self.current_lbl.text = f"Current: {ssid or '—'}"

    def _add_info_row(self, text):
        lbl = Label(text=text, font_size=THEME.FONT_SIZE_NORMAL, color=THEME.TEXT_COLOR_DARK,
                    halign='left', valign='middle', size_hint_y=None, height=34)
        lbl.bind(size=lbl.setter('text_size'))
        self.list_grid.add_widget(lbl)

    def on_disconnect(self, *_):
        if self._connecting:
            return
        show_busy_indicator()
        def _task():
            disconnect_client_wifi(STATE.host_iface)
            time.sleep(0.5)
            return True
        def _done(result, err):
            hide_busy_indicator()
            if err:
                show_message("Wi‑Fi", "Failed to disconnect", is_error=True)
            else:
                STATE.update_async()
                if self.manager:
                    self.manager.current = "main"
        run_bg(_task, _done)

    def refresh_networks(self):
        if self._connecting:
            return
        self.list_grid.clear_widgets()
        self._add_info_row("Scanning saved networks in range...")
        show_busy_indicator()

        iface = STATE.host_iface
        current_ssid = (STATE.client_ssid or "").strip()

        def _task():
            saved_wpa, _ssid_to_id = get_saved_networks_wpa_cli(iface)
            saved_nm = get_saved_networks_nmcli()
            saved = {s.strip() for s in saved_wpa} | {s.strip() for s in saved_nm}
            nm = scan_nmcli(iface) if has_cmd("nmcli") else {}
            wp = scan_wpa_cli(iface)
            merged = {}
            for src in (nm, wp):
                for ssid, info in src.items():
                    if ssid not in merged or info["signal"] > merged[ssid]["signal"]:
                        merged[ssid] = info
            in_range = []
            for ssid, info in merged.items():
                s = ssid.strip() if ssid else ""
                if s and s in saved:
                    in_range.append({
                        "ssid": s,
                        "signal": info.get("signal", 0),
                        "security": info.get("security", ""),
                        "current": (s == current_ssid)
                    })
            # Sort: current first, then by descending signal
            in_range.sort(key=lambda x: (x["current"] is False, -x["signal"]))
            # Determine saved-but-out-of-range
            in_range_names = {x["ssid"] for x in in_range}
            out_of_range = sorted(list((saved - in_range_names) - ({current_ssid} if current_ssid else set())))
            return {"in_range": in_range, "out_of_range": out_of_range}

        def _done(result, err):
            hide_busy_indicator()
            self.list_grid.clear_widgets()
            if err or not result:
                self._add_info_row(f"Scan failed: {err}" if err else "No saved networks found.")
                return
            in_range = result["in_range"]
            out_of_range = result["out_of_range"]

            if not in_range and not out_of_range:
                self._add_info_row("No saved networks found in range.")
            else:
                # Show in-range networks (current at top, disabled)
                for item in in_range:
                    ssid = item["ssid"]
                    sig = item["signal"]
                    sec = item["security"] or ""
                    secure = any(k in sec for k in ("WPA", "WEP", "SAE"))
                    fa_icon = "\uf023" if secure else "\uf09c"
                    label_text = f"{ssid}   {sig}% [font={FA_FONT_FILE}]{fa_icon}[/font]"
                    btn = ThemedButton(text=label_text)
                    if item["current"]:
                        btn.disabled = True
                        btn.bg_color = THEME.ACCENT_COLOR
                    else:
                        btn.bind(on_release=partial(self._connect_to, ssid))
                    self.list_grid.add_widget(btn)

                # Show saved out-of-range section if any
                if out_of_range:
                    self._add_info_row("Saved (out of range):")
                    for ssid in out_of_range:
                        btn = ThemedButton(text=f"{ssid}   out of range")
                        btn.disabled = True
                        btn.bg_color = THEME.BUTTON_BG_PRESSED
                        self.list_grid.add_widget(btn)

        run_bg(_task, _done)

    def _connect_to(self, ssid, *_):
        if self._connecting:
            return
        self._connecting = True
        show_busy_indicator()
        iface = STATE.host_iface
        def _task():
            ok = connect_wpa_cli(iface, ssid)
            if not ok and has_cmd("nmcli"):
                ok = connect_nmcli(iface, ssid)
            if not ok:
                raise RuntimeError("Failed to connect")
            time.sleep(1.0)
            return True
        def _done(result, err):
            hide_busy_indicator()
            self._connecting = False
            if err:
                show_message("Wi‑Fi", f"Failed to connect to:\n{ssid}", is_error=True)
            else:
                STATE.update_async()
                Clock.schedule_once(lambda dt: STATE.update_geoip_async(), 1)
                if self.manager:
                    self.manager.current = "main"
        run_bg(_task, _done)


class VpnScreen(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.vpn_button_grid = None
        root = BoxLayout(orientation='vertical', padding=THEME.PADDING, spacing=THEME.SPACING)
        root.canvas.before.clear()
        from kivy.graphics import Color, Rectangle
        with root.canvas.before:
            Color(*THEME.BACKGROUND_COLOR)
            self.rect = Rectangle(pos=root.pos, size=root.size)
            root.bind(pos=self.update_rect, size=self.update_rect)

        root.add_widget(Label(text="[b]VPN Control[/b]", font_size=THEME.FONT_SIZE_TITLE, color=THEME.TEXT_COLOR_DARK, size_hint_y=None, height=40, markup=True))

        content_area = BoxLayout(orientation='horizontal', spacing=THEME.SPACING)
        self.vpn_button_grid = GridLayout(cols=1, spacing=THEME.SPACING, size_hint_x=0.66)
        content_area.add_widget(self.vpn_button_grid)

        control_button_layout = BoxLayout(orientation='vertical', spacing=THEME.SPACING, size_hint_x=0.34)
        control_button_layout.add_widget(ThemedButton(text="Disconnect", on_release=self.disconnect_vpn))
        control_button_layout.add_widget(ThemedButton(text="Back", on_release=lambda *_: setattr(self.manager, 'current', 'main')))
        content_area.add_widget(control_button_layout)

        root.add_widget(content_area)
        self.add_widget(root)

        self.bind(on_enter=self.populate_vpn_buttons)
        STATE.bind(vpn_status=self._on_state_change, vpn_name=self._on_state_change)

    def _on_state_change(self, *args):
        self.populate_vpn_buttons()

    def update_rect(self, instance, value):
        self.rect.pos = instance.pos
        self.rect.size = instance.size

    def populate_vpn_buttons(self, *args):
        self.vpn_button_grid.clear_widgets()
        vpn_configs = CONFIG.get("vpn_profiles", [])
        if not vpn_configs:
            self.vpn_button_grid.add_widget(Label(text="No VPN profiles in config.json.", color=THEME.TEXT_COLOR_DARK))
            return
        for config in vpn_configs:
            display_name = config.get("display_name", "Unnamed")
            vpn_file = config.get("file")
            if not vpn_file:
                continue
            button = ThemedButton(text=display_name)
            if STATE.vpn_status == "ON" and STATE.vpn_name == display_name:
                button.bg_color = THEME.ACCENT_COLOR
            else:
                button.bg_color = THEME.BUTTON_BG_NORMAL
            button.bind(on_release=partial(self.toggle_vpn, vpn_file, display_name))
            self.vpn_button_grid.add_widget(button)

    def toggle_vpn(self, vpn_file, display_name, *args):
        show_busy_indicator()
        def _task():
            run_cmd(["sudo", "killall", "openvpn"])
            config_path = OVPN_DIR / vpn_file
            if not config_path.exists():
                raise FileNotFoundError(str(config_path))
            # No shell: pass argv list to avoid quoting issues
            run_cmd(["sudo", "openvpn", "--daemon", "--config", str(config_path)])
            return True
        def _done(result, err):
            hide_busy_indicator()
            if err:
                show_message("Error", f"Failed to start VPN:\n{vpn_file}", is_error=True)
            else:
                STATE.vpn_name = display_name
                STATE.vpn_status = "ON"
                STATE.update_geoip_async()
                if self.manager:
                    self.manager.current = "main"
        run_bg(_task, _done)

    def disconnect_vpn(self, *args):
        show_busy_indicator()
        def _task():
            run_cmd(["sudo", "killall", "openvpn"])
            return True
        def _done(result, err):
            hide_busy_indicator()
            STATE.vpn_name = "None"
            STATE.vpn_status = "OFF"
            self.populate_vpn_buttons()
            Clock.schedule_once(lambda dt: self.finish_vpn_action(), 0.8)
        run_bg(_task, _done)

    def finish_vpn_action(self):
        STATE.update_async()
        STATE.update_geoip_async()


# ------------------------------------------------------------
# App and poller
# ------------------------------------------------------------
class StatePoller:
    def __init__(self, interval_sec, state: UiState):
        self.interval = max(1, int(interval_sec))
        self.state = state
        self._event = None

    def start(self):
        if self._event:
            return
        self._event = Clock.schedule_interval(lambda dt: self.state.update_async(), self.interval)

    def stop(self):
        if self._event:
            self._event.cancel()
            self._event = None


class RaspApTouchApp(App):
    def build(self):
        self.theme = THEME
        kv_string = """
<ThemedButton>:
    markup: True
    background_normal: ''
    background_down: ''
    background_color: 0,0,0,0
    font_size: app.theme.FONT_SIZE_NORMAL
    color: app.theme.TEXT_COLOR_LIGHT
    size_hint: (1, 1)
    text_size: self.size
    halign: 'center'
    valign: 'middle'
    padding: 0, 0
    disabled_color: self.color[:3] + [0.3]

    canvas.before:
        Color:
            rgba: self.bg_color if self.state == 'normal' else app.theme.BUTTON_BG_PRESSED
        RoundedRectangle:
            size: self.size
            pos: self.pos
            radius: [app.theme.PADDING/2,]

<HeaderLayout>:
    canvas.after:
        Color:
            rgba: app.theme.TEXT_COLOR_DARK
        Rectangle:
            pos: self.x, self.y
            size: self.width, 2

<NavButton>:
    size_hint_y: 0.25
    font_name: "FontAwesome"

<VpnButton>:
    canvas.before:
        Color:
            rgba: (0.8, 0.8, 0.8, 1) if self.state == 'down' else (0,0,0,0)
        Rectangle:
            pos: self.pos
            size: self.size
"""
        Builder.load_string(kv_string)

        sm = ScreenManager(transition=FadeTransition())
        sm.add_widget(MainScreen(name='main'))
        sm.add_widget(WifiScreen(name='wifi'))
        sm.add_widget(VpnScreen(name='vpn'))
        sm.add_widget(SystemScreen(name='sys'))
        sm.add_widget(InfoScreen(name='info'))
        sm.current = CONFIG.get("default_screen", "main")
        self.sm = sm

        # Paint black on OS/WM close request as well
        Window.bind(on_request_close=self._before_close)

        # GeoIP triggers: debounce + periodic
        self._geoip_pending = None
        self._geoip_periodic_ev = None
        self._bind_geoip_triggers()

        return sm

    def _bind_geoip_triggers(self):
        # Debounced trigger whenever net/VPN state changes
        def _trig(*args):
            self._trigger_geoip_soon(0.5)
        STATE.bind(
            net_status=_trig,   # ON/OFF change
            client_ssid=_trig,  # SSID change
            vpn_status=_trig,   # VPN ON/OFF
            vpn_name=_trig      # VPN profile change
        )

    def _trigger_geoip_soon(self, delay=0.75):
        # Debounce to avoid bursts
        try:
            if self._geoip_pending:
                self._geoip_pending.cancel()
        except Exception:
            pass
        self._geoip_pending = Clock.schedule_once(lambda dt: STATE.update_geoip_async(), delay)

    def _before_close(self, *args):
        try:
            paint_black_now()
        except Exception:
            pass
        return False  # allow closing

    def on_start(self):
        # Start normal polling
        self.poller = StatePoller(CONFIG.get("update_interval", 2), STATE)
        self.poller.start()
        STATE.update_async()

        # GeoIP: immediate, then periodic
        STATE.update_geoip_async()
        self._geoip_periodic_ev = Clock.schedule_interval(
            lambda dt: STATE.update_geoip_async(),
            CONFIG.get("geoip_interval", 300)
        )

    def on_stop(self):
        # Cancel periodic/debounce timers
        try:
            if self._geoip_periodic_ev:
                self._geoip_periodic_ev.cancel()
                self._geoip_periodic_ev = None
            if self._geoip_pending:
                self._geoip_pending.cancel()
                self._geoip_pending = None
        except Exception:
            pass

        try:
            paint_black_now()
        except Exception:
            pass
        try:
            HTTP.close()
        except Exception:
            pass


if __name__ == '__main__':
    RaspApTouchApp().run()
