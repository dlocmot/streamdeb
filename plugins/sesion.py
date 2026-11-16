"""Plugin sesión: qué servidor gráfico hay debajo.

Nació al pasar dinamo de MATE/X11 a KDE Plasma sobre Wayland, cuando varias
cosas dejaron de funcionar a la vez por la misma razón: hablaban X11 y bajo
Wayland eso sólo alcanza a las ventanas XWayland, que bajo KDE ya casi no
existen. Cada afectado necesita su propio arreglo — KWin por DBus para colocar
ventanas, PowerDevil por DBus para el brillo — pero todos comparten la misma
pregunta previa, así que la respuesta vive aquí y no duplicada en cada uno.

Consumidores: `plugins/vent.py` (página WIN) y `plugins/monitor.py` (brillo
del monitor externo). El tile de CONF, bajo Perfil V, muestra qué backend está
en uso y permite fijarlo a mano si la detección fallara.
"""
import glob
import json
import os
import tempfile

from core.widgets import dibujar_panel_metrica

BACKEND_MODOS = ("auto", "x11", "wayland")
TECLA_CONF    = 22   # CONF, justo debajo de Perfil V (14)

# Fichero propio y no state.json: _persist_save() de dashboard_pro reescribe
# ese dict entero desde sus globals y se llevaría la clave por delante.
_ESTADO_PATH = os.path.expanduser("~/.config/streamdeb/sesion.json")

backend_modo = "auto"   # elección del usuario; "auto" la resuelve la sesión
_errores     = {}       # origen ("win"/"mon") → nombre de la excepción


def _sesion_es_wayland():
    tipo = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if tipo in ("wayland", "x11"):
        return tipo == "wayland"
    # El servicio --user hereda XDG_SESSION_TYPE en esta máquina, pero no es
    # garantía: si faltara, el socket del compositor es la pista que queda.
    if os.environ.get("WAYLAND_DISPLAY"):
        return True
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return bool(glob.glob(os.path.join(runtime, "wayland-*")))


def backend_activo():
    """"wayland" o "x11": el modo elegido, resolviendo "auto" por la sesión."""
    if backend_modo in ("x11", "wayland"):
        return backend_modo
    return "wayland" if _sesion_es_wayland() else "x11"


def marcar_error(origen, exc):
    """Un consumidor avisa de que su última acción falló; tiñe el tile."""
    _errores[origen] = type(exc).__name__
    print(f"[SESION] {origen} falló con {backend_activo()}: {exc}", flush=True)


def limpiar_error(origen):
    _errores.pop(origen, None)


def _cargar_estado():
    global backend_modo
    try:
        with open(_ESTADO_PATH, encoding="utf-8") as fh:
            modo = json.load(fh).get("backend")
    except FileNotFoundError:
        return
    except Exception as e:
        print(f"[SESION] estado ilegible ({e}); backend en auto", flush=True)
        return
    if modo in BACKEND_MODOS:
        backend_modo = modo


def _guardar_estado():
    try:
        os.makedirs(os.path.dirname(_ESTADO_PATH), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(_ESTADO_PATH),
                                   prefix=".sesion-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"backend": backend_modo}, fh)
        os.replace(tmp, _ESTADO_PATH)
    except Exception as e:
        print(f"[SESION] no se pudo guardar el backend: {e}", flush=True)


_cargar_estado()


def widget_para_config(deck, tam):
    """Tile de CONF: qué backend se usa y si se eligió solo."""
    valor = "Wayl" if backend_activo() == "wayland" else "X11"
    if _errores:
        # Cuál falló importa más que el nombre de la excepción, que no cabe;
        # el detalle completo ya está en el log.
        color, sub = "#ff3333", " ".join(sorted(_errores)) + " err"
    elif backend_modo == "auto":
        color, sub = "#33ff33", "auto"
    else:
        color, sub = "#ffaa00", "fijo"
    return {TECLA_CONF: dibujar_panel_metrica(deck, tam, "Sesión", valor,
                                              color, sub=sub)}


def on_press_config(tecla):
    """Rota auto → X11 → Wayland. True si la tecla era suya."""
    global backend_modo
    if tecla != TECLA_CONF:
        return False
    backend_modo = BACKEND_MODOS[(BACKEND_MODOS.index(backend_modo) + 1)
                                 % len(BACKEND_MODOS)]
    _errores.clear()
    _guardar_estado()
    print(f"[SESION] backend={backend_modo} → se usará {backend_activo()}",
          flush=True)
    return True
