"""Plugin WEB (página 6): accesos rápidos a URLs vía favicons.

Data declarativa en `config/default.toml` o `~/.config/streamdeb/config.toml`."""
from core.iconos import favicon_path as _favicon_core
from core.keyboard import tipear_url
from core.widgets import dibujar_lanzador_web


# Misma forma de antes: key → (label, sub, url, color)
WEB_PAGINA: dict[int, tuple] = {}
# url → ruta de icono (override del favicon resuelto automáticamente)
WEB_ICON_OVERRIDE: dict[str, str] = {}


def reload(cfg=None):
    """Reconstruye WEB_PAGINA y WEB_ICON_OVERRIDE desde el config TOML."""
    if cfg is None:
        from plugins.userconfig import load as _load
        cfg = _load()
    WEB_PAGINA.clear()
    for b in cfg.web.buttons:
        WEB_PAGINA[b.key] = (b.label, b.sub, b.url, b.color)
    WEB_ICON_OVERRIDE.clear()
    WEB_ICON_OVERRIDE.update(cfg.web.icon_overrides)
    print(f"[USERCONFIG] web: {len(WEB_PAGINA)} botones, "
          f"{len(WEB_ICON_OVERRIDE)} icon overrides", flush=True)


reload()


def _favicon_path(url):
    return _favicon_core(url, override_dict=WEB_ICON_OVERRIDE)


def render_pagina_web(deck, tam, nav_imgs):
    imgs = dict(nav_imgs)
    for tecla, (label, _sub, url, color) in WEB_PAGINA.items():
        ico = _favicon_path(url)
        imgs[tecla] = dibujar_lanzador_web(deck, tam, label, color, ico)
    return imgs


def on_press(tecla):
    """Tap en página WEB → tipea Ctrl+T + URL + Enter en la app enfocada."""
    if tecla in WEB_PAGINA:
        tipear_url(WEB_PAGINA[tecla][2])
        return True
    return False
