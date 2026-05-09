"""Plugin APP (página 4): launcher de aplicaciones del sistema."""
from core.helpers import _lanzar
from core.widgets import dibujar_lanzador


# tecla: (categoría, app, comando, color, icono_sistema)
APPS_PAGINA = {
    8:  ("Dev",   "Term",    "mate-terminal --working-directory=/home/jfqp",  "#33ccff", "utilities-terminal"),
    9:  ("Dev",   "Arduino", "flatpak run cc.arduino.IDE2",                  "#33ccff", "cc.arduino.IDE2"),
    10: ("Dev",   "GitHub",  "flatpak run io.github.shiftey.Desktop",        "#33ccff", "io.github.shiftey.Desktop"),
    11: ("Web",   "Brave",   "/usr/bin/brave-browser-stable",                "#ff9933", "brave-browser"),
    12: ("Web",   "Firefox", "firejail --netfilter --novideo --nodbus --whitelist=~/Descargas /usr/lib/firefox-esr/firefox-esr --no-remote", "#ff9933", "firefox-esr"),
    16: ("3D",    "Prusa",   "flatpak run com.prusa3d.PrusaSlicer",          "#cc66ff", "com.prusa3d.PrusaSlicer"),
    17: ("Media", "OBS",     "obs",                                          "#ff66cc", "com.obsproject.Studio"),
    18: ("Media", "VLC",     "/usr/bin/vlc",                                 "#ff66cc", "vlc"),
    19: ("Sec",   "Burp",    "/opt/BurpSuiteCommunity/BurpSuiteCommunity",   "#ff3333", "/opt/BurpSuiteCommunity/.install4j/BurpSuiteCommunity.png"),
    20: ("Net",   "Winbox",  "wine /home/jfqp/Downloads/winbox.exe",         "#ffcc33", None),
    24: ("Util",  "AnyDesk", "flatpak run com.anydesk.Anydesk",              "#aaaaaa", "com.anydesk.Anydesk"),
    25: ("Util",  "RustDesk","rustdesk",                                     "#aaaaaa", "rustdesk"),
    29: ("Util",  "SysMon",  "mate-system-monitor",                          "#aaaaaa", "utilities-system-monitor"),
    30: ("Util",  "VBox",    "VirtualBox",                                   "#aaaaaa", "virtualbox"),
    26: ("Util",  "Pluma",   "pluma",                                        "#aaaaaa", "accessories-text-editor"),
    27: ("Util",  "Calc",    "mate-calc",                                    "#aaaaaa", "accessories-calculator"),
}


def render_pagina_apps(deck, tam, nav_imgs):
    """Renderiza la página APP. `nav_imgs` viene del caller (botones_navegacion)."""
    imgs = dict(nav_imgs)
    for tecla, (cat, label, _cmd, color, icono) in APPS_PAGINA.items():
        imgs[tecla] = dibujar_lanzador(deck, tam, cat, color, icono=icono, fallback=label)
    return imgs


def on_press(tecla):
    """Devuelve True si la tecla pertenece a la página APP y se manejó."""
    if tecla in APPS_PAGINA:
        _lanzar(APPS_PAGINA[tecla][2])
        return True
    return False
