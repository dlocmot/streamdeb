"""Plugin APP (página 4): launcher de aplicaciones del sistema.

Data declarativa en `config/default.toml` o `~/.config/streamdeb/config.toml`.
El dict `APPS_PAGINA` se rellena en `reload()` y se mantiene como **misma
referencia** entre reloads (clear+update) para que los consumidores que
importaron el módulo lo vean siempre actualizado."""
from core.helpers import _lanzar
from core.widgets import dibujar_lanzador


# Misma forma de antes: key → (category, label, command, color, icon)
APPS_PAGINA: dict[int, tuple] = {}


def reload(cfg=None):
    """Reconstruye APPS_PAGINA desde el config TOML (in-place)."""
    if cfg is None:
        from plugins.userconfig import load as _load
        cfg = _load()
    APPS_PAGINA.clear()
    for b in cfg.apps.buttons:
        APPS_PAGINA[b.key] = (b.category, b.label, b.command, b.color, b.icon)
    print(f"[USERCONFIG] apps: {len(APPS_PAGINA)} botones", flush=True)


reload()


def render_pagina_apps(deck, tam, nav_imgs):
    """Renderiza la página APP. `nav_imgs` viene del caller (botones_navegacion)."""
    imgs = dict(nav_imgs)
    for tecla, (cat, label, _cmd, color, icono) in APPS_PAGINA.items():
        imgs[tecla] = dibujar_lanzador(deck, tam, cat, color, icono=icono, fallback=label)
    return imgs


def on_press(tecla):
    """Devuelve True si la tecla pertenece a la página APP y se manejó."""
    if tecla in APPS_PAGINA:
        _lanzar(APPS_PAGINA[tecla][2])
        return True
    return False
