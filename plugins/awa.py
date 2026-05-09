"""Plugin AWA (página 2): control de válvula ESP32 AWAhorro vía API REST."""
import json
import math
import time
import urllib.request
from PIL import Image, ImageDraw, ImageFont

from core.config import API_HOST, API_USER, FONT_PATH
from core.helpers import _fit_font, _fmt_tiempo
from core.widgets import (
    _nuevo_lienzo, con_marco,
    dibujar_panel_metrica, dibujar_panel_info, dibujar_panel_2lineas,
)


# Estado live del ESP32 (mutado por tareas_api_fondo). Otros plugins
# (sistema, banner) lo consultan vía `from plugins.awa import api_info`.
api_info = {
    "online": False, "estado": "---", "cuenta": "---", "modo": 0, "modoNombre": "---",
    "contador": 0, "wifiSignal": 0, "tankOnline": False, "tankSignal": 0,
    "usuario": "---", "adminLocked": False,
    "segundos": 0, "initial_seconds": 0,
}

DURACION_A_TECLA = {60: 16, 120: 17, 180: 18, 240: 19, 300: 20,
                    900: 24, 1800: 25, 3600: 26, 7200: 27}
ACCIONES_LABELS  = {16: "1 MIN", 17: "2 MIN", 18: "3 MIN", 19: "4 MIN", 20: "5 MIN",
                    24: "15 MIN", 25: "30 MIN", 26: "1 HORA", 27: "2 HORAS"}

_AWA_FONDO_RGBA = (0, 26, 38, 51)  # #001a26 al 20% opacidad


# --- Networking ---

def tareas_api_fondo():
    """Polling cada 2s del ESP32 base; actualiza api_info in-place."""
    while True:
        try:
            req = urllib.request.Request(f"{API_HOST}/estado", method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                data = json.loads(resp.read().decode("utf-8"))
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
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{API_HOST}/api/comando",
            data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            print(f"[API] {payload} → {resp.status}", flush=True)
    except Exception as e:
        print(f"[ERR API] {payload}: {e}", flush=True)


# --- Widgets AWA-específicos ---

def dibujar_estado_pro(deck, tamaño, online, abierta):
    """Estado AWA: aro + círculo interno (latiendo si abierta, fijo si cerrada)."""
    imagen = _nuevo_lienzo(tamaño)
    dibujo = ImageDraw.Draw(imagen)
    rect = (4, 4, tamaño[0]-5, tamaño[1]-5)
    f_tit = ImageFont.truetype(FONT_PATH, 13)

    if not online:    color = "#666666"
    elif abierta:     color = "#22dd44"
    else:             color = "#ff3333"

    if con_marco():
        dibujo.rounded_rectangle(rect, radius=10, outline=color, width=2)

    dibujo.text((tamaño[0]//2, 16), "Estado", font=f_tit, fill=color, anchor="mm")
    dibujo.line((10, 28, tamaño[0]-11, 28), fill=color, width=1)

    cx, cy = tamaño[0]//2, 62
    R = 24
    dibujo.ellipse((cx-R, cy-R, cx+R, cy+R), outline=color, width=4)

    if online and abierta:
        # Latido: radio oscila ~7..16 con periodo no entero.
        fase = (math.sin(2 * math.pi * time.time() / 2.7) + 1) / 2
        r_int = int(7 + fase * 9)
    else:
        r_int = 12
    dibujo.ellipse((cx-r_int, cy-r_int, cx+r_int, cy+r_int), fill=color)
    return imagen


def dibujar_accion_pro(deck, tamaño, texto, color, peligro=False, drain=None):
    """Acción AWA con marco redondeado. drain en [0,1] para efecto vaciado de vaso.
    None = botón inactivo. peligro=True → fondo sólido (CERRAR rojo)."""
    imagen = _nuevo_lienzo(tamaño)
    dibujo = ImageDraw.Draw(imagen)
    rect = (4, 4, tamaño[0]-5, tamaño[1]-5)

    if peligro:
        dibujo.rounded_rectangle(rect, radius=10, fill=color)
    elif drain is None:
        dibujo.rounded_rectangle(rect, radius=10, fill=_AWA_FONDO_RGBA)
        if con_marco():
            dibujo.rounded_rectangle(rect, radius=10, outline=color, width=2)
    else:
        d = max(0.0, min(1.0, drain))
        dibujo.rounded_rectangle(rect, radius=10, fill=_AWA_FONDO_RGBA)
        if d < 1.0:
            water = Image.new("RGBA", tamaño, (0, 0, 0, 0))
            wd = ImageDraw.Draw(water)
            wd.rounded_rectangle(rect, radius=10, fill=color)
            mask = Image.new("L", tamaño, 0)
            md = ImageDraw.Draw(mask)
            water_top = int(4 + (tamaño[1] - 8) * d)
            md.rectangle((0, water_top, tamaño[0], tamaño[1]), fill=255)
            imagen = Image.composite(water, imagen, mask)
            dibujo = ImageDraw.Draw(imagen)
        if con_marco():
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


# --- Render página AWA ---

def render_pagina_api(deck, tam, nav_imgs, net_info, ping_pct_relativo_fn):
    cyan = "#00ddff"
    online = api_info["online"]
    estado = api_info["estado"]
    abierta = (estado == "Abierta")
    cuenta_color = "#666666" if not online else "#33ff33" if abierta else "#ff3333"
    admin_color  = "#ff3333" if api_info["adminLocked"] else "#33ff33"
    admin_txt    = "BLOQ" if api_info["adminLocked"] else "OK"
    tank_color   = "#33ff33" if api_info["tankOnline"] else "#ff3333"
    tank_txt     = f"{api_info['tankSignal']}/4" if api_info["tankOnline"] else "OFF"

    ms_api = net_info["ping_api"]
    if ms_api > 0:
        api_pct, api_color = ping_pct_relativo_fn("ping_api", ms_api)
        api_ping_btn = dibujar_panel_metrica(deck, tam, "Ping API", f"{ms_api:.1f}",
                                              api_color, pct=api_pct, sub="ms")
    else:
        api_ping_btn = dibujar_panel_metrica(deck, tam, "Ping API", "Err", "#666666", pct=0)

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

    imgs = dict(nav_imgs)
    imgs.update({
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
        # Fila 3: acciones largas + CERRAR
        24: accion(24, "15 MIN"),
        25: accion(25, "30 MIN"),
        26: accion(26, "1 HORA"),
        27: accion(27, "2 HORAS"),
        31: dibujar_accion_pro(deck, tam, "CERRAR", "#ff3333", peligro=True),
    })
    return imgs


def on_press(tecla):
    """Handler de página AWA: 16-20 → 1..5 min · 24-27 → 15/30/60/120 min · 31 → CERRAR."""
    mapa_largo = {24: 15, 25: 30, 26: 60, 27: 120}
    if 16 <= tecla <= 20:
        api_post_comando({"action": "open", "minutes": tecla - 15, "user": API_USER})
    elif tecla == 31:
        api_post_comando({"action": "close"})
    elif tecla in mapa_largo:
        api_post_comando({"action": "open", "minutes": mapa_largo[tecla], "user": API_USER})
    else:
        return False
    return True
