"""Composición final RGBA → bytes nativos JPEG, con cache y dedup USB."""
from PIL import Image
from StreamDeck.ImageHelpers import PILHelper

from . import wallpaper as wp


_finalizar_cache = {}        # (id(pil)|0, wallpaper_idx, tecla) → bytes JPEG
_FINALIZAR_CACHE_MAX = 512   # cap defensivo: si crece (PILs dinámicos) se vacía entera
_last_sent = {}              # tecla → bytes (dedup USB writes)


def finalizar(deck, tamaño, imagen_rgba, tecla):
    """Compone PIL RGBA sobre el tile de wallpaper (si está ON) o negro,
    devuelve bytes nativos. Cachea SOLO PILs marcados estables (atributo
    `_streamdeb_stable`) o el caso None — un id() de PIL transitorio
    se reutiliza tras GC y devolvería bytes obsoletos de otra página."""
    es_estable = imagen_rgba is None or getattr(imagen_rgba, "_streamdeb_stable", False)
    cache_key = None
    if es_estable:
        cache_key = (id(imagen_rgba) if imagen_rgba is not None else 0,
                     wp.get_idx(), tecla)
        nb = _finalizar_cache.get(cache_key)
        if nb is not None:
            return nb
    if wp.get_idx() > 0:
        tile = wp.tile(tamaño, tecla)
        fondo = tile if tile is not None else Image.new("RGB", tamaño, "black")
    else:
        fondo = Image.new("RGB", tamaño, "black")
    if imagen_rgba is not None:
        fondo.paste(imagen_rgba, (0, 0), imagen_rgba)
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
