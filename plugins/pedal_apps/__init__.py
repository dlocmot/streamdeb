"""Registry de bindings del Stream Deck Pedal por aplicación activa (WM_CLASS).

Cada `plugins/pedal_apps/<wm_class>.py` registra un mapping de 5 acciones del
pedal a (label, combo). Cuando el detector de contexto (CTX) ve cambio de
WM_CLASS, llama a `sync(wm_class)` para:
  1. Encontrar el binding del app actual (o el 'default' si no hay)
  2. Reinstalar handlers en plugins.pedal con callbacks que ejecutan el combo
  3. Publicar las 5 etiquetas para que los tiles SIS las muestren live

Las 5 acciones (corresponden a las 5 tiles SIS del pedal):
  tap_izq    → SIS 29  (pedal IZQ, tap corto)
  tap_der    → SIS 31  (pedal DER, tap corto)
  hold_izq   → SIS 21  (pedal IZQ, hold)
  hold_der   → SIS 23  (pedal DER, hold)
  double_cen → SIS 22  (pedal CEN, doble-tap; única acción del footrest)

Binding combo: string parseable por core.keyboard.enviar_combo, o callable
`fn()` para acción custom (sin combo).

Para añadir un app: crea `plugins/pedal_apps/<name>.py` con
`register("name", bindings={...})`. Cero modificación de core/dashboard.
"""
import importlib
import os
import pkgutil
import threading


_APPS = {}
_lock = threading.Lock()

# 5 slots fijos — referencia común para tiles SIS y handlers del pedal.
SLOTS = ("tap_izq", "tap_der", "hold_izq", "hold_der", "double_cen")


def register(wm_class, *, bindings, description=""):
    """Registra bindings para una WM_CLASS. `bindings` es dict con 5 keys
    (los SLOTS) → (label_str, combo_or_callable). Combos siguen el formato
    de core.keyboard ('<Ctrl><Shift>r', '<Alt>Left', 'space', etc.).
    Si una key falta, ese slot queda inactivo (label '—')."""
    with _lock:
        _APPS[wm_class] = {
            "wm_class":    wm_class,
            "bindings":    bindings,
            "description": description,
        }


def get(wm_class):
    return _APPS.get(wm_class)


def names():
    return list(_APPS.keys())


def all_apps():
    return dict(_APPS)


def autoload():
    pkg_dir = os.path.dirname(__file__)
    for mod in pkgutil.iter_modules([pkg_dir]):
        if mod.name.startswith("_"):
            continue
        try:
            importlib.import_module(f"plugins.pedal_apps.{mod.name}")
        except Exception as e:
            print(f"[PEDAL-APPS] error cargando {mod.name}: {e}", flush=True)
    print(f"[PEDAL-APPS] cargados: {', '.join(names())}", flush=True)


# --- Sync activo ------------------------------------------------------

# Estado live: app activa + labels resueltos por slot.
_current_app = None
_current_labels = {s: "—" for s in SLOTS}
_listeners = []   # callables() llamados tras cada sync (p.ej. forzar redraw)


def current_app():
    return _current_app


def current_labels():
    """Dict {slot: label_str} del binding actualmente activo."""
    return dict(_current_labels)


def add_listener(fn):
    """Suscribe callable() que se invoca cada vez que sync() cambia bindings."""
    _listeners.append(fn)


def _resolver(wm_class):
    """Devuelve el app entry para wm_class, con cascada a 'default'."""
    if wm_class and wm_class in _APPS:
        return _APPS[wm_class], wm_class
    if "default" in _APPS:
        return _APPS["default"], "default"
    return None, ""


def sync(wm_class):
    """Llamado por CTX cuando cambia la app activa. Reinstala los handlers
    del pedal con los combos del app y publica las nuevas labels."""
    global _current_app, _current_labels
    app, resolved = _resolver(wm_class)
    if resolved == _current_app and app:
        return  # sin cambio efectivo

    _current_app = resolved
    new_labels = {s: "—" for s in SLOTS}
    new_combos = {s: None for s in SLOTS}

    if app:
        for slot, val in (app.get("bindings") or {}).items():
            if slot not in SLOTS:
                continue
            if val is None:
                continue
            label, combo = val
            new_labels[slot] = label
            new_combos[slot] = combo

    _current_labels = new_labels

    # Reinstala handlers en plugins.pedal (lazy import para evitar ciclos).
    try:
        from plugins import pedal as _pedal
        # Mapping slot → pedal callback signature.
        # on_short(i): i=0 IZQ, 1 CEN, 2 DER. on_long(i) idem. on_rest_double().
        def _make_runner(combo):
            from core.keyboard import enviar_combo
            from plugins.contexto import _parse_combo
            def _run():
                if combo is None:
                    return
                if callable(combo):
                    try: combo()
                    except Exception as e:
                        print(f"[PEDAL-APPS] callable err: {e}", flush=True)
                    return
                try:
                    keys = _parse_combo(combo)
                    if not keys:
                        print(f"[PEDAL-APPS] combo '{combo}' no parseable", flush=True)
                        return
                    enviar_combo(keys)
                except Exception as e:
                    print(f"[PEDAL-APPS] combo '{combo}' err: {e}", flush=True)
            return _run

        runners = {s: _make_runner(new_combos[s]) for s in SLOTS}

        def on_short(i):
            if i == 0: runners["tap_izq"]()
            elif i == 2: runners["tap_der"]()
        def on_long(i):
            if i == 0: runners["hold_izq"]()
            elif i == 2: runners["hold_der"]()
        def on_rest_double():
            runners["double_cen"]()

        _pedal.set_handlers(on_short=on_short, on_long=on_long,
                            on_rest_double=on_rest_double)
    except Exception as e:
        print(f"[PEDAL-APPS] sync err: {e}", flush=True)

    print(f"[PEDAL-APPS] active='{_current_app}' "
          f"izq={_current_labels['tap_izq']}/{_current_labels['hold_izq']} "
          f"der={_current_labels['tap_der']}/{_current_labels['hold_der']} "
          f"cen²={_current_labels['double_cen']}", flush=True)

    for fn in list(_listeners):
        try: fn()
        except Exception as e:
            print(f"[PEDAL-APPS] listener: {e}", flush=True)
