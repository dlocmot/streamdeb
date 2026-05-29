"""Matrix — digital rain verde fósforo sobre negro absoluto.

Es el primer tema ANIMADO: el `background(tamaño, tecla, t)` devuelve un
PIL RGBA con código cayendo en columnas. El loop principal del dashboard
detecta `animated=True` y dispara redraws periódicos a ~8 FPS.

Eficiencia: cada tile mantiene su propio conjunto de columnas (deriv. de
`tecla`) para que las gotas no estén sincronizadas y se vea orgánico.
"""
import random
import time
from PIL import Image, ImageDraw, ImageFont

from core.helpers import cargar_fuente
from plugins.themes import register
from plugins.themes._chromes import matrix_chrome


PALETTE = {
    "primary": "#00FF41",   # verde Matrix
    "alert":   "#FF0033",
    "warn":    "#FFB000",
    "ok":      "#00FF41",
    "info":    "#39FF14",
    "violet":  "#008F11",
    "neutral": "#003B00",
    "ribs":   ("#00FF41", "#008F11", "#003B00"),
}

_GLYPHS = "アァイウエオカキクケコサシスセソタチツテトナニヌネノ" \
          "ハヒフヘホマミムメモヤユヨラリルレロワヲンabcdef0123456789<>?+-=*/"
_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"

# Cache de frame estático por tile — la lluvia se renderiza una sola vez.
_cache = {}

def background(tamaño, tecla, t):
    """Frame Matrix ESTÁTICO (no animado): se computa una vez por tile y
    se reusa. Glifos en verde tenue para no competir con el contenido."""
    W, H = tamaño
    key = (tecla, W, H)
    if key in _cache:
        return _cache[key]
    rnd = random.Random(tecla * 9973 + 7)
    img = Image.new("RGBA", tamaño, (0, 0, 0, 255))
    d = ImageDraw.Draw(img)
    n_cols = 7
    col_w = W // n_cols
    try:
        font = cargar_fuente(max(10, col_w - 2), _FONT_PATH)
    except Exception:
        _cache[key] = img
        return img
    for ci in range(n_cols):
        x = ci * col_w + col_w // 2
        head_y = rnd.randint(-H//3, H - 4)
        length = rnd.randint(4, 8)
        for j in range(length):
            yy = head_y - j * (col_w + 1)
            if yy < -col_w or yy > H:
                continue
            g = _GLYPHS[rnd.randint(0, len(_GLYPHS)-1)]
            if j == 0:
                color = (0x80, 0xC0, 0x80, 220)   # cabeza apagada
            else:
                fade = 1.0 - (j / length)
                v = int(0x20 + 0x40 * fade)      # mucho más tenue
                color = (0x00, v, 0x10, 200)
            d.text((x, int(yy)), g, font=font, fill=color, anchor="mm")
    _cache[key] = img
    return img


register("matrix",
         palette=PALETTE,
         animated=False,
         background=background,
         chrome=matrix_chrome,
         description="Matrix digital rain (estático tenue)")
