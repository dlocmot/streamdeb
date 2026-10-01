"""Plugin KERNEL: versión en marcha y aviso de reinicio pendiente.

Widget en SIS tecla 20 (bajo el de PV). Sin página propia: es un indicador.

Avisa cuando hay instalado un kernel posterior al que está corriendo, que es
justo lo que no se nota: tras un `apt upgrade` el sistema sigue con el viejo
hasta reiniciar y nada lo recuerda.

La comparación se hace **dentro del mismo sabor** (el sufijo tras la versión:
`x64v3-xanmod1`, `deb13-amd64`…). En esta máquina conviven kernels de Debian y
de XanMod, y mezclarlos daría avisos falsos: tener un `7.1.13+deb13-amd64`
guardado no significa que haya que reiniciar el XanMod en marcha.
"""
import glob
import os
import platform
import re
import threading
import time

from core.widgets import dibujar_panel_metrica

TECLA_SIS = 20   # fila 2, bajo el tile de PV (12)

POLL_S = 300     # los kernels sólo cambian al instalar paquetes

kernel_info = {
    "version": "",      # 7.2.8
    "sabor":   "",      # xanmod / amd64…
    "pendiente": None,  # versión instalada más nueva del mismo sabor, o None
}
_lock = threading.Lock()


def _partir(release):
    """'7.2.8-x64v3-xanmod1' → ('7.2.8', 'x64v3-xanmod1').

    El separador es el primer guion que precede a algo no numérico; así
    '6.12.107+deb13-amd64' da ('6.12.107+deb13', 'amd64') y no se parte por
    los puntos de la versión."""
    m = re.match(r"^([0-9][0-9.]*)[-+]?(.*)$", release)
    if not m:
        return release, ""
    return m.group(1), m.group(2)


def _version_tupla(v):
    """'7.2.8' → (7, 2, 8) para comparar sin sorpresas lexicográficas."""
    return tuple(int(n) for n in re.findall(r"\d+", v))


def _kernels_instalados():
    """Releases presentes en /boot, por el nombre de sus vmlinuz."""
    return [os.path.basename(p)[len("vmlinuz-"):]
            for p in glob.glob("/boot/vmlinuz-*")]


def _refrescar():
    corriendo = platform.release()
    version, sabor = _partir(corriendo)
    pendiente = None
    actual = _version_tupla(version)
    for rel in _kernels_instalados():
        v, s = _partir(rel)
        if s != sabor or rel == corriendo:
            continue
        if _version_tupla(v) > actual:
            # Quedarse con el más nuevo de los pendientes
            if pendiente is None or _version_tupla(v) > _version_tupla(pendiente):
                pendiente = v
    with _lock:
        kernel_info.update(version=version, sabor=sabor, pendiente=pendiente)


def tareas_fondo():
    """Relee /boot cada POLL_S. Un fallo de lectura no tumba el hilo: el tile
    se queda con lo último conocido."""
    while True:
        try:
            _refrescar()
        except Exception as e:
            print(f"[KERNEL] no pude leer /boot: {type(e).__name__}: {e}", flush=True)
        time.sleep(POLL_S)


def _sabor_corto(sabor):
    """'x64v3-xanmod1' → 'xanmod' · 'amd64' → 'amd64'. Cabe en el tile."""
    for marca in ("xanmod", "liquorix", "zen", "rt", "cloud"):
        if marca in sabor:
            return marca
    return sabor.split("-")[-1] or "—"


def widget_para_sistema(deck, tam):
    """Verde con el sabor debajo; ámbar y 'reiniciar' si hay uno más nuevo."""
    with _lock:
        info = dict(kernel_info)
    if not info["version"]:
        _refrescar()
        with _lock:
            info = dict(kernel_info)
    if info["pendiente"]:
        color, sub = "#ffaa00", "reiniciar"
    else:
        color, sub = "#33ff33", _sabor_corto(info["sabor"])
    return {TECLA_SIS: dibujar_panel_metrica(deck, tam, "Kernel",
                                             info["version"], color, sub=sub)}
