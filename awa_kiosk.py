"""
awa_kiosk.py — Stream Deck XL en modo kiosko de una sola página (AWA).

Pensado para correr en una Raspberry Pi dedicada que controla el ESP32
AWAhorro vía HTTP. NO comparte código con dashboard_pro.py: es una copia
recortada para que ambos evolucionen sin acoplarse. Si una mejora del
dashboard vale la pena para el kiosko, se porta a mano.

Layout (Stream Deck XL · 4 filas × 8 columnas):

Página AWA (default):
  Fila 0:  Ext   Ambas Tanque Inten Mix   Eco   Ráp   Pre        ← modos + lavaplatos
  Fila 1:  Estado Cuenta Modo  Aper. WiFi  Tank  Usuario Admin   ← estado API
  Fila 2:  1MIN  2MIN  3MIN  4MIN  5MIN   .     .     PingAPI
  Fila 3:  15MIN 30MIN 1HORA 2HORAS .     .    CONF    CERRAR

Página CONF:
  Fila 1:  Brillo+ .    .    .    .    .    .    .
  Fila 2:  Brillo% .    .    .    .    .    .    .
  Fila 3:  Brillo− .    .    .    .    .    AWA  X

Configuración por env vars:
  STREAMDEB_API_HOST   (default http://192.168.18.10)
  STREAMDEB_API_USER   (default Kiosko)
  STREAMDEB_BRILLO     (default 75)
  STREAMDEB_DIM        (default 300 = 5 min sin uso → atenúa a 0)
"""
import os
import time
import json
import socket
import datetime
import threading
import subprocess
import urllib.request
from collections import deque
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageFont
from StreamDeck.DeviceManager import DeviceManager
from StreamDeck.ImageHelpers import PILHelper

# --- CONFIGURACIÓN ---
# Comparte FONT_PATH con dashboard_pro (mismo path de DejaVuSans-Bold).
# El resto se mantiene local porque kiosko tiene su propio entorno (Pi 3, env vars).
from core.config import FONT_PATH
from core.helpers import _fmt_tiempo  # pomodoro/api en kiosko reusan formato compacto
API_HOST     = os.environ.get("STREAMDEB_API_HOST", "http://192.168.18.10")
API_USER     = os.environ.get("STREAMDEB_API_USER", "Kiosko")
API_IP       = urlparse(API_HOST).hostname or "192.168.18.10"
BRILLO_INI   = int(os.environ.get("STREAMDEB_BRILLO", "75"))
tiempo_dim       = int(os.environ.get("STREAMDEB_DIM", "300"))
TIEMPO_DIM_MIN   = 60
TIEMPO_DIM_MAX   = 7200    # 2 h
TIEMPO_PASO      = 60      # 1 min para +/-
DECK_SERIAL  = os.environ.get("STREAMDEB_DECK_SERIAL", "").strip()
FORCE_DARK   = os.environ.get("STREAMDEB_FORCE_DARK", "0") == "1"
BRILLO_MIN   = 10
BRILLO_MAX   = 100
BRILLO_PASO  = 10
BRILLO_DARK  = 50          # brillo fijo en tema dark

# Tema por horario (America/Lima)
TZ_LIMA      = ZoneInfo("America/Lima")
LIGHT_INI    = (5, 30)    # 05:30 → empieza light
LIGHT_FIN    = (22, 0)    # 22:00 → empieza dark
REDIM_DARK   = 2          # segundos hasta auto-dim tras pulsar apertura en dark


# --- Estado global ---
ultimo_toque    = time.time()
modo_dim_activo = False
_despertar      = False
forzar_redraw   = False
ping_api        = 0.0
ping_history    = deque(maxlen=60)
pagina_actual   = 1     # 1 = AWA · 2 = CONF
brillo_actual   = BRILLO_INI
tema_override   = None  # None=auto · "light" · "dark"
auto_redim_at   = None  # epoch sec — si != None y ya pasó, atenúa
api_info = {
    "online": False, "estado": "---", "cuenta": "---",
    "modo": 0, "modoNombre": "---",
    "contador": 0, "wifiSignal": 0, "tankOnline": False, "tankSignal": 0,
    "usuario": "---", "adminLocked": False,
    "segundos": 0, "initial_seconds": 0,
    "seqActive": False, "seqProgName": "",
    "seqElapsedSec": 0, "seqTotalSec": 0,
}


# --- Mapas de teclas ---
# Fila 0: modos (cols 0-2) · programas lavaplatos (cols 3-7)
MODOS_TECLA = {0: (1, "Ext"), 1: (2, "Ambas"), 2: (3, "Tanque")}
PROGRAMAS_TECLA = {
    3: ("intensivo", "Inten"),
    4: ("mix",       "Mix"),
    5: ("eco",       "Eco"),
    6: ("rapido",    "Ráp"),
    7: ("prelavado", "Pre"),
}

# Fila 2-3: aperturas con drain (igual que dashboard_pro.py)
DURACION_A_TECLA = {60:16, 120:17, 180:18, 240:19, 300:20,
                    900:24, 1800:25, 3600:26, 7200:27}
ACCIONES_LABELS = {16:"1 MIN", 17:"2 MIN", 18:"3 MIN", 19:"4 MIN", 20:"5 MIN",
                   24:"15 MIN", 25:"30 MIN", 26:"1 HORA", 27:"2 HORAS"}
TECLA_PING   = 23
TECLA_NAV    = 30   # AWA: ir a CONF · CONF: volver a AWA
TECLA_CERRAR = 31

# Colores
COL_MODO     = "#ffaa00"   # amarillo/ámbar — fuente de agua
COL_PROG     = "#cc66ff"   # violeta — programas lavaplatos
COL_AWA      = "#00ddff"   # cyan — acciones de apertura
COL_CONF     = "#aaaaaa"   # gris — config
COL_BRILLO   = "#ffaa00"   # ámbar — controles de brillo
COL_ROJO     = "#ff3333"


# --- Tema (light / dark según horario o override) ---

def _en_horario_light():
    h = datetime.datetime.now(TZ_LIMA)
    minutos    = h.hour * 60 + h.minute
    ini        = LIGHT_INI[0] * 60 + LIGHT_INI[1]
    fin        = LIGHT_FIN[0] * 60 + LIGHT_FIN[1]
    return ini <= minutos < fin

def tema_actual():
    if FORCE_DARK:
        return "dark"
    if tema_override is not None:
        return tema_override
    return "light" if _en_horario_light() else "dark"

def _brillo_target_unused():
    """Brillo a usar al despertar del dim, según el tema vigente."""
    return BRILLO_DARK if tema_actual() == "dark" else brillo_actual


# --- Comunicación con el ESP32 ---

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
                "seqActive":       data.get("seqActive", False),
                "seqProgName":     data.get("seqProgName", ""),
                "seqElapsedSec":   data.get("seqElapsedSec", 0),
                "seqTotalSec":     data.get("seqTotalSec", 0),
            })
        except Exception:
            api_info["online"] = False
        time.sleep(2)


def tareas_ping_fondo():
    global ping_api
    while True:
        try:
            res = subprocess.run(["ping", "-c", "1", "-W", "1", API_IP],
                                 capture_output=True, text=True)
            if "time=" in res.stdout:
                ping_api = float(res.stdout.split("time=")[1].split(" ")[0])
                ping_history.append(ping_api)
            else:
                ping_api = -1.0
        except Exception:
            ping_api = -1.0
        time.sleep(5)


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


# --- Helpers de dibujo ---

def _fit_font(dibujo, txt, max_width, max_size, min_size=10):
    for size in range(max_size, min_size - 1, -1):
        f = ImageFont.truetype(FONT_PATH, size)
        if dibujo.textlength(txt, font=f) <= max_width:
            return f
    return ImageFont.truetype(FONT_PATH, min_size)


# _fmt_tiempo viene de core.helpers (importado arriba)


def _ping_pct_relativo(ms):
    if ms <= 0:
        return 0, "#666666"
    if len(ping_history) < 3:
        return 30, "#33ff33"
    avg = sum(ping_history) / len(ping_history)
    pmax = max(ping_history)
    if pmax - avg < 1.0:
        return 30, "#33ff33"
    if ms <= avg:
        pct = 30.0
    else:
        pct = 30.0 + ((ms - avg) / (pmax - avg)) * 70.0
        pct = max(0.0, min(100.0, pct))
    color = "#33ff33" if pct <= 40 else "#ffaa00" if pct <= 70 else COL_ROJO
    return pct, color


def dibujar_panel_metrica(deck, tam, titulo, valor, color, pct=None, sub=None):
    imagen = Image.new("RGB", tam, "black")
    dibujo = ImageDraw.Draw(imagen)
    rect = (4, 4, tam[0]-5, tam[1]-5)
    dibujo.rounded_rectangle(rect, radius=10, outline=color, width=2)
    f_tit = ImageFont.truetype(FONT_PATH, 13)
    dibujo.text((tam[0]//2, 15), titulo, font=f_tit, fill=color, anchor="mm")
    dibujo.line((10, 27, tam[0]-11, 27), fill=color, width=1)

    txt = str(valor)
    max_w = tam[0] - 16
    bottom = 76 if pct is not None else (tam[1] - 6)
    cy = (28 + bottom) // 2

    if sub:
        f_val = _fit_font(dibujo, txt, max_w, 22, 12)
        f_sub = ImageFont.truetype(FONT_PATH, 12)
        dibujo.text((tam[0]//2, cy - 8),  txt, font=f_val, fill="#ffffff", anchor="mm")
        dibujo.text((tam[0]//2, cy + 10), sub, font=f_sub, fill="#aaaaaa", anchor="mm")
    else:
        f_val = _fit_font(dibujo, txt, max_w, 26, 12)
        dibujo.text((tam[0]//2, cy), txt, font=f_val, fill="#ffffff", anchor="mm")

    if pct is not None:
        ancho, alto, x, y = tam[0] - 20, 8, 10, 78
        p = max(0, min(100, pct))
        dibujo.rectangle((x, y, x + ancho, y + alto), outline="#333333", fill="#111111")
        if p > 0:
            dibujo.rectangle((x, y, x + int(ancho * (p/100)), y + alto), fill=color)
    return PILHelper.to_native_format(deck, imagen)


def dibujar_panel_info(deck, tam, titulo, valor, frame_color, valor_color="#ffffff"):
    imagen = Image.new("RGB", tam, "black")
    dibujo = ImageDraw.Draw(imagen)
    rect = (4, 4, tam[0]-5, tam[1]-5)
    dibujo.rounded_rectangle(rect, radius=10, outline=frame_color, width=2)
    f_tit = ImageFont.truetype(FONT_PATH, 13)
    dibujo.text((tam[0]//2, 16), titulo, font=f_tit, fill=frame_color, anchor="mm")
    dibujo.line((10, 28, tam[0]-11, 28), fill=frame_color, width=1)
    txt = str(valor)
    f_val = _fit_font(dibujo, txt, tam[0]-16, 22, 11)
    dibujo.text((tam[0]//2, 60), txt, font=f_val, fill=valor_color, anchor="mm")
    return PILHelper.to_native_format(deck, imagen)


def dibujar_panel_2lineas(deck, tam, titulo, valor, frame_color, valor_color="#ffffff"):
    imagen = Image.new("RGB", tam, "black")
    dibujo = ImageDraw.Draw(imagen)
    rect = (4, 4, tam[0]-5, tam[1]-5)
    dibujo.rounded_rectangle(rect, radius=10, outline=frame_color, width=2)
    f_tit = ImageFont.truetype(FONT_PATH, 13)
    dibujo.text((tam[0]//2, 16), titulo, font=f_tit, fill=frame_color, anchor="mm")
    dibujo.line((10, 28, tam[0]-11, 28), fill=frame_color, width=1)
    txt = str(valor).strip()
    if " " in txt:
        l1, l2 = txt.split(" ", 1)
    else:
        mid = (len(txt) + 1) // 2
        l1, l2 = txt[:mid], txt[mid:]
    max_w = tam[0] - 16
    f1 = _fit_font(dibujo, l1, max_w, 18, 10)
    f2 = _fit_font(dibujo, l2, max_w, 18, 10)
    dibujo.text((tam[0]//2, 50), l1, font=f1, fill=valor_color, anchor="mm")
    dibujo.text((tam[0]//2, 73), l2, font=f2, fill=valor_color, anchor="mm")
    return PILHelper.to_native_format(deck, imagen)


def dibujar_estado_pro(deck, tam, online, abierta):
    imagen = Image.new("RGB", tam, "black")
    dibujo = ImageDraw.Draw(imagen)
    rect = (4, 4, tam[0]-5, tam[1]-5)
    f_tit = ImageFont.truetype(FONT_PATH, 13)
    if not online:
        color, texto = "#666666", "OFFLINE"
        dibujo.rounded_rectangle(rect, radius=10, outline=color, width=2)
    elif abierta:
        color, texto = "white", "ABIERTA"
        dibujo.rounded_rectangle(rect, radius=10, fill="#22aa33")
    else:
        color, texto = COL_ROJO, "CERRADA"
        dibujo.rounded_rectangle(rect, radius=10, outline=color, width=3)
    dibujo.text((tam[0]//2, 16), "Estado", font=f_tit, fill=color, anchor="mm")
    dibujo.line((10, 28, tam[0]-11, 28), fill=color, width=1)
    f_val = _fit_font(dibujo, texto, tam[0]-18, 20, 12)
    dibujo.text((tam[0]//2, 60), texto, font=f_val, fill=color, anchor="mm")
    return PILHelper.to_native_format(deck, imagen)


def dibujar_accion_pro(deck, tam, texto, color, peligro=False, drain=None):
    imagen = Image.new("RGB", tam, "black")
    dibujo = ImageDraw.Draw(imagen)
    rect = (4, 4, tam[0]-5, tam[1]-5)
    if peligro:
        dibujo.rounded_rectangle(rect, radius=10, fill=color)
    elif drain is None:
        dibujo.rounded_rectangle(rect, radius=10, fill="#001a26", outline=color, width=2)
    else:
        d = max(0.0, min(1.0, drain))
        dibujo.rounded_rectangle(rect, radius=10, fill="#001a26")
        if d < 1.0:
            water = Image.new("RGB", tam, "black")
            wd = ImageDraw.Draw(water)
            wd.rounded_rectangle(rect, radius=10, fill=color)
            mask = Image.new("L", tam, 0)
            md = ImageDraw.Draw(mask)
            water_top = int(4 + (tam[1] - 8) * d)
            md.rectangle((0, water_top, tam[0], tam[1]), fill=255)
            imagen = Image.composite(water, imagen, mask)
            dibujo = ImageDraw.Draw(imagen)
        dibujo.rounded_rectangle(rect, radius=10, outline=color, width=2)

    max_w = tam[0] - 16
    if " " in texto:
        num, unidad = texto.split(" ", 1)
        f_num = _fit_font(dibujo, num,    max_w, 36, 18)
        f_uni = _fit_font(dibujo, unidad, max_w, 18, 12)
        dibujo.text((tam[0]//2, 36), num,    font=f_num, fill="white", anchor="mm")
        dibujo.text((tam[0]//2, 72), unidad, font=f_uni, fill="white", anchor="mm")
    else:
        f = _fit_font(dibujo, texto, max_w, 24, 12)
        dibujo.text((tam[0]//2, tam[1]//2), texto, font=f, fill="white", anchor="mm")
    return PILHelper.to_native_format(deck, imagen)


def dibujar_btn_seleccion(deck, tam, titulo, etiqueta, color, activo=False):
    """Botón con header (título + separador) y zona inferior con etiqueta.
    Si activo: relleno color, texto negro. Si no: outline + texto color."""
    imagen = Image.new("RGB", tam, "black")
    dibujo = ImageDraw.Draw(imagen)
    rect = (4, 4, tam[0]-5, tam[1]-5)
    if activo:
        dibujo.rounded_rectangle(rect, radius=10, fill=color)
        title_color = "black"
        sep_color   = "black"
        v_color     = "black"
    else:
        dibujo.rounded_rectangle(rect, radius=10, outline=color, width=2)
        title_color = color
        sep_color   = color
        v_color     = "#ffffff"
    f_tit = ImageFont.truetype(FONT_PATH, 13)
    dibujo.text((tam[0]//2, 16), titulo, font=f_tit, fill=title_color, anchor="mm")
    dibujo.line((10, 28, tam[0]-11, 28), fill=sep_color, width=1)
    f_val = _fit_font(dibujo, str(etiqueta), tam[0]-16, 22, 11)
    dibujo.text((tam[0]//2, 60), str(etiqueta), font=f_val, fill=v_color, anchor="mm")
    return PILHelper.to_native_format(deck, imagen)


def dibujar_boton_x(deck, tam):
    imagen = Image.new("RGB", tam, "black")
    dibujo = ImageDraw.Draw(imagen)
    rect = (4, 4, tam[0]-5, tam[1]-5)
    dibujo.rounded_rectangle(rect, radius=10, fill="#1a0000", outline="#cc0000", width=2)
    pad = 24
    x1, y1 = pad, pad
    x2, y2 = tam[0]-pad-1, tam[1]-pad-1
    dibujo.line((x1, y1, x2, y2), fill=COL_ROJO, width=5)
    dibujo.line((x1, y2, x2, y1), fill=COL_ROJO, width=5)
    return PILHelper.to_native_format(deck, imagen)


def dibujar_negro(deck, tam):
    return PILHelper.to_native_format(deck, Image.new("RGB", tam, "black"))


def dibujar_texto_dark(deck, tam, texto, color, max_size=36, min_size=14):
    """Texto centrado sobre negro, sin marco. Usado en tema dark."""
    imagen = Image.new("RGB", tam, "black")
    dibujo = ImageDraw.Draw(imagen)
    f = _fit_font(dibujo, str(texto), tam[0]-12, max_size, min_size)
    dibujo.text((tam[0]//2, tam[1]//2), str(texto), font=f, fill=color, anchor="mm")
    return PILHelper.to_native_format(deck, imagen)


# --- Callback de teclas ---

def _accion_boton(deck, tecla):
    global pagina_actual, forzar_redraw, brillo_actual, modo_dim_activo
    global tema_override, auto_redim_at, tiempo_dim

    tema = tema_actual()

    # Nav AWA ↔ CONF — slot depende del tema en página AWA; en CONF siempre TECLA_NAV
    if pagina_actual == 2:
        nav_slot = TECLA_NAV
    else:
        nav_slot = DARK_TECLA_CONF if tema == "dark" else TECLA_NAV
    if tecla == nav_slot:
        pagina_actual = 2 if pagina_actual == 1 else 1
        forzar_redraw = True
        return

    # Página CONF
    if pagina_actual == 2:
        if tecla == 8:
            brillo_actual = min(BRILLO_MAX, brillo_actual + BRILLO_PASO)
            try: deck.set_brightness(brillo_actual)
            except: pass
            print(f"[CONF] brillo_actual={brillo_actual} (tema={tema})", flush=True)
            forzar_redraw = True
        elif tecla == 24:
            brillo_actual = max(BRILLO_MIN, brillo_actual - BRILLO_PASO)
            try: deck.set_brightness(brillo_actual)
            except: pass
            print(f"[CONF] brillo_actual={brillo_actual} (tema={tema})", flush=True)
            forzar_redraw = True
        elif tecla == 15:   # Diurna — toggle
            tema_override = None if tema_override == "light" else "light"
            print(f"[CONF] tema_override={tema_override}", flush=True)
            forzar_redraw = True
        elif tecla == 9:    # Dim +
            tiempo_dim = min(TIEMPO_DIM_MAX, tiempo_dim + TIEMPO_PASO)
            print(f"[CONF] tiempo_dim={tiempo_dim}s", flush=True)
            forzar_redraw = True
        elif tecla == 25:   # Dim −
            tiempo_dim = max(TIEMPO_DIM_MIN, tiempo_dim - TIEMPO_PASO)
            print(f"[CONF] tiempo_dim={tiempo_dim}s", flush=True)
            forzar_redraw = True
        elif tecla == 23:   # Oscura — toggle
            tema_override = None if tema_override == "dark" else "dark"
            print(f"[CONF] tema_override={tema_override}", flush=True)
            forzar_redraw = True
        elif tecla == 11:   # Perfil Main — sólo aplica en dinamo, no-op en la Pi
            print("[CONF] cambiando a perfil Main", flush=True)
            switch = "/home/jfqp/Documents/GitHub/streamdeb/bin/switch-profile.sh"
            if os.path.exists(switch):
                subprocess.Popen([switch, "main"], start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                print("[CONF] switch-profile.sh no encontrado (¿host Pi?) — ignoro", flush=True)
        elif tecla == TECLA_CERRAR:
            try:
                deck.set_brightness(0)
                modo_dim_activo = True
            except: pass
        return

    # En tema dark, sólo se aceptan: Estado (read-only), 1-5, Cerrar, Conf
    if tema == "dark":
        if 16 <= tecla <= 20:
            api_post_comando({"action": "open", "minutes": tecla - 15, "user": API_USER})
            auto_redim_at = time.time() + REDIM_DARK
            return
        if tecla == TECLA_CERRAR:
            api_post_comando({"action": "close"})
            auto_redim_at = time.time() + REDIM_DARK
            return
        # cualquier otra tecla en dark se ignora (Estado es read-only, modos/programas no se muestran)
        return

    # Página AWA en tema light — modos (fila 0, cols 0-2)
    if tecla in MODOS_TECLA:
        modo, _ = MODOS_TECLA[tecla]
        api_post_comando({"action": "mode", "mode": modo, "user": API_USER})
        return

    # Programas lavaplatos (fila 0, cols 3-7)
    if tecla in PROGRAMAS_TECLA:
        prog, _ = PROGRAMAS_TECLA[tecla]
        api_post_comando({"action": "sequence", "program": prog, "user": API_USER})
        return

    # Aperturas cortas (16-20 = 1..5 min)
    if 16 <= tecla <= 20:
        api_post_comando({"action": "open", "minutes": tecla - 15, "user": API_USER})
        return

    # Aperturas largas (24-27)
    mapa_largo = {24: 15, 25: 30, 26: 60, 27: 120}
    if tecla in mapa_largo:
        api_post_comando({"action": "open", "minutes": mapa_largo[tecla], "user": API_USER})
        return

    # Cerrar
    if tecla == TECLA_CERRAR:
        api_post_comando({"action": "close"})
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


# --- Inicialización del deck ---

def _abrir_deck():
    """Abre el primer Stream Deck disponible. Si STREAMDEB_DECK_SERIAL está
    definido, sólo abre ese serial. Si no, recorre los decks y se queda con
    el primero que se pueda abrir (skip los que ya tiene otro proceso)."""
    try:
        decks = DeviceManager().enumerate()
    except Exception as e:
        print(f"[WARN] enumerate: {e}", flush=True)
        return None
    if not decks:
        return None
    for i, d in enumerate(decks):
        try:
            d.open()
        except Exception as e:
            print(f"[SKIP] deck[{i}] ocupado o no abrible: {e}", flush=True)
            continue
        try:
            serial = d.get_serial_number()
            if DECK_SERIAL and serial != DECK_SERIAL:
                print(f"[SKIP] deck[{i}] serial={serial} (busco {DECK_SERIAL})", flush=True)
                d.close()
                continue
            time.sleep(0.3)
            d.reset()
            d.set_brightness(brillo_actual)
            print(f"[DECK] abierto serial={serial} keys={d.key_count()}", flush=True)
            return d
        except Exception as e:
            print(f"[WARN] init deck[{i}]: {e}", flush=True)
            try: d.close()
            except: pass
    return None


# --- Render ---

def render_pagina(deck, tam):
    online  = api_info["online"]
    estado  = api_info["estado"]
    abierta = (estado == "Abierta")

    # Drain animado en aperturas (igual que dashboard_pro.py)
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
            return dibujar_accion_pro(deck, tam, txt, COL_AWA, drain=active_drain)
        return dibujar_accion_pro(deck, tam, label, COL_AWA)

    cuenta_color = "#666666" if not online else "#33ff33" if abierta else COL_ROJO
    admin_color  = COL_ROJO if api_info["adminLocked"] else "#33ff33"
    admin_txt    = "BLOQ" if api_info["adminLocked"] else "OK"
    tank_color   = "#33ff33" if api_info["tankOnline"] else COL_ROJO
    tank_txt     = f"{api_info['tankSignal']}/4" if api_info["tankOnline"] else "OFF"

    # Ping API
    if ping_api > 0:
        api_pct, api_color = _ping_pct_relativo(ping_api)
        ping_btn = dibujar_panel_metrica(deck, tam, "Ping API", f"{ping_api:.1f}",
                                         api_color, pct=api_pct, sub="ms")
    else:
        ping_btn = dibujar_panel_metrica(deck, tam, "Ping API", "Err", "#666666", pct=0)

    imgs = {}

    # Fila 0 — modos
    modo_actual = api_info.get("modo", 0)
    for tecla, (modo, label) in MODOS_TECLA.items():
        imgs[tecla] = dibujar_btn_seleccion(deck, tam, "Fuente", label, COL_MODO,
                                            activo=(online and modo == modo_actual))

    # Fila 0 — programas
    prog_actual = api_info.get("seqProgName", "") if api_info.get("seqActive") else ""
    for tecla, (prog, label) in PROGRAMAS_TECLA.items():
        imgs[tecla] = dibujar_btn_seleccion(deck, tam, "Lavap.", label, COL_PROG,
                                            activo=(prog == prog_actual))

    # Fila 1 — estado API (idéntica a dashboard_pro.py)
    imgs[8]  = dibujar_estado_pro(deck, tam, online, abierta)
    imgs[9]  = dibujar_panel_2lineas(deck, tam, "Cuenta",  str(api_info["cuenta"]), cuenta_color)
    imgs[10] = dibujar_panel_2lineas(deck, tam, "Modo",    str(api_info["modoNombre"]), COL_AWA)
    imgs[11] = dibujar_panel_info(deck, tam,    "Aper.",   str(api_info["contador"]), COL_AWA)
    imgs[12] = dibujar_panel_info(deck, tam,    "WiFi",    f"{api_info['wifiSignal']}/4", COL_AWA)
    imgs[13] = dibujar_panel_info(deck, tam,    "Tank",    tank_txt, tank_color)
    imgs[14] = dibujar_panel_2lineas(deck, tam, "Usuario", api_info["usuario"], COL_AWA)
    imgs[15] = dibujar_panel_info(deck, tam,    "Admin",   admin_txt, admin_color)

    # Fila 2 — aperturas cortas + ping API
    for t in (16, 17, 18, 19, 20):
        imgs[t] = accion(t, ACCIONES_LABELS[t])
    imgs[TECLA_PING] = ping_btn

    # Fila 3 — aperturas largas + nav a CONF + cerrar
    for t in (24, 25, 26, 27):
        imgs[t] = accion(t, ACCIONES_LABELS[t])
    imgs[TECLA_NAV]    = dibujar_btn_seleccion(deck, tam, "Menu", "Conf", COL_CONF)
    # CERRAR: rojo sólido cuando hay aper. en curso (call to action);
    # outline tenue cuando el estado actual ya es Cerrada (acción pasiva)
    imgs[TECLA_CERRAR] = dibujar_accion_pro(deck, tam, "CERRAR", COL_ROJO,
                                            peligro=(online and abierta))

    return imgs


DARK_TECLA_ESTADO = 0    # col 1, row 1 (1-indexed)
DARK_TECLA_HORA1  = 1    # primer dígito + ":"
DARK_TECLA_HORA2  = 2    # minutos
DARK_TECLA_CONF   = 7    # col 8, row 1 (esquina sup. derecha)

def render_pagina_dark(deck, tam):
    """Layout dark minimalista — sin marcos, solo texto sobre negro.
    Estado=0, Hora=1-2, Conf=7, números 1-5 en 16-20, Cerrar en 31."""
    online  = api_info["online"]
    estado  = api_info["estado"]
    abierta = (estado == "Abierta")
    ahora_lima = datetime.datetime.now(TZ_LIMA)

    # En aperturas activas mostramos el countdown en lugar del número
    active_key = None
    if online and abierta:
        init_s = api_info.get("initial_seconds", 0)
        if init_s in (60, 120, 180, 240, 300) and init_s > 0:
            active_key = DURACION_A_TECLA[init_s]

    def num(tecla, label):
        if tecla == active_key:
            return dibujar_texto_dark(deck, tam,
                                      _fmt_tiempo(api_info.get("segundos", 0)),
                                      COL_AWA, max_size=24)
        return dibujar_texto_dark(deck, tam, label, COL_AWA, max_size=48)

    if not online:
        estado_color, estado_txt = "#666666", "OFF"
    elif abierta:
        estado_color, estado_txt = "#33ff33", "ABIERTA"
    else:
        estado_color, estado_txt = COL_ROJO, "CERRADA"

    hh = ahora_lima.strftime("%H")
    mm = ahora_lima.strftime("%M")

    imgs = {
        DARK_TECLA_ESTADO: dibujar_texto_dark(deck, tam, estado_txt, estado_color, max_size=20),
        DARK_TECLA_HORA1:  dibujar_texto_dark(deck, tam, hh, COL_CONF, max_size=44),
        DARK_TECLA_HORA2:  dibujar_texto_dark(deck, tam, mm,       COL_CONF, max_size=44),
        16: num(16, "1"),
        17: num(17, "2"),
        18: num(18, "3"),
        19: num(19, "4"),
        20: num(20, "5"),
        DARK_TECLA_CONF:   dibujar_texto_dark(deck, tam, "Conf",   COL_CONF, max_size=22),
        # CERRAR: rojo cuando hay aper. en curso, gris tenue cuando ya está cerrada
        TECLA_CERRAR:      dibujar_texto_dark(deck, tam, "CERRAR",
                                              COL_ROJO if (online and abierta) else "#444444",
                                              max_size=20),
    }
    return imgs


def render_pagina_config(deck, tam):
    """Página CONF — brillo en col 0, override de tema en col 7, X y back en fila 3."""
    tema = tema_actual()
    light_activa = (tema_override == "light")
    dark_activa  = (tema_override == "dark")
    dim_pct = (tiempo_dim - TIEMPO_DIM_MIN) / (TIEMPO_DIM_MAX - TIEMPO_DIM_MIN) * 100
    imgs = {
        # Col 0 — brillo
        8:  dibujar_panel_metrica(deck, tam, "Brillo", "+", COL_BRILLO),
        16: dibujar_panel_metrica(deck, tam, "Brillo", f"{brillo_actual}%", COL_BRILLO,
                                  pct=brillo_actual),
        24: dibujar_panel_metrica(deck, tam, "Brillo", "−", COL_BRILLO),
        # Col 1 — Dim por inactividad
        9:  dibujar_panel_metrica(deck, tam, "Dim", "+", "#cc66ff"),
        17: dibujar_panel_metrica(deck, tam, "Dim", _fmt_tiempo(tiempo_dim), "#cc66ff", pct=dim_pct),
        25: dibujar_panel_metrica(deck, tam, "Dim", "−", "#cc66ff"),
        # Col 7 — override de tema (toggle: pulsar el activo lo libera)
        15: dibujar_btn_seleccion(deck, tam, "Tema", "Diurna", COL_BRILLO,
                                  activo=light_activa),
        23: dibujar_btn_seleccion(deck, tam, "Tema", "Oscura", COL_CONF,
                                  activo=dark_activa),
        # Fila 3 — vuelta a AWA + apagar
        TECLA_NAV:    dibujar_btn_seleccion(deck, tam, "Volver", "AWA", COL_AWA),
        TECLA_CERRAR: dibujar_boton_x(deck, tam),
    }
    # Botón "Perfil Main" sólo cuando corremos en dinamo (existe el switch script)
    if os.path.exists("/home/jfqp/Documents/GitHub/streamdeb/bin/switch-profile.sh"):
        imgs[11] = dibujar_btn_seleccion(deck, tam, "Perfil", "Main", "#ffaa00")
    return imgs


# --- Loop principal ---

def iniciar_kiosko():
    global modo_dim_activo, _despertar, forzar_redraw, auto_redim_at

    deck = None
    while deck is None:
        deck = _abrir_deck()
        if deck is None:
            print("[WAIT] buscando Stream Deck...", flush=True)
            time.sleep(2)
    print(f"[OK] Stream Deck listo (kiosko AWA → {API_HOST}) tema={tema_actual()}",
          flush=True)

    tam = deck.key_image_format()['size']
    deck.set_key_callback(boton_presionado)
    threading.Thread(target=tareas_api_fondo,  daemon=True).start()
    threading.Thread(target=tareas_ping_fondo, daemon=True).start()
    img_negra = dibujar_negro(deck, tam)
    pagina_anterior = None
    tema_anterior   = None

    try:
        while True:
            ahora = time.time()
            tema  = tema_actual()

            # Despertar por toque (brillo según tema)
            if _despertar:
                try:
                    deck.set_brightness(brillo_actual)
                    modo_dim_activo = False
                except Exception:
                    pass
                _despertar = False

            # Transición de tema (auto o manual): redibuja todo
            if tema != tema_anterior:
                if tema_anterior is not None:
                    print(f"[TEMA] {tema_anterior} → {tema}", flush=True)
                forzar_redraw = True
                # Al entrar a dark: atenúa de inmediato (queda a la espera de toque)
                if tema == "dark" and tema_anterior is not None:
                    try: deck.set_brightness(0)
                    except: pass
                    modo_dim_activo = True
                # Al volver a light, si no estaba dim, ajusta brillo a brillo_actual
                elif tema == "light" and tema_anterior is not None and not modo_dim_activo:
                    try: deck.set_brightness(brillo_actual)
                    except: pass
                tema_anterior = tema

            # Auto-redim 2s tras pulsar apertura o cerrar en dark
            if auto_redim_at is not None and ahora >= auto_redim_at:
                try: deck.set_brightness(0)
                except: pass
                modo_dim_activo = True
                auto_redim_at   = None

            # Auto-dim por inactividad (aplica en light y dark)
            if not modo_dim_activo and (ahora - ultimo_toque) > tiempo_dim:
                print(f"[DIM] auto-dim tras {int(ahora - ultimo_toque)}s "
                      f"(tiempo_dim={tiempo_dim})", flush=True)
                try: deck.set_brightness(0)
                except: pass
                modo_dim_activo = True

            if modo_dim_activo:
                # Ping al deck para detectar desconexión USB durante dim
                try:
                    deck.set_brightness(0)
                except Exception as e:
                    print(f"[ERR] dim ping: {e} — reconectando...", flush=True)
                    try: deck.close()
                    except: pass
                    deck = None
                    while deck is None:
                        deck = _abrir_deck()
                        if deck is None:
                            print("[WAIT] esperando deck...", flush=True)
                            time.sleep(2)
                    tam = deck.key_image_format()['size']
                    deck.set_key_callback(boton_presionado)
                    img_negra = dibujar_negro(deck, tam)
                    pagina_anterior = None
                    forzar_redraw = True
                time.sleep(1)
                continue

            try:
                if pagina_actual == 2:
                    imgs = render_pagina_config(deck, tam)
                elif tema == "dark":
                    imgs = render_pagina_dark(deck, tam)
                else:
                    imgs = render_pagina(deck, tam)

                clave_pag = (pagina_actual, tema)
                if clave_pag != pagina_anterior or forzar_redraw:
                    for k in range(deck.key_count()):
                        if k not in imgs:
                            deck.set_key_image(k, img_negra)
                    pagina_anterior = clave_pag
                    forzar_redraw   = False

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
                primera   = True
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
        iniciar_kiosko()
    except KeyboardInterrupt:
        pass
