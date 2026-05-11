"""Plugin PEDAL: integra un Stream Deck Pedal (3 pedales) como entrada
auxiliar del dashboard. Mapeo en SIS:
  - Pedal IZQ/CEN/DER → teclas SIS 29/30/31 (fila inferior, cols 5-7)
  - Hold por pedal     → teclas SIS 21/22/23 (fila intermedia, mismas cols)

Convención Elgato: el pedal central está diseñado como **footrest**
físico (con stoppers opcionales). Aquí se respeta esa convención —
el central muestra "REST" y no dispara acciones.

Protecciones anti-falso-positivo:
  - Debounce: presses < DEBOUNCE_S se descartan (rebotes mecánicos).
  - Disparo en release, no en press (apoyo pasivo no genera evento).
  - Stuck detection: si un pedal queda pisado > STUCK_S, se marca
    "resting"; el release subsiguiente no dispara — sólo re-arma.
  - Cooldown: ventana COOLDOWN_S tras un disparo, ignora nuevos events.
"""
import os
import threading
import time

from StreamDeck.DeviceManager import DeviceManager

from core.widgets import dibujar_panel_info


# --- Mapeo SIS --------------------------------------------------------
TECLAS_SHORT = [29, 30, 31]   # fila 3 — tap por pedal
TECLAS_LONG  = [21, 22, 23]   # fila 2 — hold por pedal
TECLA_REST_DOUBLE = 22        # única tile de doble-tap (sólo centro, fila hold)

# Índice del pedal designado como footrest físico (convención Elgato).
# `None` = los 3 son botones activos.
PEDAL_REST = 1
# Ventana del doble-tap del pedal REST. Es la única acción consciente
# sobre el footrest — tap/hold quedan ignorados como apoyo.
REST_DOUBLE_WINDOW_S = 0.6

LABELS = ["IZQ", "CEN", "DER"]


# --- Umbrales temporales ----------------------------------------------
# Hold por pedal en segundos. El izq necesita más margen — el recorrido
# del pie a la izquierda es menos preciso temporalmente.
LONGPRESS_S = [1.2, 1.0, 1.0]   # [IZQ, CEN, DER]
# Debounce: ignorar pulsaciones <25ms (rebote mecánico).
DEBOUNCE_S  = 0.025
# Stuck: pisado > 5s sin soltar = "resting", el release no dispara.
STUCK_S     = 5.0
# Cooldown post-acción para evitar dobles disparos por rebote al soltar.
COOLDOWN_S  = 0.2
# Duración del "flash" visual al detectar acción.
FLASH_S = 0.7


# --- Paleta -----------------------------------------------------------
COLORS_SHORT = ["#33ddff", "#888888", "#ffcc33"]   # cen dim (REST)
COLORS_LONG  = ["#0088aa", "#555555", "#aa7700"]
COLOR_DOUBLE_CEN = "#66dd66"   # doble-tap del centro
DIM      = "#444444"
TEXT_DIM = "#888888"
REST_COLOR = "#555555"
REST_TEXT  = "#aaaaaa"


# --- Pin opcional por serial ------------------------------------------
PEDAL_SERIAL = os.environ.get("STREAMDEB_PEDAL_SERIAL", "").strip()


# --- Estado interno ---------------------------------------------------
_lock = threading.Lock()
_press_t      = [0.0, 0.0, 0.0]
_pressed      = [False, False, False]
_armed_long   = [False, False, False]   # cruzó umbral mientras se mantiene
_resting      = [False, False, False]   # pisado > STUCK_S → próximo release no dispara
_last_fire_t  = [0.0, 0.0, 0.0]         # epoch del último disparo (cooldown)
_flash_until  = [0.0, 0.0, 0.0]
_flash_kind   = [None, None, None]      # "short" | "long" | "double" | None
_rest_pending_until = 0.0               # epoch hasta cuando un tap REST espera segundo

_forzar_redraw_fn = lambda: None
_on_short      = lambda i: None
_on_long       = lambda i: None
_on_rest_double = lambda: None


def set_forzar_redraw_fn(fn):
    global _forzar_redraw_fn
    _forzar_redraw_fn = fn


def set_handlers(on_short=None, on_long=None, on_rest_double=None):
    """Registra callbacks. `on_short`/`on_long` reciben índice 0..2 y
    sólo disparan para pedales != PEDAL_REST. `on_rest_double` no recibe
    argumentos — es la única acción del pedal REST."""
    global _on_short, _on_long, _on_rest_double
    if on_short       is not None: _on_short       = on_short
    if on_long        is not None: _on_long        = on_long
    if on_rest_double is not None: _on_rest_double = on_rest_double


# --- Device callback --------------------------------------------------

def _key_callback(deck, key, state):
    ahora = time.time()
    if key < 0 or key > 2:
        return
    fire_kind = None
    with _lock:
        if state:
            _pressed[key] = True
            _press_t[key] = ahora
            _armed_long[key] = False
            _resting[key]    = False
        else:
            held = ahora - _press_t[key] if _press_t[key] else 0.0
            _pressed[key] = False
            _armed_long[key] = False
            # Stuck: release tras > STUCK_S → sólo re-arma, no dispara.
            if _resting[key]:
                _resting[key] = False
                print(f"[PEDAL] {key+1} rest-release ({held*1000:.0f}ms) ignorado", flush=True)
            elif held < DEBOUNCE_S:
                print(f"[PEDAL] {key+1} debounce ({held*1000:.0f}ms)", flush=True)
            elif ahora - _last_fire_t[key] < COOLDOWN_S:
                print(f"[PEDAL] {key+1} cooldown ({held*1000:.0f}ms)", flush=True)
            elif key == PEDAL_REST:
                # REST: hold ignorado siempre. Tap intentando ser parte
                # de un doble — si hay pending dentro de ventana, dispara
                # double; si no, abre la ventana.
                global _rest_pending_until
                if held >= LONGPRESS_S[key]:
                    _rest_pending_until = 0.0
                    print(f"[PEDAL] {key+1} REST hold ({held*1000:.0f}ms) ignorado", flush=True)
                elif _rest_pending_until > ahora:
                    _rest_pending_until = 0.0
                    _flash_kind[key]  = "double"
                    _flash_until[key] = ahora + FLASH_S
                    _last_fire_t[key] = ahora
                    fire_kind = "rest_double"
                    print(f"[PEDAL] {key+1} REST double ({held*1000:.0f}ms)", flush=True)
                else:
                    _rest_pending_until = ahora + REST_DOUBLE_WINDOW_S
                    print(f"[PEDAL] {key+1} REST tap-pending ({held*1000:.0f}ms)", flush=True)
            else:
                kind = "long" if held >= LONGPRESS_S[key] else "short"
                _flash_kind[key]  = kind
                _flash_until[key] = ahora + FLASH_S
                _last_fire_t[key] = ahora
                fire_kind = kind
                print(f"[PEDAL] {key+1} {kind} ({held*1000:.0f}ms)", flush=True)

    if fire_kind is not None:
        try:
            if fire_kind == "rest_double":
                _on_rest_double()
            elif fire_kind == "long":
                _on_long(key)
            else:
                _on_short(key)
        except Exception as e:
            print(f"[PEDAL] handler: {e}", flush=True)
    _forzar_redraw_fn()


# --- Device loop ------------------------------------------------------

def _abrir_pedal():
    try:
        for d in DeviceManager().enumerate():
            try:
                if "Pedal" not in d.deck_type():
                    continue
                d.open()
                try:
                    serial = d.get_serial_number()
                except Exception:
                    serial = ""
                if PEDAL_SERIAL and serial != PEDAL_SERIAL:
                    d.close()
                    continue
                print(f"[PEDAL] abierto serial={serial}", flush=True)
                return d
            except Exception as e:
                print(f"[PEDAL] open: {e}", flush=True)
    except Exception as e:
        print(f"[PEDAL] enumerate: {e}", flush=True)
    return None


def tareas_fondo():
    """Hilo: abre el pedal, registra callback, tick para flashes / armado
    long / stuck detection. Reabre si se desconecta en caliente."""
    deck = None
    while True:
        if deck is None:
            deck = _abrir_pedal()
            if deck is not None:
                try: deck.reset()
                except Exception: pass
                try:
                    deck.set_key_callback(_key_callback)
                except Exception as e:
                    print(f"[PEDAL] set_key_callback: {e}", flush=True)
                    deck = None
            else:
                time.sleep(5)
                continue

        ahora = time.time()
        cambio = False
        with _lock:
            global _rest_pending_until
            if _rest_pending_until and ahora >= _rest_pending_until:
                _rest_pending_until = 0.0
                cambio = True   # apaga hint visual del pending
            for i in range(3):
                if _flash_kind[i] is not None and ahora >= _flash_until[i]:
                    _flash_kind[i] = None
                    cambio = True
                if _pressed[i]:
                    held = ahora - _press_t[i]
                    if not _armed_long[i] and held >= LONGPRESS_S[i]:
                        _armed_long[i] = True
                        cambio = True
                    if not _resting[i] and held >= STUCK_S:
                        _resting[i] = True
                        cambio = True
                        print(f"[PEDAL] {i+1} stuck → resting", flush=True)
        if cambio:
            _forzar_redraw_fn()

        try:
            if hasattr(deck, "connected") and not deck.connected():
                print("[PEDAL] desconectado, reintentando", flush=True)
                try: deck.close()
                except Exception: pass
                deck = None
        except Exception:
            pass
        time.sleep(0.15)


# --- Widgets ----------------------------------------------------------

def _estado_visual(i):
    """(c_short, c_long, t_short, t_long) según estado i."""
    ahora = time.time()
    with _lock:
        pressed = _pressed[i]
        armed   = _armed_long[i]
        resting = _resting[i]
        kind    = _flash_kind[i]
        flash_active = kind is not None and ahora < _flash_until[i]

    if i == PEDAL_REST:
        return REST_COLOR, REST_COLOR, REST_TEXT, REST_TEXT

    c_short, c_long = DIM, DIM
    t_short, t_long = TEXT_DIM, TEXT_DIM

    if pressed and not resting:
        # Antes del umbral: nada. Tras cruzar: hold iluminado en vivo.
        if armed:
            c_long, t_long = COLORS_LONG[i], "#ffffff"
    elif flash_active:
        if kind == "short":
            c_short, t_short = COLORS_SHORT[i], "#ffffff"
        else:
            c_long, t_long   = COLORS_LONG[i],  "#ffffff"
    return c_short, c_long, t_short, t_long


def _binding_labels():
    """Lee las etiquetas del binding activo desde plugins.pedal_apps.
    Devuelve dict con keys tap_izq/tap_der/hold_izq/hold_der/double_cen."""
    try:
        from plugins import pedal_apps
        return pedal_apps.current_labels()
    except Exception:
        return {}


def widget_para_sistema(deck, tam):
    """Devuelve dict {tecla: img}: 5 tiles del pedal (tap IZQ/DER, hold
    IZQ/DER, doble-tap CEN) + tile REST estática del centro. Las etiquetas
    son dinámicas — reflejan el binding del app activa (vía pedal_apps)."""
    out = {}
    labels = _binding_labels()
    L = {
        "tap_izq":    labels.get("tap_izq",    "IZQ"),
        "tap_der":    labels.get("tap_der",    "DER"),
        "hold_izq":   labels.get("hold_izq",   "IZQ L"),
        "hold_der":   labels.get("hold_der",   "DER L"),
        "double_cen": labels.get("double_cen", "x2"),
    }
    for i in range(3):
        c_short, c_long, t_short, t_long = _estado_visual(i)
        if i == PEDAL_REST:
            # Fila tap del centro → REST estático (footrest convención Elgato).
            out[TECLAS_SHORT[i]] = dibujar_panel_info(deck, tam, "REST", "·", c_short, valor_color=t_short)
        elif i == 0:  # IZQ
            out[TECLAS_SHORT[i]] = dibujar_panel_info(deck, tam, "IZQ", L["tap_izq"],
                                                      c_short, valor_color=t_short)
            out[TECLAS_LONG[i]]  = dibujar_panel_info(deck, tam, "IZQ L", L["hold_izq"],
                                                      c_long, valor_color=t_long)
        else:  # DER (i == 2)
            out[TECLAS_SHORT[i]] = dibujar_panel_info(deck, tam, "DER", L["tap_der"],
                                                      c_short, valor_color=t_short)
            out[TECLAS_LONG[i]]  = dibujar_panel_info(deck, tam, "DER L", L["hold_der"],
                                                      c_long, valor_color=t_long)

    # Tile extra: doble-tap del centro. Se ilumina mientras hay pending o flash.
    ahora = time.time()
    with _lock:
        pending      = _rest_pending_until > ahora
        flash_active = (_flash_kind[PEDAL_REST] == "double"
                        and ahora < _flash_until[PEDAL_REST])
    c_dbl, t_dbl = DIM, TEXT_DIM
    if pending or flash_active:
        c_dbl, t_dbl = COLOR_DOUBLE_CEN, "#ffffff"
    out[TECLA_REST_DOUBLE] = dibujar_panel_info(
        deck, tam, "CEN x2", L["double_cen"], c_dbl, valor_color=t_dbl,
    )
    return out
