import os
import re
import sys
import math
import time
import json
import datetime
import psutil
import subprocess
import threading
import socket
import urllib.request
from io import BytesIO
from collections import deque
from urllib.parse import urlparse
from PIL import Image, ImageDraw, ImageFont, ImageEnhance
from StreamDeck.DeviceManager import DeviceManager
from StreamDeck.ImageHelpers import PILHelper

try:
    from pynput.keyboard import Controller, Key
    keyboard = Controller()
    KB_DISPONIBLE = True
except Exception as e:
    print(f"[WARN] pynput no disponible: {e}")
    KB_DISPONIBLE = False
    Key = None

# --- CONFIGURACIÓN ---
FONT_PATH    = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
DECK_SERIAL  = os.environ.get("STREAMDEB_DECK_SERIAL", "").strip()
DUMMY_MODE   = "--dummy" in sys.argv
PREVIEW_DIR  = os.environ.get("STREAMDEB_PREVIEW_DIR", "/tmp/streamdeb-preview")
POLL_HZ      = int(os.environ.get("STREAMDEB_POLL_HZ", "30"))
CICLO_UPTIME = 14400
BRILLO_MIN   = 10           # mínimo (no apaga del todo)
BRILLO_MAX   = 100
BRILLO_PASO  = 10
TIEMPO_PASO            = 60    # 1 min para los +/- de tiempos en config
TIEMPO_FALLBACK_MIN    = 60
TIEMPO_FALLBACK_MAX    = 1800  # 30 min
TIEMPO_DIM_MIN         = 60
TIEMPO_DIM_MAX         = 7200  # 2 h
ROOT_TEXT    = "REDACTED"
API_HOST     = "http://192.168.18.10"   # IP del ESP32 Base — editar según red
API_USER     = "StreamDeck"
API_IP       = urlparse(API_HOST).hostname or "192.168.18.10"

# --- Estado Global ---
ultimo_toque    = time.time()
modo_dim_activo = False
_despertar      = False
max_visto_down  = 1024.0
max_visto_up    = 1024.0
mute_activo     = False
volumen_actual  = 0
net_info = {"ip_pub": "---", "ip_loc": "---", "ping_gw": 0.0, "ping_dns1": 0.0, "ping_dns2": 0.0, "ping_api": 0.0}
PING_HIST_LEN = 60   # ventana móvil ~5 min a 5s/sample
ping_history = {k: deque(maxlen=PING_HIST_LEN) for k in ("ping_gw", "ping_dns1", "ping_dns2", "ping_api")}
api_info = {
    "online": False, "estado": "---", "cuenta": "---", "modo": 0, "modoNombre": "---",
    "contador": 0, "wifiSignal": 0, "tankOnline": False, "tankSignal": 0,
    "usuario": "---", "adminLocked": False,
    "segundos": 0, "initial_seconds": 0,
}

# --- Pomodoro ---
POMODORO_FOCUS_S = 25 * 60    # 25 min de foco
POMODORO_BREAK_S = 5  * 60    # 5 min de descanso
pomodoro_state   = "idle"     # idle | running | break
pomodoro_phase_t = 0.0        # epoch en que arrancó la fase actual

# --- Docker ---
docker_info = {"available": False, "running": 0, "containers": []}  # lista de (name, status_running_bool, image)

# --- Clima Arequipa (Open-Meteo) ---
CLIMA_LAT, CLIMA_LON = -16.4090, -71.5375  # Arequipa, Perú
clima_info = {
    "online": False, "temp": None, "temp_min": None, "temp_max": None,
    "humedad": None, "viento": None, "weather_code": None, "ts": 0,
    "hourly": [],   # lista de dicts: {hora, temp, code, precip}
}
pagina_actual = 1     # 1=sistema · 2=API · 3=multimedia · 4=apps · 5=configuración
forzar_redraw = False
brillo_actual    = 75
tiempo_fallback  = 300    # s sin interacción en otra pág. → vuelve a SIS
tiempo_dim       = 1800   # s sin interacción → atenúa el deck
perfil_visual    = 1      # 1 = con marcos · 2 = sin marco externo
PERFILES_TOTAL   = 2
banner_enabled   = False  # Si True, la auto-fallback va a página IDLE/BANNER (9) en vez de SIS


# --- Helpers ---

def _env_sesion():
    uid = os.getuid()
    env = os.environ.copy()
    env.setdefault('XDG_RUNTIME_DIR',         f'/run/user/{uid}')
    env.setdefault('DBUS_SESSION_BUS_ADDRESS', f'unix:path=/run/user/{uid}/bus')
    env.setdefault('DISPLAY', ':0')
    return env

def _run(cmd):
    res = subprocess.run(cmd, shell=True, env=_env_sesion(), capture_output=True, text=True)
    if res.returncode != 0:
        print(f"[ERR] '{cmd}' → {res.stderr.strip()}", flush=True)

def _lanzar(cmd):
    """Lanza una app fire-and-forget desplegada del dashboard."""
    try:
        subprocess.Popen(cmd, shell=True, env=_env_sesion(), start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[LAUNCH] {cmd}", flush=True)
    except Exception as e:
        print(f"[ERR LAUNCH] {cmd}: {e}", flush=True)


# --- Lanzador de apps (página 4) ---

APPS_PAGINA = {
    # tecla: (categoría, app, comando, color, icono)
    8:  ("Dev",   "Term",    "mate-terminal --working-directory=/home/jfqp",  "#33ccff", "utilities-terminal"),
    9:  ("Dev",   "Arduino", "flatpak run cc.arduino.IDE2",                  "#33ccff", "cc.arduino.IDE2"),
    10: ("Dev",   "GitHub",  "flatpak run io.github.shiftey.Desktop",        "#33ccff", "io.github.shiftey.Desktop"),
    11: ("Web",   "Brave",   "/usr/bin/brave-browser-stable",                "#ff9933", "brave-browser"),
    12: ("Web",   "Firefox", "firejail --netfilter --novideo --nodbus --whitelist=~/Descargas /usr/lib/firefox-esr/firefox-esr --no-remote", "#ff9933", "firefox-esr"),
    16: ("3D",    "Prusa",   "flatpak run com.prusa3d.PrusaSlicer",          "#cc66ff", "com.prusa3d.PrusaSlicer"),
    17: ("Media", "OBS",     "obs",                                          "#ff66cc", "com.obsproject.Studio"),
    18: ("Media", "VLC",     "/usr/bin/vlc",                                 "#ff66cc", "vlc"),
    19: ("Sec",   "Burp",    "/opt/BurpSuiteCommunity/BurpSuiteCommunity",   "#ff3333", "/opt/BurpSuiteCommunity/.install4j/BurpSuiteCommunity.png"),
    20: ("Net",   "Winbox",  "wine /home/jfqp/Downloads/winbox.exe",         "#ffcc33", None),
    24: ("Util",  "AnyDesk", "flatpak run com.anydesk.Anydesk",              "#aaaaaa", "com.anydesk.Anydesk"),
    25: ("Util",  "RustDesk","rustdesk",                                     "#aaaaaa", "rustdesk"),
    29: ("Util",  "SysMon",  "mate-system-monitor",                          "#aaaaaa", "utilities-system-monitor"),
    30: ("Util",  "VBox",    "VirtualBox",                                   "#aaaaaa", "virtualbox"),
    26: ("Util",  "Pluma",   "pluma",                                        "#aaaaaa", "accessories-text-editor"),
    27: ("Util",  "Calc",    "mate-calc",                                    "#aaaaaa", "accessories-calculator"),
}


# --- Página WEB (5) — accesos rápidos a URLs ---
# Agrupado por tipo de contenido (un color por grupo).
# Mail/Msg #ea4335 · AI #ab47bc · Dev #cccccc · Video #ff6f00 ·
# 3D #00bcd4 · Net #66bb6a · News #ffc107 · Empresa #26c6da
# tecla: (label, sub, url, color)
WEB_PAGINA = {
    # Fila 1: Mail/Msg · AI · Dev · Video
    8:  ("Gmail",    "google",     "https://mail.google.com",                     "#ea4335"),
    9:  ("Proton",   "mail",       "https://mail.proton.me",                      "#ea4335"),
    10: ("WhatsApp", "web",        "https://web.whatsapp.com",                    "#ea4335"),
    11: ("Claude",   "ai",         "https://claude.ai",                           "#ab47bc"),
    12: ("Gemini",   "google",     "https://gemini.google.com",                   "#ab47bc"),
    13: ("GitHub",   "code",       "https://github.com",                          "#cccccc"),
    14: ("YouTube",  "video",      "https://youtube.com",                         "#ff6f00"),
    # Fila 2: 3D · Net
    16: ("Tinker",   "cad",        "https://tinkercad.com",                       "#00bcd4"),
    17: ("Thingi",   "verse",      "https://thingiverse.com",                     "#00bcd4"),
    18: ("MyIP",     "publico",    "https://whatismyipaddress.com",               "#66bb6a"),
    19: ("Cloudfl.", "dash",       "https://dash.cloudflare.com",                 "#66bb6a"),
    20: ("AWA",      "admin",      "http://192.168.18.10/admin",                  "#66bb6a"),
    # Fila 3: News + Empresa
    24: ("Repúb.",   "lica",       "https://larepublica.pe",                      "#ffc107"),
    25: ("El Com.",  "ercio",      "https://elcomercio.pe",                       "#ffc107"),
    26: ("Gestión",  "diario",     "https://gestion.pe",                          "#ffc107"),
    27: ("Agentica", "Holotech",   "https://agentica.holotech.pe/HOL/inbox/all",  "#26c6da"),
    28: ("Growatt",  "server",     "https://server.growatt.com/login?lang=en",    "#26c6da"),
}

# Overrides de icono. Si el valor empieza con http(s) se descarga; si es ruta
# absoluta se usa directamente (para sites locales o iconos de sistema).
WEB_ICON_OVERRIDE = {
    "https://github.com":              "https://github.githubassets.com/favicons/favicon-dark.png",
    "https://claude.ai":               "https://api.iconify.design/simple-icons:claude.svg?color=%23d97757",
    "http://192.168.18.10/admin":      "/usr/share/icons/mate/48x48/categories/preferences-system-network.png",
}


# --- Página KEYS (6) — atajos de teclado ---
# tecla: (label, combo_str, [pynput keys])
def _kp(*keys):
    return list(keys)

# --- Página VENT (8) — tiling de ventanas vía wmctrl (mismas coords que ~/.xbindkeysrc) ---
# pynput inyecta eventos sintéticos que xbindkeys ignora (XGrabKey no atrapa XTest),
# así que llamamos wmctrl directamente.
# tecla → (label, x_ini, x_fin, y_ini, y_fin, geometría wmctrl "x,y,w,h")
# Fila 2 (8..12)  = altura completa (h=1168, y=27)
# Fila 3 (16..20) = mitad superior (h=584,  y=27)
# Fila 4 (24..28) = mitad inferior (h=584,  y=611)
VENT_PAGINA = {
    # Fila 2 — altura completa
    8:  ("Izq",    0.00, 1/3,  0.0, 1.0, "0,0,27,1276,1168"),
    9:  ("Centro", 1/3,  2/3,  0.0, 1.0, "0,1282,27,1276,1168"),
    10: ("Der",    2/3,  1.00, 0.0, 1.0, "0,2564,27,1276,1168"),
    11: ("M.Izq",  0.00, 0.50, 0.0, 1.0, "0,0,27,1917,1168"),
    12: ("M.Der",  0.50, 1.00, 0.0, 1.0, "0,1923,27,1917,1168"),
    # Fila 3 — mitad superior
    16: ("Izq↑",   0.00, 1/3,  0.0, 0.5, "0,0,27,1276,584"),
    17: ("Cen↑",   1/3,  2/3,  0.0, 0.5, "0,1282,27,1276,584"),
    18: ("Der↑",   2/3,  1.00, 0.0, 0.5, "0,2564,27,1276,584"),
    19: ("MI↑",    0.00, 0.50, 0.0, 0.5, "0,0,27,1917,584"),
    20: ("MD↑",    0.50, 1.00, 0.0, 0.5, "0,1923,27,1917,584"),
    # Fila 4 — mitad inferior
    24: ("Izq↓",   0.00, 1/3,  0.5, 1.0, "0,0,611,1276,584"),
    25: ("Cen↓",   1/3,  2/3,  0.5, 1.0, "0,1282,611,1276,584"),
    26: ("Der↓",   2/3,  1.00, 0.5, 1.0, "0,2564,611,1276,584"),
    27: ("MI↓",    0.00, 0.50, 0.5, 1.0, "0,0,611,1917,584"),
    28: ("MD↓",    0.50, 1.00, 0.5, 1.0, "0,1923,611,1917,584"),
}


KEYS_PAGINA = {
    # tecla: (label, combo, factory_keys, icono_sistema)
    8:  ("Captura", "Print",         lambda: _kp(Key.print_screen),               "applets-screenshooter"),
    9:  ("CapSel",  "Shift+Print",   lambda: _kp(Key.shift, Key.print_screen),    "applets-screenshooter"),
    10: ("Bloqueo", "Super+L",       lambda: _kp(Key.cmd, 'l'),                   "system-lock-screen"),
    11: ("AltTab",  "Alt+Tab",       lambda: _kp(Key.alt, Key.tab),               "view-restore"),
    12: ("Cerrar",  "Alt+F4",        lambda: _kp(Key.alt, Key.f4),                "window-close"),
    13: ("Escrit",  "Super+D",       lambda: _kp(Key.cmd, 'd'),                   "user-desktop"),
    16: ("CopiaT",  "Ctrl+Shift+C",  lambda: _kp(Key.ctrl, Key.shift, 'c'),       "edit-copy"),
    17: ("PegaT",   "Ctrl+Shift+V",  lambda: _kp(Key.ctrl, Key.shift, 'v'),       "edit-paste"),
    18: ("Root",    "PWD",           lambda: ROOT_TEXT,                           "dialog-password"),
}


_FAVICON_CACHE_DIR = os.path.expanduser("~/.cache/streamdeb/favicons")
_ICONIFY_CACHE_DIR = os.path.expanduser("~/.cache/streamdeb/iconify")
_favicon_paths = {}
_iconify_paths = {}

def _iconify_png(name, color_hex, size=256):
    """Descarga un icono de iconify (set:icon) y lo cachea como PNG.
    `color_hex` puede ser None para iconos multicolor (fluent-color, etc.)."""
    key = (name, color_hex, size)
    if key in _iconify_paths:
        return _iconify_paths[key]
    os.makedirs(_ICONIFY_CACHE_DIR, exist_ok=True)
    safe = name.replace(":", "_").replace("/", "_")
    color_tag = color_hex if color_hex else "raw"
    path = os.path.join(_ICONIFY_CACHE_DIR, f"{safe}_{color_tag}_{size}.png")
    if not os.path.exists(path) or os.path.getsize(path) < 100:
        if color_hex:
            url = f"https://api.iconify.design/{name}.svg?color=%23{color_hex}"
        else:
            url = f"https://api.iconify.design/{name}.svg"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6) as r:
                svg = r.read()
            import cairosvg
            data = cairosvg.svg2png(bytestring=svg, output_width=size, output_height=size)
            with open(path, "wb") as f:
                f.write(data)
            print(f"[ICONIFY] {name} ({color_hex}) -> {len(data)}B", flush=True)
        except Exception as e:
            print(f"[WARN] iconify {name}: {e}", flush=True)
            _iconify_paths[key] = None
            return None
    _iconify_paths[key] = path
    return path

def _favicon_path(url):
    """Devuelve la ruta a un PNG con el favicon del dominio, descargándolo
    desde el servicio s2 de Google si hace falta. Cachea en disco y memoria."""
    if url in _favicon_paths:
        return _favicon_paths[url]
    try:
        host = urlparse(url).hostname or url
    except Exception:
        host = url
    os.makedirs(_FAVICON_CACHE_DIR, exist_ok=True)
    path = os.path.join(_FAVICON_CACHE_DIR, f"{host}.png")
    # Override que apunta a un archivo local: úsalo directo, sin descargar.
    if url in WEB_ICON_OVERRIDE and not WEB_ICON_OVERRIDE[url].startswith("http"):
        local = WEB_ICON_OVERRIDE[url]
        if os.path.exists(local):
            _favicon_paths[url] = local
            return local
    if not os.path.exists(path) or os.path.getsize(path) < 100:
        sources = []
        if url in WEB_ICON_OVERRIDE and WEB_ICON_OVERRIDE[url].startswith("http"):
            sources.append(WEB_ICON_OVERRIDE[url])
        sources += [
            f"https://www.google.com/s2/favicons?domain={host}&sz=128",
            f"https://icons.duckduckgo.com/ip3/{host}.ico",
            f"https://{host}/favicon.ico",
        ]
        data = None
        for src in sources:
            try:
                req = urllib.request.Request(src, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=4) as r:
                    data = r.read()
                if len(data) >= 100:
                    # Si nos devolvieron SVG, renderizar a PNG con cairosvg.
                    head = data[:200].lstrip()
                    if head.startswith(b"<?xml") or head.startswith(b"<svg"):
                        try:
                            import cairosvg
                            data = cairosvg.svg2png(bytestring=data,
                                                    output_width=256, output_height=256)
                        except Exception as e:
                            print(f"[WARN] svg2png {host}: {e}", flush=True)
                            data = None
                            continue
                    print(f"[FAVICON] {host} -> {len(data)}B ({src.split('/')[2]})", flush=True)
                    break
                data = None
            except Exception as e:
                print(f"[WARN] favicon {host} via {src.split('/')[2]}: {e}", flush=True)
        if not data:
            _favicon_paths[url] = None
            return None
        with open(path, "wb") as f:
            f.write(data)
    _favicon_paths[url] = path
    return path

def _enviar_combo(keys):
    if not KB_DISPONIBLE:
        print("[WARN] pynput no disponible, no se envía combo", flush=True)
        return
    pressed = []
    try:
        for k in keys:
            keyboard.press(k); pressed.append(k)
            time.sleep(0.02)
        time.sleep(0.05)
    finally:
        for k in reversed(pressed):
            try: keyboard.release(k)
            except Exception: pass

def _tipear_url(url):
    """Abre una pestaña nueva (Ctrl+T), tipea la URL y pulsa Enter.
    El navegador debe estar enfocado al pulsar el botón."""
    if not KB_DISPONIBLE:
        print("[WARN] pynput no disponible, no se tipea URL", flush=True)
        return
    _enviar_combo([Key.ctrl, 't'])
    time.sleep(0.35)
    keyboard.type(url)
    time.sleep(0.05)
    keyboard.press(Key.enter); keyboard.release(Key.enter)


# --- Carga y resolución de iconos ---

import glob as _glob

_ICONO_BASES = (
    "/var/lib/flatpak/exports/share/icons/hicolor",
    os.path.expanduser("~/.local/share/icons/hicolor"),
    "/usr/share/icons/hicolor",
    "/usr/share/icons/gnome",
    "/usr/share/icons/mate",
)
_ICONO_TAMS = ("512x512", "256x256", "128x128", "96x96", "64x64", "48x48")
_ICONO_SUBDIRS = ("apps", "actions", "categories", "places", "status", "devices")
_icono_cache = {}

def _buscar_icono(nombre):
    if not nombre:
        return None
    if os.path.isabs(nombre):
        return nombre if os.path.exists(nombre) else None
    for base in _ICONO_BASES:
        for size in _ICONO_TAMS:
            for sub in _ICONO_SUBDIRS:
                p = f"{base}/{size}/{sub}/{nombre}.png"
                if os.path.exists(p):
                    return p
    for ext in ("png", "xpm"):
        p = f"/usr/share/pixmaps/{nombre}.{ext}"
        if os.path.exists(p):
            return p
    for size in ("128x128", "64x64"):
        m = sorted(_glob.glob(f"/var/lib/flatpak/appstream/flathub/x86_64/*/icons/{size}/{nombre}.png"))
        if m:
            return m[0]
    return None

def _cargar_icono(nombre, lado_max):
    key = (nombre, lado_max)
    if key in _icono_cache:
        return _icono_cache[key]
    path = _buscar_icono(nombre)
    if not path:
        _icono_cache[key] = None
        return None
    try:
        img = Image.open(path).convert("RGBA")
        img.thumbnail((lado_max, lado_max), Image.LANCZOS)
        _icono_cache[key] = img
        return img
    except Exception as e:
        print(f"[ERR ICON] {nombre}: {e}", flush=True)
        _icono_cache[key] = None
        return None


# --- Hilos de fondo ---

def tareas_red_fondo():
    global mute_activo, volumen_actual
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            net_info["ip_loc"] = s.getsockname()[0]
            s.close()
            req = urllib.request.Request("https://api.ipify.org")
            with urllib.request.urlopen(req, timeout=3) as resp:
                net_info["ip_pub"] = resp.read().decode('utf-8')
        except: pass

        for clave, ip in [("ping_gw", "192.168.18.1"), ("ping_dns1", "1.1.1.1"), ("ping_dns2", "8.8.8.8"), ("ping_api", API_IP)]:
            try:
                res = subprocess.run(["ping", "-c", "1", "-W", "1", ip], capture_output=True, text=True)
                net_info[clave] = float(res.stdout.split("time=")[1].split(" ")[0]) if "time=" in res.stdout else -1.0
            except: net_info[clave] = -1.0
            if net_info[clave] > 0:
                ping_history[clave].append(net_info[clave])

        try:
            res = subprocess.run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"],
                                 capture_output=True, text=True, timeout=1, env=_env_sesion())
            mute_activo = "yes" in res.stdout.lower()
        except: pass

        try:
            res = subprocess.run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
                                 capture_output=True, text=True, timeout=1, env=_env_sesion())
            m = re.search(r"(\d+)%", res.stdout)
            if m: volumen_actual = int(m.group(1))
        except: pass

        time.sleep(5)


def tareas_api_fondo():
    while True:
        try:
            req = urllib.request.Request(f"{API_HOST}/estado", method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            api_info.update({
                "online": True,
                "estado":          data.get("estado", "---"),
                "cuenta":          data.get("cuenta", "---"),
                "modo":            data.get("modo", 0),
                "modoNombre":      data.get("modoNombre", "---"),
                "contador":        data.get("contador", 0),
                "wifiSignal":      data.get("wifiSignal", 0),
                "tankOnline":      data.get("tankOnline", False),
                "tankSignal":      data.get("tankSignal", 0),
                "usuario":         data.get("usuario", "---"),
                "adminLocked":     data.get("adminLocked", False),
                "segundos":        data.get("segundos", 0),
                "initial_seconds": data.get("initial_seconds", 0),
            })
        except Exception:
            api_info["online"] = False
        time.sleep(2)


def tareas_pomodoro_fondo():
    """Tick de estado para que las transiciones (focus→break→idle) ocurran
    aunque el usuario no esté viendo SIS."""
    while True:
        try: _pomodoro_tick()
        except Exception as e: print(f"[POMO] tick: {e}", flush=True)
        time.sleep(2)


def tareas_docker_fondo():
    """Lista contenedores docker cada 10s. Si docker no está, queda available=False."""
    while True:
        try:
            res = subprocess.run(
                ["docker", "ps", "-a", "--format", "{{.Names}}\t{{.State}}\t{{.Image}}"],
                capture_output=True, text=True, timeout=3,
            )
            if res.returncode == 0:
                containers = []
                running = 0
                for line in res.stdout.strip().splitlines():
                    parts = line.split("\t")
                    if len(parts) >= 2:
                        name, state = parts[0], parts[1]
                        image = parts[2] if len(parts) > 2 else ""
                        is_run = (state == "running")
                        if is_run:
                            running += 1
                        containers.append((name, is_run, image))
                docker_info["available"] = True
                docker_info["running"]   = running
                docker_info["containers"] = containers
            else:
                docker_info["available"] = False
        except FileNotFoundError:
            docker_info["available"] = False
        except Exception as e:
            docker_info["available"] = False
            print(f"[DOCKER] error: {e}", flush=True)
        time.sleep(10)


def tareas_clima_fondo():
    """Open-Meteo API: temp, humedad, viento, min/max. Refresh cada 15 min."""
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={CLIMA_LAT}&longitude={CLIMA_LON}"
        f"&current=temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code"
        f"&daily=temperature_2m_max,temperature_2m_min"
        f"&hourly=temperature_2m,weather_code,precipitation_probability"
        f"&forecast_days=2"
        f"&timezone=America/Lima"
    )
    while True:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "streamdeb/1.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode("utf-8"))
            cur = data.get("current", {})
            daily = data.get("daily", {})
            hourly = data.get("hourly", {})
            # Construir lista hourly empezando desde la hora actual (sin pasadas)
            h_times = hourly.get("time", []) or []
            h_temps = hourly.get("temperature_2m", []) or []
            h_codes = hourly.get("weather_code", []) or []
            h_precs = hourly.get("precipitation_probability", []) or []
            now_iso = datetime.datetime.now().strftime("%Y-%m-%dT%H:00")
            inicio = 0
            for i, t in enumerate(h_times):
                if t >= now_iso:
                    inicio = i
                    break
            hourly_list = []
            for i in range(inicio, min(inicio + 24, len(h_times))):
                hourly_list.append({
                    "hora":   h_times[i][-5:],  # "HH:MM"
                    "temp":   h_temps[i] if i < len(h_temps) else None,
                    "code":   h_codes[i] if i < len(h_codes) else None,
                    "precip": h_precs[i] if i < len(h_precs) else None,
                })
            clima_info.update({
                "online": True,
                "temp":     cur.get("temperature_2m"),
                "humedad":  cur.get("relative_humidity_2m"),
                "viento":   cur.get("wind_speed_10m"),
                "weather_code": cur.get("weather_code"),
                "temp_min": (daily.get("temperature_2m_min") or [None])[0],
                "temp_max": (daily.get("temperature_2m_max") or [None])[0],
                "hourly":   hourly_list,
                "ts": time.time(),
            })
        except Exception as e:
            clima_info["online"] = False
            print(f"[CLIMA] error: {e}", flush=True)
        time.sleep(15 * 60)


def api_post_comando(payload):
    try:
        body = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            f"{API_HOST}/api/comando",
            data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            print(f"[API] {payload} → {resp.status}", flush=True)
    except Exception as e:
        print(f"[ERR API] {payload}: {e}", flush=True)


# --- Dibujo ---

def _con_marco():
    """¿Se dibuja el marco externo del botón? Depende del perfil visual activo."""
    return perfil_visual == 1

def _nuevo_lienzo(tamaño):
    """Lienzo RGBA totalmente transparente. El fondo (negro o wallpaper)
    se compone en _finalizar()."""
    return Image.new("RGBA", tamaño, (0, 0, 0, 0))

# --- Wallpaper rotativo (0=OFF, 1..30=imágenes) ---
# Idx 1 = galaxia actual (~/.cache/streamdeb/wallpaper.jpg)
# Idx 2..30 = ~/.cache/streamdeb/wallpapers/NN_*.{jpg,png} (10 espacio + 10 linux + 9 nature)
WALLPAPER_DIR    = os.path.expanduser("~/.cache/streamdeb/wallpapers")
WALLPAPER_GALAXY = os.path.expanduser("~/.cache/streamdeb/wallpaper.jpg")
# Default para XL; se sobreescribe desde deck.key_layout() en _abrir_deck()
DECK_COLS, DECK_ROWS = 8, 4
WALLPAPER_BRILLO     = 0.4      # 1.0 = original · 0.4 = 40% (oscurecido para destaque de botones)
WALLPAPER_SATURACION = 1.25     # 1.0 = original · 1.25 = +25% saturación
LONGPRESS_S          = 2.0      # umbral pulsación larga (SIS→CONF, wallpaper→OFF)
wallpaper_idx     = 0           # 0 = OFF
_wallpaper_paths  = None        # lista [None, path1, path2, …, path30]
_wallpaper_cache  = {}          # idx → PIL RGB redimensionado (cols*W, rows*H)
_wallpaper_size   = None        # tamaño cacheado; si cambia se invalida cache

def _wallpaper_lista():
    """Construye la lista de paths una vez. [0]=None, [1]=galaxy, [2..30]=dir."""
    global _wallpaper_paths
    if _wallpaper_paths is not None:
        return _wallpaper_paths
    paths = [None, WALLPAPER_GALAXY]
    if os.path.isdir(WALLPAPER_DIR):
        extras = sorted(
            os.path.join(WALLPAPER_DIR, n)
            for n in os.listdir(WALLPAPER_DIR)
            if n.lower().endswith((".jpg", ".jpeg", ".png"))
        )
        paths.extend(extras)
    _wallpaper_paths = paths
    print(f"[WALLPAPER] {len(paths)-1} imágenes disponibles (1..{len(paths)-1})", flush=True)
    return paths

def wallpaper_total():
    return max(0, len(_wallpaper_lista()) - 1)

def _wallpaper_cargar(tamaño, idx):
    """Devuelve PIL RGB de tamaño (cols*W, rows*H) para el idx, cacheado."""
    global _wallpaper_cache, _wallpaper_size
    if _wallpaper_size != tamaño:
        _wallpaper_cache.clear()
        _wallpaper_size = tamaño
    if idx in _wallpaper_cache:
        return _wallpaper_cache[idx]
    paths = _wallpaper_lista()
    if idx <= 0 or idx >= len(paths) or not paths[idx] or not os.path.exists(paths[idx]):
        return None
    try:
        img = Image.open(paths[idx]).convert("RGB")
        total = (DECK_COLS * tamaño[0], DECK_ROWS * tamaño[1])
        img = img.resize(total, Image.LANCZOS)
        if WALLPAPER_SATURACION != 1.0:
            img = ImageEnhance.Color(img).enhance(WALLPAPER_SATURACION)
        if WALLPAPER_BRILLO != 1.0:
            img = ImageEnhance.Brightness(img).enhance(WALLPAPER_BRILLO)
        _wallpaper_cache[idx] = img
        return img
    except Exception as e:
        print(f"[WALLPAPER] error cargando idx={idx} ({paths[idx]}): {e}", flush=True)
        return None

def _wallpaper_tile(tamaño, tecla):
    if wallpaper_idx <= 0 or tecla is None:
        return None
    full = _wallpaper_cargar(tamaño, wallpaper_idx)
    if full is None:
        return None
    row, col = tecla // DECK_COLS, tecla % DECK_COLS
    box = (col * tamaño[0], row * tamaño[1],
           (col + 1) * tamaño[0], (row + 1) * tamaño[1])
    return full.crop(box).copy()

_finalizar_cache = {}        # (id(pil) | 0, wallpaper_idx, tecla) → bytes JPEG nativos
_FINALIZAR_CACHE_MAX = 512   # cap defensivo: si crece (PILs dinámicos) se vacía entera
_last_sent = {}              # tecla → bytes (dedup de USB writes)

def _finalizar(deck, tamaño, imagen_rgba, tecla):
    """Compone PIL RGBA sobre el tile de wallpaper (si está ON) o negro,
    y devuelve los bytes nativos. Cachea SOLO cuando el caller indica que
    el PIL es estable (atributo `_streamdeb_stable`) o cuando es None.
    Cachear por id() de un PIL transitorio es inseguro: Python reusa ids
    de objetos liberados, devolviendo bytes obsoletos de otras páginas."""
    es_estable = imagen_rgba is None or getattr(imagen_rgba, "_streamdeb_stable", False)
    cache_key = None
    if es_estable:
        cache_key = (id(imagen_rgba) if imagen_rgba is not None else 0,
                     wallpaper_idx, tecla)
        nb = _finalizar_cache.get(cache_key)
        if nb is not None:
            return nb
    if wallpaper_idx > 0:
        tile = _wallpaper_tile(tamaño, tecla)
        fondo = tile if tile is not None else Image.new("RGB", tamaño, "black")
    else:
        fondo = Image.new("RGB", tamaño, "black")
    if imagen_rgba is not None:
        fondo.paste(imagen_rgba, (0, 0), imagen_rgba)
    nb = PILHelper.to_native_format(deck, fondo)
    if cache_key is not None:
        if len(_finalizar_cache) >= _FINALIZAR_CACHE_MAX:
            _finalizar_cache.clear()
        _finalizar_cache[cache_key] = nb
    return nb

def _push_key(deck, tecla, nb):
    """Envía al deck solo si los bytes cambiaron — evita USB writes redundantes."""
    if _last_sent.get(tecla) == nb:
        return
    deck.set_key_image(tecla, nb)
    _last_sent[tecla] = nb

def _invalidar_render_cache():
    """Limpia caches cuando cambia el contexto global (perfil, wallpaper, reconexión)."""
    _finalizar_cache.clear()
    _last_sent.clear()

def obtener_color_rango(valor):
    if valor < 30: return "#33ff33"
    elif valor <= 80: return "#ffaa00"
    else: return "#ff3333"

def dibujar_panel_metrica(deck, tamaño, titulo, valor, color, pct=None, valor_color=None, sub=None):
    """Estilo unificado SIS: marco redondeado + título separado + valor + barra inferior."""
    imagen = _nuevo_lienzo(tamaño)
    dibujo = ImageDraw.Draw(imagen)
    rect = (4, 4, tamaño[0]-5, tamaño[1]-5)
    if _con_marco():
        dibujo.rounded_rectangle(rect, radius=10, outline=color, width=2)
    f_tit = ImageFont.truetype(FONT_PATH, 13)
    dibujo.text((tamaño[0]//2, 15), titulo, font=f_tit, fill=color, anchor="mm")
    dibujo.line((10, 27, tamaño[0]-11, 27), fill=color, width=1)

    vc = valor_color or "#ffffff"
    txt = str(valor)
    max_w = tamaño[0] - 16

    # Centrado vertical del contenido: con barra el área es [28, 76], sin barra [28, alto-6]
    bottom = 76 if pct is not None else (tamaño[1] - 6)
    cy = (28 + bottom) // 2

    if " " in txt and sub is None:
        l1, l2 = txt.split(" ", 1)
        f1 = _fit_font(dibujo, l1, max_w, 18, 11)
        f2 = _fit_font(dibujo, l2, max_w, 18, 11)
        dibujo.text((tamaño[0]//2, cy - 9),  l1, font=f1, fill=vc, anchor="mm")
        dibujo.text((tamaño[0]//2, cy + 10), l2, font=f2, fill=vc, anchor="mm")
    elif sub:
        f_val = _fit_font(dibujo, txt, max_w, 22, 12)
        f_sub = ImageFont.truetype(FONT_PATH, 12)
        dibujo.text((tamaño[0]//2, cy - 8),  txt, font=f_val, fill=vc, anchor="mm")
        dibujo.text((tamaño[0]//2, cy + 10), sub, font=f_sub, fill="#aaaaaa", anchor="mm")
    else:
        f_val = _fit_font(dibujo, txt, max_w, 26, 12)
        dibujo.text((tamaño[0]//2, cy), txt, font=f_val, fill=vc, anchor="mm")

    if pct is not None:
        ancho, alto, x, y = tamaño[0] - 20, 8, 10, 78
        p = max(0, min(100, pct))
        dibujo.rectangle((x, y, x + ancho, y + alto), outline="#333333", fill="#111111")
        if p > 0:
            dibujo.rectangle((x, y, x + int(ancho * (p/100)), y + alto), fill=color)
    return imagen

def _ip_2_lineas(ip):
    partes = ip.split('.')
    if len(partes) == 4:
        return f"{partes[0]}.{partes[1]}. {partes[2]}.{partes[3]}"
    return ip

def _fmt_tiempo(segundos):
    """Formato compacto m'ss\" (o h'mm\" si ≥1h)."""
    s = max(0, int(segundos))
    if s >= 3600:
        h, rem = divmod(s, 3600)
        return f"{h}'{rem // 60:02d}\""
    m, sec = divmod(s, 60)
    return f"{m}'{sec:02d}\""

def _ping_pct_relativo(clave, ms):
    """Devuelve (pct, color). Baseline 30% verde cuando ms ≤ promedio observado;
    crece hacia 100% rojo a medida que ms se acerca al máximo histórico."""
    if ms <= 0:
        return 0, "#666666"
    hist = ping_history.get(clave)
    if not hist or len(hist) < 3:
        return 30, "#33ff33"
    avg = sum(hist) / len(hist)
    pmax = max(hist)
    if pmax - avg < 1.0:
        return 30, "#33ff33"
    if ms <= avg:
        pct = 30.0
    else:
        pct = 30.0 + ((ms - avg) / (pmax - avg)) * 70.0
        pct = max(0.0, min(100.0, pct))
    if pct <= 40:
        color = "#33ff33"
    elif pct <= 70:
        color = "#ffaa00"
    else:
        color = "#ff3333"
    return pct, color

def dibujar_boton_fijo(deck, tamaño, texto, color, relleno=False):
    imagen = _nuevo_lienzo(tamaño)
    dibujo = ImageDraw.Draw(imagen)
    f_btn = ImageFont.truetype(FONT_PATH, 18)
    rect  = (5, 5, tamaño[0]-6, tamaño[1]-6)
    if relleno:
        dibujo.rounded_rectangle(rect, radius=12, fill=color)
        dibujo.text((tamaño[0]//2, tamaño[1]//2), texto, font=f_btn, fill="black", anchor="mm")
    else:
        if _con_marco():
            dibujo.rounded_rectangle(rect, radius=12, outline=color, width=3)
        dibujo.text((tamaño[0]//2, tamaño[1]//2), texto, font=f_btn, fill="white", anchor="mm")
    return imagen

def _fit_font(dibujo, txt, max_width, max_size, min_size=10):
    for size in range(max_size, min_size - 1, -1):
        f = ImageFont.truetype(FONT_PATH, size)
        if dibujo.textlength(txt, font=f) <= max_width:
            return f
    return ImageFont.truetype(FONT_PATH, min_size)

def dibujar_panel_info(deck, tamaño, titulo, valor, frame_color, valor_color="#ffffff"):
    imagen = _nuevo_lienzo(tamaño)
    dibujo = ImageDraw.Draw(imagen)
    rect = (4, 4, tamaño[0]-5, tamaño[1]-5)
    if _con_marco():
        dibujo.rounded_rectangle(rect, radius=10, outline=frame_color, width=2)
    f_tit = ImageFont.truetype(FONT_PATH, 13)
    dibujo.text((tamaño[0]//2, 16), titulo, font=f_tit, fill=frame_color, anchor="mm")
    dibujo.line((10, 28, tamaño[0]-11, 28), fill=frame_color, width=1)
    txt = str(valor)
    f_val = _fit_font(dibujo, txt, tamaño[0]-16, 22, 11)
    dibujo.text((tamaño[0]//2, 60), txt, font=f_val, fill=valor_color, anchor="mm")
    return imagen

def dibujar_panel_2lineas(deck, tamaño, titulo, valor, frame_color, valor_color="#ffffff"):
    imagen = _nuevo_lienzo(tamaño)
    dibujo = ImageDraw.Draw(imagen)
    rect = (4, 4, tamaño[0]-5, tamaño[1]-5)
    if _con_marco():
        dibujo.rounded_rectangle(rect, radius=10, outline=frame_color, width=2)
    f_tit = ImageFont.truetype(FONT_PATH, 13)
    dibujo.text((tamaño[0]//2, 16), titulo, font=f_tit, fill=frame_color, anchor="mm")
    dibujo.line((10, 28, tamaño[0]-11, 28), fill=frame_color, width=1)
    txt = str(valor).strip()
    if " " in txt:
        l1, l2 = txt.split(" ", 1)
    else:
        mid = (len(txt) + 1) // 2
        l1, l2 = txt[:mid], txt[mid:]
    max_w = tamaño[0] - 16
    f1 = _fit_font(dibujo, l1, max_w, 18, 10)
    f2 = _fit_font(dibujo, l2, max_w, 18, 10)
    dibujo.text((tamaño[0]//2, 50), l1, font=f1, fill=valor_color, anchor="mm")
    dibujo.text((tamaño[0]//2, 73), l2, font=f2, fill=valor_color, anchor="mm")
    return imagen

def dibujar_estado_pro(deck, tamaño, online, abierta):
    """Estado AWA visual: aro + círculo interno.
    Abierta = verde, círculo latiendo. Cerrada = rojo, círculo fijo.
    Offline = gris, círculo fijo y aro tenue."""
    imagen = _nuevo_lienzo(tamaño)
    dibujo = ImageDraw.Draw(imagen)
    rect = (4, 4, tamaño[0]-5, tamaño[1]-5)
    f_tit = ImageFont.truetype(FONT_PATH, 13)

    if not online:
        color = "#666666"
    elif abierta:
        color = "#22dd44"
    else:
        color = "#ff3333"

    if _con_marco():
        dibujo.rounded_rectangle(rect, radius=10, outline=color, width=2)

    # Header consistente con el resto de paneles
    dibujo.text((tamaño[0]//2, 16), "Estado", font=f_tit, fill=color, anchor="mm")
    dibujo.line((10, 28, tamaño[0]-11, 28), fill=color, width=1)

    # Visual: aro + círculo interno (latiendo si abierta)
    cx, cy = tamaño[0]//2, 62
    R = 24
    grosor_aro = 4
    dibujo.ellipse((cx-R, cy-R, cx+R, cy+R), outline=color, width=grosor_aro)

    if online and abierta:
        # Latido: radio oscila entre ~7 y ~16 con periodo no entero
        # para que samples a 1 Hz devuelvan valores variados.
        fase = (math.sin(2 * math.pi * time.time() / 2.7) + 1) / 2  # 0..1
        r_int = int(7 + fase * 9)
    else:
        r_int = 12
    dibujo.ellipse((cx-r_int, cy-r_int, cx+r_int, cy+r_int), fill=color)
    return imagen

_AWA_FONDO_RGBA = (0, 26, 38, 51)  # #001a26 con 20% opacidad (80% transparente al wallpaper)

def dibujar_accion_pro(deck, tamaño, texto, color, peligro=False, drain=None):
    """Acción con marco redondeado. drain en [0,1]: 0=lleno (recién pulsado),
    1=vaciado completo. None = estado inactivo (fondo oscuro)."""
    imagen = _nuevo_lienzo(tamaño)
    dibujo = ImageDraw.Draw(imagen)
    rect = (4, 4, tamaño[0]-5, tamaño[1]-5)

    if peligro:
        dibujo.rounded_rectangle(rect, radius=10, fill=color)
    elif drain is None:
        dibujo.rounded_rectangle(rect, radius=10, fill=_AWA_FONDO_RGBA)
        if _con_marco():
            dibujo.rounded_rectangle(rect, radius=10, outline=color, width=2)
    else:
        d = max(0.0, min(1.0, drain))
        # Base oscura translúcida
        dibujo.rounded_rectangle(rect, radius=10, fill=_AWA_FONDO_RGBA)
        if d < 1.0:
            # Capa de agua (rect redondeado lleno) + máscara que recorta
            # solo la franja inferior — efecto "el agua baja al vaciarse".
            water = Image.new("RGBA", tamaño, (0, 0, 0, 0))
            wd = ImageDraw.Draw(water)
            wd.rounded_rectangle(rect, radius=10, fill=color)
            mask = Image.new("L", tamaño, 0)
            md = ImageDraw.Draw(mask)
            water_top = int(4 + (tamaño[1] - 8) * d)
            md.rectangle((0, water_top, tamaño[0], tamaño[1]), fill=255)
            imagen = Image.composite(water, imagen, mask)
            dibujo = ImageDraw.Draw(imagen)
        if _con_marco():
            dibujo.rounded_rectangle(rect, radius=10, outline=color, width=2)

    max_w = tamaño[0] - 16
    if " " in texto:
        num, unidad = texto.split(" ", 1)
        f_num = _fit_font(dibujo, num,    max_w, 36, 18)
        f_uni = _fit_font(dibujo, unidad, max_w, 18, 12)
        dibujo.text((tamaño[0]//2, 36), num,    font=f_num, fill="white", anchor="mm")
        dibujo.text((tamaño[0]//2, 72), unidad, font=f_uni, fill="white", anchor="mm")
    else:
        f = _fit_font(dibujo, texto, max_w, 24, 12)
        dibujo.text((tamaño[0]//2, tamaño[1]//2), texto, font=f, fill="white", anchor="mm")
    return imagen

def dibujar_boton_nav(deck, tamaño, titulo, sub1=None, sub2=None, color="#33ccff", activo=False):
    """Botón de navegación con título y hasta 2 sublíneas opcionales."""
    imagen = _nuevo_lienzo(tamaño)
    dibujo = ImageDraw.Draw(imagen)
    rect = (5, 5, tamaño[0]-6, tamaño[1]-6)
    if activo:
        dibujo.rounded_rectangle(rect, radius=12, fill=color)
        title_color = "black"
        sub_color   = "black"
    else:
        if _con_marco():
            dibujo.rounded_rectangle(rect, radius=12, outline=color, width=3)
        title_color = "white"
        sub_color   = color
    max_w = tamaño[0] - 18
    if sub1 and sub2:
        # Header: título compacto + línea separadora · datos en zonas iguales
        f_tit = ImageFont.truetype(FONT_PATH, 13)
        dibujo.text((tamaño[0]//2, 16), titulo, font=f_tit, fill=title_color, anchor="mm")
        dibujo.line((11, 28, tamaño[0]-12, 28), fill=sub_color, width=1)
        f1 = _fit_font(dibujo, str(sub1), max_w, 16, 10)
        f2 = _fit_font(dibujo, str(sub2), max_w, 20, 11)
        dibujo.text((tamaño[0]//2, 50), str(sub1), font=f1, fill=sub_color, anchor="mm")
        dibujo.text((tamaño[0]//2, 76), str(sub2), font=f2, fill=sub_color, anchor="mm")
    elif sub1:
        # Mismo estilo que el header de 3 líneas, con un único dato centrado abajo
        f_tit = ImageFont.truetype(FONT_PATH, 13)
        dibujo.text((tamaño[0]//2, 16), titulo, font=f_tit, fill=title_color, anchor="mm")
        dibujo.line((11, 28, tamaño[0]-12, 28), fill=sub_color, width=1)
        f1 = _fit_font(dibujo, str(sub1), max_w, 26, 12)
        dibujo.text((tamaño[0]//2, 62), str(sub1), font=f1, fill=sub_color, anchor="mm")
    else:
        f_tit = ImageFont.truetype(FONT_PATH, 18)
        dibujo.text((tamaño[0]//2, tamaño[1]//2), titulo, font=f_tit, fill=title_color, anchor="mm")
    return imagen

_gear_cache = {}
_app_cache = {}
_web_cache = {}
_keys_cache = {}
_vent_cache = {}
GEAR_ICON_PATHS = (
    "/usr/share/icons/gnome/256x256/categories/preferences-system.png",
    "/usr/share/icons/mate/256x256/categories/preferences-system.png",
    "/usr/share/icons/gnome/256x256/categories/applications-system.png",
)
APP_NAV_ICON_PATHS = (
    "/usr/share/icons/gnome/256x256/places/start-here.png",
)
WEB_NAV_ICON_PATHS = (
    "/usr/share/icons/gnome/256x256/apps/web-browser.png",
    "/usr/share/icons/gnome/256x256/categories/applications-internet.png",
)
KEYS_NAV_ICON_PATHS = (
    "/usr/share/icons/gnome/256x256/apps/preferences-desktop-keyboard-shortcuts.png",
    "/usr/share/icons/gnome/256x256/apps/preferences-desktop-keyboard.png",
)
def _vent_nav_paths():
    """Icono para el botón VENT: 3 columnas verticales (mdi:view-column)
    representan los tercios de tiling. Descarga vía iconify una vez."""
    p = _iconify_png("mdi:view-quilt", "66ddff", 256)
    fallbacks = (
        "/usr/share/icons/ContrastHigh/256x256/actions/view-grid.png",
        "/usr/share/icons/hicolor/256x256/apps/mate-panel-window-list.png",
    )
    return tuple(x for x in (p, *fallbacks) if x)

def _dibujar_btn_icono_nav(deck, tamaño, paths, color, titulo, activo, cache):
    """Botón de navegación con header (título + separador) e icono colorido en la
    zona inferior, mismo estilo que el resto de nav. Cache por (tamaño, activo, titulo)."""
    cache_key = (tamaño, activo, titulo, perfil_visual)
    if cache_key in cache:
        return cache[cache_key]
    imagen = _nuevo_lienzo(tamaño)
    dibujo = ImageDraw.Draw(imagen)
    rect = (5, 5, tamaño[0]-6, tamaño[1]-6)
    if activo:
        dibujo.rounded_rectangle(rect, radius=12, fill=color)
        title_color, sep_color = "black", "black"
    else:
        if _con_marco():
            dibujo.rounded_rectangle(rect, radius=12, outline=color, width=3)
        title_color, sep_color = "white", color
    f_tit = ImageFont.truetype(FONT_PATH, 13)
    dibujo.text((tamaño[0]//2, 16), titulo, font=f_tit, fill=title_color, anchor="mm")
    dibujo.line((11, 28, tamaño[0]-12, 28), fill=sep_color, width=1)

    zone_top, zone_bot = 30, tamaño[1] - 6
    zone_h = zone_bot - zone_top
    icono = None
    for path in paths:
        if os.path.exists(path):
            try:
                icono = Image.open(path).convert("RGBA")
                break
            except Exception as e:
                print(f"[ERR ICON NAV] {path}: {e}", flush=True)
    if icono is not None:
        lado = int(min(tamaño[0] - 18, zone_h - 2) * 0.9)
        icono.thumbnail((lado, lado), Image.LANCZOS)
        ix = (tamaño[0] - icono.width) // 2
        iy = zone_top + (zone_h - icono.height) // 2
        imagen.paste(icono, (ix, iy), icono)
    out = imagen
    out._streamdeb_stable = True  # PIL retenido por 'cache': id() permanece válido
    cache[cache_key] = out
    return out

def dibujar_lanzador(deck, tamaño, categoria, color, icono=None, fallback=None):
    """Lanzador de app: marco redondeado + título (categoría) + separador + icono
    centrado debajo. Si no hay icono disponible cae a texto fallback."""
    imagen = _nuevo_lienzo(tamaño)
    dibujo = ImageDraw.Draw(imagen)
    rect = (4, 4, tamaño[0]-5, tamaño[1]-5)
    if _con_marco():
        dibujo.rounded_rectangle(rect, radius=10, outline=color, width=2)
    f_tit = ImageFont.truetype(FONT_PATH, 13)
    dibujo.text((tamaño[0]//2, 15), categoria, font=f_tit, fill=color, anchor="mm")
    dibujo.line((10, 27, tamaño[0]-11, 27), fill=color, width=1)

    # Zona disponible bajo el separador: y=28..alto-6
    zone_top, zone_bot = 28, tamaño[1] - 6
    zone_h = zone_bot - zone_top
    lado_max = min(tamaño[0] - 16, zone_h - 4)
    img_icono = _cargar_icono(icono, lado_max) if icono else None
    if img_icono is not None:
        ix = (tamaño[0] - img_icono.width) // 2
        iy = zone_top + (zone_h - img_icono.height) // 2
        imagen.paste(img_icono, (ix, iy), img_icono)
    elif fallback:
        f_val = _fit_font(dibujo, fallback, tamaño[0] - 16, 26, 12)
        cy = (zone_top + zone_bot) // 2
        dibujo.text((tamaño[0]//2, cy), fallback, font=f_val, fill="white", anchor="mm")
    return imagen

def dibujar_lanzador_web(deck, tamaño, label, color, icon_path):
    """Variante de dibujar_lanzador para favicons: escala el icono (incluso
    hacia arriba) hasta llenar ~90% del área inferior."""
    imagen = _nuevo_lienzo(tamaño)
    dibujo = ImageDraw.Draw(imagen)
    rect = (4, 4, tamaño[0]-5, tamaño[1]-5)
    if _con_marco():
        dibujo.rounded_rectangle(rect, radius=10, outline=color, width=2)
    f_tit = ImageFont.truetype(FONT_PATH, 13)
    dibujo.text((tamaño[0]//2, 15), label, font=f_tit, fill=color, anchor="mm")
    dibujo.line((10, 27, tamaño[0]-11, 27), fill=color, width=1)

    zone_top, zone_bot = 28, tamaño[1] - 6
    zone_h = zone_bot - zone_top
    target = int(min(tamaño[0] - 12, zone_h) * 0.9)

    img_icono = None
    if icon_path and os.path.exists(icon_path):
        try:
            img_icono = Image.open(icon_path).convert("RGBA")
            w, h = img_icono.size
            if w > 0 and h > 0:
                scale = target / max(w, h)
                img_icono = img_icono.resize(
                    (max(1, int(w * scale)), max(1, int(h * scale))),
                    Image.LANCZOS,
                )
        except Exception as e:
            print(f"[ERR ICON WEB] {icon_path}: {e}", flush=True)
            img_icono = None

    if img_icono is not None:
        ix = (tamaño[0] - img_icono.width) // 2
        iy = zone_top + (zone_h - img_icono.height) // 2
        imagen.paste(img_icono, (ix, iy), img_icono)
    else:
        f_val = _fit_font(dibujo, label, tamaño[0] - 16, 26, 12)
        cy = (zone_top + zone_bot) // 2
        dibujo.text((tamaño[0]//2, cy), label, font=f_val, fill="white", anchor="mm")
    return imagen


def dibujar_boton_gear(deck, tamaño, activo=False):
    return _dibujar_btn_icono_nav(deck, tamaño, GEAR_ICON_PATHS, "#aaaaaa", "CONF", activo, _gear_cache)

def dibujar_boton_app_nav(deck, tamaño, activo=False):
    return _dibujar_btn_icono_nav(deck, tamaño, APP_NAV_ICON_PATHS, "#33ff66", "APP", activo, _app_cache)

def dibujar_boton_web_nav(deck, tamaño, activo=False):
    return _dibujar_btn_icono_nav(deck, tamaño, WEB_NAV_ICON_PATHS, "#33ff99", "WEB", activo, _web_cache)

def dibujar_boton_keys_nav(deck, tamaño, activo=False):
    return _dibujar_btn_icono_nav(deck, tamaño, KEYS_NAV_ICON_PATHS, "#ffcc33", "KEYS", activo, _keys_cache)

def dibujar_boton_vent_nav(deck, tamaño, activo=False):
    return _dibujar_btn_icono_nav(deck, tamaño, _vent_nav_paths(), "#66ddff", "VENT", activo, _vent_cache)

def dibujar_vent_preview(deck, tamaño, label, x_ini, x_fin, y_ini, y_fin, color):
    """Botón con preview gráfico: marco redondeado + título + 'pantalla'
    en miniatura con la región objetivo (x_ini..x_fin, y_ini..y_fin) resaltada."""
    imagen = _nuevo_lienzo(tamaño)
    dibujo = ImageDraw.Draw(imagen)
    rect = (4, 4, tamaño[0]-5, tamaño[1]-5)
    if _con_marco():
        dibujo.rounded_rectangle(rect, radius=10, outline=color, width=2)
    f_tit = ImageFont.truetype(FONT_PATH, 13)
    dibujo.text((tamaño[0]//2, 15), label, font=f_tit, fill=color, anchor="mm")
    dibujo.line((10, 27, tamaño[0]-11, 27), fill=color, width=1)
    # Pantalla en miniatura (zona inferior)
    pad_x, pad_top, pad_bot = 14, 36, 14
    sx, sy = pad_x, pad_top
    ex, ey = tamaño[0] - pad_x - 1, tamaño[1] - pad_bot - 1
    dibujo.rectangle((sx, sy, ex, ey), outline="#666666", width=1)
    w, h = ex - sx, ey - sy
    rx1 = sx + int(round(w * x_ini))
    rx2 = sx + int(round(w * x_fin))
    ry1 = sy + int(round(h * y_ini))
    ry2 = sy + int(round(h * y_fin))
    if rx2 > rx1 and ry2 > ry1:
        dibujo.rectangle((rx1+1, ry1+1, rx2-1, ry2-1), fill=color)
    return imagen

def dibujar_boton_x(deck, tamaño):
    """Botón profesional con X roja, atenúa el brillo del deck a 0."""
    imagen = _nuevo_lienzo(tamaño)
    dibujo = ImageDraw.Draw(imagen)
    rect = (4, 4, tamaño[0]-5, tamaño[1]-5)
    dibujo.rounded_rectangle(rect, radius=10, fill="#1a0000")
    if _con_marco():
        dibujo.rounded_rectangle(rect, radius=10, outline="#cc0000", width=2)
    pad = 24
    x1, y1 = pad, pad
    x2, y2 = tamaño[0]-pad-1, tamaño[1]-pad-1
    dibujo.line((x1, y1, x2, y2), fill="#ff3333", width=5)
    dibujo.line((x1, y2, x2, y1), fill="#ff3333", width=5)
    return imagen

def dibujar_negro(deck, tamaño):
    return None  # _finalizar(None, tecla) genera el tile (negro o wallpaper)


# --- Callback ---

def _accion_boton(deck, tecla):
    global pagina_actual, forzar_redraw, brillo_actual, modo_dim_activo
    global tiempo_fallback, tiempo_dim, perfil_visual, banner_enabled

    # En banner idle (9), cualquier tecla no-nav despierta a SIS.
    # Las nav (0-7) caen al routing normal de abajo.
    if pagina_actual == 9 and tecla not in (0, 1, 2, 3, 5, 6, 7):
        pagina_actual = 1
        forzar_redraw = True
        return

    # Navegación entre páginas (siempre activa)
    if tecla == 0:
        if pagina_actual != 1:
            pagina_actual = 1
            forzar_redraw = True
        return
    if tecla == 1:
        if pagina_actual != 2:
            pagina_actual = 2
            forzar_redraw = True
        return
    if tecla == 2:
        if pagina_actual != 3:
            pagina_actual = 3
            forzar_redraw = True
        return
    if tecla == 3:
        if pagina_actual != 4:
            pagina_actual = 4
            forzar_redraw = True
        return
    if tecla == 5:
        if pagina_actual != 6:
            pagina_actual = 6
            forzar_redraw = True
        return
    if tecla == 6:
        if pagina_actual != 7:
            pagina_actual = 7
            forzar_redraw = True
        return
    if tecla == 7:
        if pagina_actual != 8:
            pagina_actual = 8
            forzar_redraw = True
        return

    if pagina_actual == 1:
        # Tecla 31 SIS: abre página DOCKER (id 10)
        if tecla == 31:
            if pagina_actual != 10:
                pagina_actual = 10
                forzar_redraw = True
        # Teclas 20-23 SIS (panel clima): abre página CLIMA (id 11)
        elif tecla in (20, 21, 22, 23):
            if pagina_actual != 11:
                pagina_actual = 11
                forzar_redraw = True
        return

    if pagina_actual == 10:
        # 8..(8+N-1) → toggle start/stop del container correspondiente
        idx = tecla - 8
        if 0 <= idx < len(docker_info["containers"]):
            name, running, _ = docker_info["containers"][idx]
            cmd = "stop" if running else "start"
            try:
                subprocess.run(["docker", cmd, name], timeout=10,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print(f"[DOCKER] {cmd} {name}", flush=True)
            except Exception as e:
                print(f"[DOCKER] error {cmd} {name}: {e}", flush=True)
        return

    if pagina_actual == 2:
        # 16-20 → abrir 1..5 min · 24-27 → 15/30/60/120 min · 31 → cerrar
        mapa_largo = {24: 15, 25: 30, 26: 60, 27: 120}
        if 16 <= tecla <= 20:
            api_post_comando({"action": "open", "minutes": tecla - 15, "user": API_USER})
        elif tecla == 31:
            api_post_comando({"action": "close"})
        elif tecla in mapa_largo:
            api_post_comando({"action": "open", "minutes": mapa_largo[tecla], "user": API_USER})
        return

    if pagina_actual == 3:
        # Última columna vertical: 15=VOL+ · 23=MUTE · 31=VOL- · 22=PLAY
        if   tecla == 15: _run("pactl set-sink-volume @DEFAULT_SINK@ +5%")
        elif tecla == 23: _run("pactl set-sink-mute @DEFAULT_SINK@ toggle")
        elif tecla == 31: _run("pactl set-sink-volume @DEFAULT_SINK@ -5%")
        elif tecla == 22: _run("playerctl play-pause")
        return

    if pagina_actual == 4:
        if tecla in APPS_PAGINA:
            _lanzar(APPS_PAGINA[tecla][2])
        return

    if pagina_actual == 6:
        if tecla in WEB_PAGINA:
            url = WEB_PAGINA[tecla][2]
            _tipear_url(url)
        return

    if pagina_actual == 7:
        if tecla in KEYS_PAGINA:
            entry = KEYS_PAGINA[tecla]
            accion = entry[2]()
            if isinstance(accion, str):
                if KB_DISPONIBLE:
                    keyboard.type(accion)
            else:
                _enviar_combo(accion)
        return

    if pagina_actual == 8:
        if tecla in VENT_PAGINA:
            geom = VENT_PAGINA[tecla][5]
            try:
                subprocess.run(["wmctrl", "-r", ":ACTIVE:", "-b",
                                "remove,maximized_vert,maximized_horz"],
                               check=False, timeout=2)
                subprocess.run(["wmctrl", "-r", ":ACTIVE:", "-e", geom],
                               check=False, timeout=2)
            except Exception as e:
                print(f"[VENT] error wmctrl: {e}", flush=True)
        return

    if pagina_actual == 5:
        # Col 0 — Brillo (+ arriba, − abajo)
        if tecla == 8:
            brillo_actual = min(BRILLO_MAX, brillo_actual + BRILLO_PASO)
            try: deck.set_brightness(brillo_actual)
            except: pass
            print(f"[CONFIG] brillo_actual={brillo_actual}", flush=True)
            forzar_redraw = True
        elif tecla == 24:
            brillo_actual = max(BRILLO_MIN, brillo_actual - BRILLO_PASO)
            try: deck.set_brightness(brillo_actual)
            except: pass
            print(f"[CONFIG] brillo_actual={brillo_actual}", flush=True)
            forzar_redraw = True
        # Col 1 — Fallback a SIS (paso 1 min)
        elif tecla == 9:
            tiempo_fallback = min(TIEMPO_FALLBACK_MAX, tiempo_fallback + TIEMPO_PASO)
            print(f"[CONFIG] tiempo_fallback={tiempo_fallback}s", flush=True)
            forzar_redraw = True
        elif tecla == 25:
            tiempo_fallback = max(TIEMPO_FALLBACK_MIN, tiempo_fallback - TIEMPO_PASO)
            print(f"[CONFIG] tiempo_fallback={tiempo_fallback}s", flush=True)
            forzar_redraw = True
        # Col 2 — Dim por inactividad (paso 1 min)
        elif tecla == 10:
            tiempo_dim = min(TIEMPO_DIM_MAX, tiempo_dim + TIEMPO_PASO)
            print(f"[CONFIG] tiempo_dim={tiempo_dim}s", flush=True)
            forzar_redraw = True
        elif tecla == 26:
            tiempo_dim = max(TIEMPO_DIM_MIN, tiempo_dim - TIEMPO_PASO)
            print(f"[CONFIG] tiempo_dim={tiempo_dim}s", flush=True)
            forzar_redraw = True
        # Perfil visual (rota 1 → 2 → … → 1)
        elif tecla == 11:
            perfil_visual = (perfil_visual % PERFILES_TOTAL) + 1
            _gear_cache.clear(); _app_cache.clear()
            _web_cache.clear(); _keys_cache.clear(); _vent_cache.clear()
            _invalidar_render_cache()
            print(f"[CONFIG] perfil_visual={perfil_visual}", flush=True)
            forzar_redraw = True
        # Wallpaper: la rotación / apagado se maneja en boton_presionado
        # vía detección de press corto vs long-press (ver _wallpaper_evento).
        # Banner ON/OFF
        elif tecla == 13:
            banner_enabled = not banner_enabled
            print(f"[CONFIG] banner_enabled={banner_enabled}", flush=True)
            forzar_redraw = True
        # Perfil Kiosko: pasa este deck (B) a AWA. Lanza awa_kiosk pineado
        # al mismo serial como servicio transient, luego para streamdeb.
        elif tecla == 15:
            serial_b = DECK_SERIAL or ""
            print(f"[CONFIG] deck {serial_b} → AWA kiosko", flush=True)
            unit = f"streamdeb-kiosk-b-{int(time.time())}"
            cmd_arranque = (
                f"sleep 1.5 && "
                f"STREAMDEB_DECK_SERIAL={serial_b} STREAMDEB_FORCE_DARK=1 "
                f"/home/jfqp/Documents/GitHub/streamdeb/.venv/bin/python "
                f"/home/jfqp/Documents/GitHub/streamdeb/awa_kiosk.py"
            )
            subprocess.Popen(
                ["systemd-run", "--user", "--no-block",
                 f"--unit={unit}",
                 "--description=AWA kiosko en deck B",
                 "--setenv=DISPLAY=:0",
                 "--setenv=STREAMDEB_API_HOST=http://192.168.18.10",
                 "--setenv=STREAMDEB_API_USER=Dinamo",
                 "bash", "-lc", cmd_arranque],
                start_new_session=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            subprocess.Popen(
                ["systemctl", "--user", "stop", "streamdeb.service"],
                start_new_session=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        # X de apagado en config
        elif tecla == 31:
            try:
                deck.set_brightness(0)
                modo_dim_activo = True
            except: pass
        return

_sis_press_t       = None  # timestamp del press en tecla SIS (0)
_wallpaper_press_t = None  # timestamp del press en tecla wallpaper (CONF/12)
_pomo_press_t      = None  # timestamp del press en tecla Pomodoro (SIS/15)

def _wallpaper_evento(held):
    """Procesa la liberación de la tecla wallpaper. held = segundos pulsada."""
    global wallpaper_idx, forzar_redraw
    if held >= LONGPRESS_S:
        wallpaper_idx = 0
        print(f"[WALLPAPER] long-press {held:.1f}s → OFF", flush=True)
    else:
        total = wallpaper_total()
        if total <= 0:
            print("[WALLPAPER] sin imágenes disponibles", flush=True)
            return
        # 0→1, 1→2, …, total→1 (no vuelve a OFF por pulsación corta)
        wallpaper_idx = (wallpaper_idx % total) + 1
        print(f"[WALLPAPER] idx={wallpaper_idx}/{total}", flush=True)
    _invalidar_render_cache()
    forzar_redraw = True

def _sis_evento(held):
    """Tecla SIS (0): corta = página SIS, larga ≥2s = página CONF."""
    global pagina_actual, forzar_redraw
    destino = 5 if held >= LONGPRESS_S else 1
    etiqueta = "long→CONF" if destino == 5 else "short→SIS"
    if pagina_actual != destino:
        pagina_actual = destino
        forzar_redraw = True
    print(f"[NAV] SIS {etiqueta} ({held:.2f}s)", flush=True)

def boton_presionado(deck, tecla, estado):
    global ultimo_toque, _despertar, _wallpaper_press_t, _sis_press_t, _pomo_press_t
    ultimo_toque = time.time()

    # Tecla SIS (0): corta = SIS, larga ≥2s = CONF (en cualquier página)
    if tecla == 0 and not modo_dim_activo:
        if estado:
            _sis_press_t = time.time()
        else:
            t0 = _sis_press_t
            _sis_press_t = None
            if t0 is not None:
                threading.Thread(target=_sis_evento,
                                 args=(time.time() - t0,), daemon=True).start()
        return

    # Tecla Pomodoro (SIS/15): corta = avanza estado, larga ≥2s = reset
    if pagina_actual == 1 and tecla == 15 and not modo_dim_activo:
        if estado:
            _pomo_press_t = time.time()
        else:
            t0 = _pomo_press_t
            _pomo_press_t = None
            if t0 is not None:
                threading.Thread(target=_pomodoro_evento,
                                 args=(time.time() - t0,), daemon=True).start()
        return

    # Tecla wallpaper en CONF: corta = siguiente, larga ≥2s = OFF
    if pagina_actual == 5 and tecla == 12 and not modo_dim_activo:
        if estado:
            _wallpaper_press_t = time.time()
        else:
            t0 = _wallpaper_press_t
            _wallpaper_press_t = None
            if t0 is not None:
                threading.Thread(target=_wallpaper_evento,
                                 args=(time.time() - t0,), daemon=True).start()
        return

    if not estado:
        return
    if modo_dim_activo:
        _despertar = True
        return
    threading.Thread(target=_accion_boton, args=(deck, tecla), daemon=True).start()


# --- Inicialización ---

class DummyDeck:
    """Mock de StreamDeck XL para iteración visual sin hardware.
    Decodifica los bytes JPEG de cada tecla y los compone en un mosaico
    PNG (8x4) en PREVIEW_DIR/deck.png. Activado con `--dummy`."""
    KEY_COUNT = 32
    KEY_COLS  = 8
    KEY_ROWS  = 4
    KEY_W, KEY_H = 96, 96

    def __init__(self):
        self._keys = {}
        self._dirty = False
        self._depth = 0
        self._serial = "DUMMY-" + str(os.getpid())
        os.makedirs(PREVIEW_DIR, exist_ok=True)
        print(f"[DUMMY] preview dir: {PREVIEW_DIR}", flush=True)

    # API mínima usada por dashboard_pro
    def open(self): pass
    def close(self): pass
    def reset(self): self._keys.clear(); self._save_mosaic()
    def is_open(self): return True
    def is_visual(self): return True
    def is_touch(self): return False
    def connected(self): return True
    def key_count(self): return self.KEY_COUNT
    def key_image_format(self):
        return {"size": (self.KEY_W, self.KEY_H), "format": "JPEG",
                "rotation": 0, "flip": (False, False)}
    def key_layout(self): return (self.KEY_ROWS, self.KEY_COLS)
    def get_serial_number(self): return self._serial
    def get_firmware_version(self): return "DUMMY 1.0"
    def set_brightness(self, n): pass
    def set_poll_frequency(self, hz): pass
    def set_key_callback(self, cb): pass
    def set_key_image(self, k, native_bytes):
        self._keys[k] = native_bytes
        if self._depth == 0:
            self._save_mosaic()
        else:
            self._dirty = True

    # `with deck:` agrupa writes; salvamos el mosaico una sola vez por bloque
    def __enter__(self):
        self._depth += 1
        return self
    def __exit__(self, *a):
        self._depth = max(0, self._depth - 1)
        if self._depth == 0 and self._dirty:
            self._save_mosaic()
            self._dirty = False

    def _save_mosaic(self):
        try:
            mosaic = Image.new("RGB",
                               (self.KEY_W * self.KEY_COLS, self.KEY_H * self.KEY_ROWS),
                               "black")
            for k, b in self._keys.items():
                if not b:
                    continue
                try:
                    img = Image.open(BytesIO(b)).convert("RGB")
                    if img.size != (self.KEY_W, self.KEY_H):
                        img = img.resize((self.KEY_W, self.KEY_H), Image.LANCZOS)
                    row, col = k // self.KEY_COLS, k % self.KEY_COLS
                    mosaic.paste(img, (col * self.KEY_W, row * self.KEY_H))
                except Exception:
                    pass
            mosaic.save(os.path.join(PREVIEW_DIR, "deck.png"))
        except Exception as e:
            print(f"[DUMMY] mosaic error: {e}", flush=True)


def _abrir_deck():
    if DUMMY_MODE:
        d = DummyDeck()
        d.set_brightness(brillo_actual)
        return d
    try:
        decks = DeviceManager().enumerate()
        if not decks:
            return None
        d = None
        for cand in decks:
            try:
                cand.open()
            except Exception as e:
                print(f"[WARN] open: {e}", flush=True)
                continue
            try:
                serial = cand.get_serial_number()
            except Exception:
                serial = ""
            if DECK_SERIAL and serial != DECK_SERIAL:
                print(f"[SKIP] serial={serial} (busco {DECK_SERIAL})", flush=True)
                cand.close()
                continue
            d = cand
            print(f"[DECK] abierto serial={serial}", flush=True)
            break
        if d is None:
            return None
        time.sleep(0.3)
        d.reset()
        d.set_brightness(brillo_actual)
        try:
            d.set_poll_frequency(POLL_HZ)
        except Exception as e:
            print(f"[WARN] set_poll_frequency({POLL_HZ}): {e}", flush=True)
        # Introspección: usar layout del deck en vez de hardcode 8x4
        try:
            global DECK_COLS, DECK_ROWS
            rows, cols = d.key_layout()
            if (rows, cols) != (DECK_ROWS, DECK_COLS):
                _invalidar_render_cache()
            DECK_ROWS, DECK_COLS = rows, cols
            visual = "visual" if d.is_visual() else "no-visual"
            print(f"[DECK] layout={cols}x{rows} {visual} firmware={d.get_firmware_version()} poll={POLL_HZ}Hz", flush=True)
        except Exception as e:
            print(f"[WARN] introspección: {e}", flush=True)
        return d
    except Exception as e:
        print(f"[WARN] _abrir_deck: {e}", flush=True)
        return None


# --- Renderizado por página ---

def botones_navegacion(deck, tam):
    ahora = datetime.datetime.now()
    fecha = ahora.strftime("%d/%m/%y")
    hora  = ahora.strftime("%H:%M")
    if api_info["online"]:
        estado_awa = api_info["estado"].upper()
        if api_info["estado"] == "Abierta" and api_info.get("segundos", 0) > 0:
            cuenta_awa = _fmt_tiempo(api_info["segundos"])
        else:
            cuenta_awa = str(api_info["cuenta"])
    else:
        estado_awa = "OFFLINE"
        cuenta_awa = "---"
    media_vol = f"{volumen_actual}%"

    p1 = dibujar_boton_nav(deck, tam, "SIS",   fecha, hora,
                           color="#ffaa00", activo=(pagina_actual == 1))
    p2 = dibujar_boton_nav(deck, tam, "AWA",   estado_awa, cuenta_awa,
                           color="#00ddff", activo=(pagina_actual == 2))
    p3 = dibujar_boton_nav(deck, tam, "MEDIA", media_vol,
                           color="#cc66ff", activo=(pagina_actual == 3))
    p4 = dibujar_boton_app_nav(deck, tam, activo=(pagina_actual == 4))
    p_web  = dibujar_boton_web_nav(deck, tam, activo=(pagina_actual == 6))
    p_keys = dibujar_boton_keys_nav(deck, tam, activo=(pagina_actual == 7))
    p_vent = dibujar_boton_vent_nav(deck, tam, activo=(pagina_actual == 8))
    # CONF se entra con long-press ≥2s en SIS (no tiene nav button).
    return {0: p1, 1: p2, 2: p3, 3: p4, 5: p_web, 6: p_keys, 7: p_vent}

def _pomodoro_tick():
    """Avanza el estado: focus expira → break, break expira → idle.
    Devuelve (state, restante_s, total_s, color, label)."""
    global pomodoro_state, pomodoro_phase_t
    ahora = time.time()
    if pomodoro_state == "running":
        elapsed = ahora - pomodoro_phase_t
        if elapsed >= POMODORO_FOCUS_S:
            pomodoro_state = "break"
            pomodoro_phase_t = ahora
            elapsed = 0.0
            try:
                subprocess.Popen(["notify-send", "Pomodoro", "Foco completo · descanso",
                                   "-t", "8000"], env=_env_sesion(),
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception: pass
    if pomodoro_state == "break":
        elapsed = ahora - pomodoro_phase_t
        if elapsed >= POMODORO_BREAK_S:
            pomodoro_state = "idle"
            pomodoro_phase_t = 0.0
            try:
                subprocess.Popen(["notify-send", "Pomodoro", "Descanso terminado · listo",
                                   "-t", "8000"], env=_env_sesion(),
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception: pass

    if pomodoro_state == "running":
        rest = max(0, POMODORO_FOCUS_S - (ahora - pomodoro_phase_t))
        return ("running", rest, POMODORO_FOCUS_S, "#ff6644", "Foco")
    if pomodoro_state == "break":
        rest = max(0, POMODORO_BREAK_S - (ahora - pomodoro_phase_t))
        return ("break", rest, POMODORO_BREAK_S, "#33dd66", "Break")
    return ("idle", POMODORO_FOCUS_S, POMODORO_FOCUS_S, "#888888", "Pomo")


def _pomodoro_evento(held):
    """held >=2s = reset a idle. Tap corto = avanza estado."""
    global pomodoro_state, pomodoro_phase_t, forzar_redraw
    ahora = time.time()
    if held >= LONGPRESS_S:
        pomodoro_state = "idle"
        pomodoro_phase_t = 0.0
        print(f"[POMO] reset (long {held:.1f}s)", flush=True)
    else:
        if pomodoro_state == "idle":
            pomodoro_state = "running"
            pomodoro_phase_t = ahora
        elif pomodoro_state == "running":
            pomodoro_state = "idle"
            pomodoro_phase_t = 0.0
        elif pomodoro_state == "break":
            pomodoro_state = "idle"
            pomodoro_phase_t = 0.0
        print(f"[POMO] state={pomodoro_state}", flush=True)
    forzar_redraw = True


# --- Clima Arequipa: iconos por código WMO ---
def _clima_icono(code):
    """Mapea WMO weather_code a (iconify_name, color_hex)."""
    if code is None:
        return ("mdi:weather-cloudy-alert", "888888")
    if code == 0:                  return ("mdi:weather-sunny",            "ffcc33")
    if code in (1, 2):             return ("mdi:weather-partly-cloudy",    "ffaa66")
    if code == 3:                  return ("mdi:weather-cloudy",           "aaaaaa")
    if code in (45, 48):           return ("mdi:weather-fog",              "999999")
    if 51 <= code <= 57:           return ("mdi:weather-pouring",          "66aadd")
    if 61 <= code <= 67:           return ("mdi:weather-rainy",            "4488cc")
    if 71 <= code <= 77:           return ("mdi:weather-snowy",            "ddeeff")
    if 80 <= code <= 82:           return ("mdi:weather-pouring",          "4488cc")
    if 85 <= code <= 86:           return ("mdi:weather-snowy-heavy",      "ddeeff")
    if 95 <= code <= 99:           return ("mdi:weather-lightning",        "cc66ff")
    return ("mdi:weather-cloudy", "aaaaaa")

def _clima_descripcion(code):
    if code is None: return "—"
    return {
        0: "Despejado", 1: "Mayorment.", 2: "Parc nubl.", 3: "Nublado",
        45: "Niebla", 48: "Niebla esc",
        51: "Llov susv", 53: "Llov susv", 55: "Llov susv",
        61: "Lluvia",  63: "Lluvia",     65: "Lluv fuer",
        71: "Nieve",   73: "Nieve",      75: "Nieve int",
        80: "Chubasco",81: "Chubasco",   82: "Chub fuer",
        95: "Tormenta",96: "Torm gran",  99: "Torm gran",
    }.get(code, "—")

def render_pagina_sistema(deck, tam, last_net, cur_net):
    global max_visto_down, max_visto_up
    ahora = time.time()
    up_t  = ahora - psutil.boot_time()
    pct_u = (up_t % CICLO_UPTIME) / CICLO_UPTIME * 100
    h, m  = divmod(int(up_t // 60), 60)
    cpu_t = psutil.cpu_percent()
    cores = psutil.cpu_percent(percpu=True)
    ram   = psutil.virtual_memory().percent
    swp   = psutil.swap_memory().percent
    disk  = psutil.disk_usage('/')
    dn_kbps = ((cur_net.bytes_recv - last_net.bytes_recv) * 8) / 1024
    up_kbps = ((cur_net.bytes_sent - last_net.bytes_sent) * 8) / 1024
    max_visto_down = max(max_visto_down, dn_kbps)
    max_visto_up   = max(max_visto_up,   up_kbps)
    f_r = lambda v: f"{int(v/1000)}Mb" if v >= 1000 else f"{int(v)}Kb"

    nav = botones_navegacion(deck, tam)
    imgs = {
        **nav,
        # Fila 1: uptime, CPU total, C1-C4, ROOT
        8:  dibujar_panel_metrica(deck, tam, "Uptime", _fmt_tiempo(up_t), obtener_color_rango(pct_u), pct=pct_u),
        9:  dibujar_panel_metrica(deck, tam, "CPU T",  f"{int(cpu_t)}%", obtener_color_rango(cpu_t), pct=cpu_t),
        # Fila 2: RAM, SWAP, DISK
        16: dibujar_panel_metrica(deck, tam, "RAM",  f"{int(ram)}%", obtener_color_rango(ram), pct=ram),
        17: dibujar_panel_metrica(deck, tam, "SWAP", f"{int(swp)}%", obtener_color_rango(swp), pct=swp),
        18: dibujar_panel_metrica(deck, tam, "ROOT", f"{disk.free/(1024**3):.1f}G", obtener_color_rango(disk.percent), pct=disk.percent),
        # Fila 3: red
        24: dibujar_panel_metrica(deck, tam, "DOWN", f_r(dn_kbps), "#33ccff", pct=(dn_kbps/max_visto_down)*100),
        25: dibujar_panel_metrica(deck, tam, "UP",   f_r(up_kbps), "#0066ff", pct=(up_kbps/max_visto_up)*100),
        26: dibujar_panel_metrica(deck, tam, "Pública", _ip_2_lineas(net_info["ip_pub"]), "#33ccff"),
        27: dibujar_panel_metrica(deck, tam, "Local",   _ip_2_lineas(net_info["ip_loc"]), "#33ccff"),
    }
    for i, v in enumerate(cores[:4]):
        imgs[10+i] = dibujar_panel_metrica(deck, tam, f"C{i+1}", f"{int(v)}%", obtener_color_rango(v), pct=v)
    for idx, (cl, lb) in enumerate([("ping_gw","Gateway"),("ping_dns1","1.1.1.1"),("ping_dns2","8.8.8.8")]):
        ms = net_info[cl]
        if ms > 0:
            pct, color = _ping_pct_relativo(cl, ms)
            imgs[28+idx] = dibujar_panel_metrica(deck, tam, lb, f"{ms:.1f}", color, pct=pct, sub="ms")
        else:
            imgs[28+idx] = dibujar_panel_metrica(deck, tam, lb, "Err", "#666666", pct=0)

    # Tecla 15: Pomodoro (debajo de VENT)
    p_state, p_rest, p_total, p_color, p_label = _pomodoro_tick()
    p_pct = ((p_total - p_rest) / p_total * 100) if p_total > 0 else 0
    p_val = _fmt_tiempo(int(p_rest)) if p_state != "idle" else "READY"
    imgs[15] = dibujar_panel_metrica(deck, tam, p_label, p_val, p_color, pct=p_pct)

    # Teclas 20-23: Clima Arequipa (4 tiles)
    if clima_info["online"] and clima_info["temp"] is not None:
        ico_name, ico_color = _clima_icono(clima_info["weather_code"])
        ico_path = _iconify_png(ico_name, ico_color, 256)
        cond_txt = _clima_descripcion(clima_info["weather_code"])
        imgs[20] = dibujar_lanzador_web(deck, tam, cond_txt, "#" + ico_color, ico_path)
        imgs[21] = dibujar_panel_metrica(deck, tam, "Temp",
                                          f"{clima_info['temp']:.0f}°", "#ffaa66")
        imgs[22] = dibujar_panel_metrica(deck, tam, "Humedad",
                                          f"{int(clima_info['humedad'] or 0)}%", "#66aadd",
                                          sub=f"{int(clima_info['viento'] or 0)} km/h")
        tmin = int(round(clima_info['temp_min'] or 0))
        tmax = int(round(clima_info['temp_max'] or 0))
        imgs[23] = dibujar_panel_metrica(deck, tam, "Min/Max",
                                          f"{tmin}°/{tmax}°", "#cc66ff")
    else:
        imgs[20] = dibujar_panel_metrica(deck, tam, "Clima", "—", "#666666")
        imgs[21] = dibujar_panel_metrica(deck, tam, "AQP", "off", "#666666")
        imgs[22] = dibujar_panel_metrica(deck, tam, "API", "—", "#666666")
        imgs[23] = dibujar_panel_metrica(deck, tam, "Open-M.", "wait", "#666666")

    # Tecla 31: Entry a página DOCKER
    if docker_info["available"]:
        d_color = "#3399ff" if docker_info["running"] > 0 else "#666666"
        d_val = f"{docker_info['running']}/{len(docker_info['containers'])}"
    else:
        d_color = "#444444"
        d_val = "off"
    imgs[31] = dibujar_panel_metrica(deck, tam, "Docker", d_val, d_color)

    return imgs

DURACION_A_TECLA = {60:16, 120:17, 180:18, 240:19, 300:20,
                    900:24, 1800:25, 3600:26, 7200:27}
ACCIONES_LABELS = {16:"1 MIN", 17:"2 MIN", 18:"3 MIN", 19:"4 MIN", 20:"5 MIN",
                   24:"15 MIN", 25:"30 MIN", 26:"1 HORA", 27:"2 HORAS"}

def render_pagina_api(deck, tam):
    nav = botones_navegacion(deck, tam)
    online = api_info["online"]
    estado = api_info["estado"]
    abierta = (estado == "Abierta")
    cyan = "#00ddff"
    cuenta_color = "#666666" if not online else "#33ff33" if abierta else "#ff3333"
    admin_color = "#ff3333" if api_info["adminLocked"] else "#33ff33"
    admin_txt = "BLOQ" if api_info["adminLocked"] else "OK"
    tank_color = "#33ff33" if api_info["tankOnline"] else "#ff3333"
    tank_txt = f"{api_info['tankSignal']}/4" if api_info["tankOnline"] else "OFF"
    ms_api = net_info["ping_api"]
    if ms_api > 0:
        api_pct, api_color = _ping_pct_relativo("ping_api", ms_api)
        api_ping_btn = dibujar_panel_metrica(deck, tam, "Ping API", f"{ms_api:.1f}", api_color,
                                             pct=api_pct, sub="ms")
    else:
        api_ping_btn = dibujar_panel_metrica(deck, tam, "Ping API", "Err", "#666666", pct=0)

    # Determinar tecla activa y progreso de vaciado a partir del estado API
    active_key, active_drain = None, None
    if online and abierta:
        init_s = api_info.get("initial_seconds", 0)
        sec    = api_info.get("segundos", 0)
        if init_s > 0 and init_s in DURACION_A_TECLA:
            active_key   = DURACION_A_TECLA[init_s]
            active_drain = max(0.0, min(1.0, (init_s - sec) / init_s))

    def accion(tecla, label):
        if tecla == active_key:
            txt = _fmt_tiempo(api_info.get("segundos", 0))
            return dibujar_accion_pro(deck, tam, txt, cyan, drain=active_drain)
        return dibujar_accion_pro(deck, tam, label, cyan)

    imgs = {
        **nav,
        # Fila 1: estado API
        8:  dibujar_estado_pro(deck, tam, online, abierta),
        9:  dibujar_panel_2lineas(deck, tam, "Cuenta",  str(api_info["cuenta"]), cuenta_color),
        10: dibujar_panel_2lineas(deck, tam, "Modo",    str(api_info["modoNombre"]), cyan),
        11: dibujar_panel_info(deck, tam,    "Aper.",   str(api_info["contador"]), cyan),
        12: dibujar_panel_info(deck, tam,    "WiFi",    f"{api_info['wifiSignal']}/4", cyan),
        13: dibujar_panel_info(deck, tam,    "Tank",    tank_txt, tank_color),
        14: dibujar_panel_2lineas(deck, tam, "Usuario", api_info["usuario"], cyan),
        15: dibujar_panel_info(deck, tam,    "Admin",   admin_txt, admin_color),
        # Fila 2: acciones cortas + ping API en última columna
        16: accion(16, "1 MIN"),
        17: accion(17, "2 MIN"),
        18: accion(18, "3 MIN"),
        19: accion(19, "4 MIN"),
        20: accion(20, "5 MIN"),
        23: api_ping_btn,
        # Fila 3: acciones largas + CERRAR en última columna
        24: accion(24, "15 MIN"),
        25: accion(25, "30 MIN"),
        26: accion(26, "1 HORA"),
        27: accion(27, "2 HORAS"),
        31: dibujar_accion_pro(deck, tam, "CERRAR", "#ff3333", peligro=True),
    }
    return imgs

def render_pagina_media(deck, tam):
    nav = botones_navegacion(deck, tam)
    icon_volup   = _buscar_icono("audio-volume-high")
    icon_voldown = _buscar_icono("audio-volume-low")
    icon_mute    = _buscar_icono("audio-volume-muted" if mute_activo else "audio-volume-medium")
    icon_play    = _buscar_icono("media-playback-start")
    imgs = {
        **nav,
        # Última columna (col 7) vertical: VOL+ · MUTE · VOL-
        15: dibujar_lanzador_web(deck, tam, "VOL+", "#663399", icon_volup),
        23: dibujar_lanzador_web(deck, tam, "MUTE", "#cc0000", icon_mute),
        31: dibujar_lanzador_web(deck, tam, "VOL-", "#663399", icon_voldown),
        # PLAY 2 lugares a la derecha del centro
        22: dibujar_lanzador_web(deck, tam, "PLAY", "#0099ff", icon_play),
    }
    return imgs

def render_pagina_apps(deck, tam):
    imgs = dict(botones_navegacion(deck, tam))
    for tecla, (cat, label, _cmd, color, icono) in APPS_PAGINA.items():
        imgs[tecla] = dibujar_lanzador(deck, tam, cat, color, icono=icono, fallback=label)
    return imgs

def render_pagina_web(deck, tam):
    imgs = dict(botones_navegacion(deck, tam))
    for tecla, (label, _sub, url, color) in WEB_PAGINA.items():
        ico = _favicon_path(url)
        imgs[tecla] = dibujar_lanzador_web(deck, tam, label, color, ico)
    return imgs

def render_pagina_keys(deck, tam):
    imgs = dict(botones_navegacion(deck, tam))
    for tecla, (label, _combo, _keys, icono) in KEYS_PAGINA.items():
        path = _buscar_icono(icono) if icono else None
        imgs[tecla] = dibujar_lanzador_web(deck, tam, label, "#ffcc33", path)
    return imgs

# --- Clima: helpers de gradiente y dibujo de panel world-class ---
_TEMP_GRADIENT = [
    (-10, (59, 91, 219)), (0, (77, 171, 247)), (15, (169, 227, 75)),
    (22, (255, 212, 59)), (30, (255, 146, 43)), (38, (224, 49, 49)),
]

def _temp_color(t):
    if t is None: return (136, 136, 136)
    g = _TEMP_GRADIENT
    if t <= g[0][0]: return g[0][1]
    if t >= g[-1][0]: return g[-1][1]
    for i in range(len(g) - 1):
        (t1, c1), (t2, c2) = g[i], g[i + 1]
        if t1 <= t < t2:
            r = (t - t1) / (t2 - t1)
            return tuple(int(c1[k] + (c2[k] - c1[k]) * r) for k in range(3))
    return (255, 255, 255)

def _hex(rgb): return "#%02x%02x%02x" % rgb

def _icono_clima_pil(code, size):
    name, col = _clima_icono(code)
    p = _iconify_png(name, col, 256)
    if not p or not os.path.exists(p):
        return None
    try:
        ico = Image.open(p).convert("RGBA")
        return ico.resize((size, size), Image.LANCZOS)
    except Exception:
        return None

def _trocear_banner_en_imgs(imagen_full, tecla_base, W, H, cols, imgs):
    for i in range(cols):
        tile = imagen_full.crop((i * W, 0, (i + 1) * W, H)).convert("RGBA")
        tile._streamdeb_stable = False  # contenido cambia con datos clima
        imgs[tecla_base + i] = tile


def render_pagina_clima(deck, tam):
    """Panel world-class de clima Arequipa, 3 bandas:
    Fila 1 (8-15): Ahora — icono+temp grande izq, detalles + ciudad+hora der
    Fila 2 (16-23): Meteograma 12h — curva temp + barras lluvia
    Fila 3 (24-31): Strip horario 12h paso 2h
    """
    W, H = tam
    imgs = dict(botones_navegacion(deck, tam))
    horas = clima_info.get("hourly", [])

    # === BANDA 1: AHORA (768×96) ===
    banner = Image.new("RGB", (8 * W, H), (13, 27, 42))
    d = ImageDraw.Draw(banner)
    if clima_info.get("online") and clima_info.get("temp") is not None:
        # Izquierda: icono grande + temp + condición
        ico = _icono_clima_pil(clima_info["weather_code"], 64)
        if ico is not None:
            banner.paste(ico, (12, 16), ico)
        f_temp = ImageFont.truetype(FONT_PATH, 64)
        f_cond = ImageFont.truetype(FONT_PATH, 14)
        col_temp = _temp_color(clima_info["temp"])
        d.text((92, 36), f"{int(round(clima_info['temp']))}°",
               font=f_temp, fill=col_temp, anchor="lm")
        d.text((92, 78), _clima_descripcion(clima_info["weather_code"]),
               font=f_cond, fill=(180, 180, 180), anchor="lm")

        # Derecha: min/max grande + viento/humedad + ciudad+hora
        x_right = 8 * W - 16
        f_mm = ImageFont.truetype(FONT_PATH, 22)
        f_lbl = ImageFont.truetype(FONT_PATH, 11)
        f_det = ImageFont.truetype(FONT_PATH, 14)
        f_city = ImageFont.truetype(FONT_PATH, 12)

        tmin = clima_info.get("temp_min")
        tmax = clima_info.get("temp_max")
        if tmin is not None and tmax is not None:
            mm_txt = f"{int(round(tmin))}° / {int(round(tmax))}°"
            d.text((x_right, 22), "MIN/MAX", font=f_lbl, fill=(140, 140, 140), anchor="rm")
            d.text((x_right, 42), mm_txt, font=f_mm, fill=(220, 220, 220), anchor="rm")

        hum = clima_info.get("humedad") or 0
        vie = clima_info.get("viento") or 0
        d.text((x_right, 64), f"💧 {int(hum)}%   💨 {int(vie)} km/h",
               font=f_det, fill=(120, 180, 220), anchor="rm")

        ahora = datetime.datetime.now().strftime("%H:%M")
        d.text((x_right, 84), f"AREQUIPA · {ahora}",
               font=f_city, fill=(160, 160, 160), anchor="rm")
    else:
        f = ImageFont.truetype(FONT_PATH, 24)
        d.text((4 * W, H // 2), "Clima · sin datos",
               font=f, fill=(120, 120, 120), anchor="mm")
    _trocear_banner_en_imgs(banner, 8, W, H, 8, imgs)

    # === BANDA 2: METEOGRAMA 12h (768×96) ===
    meteo = Image.new("RGB", (8 * W, H), (10, 10, 10))
    d = ImageDraw.Draw(meteo)
    h12 = horas[:12]
    if len(h12) >= 2:
        temps = [h["temp"] for h in h12 if h.get("temp") is not None]
        precs = [(h.get("precip") or 0) for h in h12]
        if temps:
            tmin_g = min(temps)
            tmax_g = max(temps)
            rango = max(1.0, tmax_g - tmin_g)
            margen_x = 24
            graph_w = 8 * W - 2 * margen_x
            graph_top = 22
            graph_bot = H - 14
            graph_h = graph_bot - graph_top
            n = len(h12)

            def x_de(i): return margen_x + int(i * graph_w / (n - 1))
            def y_de(t): return graph_bot - int((t - tmin_g) / rango * graph_h)

            # Barras de lluvia (azul translúcido)
            for i, p in enumerate(precs):
                if p > 0:
                    bar_h = int(p / 100 * graph_h * 0.9)
                    cx = x_de(i)
                    alpha = max(60, int(p * 2.55))
                    d.rectangle((cx - 8, graph_bot - bar_h, cx + 8, graph_bot),
                                fill=(77, 171, 247))

            # Línea de temperatura con gradiente: dibujo segmento a segmento
            for i in range(n - 1):
                t0, t1 = h12[i].get("temp"), h12[i + 1].get("temp")
                if t0 is None or t1 is None: continue
                col = _temp_color((t0 + t1) / 2)
                d.line([(x_de(i), y_de(t0)), (x_de(i + 1), y_de(t1))],
                       fill=col, width=3)

            # Puntos en cada hora
            for i, h in enumerate(h12):
                t = h.get("temp")
                if t is None: continue
                col = _temp_color(t)
                cx, cy = x_de(i), y_de(t)
                d.ellipse((cx - 3, cy - 3, cx + 3, cy + 3), fill=col)

            # Etiquetas de eje: hora cada 3, en parte superior
            f_hr = ImageFont.truetype(FONT_PATH, 11)
            for i in range(0, n, 3):
                d.text((x_de(i), 8), h12[i]["hora"][:2] + "h",
                       font=f_hr, fill=(140, 140, 140), anchor="mm")
            # Etiquetas min/max temp en eje izquierdo
            f_t = ImageFont.truetype(FONT_PATH, 11)
            d.text((4, graph_top), f"{int(round(tmax_g))}°",
                   font=f_t, fill=(180, 180, 180), anchor="lm")
            d.text((4, graph_bot), f"{int(round(tmin_g))}°",
                   font=f_t, fill=(180, 180, 180), anchor="lm")
    else:
        f = ImageFont.truetype(FONT_PATH, 14)
        d.text((4 * W, H // 2), "meteograma sin datos",
               font=f, fill=(100, 100, 100), anchor="mm")
    _trocear_banner_en_imgs(meteo, 16, W, H, 8, imgs)

    # === BANDA 3: Strip horario 12h, paso 2h (8 tiles) ===
    paso = 2
    for i in range(8):
        h_idx = i * paso
        tecla = 24 + i
        if h_idx >= len(horas):
            imgs[tecla] = _nuevo_lienzo(tam)
            continue
        h = horas[h_idx]
        tile = Image.new("RGBA", tam, (10, 10, 10, 255))
        td = ImageDraw.Draw(tile)
        f_hr = ImageFont.truetype(FONT_PATH, 13)
        td.text((W // 2, 12), h["hora"][:2] + "h",
                font=f_hr, fill=(170, 170, 170), anchor="mm")
        t = h.get("temp")
        if t is not None:
            f_t = ImageFont.truetype(FONT_PATH, 26)
            td.text((W // 2, 38), f"{int(round(t))}°",
                    font=f_t, fill=_temp_color(t), anchor="mm")
        ico = _icono_clima_pil(h.get("code"), 30)
        if ico is not None:
            tile.paste(ico, ((W - 30) // 2, 56), ico)
        # Prob lluvia solo si > 40%
        p = h.get("precip") or 0
        if p > 40:
            f_p = ImageFont.truetype(FONT_PATH, 11)
            td.text((W - 4, H - 4), f"{int(p)}%",
                    font=f_p, fill=(77, 171, 247), anchor="rb")
        imgs[tecla] = tile
    return imgs


def render_pagina_docker(deck, tam):
    """Lista hasta 24 containers en filas 1-3, 8 cols. Tap → start/stop."""
    imgs = dict(botones_navegacion(deck, tam))
    containers = docker_info["containers"][:24]  # 32 - 8 nav = 24 max
    for i, (name, running, _img) in enumerate(containers):
        tecla = 8 + i  # 8..31
        color = "#33dd66" if running else "#888888"
        # Acortar nombre a 10 chars max para que entre
        label = (name[:10] + "…") if len(name) > 11 else name
        sub = "ON" if running else "off"
        imgs[tecla] = dibujar_panel_metrica(deck, tam, label, sub, color)
    return imgs


def render_pagina_banner(deck, tam):
    """Pantalla idle: imagen full-deck (cols*W × rows*H) con reloj grande,
    fecha, CPU%/RAM% y estado AWA. Se trocea en 32 tiles RGBA para set_key_image."""
    W, H = tam
    full = Image.new("RGB", (DECK_COLS * W, DECK_ROWS * H), "black")
    d = ImageDraw.Draw(full)

    ahora = datetime.datetime.now()
    hora = ahora.strftime("%H:%M")
    fecha = ahora.strftime("%a %d %b %Y").upper()

    cw, ch = full.size
    # Reloj grande
    fclock = ImageFont.truetype(FONT_PATH, int(H * 1.9))
    d.text((cw // 2, int(ch * 0.42)), hora, font=fclock, fill="#ffffff", anchor="mm")
    # Fecha bajo el reloj
    ffecha = ImageFont.truetype(FONT_PATH, int(H * 0.42))
    d.text((cw // 2, int(ch * 0.78)), fecha, font=ffecha, fill="#888888", anchor="mm")

    # Stats inferior izquierda
    cpu = int(psutil.cpu_percent())
    ram = int(psutil.virtual_memory().percent)
    fstats = ImageFont.truetype(FONT_PATH, int(H * 0.30))
    d.text((W // 2, ch - int(H * 0.35)),
           f"CPU {cpu}%   RAM {ram}%",
           font=fstats, fill="#33ccff", anchor="lm")

    # Estado AWA inferior derecha
    if api_info.get("online"):
        awa_txt = api_info["estado"].upper()
        awa_col = "#33ff33" if api_info["estado"] == "Abierta" else "#ff3333"
    else:
        awa_txt = "AWA OFFLINE"
        awa_col = "#666666"
    d.text((cw - W // 2, ch - int(H * 0.35)),
           awa_txt, font=fstats, fill=awa_col, anchor="rm")

    # Marca arriba a la derecha (toca cualquier tecla)
    fhint = ImageFont.truetype(FONT_PATH, int(H * 0.20))
    d.text((cw - 12, int(H * 0.30)), "tap any key", font=fhint, fill="#444444", anchor="rm")

    # Trocear en tiles
    imgs = {}
    for k in range(DECK_COLS * DECK_ROWS):
        row, col = k // DECK_COLS, k % DECK_COLS
        tile = full.crop((col * W, row * H, (col + 1) * W, (row + 1) * H)).convert("RGBA")
        imgs[k] = tile
    return imgs

def render_pagina_vent(deck, tam):
    imgs = dict(botones_navegacion(deck, tam))
    for tecla, (label, x_ini, x_fin, y_ini, y_fin, _geom) in VENT_PAGINA.items():
        # Tono base por ancho (tercios cyan, mitades violeta);
        # más tenue cuando es media-altura, para distinguir filas de un vistazo.
        es_mitad_x = (x_fin - x_ini) > 0.34
        es_alto_completo = (y_fin - y_ini) > 0.99
        if es_mitad_x:
            color = "#cc66ff" if es_alto_completo else "#aa55cc"
        else:
            color = "#66ddff" if es_alto_completo else "#4499bb"
        imgs[tecla] = dibujar_vent_preview(deck, tam, label, x_ini, x_fin, y_ini, y_fin, color)
    return imgs

def render_pagina_config(deck, tam):
    nav = botones_navegacion(deck, tam)
    fb_pct  = (tiempo_fallback - TIEMPO_FALLBACK_MIN) / (TIEMPO_FALLBACK_MAX - TIEMPO_FALLBACK_MIN) * 100
    dim_pct = (tiempo_dim - TIEMPO_DIM_MIN) / (TIEMPO_DIM_MAX - TIEMPO_DIM_MIN) * 100
    imgs = {
        **nav,
        # Col 0 — Brillo (+ arriba, valor en medio, − abajo)
        8:  dibujar_panel_metrica(deck, tam, "Brillo", "+", "#ffaa00"),
        16: dibujar_panel_metrica(deck, tam, "Brillo", f"{brillo_actual}%", "#ffaa00", pct=brillo_actual),
        24: dibujar_panel_metrica(deck, tam, "Brillo", "−", "#ffaa00"),
        # Col 1 — Fallback a SIS
        9:  dibujar_panel_metrica(deck, tam, "Fallback", "+", "#33ccff"),
        17: dibujar_panel_metrica(deck, tam, "Fallback", _fmt_tiempo(tiempo_fallback), "#33ccff", pct=fb_pct),
        25: dibujar_panel_metrica(deck, tam, "Fallback", "−", "#33ccff"),
        # Col 2 — Dim por inactividad
        10: dibujar_panel_metrica(deck, tam, "Dim", "+", "#cc66ff"),
        18: dibujar_panel_metrica(deck, tam, "Dim", _fmt_tiempo(tiempo_dim), "#cc66ff", pct=dim_pct),
        26: dibujar_panel_metrica(deck, tam, "Dim", "−", "#cc66ff"),
        # Col 3 — Perfil visual (rota entre 1, 2, …)
        11: dibujar_panel_metrica(deck, tam, "Perfil V", f"{perfil_visual}", "#33ff99"),
        # Col 4 — Wallpaper: corto = siguiente, ≥2s = OFF
        12: dibujar_panel_metrica(deck, tam, "Wallpaper",
                                   "OFF" if wallpaper_idx == 0
                                   else f"{wallpaper_idx}/{wallpaper_total()}",
                                   "#666666" if wallpaper_idx == 0 else "#ff66cc"),
        # Col 5 — Banner idle ON/OFF (toggle)
        13: dibujar_panel_metrica(deck, tam, "Banner",
                                   "ON" if banner_enabled else "OFF",
                                   "#ffaa66" if banner_enabled else "#666666"),
        # Col 7 fila 1 — perfil Kiosko (justo debajo del gear CONF)
        15: dibujar_panel_metrica(deck, tam, "Perfil", "Kiosko", "#00ddff"),
        # Cols 3-6 (rows 1-3) libres para futuras configuraciones
        # X de apagado en esquina inferior derecha
        31: dibujar_boton_x(deck, tam),
    }
    return imgs


# --- Loop principal ---

def iniciar_dashboard():
    global modo_dim_activo, _despertar, forzar_redraw, pagina_actual

    deck = None
    while deck is None:
        deck = _abrir_deck()
        if deck is None:
            print("[WAIT] buscando Stream Deck...", flush=True)
            time.sleep(2)
    print("[OK] Stream Deck listo", flush=True)

    tam = deck.key_image_format()['size']
    deck.set_key_callback(boton_presionado)
    threading.Thread(target=tareas_red_fondo, daemon=True).start()
    threading.Thread(target=tareas_api_fondo, daemon=True).start()
    threading.Thread(target=tareas_docker_fondo, daemon=True).start()
    threading.Thread(target=tareas_clima_fondo, daemon=True).start()
    threading.Thread(target=tareas_pomodoro_fondo, daemon=True).start()
    last_net = psutil.net_io_counters()
    pagina_anterior = None

    try:
        while True:
            ahora = time.time()

            if _despertar:
                try:
                    deck.set_brightness(brillo_actual)
                    modo_dim_activo = False
                except Exception: pass
                _despertar = False

            # Fallback por inactividad: a banner si activado, si no a SIS.
            # Excluyo WEB(6) y KEYS(7) — uso prolongado — y banner (9) consigo mismo.
            if (pagina_actual not in (6, 7, 9)
                    and (ahora - ultimo_toque) > tiempo_fallback):
                pagina_actual = 9 if banner_enabled else 1
                forzar_redraw = True

            # Auto-dim por inactividad
            if not modo_dim_activo and (ahora - ultimo_toque) > tiempo_dim:
                try: deck.set_brightness(0)
                except: pass
                modo_dim_activo = True

            # Si está dim (manual via X o auto), no renderizar
            if modo_dim_activo:
                time.sleep(1)
                continue

            try:
                cur_net = psutil.net_io_counters()
                if pagina_actual == 1:
                    imgs = render_pagina_sistema(deck, tam, last_net, cur_net)
                elif pagina_actual == 2:
                    imgs = render_pagina_api(deck, tam)
                elif pagina_actual == 3:
                    imgs = render_pagina_media(deck, tam)
                elif pagina_actual == 4:
                    imgs = render_pagina_apps(deck, tam)
                elif pagina_actual == 6:
                    imgs = render_pagina_web(deck, tam)
                elif pagina_actual == 7:
                    imgs = render_pagina_keys(deck, tam)
                elif pagina_actual == 8:
                    imgs = render_pagina_vent(deck, tam)
                elif pagina_actual == 9:
                    imgs = render_pagina_banner(deck, tam)
                elif pagina_actual == 10:
                    imgs = render_pagina_docker(deck, tam)
                elif pagina_actual == 11:
                    imgs = render_pagina_clima(deck, tam)
                else:
                    imgs = render_pagina_config(deck, tam)
                last_net = cur_net

                # `with deck:` agrupa writes en un bloque atómico (lock interno
                # de la librería) — más robusto frente a reconexión USB y
                # señaliza al DummyDeck cuándo redibujar el mosaico.
                with deck:
                    if pagina_actual != pagina_anterior or forzar_redraw:
                        if pagina_actual != pagina_anterior:
                            # Cambio de página: descarta el dedup (mismo tecla
                            # con contenido distinto fuerza redraw real).
                            _last_sent.clear()
                        for k in range(deck.key_count()):
                            if k not in imgs:
                                _push_key(deck, k, _finalizar(deck, tam, None, k))
                        pagina_anterior = pagina_actual
                        forzar_redraw = False

                    for key, img in imgs.items():
                        _push_key(deck, key, _finalizar(deck, tam, img, key))

            except Exception as e:
                print(f"[ERR] {e} — intentando reconectar...", flush=True)
                try: deck.close()
                except: pass
                deck = None
                time.sleep(2)
                while deck is None:
                    deck = _abrir_deck()
                    if deck is None:
                        print("[WAIT] esperando deck...", flush=True)
                        time.sleep(2)
                tam = deck.key_image_format()['size']
                deck.set_key_callback(boton_presionado)
                pagina_anterior = None
                _invalidar_render_cache()
                print("[OK] reconectado", flush=True)

            time.sleep(1)

    finally:
        try: deck.reset()
        except: pass
        try: deck.close()
        except: pass


if __name__ == "__main__":
    import signal
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt))
    try:
        iniciar_dashboard()
    except KeyboardInterrupt:
        pass
