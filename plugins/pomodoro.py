"""Plugin POMODORO: widget en SIS tecla 27 (foco 25min + break 5min).
- Tap corto: avanza estado (idle→running→idle, o break→idle).
- Long-press ≥ LONGPRESS_S: reset a idle.
- Notificación desktop al fin de cada fase."""
import subprocess
import threading
import time

from core.config import LONGPRESS_S
from core.helpers import _env_sesion, _fmt_tiempo
from core.iconos import iconify_png as _iconify_png
from core.widgets import dibujar_lanzador_web, dibujar_panel_metrica


POMODORO_FOCUS_S = 25 * 60
POMODORO_BREAK_S = 5  * 60
TECLA_SIS        = 27

# Estado interno (mutado por evento [input], tareas_fondo [bg] y tick desde
# el render → tres threads). _lock serializa las transiciones para que la
# notificación de fin de fase no se dispare dos veces.
state    = "idle"     # idle | running | break
phase_t  = 0.0        # epoch en que arrancó la fase actual
_lock    = threading.Lock()

# Hook que dashboard_pro setea para forzar redibujo tras cambio de estado
_forzar_redraw_fn = lambda: None
def set_forzar_redraw_fn(fn):
    global _forzar_redraw_fn
    _forzar_redraw_fn = fn


def tick():
    """Avanza el estado: focus expira → break, break expira → idle.
    Devuelve (state, restante_s, total_s, color, label)."""
    global state, phase_t
    ahora = time.time()
    notif = None
    with _lock:
        if state == "running" and ahora - phase_t >= POMODORO_FOCUS_S:
            state = "break"
            phase_t = ahora
            notif = "Foco completo · descanso"
        if state == "break" and ahora - phase_t >= POMODORO_BREAK_S:
            state = "idle"
            phase_t = 0.0
            notif = "Descanso terminado · listo"
        st, pt = state, phase_t
    # notify-send fuera del lock (solo un thread alcanza la transición).
    if notif:
        try:
            subprocess.Popen(["notify-send", "Pomodoro", notif, "-t", "8000"],
                             env=_env_sesion(),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception: pass

    if st == "running":
        rest = max(0, POMODORO_FOCUS_S - (ahora - pt))
        return ("running", rest, POMODORO_FOCUS_S, "#ff6644", "Foco")
    if st == "break":
        rest = max(0, POMODORO_BREAK_S - (ahora - pt))
        return ("break", rest, POMODORO_BREAK_S, "#33dd66", "Break")
    return ("idle", POMODORO_FOCUS_S, POMODORO_FOCUS_S, "#888888", "Pomo")


def evento(held):
    """held >=LONGPRESS_S = reset a idle. Tap corto = avanza estado."""
    global state, phase_t
    ahora = time.time()
    with _lock:
        if held >= LONGPRESS_S:
            state = "idle"
            phase_t = 0.0
            print(f"[POMO] reset (long {held:.1f}s)", flush=True)
        else:
            if state == "idle":
                state, phase_t = "running", ahora
            else:  # running o break → cancela / skip
                state, phase_t = "idle", 0.0
            print(f"[POMO] state={state}", flush=True)
    _forzar_redraw_fn()


def tareas_fondo():
    """Hilo background: tick cada 2s para que las transiciones ocurran
    aunque el usuario esté en otra página."""
    while True:
        try: tick()
        except Exception as e: print(f"[POMO] tick: {e}", flush=True)
        time.sleep(2)


def widget_para_sistema(deck, tam):
    """Tile pomodoro para SIS. Idle = icono tomate (noto multicolor).
    Running = countdown rojo · Break = countdown verde, ambos con barra."""
    p_state, p_rest, p_total, p_color, p_label = tick()
    if p_state == "idle":
        # Tomate canónico (pomodoro = tomate en italiano). noto:tomato es
        # multicolor — color_hex=None preserva su paleta original.
        ico = _iconify_png("noto:tomato", None, 256)
        return {TECLA_SIS: dibujar_lanzador_web(deck, tam, p_label, p_color, ico)}
    p_pct = ((p_total - p_rest) / p_total * 100) if p_total > 0 else 0
    p_val = _fmt_tiempo(int(p_rest))
    return {TECLA_SIS: dibujar_panel_metrica(deck, tam, p_label, p_val, p_color, pct=p_pct)}
