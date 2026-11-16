"""Plugin VENT (página 8): tiling de ventanas, con dos backends.

**X11** usa `wmctrl` con las geometrías absolutas del TOML, calibradas a mano
(ver la sección `[pages.vent]`). Son las mismas que ~/.xbindkeysrc — no se
envía Super+N porque xbindkeys ignora los eventos sintéticos de pynput y
XGrabKey no atrapa XTest.

**Wayland** usa el scripting de KWin por DBus. Es la única vía que coloca una
ventana con geometría exacta en una sesión Wayland: wmctrl y xdotool sólo ven
ventanas XWayland (y bajo KDE casi nada lo es ya), y los atajos de quick-tile
de KWin se quedan en mitades y cuartos, que no cubren los tercios de esta
página. La geometría sale de las fracciones del TOML multiplicadas por el área
útil que reporta `clientArea`, así que no depende de la resolución ni de la
altura del panel de Plasma — a diferencia de los píxeles de wmctrl, que están
atados a los 29 px del panel de MATE.

El backend se elige solo según el tipo de sesión; el tile WIN de SIS permite
fijarlo a mano (auto → X11 → Wayland) para probar o si la detección falla.
"""
import glob
import json
import os
import shutil
import subprocess
import tempfile
from PIL import Image, ImageDraw, ImageFont

from core.config import FONT_PATH
from core.helpers import cargar_fuente
from core.iconos import iconify_png as _iconify_png
from core.widgets import (_nuevo_lienzo, con_marco, dibujar_btn_icono_nav,
                          dibujar_panel_metrica)


# tecla → (label, x_ini, x_fin, y_ini, y_fin, geometría wmctrl "x,y,w,h")
# Data declarativa en config/default.toml; las geometrías están CALIBRADAS para
# 3840×1200 con panel MATE de 29px — ver el comentario de la sección [pages.vent]
# de ese archivo antes de tocarlas (la x,y de wmctrl es la del marco pero el w,h
# es el del cliente, así que hay que descontar la barra de título).
VENT_PAGINA: dict[int, tuple] = {}


def reload(cfg=None):
    """Reconstruye VENT_PAGINA desde el config TOML."""
    if cfg is None:
        from plugins.userconfig import load as _load
        cfg = _load()
    VENT_PAGINA.clear()
    for b in cfg.vent.buttons:
        VENT_PAGINA[b.key] = (
            b.label,
            b.fraction_x[0], b.fraction_x[1],
            b.fraction_y[0], b.fraction_y[1],
            b.wmctrl_geom,
        )
    print(f"[USERCONFIG] vent: {len(VENT_PAGINA)} botones", flush=True)


reload()

_vent_cache = {}


def _vent_nav_paths():
    """Icono nav VENT: mdi:view-quilt rasterizado vía iconify."""
    p = _iconify_png("mdi:view-quilt", "66ddff", 256)
    fallbacks = (
        "/usr/share/icons/ContrastHigh/256x256/actions/view-grid.png",
        "/usr/share/icons/hicolor/256x256/apps/mate-panel-window-list.png",
    )
    return tuple(x for x in (p, *fallbacks) if x)


def dibujar_boton_vent_nav(deck, tamaño, activo=False):
    return dibujar_btn_icono_nav(deck, tamaño, _vent_nav_paths(),
                                  "#66ddff", "WIN", activo, _vent_cache)


def dibujar_vent_preview(deck, tamaño, label, x_ini, x_fin, y_ini, y_fin, color):
    """Botón con preview gráfico de la región objetivo en una mini-pantalla."""
    imagen = _nuevo_lienzo(tamaño)
    dibujo = ImageDraw.Draw(imagen)
    rect = (4, 4, tamaño[0]-5, tamaño[1]-5)
    if con_marco():
        dibujo.rounded_rectangle(rect, radius=10, outline=color, width=2)
    f_tit = cargar_fuente(13)
    dibujo.text((tamaño[0]//2, 15), label, font=f_tit, fill=color, anchor="mm")
    dibujo.line((10, 27, tamaño[0]-11, 27), fill=color, width=1)
    pad_x, pad_top, pad_bot = 14, 36, 14
    sx, sy = pad_x, pad_top
    ex, ey = tamaño[0] - pad_x - 1, tamaño[1] - pad_bot - 1
    dibujo.rectangle((sx, sy, ex, ey), outline="#666666", width=1)
    w, h = ex - sx, ey - sy
    rx1 = sx + int(round(w * x_ini))
    rx2 = sx + int(round(w * x_fin))
    ry1 = sy + int(round(h * y_ini))
    ry2 = sy + int(round(h * y_fin))
    if rx2 > rx1 and ry2 > ry1:
        dibujo.rectangle((rx1+1, ry1+1, rx2-1, ry2-1), fill=color)
    return imagen


def render_pagina_vent(deck, tam, nav_imgs):
    imgs = dict(nav_imgs)
    for tecla, (label, x_ini, x_fin, y_ini, y_fin, _geom) in VENT_PAGINA.items():
        es_mitad_x = (x_fin - x_ini) > 0.34
        es_alto_completo = (y_fin - y_ini) > 0.99
        if es_mitad_x:
            color = "#cc66ff" if es_alto_completo else "#aa55cc"
        else:
            color = "#66ddff" if es_alto_completo else "#4499bb"
        imgs[tecla] = dibujar_vent_preview(deck, tam, label, x_ini, x_fin, y_ini, y_fin, color)
    return imgs


# --- Backend de colocación ---------------------------------------------------

BACKEND_MODOS = ("auto", "x11", "wayland")   # lo que rota el tile de SIS
TECLA_SIS     = 14                            # fila 1, a la derecha de PV (13)

# Estado propio y no state.json: _persist_save() de dashboard_pro reescribe ese
# dict entero desde sus globals y se llevaría por delante cualquier clave ajena.
_ESTADO_PATH = os.path.expanduser("~/.config/streamdeb/vent.json")

_KWIN_JS     = os.path.expanduser("~/.cache/streamdeb/kwin-colocar.js")
_KWIN_NOMBRE = "streamdebColocar"

backend_modo  = "auto"   # elección del usuario; "auto" la resuelve la sesión
_ultimo_error = None     # nombre corto del último fallo, para teñir el tile


# Los bordes se calculan por separado (x1 y x2, no x1 y ancho) para que las
# tres columnas encajen sin huecos de 1 px por redondeo.
_JS_PLANTILLA = """\
// Generado por streamdeb (plugins/vent.py) en cada pulsación.
var w = workspace.activeWindow;
if (w) {{
    var a = workspace.clientArea(KWin.MaximizeArea, w.output, workspace.currentDesktop);
    var x1 = Math.round(a.width  * {xi}), x2 = Math.round(a.width  * {xf});
    var y1 = Math.round(a.height * {yi}), y2 = Math.round(a.height * {yf});
    if (w.fullScreen) w.fullScreen = false;
    w.setMaximize(false, false);
    w.frameGeometry = {{x: a.x + x1, y: a.y + y1,
                       width: x2 - x1, height: y2 - y1}};
}}
"""


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


def _qdbus():
    for binario in ("qdbus6", "qdbus", "qdbus-qt6"):
        ruta = shutil.which(binario)
        if ruta:
            return ruta
    return None


def _colocar_kwin(x_ini, x_fin, y_ini, y_fin):
    """Coloca la ventana activa vía scripting de KWin.

    KWin no ejecuta JS suelto por DBus: hay que escribir el script a disco,
    cargarlo, correrlo y descargarlo en cada pulsación (~100 ms, imperceptible
    en una tecla). El descargar ANTES de cargar no es por limpieza: con el
    nombre ya registrado, `loadScript` devuelve el id viejo sin releer el
    fichero y la tecla repetiría la geometría de la pulsación anterior."""
    binario = _qdbus()
    if binario is None:
        raise RuntimeError("sin qdbus")
    os.makedirs(os.path.dirname(_KWIN_JS), exist_ok=True)
    with open(_KWIN_JS, "w", encoding="utf-8") as fh:
        fh.write(_JS_PLANTILLA.format(xi=x_ini, xf=x_fin, yi=y_ini, yf=y_fin))

    def llamar(objeto, metodo, *args):
        r = subprocess.run([binario, "org.kde.KWin", objeto, metodo, *args],
                           capture_output=True, text=True, timeout=3)
        if r.returncode != 0:
            detalle = (r.stderr or r.stdout).strip() or f"rc={r.returncode}"
            raise RuntimeError(detalle.splitlines()[-1])
        return r.stdout.strip()

    llamar("/Scripting", "org.kde.kwin.Scripting.unloadScript", _KWIN_NOMBRE)
    sid = llamar("/Scripting", "org.kde.kwin.Scripting.loadScript",
                 _KWIN_JS, _KWIN_NOMBRE)
    llamar(f"/Scripting/Script{sid}", "org.kde.kwin.Script.run")
    llamar("/Scripting", "org.kde.kwin.Scripting.unloadScript", _KWIN_NOMBRE)


def _colocar_wmctrl(geom):
    subprocess.run(["wmctrl", "-r", ":ACTIVE:", "-b",
                     "remove,maximized_vert,maximized_horz"],
                   check=False, timeout=2)
    subprocess.run(["wmctrl", "-r", ":ACTIVE:", "-e", geom],
                   check=False, timeout=2)


def _cargar_estado():
    global backend_modo
    try:
        with open(_ESTADO_PATH, encoding="utf-8") as fh:
            modo = json.load(fh).get("backend")
    except FileNotFoundError:
        return
    except Exception as e:
        print(f"[VENT] estado ilegible ({e}); backend en auto", flush=True)
        return
    if modo in BACKEND_MODOS:
        backend_modo = modo


def _guardar_estado():
    try:
        os.makedirs(os.path.dirname(_ESTADO_PATH), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(_ESTADO_PATH),
                                   prefix=".vent-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"backend": backend_modo}, fh)
        os.replace(tmp, _ESTADO_PATH)
    except Exception as e:
        print(f"[VENT] no se pudo guardar el backend: {e}", flush=True)


_cargar_estado()


def widget_para_sistema(deck, tam):
    """Tile WIN de SIS: qué backend coloca las ventanas y cómo se eligió."""
    activo = backend_activo()
    valor  = "Wayl" if activo == "wayland" else "X11"
    if _ultimo_error:
        color, sub = "#ff3333", _ultimo_error
    elif backend_modo == "auto":
        color, sub = "#33ff33", "auto"
    else:
        color, sub = "#ffaa00", "fijo"
    return {TECLA_SIS: dibujar_panel_metrica(deck, tam, "Ventanas", valor,
                                             color, sub=sub)}


def on_press_sistema(tecla):
    """Tecla 14 de SIS: rota auto → X11 → Wayland. True si la tecla era suya."""
    global backend_modo, _ultimo_error
    if tecla != TECLA_SIS:
        return False
    backend_modo = BACKEND_MODOS[(BACKEND_MODOS.index(backend_modo) + 1)
                                 % len(BACKEND_MODOS)]
    _ultimo_error = None
    _guardar_estado()
    print(f"[VENT] backend={backend_modo} → coloca con {backend_activo()}",
          flush=True)
    return True


def on_press(tecla):
    global _ultimo_error
    if tecla not in VENT_PAGINA:
        return False
    label, x_ini, x_fin, y_ini, y_fin, geom = VENT_PAGINA[tecla]
    destino = backend_activo()
    try:
        if destino == "wayland":
            _colocar_kwin(x_ini, x_fin, y_ini, y_fin)
        else:
            _colocar_wmctrl(geom)
        _ultimo_error = None
    except Exception as e:
        # El nombre de la excepción cabe en el tile; el detalle va al log.
        _ultimo_error = type(e).__name__
        print(f"[VENT] {destino}: '{label}' falló: {e}", flush=True)
    return True
