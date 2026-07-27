"""Plugin GRIDWATCH: salud del vigilante de cortes de red pública.

Widget en SIS tecla 27 (fila 4, junto a Docker). Sin página propia: es un
indicador de un vistazo.

**Por qué existe:** grid-watch (repo aparte, desplegado en el VPS `paperclip`)
avisa al celular cuando se va la luz. Pero su silencio es ambiguo — "todo bien"
y "el vigilante está muerto" se ven exactamente igual desde el teléfono. Este
tile convierte esa ausencia en algo visible: si el estado deja de refrescarse,
el tile se pone en alerta aunque no llegue ninguna notificación.

Lee por SSH el `state.json` que grid-watch persiste en su volumen Docker. No
requiere ningún cambio ni puerto abierto en el VPS.
"""
import datetime
import json
import os
import subprocess
import threading
import time

from core.widgets import dibujar_panel_metrica

TECLA_SIS = 27   # fila 4, a la derecha de Docker (26); libre desde que se quitó POMO

# Host tal como está en ~/.ssh/config (clave ya configurada, sin contraseña).
GW_HOST = os.environ.get("STREAMDEB_GRIDWATCH_HOST", "paperclip")
GW_STATE_PATH = os.environ.get(
    "STREAMDEB_GRIDWATCH_STATE",
    "/var/lib/docker/volumes/grid-watch_grid-watch-state/_data/state.json",
)

POLL_S = 300         # el servicio remoto sondea cada 180s; mirar más seguido no aporta
SSH_TIMEOUT_S = 15   # con margen sobre el ConnectTimeout del propio ssh
EDAD_SOSPECHOSA_S = 900   # 15 min sin lectura nueva ⇒ el vigilante no está sano

gw_info = {
    "online":    False,   # ¿pudimos leer el estado remoto?
    "grid":      "unknown",
    # Marca de la última lectura correcta que hizo el VPS. Se guarda el instante,
    # no la edad: la edad se calcula al dibujar para que siga contando entre
    # consultas — con POLL_S de 5 min, una edad congelada mentiría durante
    # minutos justo cuando algo va mal.
    "last_ok":   None,    # datetime aware (UTC) o None
    "cola":      0,       # alertas pendientes de entregar
    "error":     None,
}
_lock = threading.Lock()


def _leer_remoto():
    """Devuelve el dict de state.json del VPS, o lanza."""
    res = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
         GW_HOST, "cat", GW_STATE_PATH],
        capture_output=True, text=True, timeout=SSH_TIMEOUT_S,
    )
    if res.returncode != 0:
        raise RuntimeError((res.stderr or "ssh falló").strip()[:60])
    return json.loads(res.stdout)


def tareas_fondo():
    """Consulta el estado remoto cada POLL_S. Nunca lanza: un fallo de red es
    información (el vigilante no responde), no una excepción que tumbe el hilo."""
    while True:
        try:
            d = _leer_remoto()
            with _lock:
                gw_info.update(online=True, grid=d.get("grid", "unknown"),
                               last_ok=datetime.datetime.fromisoformat(d["last_ok_read_at"]),
                               cola=len(d.get("queue", [])), error=None)
        except Exception as e:
            with _lock:
                gw_info.update(online=False, error=f"{type(e).__name__}")
            print(f"[GRIDWATCH] sin estado remoto: {type(e).__name__}: {e}", flush=True)
        time.sleep(POLL_S)


def _fmt_edad(seg):
    if seg is None:
        return "?"
    seg = int(seg)
    if seg < 90:
        return f"{seg}s"
    if seg < 5400:
        return f"{seg // 60}m"
    return f"{seg // 3600}h"


def widget_para_sistema(deck, tam):
    """Tile de salud en SIS. Verde = vigilando y hay luz · rojo = corte en curso
    · ámbar = el vigilante no responde o lleva demasiado sin leer."""
    with _lock:
        info = dict(gw_info)

    # Edad calculada aquí, no al consultar: entre sondeos sigue contando, así
    # que un vigilante caído se delata solo aunque no hayamos podido preguntar.
    edad = None
    if info["last_ok"] is not None:
        edad = (datetime.datetime.now(datetime.timezone.utc)
                - info["last_ok"]).total_seconds()
    rancio = edad is None or edad > EDAD_SOSPECHOSA_S

    if not info["online"]:
        # No llegamos al VPS: eso ya es la alarma.
        valor, color, sub = "SIN RESP", "#ff9933", info["error"] or "ssh"
    elif rancio:
        valor, color, sub = "PARADO", "#ff9933", _fmt_edad(edad)
    elif info["grid"] == "down":
        valor, color, sub = "CORTE", "#ff3333", _fmt_edad(edad)
    elif info["grid"] == "ok":
        valor, color, sub = "OK", "#33ff33", _fmt_edad(edad)
    else:
        valor, color, sub = "?", "#666666", _fmt_edad(edad)

    # Alertas encoladas sin entregar: el corte se detectó pero el aviso no salió.
    if info["cola"]:
        valor, color = f"{info['cola']} PEND", "#ffaa00"

    return {TECLA_SIS: dibujar_panel_metrica(deck, tam, "GridW", valor, color, sub=sub)}
