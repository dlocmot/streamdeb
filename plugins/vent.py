"""Plugin VENT (página 8): tiling de ventanas vía wmctrl.
Usa las mismas geometrías que ~/.xbindkeysrc — no envía Super+N (xbindkeys
ignora eventos sintéticos de pynput, XGrabKey no atrapa XTest)."""
import os
import subprocess
from PIL import Image, ImageDraw, ImageFont

from core.config import FONT_PATH
from core.iconos import iconify_png as _iconify_png
from core.widgets import _nuevo_lienzo, con_marco, dibujar_btn_icono_nav


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

_vent_cache = {}


def _vent_nav_paths():
    """Icono nav VENT: mdi:view-quilt rasterizado vía iconify."""
    p = _iconify_png("mdi:view-quilt", "66ddff", 256)
    fallbacks = (
        "/usr/share/icons/ContrastHigh/256x256/actions/view-grid.png",
        "/usr/share/icons/hicolor/256x256/apps/mate-panel-window-list.png",
    )
    return tuple(x for x in (p, *fallbacks) if x)


def dibujar_boton_vent_nav(deck, tamaño, activo=False):
    return dibujar_btn_icono_nav(deck, tamaño, _vent_nav_paths(),
                                  "#66ddff", "VENT", activo, _vent_cache)


def dibujar_vent_preview(deck, tamaño, label, x_ini, x_fin, y_ini, y_fin, color):
    """Botón con preview gráfico de la región objetivo en una mini-pantalla."""
    imagen = _nuevo_lienzo(tamaño)
    dibujo = ImageDraw.Draw(imagen)
    rect = (4, 4, tamaño[0]-5, tamaño[1]-5)
    if con_marco():
        dibujo.rounded_rectangle(rect, radius=10, outline=color, width=2)
    f_tit = ImageFont.truetype(FONT_PATH, 13)
    dibujo.text((tamaño[0]//2, 15), label, font=f_tit, fill=color, anchor="mm")
    dibujo.line((10, 27, tamaño[0]-11, 27), fill=color, width=1)
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


def render_pagina_vent(deck, tam, nav_imgs):
    imgs = dict(nav_imgs)
    for tecla, (label, x_ini, x_fin, y_ini, y_fin, _geom) in VENT_PAGINA.items():
        es_mitad_x = (x_fin - x_ini) > 0.34
        es_alto_completo = (y_fin - y_ini) > 0.99
        if es_mitad_x:
            color = "#cc66ff" if es_alto_completo else "#aa55cc"
        else:
            color = "#66ddff" if es_alto_completo else "#4499bb"
        imgs[tecla] = dibujar_vent_preview(deck, tam, label, x_ini, x_fin, y_ini, y_fin, color)
    return imgs


def on_press(tecla):
    if tecla not in VENT_PAGINA:
        return False
    geom = VENT_PAGINA[tecla][5]
    try:
        subprocess.run(["wmctrl", "-r", ":ACTIVE:", "-b",
                         "remove,maximized_vert,maximized_horz"],
                       check=False, timeout=2)
        subprocess.run(["wmctrl", "-r", ":ACTIVE:", "-e", geom],
                       check=False, timeout=2)
    except Exception as e:
        print(f"[VENT] error wmctrl: {e}", flush=True)
    return True
