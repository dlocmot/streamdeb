"""Widgets de dibujo primitivos. Sin estado mutable propio salvo:
- caches de PIL retenidos para nav buttons (deliberado: marca _streamdeb_stable=True)
- hook `_con_marco_fn` que el caller debe wirear con `set_con_marco_fn(...)`
"""
import os
from PIL import Image, ImageDraw, ImageFont

from .config import FONT_PATH
from .helpers import _fit_font
from .iconos import cargar_icono as _cargar_icono


# Hook para perfil visual (con/sin marco): el caller wirea esto al arrancar.
_con_marco_fn = lambda: True

def set_con_marco_fn(fn):
    """Conecta la fuente de verdad del perfil visual."""
    global _con_marco_fn
    _con_marco_fn = fn

def con_marco():
    """Devuelve el bool actual del perfil visual (público para plugins)."""
    return _con_marco_fn()


def _nuevo_lienzo(tamaño):
    """Lienzo RGBA totalmente transparente. El fondo (negro o wallpaper)
    se compone más adelante (en core.render._finalizar)."""
    return Image.new("RGBA", tamaño, (0, 0, 0, 0))


def dibujar_panel_metrica(deck, tamaño, titulo, valor, color,
                           pct=None, valor_color=None, sub=None):
    """Estilo unificado: marco redondeado + título + separador + valor + barra inferior."""
    imagen = _nuevo_lienzo(tamaño)
    dibujo = ImageDraw.Draw(imagen)
    rect = (4, 4, tamaño[0]-5, tamaño[1]-5)
    if _con_marco_fn():
        dibujo.rounded_rectangle(rect, radius=10, outline=color, width=2)
    f_tit = ImageFont.truetype(FONT_PATH, 13)
    dibujo.text((tamaño[0]//2, 15), titulo, font=f_tit, fill=color, anchor="mm")
    dibujo.line((10, 27, tamaño[0]-11, 27), fill=color, width=1)

    vc = valor_color or "#ffffff"
    txt = str(valor)
    max_w = tamaño[0] - 16
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


def dibujar_panel_cores(deck, tamaño, titulo, valores, color_fn):
    """Panel con header + N barras verticales (una por core), color por %."""
    imagen = _nuevo_lienzo(tamaño)
    dibujo = ImageDraw.Draw(imagen)
    rect = (4, 4, tamaño[0]-5, tamaño[1]-5)
    frame_color = color_fn(max(valores) if valores else 0)
    if _con_marco_fn():
        dibujo.rounded_rectangle(rect, radius=10, outline=frame_color, width=2)
    f_tit = ImageFont.truetype(FONT_PATH, 13)
    dibujo.text((tamaño[0]//2, 15), titulo, font=f_tit, fill=frame_color, anchor="mm")
    dibujo.line((10, 27, tamaño[0]-11, 27), fill=frame_color, width=1)

    n = len(valores) or 1
    pad_x = 10
    gap = 4
    zone_top, zone_bot = 34, tamaño[1] - 10
    bar_zone_h = zone_bot - zone_top
    bar_w = (tamaño[0] - 2*pad_x - gap*(n-1)) // n
    f_lbl = ImageFont.truetype(FONT_PATH, 9)
    for i, v in enumerate(valores):
        x = pad_x + i*(bar_w + gap)
        c = color_fn(v)
        dibujo.rectangle((x, zone_top, x+bar_w, zone_bot), outline="#333333", fill="#111111")
        p = max(0, min(100, v))
        fill_h = int(bar_zone_h * (p/100))
        if fill_h > 0:
            dibujo.rectangle((x, zone_bot - fill_h, x+bar_w, zone_bot), fill=c)
        dibujo.text((x + bar_w//2, tamaño[1]-5), str(i+1), font=f_lbl, fill="#888888", anchor="mm")
    return imagen


def dibujar_panel_pings(deck, tamaño, titulo, items):
    """Panel header + N barras verticales para latencias.
    items: lista [(label_corto, pct, color, ms_str), ...]. ms_str se dibuja
    abajo de cada barra."""
    imagen = _nuevo_lienzo(tamaño)
    dibujo = ImageDraw.Draw(imagen)
    rect = (4, 4, tamaño[0]-5, tamaño[1]-5)
    # Color del marco: peor (más alto pct) entre los items.
    worst_color = "#33ff33"
    if items:
        worst = max(items, key=lambda x: x[1])
        worst_color = worst[2]
    if _con_marco_fn():
        dibujo.rounded_rectangle(rect, radius=10, outline=worst_color, width=2)
    f_tit = ImageFont.truetype(FONT_PATH, 13)
    dibujo.text((tamaño[0]//2, 15), titulo, font=f_tit, fill=worst_color, anchor="mm")
    dibujo.line((10, 27, tamaño[0]-11, 27), fill=worst_color, width=1)

    n = len(items) or 1
    pad_x = 8
    gap = 4
    zone_top, zone_bot = 32, tamaño[1] - 16
    bar_zone_h = zone_bot - zone_top
    bar_w = (tamaño[0] - 2*pad_x - gap*(n-1)) // n
    f_lbl = ImageFont.truetype(FONT_PATH, 9)
    for i, (lbl, pct, color, _ms) in enumerate(items):
        x = pad_x + i*(bar_w + gap)
        dibujo.rectangle((x, zone_top, x+bar_w, zone_bot), outline="#333333", fill="#111111")
        p = max(0, min(100, pct))
        fill_h = int(bar_zone_h * (p/100))
        if fill_h > 0:
            dibujo.rectangle((x, zone_bot - fill_h, x+bar_w, zone_bot), fill=color)
        dibujo.text((x + bar_w//2, tamaño[1]-7), lbl, font=f_lbl, fill="#aaaaaa", anchor="mm")
    return imagen


def dibujar_panel_info(deck, tamaño, titulo, valor, frame_color, valor_color="#ffffff"):
    imagen = _nuevo_lienzo(tamaño)
    dibujo = ImageDraw.Draw(imagen)
    rect = (4, 4, tamaño[0]-5, tamaño[1]-5)
    if _con_marco_fn():
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
    if _con_marco_fn():
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


def dibujar_boton_nav(deck, tamaño, titulo, sub1=None, sub2=None,
                       color="#33ccff", activo=False):
    """Botón de navegación con título y hasta 2 sublíneas opcionales."""
    imagen = _nuevo_lienzo(tamaño)
    dibujo = ImageDraw.Draw(imagen)
    rect = (5, 5, tamaño[0]-6, tamaño[1]-6)
    if activo:
        dibujo.rounded_rectangle(rect, radius=12, fill=color)
        title_color, sub_color = "black", "black"
    else:
        if _con_marco_fn():
            dibujo.rounded_rectangle(rect, radius=12, outline=color, width=3)
        title_color, sub_color = "white", color
    max_w = tamaño[0] - 18
    if sub1 and sub2:
        f_tit = ImageFont.truetype(FONT_PATH, 13)
        dibujo.text((tamaño[0]//2, 16), titulo, font=f_tit, fill=title_color, anchor="mm")
        dibujo.line((11, 28, tamaño[0]-12, 28), fill=sub_color, width=1)
        f1 = _fit_font(dibujo, str(sub1), max_w, 16, 10)
        f2 = _fit_font(dibujo, str(sub2), max_w, 20, 11)
        dibujo.text((tamaño[0]//2, 50), str(sub1), font=f1, fill=sub_color, anchor="mm")
        dibujo.text((tamaño[0]//2, 76), str(sub2), font=f2, fill=sub_color, anchor="mm")
    elif sub1:
        f_tit = ImageFont.truetype(FONT_PATH, 13)
        dibujo.text((tamaño[0]//2, 16), titulo, font=f_tit, fill=title_color, anchor="mm")
        dibujo.line((11, 28, tamaño[0]-12, 28), fill=sub_color, width=1)
        f1 = _fit_font(dibujo, str(sub1), max_w, 26, 12)
        dibujo.text((tamaño[0]//2, 62), str(sub1), font=f1, fill=sub_color, anchor="mm")
    else:
        f_tit = ImageFont.truetype(FONT_PATH, 18)
        dibujo.text((tamaño[0]//2, tamaño[1]//2), titulo, font=f_tit, fill=title_color, anchor="mm")
    return imagen


def dibujar_boton_fijo(deck, tamaño, texto, color, relleno=False):
    imagen = _nuevo_lienzo(tamaño)
    dibujo = ImageDraw.Draw(imagen)
    f_btn = ImageFont.truetype(FONT_PATH, 18)
    rect  = (5, 5, tamaño[0]-6, tamaño[1]-6)
    if relleno:
        dibujo.rounded_rectangle(rect, radius=12, fill=color)
        dibujo.text((tamaño[0]//2, tamaño[1]//2), texto, font=f_btn, fill="black", anchor="mm")
    else:
        if _con_marco_fn():
            dibujo.rounded_rectangle(rect, radius=12, outline=color, width=3)
        dibujo.text((tamaño[0]//2, tamaño[1]//2), texto, font=f_btn, fill="white", anchor="mm")
    return imagen


def dibujar_boton_x(deck, tamaño):
    """Botón profesional con X roja, semánticamente "apagar/dim"."""
    imagen = _nuevo_lienzo(tamaño)
    dibujo = ImageDraw.Draw(imagen)
    rect = (4, 4, tamaño[0]-5, tamaño[1]-5)
    dibujo.rounded_rectangle(rect, radius=10, fill="#1a0000")
    if _con_marco_fn():
        dibujo.rounded_rectangle(rect, radius=10, outline="#cc0000", width=2)
    pad = 24
    x1, y1 = pad, pad
    x2, y2 = tamaño[0]-pad-1, tamaño[1]-pad-1
    dibujo.line((x1, y1, x2, y2), fill="#ff3333", width=5)
    dibujo.line((x1, y2, x2, y1), fill="#ff3333", width=5)
    return imagen


def dibujar_negro(deck, tamaño):
    """Tile vacío. _finalizar(None, tecla) compone fondo (negro o wallpaper)."""
    return None


def dibujar_lanzador(deck, tamaño, categoria, color, icono=None, fallback=None):
    """Lanzador con icono del tema del sistema (vía core.iconos.cargar_icono)."""
    imagen = _nuevo_lienzo(tamaño)
    dibujo = ImageDraw.Draw(imagen)
    rect = (4, 4, tamaño[0]-5, tamaño[1]-5)
    if _con_marco_fn():
        dibujo.rounded_rectangle(rect, radius=10, outline=color, width=2)
    f_tit = ImageFont.truetype(FONT_PATH, 13)
    dibujo.text((tamaño[0]//2, 15), categoria, font=f_tit, fill=color, anchor="mm")
    dibujo.line((10, 27, tamaño[0]-11, 27), fill=color, width=1)
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
    """Variante para favicons / iconos arbitrarios desde path absoluto."""
    imagen = _nuevo_lienzo(tamaño)
    dibujo = ImageDraw.Draw(imagen)
    rect = (4, 4, tamaño[0]-5, tamaño[1]-5)
    if _con_marco_fn():
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


def dibujar_btn_icono_nav(deck, tamaño, paths, color, titulo, activo, cache):
    """Botón nav con header + icono coloreable abajo. Cache por (tamaño, activo, titulo, marco)."""
    cache_key = (tamaño, activo, titulo, _con_marco_fn())
    if cache_key in cache:
        return cache[cache_key]
    imagen = _nuevo_lienzo(tamaño)
    dibujo = ImageDraw.Draw(imagen)
    rect = (5, 5, tamaño[0]-6, tamaño[1]-6)
    if activo:
        dibujo.rounded_rectangle(rect, radius=12, fill=color)
        title_color, sep_color = "black", "black"
    else:
        if _con_marco_fn():
            dibujo.rounded_rectangle(rect, radius=12, outline=color, width=3)
        title_color, sep_color = "white", color
    f_tit = ImageFont.truetype(FONT_PATH, 13)
    dibujo.text((tamaño[0]//2, 16), titulo, font=f_tit, fill=title_color, anchor="mm")
    dibujo.line((11, 28, tamaño[0]-12, 28), fill=sep_color, width=1)

    zone_top, zone_bot = 30, tamaño[1] - 6
    zone_h = zone_bot - zone_top
    icono = None
    for path in paths:
        if path and os.path.exists(path):
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
