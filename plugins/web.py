"""Plugin WEB (página 6): accesos rápidos a URLs vía favicons."""
from core.iconos import favicon_path as _favicon_core
from core.keyboard import tipear_url
from core.widgets import dibujar_lanzador_web


# tecla: (label, sub, url, color) — agrupado por tipo de contenido
# Mail/Msg #ea4335 · AI #ab47bc · Dev #cccccc · Video #ff6f00
# 3D #00bcd4 · Net #66bb6a · News #ffc107 · Empresa #26c6da
WEB_PAGINA = {
    # Fila 1: Mail/Msg · AI · Dev · Video
    8:  ("Gmail",    "google",     "https://mail.google.com",                     "#ea4335"),
    9:  ("Proton",   "mail",       "https://mail.proton.me",                      "#ea4335"),
    10: ("WhatsApp", "web",        "https://web.whatsapp.com",                    "#ea4335"),
    11: ("Claude",   "ai",         "https://claude.ai",                           "#ab47bc"),
    12: ("Gemini",   "google",     "https://gemini.google.com",                   "#ab47bc"),
    13: ("GitHub",   "code",       "https://github.com",                          "#cccccc"),
    14: ("YouTube",  "video",      "https://youtube.com",                         "#ff6f00"),
    # Fila 2: 3D · Net
    16: ("Tinker",   "cad",        "https://tinkercad.com",                       "#00bcd4"),
    17: ("Thingi",   "verse",      "https://thingiverse.com",                     "#00bcd4"),
    18: ("MyIP",     "publico",    "https://whatismyipaddress.com",               "#66bb6a"),
    19: ("Cloudfl.", "dash",       "https://dash.cloudflare.com",                 "#66bb6a"),
    20: ("AWA",      "admin",      "http://192.168.18.10/admin",                  "#66bb6a"),
    # Fila 3: News + Empresa
    24: ("Repúb.",   "lica",       "https://larepublica.pe",                      "#ffc107"),
    25: ("El Com.",  "ercio",      "https://elcomercio.pe",                       "#ffc107"),
    26: ("Gestión",  "diario",     "https://gestion.pe",                          "#ffc107"),
    27: ("Agentica", "Holotech",   "https://agentica.holotech.pe/HOL/inbox/all",  "#26c6da"),
    28: ("Growatt",  "server",     "https://server.growatt.com/login?lang=en",    "#26c6da"),
}

# Overrides de icono. URL http(s) → descarga; ruta absoluta → archivo local.
WEB_ICON_OVERRIDE = {
    "https://github.com":              "https://github.githubassets.com/favicons/favicon-dark.png",
    "https://claude.ai":               "https://api.iconify.design/simple-icons:claude.svg?color=%23d97757",
    "http://192.168.18.10/admin":      "/usr/share/icons/mate/48x48/categories/preferences-system-network.png",
}


def _favicon_path(url):
    return _favicon_core(url, override_dict=WEB_ICON_OVERRIDE)


def render_pagina_web(deck, tam, nav_imgs):
    imgs = dict(nav_imgs)
    for tecla, (label, _sub, url, color) in WEB_PAGINA.items():
        ico = _favicon_path(url)
        imgs[tecla] = dibujar_lanzador_web(deck, tam, label, color, ico)
    return imgs


def on_press(tecla):
    """Tap en página WEB → tipea Ctrl+T + URL + Enter en la app enfocada."""
    if tecla in WEB_PAGINA:
        tipear_url(WEB_PAGINA[tecla][2])
        return True
    return False
