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
from PIL import Image, ImageDraw, ImageFont
from StreamDeck.DeviceManager import DeviceManager
from StreamDeck.ImageHelpers import PILHelper

try:
    from pynput.keyboard import Controller
    keyboard = Controller()
    KB_DISPONIBLE = True
except Exception as e:
    print(f"[WARN] pynput no disponible: {e}")
    KB_DISPONIBLE = False

# --- CONFIGURACIÓN ---
FONT_PATH    = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
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
    8:  ("Dev",   "Term",    "mate-terminal",                                "#33ccff", "utilities-terminal"),
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
    25: ("Util",  "SysMon",  "mate-system-monitor",                          "#aaaaaa", "utilities-system-monitor"),
    26: ("Util",  "VBox",    "VirtualBox",                                   "#aaaaaa", "virtualbox"),
}


# --- Carga y resolución de iconos ---

import glob as _glob

_ICONO_BASES = (
    "/var/lib/flatpak/exports/share/icons/hicolor",
    os.path.expanduser("~/.local/share/icons/hicolor"),
    "/usr/share/icons/hicolor",
    "/usr/share/icons/gnome",
)
_ICONO_TAMS = ("512x512", "256x256", "128x128", "96x96", "64x64", "48x48")
_icono_cache = {}

def _buscar_icono(nombre):
    if not nombre:
        return None
    if os.path.isabs(nombre):
        return nombre if os.path.exists(nombre) else None
    for base in _ICONO_BASES:
        for size in _ICONO_TAMS:
            p = f"{base}/{size}/apps/{nombre}.png"
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

def obtener_color_rango(valor):
    if valor < 30: return "#33ff33"
    elif valor <= 80: return "#ffaa00"
    else: return "#ff3333"

def dibujar_panel_metrica(deck, tamaño, titulo, valor, color, pct=None, valor_color=None, sub=None):
    """Estilo unificado SIS: marco redondeado + título separado + valor + barra inferior."""
    imagen = Image.new("RGB", tamaño, "black")
    dibujo = ImageDraw.Draw(imagen)
    rect = (4, 4, tamaño[0]-5, tamaño[1]-5)
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
    return PILHelper.to_native_format(deck, imagen)

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
    imagen = Image.new("RGB", tamaño, "black")
    dibujo = ImageDraw.Draw(imagen)
    f_btn = ImageFont.truetype(FONT_PATH, 18)
    rect  = (5, 5, tamaño[0]-6, tamaño[1]-6)
    if relleno:
        dibujo.rounded_rectangle(rect, radius=12, fill=color)
        dibujo.text((tamaño[0]//2, tamaño[1]//2), texto, font=f_btn, fill="black", anchor="mm")
    else:
        dibujo.rounded_rectangle(rect, radius=12, outline=color, width=3)
        dibujo.text((tamaño[0]//2, tamaño[1]//2), texto, font=f_btn, fill="white", anchor="mm")
    return PILHelper.to_native_format(deck, imagen)

def _fit_font(dibujo, txt, max_width, max_size, min_size=10):
    for size in range(max_size, min_size - 1, -1):
        f = ImageFont.truetype(FONT_PATH, size)
        if dibujo.textlength(txt, font=f) <= max_width:
            return f
    return ImageFont.truetype(FONT_PATH, min_size)

def dibujar_panel_info(deck, tamaño, titulo, valor, frame_color, valor_color="#ffffff"):
    imagen = Image.new("RGB", tamaño, "black")
    dibujo = ImageDraw.Draw(imagen)
    rect = (4, 4, tamaño[0]-5, tamaño[1]-5)
    dibujo.rounded_rectangle(rect, radius=10, outline=frame_color, width=2)
    f_tit = ImageFont.truetype(FONT_PATH, 13)
    dibujo.text((tamaño[0]//2, 16), titulo, font=f_tit, fill=frame_color, anchor="mm")
    dibujo.line((10, 28, tamaño[0]-11, 28), fill=frame_color, width=1)
    txt = str(valor)
    f_val = _fit_font(dibujo, txt, tamaño[0]-16, 22, 11)
    dibujo.text((tamaño[0]//2, 60), txt, font=f_val, fill=valor_color, anchor="mm")
    return PILHelper.to_native_format(deck, imagen)

def dibujar_panel_2lineas(deck, tamaño, titulo, valor, frame_color, valor_color="#ffffff"):
    imagen = Image.new("RGB", tamaño, "black")
    dibujo = ImageDraw.Draw(imagen)
    rect = (4, 4, tamaño[0]-5, tamaño[1]-5)
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
    return PILHelper.to_native_format(deck, imagen)

def dibujar_estado_pro(deck, tamaño, online, abierta):
    imagen = Image.new("RGB", tamaño, "black")
    dibujo = ImageDraw.Draw(imagen)
    rect = (4, 4, tamaño[0]-5, tamaño[1]-5)
    f_tit = ImageFont.truetype(FONT_PATH, 13)
    if not online:
        color, texto = "#666666", "OFFLINE"
        dibujo.rounded_rectangle(rect, radius=10, outline=color, width=2)
    elif abierta:
        color, texto = "white", "ABIERTA"
        dibujo.rounded_rectangle(rect, radius=10, fill="#22aa33")
    else:
        color, texto = "#ff3333", "CERRADA"
        dibujo.rounded_rectangle(rect, radius=10, outline=color, width=3)
    dibujo.text((tamaño[0]//2, 16), "Estado", font=f_tit, fill=color, anchor="mm")
    dibujo.line((10, 28, tamaño[0]-11, 28), fill=color, width=1)
    f_val = _fit_font(dibujo, texto, tamaño[0]-18, 20, 12)
    dibujo.text((tamaño[0]//2, 60), texto, font=f_val, fill=color, anchor="mm")
    return PILHelper.to_native_format(deck, imagen)

def dibujar_accion_pro(deck, tamaño, texto, color, peligro=False, drain=None):
    """Acción con marco redondeado. drain en [0,1]: 0=lleno (recién pulsado),
    1=vaciado completo. None = estado inactivo (fondo oscuro)."""
    imagen = Image.new("RGB", tamaño, "black")
    dibujo = ImageDraw.Draw(imagen)
    rect = (4, 4, tamaño[0]-5, tamaño[1]-5)

    if peligro:
        dibujo.rounded_rectangle(rect, radius=10, fill=color)
    elif drain is None:
        dibujo.rounded_rectangle(rect, radius=10, fill="#001a26", outline=color, width=2)
    else:
        d = max(0.0, min(1.0, drain))
        # Base oscura
        dibujo.rounded_rectangle(rect, radius=10, fill="#001a26")
        if d < 1.0:
            # Capa de agua (rect redondeado lleno) + máscara que recorta
            # solo la franja inferior — efecto "el agua baja al vaciarse".
            water = Image.new("RGB", tamaño, "black")
            wd = ImageDraw.Draw(water)
            wd.rounded_rectangle(rect, radius=10, fill=color)
            mask = Image.new("L", tamaño, 0)
            md = ImageDraw.Draw(mask)
            water_top = int(4 + (tamaño[1] - 8) * d)
            md.rectangle((0, water_top, tamaño[0], tamaño[1]), fill=255)
            imagen = Image.composite(water, imagen, mask)
            dibujo = ImageDraw.Draw(imagen)
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
    return PILHelper.to_native_format(deck, imagen)

def dibujar_boton_nav(deck, tamaño, titulo, sub1=None, sub2=None, color="#33ccff", activo=False):
    """Botón de navegación con título y hasta 2 sublíneas opcionales."""
    imagen = Image.new("RGB", tamaño, "black")
    dibujo = ImageDraw.Draw(imagen)
    rect = (5, 5, tamaño[0]-6, tamaño[1]-6)
    if activo:
        dibujo.rounded_rectangle(rect, radius=12, fill=color)
        title_color = "black"
        sub_color   = "black"
    else:
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
    return PILHelper.to_native_format(deck, imagen)

_gear_cache = {}
_app_cache = {}
GEAR_ICON_PATHS = (
    "/usr/share/icons/gnome/256x256/categories/preferences-system.png",
    "/usr/share/icons/mate/256x256/categories/preferences-system.png",
    "/usr/share/icons/gnome/256x256/categories/applications-system.png",
)
APP_NAV_ICON_PATHS = (
    "/usr/share/icons/gnome/256x256/places/start-here.png",
)

def _dibujar_btn_icono_nav(deck, tamaño, paths, color, titulo, activo, cache):
    """Botón de navegación con header (título + separador) e icono colorido en la
    zona inferior, mismo estilo que el resto de nav. Cache por (tamaño, activo, titulo)."""
    cache_key = (tamaño, activo, titulo)
    if cache_key in cache:
        return cache[cache_key]
    imagen = Image.new("RGB", tamaño, "black")
    dibujo = ImageDraw.Draw(imagen)
    rect = (5, 5, tamaño[0]-6, tamaño[1]-6)
    if activo:
        dibujo.rounded_rectangle(rect, radius=12, fill=color)
        title_color, sep_color = "black", "black"
    else:
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
        lado = min(tamaño[0] - 18, zone_h - 2)
        icono.thumbnail((lado, lado), Image.LANCZOS)
        ix = (tamaño[0] - icono.width) // 2
        iy = zone_top + (zone_h - icono.height) // 2
        imagen.paste(icono, (ix, iy), icono)
    out = PILHelper.to_native_format(deck, imagen)
    cache[cache_key] = out
    return out

def dibujar_lanzador(deck, tamaño, categoria, color, icono=None, fallback=None):
    """Lanzador de app: marco redondeado + título (categoría) + separador + icono
    centrado debajo. Si no hay icono disponible cae a texto fallback."""
    imagen = Image.new("RGB", tamaño, "black")
    dibujo = ImageDraw.Draw(imagen)
    rect = (4, 4, tamaño[0]-5, tamaño[1]-5)
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
    return PILHelper.to_native_format(deck, imagen)

def dibujar_boton_gear(deck, tamaño, activo=False):
    return _dibujar_btn_icono_nav(deck, tamaño, GEAR_ICON_PATHS, "#aaaaaa", "CONF", activo, _gear_cache)

def dibujar_boton_app_nav(deck, tamaño, activo=False):
    return _dibujar_btn_icono_nav(deck, tamaño, APP_NAV_ICON_PATHS, "#33ff66", "APP", activo, _app_cache)

def dibujar_boton_x(deck, tamaño):
    """Botón profesional con X roja, atenúa el brillo del deck a 0."""
    imagen = Image.new("RGB", tamaño, "black")
    dibujo = ImageDraw.Draw(imagen)
    rect = (4, 4, tamaño[0]-5, tamaño[1]-5)
    dibujo.rounded_rectangle(rect, radius=10, fill="#1a0000", outline="#cc0000", width=2)
    pad = 24
    x1, y1 = pad, pad
    x2, y2 = tamaño[0]-pad-1, tamaño[1]-pad-1
    dibujo.line((x1, y1, x2, y2), fill="#ff3333", width=5)
    dibujo.line((x1, y2, x2, y1), fill="#ff3333", width=5)
    return PILHelper.to_native_format(deck, imagen)

def dibujar_negro(deck, tamaño):
    return PILHelper.to_native_format(deck, Image.new("RGB", tamaño, "black"))


# --- Callback ---

def _accion_boton(deck, tecla):
    global pagina_actual, forzar_redraw, brillo_actual, modo_dim_activo
    global tiempo_fallback, tiempo_dim

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
    if tecla == 7:
        if pagina_actual != 5:
            pagina_actual = 5
            forzar_redraw = True
        return

    if pagina_actual == 1:
        if tecla == 14 and KB_DISPONIBLE:
            keyboard.type(ROOT_TEXT)
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
        # Perfil Kiosko (cambiar al servicio streamdeb-kiosk)
        elif tecla == 15:
            print("[CONFIG] cambiando a perfil Kiosko", flush=True)
            subprocess.Popen(
                ["/home/jfqp/Documents/GitHub/streamdeb/bin/switch-profile.sh", "kiosk"],
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
        d = decks[0]
        d.open()
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
    gear = dibujar_boton_gear(deck, tam, activo=(pagina_actual == 5))
    return p1, p2, p3, p4, gear

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

    p1, p2, p3, p4, gear = botones_navegacion(deck, tam)
    imgs = {
        # Fila 0: navegación (+ gear y X en última columna)
        0: p1, 1: p2, 2: p3, 3: p4, 7: gear,
        # Fila 1: uptime, CPU total, C1-C4, ROOT
        8:  dibujar_panel_metrica(deck, tam, "Uptime", _fmt_tiempo(up_t), obtener_color_rango(pct_u), pct=pct_u),
        9:  dibujar_panel_metrica(deck, tam, "CPU T",  f"{int(cpu_t)}%", obtener_color_rango(cpu_t), pct=cpu_t),
        14: dibujar_panel_metrica(deck, tam, "Root",   "PWD",       "#ff3333"),
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
    p1, p2, p3, p4, gear = botones_navegacion(deck, tam)
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
        # Fila 0: navegación (+ gear y X)
        0: p1, 1: p2, 2: p3, 3: p4, 7: gear,
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
    p1, p2, p3, p4, gear = botones_navegacion(deck, tam)
    imgs = {
        # Fila 0: navegación (+ gear y X)
        0: p1, 1: p2, 2: p3, 3: p4, 7: gear,
        # Última columna (col 7) vertical: VOL+ · MUTE · VOL-
        15: dibujar_boton_fijo(deck, tam, "VOL+", "#663399"),
        23: dibujar_boton_fijo(deck, tam, "MUTE", "#cc0000", relleno=mute_activo),
        31: dibujar_boton_fijo(deck, tam, "VOL-", "#663399"),
        # PLAY 2 lugares a la derecha del centro
        22: dibujar_boton_fijo(deck, tam, "PLAY", "#0099ff"),
    }
    return imgs

def render_pagina_apps(deck, tam):
    p1, p2, p3, p4, gear = botones_navegacion(deck, tam)
    imgs = {
        0: p1, 1: p2, 2: p3, 3: p4, 7: gear,
    }
    for tecla, (cat, label, _cmd, color, icono) in APPS_PAGINA.items():
        imgs[tecla] = dibujar_lanzador(deck, tam, cat, color, icono=icono, fallback=label)
    return imgs

def render_pagina_config(deck, tam):
    p1, p2, p3, p4, gear = botones_navegacion(deck, tam)
    fb_pct  = (tiempo_fallback - TIEMPO_FALLBACK_MIN) / (TIEMPO_FALLBACK_MAX - TIEMPO_FALLBACK_MIN) * 100
    dim_pct = (tiempo_dim - TIEMPO_DIM_MIN) / (TIEMPO_DIM_MAX - TIEMPO_DIM_MIN) * 100
    imgs = {
        # Fila 0: navegación (+ gear y X)
        0: p1, 1: p2, 2: p3, 3: p4, 7: gear,
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
    img_negra = dibujar_negro(deck, tam)
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

            # Fallback a SIS si lleva mucho rato en otra página sin interacción
            if pagina_actual != 1 and (ahora - ultimo_toque) > tiempo_fallback:
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
                else:
                    imgs = render_pagina_config(deck, tam)
                last_net = cur_net

                if pagina_actual != pagina_anterior or forzar_redraw:
                    for k in range(deck.key_count()):
                        if k not in imgs:
                            deck.set_key_image(k, img_negra)
                    pagina_anterior = pagina_actual
                    forzar_redraw = False

                for key, img in imgs.items():
                    deck.set_key_image(key, img)

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
                img_negra = dibujar_negro(deck, tam)
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
