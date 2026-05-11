"""Widgets de dibujo primitivos. Sin estado mutable propio salvo:
- caches de PIL retenidos para nav buttons (deliberado: marca _streamdeb_stable=True)
- hooks `_con_marco_fn` / `_perfil_fn` que el caller wirea al arrancar

Perfiles visuales:
  1 = con marco redondeado (default)
  2 = sin marco externo (limpio)
  3 = LCARS estilo TNG (chrome propio: elbow superior + paleta Okuda)
"""
import colorsys
import os
from PIL import Image, ImageDraw, ImageFont

from .config import FONT_PATH
from .helpers import _fit_font
from .iconos import cargar_icono as _cargar_icono


# Hook para perfil visual (con/sin marco): el caller wirea esto al arrancar.
_con_marco_fn = lambda: True
_perfil_fn    = lambda: 1
_lcars_theme_fn = lambda: "classic"  # Sub-tema LCARS por página

def set_con_marco_fn(fn):
    """Conecta la fuente de verdad del perfil visual."""
    global _con_marco_fn
    _con_marco_fn = fn

def set_perfil_fn(fn):
    """Conecta el getter del perfil_visual (int 1/2/3)."""
    global _perfil_fn
    _perfil_fn = fn

def set_lcars_theme_fn(fn):
    """Conecta el getter del sub-tema LCARS activo (str), p.ej. por página."""
    global _lcars_theme_fn
    _lcars_theme_fn = fn

def con_marco():
    """Devuelve el bool actual del perfil visual (público para plugins)."""
    return _con_marco_fn()

def perfil():
    return _perfil_fn()

def es_lcars():
    return _perfil_fn() == 3


# --- LCARS (paleta canónica ha-lcars / theLCARS.com) ------------------
# Hex EXACTOS extraídos de github.com/th3jesta/ha-lcars/themes/lcars.yaml
# (variante TNG). Paleta cálida dominante; violetas como acento.
LCARS_ORANGE    = "#FF7700"   # lcars-orange (primario)
LCARS_PUMPKIN   = "#FF7744"   # lcars-pumpkinshade
LCARS_PEACH     = "#FF8866"   # lcars-peach
LCARS_ALMOND    = "#FFAA90"   # lcars-almond
LCARS_ALMONDCR  = "#FFBBAA"   # lcars-almond-creme
LCARS_SUNFLOWER = "#FFCC66"   # lcars-sunflower
LCARS_GOLD      = "#FFAA00"   # lcars-gold
LCARS_HARVEST   = "#FFAA44"   # lcars-harvestgold
LCARS_LIGHTORG  = "#FF6753"   # lcars-light-orange
LCARS_PALEORG   = "#FF977B"   # lcars-pale-orange
LCARS_RED       = "#DD4444"   # lcars-red (alerta)
LCARS_BLUEY     = "#7788FF"   # lcars-bluey
LCARS_VIOLET    = "#9944FF"   # lcars-violet
LCARS_AFVIOLET  = "#CC88FF"   # lcars-african-violet
LCARS_VIOLETCR  = "#DDBBFF"   # lcars-violet-creme
LCARS_BG        = "#000000"   # lcars-background-color
LCARS_SPACEW    = "#FFFFFF"
# Alias compat
LCARS_MARS      = LCARS_RED
LCARS_BUTTER    = LCARS_PEACH
LCARS_HOPBUSH   = LCARS_AFVIOLET
LCARS_ICE       = LCARS_BLUEY

# Font Antonio (OFL, Google Fonts) — match oficial de Helvetica Ultra
# Compressed según theLCARS.com.
_ANTONIO = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "fonts", "Antonio-Bold.ttf",
)
_LCARS_FONT_PATH = _ANTONIO if os.path.exists(_ANTONIO) else (
    "/usr/share/fonts/truetype/liberation/LiberationSansNarrow-Bold.ttf"
    if os.path.exists("/usr/share/fonts/truetype/liberation/LiberationSansNarrow-Bold.ttf")
    else FONT_PATH
)

def _lcars_font(size):
    try:
        return ImageFont.truetype(_LCARS_FONT_PATH, size)
    except Exception:
        return ImageFont.truetype(FONT_PATH, size)

# Fallback inline si el registry de plugins/themes no está cargado aún
# (típico durante imports antes de autoload). Evita romper widgets en
# arranque temprano.
_FALLBACK_PALETTE = {
    "primary": LCARS_ORANGE, "alert": LCARS_RED,    "warn": LCARS_GOLD,
    "ok":      LCARS_PUMPKIN,"info":  LCARS_BLUEY,  "violet": LCARS_AFVIOLET,
    "neutral": LCARS_ALMONDCR,
    "ribs":   (LCARS_HARVEST, LCARS_AFVIOLET, LCARS_BLUEY),
}

def _theme():
    """Devuelve la paleta del tema activo desde plugins/themes registry."""
    try:
        from plugins import themes as theme_registry
        t = theme_registry.get(_lcars_theme_fn())
        if t is not None:
            return t["palette"]
    except Exception:
        pass
    return _FALLBACK_PALETTE

def _lcars_remap(hex_color):
    """Mapea color de severidad a paleta LCARS, sesgada por el sub-tema activo.
    Rojo→alert, amarillo→warn, verde→ok, cian/azul→info, violeta→violet,
    gris→neutral. Por defecto primary."""
    t = _theme()
    try:
        c = str(hex_color).lstrip("#")
        if len(c) == 3:
            c = "".join(ch*2 for ch in c)
        r = int(c[0:2], 16)/255.0
        g = int(c[2:4], 16)/255.0
        b = int(c[4:6], 16)/255.0
    except Exception:
        return t["primary"]
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    if v < 0.2:  return t["neutral"]
    if s < 0.15: return t["neutral"]
    deg = h * 360
    if deg <  15: return t["alert"]
    if deg <  40: return t["primary"]
    if deg <  65: return t["warn"]
    if deg < 170: return t["ok"]
    if deg < 230: return t["info"]
    if deg < 290: return t["violet"]
    if deg < 340: return t["violet"]
    return t["alert"]

def _lcars_block_number(titulo):
    """Bloque numérico Okuda determinístico a partir del título.
    Formato NN o NN-X. '47' aparece intencionalmente con frecuencia."""
    h = abs(hash(str(titulo).upper())) % 100
    # Sesgo 47 (homenaje Okuda) cuando el hash cae en ciertos buckets.
    if h % 17 == 0:
        h = 47
    return f"{h:02d}"

# Geometría LCARS para tile 96×96. Codo Okuda con arcos CONCÉNTRICOS de
# grosor uniforme T (sidebar y topbar = T). Radios: exterior R, interior r=R-T.
_LCARS_MARGIN  = 3
_LCARS_T       = 14    # grosor del codo (sidebar y topbar)
_LCARS_R_OUT   = 24    # radio exterior del codo
_LCARS_GAP     = 3     # gap negro entre header y body
_LCARS_RIB_H   = 4     # alto de cada rib

_LCARS_STEM_W   = 5      # ancho del stem lateral
_LCARS_FOOTER_H = 2      # alto de la franja inferior (fina)


def _chrome_style():
    """Lee el chrome_style del tema activo (default: lcars)."""
    try:
        from plugins import themes
        t = themes.active()
        return (t or {}).get("chrome_style", "lcars")
    except Exception:
        return "lcars"


def _lcars_chrome(dibujo, tamaño, titulo, color, *, stem=True,
                  block=None, ribs=None):
    """Dispatcher: si el tema activo trae su `chrome` callable propio, úsalo
    con la paleta del tema. Fallback al chrome built-in del style."""
    try:
        from plugins import themes
        t = themes.active() or {}
        ch = t.get("chrome")
        if callable(ch):
            return ch(dibujo, tamaño, titulo, color,
                      stem=stem, block=block, ribs=ribs,
                      palette=t.get("palette", {}))
        style = t.get("chrome_style", "lcars")
    except Exception:
        style = "lcars"
    fn = {
        "lcars":    _chrome_lcars,
        "flat":     _chrome_flat,
        "neon":     _chrome_neon,
        "terminal": _chrome_terminal,
    }.get(style, _chrome_lcars)
    return fn(dibujo, tamaño, titulo, color, stem=stem, block=block, ribs=ribs)


def _chrome_lcars(dibujo, tamaño, titulo, color, *, stem=True,
                  block=None, ribs=None):
    """Mini-panel LCARS auto-contenido para un tile aislado:
      - pill stadium con block + título CAPS arriba
      - stem vertical en lado izq (mismo color) conectando pill con footer
      - footer rib: 2-3 pills mini de colores ha-lcars distintos al pie
    Devuelve (color_tng, body_top)."""
    c = _lcars_remap(color)
    M, T = _LCARS_MARGIN, _LCARS_T

    # Header pill stadium horizontal.
    dibujo.rounded_rectangle(
        (M, M, tamaño[0]-M, M+T), radius=T//2, fill=c,
    )
    label = str(titulo).upper()
    if block is None:
        block = _lcars_block_number(titulo)
    full = f"{block} {label}" if block else label
    label_max_w = tamaño[0] - 2*M - 6
    f = _fit_font(dibujo, full, label_max_w, 12, 8,
                  font_path=_LCARS_FONT_PATH)
    dibujo.text((tamaño[0] - M - 6, M + T//2 + 1),
                full, font=f, fill="black", anchor="rm")

    # Franja inferior fina partida en 3 tramos con la paleta del sub-tema.
    rib_y = tamaño[1] - M - _LCARS_FOOTER_H
    rib_palette = [p for p in _theme()["ribs"] if p != c] or list(_theme()["ribs"])
    rib_total_w = tamaño[0] - 2*M
    seg_w = rib_total_w // 3
    x = M
    for i in range(3):
        x2 = (M + rib_total_w) if i == 2 else (x + seg_w)
        dibujo.rectangle((x, rib_y, x2, rib_y + _LCARS_FOOTER_H),
                         fill=rib_palette[i % len(rib_palette)])
        x = x2

    # Stem lateral izq: rectángulo del color del header conectando pill ↓ footer.
    if stem:
        stem_top = M + T + 2
        stem_bot = rib_y - 2
        if stem_bot > stem_top:
            dibujo.rounded_rectangle(
                (M, stem_top, M + _LCARS_STEM_W, stem_bot),
                radius=_LCARS_STEM_W//2, fill=c,
            )

    body_top = M + T + _LCARS_GAP
    return c, body_top

def _chrome_flat(dibujo, tamaño, titulo, color, *, stem=True,
                 block=None, ribs=None):
    """Estilo minimalista (minimal_dark, terminal_ide): línea de color
    arriba (2px) + título pequeño CAPS, línea inferior fina. Sin pills,
    sin stem, sin ribs."""
    c = _lcars_remap(color)
    M = _LCARS_MARGIN
    # Top accent line
    dibujo.rectangle((M, M, tamaño[0]-M, M+2), fill=c)
    f = _fit_font(dibujo, str(titulo).upper(), tamaño[0]-2*M-4, 10, 8,
                  font_path=_LCARS_FONT_PATH)
    dibujo.text((tamaño[0]-M-2, M+10), str(titulo).upper(),
                font=f, fill=c, anchor="rm")
    # Bottom accent line
    by = tamaño[1] - M - 2
    dibujo.rectangle((M, by, tamaño[0]-M, by+2), fill=c)
    body_top = M + 18
    return c, body_top


def _chrome_neon(dibujo, tamaño, titulo, color, *, stem=True,
                 block=None, ribs=None):
    """Estilo neón con corner brackets (cyberpunk/synthwave/tron/twitch/
    halloween): 4 esquinas tipo [ ] en color neón + título CAPS arriba-izq.
    Sin pills, sin ribs."""
    c = _lcars_remap(color)
    M = _LCARS_MARGIN
    L = 14   # longitud de las patas del corner bracket
    Tk = 2   # grosor del bracket
    W, H = tamaño
    # Top-left bracket
    dibujo.rectangle((M, M, M+L, M+Tk), fill=c)
    dibujo.rectangle((M, M, M+Tk, M+L), fill=c)
    # Top-right
    dibujo.rectangle((W-M-L, M, W-M, M+Tk), fill=c)
    dibujo.rectangle((W-M-Tk, M, W-M, M+L), fill=c)
    # Bottom-left
    dibujo.rectangle((M, H-M-Tk, M+L, H-M), fill=c)
    dibujo.rectangle((M, H-M-L, M+Tk, H-M), fill=c)
    # Bottom-right
    dibujo.rectangle((W-M-L, H-M-Tk, W-M, H-M), fill=c)
    dibujo.rectangle((W-M-Tk, H-M-L, W-M, H-M), fill=c)
    # Título centrado arriba, dentro del marco neón
    full = (f"// {str(titulo).upper()}") if titulo else ""
    f = _fit_font(dibujo, full, W-2*M-L*2-4, 12, 8,
                  font_path=_LCARS_FONT_PATH)
    dibujo.text((W//2, M + L//2 + 2), full,
                font=f, fill=c, anchor="mm")
    body_top = M + L + 6
    return c, body_top


def _chrome_terminal(dibujo, tamaño, titulo, color, *, stem=True,
                     block=None, ribs=None):
    """Estilo terminal/matrix: prompt '> TITLE_' arriba en monospace,
    sin chrome adicional. Pensado para fondos animados (digital rain)."""
    c = _lcars_remap(color)
    M = _LCARS_MARGIN
    mono_path = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
    if not os.path.exists(mono_path):
        mono_path = _LCARS_FONT_PATH
    full = f"> {str(titulo).upper()}"
    f = _fit_font(dibujo, full, tamaño[0]-2*M-4, 12, 8,
                  font_path=mono_path)
    # Sombra negra detrás del texto para legibilidad sobre fondo animado.
    for dx, dy in ((1,0),(-1,0),(0,1),(0,-1)):
        dibujo.text((M+2+dx, M+8+dy), full, font=f, fill="black", anchor="lm")
    dibujo.text((M+2, M+8), full, font=f, fill=c, anchor="lm")
    body_top = M + 18
    return c, body_top


def _lcars_body_x_left(tamaño=None, stem=True):
    """X mínimo libre del body — esquiva el stem lateral si lo hay."""
    if _chrome_style() != "lcars":
        return _LCARS_MARGIN + 4
    return _LCARS_MARGIN + (_LCARS_STEM_W + 4 if stem else 4)

def _lcars_body_bottom(tamaño):
    """Y máximo del body — esquiva el footer rib si lo hay."""
    if _chrome_style() != "lcars":
        return tamaño[1] - _LCARS_MARGIN - 4
    return tamaño[1] - _LCARS_MARGIN - _LCARS_FOOTER_H - 3

def _lcars_rib(dibujo, tamaño, color, *, y=None):
    """Stadium pill horizontal al pie del tile (footer band)."""
    c = _lcars_remap(color)
    M, rh = _LCARS_MARGIN, _LCARS_RIB_H + 2
    y = y if y is not None else tamaño[1] - M - rh
    dibujo.rounded_rectangle(
        (M, y, tamaño[0]-M, y+rh), radius=rh//2, fill=c,
    )


def _nuevo_lienzo(tamaño):
    """Lienzo RGBA totalmente transparente. El fondo (negro o wallpaper)
    se compone más adelante (en core.render._finalizar)."""
    return Image.new("RGBA", tamaño, (0, 0, 0, 0))


def dibujar_panel_metrica(deck, tamaño, titulo, valor, color,
                           pct=None, valor_color=None, sub=None):
    """Estilo unificado: marco redondeado + título + separador + valor + barra inferior."""
    imagen = _nuevo_lienzo(tamaño)
    dibujo = ImageDraw.Draw(imagen)
    lcars = es_lcars()
    if lcars:
        color, body_top = _lcars_chrome(dibujo, tamaño, titulo, color, ribs=3)
        x_off = _lcars_body_x_left(tamaño, stem=True)
    else:
        rect = (4, 4, tamaño[0]-5, tamaño[1]-5)
        if _con_marco_fn():
            dibujo.rounded_rectangle(rect, radius=10, outline=color, width=2)
        f_tit = ImageFont.truetype(FONT_PATH, 13)
        dibujo.text((tamaño[0]//2, 15), titulo, font=f_tit, fill=color, anchor="mm")
        dibujo.line((10, 27, tamaño[0]-11, 27), fill=color, width=1)
        body_top = 28
        x_off = 8

    vc = valor_color or ("#ffffff" if not lcars else LCARS_SPACEW)
    txt = str(valor).upper() if lcars else str(valor)
    max_w = tamaño[0] - x_off - 8
    bottom = 76 if pct is not None else (tamaño[1] - 6)
    cx = (x_off + tamaño[0] - 8) // 2
    cy = (body_top + bottom) // 2
    fp = _LCARS_FONT_PATH if lcars else FONT_PATH

    if " " in txt and sub is None:
        l1, l2 = txt.split(" ", 1)
        f1 = _fit_font(dibujo, l1, max_w, 18, 11, font_path=fp)
        f2 = _fit_font(dibujo, l2, max_w, 18, 11, font_path=fp)
        dibujo.text((cx, cy - 9),  l1, font=f1, fill=vc, anchor="mm")
        dibujo.text((cx, cy + 10), l2, font=f2, fill=vc, anchor="mm")
    elif sub:
        f_val = _fit_font(dibujo, txt, max_w, 22, 12, font_path=fp)
        f_sub = ImageFont.truetype(fp, 12)
        dibujo.text((cx, cy - 8),  txt, font=f_val, fill=vc, anchor="mm")
        dibujo.text((cx, cy + 10), sub.upper() if lcars else sub,
                    font=f_sub, fill="#aaaaaa", anchor="mm")
    else:
        f_val = _fit_font(dibujo, txt, max_w, 30 if lcars else 26, 12, font_path=fp)
        dibujo.text((cx, cy), txt, font=f_val, fill=vc, anchor="mm")

    if pct is not None:
        if lcars:
            x = x_off; ancho = tamaño[0] - x_off - 8
        else:
            x = 10; ancho = tamaño[0] - 20
        alto, y = 8, 78
        p = max(0, min(100, pct))
        dibujo.rectangle((x, y, x + ancho, y + alto), outline="#333333", fill="#111111")
        if p > 0:
            dibujo.rectangle((x, y, x + int(ancho * (p/100)), y + alto), fill=color)
    return imagen


def dibujar_panel_cores(deck, tamaño, titulo, valores, color_fn):
    """Panel con header + N barras verticales (una por core), color por %."""
    imagen = _nuevo_lienzo(tamaño)
    dibujo = ImageDraw.Draw(imagen)
    frame_color = color_fn(max(valores) if valores else 0)
    lcars = es_lcars()
    if lcars:
        frame_color, _ = _lcars_chrome(dibujo, tamaño, titulo, frame_color, stem=False)
        pad_left = 8
    else:
        rect = (4, 4, tamaño[0]-5, tamaño[1]-5)
        if _con_marco_fn():
            dibujo.rounded_rectangle(rect, radius=10, outline=frame_color, width=2)
        f_tit = ImageFont.truetype(FONT_PATH, 13)
        dibujo.text((tamaño[0]//2, 15), titulo, font=f_tit, fill=frame_color, anchor="mm")
        dibujo.line((10, 27, tamaño[0]-11, 27), fill=frame_color, width=1)
        pad_left = 10

    n = len(valores) or 1
    pad_x = pad_left
    gap = 4
    zone_top = 34
    zone_bot = (_lcars_body_bottom(tamaño) - 8) if lcars else (tamaño[1] - 10)
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
        lbl_y = (zone_bot + 5) if lcars else (tamaño[1]-5)
        dibujo.text((x + bar_w//2, lbl_y), str(i+1), font=f_lbl, fill="#888888", anchor="mm")
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
    lcars = es_lcars()
    if lcars:
        worst_color, _ = _lcars_chrome(dibujo, tamaño, titulo, worst_color, stem=False)
    else:
        if _con_marco_fn():
            dibujo.rounded_rectangle(rect, radius=10, outline=worst_color, width=2)
        f_tit = ImageFont.truetype(FONT_PATH, 13)
        dibujo.text((tamaño[0]//2, 15), titulo, font=f_tit, fill=worst_color, anchor="mm")
        dibujo.line((10, 27, tamaño[0]-11, 27), fill=worst_color, width=1)

    n = len(items) or 1
    pad_x = 8
    gap = 4
    zone_top = 32
    zone_bot = (_lcars_body_bottom(tamaño) - 12) if lcars else (tamaño[1] - 16)
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
        lbl_y = (zone_bot + 6) if lcars else (tamaño[1]-7)
        dibujo.text((x + bar_w//2, lbl_y), lbl, font=f_lbl, fill="#aaaaaa", anchor="mm")
    return imagen


def dibujar_panel_info(deck, tamaño, titulo, valor, frame_color, valor_color="#ffffff"):
    imagen = _nuevo_lienzo(tamaño)
    dibujo = ImageDraw.Draw(imagen)
    if es_lcars():
        frame_color, _ = _lcars_chrome(dibujo, tamaño, titulo, frame_color, stem=False)
    else:
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
    if es_lcars():
        frame_color, _ = _lcars_chrome(dibujo, tamaño, titulo, frame_color, stem=False)
    else:
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
    lcars = es_lcars()
    if lcars:
        c_tng = _lcars_remap(color)
        if activo:
            # Activo: píldora LCARS gruesa centrada, label CAPS negro grande.
            pad = (tamaño[1] - 44) // 2
            dibujo.rounded_rectangle(
                (3, pad, tamaño[0]-4, pad+44), radius=22, fill=c_tng,
            )
            f_tit = ImageFont.truetype(FONT_PATH, 18)
            dibujo.text((tamaño[0]//2, pad+22), str(titulo).upper(),
                        font=f_tit, fill="black", anchor="mm")
            _lcars_rib(dibujo, tamaño, color)
            return imagen
        # Inactivo: codo + datos en body.
        _lcars_chrome(dibujo, tamaño, titulo, color, stem=True)
        sub_color = c_tng
        x_left = _lcars_body_x_left(stem=True)
        max_w = tamaño[0] - x_left - 8
        cx = (x_left + tamaño[0] - 8) // 2
        if sub1 and sub2:
            f1 = _fit_font(dibujo, str(sub1), max_w, 16, 10)
            f2 = _fit_font(dibujo, str(sub2), max_w, 20, 11)
            dibujo.text((cx, 56), str(sub1).upper(), font=f1, fill=sub_color, anchor="mm")
            dibujo.text((cx, 78), str(sub2).upper(), font=f2, fill=sub_color, anchor="mm")
        elif sub1:
            f1 = _fit_font(dibujo, str(sub1), max_w, 26, 12)
            dibujo.text((cx, 66), str(sub1).upper(), font=f1, fill=sub_color, anchor="mm")
        return imagen
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
    if es_lcars():
        c = _lcars_remap(color)
        if relleno:
            dibujo.rounded_rectangle(
                (3, 3, tamaño[0]-4, tamaño[1]-4), radius=14, fill=c,
            )
            dibujo.text((tamaño[0]//2, tamaño[1]//2), str(texto).upper(),
                        font=f_btn, fill="black", anchor="mm")
        else:
            # Pill horizontal centrado verticalmente.
            pad_y = (tamaño[1] - 36) // 2
            dibujo.rounded_rectangle(
                (3, pad_y, tamaño[0]-4, pad_y+36), radius=18, fill=c,
            )
            dibujo.text((tamaño[0]//2, pad_y+18), str(texto).upper(),
                        font=f_btn, fill="black", anchor="mm")
        return imagen
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
    if es_lcars():
        # X sobre fondo LCARS plum/orange.
        c = LCARS_MARS
        dibujo.rounded_rectangle(
            (3, 3, tamaño[0]-4, tamaño[1]-4), radius=14, fill="#1a0000",
        )
        dibujo.rounded_rectangle(
            (3, 3, tamaño[0]-4, tamaño[1]-4), radius=14, outline=c, width=3,
        )
        pad = 24
        x1, y1 = pad, pad
        x2, y2 = tamaño[0]-pad-1, tamaño[1]-pad-1
        dibujo.line((x1, y1, x2, y2), fill=c, width=5)
        dibujo.line((x1, y2, x2, y1), fill=c, width=5)
        return imagen
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
    if es_lcars():
        color, body_top = _lcars_chrome(dibujo, tamaño, categoria, color, stem=False)
        zone_top, zone_bot = body_top, tamaño[1] - 6
    else:
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
    if es_lcars():
        color, body_top = _lcars_chrome(dibujo, tamaño, label, color, stem=False)
        zone_top, zone_bot = body_top, tamaño[1] - 6
    else:
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
    """Botón nav con header + icono coloreable abajo. Cache por (tamaño, activo, titulo, marco, perfil)."""
    cache_key = (tamaño, activo, titulo, _con_marco_fn(), _perfil_fn(),
                  _lcars_theme_fn() if _perfil_fn() == 3 else None,
                  _chrome_style() if _perfil_fn() == 3 else None)
    if cache_key in cache:
        return cache[cache_key]
    imagen = _nuevo_lienzo(tamaño)
    dibujo = ImageDraw.Draw(imagen)
    if es_lcars():
        c_tng = _lcars_remap(color)
        if activo:
            dibujo.rounded_rectangle(
                (3, 3, tamaño[0]-4, tamaño[1]-4), radius=14, fill=c_tng,
            )
        else:
            _lcars_chrome(dibujo, tamaño, titulo, color, stem=False)
        zone_top, zone_bot = (30 if not activo else 34), tamaño[1] - 6
    else:
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
