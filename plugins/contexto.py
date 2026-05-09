"""Plugin CTX (página 12): atajos context-aware según la app enfocada.
Polling de xprop cada CTX_POLL_S; mapea WM_CLASS → lista de atajos."""
import subprocess
import time

from core.helpers import _env_sesion
from core.iconos import buscar_icono as _buscar_icono, iconify_png as _iconify_png
from core.keyboard import enviar_combo, KB_DISPONIBLE, Key
from core.widgets import dibujar_lanzador_web, dibujar_panel_metrica, dibujar_btn_icono_nav


CTX_POLL_S = 0.7   # poll xprop más rápido para sentir cambio inmediato

# Estado live: WM_CLASS de la ventana activa.
# `wm_class_actual` es el primer match contra CONTEXTO_APPS, o el instance si no hay match.
# `wm_class_candidatos` es la tupla (instance, class) en lowercase para debugging.
wm_class_actual    = ""
wm_class_candidatos = ()

_nav_cache = {}

# Hook que dashboard_pro setea para que CTX pueda navegar a otras páginas
# cuando un atajo es de tipo "@page:N" en vez de un combo de teclado.
_navigate_fn = lambda page_id: None
def set_navigate_fn(fn):
    global _navigate_fn
    _navigate_fn = fn

# Hook para forzar redibujo cuando cambia la app activa (limpia teclas stale).
_forzar_redraw_fn = lambda: None
def set_forzar_redraw_fn(fn):
    global _forzar_redraw_fn
    _forzar_redraw_fn = fn


# --- Parser de combos: "<Ctrl><Shift>c" → [Key.ctrl, Key.shift, 'c'] ---

_MODIFIERS = {
    "Ctrl":  None,  # se rellena tras el `if KB_DISPONIBLE`
    "Shift": None,
    "Alt":   None,
    "Super": None,
}
_SPECIAL = {}

if KB_DISPONIBLE:
    _MODIFIERS = {
        "Ctrl":  Key.ctrl,
        "Shift": Key.shift,
        "Alt":   Key.alt,
        "Super": Key.cmd,
    }
    _SPECIAL = {
        "Left":      Key.left,    "Right":     Key.right,
        "Up":        Key.up,      "Down":      Key.down,
        "space":     Key.space,   "Tab":       Key.tab,
        "Enter":     Key.enter,   "Escape":    Key.esc,
        "Home":      Key.home,    "End":       Key.end,
        "Backspace": Key.backspace, "Delete":  Key.delete,
        "Print":     Key.print_screen,
    }
    for i in range(1, 13):
        _SPECIAL[f"F{i}"] = getattr(Key, f"f{i}")


def _parse_combo(s):
    """'<Ctrl><Shift>c' → [Key.ctrl, Key.shift, 'c']."""
    keys = []
    rest = s
    while rest.startswith("<"):
        end = rest.index(">")
        mod = rest[1:end]
        if mod in _MODIFIERS and _MODIFIERS[mod] is not None:
            keys.append(_MODIFIERS[mod])
        rest = rest[end+1:]
    if not rest:
        return keys
    if rest in _SPECIAL:
        keys.append(_SPECIAL[rest])
    elif len(rest) == 1:
        keys.append(rest.lower())
    return keys


# --- Mapa app → atajos. Cada entry: (label, combo_str, icono_sistema_o_None) ---
# tecla = 8 + index

CONTEXTO_APPS = {
    "mate-terminal": [
        ("Copy",     "<Ctrl><Shift>c", "edit-copy"),
        ("Paste",    "<Ctrl><Shift>v", "edit-paste"),
        ("Tab+",     "<Ctrl><Shift>t", "tab-new"),
        ("Tab×",     "<Ctrl><Shift>w", "window-close"),
        ("Find",     "<Ctrl><Shift>f", "edit-find"),
        ("Win+",     "<Ctrl><Shift>n", "window-new"),
    ],
    "firefox-esr": [
        ("Atrás",    "<Alt>Left",      "go-previous"),
        ("Adelan.",  "<Alt>Right",     "go-next"),
        ("Reload",   "<Ctrl>r",        "view-refresh"),
        ("Tab+",     "<Ctrl>t",        "tab-new"),
        ("Tab×",     "<Ctrl>w",        "window-close"),
        ("Find",     "<Ctrl>f",        "edit-find"),
        ("DevTools", "<Ctrl><Shift>i", "applications-development"),
        ("Privado",  "<Ctrl><Shift>p", "view-private"),
        ("WEB",      "@page:6",        "web-browser"),
    ],
    "firefox": [   # alias por instance name alternativo
        ("Atrás",    "<Alt>Left",      "go-previous"),
        ("Adelan.",  "<Alt>Right",     "go-next"),
        ("Reload",   "<Ctrl>r",        "view-refresh"),
        ("Tab+",     "<Ctrl>t",        "tab-new"),
        ("Tab×",     "<Ctrl>w",        "window-close"),
        ("Find",     "<Ctrl>f",        "edit-find"),
        ("DevTools", "<Ctrl><Shift>i", "applications-development"),
        ("Privado",  "<Ctrl><Shift>p", "view-private"),
        ("WEB",      "@page:6",        "web-browser"),
    ],
    "navigator": [   # Firefox-esr expone "Navigator" como instance name
        ("Atrás",    "<Alt>Left",      "go-previous"),
        ("Adelan.",  "<Alt>Right",     "go-next"),
        ("Reload",   "<Ctrl>r",        "view-refresh"),
        ("Tab+",     "<Ctrl>t",        "tab-new"),
        ("Tab×",     "<Ctrl>w",        "window-close"),
        ("Find",     "<Ctrl>f",        "edit-find"),
        ("DevTools", "<Ctrl><Shift>i", "applications-development"),
        ("Privado",  "<Ctrl><Shift>p", "view-private"),
        ("WEB",      "@page:6",        "web-browser"),
    ],
    "brave-browser": [
        ("Atrás",    "<Alt>Left",      "go-previous"),
        ("Adelan.",  "<Alt>Right",     "go-next"),
        ("Reload",   "<Ctrl>r",        "view-refresh"),
        ("Tab+",     "<Ctrl>t",        "tab-new"),
        ("Tab×",     "<Ctrl>w",        "window-close"),
        ("Find",     "<Ctrl>f",        "edit-find"),
        ("DevTools", "<Ctrl><Shift>i", "applications-development"),
        ("Incógn.",  "<Ctrl><Shift>n", "view-private"),
        ("WEB",      "@page:6",        "web-browser"),
    ],
}


# --- Polling ---

def _detectar_wm_class():
    """Devuelve tupla (instance, class) lowercased de WM_CLASS, o ()."""
    try:
        env = _env_sesion()
        r = subprocess.run(["xprop", "-root", "_NET_ACTIVE_WINDOW"],
                            capture_output=True, text=True, timeout=1, env=env)
        wid = r.stdout.strip().split()[-1]
        if not wid.startswith("0x"):
            return ()
        r2 = subprocess.run(["xprop", "-id", wid, "WM_CLASS"],
                             capture_output=True, text=True, timeout=1, env=env)
        # WM_CLASS(STRING) = "instance", "Class"
        if "=" not in r2.stdout:
            return ()
        rhs = r2.stdout.split("=", 1)[1].strip()
        # extrae todas las strings entre comillas (en orden)
        vals = []
        i = 0
        while True:
            a = rhs.find('"', i)
            if a < 0: break
            b = rhs.find('"', a + 1)
            if b < 0: break
            vals.append(rhs[a+1:b].lower())
            i = b + 1
        return tuple(vals)
    except Exception:
        pass
    return ()


def _resolver_app(candidatos):
    """Devuelve la primera string de `candidatos` que esté en CONTEXTO_APPS,
    o el primer candidato (para mostrar el nombre aunque no haya atajos)."""
    for c in candidatos:
        if c in CONTEXTO_APPS:
            return c
    return candidatos[0] if candidatos else ""


def tareas_fondo():
    """Poll xprop cada CTX_POLL_S y guarda wm_class_actual + candidatos.
    Si cambia la app, fuerza redraw para limpiar iconos stale del set anterior."""
    global wm_class_actual, wm_class_candidatos
    while True:
        try:
            cands = _detectar_wm_class()
            if cands and cands != wm_class_candidatos:
                wm_class_candidatos = cands
                wm_class_actual     = _resolver_app(cands)
                tag = "✓" if wm_class_actual in CONTEXTO_APPS else "—"
                print(f"[CTX] {tag} {cands} → {wm_class_actual}", flush=True)
                _forzar_redraw_fn()
        except Exception as e:
            print(f"[CTX] poll error: {e}", flush=True)
        time.sleep(CTX_POLL_S)


# --- Render ---

# Mapa wm_class → nombre legible para el nav title (max ~8 chars).
NOMBRE_AMIGABLE = {
    "mate-terminal": "Terminal",
    "navigator":     "Firefox",
    "firefox-esr":   "Firefox",
    "firefox":       "Firefox",
    "brave-browser": "Brave",
}

CTX_COLOR = "#ff7733"  # naranja saturado, distinto del resto de nav buttons


def _nombre_friendly():
    if not wm_class_actual:
        return "CTX"
    n = NOMBRE_AMIGABLE.get(wm_class_actual, wm_class_actual)
    return n[:11]


def _iconos_nav():
    # Icono blanco — contrasta tanto con frame oscuro (inactivo) como con
    # fill naranja del estado activo.
    p = _iconify_png("mdi:application-cog", "ffffff", 256)
    fallbacks = ("/usr/share/icons/hicolor/256x256/apps/mate-panel-window-menu.png",)
    return tuple(x for x in (p, *fallbacks) if x)


def dibujar_boton_ctx_nav(deck, tam, activo=False):
    """Nav CTX. Title dinámico = nombre amigable de la app activa."""
    return dibujar_btn_icono_nav(deck, tam, _iconos_nav(),
                                  CTX_COLOR, _nombre_friendly(),
                                  activo, _nav_cache)


def render_pagina_contexto(deck, tam, nav_imgs):
    imgs = dict(nav_imgs)
    shortcuts = CONTEXTO_APPS.get(wm_class_actual, [])
    if not shortcuts:
        label = wm_class_actual or "—"
        imgs[12] = dibujar_panel_metrica(deck, tam, "App",
                                          label[:11] if len(label) > 11 else label,
                                          "#888888")
        imgs[19] = dibujar_panel_metrica(deck, tam, "CTX", "sin", "#666666")
        imgs[20] = dibujar_panel_metrica(deck, tam, "atajos", "—", "#666666")
        return imgs
    # Atajos desde tecla 8 (sin header — el nombre de la app está en el nav).
    for i, (label, _combo, icono) in enumerate(shortcuts[:24]):
        tecla = 8 + i
        path = _buscar_icono(icono) if icono else None
        imgs[tecla] = dibujar_lanzador_web(deck, tam, label, CTX_COLOR, path)
    return imgs


def on_press(tecla):
    """Tap en CTX: ejecuta combo de teclado, o navega a otra página
    si el `combo_str` tiene prefijo @page:N."""
    shortcuts = CONTEXTO_APPS.get(wm_class_actual, [])
    if tecla < 8 or tecla - 8 >= len(shortcuts):
        return False
    _label, combo_str, _icon = shortcuts[tecla - 8]
    if combo_str.startswith("@page:"):
        try:
            target = int(combo_str.split(":", 1)[1])
            _navigate_fn(target)
            print(f"[CTX] {wm_class_actual} → page {target}", flush=True)
        except Exception as e:
            print(f"[CTX] error nav {combo_str}: {e}", flush=True)
        return True
    keys = _parse_combo(combo_str)
    if keys:
        enviar_combo(keys)
        print(f"[CTX] {wm_class_actual} → {combo_str}", flush=True)
    return True
