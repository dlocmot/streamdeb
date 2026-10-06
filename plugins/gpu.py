"""Plugin GPU: actividad de la iGPU Intel, leída sin privilegios.

Widget en SIS tecla 12. Sin página propia: es un indicador de un vistazo.

**Qué mide y qué no.** El porcentaje sale de la residencia RC6, el tiempo que
la GPU pasa en su estado de sueño profundo: `100 − RC6` es el tiempo que estuvo
despierta. No es idéntico al uso de los motores de render que reporta
`intel_gpu_top` — una GPU despierta puede estar haciendo poco, así que esta
cifra queda por encima — medido contra `intel_gpu_top` el 2026-10-06, con el
escritorio trabajando: este tile marcaba 88,1 % mientras el motor de render
estaba al 75,6 % y el de vídeo al 11 %, o sea 12,5 puntos de más. A cambio se
lee de sysfs **sin permisos especiales** y sigue la carga con fidelidad (en
reposo cae a 3-4 %). Por eso el tile se titula "GPU activa" y no "GPU".

El cálculo en sí es exacto: coincide con el RC6 que reporta el propio
`intel_gpu_top` con uno o dos puntos de desfase.

El contador exacto vive en el PMU del i915, que exige `CAP_PERFMON` o bajar
`kernel.perf_event_paranoid`; se descartó para no relajar la seguridad del
equipo por un tile.
"""
import glob
import threading
import time

from core.helpers import obtener_color_rango
from core.widgets import dibujar_panel_metrica

TECLA_SIS = 12   # fila 1, donde antes estaba PV (que pasó a la 13)

POLL_S = 2.0     # ventana de muestreo del contador RC6

gpu_info = {
    "ocupada": None,   # % de tiempo despierta, o None si no hay dato aún
    "mhz":     None,
    "error":   None,
}
_lock = threading.Lock()


def _ruta_rc6():
    """Primer contador de residencia RC6 disponible.

    El layout cambió entre versiones del driver: antes colgaba de `power/`,
    en los i915 recientes de `gt/gt0/`. Se aceptan ambos."""
    for patron in ("/sys/class/drm/card*/power/rc6_residency_ms",
                   "/sys/class/drm/card*/gt/gt*/rc6_residency_ms"):
        rutas = sorted(glob.glob(patron))
        if rutas:
            return rutas[0]
    return None


def _leer(ruta):
    with open(ruta) as fh:
        return int(fh.read().strip())


def _freq_mhz():
    """Frecuencia real de la GPU (no la solicitada), o None."""
    for patron in ("/sys/class/drm/card*/gt_act_freq_mhz",
                   "/sys/class/drm/card*/gt/gt*/rps_act_freq_mhz"):
        for ruta in sorted(glob.glob(patron)):
            try:
                return int(open(ruta).read().strip())
            except (OSError, ValueError):
                continue
    return None


def tareas_fondo():
    """Muestrea RC6 cada POLL_S. Dos lecturas y el reloj dan el porcentaje:
    lo que el contador NO avanzó es tiempo que la GPU estuvo despierta."""
    ruta = _ruta_rc6()
    if ruta is None:
        with _lock:
            gpu_info["error"] = "sin RC6"
        print("[GPU] sin contador RC6 en sysfs; el tile quedará en n/d", flush=True)
        return
    try:
        prev, prev_t = _leer(ruta), time.monotonic()
    except Exception as e:
        with _lock:
            gpu_info["error"] = type(e).__name__
        return
    while True:
        time.sleep(POLL_S)
        try:
            ahora_ms, ahora_t = _leer(ruta), time.monotonic()
            transcurrido = (ahora_t - prev_t) * 1000.0
            dormida = ahora_ms - prev
            prev, prev_t = ahora_ms, ahora_t
            if transcurrido <= 0:
                continue
            ocupada = 100.0 - (dormida / transcurrido * 100.0)
            with _lock:
                gpu_info.update(ocupada=max(0.0, min(100.0, ocupada)),
                                mhz=_freq_mhz(), error=None)
        except Exception as e:
            with _lock:
                gpu_info["error"] = type(e).__name__
            print(f"[GPU] lectura fallida: {type(e).__name__}: {e}", flush=True)


def widget_para_sistema(deck, tam):
    with _lock:
        info = dict(gpu_info)
    # El título dice "activa", no "GPU" a secas: lo que se mide es tiempo
    # despierta, que con carga real queda ~12 puntos por encima del uso del
    # motor de render (medido: tile 88,1% vs RCS 75,6%). La etiqueta no debe
    # prometer una precisión que el contador no da.
    if info["ocupada"] is None:
        return {TECLA_SIS: dibujar_panel_metrica(deck, tam, "GPU activa", "n/d",
                                                 "#666666", sub=info["error"] or "…")}
    pct = info["ocupada"]
    sub = f"{info['mhz']}MHz" if info["mhz"] else None
    return {TECLA_SIS: dibujar_panel_metrica(deck, tam, "GPU activa", f"{int(round(pct))}%",
                                             obtener_color_rango(pct), pct=pct, sub=sub)}
