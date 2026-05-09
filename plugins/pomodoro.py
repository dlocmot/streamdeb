"""Plugin POMODORO: widget en SIS tecla 11 (foco 25min + break 5min).
- Tap corto: avanza estado (idle→running→idle, o break→idle).
- Long-press ≥ LONGPRESS_S: reset a idle.
- Notificación desktop al fin de cada fase."""
import subprocess
import time

from core.config import LONGPRESS_S
from core.helpers import _env_sesion, _fmt_tiempo
from core.iconos import iconify_png as _iconify_png
from core.widgets import dibujar_lanzador_web, dibujar_panel_metrica


POMODORO_FOCUS_S = 25 * 60
POMODORO_BREAK_S = 5  * 60
TECLA_SIS        = 11

# Estado interno (mutado por _pomodoro_evento y tareas_fondo)
state    = "idle"     # idle | running | break
phase_t  = 0.0        # epoch en que arrancó la fase actual

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
    if state == "running":
        if ahora - phase_t >= POMODORO_FOCUS_S:
            state = "break"
            phase_t = ahora
            try:
                subprocess.Popen(["notify-send", "Pomodoro", "Foco completo · descanso",
                                   "-t", "8000"], env=_env_sesion(),
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception: pass
    if state == "break":
        if ahora - phase_t >= POMODORO_BREAK_S:
            state = "idle"
            phase_t = 0.0
            try:
                subprocess.Popen(["notify-send", "Pomodoro", "Descanso terminado · listo",
                                   "-t", "8000"], env=_env_sesion(),
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception: pass

    if state == "running":
        rest = max(0, POMODORO_FOCUS_S - (ahora - phase_t))
        return ("running", rest, POMODORO_FOCUS_S, "#ff6644", "Foco")
    if state == "break":
        rest = max(0, POMODORO_BREAK_S - (ahora - phase_t))
        return ("break", rest, POMODORO_BREAK_S, "#33dd66", "Break")
    return ("idle", POMODORO_FOCUS_S, POMODORO_FOCUS_S, "#888888", "Pomo")


def evento(held):
    """held >=LONGPRESS_S = reset a idle. Tap corto = avanza estado."""
    global state, phase_t
    ahora = time.time()
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
