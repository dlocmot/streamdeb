"""Resolución de iconos: tema del sistema (hicolor/gnome/mate/flatpak) e Iconify."""
import os
import glob as _glob
import urllib.request
from PIL import Image


_FAVICON_CACHE_DIR = os.path.expanduser("~/.cache/streamdeb/favicons")
_ICONIFY_CACHE_DIR = os.path.expanduser("~/.cache/streamdeb/iconify")

_ICONO_BASES = (
    "/var/lib/flatpak/exports/share/icons/hicolor",
    os.path.expanduser("~/.local/share/icons/hicolor"),
    "/usr/share/icons/hicolor",
    "/usr/share/icons/gnome",
    "/usr/share/icons/mate",
)
_ICONO_TAMS    = ("512x512", "256x256", "128x128", "96x96", "64x64", "48x48")
_ICONO_SUBDIRS = ("apps", "actions", "categories", "places", "status", "devices")

_iconify_paths = {}
_favicon_paths = {}
_icono_cache   = {}


def iconify_png(name, color_hex, size=256):
    """Descarga icono SVG de api.iconify.design, lo rasteriza a PNG (cairosvg)
    y lo cachea por (name, color_hex, size). `color_hex` puede ser None."""
    key = (name, color_hex, size)
    if key in _iconify_paths:
        return _iconify_paths[key]
    os.makedirs(_ICONIFY_CACHE_DIR, exist_ok=True)
    safe = name.replace(":", "_").replace("/", "_")
    color_tag = color_hex if color_hex else "raw"
    path = os.path.join(_ICONIFY_CACHE_DIR, f"{safe}_{color_tag}_{size}.png")
    if not os.path.exists(path) or os.path.getsize(path) < 100:
        if color_hex:
            url = f"https://api.iconify.design/{name}.svg?color=%23{color_hex}"
        else:
            url = f"https://api.iconify.design/{name}.svg"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6) as r:
                svg = r.read()
            import cairosvg
            data = cairosvg.svg2png(bytestring=svg, output_width=size, output_height=size)
            with open(path, "wb") as f:
                f.write(data)
            print(f"[ICONIFY] {name} ({color_hex}) -> {len(data)}B", flush=True)
        except Exception as e:
            print(f"[WARN] iconify {name}: {e}", flush=True)
            _iconify_paths[key] = None
            return None
    _iconify_paths[key] = path
    return path


def favicon_path(url, override_dict=None):
    """Descarga el favicon de un dominio (Google s2 → DDG → directo) y lo cachea.
    `override_dict`: opcional, mapa url → path local o URL alternativa para overrides."""
    from urllib.parse import urlparse
    if url in _favicon_paths:
        return _favicon_paths[url]
    try:
        host = urlparse(url).hostname or url
    except Exception:
        host = url
    os.makedirs(_FAVICON_CACHE_DIR, exist_ok=True)
    path = os.path.join(_FAVICON_CACHE_DIR, f"{host}.png")

    overrides = override_dict or {}
    if url in overrides and not overrides[url].startswith("http"):
        local = overrides[url]
        if os.path.exists(local):
            _favicon_paths[url] = local
            return local

    if not os.path.exists(path) or os.path.getsize(path) < 100:
        sources = []
        if url in overrides and overrides[url].startswith("http"):
            sources.append(overrides[url])
        sources += [
            f"https://www.google.com/s2/favicons?domain={host}&sz=128",
            f"https://icons.duckduckgo.com/ip3/{host}.ico",
            f"https://{host}/favicon.ico",
        ]
        data = None
        for src in sources:
            try:
                req = urllib.request.Request(src, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=4) as r:
                    data = r.read()
                if len(data) >= 100:
                    head = data[:200].lstrip()
                    if head.startswith(b"<?xml") or head.startswith(b"<svg"):
                        try:
                            import cairosvg
                            data = cairosvg.svg2png(bytestring=data,
                                                    output_width=256, output_height=256)
                        except Exception as e:
                            print(f"[WARN] svg2png {host}: {e}", flush=True)
                            data = None
                            continue
                    print(f"[FAVICON] {host} -> {len(data)}B ({src.split('/')[2]})", flush=True)
                    break
                data = None
            except Exception as e:
                print(f"[WARN] favicon {host} via {src.split('/')[2]}: {e}", flush=True)
        if not data:
            _favicon_paths[url] = None
            return None
        with open(path, "wb") as f:
            f.write(data)
    _favicon_paths[url] = path
    return path


def buscar_icono(nombre):
    """Busca un icono en los temas del sistema (hicolor/gnome/mate/flatpak)
    y devuelve la ruta absoluta del PNG, o None si no se encuentra."""
    if not nombre:
        return None
    if os.path.isabs(nombre):
        return nombre if os.path.exists(nombre) else None
    for base in _ICONO_BASES:
        for size in _ICONO_TAMS:
            for sub in _ICONO_SUBDIRS:
                p = f"{base}/{size}/{sub}/{nombre}.png"
                if os.path.exists(p):
                    return p
    for ext in ("png", "xpm"):
        p = f"/usr/share/pixmaps/{nombre}.{ext}"
        if os.path.exists(p):
            return p
    for size in ("128x128", "64x64"):
        m = sorted(_glob.glob(f"/var/lib/flatpak/appstream/flathub/x86_64/*/icons/{size}/{nombre}.png"))
        if m:
            return m[0]
    return None


def cargar_icono(nombre, lado_max):
    """Devuelve PIL.Image RGBA del icono, escalado a `lado_max`. Cachea por (nombre, lado_max)."""
    key = (nombre, lado_max)
    if key in _icono_cache:
        return _icono_cache[key]
    path = buscar_icono(nombre)
    if not path:
        _icono_cache[key] = None
        return None
    try:
        img = Image.open(path).convert("RGBA")
        img.thumbnail((lado_max, lado_max), Image.LANCZOS)
        _icono_cache[key] = img
        return img
    except Exception as e:
        print(f"[ERR ICON] {nombre}: {e}", flush=True)
        _icono_cache[key] = None
        return None
