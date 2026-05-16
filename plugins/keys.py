"""Plugin KEYS (página 7): atajos de teclado y typed strings."""
from core.helpers import _kp
from core.iconos import buscar_icono as _buscar_icono
from core.keyboard import enviar_combo, KB_DISPONIBLE, Key, keyboard
from core.widgets import dibujar_lanzador_web


# tecla: (label, combo_str, factory_keys_o_string, icono_sistema)
KEYS_PAGINA = {
    8:  ("Captura", "Print",         lambda: _kp(Key.print_screen),               "applets-screenshooter"),
    9:  ("CapSel",  "Shift+Print",   lambda: _kp(Key.shift, Key.print_screen),    "applets-screenshooter"),
    10: ("Bloqueo", "Super+L",       lambda: _kp(Key.cmd, 'l'),                   "system-lock-screen"),
    11: ("AltTab",  "Alt+Tab",       lambda: _kp(Key.alt, Key.tab),               "view-restore"),
    12: ("Cerrar",  "Alt+F4",        lambda: _kp(Key.alt, Key.f4),                "window-close"),
    13: ("Escrit",  "Super+D",       lambda: _kp(Key.cmd, 'd'),                   "user-desktop"),
    16: ("CopiaT",  "Ctrl+Shift+C",  lambda: _kp(Key.ctrl, Key.shift, 'c'),       "edit-copy"),
    17: ("PegaT",   "Ctrl+Shift+V",  lambda: _kp(Key.ctrl, Key.shift, 'v'),       "edit-paste"),
}


def render_pagina_keys(deck, tam, nav_imgs):
    imgs = dict(nav_imgs)
    for tecla, (label, _combo, _keys, icono) in KEYS_PAGINA.items():
        path = _buscar_icono(icono) if icono else None
        imgs[tecla] = dibujar_lanzador_web(deck, tam, label, "#ffcc33", path)
    return imgs


def on_press(tecla):
    if tecla not in KEYS_PAGINA:
        return False
    accion = KEYS_PAGINA[tecla][2]()
    if isinstance(accion, str):
        if KB_DISPONIBLE:
            keyboard.type(accion)
    else:
        enviar_combo(accion)
    return True
