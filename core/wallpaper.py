"""Wallpaper rotativo (idx 0=OFF, 1..N=imagen). Cachea PIL redimensionado
por idx, los provee como tiles a `core.render._finalizar`."""
import os
from PIL import Image, ImageEnhance

from .config import WALLPAPER_BRILLO, WALLPAPER_SATURACION


# Wallpapers viven en ~/Pictures/wallpapers/ — persisten frente a limpiezas
# de cache, y el usuario puede arrastrar imágenes con cualquier file manager.
WALLPAPER_DIR = os.path.expanduser("~/Pictures/wallpapers")

# Layout del deck (sobreescrito por _abrir_deck → set_layout)
_cols, _rows = 8, 4

# Estado live
wallpaper_idx     = 0       # 0 = OFF
_paths            = None
_paths_mtime      = 0       # mtime del WALLPAPER_DIR la última vez que indexamos
_cache            = {}      # idx → PIL RGB redimensionado
_size             = None    # tamaño de tile cacheado


def set_layout(cols, rows):
    """Llamado desde _abrir_deck con el layout real del deck."""
    global _cols, _rows, _cache, _size
    if (cols, rows) != (_cols, _rows):
        _cache.clear()
        _size = None
    _cols, _rows = cols, rows


def lista_paths():
    """[0]=None (OFF), [1..N]=archivos en WALLPAPER_DIR ordenados.
    Re-indexa automáticamente si cambió el mtime del directorio (auto-detect
    de archivos nuevos / borrados / reemplazados, sin restart)."""
    global _paths, _paths_mtime, _cache
    try:
        mtime = os.path.getmtime(WALLPAPER_DIR) if os.path.isdir(WALLPAPER_DIR) else 0
    except Exception:
        mtime = 0
    if _paths is not None and mtime == _paths_mtime:
        return _paths
    paths = [None]
    if os.path.isdir(WALLPAPER_DIR):
        extras = sorted(
            os.path.join(WALLPAPER_DIR, n)
            for n in os.listdir(WALLPAPER_DIR)
            if n.lower().endswith((".jpg", ".jpeg", ".png"))
        )
        paths.extend(extras)
    cambio = (_paths is not None)
    _paths = paths
    _paths_mtime = mtime
    if cambio:
        _cache.clear()
        # Invalidar también bytes nativos cacheados en core.render
        try:
            from . import render as _r
            _r.invalidar()
        except Exception: pass
    print(f"[WALLPAPER] {len(paths)-1} imágenes disponibles (1..{len(paths)-1})"
          f"{' [reindex]' if cambio else ''}", flush=True)
    return paths


def total():
    return max(0, len(lista_paths()) - 1)


def _cargar(tamaño, idx):
    """PIL RGB de tamaño (cols*W, rows*H) para `idx`, cacheado con brillo+sat aplicados."""
    global _cache, _size
    if _size != tamaño:
        _cache.clear()
        _size = tamaño
    if idx in _cache:
        return _cache[idx]
    paths = lista_paths()
    if idx <= 0 or idx >= len(paths) or not paths[idx] or not os.path.exists(paths[idx]):
        return None
    try:
        img = Image.open(paths[idx]).convert("RGB")
        img = img.resize((_cols * tamaño[0], _rows * tamaño[1]), Image.LANCZOS)
        if WALLPAPER_SATURACION != 1.0:
            img = ImageEnhance.Color(img).enhance(WALLPAPER_SATURACION)
        if WALLPAPER_BRILLO != 1.0:
            img = ImageEnhance.Brightness(img).enhance(WALLPAPER_BRILLO)
        _cache[idx] = img
        return img
    except Exception as e:
        print(f"[WALLPAPER] error cargando idx={idx} ({paths[idx]}): {e}", flush=True)
        return None


def tile(tamaño, tecla):
    """Tile de wallpaper para una tecla concreta. None si OFF / fuera de rango."""
    if wallpaper_idx <= 0 or tecla is None:
        return None
    full = _cargar(tamaño, wallpaper_idx)
    if full is None:
        return None
    row, col = tecla // _cols, tecla % _cols
    box = (col * tamaño[0], row * tamaño[1],
           (col + 1) * tamaño[0], (row + 1) * tamaño[1])
    return full.crop(box).copy()


def get_idx():
    return wallpaper_idx


def set_idx(n):
    global wallpaper_idx
    wallpaper_idx = max(0, n)
