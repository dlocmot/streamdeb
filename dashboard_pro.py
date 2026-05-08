import os
import re
import math
import time
import json
import datetime
import psutil
import subprocess
import threading
import socket
import urllib.request
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
pagina_actual = 1     # 1=sistema · 2=API · 3=multimedia · 4=apps · 5=configuración
forzar_redraw = False
brillo_actual    = 75
tiempo_fallback  = 300    # s sin interacción en otra pág. → vuelve a SIS
tiempo_dim       = 1800   # s sin interacción → atenúa el deck
perfil_visual    = 1      # 1 = con marcos · 2 = sin marco externo
PERFILES_TOTAL   = 2


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

# --- Wallpaper (toggle ON/OFF, hardcoded URL) ---
WALLPAPER_URL  = "https://external-content.duckduckgo.com/iu/?u=http%3A%2F%2Fhdqwalls.com%2Fwallpapers%2F4k-galaxy-space-i9.jpg&f=1&nofb=1&ipt=a34e3f52a05088bb055f2d3454bbf78e0d3d0e6eb504c5fc2881705a4e07e5ce"
WALLPAPER_PATH = os.path.expanduser("~/.cache/streamdeb/wallpaper.jpg")
DECK_COLS, DECK_ROWS = 8, 4
WALLPAPER_BRILLO = 0.5      # 1.0 = original · 0.5 = 50%
wallpaper_on    = False
_wallpaper_full = None     # PIL RGB redimensionado a (cols*W, rows*H)
_wallpaper_size = None     # (W, H) por tile cacheado

def _wallpaper_descargar():
    if os.path.exists(WALLPAPER_PATH) and os.path.getsize(WALLPAPER_PATH) > 1000:
        return True
    try:
        os.makedirs(os.path.dirname(WALLPAPER_PATH), exist_ok=True)
        req = urllib.request.Request(WALLPAPER_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read()
        with open(WALLPAPER_PATH, "wb") as f:
            f.write(data)
        return True
    except Exception as e:
        print(f"[WALLPAPER] error descarga: {e}", flush=True)
        return False

def _wallpaper_cargar(tamaño):
    """Asegura que _wallpaper_full está listo y dimensionado a (cols*W, rows*H)."""
    global _wallpaper_full, _wallpaper_size
    if _wallpaper_full is not None and _wallpaper_size == tamaño:
        return _wallpaper_full
    if not _wallpaper_descargar():
        return None
    try:
        img = Image.open(WALLPAPER_PATH).convert("RGB")
        total = (DECK_COLS * tamaño[0], DECK_ROWS * tamaño[1])
        img = img.resize(total, Image.LANCZOS)
        if WALLPAPER_BRILLO != 1.0:
            img = ImageEnhance.Brightness(img).enhance(WALLPAPER_BRILLO)
        _wallpaper_full = img
        _wallpaper_size = tamaño
        return _wallpaper_full
    except Exception as e:
        print(f"[WALLPAPER] error cargando: {e}", flush=True)
        return None

def _wallpaper_tile(tamaño, tecla):
    full = _wallpaper_cargar(tamaño)
    if full is None or tecla is None:
        return None
    row, col = tecla // DECK_COLS, tecla % DECK_COLS
    box = (col * tamaño[0], row * tamaño[1],
           (col + 1) * tamaño[0], (row + 1) * tamaño[1])
    return full.crop(box).copy()

def _finalizar(deck, tamaño, imagen_rgba, tecla):
    """Compone PIL RGBA sobre el tile de wallpaper (si está ON) o negro,
    y devuelve los bytes nativos. Si imagen_rgba es None, devuelve solo
    el fondo (tile o negro) — útil para teclas vacías."""
    if wallpaper_on:
        tile = _wallpaper_tile(tamaño, tecla)
        fondo = tile if tile is not None else Image.new("RGB", tamaño, "black")
    else:
        fondo = Image.new("RGB", tamaño, "black")
    if imagen_rgba is not None:
        fondo.paste(imagen_rgba, (0, 0), imagen_rgba)
    return PILHelper.to_native_format(deck, fondo)

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
    imagen = _nuevo_lienzo(tamaño)
    dibujo = ImageDraw.Draw(imagen)
    rect = (4, 4, tamaño[0]-5, tamaño[1]-5)
    f_tit = ImageFont.truetype(FONT_PATH, 13)
    if not online:
        color, texto = "#666666", "OFFLINE"
        if _con_marco():
            dibujo.rounded_rectangle(rect, radius=10, outline=color, width=2)
    elif abierta:
        color, texto = "white", "ABIERTA"
        dibujo.rounded_rectangle(rect, radius=10, fill="#22aa33")
    else:
        color, texto = "#ff3333", "CERRADA"
        if _con_marco():
            dibujo.rounded_rectangle(rect, radius=10, outline=color, width=3)
    dibujo.text((tamaño[0]//2, 16), "Estado", font=f_tit, fill=color, anchor="mm")
    dibujo.line((10, 28, tamaño[0]-11, 28), fill=color, width=1)
    f_val = _fit_font(dibujo, texto, tamaño[0]-18, 20, 12)
    dibujo.text((tamaño[0]//2, 60), texto, font=f_val, fill=color, anchor="mm")
    return imagen

def dibujar_accion_pro(deck, tamaño, texto, color, peligro=False, drain=None):
    """Acción con marco redondeado. drain en [0,1]: 0=lleno (recién pulsado),
    1=vaciado completo. None = estado inactivo (fondo oscuro)."""
    imagen = _nuevo_lienzo(tamaño)
    dibujo = ImageDraw.Draw(imagen)
    rect = (4, 4, tamaño[0]-5, tamaño[1]-5)

    if peligro:
        dibujo.rounded_rectangle(rect, radius=10, fill=color)
    elif drain is None:
        dibujo.rounded_rectangle(rect, radius=10, fill="#001a26")
        if _con_marco():
            dibujo.rounded_rectangle(rect, radius=10, outline=color, width=2)
    else:
        d = max(0.0, min(1.0, drain))
        # Base oscura
        dibujo.rounded_rectangle(rect, radius=10, fill="#001a26")
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
    global tiempo_fallback, tiempo_dim, perfil_visual, wallpaper_on

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
        if pagina_actual != 5:
            pagina_actual = 5
            forzar_redraw = True
        return

    if pagina_actual == 1:
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
            _web_cache.clear(); _keys_cache.clear()
            print(f"[CONFIG] perfil_visual={perfil_visual}", flush=True)
            forzar_redraw = True
        # Wallpaper ON/OFF
        elif tecla == 12:
            wallpaper_on = not wallpaper_on
            print(f"[CONFIG] wallpaper_on={wallpaper_on}", flush=True)
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

def boton_presionado(deck, tecla, estado):
    global ultimo_toque, _despertar
    if not estado:
        return
    ultimo_toque = time.time()
    if modo_dim_activo:
        _despertar = True
        return
    threading.Thread(target=_accion_boton, args=(deck, tecla), daemon=True).start()


# --- Inicialización ---

def _abrir_deck():
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
    gear = dibujar_boton_gear(deck, tam, activo=(pagina_actual == 5))
    return {0: p1, 1: p2, 2: p3, 3: p4, 5: p_web, 6: p_keys, 7: gear}

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
        # Col 4 — Wallpaper ON/OFF
        12: dibujar_panel_metrica(deck, tam, "Wallpaper", "ON" if wallpaper_on else "OFF",
                                   "#ff66cc" if wallpaper_on else "#666666"),
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

            # Fallback a SIS si lleva mucho rato en otra página sin interacción.
            # Excluyo WEB(6) y KEYS(7) — son páginas de uso prolongado.
            if (pagina_actual not in (1, 6, 7)
                    and (ahora - ultimo_toque) > tiempo_fallback):
                pagina_actual = 1
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
                else:
                    imgs = render_pagina_config(deck, tam)
                last_net = cur_net

                if pagina_actual != pagina_anterior or forzar_redraw:
                    for k in range(deck.key_count()):
                        if k not in imgs:
                            deck.set_key_image(k, _finalizar(deck, tam, None, k))
                    pagina_anterior = pagina_actual
                    forzar_redraw = False

                for key, img in imgs.items():
                    deck.set_key_image(key, _finalizar(deck, tam, img, key))

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
