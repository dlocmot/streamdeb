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
# Data declarativa en config/default.toml; geometrías wmctrl calculadas para
# 3840×1200 con 27px de margen vertical para el panel MATE.
VENT_PAGINA: dict[int, tuple] = {}


def reload(cfg=None):
    """Reconstruye VENT_PAGINA desde el config TOML."""
    if cfg is None:
        from plugins.userconfig import load as _load
        cfg = _load()
    VENT_PAGINA.clear()
    for b in cfg.vent.buttons:
        VENT_PAGINA[b.key] = (
            b.label,
            b.fraction_x[0], b.fraction_x[1],
            b.fraction_y[0], b.fraction_y[1],
            b.wmctrl_geom,
        )
    print(f"[USERCONFIG] vent: {len(VENT_PAGINA)} botones", flush=True)


reload()

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
                                  "#66ddff", "Win", activo, _vent_cache)


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
