"""Composición final RGBA → bytes nativos JPEG, con cache y dedup USB.

Incluye el chrome LCARS global (perfil 3): en vez de que cada tile dibuje su
propio codo, render.py pinta UN solo frame en L que envuelve todo el deck.
La fila 0 lleva una topbar continua, la columna 0 un sidebar continuo, y el
codo (curva de cuarto de stadium concéntrico) vive sólo en el tile (0,0).
Los tiles internos no llevan chrome global — sólo el contenido del widget.
"""
import io
import math
import os
from PIL import Image, ImageDraw, ImageFont

from . import wallpaper as wp
from .config import FONT_PATH, PREVIEW_DIR
from .helpers import cargar_fuente


# Calidad JPEG del deck. PILHelper.to_native_format usa quality=100 (~6KB/tile);
# el write USB escala con los bytes, así que ~16ms/tile. q=85 es visualmente
# indistinguible en 96×96 y casi mitad de bytes → page-change ~2x más rápido.
DECK_JPEG_QUALITY = int(os.environ.get("STREAMDEB_JPEG_QUALITY", "85"))


def _to_native(deck, image):
    """Como PILHelper.to_native_key_format pero con calidad configurable
    (la lib fuerza 100). Replica resize/rotation/flip para ser model-agnóstico."""
    fmt = deck.key_image_format()
    if image.size != fmt["size"]:
        image.thumbnail(fmt["size"])
    if fmt["rotation"]:
        image = image.rotate(fmt["rotation"])
    if fmt["flip"][0]:
        image = image.transpose(Image.FLIP_LEFT_RIGHT)
    if fmt["flip"][1]:
        image = image.transpose(Image.FLIP_TOP_BOTTOM)
    with io.BytesIO() as buf:
        image.save(buf, fmt["format"], quality=DECK_JPEG_QUALITY)
        return buf.getvalue()


_finalizar_cache = {}        # (id(pil)|0, wallpaper_idx, tecla) → bytes JPEG
_FINALIZAR_CACHE_MAX = 512   # cap defensivo: si crece (PILs dinámicos) se vacía entera
_last_sent = {}              # tecla → bytes (dedup USB writes)

# --- Live preview (mirror para la GUI configuradora) ------------------
# Cada vez que un tile se compone, se guarda como PNG en
# $STREAMDEB_PREVIEW_DIR/page_<id>/tile_<key>.png. La GUI lo lee y
# refleja lo que el deck muestra. PERO escribir 32 PNGs por frame en el
# hilo de render mata la fluidez del deck (~80ms+ de disco por redibujo,
# intercalado con los writes USB → dibujo "fila por fila" lento).
#
# Modo (env STREAMDEB_LIVE_PREVIEW): "0"=off, "1"=on siempre, "auto"=on
# sólo si la GUI está abierta. En "auto" la GUI toca PREVIEW_DIR/.watching
# periódicamente; si el marcador existe y es reciente (<10s), volcamos.
# Default "auto" → el deck va fluido salvo cuando configuras de verdad.
_LIVE_PREVIEW_MODE = os.environ.get("STREAMDEB_LIVE_PREVIEW", "auto").lower()
_WATCH_MARKER = os.path.join(PREVIEW_DIR, ".watching")
_WATCH_TTL = 10.0           # marcador válido si su mtime es < 10s
_WATCH_CHECK_INTERVAL = 2.0  # re-stat del marcador como mucho cada 2s
_current_page_id = 0  # lo wirea dashboard_pro con set_current_page()

_preview_on = False    # estado cacheado del modo auto
_preview_check_t = 0.0


def _preview_enabled():
    """¿Hay que volcar PNGs de preview? Cacheado para no hacer stat por tile."""
    if _LIVE_PREVIEW_MODE == "1":
        return True
    if _LIVE_PREVIEW_MODE == "0":
        return False
    # auto: re-evalúa el marcador como mucho cada _WATCH_CHECK_INTERVAL.
    global _preview_on, _preview_check_t
    import time as _t
    now = _t.time()
    if now - _preview_check_t >= _WATCH_CHECK_INTERVAL:
        _preview_check_t = now
        try:
            _preview_on = (now - os.path.getmtime(_WATCH_MARKER)) < _WATCH_TTL
        except OSError:
            _preview_on = False
    return _preview_on


def set_current_page(page_id: int):
    """Wirea desde dashboard cuando cambia pagina_actual, para que
    _finalizar sepa en qué subdir guardar los tiles. También escribe el
    id a `PREVIEW_DIR/current_page` para que la GUI configurador siga
    al deck en tiempo real."""
    global _current_page_id
    _current_page_id = page_id
    if not _preview_enabled():
        return
    try:
        os.makedirs(PREVIEW_DIR, exist_ok=True)
        with open(os.path.join(PREVIEW_DIR, "current_page"), "w") as f:
            f.write(str(page_id))
    except Exception:
        pass


_dump_errors_logged = 0


def _dump_tile_preview(tecla: int, fondo: Image.Image):
    global _dump_errors_logged
    if _current_page_id == 0 or not _preview_enabled():
        return
    try:
        page_dir = os.path.join(PREVIEW_DIR, f"page_{_current_page_id}")
        os.makedirs(page_dir, exist_ok=True)
        final_path = os.path.join(page_dir, f"tile_{tecla}.jpg")
        # JPEG en vez de PNG: ~4-7x más barato de codificar (el encode es el
        # cuello de botella, no la escritura — PREVIEW_DIR ya es tmpfs/RAM).
        # `fondo` es RGB (compuesto sobre negro), así que no perdemos alpha.
        # Escritura atómica: tempfile + rename. format explícito porque el
        # sufijo `.tmp` impide que PIL lo infiera por extensión.
        tmp_path = final_path + ".tmp"
        fondo.save(tmp_path, format="JPEG", quality=85)
        os.replace(tmp_path, final_path)
    except Exception as e:
        # No tumbar el render, pero loguear los primeros 10 errores para
        # que el operador no quede ciego (era `except: pass` antes).
        if _dump_errors_logged < 10:
            _dump_errors_logged += 1
            print(f"[DUMP] page={_current_page_id} tile={tecla}: "
                  f"{type(e).__name__}: {e}", flush=True)

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
    _ = cargar_fuente(10, _LCARS_FONT)
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
        f = cargar_fuente(13, _LCARS_FONT)
        block = f"{(col*7 + 3):02d}"
        d.text((W - 5, TH//2 + 1), block, font=f, fill="black", anchor="rm")
    elif is_left:
        # Sidebar segment full-height del tile.
        c = _LCARS_RIB_PALETTE[row % len(_LCARS_RIB_PALETTE)]
        d.rectangle((0, 0, SW, H), fill=c)
        f = cargar_fuente(12, _LCARS_FONT)
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
    _dump_tile_preview(tecla, fondo)
    nb = _to_native(deck, fondo)
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
