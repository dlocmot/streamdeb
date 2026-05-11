"""Composición final RGBA → bytes nativos JPEG, con cache y dedup USB.

Incluye el chrome LCARS global (perfil 3): en vez de que cada tile dibuje su
propio codo, render.py pinta UN solo frame en L que envuelve todo el deck.
La fila 0 lleva una topbar continua, la columna 0 un sidebar continuo, y el
codo (curva de cuarto de stadium concéntrico) vive sólo en el tile (0,0).
Los tiles internos no llevan chrome global — sólo el contenido del widget.
"""
import math
from PIL import Image, ImageDraw, ImageFont
from StreamDeck.ImageHelpers import PILHelper

from . import wallpaper as wp
from .config import FONT_PATH


_finalizar_cache = {}        # (id(pil)|0, wallpaper_idx, tecla) → bytes JPEG
_FINALIZAR_CACHE_MAX = 512   # cap defensivo: si crece (PILs dinámicos) se vacía entera
_last_sent = {}              # tecla → bytes (dedup USB writes)

# --- Config LCARS global (wirea desde dashboard) ----------------------
_lcars_cfg = {
    "enabled_fn": lambda: False,
    "cols": 8,
    "rows": 4,
}

def set_lcars_config(enabled_fn, cols, rows):
    _lcars_cfg["enabled_fn"] = enabled_fn
    _lcars_cfg["cols"] = cols
    _lcars_cfg["rows"] = rows
    _finalizar_cache.clear()
    _last_sent.clear()


# --- LCARS chrome geometry --------------------------------------------
# Paleta y geometría se eligen para 96×96. El codo vive sólo en tile (0,0)
# y consume sidebar_w del tile a la izq + topbar_h arriba. Para los tiles
# del resto de fila 0, sólo la topbar; para los tiles del resto de col 0,
# sólo el sidebar.
_LCARS_TOPBAR_H  = 26
_LCARS_SIDEBAR_W = 26
_LCARS_BLEED     = 0    # los tiles físicamente tienen bezel; el ojo une
_LCARS_PUMPKIN   = "#FF9900"
_LCARS_GOLD      = "#FFAA00"
_LCARS_SUNF      = "#FFCC99"
_LCARS_VIOLET    = "#CC99FF"
_LCARS_BLUEY     = "#8899FF"
_LCARS_HOPBUSH   = "#CC5599"
_LCARS_ICE       = "#99CCFF"

_LCARS_FONT = "/usr/share/fonts/truetype/liberation/LiberationSansNarrow-Bold.ttf"
try:
    _ = ImageFont.truetype(_LCARS_FONT, 10)
except Exception:
    _LCARS_FONT = FONT_PATH

# Colores por fila/columna del frame (variedad Okuda).
_LCARS_RIB_PALETTE = [_LCARS_PUMPKIN, _LCARS_VIOLET, _LCARS_SUNF,
                      _LCARS_BLUEY, _LCARS_HOPBUSH, _LCARS_ICE, _LCARS_GOLD]


def _lcars_chrome_for_tile(tamaño, tecla):
    """Devuelve un PIL RGBA con el chrome LCARS de ESTE tile pintado sobre
    fondo transparente, o None si el tile es interno (sin chrome)."""
    cols = _lcars_cfg["cols"]
    rows = _lcars_cfg["rows"]
    row = tecla // cols
    col = tecla %  cols
    is_top  = (row == 0)
    is_left = (col == 0)
    if not (is_top or is_left):
        return None

    W, H = tamaño
    img = Image.new("RGBA", tamaño, (0,0,0,0))
    d = ImageDraw.Draw(img)
    TH = _LCARS_TOPBAR_H
    SW = _LCARS_SIDEBAR_W
    main = _LCARS_PUMPKIN   # color sólido del frame principal

    if is_top and is_left:
        # ESQUINA: codo grande. Cuarto de stadium concéntrico, grosor
        # variable: topbar_h vertical, sidebar_w horizontal.
        # Fill: pieslice exterior 180..270 con radio = max(SW,TH) … pero
        # queremos el codo "L" con grosor distinto en cada brazo. Usamos
        # composición: pintar la L completa (topbar + sidebar) + cuarto
        # de elipse exterior para redondear.
        # 1) Topbar segment (sin la esquina, que la pintará la elipse).
        d.rectangle((SW, 0, W, TH), fill=main)
        # 2) Sidebar segment.
        d.rectangle((0, TH, SW, H), fill=main)
        # 3) Esquina: cuarto de elipse exterior (rx=SW, ry=TH) en cuadrante
        #    180..270 ancla la curva del codo.
        d.pieslice((0, 0, 2*SW, 2*TH), 180, 270, fill=main)
        # 4) Ribs verticales bajo el codo (parte interna del sidebar).
        y = TH + 4
        rib_h = 7
        for i, c in enumerate(_LCARS_RIB_PALETTE[1:5]):
            d.rectangle((0, y, SW, y + rib_h), fill=c)
            y += rib_h + 3
    elif is_top:
        # Topbar segment full-width del tile, color principal.
        # Color varía suavemente por columna para dar variedad Okuda.
        c = _LCARS_RIB_PALETTE[col % len(_LCARS_RIB_PALETTE)]
        d.rectangle((0, 0, W, TH), fill=c)
        # Bloque numérico + label genérico (sólo si se quiere). Se deja
        # vacío: el widget puede dibujar su título debajo si quiere.
        f = ImageFont.truetype(_LCARS_FONT, 13)
        block = f"{(col*7 + 3):02d}"
        d.text((W - 5, TH//2 + 1), block, font=f, fill="black", anchor="rm")
    elif is_left:
        # Sidebar segment full-height del tile.
        c = _LCARS_RIB_PALETTE[row % len(_LCARS_RIB_PALETTE)]
        d.rectangle((0, 0, SW, H), fill=c)
        f = ImageFont.truetype(_LCARS_FONT, 12)
        block = f"{(row*11 + 5):02d}"
        d.text((SW - 4, H - 4), block, font=f, fill="black", anchor="rb")

    return img


def finalizar(deck, tamaño, imagen_rgba, tecla):
    """Compone PIL RGBA sobre el tile de wallpaper (si está ON) o negro,
    devuelve bytes nativos. Cachea SOLO PILs marcados estables (atributo
    `_streamdeb_stable`) o el caso None — un id() de PIL transitorio
    se reutiliza tras GC y devolvería bytes obsoletos de otra página."""
    lcars_on = _lcars_cfg["enabled_fn"]()
    # Detectar tema animado para deshabilitar cache (cada frame es único).
    theme_animated = False
    if lcars_on:
        try:
            from plugins import themes as _themes
            t = _themes.active()
            theme_animated = bool(t and t.get("animated"))
        except Exception:
            pass
    # Cache key incluye flag LCARS para no servir bytes pre-overlay.
    es_estable = imagen_rgba is None or getattr(imagen_rgba, "_streamdeb_stable", False)
    cache_key = None
    if es_estable and not theme_animated:
        cache_key = (id(imagen_rgba) if imagen_rgba is not None else 0,
                     wp.get_idx(), tecla, lcars_on)
        nb = _finalizar_cache.get(cache_key)
        if nb is not None:
            return nb
    bg_animated = None
    if lcars_on:
        # Si el tema activo expone background(animated), úsalo como fondo.
        try:
            from plugins import themes as _themes
            t = _themes.active()
            if t and t.get("background"):
                import time as _time
                bg_animated = t["background"](tamaño, tecla, _time.time())
        except Exception as e:
            print(f"[RENDER] theme bg: {e}", flush=True)

    if bg_animated is not None:
        fondo = Image.new("RGB", tamaño, "black")
        fondo.paste(bg_animated.convert("RGBA"), (0, 0),
                    bg_animated if bg_animated.mode == "RGBA" else None)
    elif wp.get_idx() > 0 and not lcars_on:
        tile = wp.tile(tamaño, tecla)
        fondo = tile if tile is not None else Image.new("RGB", tamaño, "black")
    else:
        # LCARS sin animación: fondo negro absoluto.
        fondo = Image.new("RGB", tamaño, "black")
    if imagen_rgba is not None:
        fondo.paste(imagen_rgba, (0, 0), imagen_rgba)
    # NOTA: el chrome LCARS global (codo continuo across tiles) se intentó
    # pero las bezels físicas del Stream Deck rompen la ilusión — cada tile
    # se ve separado. Mantenemos `set_lcars_config` sólo para invalidar
    # cache al cambiar perfil; el look LCARS lo dibuja cada widget per-tile.
    nb = PILHelper.to_native_format(deck, fondo)
    if cache_key is not None:
        if len(_finalizar_cache) >= _FINALIZAR_CACHE_MAX:
            _finalizar_cache.clear()
        _finalizar_cache[cache_key] = nb
    return nb


def push_key(deck, tecla, nb):
    """Envía al deck solo si los bytes cambiaron — evita USB writes redundantes."""
    if _last_sent.get(tecla) == nb:
        return
    deck.set_key_image(tecla, nb)
    _last_sent[tecla] = nb


def invalidar():
    """Limpia caches cuando cambia contexto global (perfil, wallpaper, reconexión)."""
    _finalizar_cache.clear()
    _last_sent.clear()
