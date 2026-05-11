"""Registry de temas LCARS-style para el perfil visual 3.

Cada tema es un plugin Python independiente bajo `plugins/themes/<name>.py`
que llama a `register()` en su top-level. Carga automática vía
`autoload()` al arrancar el dashboard.

Un tema define:
  - name (snake_case)
  - palette: dict con primary/alert/warn/ok/info/violet/neutral/ribs
  - animated: bool — si True, el dashboard programa un tick periódico
  - tick(elapsed_s): opcional, mutación de estado por frame
  - background(tamaño, tecla, t): opcional PIL RGBA del fondo del tile
    en el frame actual (para temas tipo Matrix con código cayendo)

Para añadir un tema nuevo basta con crear `plugins/themes/<nombre>.py`
con `register("nombre", palette={...})` — no se toca core ni dashboard.
"""
import importlib
import os
import pkgutil
import threading


_THEMES = {}
_lock = threading.Lock()
_active_name_fn = lambda: "classic"


def set_active_fn(fn):
    """Conecta el getter del tema activo (callable → str nombre)."""
    global _active_name_fn
    _active_name_fn = fn


def active():
    """Tema activo actual. Fallback a classic si el solicitado no existe."""
    name = _active_name_fn()
    t = _THEMES.get(name)
    if t is None:
        t = _THEMES.get("classic")
    return t


def register(name, *, palette, animated=False, tick=None, background=None,
             description="", chrome_style="lcars", chrome=None):
    """API pública para que un módulo theme se registre.

    chrome_style: 'lcars' | 'flat' | 'neon' | 'terminal'.
      - lcars: pill + stem + 3-segment footer (Trek themes)
      - flat:  línea fina top/bottom + título small CAPS (minimal_dark, terminal_ide)
      - neon:  corner brackets [ ] + título central (cyberpunk, synthwave, tron, twitch, halloween)
      - terminal: prompt '> TITLE_' sobre fondo (matrix)
    """
    with _lock:
        _THEMES[name] = {
            "name":         name,
            "palette":      palette,
            "animated":     animated,
            "tick":         tick,
            "background":   background,
            "description":  description,
            "chrome_style": chrome_style,
            "chrome":       chrome,
        }


def get(name):
    return _THEMES.get(name)


def names():
    """Lista ordenada de nombres registrados (orden de carga)."""
    return list(_THEMES.keys())


def all_themes():
    return dict(_THEMES)


def start_animation_thread(forzar_redraw_fn, fps=8):
    """Loop daemon: si el tema activo es animated, fuerza redraw periódico
    y dispara su tick() si lo expone. fps moderado para no saturar USB."""
    import time
    def loop():
        period = 1.0 / max(1, fps)
        while True:
            try:
                t = active()
                if t and t.get("animated"):
                    if t.get("tick"):
                        try: t["tick"](period)
                        except Exception as e:
                            print(f"[THEMES] tick {t['name']}: {e}", flush=True)
                    forzar_redraw_fn()
            except Exception as e:
                print(f"[THEMES] anim loop: {e}", flush=True)
            time.sleep(period)
    threading.Thread(target=loop, daemon=True, name="themes-anim").start()


def autoload():
    """Importa todos los módulos en este paquete (excepto __init__).
    Cada módulo debe llamar a register() en top-level."""
    pkg_dir = os.path.dirname(__file__)
    for mod in pkgutil.iter_modules([pkg_dir]):
        if mod.name.startswith("_"):
            continue
        try:
            importlib.import_module(f"plugins.themes.{mod.name}")
        except Exception as e:
            print(f"[THEMES] error cargando {mod.name}: {e}", flush=True)
    print(f"[THEMES] cargados: {', '.join(names())}", flush=True)
