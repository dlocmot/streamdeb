"""Helpers puros — sin estado mutable propio."""
import os
import subprocess
from PIL import ImageFont

from .config import FONT_PATH


def _env_sesion():
    """Entorno con DISPLAY/DBUS/XDG para que subprocess hereden el contexto."""
    uid = os.getuid()
    env = os.environ.copy()
    env.setdefault("XDG_RUNTIME_DIR",          f"/run/user/{uid}")
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{uid}/bus")
    env.setdefault("DISPLAY", ":0")
    return env


def _run(cmd):
    """Bloqueante. Loguea stderr si no-cero. Usar para commands cortos donde
    importa el resultado (pactl, etc.). Para apps fire-and-forget, usar _lanzar."""
    res = subprocess.run(cmd, shell=True, env=_env_sesion(), capture_output=True, text=True)
    if res.returncode != 0:
        print(f"[ERR] '{cmd}' → {res.stderr.strip()}", flush=True)


def _lanzar(cmd):
    """Fire-and-forget: app desktop con su propia sesión, sin bloquear."""
    try:
        subprocess.Popen(cmd, shell=True, env=_env_sesion(), start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[LAUNCH] {cmd}", flush=True)
    except Exception as e:
        print(f"[ERR LAUNCH] {cmd}: {e}", flush=True)


def _kp(*keys):
    """Helper para crear listas de teclas en factory de combos."""
    return list(keys)


def _fmt_tiempo(segundos):
    """Formato compacto m'ss" (o h'mm" si ≥1h)."""
    s = max(0, int(segundos))
    if s >= 3600:
        h, rem = divmod(s, 3600)
        return f"{h}'{rem // 60:02d}\""
    m, sec = divmod(s, 60)
    return f"{m}'{sec:02d}\""


def _ip_2_lineas(ip):
    partes = ip.split('.')
    if len(partes) == 4:
        return f"{partes[0]}.{partes[1]}. {partes[2]}.{partes[3]}"
    return ip


def _fit_font(dibujo, txt, max_width, max_size, min_size=10, font_path=None):
    """Devuelve la fuente más grande (≤ max_size) cuyo render de `txt` cabe en max_width."""
    fp = font_path or FONT_PATH
    for size in range(max_size, min_size - 1, -1):
        f = ImageFont.truetype(fp, size)
        if dibujo.textlength(txt, font=f) <= max_width:
            return f
    return ImageFont.truetype(fp, min_size)


def obtener_color_rango(valor):
    """Verde/ámbar/rojo según porcentaje (0-100)."""
    if valor < 30: return "#33ff33"
    elif valor <= 80: return "#ffaa00"
    else: return "#ff3333"
