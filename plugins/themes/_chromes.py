"""Implementaciones de chrome por estilo. Cada theme plugin importa el
helper apropiado y lo pasa a `register(..., chrome=...)`. Comparten aquí
para evitar duplicar código entre temas con look similar.

Cada función firma: `chrome(dibujo, tamaño, titulo, color, *, stem, block, ribs) -> (color_resuelto, body_top)`.
"""
import hashlib
import os
import random
import time
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from core.helpers import _fit_font


# --- Paths a fuentes descargadas ----------------------------------------
_FONTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "fonts",
)

def _font(name, size):
    """Carga TTF del directorio fonts/. Fallback silencioso a DejaVu."""
    path = os.path.join(_FONTS_DIR, name)
    if not os.path.exists(path):
        path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    return ImageFont.truetype(path, size)

ANTONIO     = "Antonio-Bold.ttf"
RAJDHANI    = "Rajdhani-Bold.ttf"
SHARETECH   = "ShareTechMono-Regular.ttf"
ORBITRON    = "Orbitron.ttf"
MONOTON     = "Monoton-Regular.ttf"
VT323       = "VT323-Regular.ttf"
CINZEL      = "Cinzel.ttf"
JETBRAINS   = "JetBrainsMono-Bold.ttf"
BEBAS       = "BebasNeue-Regular.ttf"
SPELITE     = "SpecialElite-Regular.ttf"
INTER       = "Inter.ttf"
MONTSERRAT  = "Montserrat.ttf"


def _stable_id(titulo, mod=100):
    """ID estable a partir del título (para "//ID:47" tipo Okuda/Cyberpunk)."""
    h = hashlib.md5(str(titulo).encode("utf-8")).hexdigest()
    return int(h[:6], 16) % mod


# =====================================================================
# LCARS chrome (Trek themes) — pill + stem + 3-segment footer
# =====================================================================

def lcars_chrome(dibujo, tamaño, titulo, color, *, stem=True,
                 block=None, ribs=None, palette=None):
    from core.widgets import _lcars_remap
    p = palette or {}
    c = _lcars_remap(color)
    M, T = 3, 14
    # Pill header
    dibujo.rounded_rectangle((M, M, tamaño[0]-M, M+T), radius=T//2, fill=c)
    label = str(titulo).upper()
    if block is None:
        block = f"{_stable_id(titulo):02d}"
    full = f"{block} {label}" if block else label
    f = _fit_font(dibujo, full, tamaño[0]-2*M-6, 12, 8,
                  font_path=os.path.join(_FONTS_DIR, ANTONIO))
    dibujo.text((tamaño[0]-M-6, M+T//2+1), full, font=f, fill="black", anchor="rm")
    # Franja inferior 3 tramos
    ribs_palette = list((p.get("ribs") or ("#FFAA44","#CC88FF","#7788FF")))
    ribs_palette = [x for x in ribs_palette if x != c] or ribs_palette
    rib_y = tamaño[1] - M - 2
    seg_w = (tamaño[0] - 2*M) // 3
    x = M
    for i in range(3):
        x2 = (tamaño[0]-M) if i == 2 else (x + seg_w)
        dibujo.rectangle((x, rib_y, x2, rib_y+2),
                         fill=ribs_palette[i % len(ribs_palette)])
        x = x2
    # Stem lateral
    if stem:
        dibujo.rounded_rectangle((M, M+T+2, M+5, rib_y-2), radius=2, fill=c)
    return c, M + T + 3


# =====================================================================
# CYBERPUNK 2077 chrome — corner brackets asimétricos + chip + ID
# =====================================================================

def cyberpunk_chrome(dibujo, tamaño, titulo, color, *, stem=True,
                     block=None, ribs=None, palette=None):
    p = palette or {}
    YEL = p.get("primary", "#FCEE0A")
    CYA = p.get("info",    "#00F0FF")
    W, H = tamaño
    M = 6
    # 2 corner brackets asimétricos: sup-izq + inf-der (look "scan target")
    L, T = 12, 2
    dibujo.rectangle((M, M, M+L, M+T), fill=YEL)
    dibujo.rectangle((M, M, M+T, M+L), fill=YEL)
    dibujo.rectangle((W-M-L, H-M-T, W-M, H-M), fill=YEL)
    dibujo.rectangle((W-M-T, H-M-L, W-M, H-M), fill=YEL)
    # Triángulos clip-corner en sup-der e inf-izq (CDPR signature)
    dibujo.polygon([(W-M-10, M), (W-M, M), (W-M, M+10)], fill=YEL)
    dibujo.polygon([(M, H-M-10), (M, H-M), (M+10, H-M)], fill=YEL)
    # Chip de etiqueta sup-izq (debajo del bracket)
    f_lbl = _font(RAJDHANI, 10)
    label = str(titulo).upper()
    lw = dibujo.textlength(label, font=f_lbl)
    chip_w = int(lw) + 8
    chip_x, chip_y = M + L + 4, M
    dibujo.rectangle((chip_x, chip_y, chip_x + chip_w, chip_y + 13),
                     outline=YEL, width=1)
    dibujo.text((chip_x + 4, chip_y + 7), label, font=f_lbl, fill=YEL, anchor="lm")
    # ID decorativo inf-der en mono cian
    f_id = _font(SHARETECH, 8)
    id_txt = f"//ID:{_stable_id(titulo, 9999):04d}"
    dibujo.text((W-M-L-3, H-M-7), id_txt, font=f_id, fill=CYA, anchor="rm")
    return YEL, M + 20


# =====================================================================
# SYNTHWAVE chrome — gradient bg + grid perspectiva + sol + chromatic
# =====================================================================

def synthwave_chrome(dibujo, tamaño, titulo, color, *, stem=True,
                     block=None, ribs=None, palette=None):
    """Sol semicircular + título arriba (alto 24px); grid perspectiva
    bajo la línea de baseline. Body queda 24..H-14 libre."""
    p = palette or {}
    MAG  = p.get("primary", "#FF2A6D")
    CYAN = p.get("ok",      "#05D9E8")
    W, H = tamaño
    HEADER_H = 24
    # Banner superior con gradient sky + sol pequeño.
    for y in range(0, HEADER_H):
        t = y / HEADER_H
        r = int(0x2D + (0x70 - 0x2D)*t)
        g = int(0x1B + (0x10 - 0x1B)*t)
        b = int(0x4E + (0x40 - 0x4E)*t)
        dibujo.line((0, y, W, y), fill=(r,g,b,255))
    # Sol (medio círculo) en el banner
    sun_r = 14
    sun_cx, sun_cy = W//2, HEADER_H
    for ry in range(sun_r, 0, -1):
        if ry % 2 != 0:  # bandas
            tt = 1 - (ry / sun_r)
            cr = int(0xFF*tt + 0xFF*(1-tt))
            cg = int(0x6E*tt + 0xA5*(1-tt))
            cb = int(0xC7*tt + 0x00*(1-tt))
            dibujo.pieslice((sun_cx-ry, sun_cy-ry, sun_cx+ry, sun_cy+ry),
                            180, 360, fill=(cr, cg, cb, 255))
    # Título "-- CPU --" superpuesto al sol
    f = _font(MONOTON, 13)
    full = f"-- {str(titulo).upper()} --"
    dibujo.text((W//2+1, 11+1), full, font=f, fill="black", anchor="mm")
    dibujo.text((W//2, 11), full, font=f, fill=CYAN, anchor="mm")
    # Grid perspectiva al pie del tile (banda de 14px)
    horizon = H - 14
    vp_x = W//2
    for i in range(-3, 4):
        if i == 0: continue
        x_end = vp_x + i * 24
        dibujo.line((vp_x, horizon, x_end, H-1), fill=MAG, width=1)
    for step in [3, 7, 12]:
        y = horizon + step
        if y < H:
            dibujo.line((0, y, W, y), fill=MAG, width=1)
    return CYAN, HEADER_H + 2


# =====================================================================
# TRON chrome — chamfered frame + tracking masivo + glow cian
# =====================================================================

def tron_chrome(dibujo, tamaño, titulo, color, *, stem=True,
                block=None, ribs=None, palette=None):
    p = palette or {}
    CYA = p.get("primary", "#6FC3DF")
    W, H = tamaño
    M = 4
    # Marco con esquinas a 45° (chamfered): polígono de 8 vértices
    R = 8
    pts = [
        (M+R, M), (W-M-R, M), (W-M, M+R), (W-M, H-M-R),
        (W-M-R, H-M), (M+R, H-M), (M, H-M-R), (M, M+R),
    ]
    dibujo.polygon(pts, outline=CYA, width=1)
    # Doble línea paralela interior (3 px offset)
    pts2 = [(x + (3 if x < W/2 else -3), y + (3 if y < H/2 else -3)) for x, y in pts]
    # Más simple: dibujar 4 lados manualmente con offset
    M2 = M + 3
    R2 = max(R - 2, 4)
    pts_in = [
        (M2+R2, M2), (W-M2-R2, M2), (W-M2, M2+R2), (W-M2, H-M2-R2),
        (W-M2-R2, H-M2), (M2+R2, H-M2), (M2, H-M2-R2), (M2, M2+R2),
    ]
    dibujo.polygon(pts_in, outline=CYA, width=1)
    # Pequeños circuitos: una L en una esquina
    dibujo.line((M+R, M, M+R+8, M), fill=CYA, width=1)
    dibujo.rectangle((M+R+8, M-1, M+R+10, M+1), fill=CYA)
    # Título arriba CAPS expandido (simular tracking con espacios extras)
    label = " ".join(list(str(titulo).upper()))
    f = _font(ORBITRON, 9)
    dibujo.text((W//2, M + 10), label, font=f, fill=CYA, anchor="mm")
    return CYA, M + 22


# =====================================================================
# MATRIX chrome — prompt unix + cursor parpadeante. Bg lo da el theme.
# =====================================================================

def matrix_chrome(dibujo, tamaño, titulo, color, *, stem=True,
                  block=None, ribs=None, palette=None):
    p = palette or {}
    GREEN_BRIGHT = "#CCFFCC"
    GREEN        = p.get("primary", "#00FF41")
    W, H = tamaño
    M = 4
    f = _font(VT323, 14)
    prompt = "root@matrix:~#"
    dibujo.text((M+1, M+8+1), prompt, font=f, fill="black", anchor="lm")
    dibujo.text((M, M+8), prompt, font=f, fill=GREEN, anchor="lm")
    line2 = f"> {str(titulo).lower()}"
    f2 = _font(VT323, 13)
    dibujo.text((M+1, M+22+1), line2, font=f2, fill="black", anchor="lm")
    dibujo.text((M, M+22), line2, font=f2, fill=GREEN_BRIGHT, anchor="lm")
    # Cursor fijo (no parpadea — tema estático)
    cx = M + dibujo.textlength(line2, font=f2) + 2
    dibujo.rectangle((cx, M+16, cx+5, M+28), fill=GREEN)
    return GREEN, M + 32


# =====================================================================
# MINIMAL chrome — cero decoración, sólo tipografía + 1 acento puntual
# =====================================================================

def minimal_chrome(dibujo, tamaño, titulo, color, *, stem=True,
                   block=None, ribs=None, palette=None):
    """Look Linear/Apple: solo tipografía + acento puntual. Cero deco."""
    p = palette or {}
    ACC = p.get("ok",      "#50FA7B")
    SUB = "#86868B"
    W, H = tamaño
    # Punto acento sup-izq + línea hairline sup
    dibujo.ellipse((8, 9, 14, 15), fill=ACC)
    # Título small caps debajo del dot (mismo eje)
    f = _font(INTER, 9)
    dibujo.text((W-8, 12), str(titulo).upper(),
                font=f, fill=SUB, anchor="rm")
    # Separator hairline
    dibujo.line((8, 20, W-8, 20), fill="#2A2A2A", width=1)
    return ACC, 24


# =====================================================================
# TWITCH chrome — borde RGB gradient + drop shadow + chip inferior
# =====================================================================

def twitch_chrome(dibujo, tamaño, titulo, color, *, stem=True,
                  block=None, ribs=None, palette=None):
    p = palette or {}
    PURP = p.get("primary", "#9146FF")
    PINK = p.get("violet",  "#E91E63")
    GREEN = p.get("ok",     "#00FF7F")
    W, H = tamaño
    M = 3
    # Marco redondeado con borde 2px gradient simulado por 3 segmentos.
    # Top edge purp → pink → green dividido en 3
    s = (W - 2*M) // 3
    dibujo.rounded_rectangle((M, M, W-M, H-M), radius=10, outline=PURP, width=2)
    dibujo.line((M+s+10, M+1, W-M-s-10, M+1), fill=PINK, width=2)
    dibujo.line((W-M-s-10, M+1, W-M-1, M+1), fill=GREEN, width=2)
    # Chip inferior con label CAPS blanca
    chip_h = 14
    dibujo.rounded_rectangle((M+4, H-M-chip_h-2, W-M-4, H-M-2),
                             radius=7, fill=PURP)
    f = _font(MONTSERRAT, 11)
    dibujo.text((W//2, H-M-chip_h//2-2), str(titulo).upper(),
                font=f, fill="white", anchor="mm")
    return PURP, M + 4


# =====================================================================
# HALLOWEEN chrome — Cinzel serif + glow rojo radial + grano
# =====================================================================

def halloween_chrome(dibujo, tamaño, titulo, color, *, stem=True,
                     block=None, ribs=None, palette=None):
    """Banner serif Cinzel arriba sobre glow rojo radial elíptico (alto 22).
    Body queda 24..H-12 libre. Asterisco serif al pie."""
    p = palette or {}
    RED  = p.get("alert",   "#FF1744")
    ORG  = p.get("primary", "#FF6A00")
    BONE = "#F4EBD0"
    W, H = tamaño
    HEADER_H = 22
    # Glow rojo elíptico: pintar en RGBA y alpha_composite sobre dibujo.
    base = getattr(dibujo, "_image", None)
    if base is None and hasattr(dibujo, "im"):
        base = dibujo.im
    glow = Image.new("RGBA", (W, H), (0,0,0,0))
    gd = ImageDraw.Draw(glow)
    cy = HEADER_H // 2
    for r in range(28, 4, -3):
        alpha = max(0, 90 - (28-r)*4)
        gd.ellipse((W//2-r, cy-r//2, W//2+r, cy+r//2), fill=(255, 0, 0, alpha))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=2))
    if hasattr(dibujo, "_image"):
        dibujo._image.alpha_composite(glow)
    # Título serif CAPS arriba
    f = _font(CINZEL, 12)
    title = str(titulo).upper()
    dibujo.text((W//2, cy+1), title, font=f, fill=BONE, anchor="mm")
    # Líneas decorativas serif a los lados (under-flank)
    tw = dibujo.textlength(title, font=f)
    line_y = HEADER_H - 3
    side_w = (W - int(tw)) // 2 - 8
    if side_w > 4:
        dibujo.line((6, line_y, 6 + side_w, line_y), fill=RED, width=1)
        dibujo.line((W-6-side_w, line_y, W-6, line_y), fill=RED, width=1)
    # Asterisco ornamental al pie
    f_orn = _font(CINZEL, 11)
    dibujo.text((W//2+1, H-8+1), "✦", font=f_orn, fill="black", anchor="mm")
    dibujo.text((W//2, H-8), "✦", font=f_orn, fill=RED, anchor="mm")
    return ORG, HEADER_H + 4


# =====================================================================
# IDE chrome — JetBrains Mono + sintaxis + line numbers (Dracula)
# =====================================================================

def ide_chrome(dibujo, tamaño, titulo, color, *, stem=True,
               block=None, ribs=None, palette=None):
    p = palette or {}
    FG      = p.get("primary", "#F8F8F2")
    COMMENT = "#6272A4"
    PINK    = "#FF79C6"
    PURPLE  = "#BD93F9"
    YELLOW  = "#F1FA8C"
    W, H = tamaño
    f = _font(JETBRAINS, 9)
    # Gutter line numbers
    for i, n in enumerate(("1", "2", "3")):
        dibujo.text((4, 10 + i*12), n, font=f, fill=COMMENT, anchor="lm")
    gutter = 14
    # Línea 1: comentario "// titulo"
    dibujo.text((gutter, 10), f"// {str(titulo).lower()}",
                font=f, fill=COMMENT, anchor="lm")
    # Línea 2: "key: value" en sintaxis (lo dibujamos en el body después)
    # Aquí solo escribimos la keyword
    dibujo.text((gutter, 22), f"{str(titulo).lower()}:",
                font=f, fill=PINK, anchor="lm")
    return FG, 34
