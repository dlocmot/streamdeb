"""Plugin monitor: brillo del monitor externo, con dos backends.

**X11** usa `xrandr --brightness`, que no es brillo de verdad sino un
multiplicador sobre la rampa de gamma: oscurece la imagen, no la retro-
iluminación. Bajo Wayland no sirve — xrandr llega a XWayland y el output real
ignora el cambio.

**Wayland** habla con PowerDevil por DBus (`org.kde.ScreenBrightness`, Plasma
6.3+), que en un monitor externo baja el brillo **real por DDC/CI**. Eso es
mejor que lo que había, pero cambia quién manda: el monitor conoce su propio
brillo y cualquiera puede moverlo (el OSD de Plasma, los botones del monitor).
Por eso en este backend el valor se LEE del monitor en vez de llevar la cuenta
aparte — si no, el primer toque daría un salto al valor que recordara streamdeb.

El backend lo decide [plugins/sesion.py]; el tile Monitor de CONF (+ / valor /
−) no cambia.
"""
import subprocess

from core.helpers import _env_sesion
from plugins import sesion

ORIGEN = "mon"          # etiqueta para sesion.marcar_error()

_DBUS_SERVICIO = "org.kde.ScreenBrightness"
_DBUS_IFAZ     = "org.kde.ScreenBrightness.Display"

_output_x11 = None      # output de xrandr, detectado perezosamente


# --- Backend Wayland (PowerDevil / DDC-CI) -----------------------------------

def _qdbus():
    import shutil
    for binario in ("qdbus6", "qdbus", "qdbus-qt6"):
        ruta = shutil.which(binario)
        if ruta:
            return ruta
    raise RuntimeError("sin qdbus")


def _dbus(*args):
    r = subprocess.run([_qdbus(), _DBUS_SERVICIO, *args],
                       capture_output=True, text=True, timeout=3,
                       env=_env_sesion())
    if r.returncode != 0:
        detalle = (r.stderr or r.stdout).strip() or f"rc={r.returncode}"
        raise RuntimeError(detalle.splitlines()[-1])
    return r.stdout.strip()


def _display_path():
    """Ruta DBus del monitor a controlar.

    Se prefiere uno externo: en un portátil con dock, el interno no es el que
    se quiere atenuar desde el deck."""
    rutas = [l.strip() for l in _dbus().splitlines()
             if l.strip().startswith("/org/kde/ScreenBrightness/")]
    if not rutas:
        raise RuntimeError("PowerDevil no expone ningún display")
    for ruta in rutas:
        try:
            interno = _dbus(ruta, "org.freedesktop.DBus.Properties.Get",
                            _DBUS_IFAZ, "IsInternal")
        except Exception:
            continue
        if interno.lower() == "false":
            return ruta
    return rutas[0]


def _prop(ruta, nombre):
    return int(_dbus(ruta, "org.freedesktop.DBus.Properties.Get",
                     _DBUS_IFAZ, nombre))


def _leer_wayland():
    ruta = _display_path()
    maximo = _prop(ruta, "MaxBrightness")
    if maximo <= 0:
        raise RuntimeError("MaxBrightness inválido")
    return round(_prop(ruta, "Brightness") / maximo * 100)


def _aplicar_wayland(pct):
    ruta = _display_path()
    maximo = _prop(ruta, "MaxBrightness")
    if maximo <= 0:
        raise RuntimeError("MaxBrightness inválido")
    _dbus(ruta, f"{_DBUS_IFAZ}.SetBrightness",
          str(round(pct / 100 * maximo)), "0")
    return pct


# --- Backend X11 (xrandr) ----------------------------------------------------

def _detectar_output():
    from core.config import MONITOR_OUTPUT
    if MONITOR_OUTPUT:
        return MONITOR_OUTPUT
    r = subprocess.run(["xrandr", "--listactivemonitors"],
                       capture_output=True, text=True, timeout=2,
                       env=_env_sesion())
    for linea in r.stdout.splitlines():
        partes = linea.strip().split()
        # "0: +*HDMI-1 3840/1050x1200/330+0+0  HDMI-1"
        if len(partes) >= 2 and partes[0].rstrip(":").isdigit():
            return partes[-1]
    raise RuntimeError("xrandr no reporta ningún output activo")


def _aplicar_x11(pct):
    global _output_x11
    if not _output_x11:
        _output_x11 = _detectar_output()
        print(f"[MONITOR] output detectado: {_output_x11}", flush=True)
    r = subprocess.run(["xrandr", "--output", _output_x11,
                        "--brightness", f"{pct / 100:.2f}"],
                       capture_output=True, text=True, timeout=2,
                       env=_env_sesion())
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or f"rc={r.returncode}")
    return pct


# --- API ---------------------------------------------------------------------

def leer_pct():
    """% real del monitor, o None si este backend no sabe leerlo.

    Sólo Wayland: `xrandr --brightness` no es consultable, el multiplicador de
    gamma no se puede recuperar del servidor."""
    if sesion.backend_activo() != "wayland":
        return None
    try:
        pct = _leer_wayland()
        sesion.limpiar_error(ORIGEN)
        return pct
    except Exception as e:
        sesion.marcar_error(ORIGEN, e)
        return None


def paso(delta, actual):
    """Sube o baja el brillo `delta` puntos y devuelve el % efectivo.

    En Wayland parte del valor REAL del monitor, no del que recuerda
    streamdeb: el OSD de Plasma y los botones del propio monitor mueven lo
    mismo, y si alguien lo tocó, un paso desde el valor cacheado daría un
    salto. En X11 no hay nada que leer y el cacheado es la única referencia."""
    from core.config import MONITOR_BRILLO_MAX, MONITOR_BRILLO_MIN
    base = leer_pct()
    if base is None:
        base = actual
    return aplicar(max(MONITOR_BRILLO_MIN,
                       min(MONITOR_BRILLO_MAX, base + delta)))


def aplicar(pct):
    """Fija el brillo al %. Devuelve el % efectivo, o None si falló."""
    pct = max(0, min(100, int(pct)))
    try:
        efectivo = (_aplicar_wayland(pct) if sesion.backend_activo() == "wayland"
                    else _aplicar_x11(pct))
        sesion.limpiar_error(ORIGEN)
        return efectivo
    except Exception as e:
        sesion.marcar_error(ORIGEN, e)
        return None
