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
TECLAS_SHORT = [29, 30, 31]   # fila 3 (cols 5,6,7) — Izq, Cen, Der
TECLAS_LONG  = [21, 22, 23]   # fila 2 (cols 5,6,7) — Izq, Cen, Der

# Índice del pedal designado como footrest físico (convención Elgato).
PEDAL_REST = 1

LABELS = ["IZQ", "CEN", "DER"]


# --- Umbrales temporales ----------------------------------------------
# Hold por pedal en segundos. El pie no-dominante (izq) suele tener
# menos precisión temporal — se le da más margen para que el tap quede
# claramente debajo del umbral. Centro no aplica (es REST).
LONGPRESS_S = [1.0, 0.8, 0.8]   # [IZQ, CEN, DER]
# Debounce: ignorar pulsaciones <40ms (rebote mecánico / bump).
DEBOUNCE_S  = 0.04
# Stuck: pisado > 5s sin soltar = "resting", el release no dispara.
STUCK_S     = 5.0
# Cooldown post-acción para evitar dobles disparos por rebote al soltar.
COOLDOWN_S  = 0.2
# Duración del "flash" visual al detectar acción.
FLASH_S = 0.7


# --- Paleta -----------------------------------------------------------
COLORS_SHORT = ["#33ddff", "#888888", "#ffcc33"]   # cen dim (REST)
COLORS_LONG  = ["#0088aa", "#555555", "#aa7700"]
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
_armed_long   = [False, False, False]   # cruzó LONGPRESS_S mientras se mantiene
_resting      = [False, False, False]   # quedó pisado > STUCK_S → próximo release no dispara
_last_fire_t  = [0.0, 0.0, 0.0]         # epoch del último disparo (cooldown)
_flash_until  = [0.0, 0.0, 0.0]
_flash_kind   = [None, None, None]      # "short" | "long" | None

_forzar_redraw_fn = lambda: None
_on_short = lambda i: None
_on_long  = lambda i: None


def set_forzar_redraw_fn(fn):
    global _forzar_redraw_fn
    _forzar_redraw_fn = fn


def set_handlers(on_short=None, on_long=None):
    """Registra callbacks de acción. Cada uno recibe el índice 0..2.
    El pedal PEDAL_REST nunca dispara — su handler es ignorado."""
    global _on_short, _on_long
    if on_short is not None:
        _on_short = on_short
    if on_long is not None:
        _on_long = on_long


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
            # Debounce: presses muy cortos = bump.
            elif held < DEBOUNCE_S:
                print(f"[PEDAL] {key+1} debounce ({held*1000:.0f}ms)", flush=True)
            # Cooldown: ventana post-disparo para evitar rebote.
            elif ahora - _last_fire_t[key] < COOLDOWN_S:
                print(f"[PEDAL] {key+1} cooldown ({held*1000:.0f}ms)", flush=True)
            # Pedal designado como REST: nunca dispara acción.
            elif key == PEDAL_REST:
                print(f"[PEDAL] {key+1} REST tap ({held*1000:.0f}ms) ignorado", flush=True)
            else:
                kind = "long" if held >= LONGPRESS_S[key] else "short"
                _flash_kind[key]  = kind
                _flash_until[key] = ahora + FLASH_S
                _last_fire_t[key] = ahora
                fire_kind = kind
                print(f"[PEDAL] {key+1} {kind} ({held*1000:.0f}ms)", flush=True)

    if fire_kind is not None:
        try:
            (_on_long if fire_kind == "long" else _on_short)(key)
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
            for i in range(3):
                # Vencimiento de flash visual.
                if _flash_kind[i] is not None and ahora >= _flash_until[i]:
                    _flash_kind[i] = None
                    cambio = True
                if _pressed[i]:
                    held = ahora - _press_t[i]
                    # Cruce de LONGPRESS_S: visual short → long en vivo.
                    if not _armed_long[i] and held >= LONGPRESS_S[i]:
                        _armed_long[i] = True
                        cambio = True
                    # Cruce de STUCK_S: marcar resting (auto-release lógico).
                    if not _resting[i] and held >= STUCK_S:
                        _resting[i] = True
                        cambio = True
                        print(f"[PEDAL] {i+1} stuck → resting", flush=True)
        if cambio:
            _forzar_redraw_fn()

        # Reabrir si se desconecta en caliente.
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
    """(color_short, color_long, txt_short, txt_long) según estado i."""
    ahora = time.time()
    with _lock:
        pressed = _pressed[i]
        armed   = _armed_long[i]
        resting = _resting[i]
        kind    = _flash_kind[i]
        flash_active = kind is not None and ahora < _flash_until[i]

    # Pedal REST: visual estático aunque se pise (se "consume" como rest).
    if i == PEDAL_REST:
        return REST_COLOR, REST_COLOR, REST_TEXT, REST_TEXT

    c_short, c_long = DIM, DIM
    txt_short, txt_long = TEXT_DIM, TEXT_DIM

    if pressed and not resting:
        # Mientras está pisado: NO iluminar tap (sería un falso "vas a
        # hacer tap"). Sólo iluminar long una vez cruzado el umbral —
        # confirma "ya estás en zona de hold". Si suelta antes del
        # umbral, el flash de tap aparece recién al release.
        if armed:
            c_long, txt_long = COLORS_LONG[i], "#ffffff"
    elif flash_active:
        if kind == "short":
            c_short, txt_short = COLORS_SHORT[i], "#ffffff"
        else:
            c_long, txt_long = COLORS_LONG[i], "#ffffff"
    return c_short, c_long, txt_short, txt_long


def widget_para_sistema(deck, tam):
    """Devuelve dict {tecla: img} con las 6 tiles del pedal en SIS."""
    out = {}
    for i in range(3):
        c_short, c_long, t_short, t_long = _estado_visual(i)
        if i == PEDAL_REST:
            label, sub = "REST", "·"
        else:
            label, sub = LABELS[i], "tap"
        out[TECLAS_SHORT[i]] = dibujar_panel_info(
            deck, tam, label, sub, c_short, valor_color=t_short,
        )
        out[TECLAS_LONG[i]] = dibujar_panel_info(
            deck, tam,
            "REST" if i == PEDAL_REST else f"{LABELS[i]} L",
            "·" if i == PEDAL_REST else "hold",
            c_long, valor_color=t_long,
        )
    return out
