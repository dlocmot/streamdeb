import os
import re
import sys
import math
import time
import json
import datetime
import psutil
import subprocess
import threading
import socket
import urllib.request
from io import BytesIO
from collections import deque
from urllib.parse import urlparse
from PIL import Image, ImageDraw, ImageFont, ImageEnhance
from StreamDeck.DeviceManager import DeviceManager
from StreamDeck.ImageHelpers import PILHelper

try:
    from pynput.keyboard import Controller, Key
    keyboard = Controller()
    KB_DISPONIBLE = True
except Exception as e:
    print(f"[WARN] pynput no disponible: {e}")
    KB_DISPONIBLE = False
    Key = None

# --- Core (refactor etapa 1: helpers, iconos, widgets, constantes) ---
from core.config import (
    FONT_PATH, DECK_SERIAL, DUMMY_MODE, PREVIEW_DIR, POLL_HZ,
    CICLO_UPTIME, BRILLO_MIN, BRILLO_MAX, BRILLO_PASO,
    TIEMPO_PASO, TIEMPO_FALLBACK_MIN, TIEMPO_FALLBACK_MAX,
    TIEMPO_DIM_MIN, TIEMPO_DIM_MAX, LONGPRESS_S,
    WALLPAPER_BRILLO, WALLPAPER_SATURACION,
    API_HOST, API_USER, API_IP,
)
from core.helpers import (
    _env_sesion, _run, _lanzar, _kp, _fmt_tiempo, _ip_2_lineas,
    _fit_font, obtener_color_rango,
)
from core.iconos import (
    iconify_png as _iconify_png,
    buscar_icono as _buscar_icono,
    cargar_icono as _cargar_icono,
    favicon_path as _favicon_core,
)
from core.widgets import (
    _nuevo_lienzo, set_con_marco_fn, set_perfil_fn, set_lcars_theme_fn,
    dibujar_panel_metrica, dibujar_panel_info, dibujar_panel_2lineas,
    dibujar_lanzador, dibujar_lanzador_web,
    dibujar_boton_nav, dibujar_boton_fijo, dibujar_boton_x, dibujar_negro,
    dibujar_btn_icono_nav as _dibujar_btn_icono_nav,
)

# --- Estado Global ---
ultimo_toque    = time.time()
modo_dim_activo = False
_despertar      = False
max_visto_down  = 1024.0
max_visto_up    = 1024.0
mute_activo     = False
volumen_actual  = 0
net_info = {"ip_pub": "---", "ip_loc": "---", "ping_gw": 0.0, "ping_dns1": 0.0, "ping_dns2": 0.0, "ping_api": 0.0}
PING_HIST_LEN = 60   # ventana móvil ~5 min a 5s/sample
ping_history = {k: deque(maxlen=PING_HIST_LEN) for k in ("ping_gw", "ping_dns1", "ping_dns2", "ping_api")}
# api_info ahora vive en plugins/awa.py — se asigna como alias tras import abajo.

pagina_actual = 1     # 1=sistema · 2=API · 3=multimedia · 4=apps · 5=configuración
forzar_redraw = False
# Event para despertar el main loop inmediatamente. Cualquier callback
# que muta state visible (press inyectado, _accion_boton, hooks pomo/ctx,
# auto-fallback) lo dispara y el loop redibuja sin esperar el sleep.
_redraw_event = threading.Event()
brillo_actual    = 75
tiempo_fallback  = 300    # s sin interacción en otra pág. → vuelve a SIS
tiempo_dim       = 1800   # s sin interacción → atenúa el deck
perfil_visual    = 1      # 1 = con marcos · 2 = sin marco externo · 3 = LCARS (TNG)
PERFILES_TOTAL   = 3
tema_lcars       = "classic"   # nombre del tema activo (plugins/themes/<name>.py)
banner_enabled   = False  # Si True, la auto-fallback va a página IDLE/BANNER (9) en vez de SIS
monitor_brillo   = 100    # % brillo del monitor externo vía xrandr gamma

# --- Persistencia: carga state guardado y override defaults ---
from core import persistence
_PERSIST_KEYS = ("brillo_actual", "tiempo_fallback", "tiempo_dim",
                  "perfil_visual", "wallpaper_idx", "banner_enabled",
                  "tema_lcars")

def _persist_save():
    """Guarda el snapshot actual de state. Llamar tras cada mutación."""
    persistence.save({
        "brillo_actual":   brillo_actual,
        "tiempo_fallback": tiempo_fallback,
        "tiempo_dim":      tiempo_dim,
        "perfil_visual":   perfil_visual,
        "wallpaper_idx":   wp_get_idx(),
        "banner_enabled":  banner_enabled,
        "monitor_brillo":  monitor_brillo,
        "tema_lcars":      tema_lcars,
    })

def wp_get_idx():
    # Resuelto perezosamente porque `wp` se importa más abajo
    from core import wallpaper as _wp
    return _wp.get_idx()

def _persist_load():
    """Aplica el state guardado a los globals al iniciar."""
    global brillo_actual, tiempo_fallback, tiempo_dim, perfil_visual, banner_enabled, monitor_brillo, tema_lcars
    saved = persistence.load()
    if not saved:
        return
    brillo_actual    = int(saved.get("brillo_actual",   brillo_actual))
    tiempo_fallback  = int(saved.get("tiempo_fallback", tiempo_fallback))
    tiempo_dim       = int(saved.get("tiempo_dim",      tiempo_dim))
    perfil_visual    = int(saved.get("perfil_visual",   perfil_visual))
    banner_enabled   = bool(saved.get("banner_enabled", banner_enabled))
    monitor_brillo   = int(saved.get("monitor_brillo",  monitor_brillo))
    tema_lcars       = str(saved.get("tema_lcars",      tema_lcars))
    # wallpaper_idx se aplica en _abrir_deck (después de wp.set_layout)
    print(f"[STATE] cargado: brillo={brillo_actual} fallback={tiempo_fallback}s "
          f"dim={tiempo_dim}s perfil={perfil_visual} banner={banner_enabled} "
          f"mon={monitor_brillo}%", flush=True)

_persist_load()


# --- Brillo monitor externo (xrandr gamma) ---
from core.config import MONITOR_OUTPUT, MONITOR_BRILLO_MIN, MONITOR_BRILLO_MAX, MONITOR_BRILLO_PASO

def _detectar_monitor_output():
    """Devuelve el primer output activo de xrandr, o '' si falla."""
    if MONITOR_OUTPUT:
        return MONITOR_OUTPUT
    try:
        r = subprocess.run(["xrandr", "--listactivemonitors"],
                            capture_output=True, text=True, timeout=2,
                            env=_env_sesion())
        for line in r.stdout.splitlines():
            parts = line.strip().split()
            # "0: +*HDMI-1 3840/1050x1200/330+0+0  HDMI-1"
            if len(parts) >= 2 and parts[0].rstrip(":").isdigit():
                return parts[-1]
    except Exception as e:
        print(f"[MONITOR] no se pudo detectar output: {e}", flush=True)
    return ""

_monitor_output = _detectar_monitor_output()
if _monitor_output:
    print(f"[MONITOR] output detectado: {_monitor_output}", flush=True)
else:
    print("[MONITOR] sin output al arrancar, se reintentará en uso", flush=True)

def _monitor_aplicar():
    """Aplica monitor_brillo% como xrandr --brightness 0.X al output activo."""
    global _monitor_output
    if not _monitor_output:
        _monitor_output = _detectar_monitor_output()
        if _monitor_output:
            print(f"[MONITOR] output detectado (lazy): {_monitor_output}", flush=True)
        else:
            print("[MONITOR] aún sin output activo (xrandr falla)", flush=True)
            return
    val = max(MONITOR_BRILLO_MIN, min(MONITOR_BRILLO_MAX, monitor_brillo)) / 100.0
    try:
        r = subprocess.run(["xrandr", "--output", _monitor_output, "--brightness", f"{val:.2f}"],
                            timeout=2, env=_env_sesion(),
                            capture_output=True, text=True)
        if r.returncode != 0:
            print(f"[MONITOR] xrandr rc={r.returncode}: {r.stderr.strip()}", flush=True)
    except Exception as e:
        print(f"[MONITOR] error aplicando brillo: {e}", flush=True)

_monitor_aplicar()  # aplicar el persistido al arrancar


# --- Plugins (refactor etapas 2-3) ---
from plugins import apps   as plugin_apps
from plugins import media  as plugin_media
from plugins import web    as plugin_web
from plugins import keys   as plugin_keys
from plugins import vent   as plugin_vent
from plugins import banner as plugin_banner
from plugins import awa      as plugin_awa
from plugins import conf     as plugin_conf
from plugins import sistema  as plugin_sistema
from plugins import pomodoro as plugin_pomo
from plugins import docker   as plugin_docker
from plugins import clima    as plugin_clima
from plugins import contexto as plugin_ctx
from plugins import pedal    as plugin_pedal
from plugins import userconfig as plugin_userconfig
from plugins import growatt  as plugin_growatt
APPS_PAGINA = plugin_apps.APPS_PAGINA
WEB_PAGINA  = plugin_web.WEB_PAGINA
KEYS_PAGINA = plugin_keys.KEYS_PAGINA
VENT_PAGINA = plugin_vent.VENT_PAGINA
WEB_ICON_OVERRIDE = plugin_web.WEB_ICON_OVERRIDE
dibujar_boton_vent_nav = plugin_vent.dibujar_boton_vent_nav
# AWA: api_info y helpers viven en el plugin; alias para retro-compat
api_info = plugin_awa.api_info
api_post_comando = plugin_awa.api_post_comando
DURACION_A_TECLA = plugin_awa.DURACION_A_TECLA
ACCIONES_LABELS  = plugin_awa.ACCIONES_LABELS
clima_info       = plugin_clima.clima_info
docker_info      = plugin_docker.docker_info

# --- Registry: page_id → press handler ---
PAGINAS_PRESS = {
    2:  plugin_awa.on_press,
    3:  plugin_media.on_press,
    4:  plugin_apps.on_press,
    6:  plugin_web.on_press,
    7:  plugin_keys.on_press,
    8:  plugin_vent.on_press,
    10: plugin_docker.on_press_dentro_pagina,
    12: plugin_ctx.on_press,
    17: plugin_growatt.on_press,
}


# --- Hilos de fondo ---

def tareas_press_inject(deck):
    """Inyecta presses simulados desde fuera (p.ej. el GUI configurador).
    Lee `PREVIEW_DIR/press_queue` cada 100 ms: cada línea es un índice de
    tecla (0..31). Por cada uno dispara boton_presionado(deck, k, True/False)
    igual que un toque físico, y luego borra el archivo. Sin file → no-op."""
    path = os.path.join(PREVIEW_DIR, "press_queue")
    while True:
        # 30 ms — round-trip GUI→deck queda en <100 ms incluyendo redraw
        time.sleep(0.03)
        try:
            if not os.path.exists(path):
                continue
            with open(path, "r") as f:
                lines = f.readlines()
            try:
                os.unlink(path)
            except OSError:
                pass
            for line in lines:
                line = line.strip()
                if not line.isdigit():
                    continue
                k = int(line)
                if 0 <= k <= 31:
                    try:
                        boton_presionado(deck, k, True)
                        time.sleep(0.05)
                        boton_presionado(deck, k, False)
                        print(f"[INJECT] key={k}", flush=True)
                    except Exception as e:
                        print(f"[INJECT] error key={k}: {e}", flush=True)
        except Exception as e:
            print(f"[INJECT] read error: {e}", flush=True)


def tareas_userconfig_watch():
    """Poll de los TOML que alimentan apps/web/keys/vent.

    Cuando cambia el mtime de cualquiera (~/.config/streamdeb/config.toml o
    config/default.toml del repo), recarga todos los plugins editables y
    fuerza un redraw. Errores de schema no tumban el thread: se loguean y
    los cambios se ignoran hasta el siguiente edit válido."""
    global forzar_redraw
    paths = [plugin_userconfig.DEFAULT_CONFIG_PATH,
             plugin_userconfig.REPO_DEFAULT_PATH]
    last_mtimes = {p: (p.stat().st_mtime if p.exists() else 0) for p in paths}
    while True:
        time.sleep(2)
        try:
            changed = False
            for p in paths:
                m = p.stat().st_mtime if p.exists() else 0
                if m != last_mtimes[p]:
                    last_mtimes[p] = m
                    changed = True
            if not changed:
                continue
            cfg = plugin_userconfig.load()
            plugin_apps.reload(cfg)
            plugin_web.reload(cfg)
            plugin_keys.reload(cfg)
            plugin_vent.reload(cfg)
            print("[USERCONFIG] hot-reload OK", flush=True)
            forzar_redraw = True
        except plugin_userconfig.ConfigError as e:
            print(f"[USERCONFIG] schema error: {e} (cambios descartados)",
                  flush=True)
        except Exception as e:
            print(f"[USERCONFIG] watch error: {type(e).__name__}: {e}",
                  flush=True)


def tareas_red_fondo():
    global mute_activo, volumen_actual
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            net_info["ip_loc"] = s.getsockname()[0]
            s.close()
            req = urllib.request.Request("https://api.ipify.org")
            with urllib.request.urlopen(req, timeout=3) as resp:
                net_info["ip_pub"] = resp.read().decode('utf-8')
        except: pass

        for clave, ip in [("ping_gw", "192.168.18.1"), ("ping_dns1", "1.1.1.1"), ("ping_dns2", "8.8.8.8"), ("ping_api", API_IP)]:
            try:
                res = subprocess.run(["ping", "-c", "1", "-W", "1", ip], capture_output=True, text=True)
                net_info[clave] = float(res.stdout.split("time=")[1].split(" ")[0]) if "time=" in res.stdout else -1.0
            except: net_info[clave] = -1.0
            if net_info[clave] > 0:
                ping_history[clave].append(net_info[clave])

        try:
            res = subprocess.run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"],
                                 capture_output=True, text=True, timeout=1, env=_env_sesion())
            mute_activo = "yes" in res.stdout.lower()
        except: pass

        try:
            res = subprocess.run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
                                 capture_output=True, text=True, timeout=1, env=_env_sesion())
            m = re.search(r"(\d+)%", res.stdout)
            if m: volumen_actual = int(m.group(1))
        except: pass

        time.sleep(5)


# --- Dibujo (los primitivos vienen de core.widgets; aquí solo el hook de marco) ---

def _con_marco():
    """¿Se dibuja el marco externo del botón? Sólo perfil 1.
    Perfil 2 = limpio (sin marco). Perfil 3 = LCARS (chrome propio)."""
    return perfil_visual == 1

def _perfil():
    return perfil_visual

def _lcars_theme():
    """Nombre del tema LCARS activo (persistido en `tema_lcars`)."""
    return tema_lcars

# Wirea hooks que core.widgets usa para decidir estilo
set_con_marco_fn(_con_marco)
set_perfil_fn(_perfil)
set_lcars_theme_fn(_lcars_theme)

# Carga todos los plugins de tema y arranca el loop de animación.
from plugins import themes as _theme_registry
_theme_registry.autoload()
_theme_registry.set_active_fn(_lcars_theme)
def _force_redraw():
    global forzar_redraw
    forzar_redraw = True
_theme_registry.start_animation_thread(_force_redraw, fps=8)

# --- Wallpaper + render core: ahora en core/wallpaper.py + core/render.py ---
from core import wallpaper as wp
from core import render as render_core
# Aliases para que el código existente no cambie de nombre
DECK_COLS, DECK_ROWS = 8, 4   # default; sobreescrito en _abrir_deck → wp.set_layout
_finalizar = render_core.finalizar
_push_key  = render_core.push_key
_invalidar_render_cache = render_core.invalidar
def wallpaper_total(): return wp.total()

def _ping_pct_relativo(clave, ms):
    """Devuelve (pct, color). Baseline 30% verde cuando ms ≤ promedio observado;
    crece hacia 100% rojo a medida que ms se acerca al máximo histórico."""
    if ms <= 0:
        return 0, "#666666"
    hist = ping_history.get(clave)
    if not hist or len(hist) < 3:
        return 30, "#33ff33"
    avg = sum(hist) / len(hist)
    pmax = max(hist)
    if pmax - avg < 1.0:
        return 30, "#33ff33"
    if ms <= avg:
        pct = 30.0
    else:
        pct = 30.0 + ((ms - avg) / (pmax - avg)) * 70.0
        pct = max(0.0, min(100.0, pct))
    if pct <= 40:
        color = "#33ff33"
    elif pct <= 70:
        color = "#ffaa00"
    else:
        color = "#ff3333"
    return pct, color


_gear_cache = {}
_app_cache = {}
_web_cache = {}
_keys_cache = {}
_vent_cache = {}
GEAR_ICON_PATHS = (
    "/usr/share/icons/gnome/256x256/categories/preferences-system.png",
    "/usr/share/icons/mate/256x256/categories/preferences-system.png",
    "/usr/share/icons/gnome/256x256/categories/applications-system.png",
)
APP_NAV_ICON_PATHS = (
    "/usr/share/icons/gnome/256x256/places/start-here.png",
)
WEB_NAV_ICON_PATHS = (
    "/usr/share/icons/gnome/256x256/apps/web-browser.png",
    "/usr/share/icons/gnome/256x256/categories/applications-internet.png",
)
KEYS_NAV_ICON_PATHS = (
    "/usr/share/icons/gnome/256x256/apps/preferences-desktop-keyboard-shortcuts.png",
    "/usr/share/icons/gnome/256x256/apps/preferences-desktop-keyboard.png",
)
def dibujar_boton_gear(deck, tamaño, activo=False):
    return _dibujar_btn_icono_nav(deck, tamaño, GEAR_ICON_PATHS, "#aaaaaa", "CONF", activo, _gear_cache)

def dibujar_boton_app_nav(deck, tamaño, activo=False):
    return _dibujar_btn_icono_nav(deck, tamaño, APP_NAV_ICON_PATHS, "#33ff66", "APP", activo, _app_cache)

def dibujar_boton_web_nav(deck, tamaño, activo=False):
    return _dibujar_btn_icono_nav(deck, tamaño, WEB_NAV_ICON_PATHS, "#33ff99", "WEB", activo, _web_cache)

def dibujar_boton_keys_nav(deck, tamaño, activo=False):
    return _dibujar_btn_icono_nav(deck, tamaño, KEYS_NAV_ICON_PATHS, "#ffcc33", "KEYS", activo, _keys_cache)



# --- Callback ---

def _accion_boton(deck, tecla):
    global pagina_actual, forzar_redraw, brillo_actual, modo_dim_activo
    global tiempo_fallback, tiempo_dim, perfil_visual, banner_enabled, monitor_brillo

    # En banner idle (9), cualquier tecla no-nav despierta a SIS.
    # Las nav (0-7) caen al routing normal de abajo.
    if pagina_actual == 9 and tecla not in (0, 1, 2, 3, 4, 6, 7):
        pagina_actual = 1
        forzar_redraw = True
        return

    # Navegación entre páginas (siempre activa)
    if tecla == 0:
        if pagina_actual != 1:
            pagina_actual = 1
            forzar_redraw = True
        return
    if tecla == 1:
        if pagina_actual != 2:
            pagina_actual = 2
            forzar_redraw = True
        return
    if tecla == 2:
        if pagina_actual != 3:
            pagina_actual = 3
            forzar_redraw = True
        return
    if tecla == 3:
        if pagina_actual != 4:
            pagina_actual = 4
            forzar_redraw = True
        return
    if tecla == 4:
        if pagina_actual != 12:
            pagina_actual = 12
            forzar_redraw = True
        return
    if tecla == 6:
        if pagina_actual != 7:
            pagina_actual = 7
            forzar_redraw = True
        return
    if tecla == 7:
        if pagina_actual != 8:
            pagina_actual = 8
            forzar_redraw = True
        return

    if pagina_actual == 1:
        # Tecla 26 SIS: abre página DOCKER (id 10)
        if tecla == 26:
            if pagina_actual != 10:
                pagina_actual = 10
                forzar_redraw = True
        # Tecla 19 SIS (Clima consolidado): abre página CLIMA (id 11)
        elif tecla == 19:
            if pagina_actual != 11:
                pagina_actual = 11
                forzar_redraw = True
        # Tecla 9 SIS (Cores consolidados): abre página CORES detalle (id 13)
        elif tecla == 9:
            if pagina_actual != 13:
                pagina_actual = 13
                forzar_redraw = True
        # Tecla 25 SIS (Pings consolidados): abre página PINGS detalle (id 14)
        elif tecla == 25:
            if pagina_actual != 14:
                pagina_actual = 14
                forzar_redraw = True
        # Tecla 24 SIS (Net consolidado): abre página NET detalle (id 15)
        elif tecla == 24:
            if pagina_actual != 15:
                pagina_actual = 15
                forzar_redraw = True
        # Tecla 10 SIS (Temp cores): abre página TEMPS detalle (id 16)
        elif tecla == 10:
            if pagina_actual != 16:
                pagina_actual = 16
                forzar_redraw = True
        # Tecla 11 SIS (PV widget): abre página GROWATT (id 17)
        elif tecla == 11:
            if pagina_actual != 17:
                pagina_actual = 17
                forzar_redraw = True
        return

    # Dispatch press → plugin handlers (registry simple)
    h = PAGINAS_PRESS.get(pagina_actual)
    if h is not None:
        h(tecla)
        return

    if pagina_actual == 5:
        # Col 0 — Brillo (+ arriba, − abajo)
        if tecla == 8:
            brillo_actual = min(BRILLO_MAX, brillo_actual + BRILLO_PASO)
            try: deck.set_brightness(brillo_actual)
            except: pass
            print(f"[CONFIG] brillo_actual={brillo_actual}", flush=True)
            forzar_redraw = True; _persist_save()
        elif tecla == 24:
            brillo_actual = max(BRILLO_MIN, brillo_actual - BRILLO_PASO)
            try: deck.set_brightness(brillo_actual)
            except: pass
            print(f"[CONFIG] brillo_actual={brillo_actual}", flush=True)
            forzar_redraw = True; _persist_save()
        # Col 1 — Fallback a SIS (paso 1 min)
        elif tecla == 9:
            tiempo_fallback = min(TIEMPO_FALLBACK_MAX, tiempo_fallback + TIEMPO_PASO)
            print(f"[CONFIG] tiempo_fallback={tiempo_fallback}s", flush=True)
            forzar_redraw = True; _persist_save()
        elif tecla == 25:
            tiempo_fallback = max(TIEMPO_FALLBACK_MIN, tiempo_fallback - TIEMPO_PASO)
            print(f"[CONFIG] tiempo_fallback={tiempo_fallback}s", flush=True)
            forzar_redraw = True; _persist_save()
        # Col 2 — Dim por inactividad (paso 1 min)
        elif tecla == 10:
            tiempo_dim = min(TIEMPO_DIM_MAX, tiempo_dim + TIEMPO_PASO)
            print(f"[CONFIG] tiempo_dim={tiempo_dim}s", flush=True)
            forzar_redraw = True; _persist_save()
        elif tecla == 26:
            tiempo_dim = max(TIEMPO_DIM_MIN, tiempo_dim - TIEMPO_PASO)
            print(f"[CONFIG] tiempo_dim={tiempo_dim}s", flush=True)
            forzar_redraw = True; _persist_save()
        # Col 3 — Brillo monitor (xrandr gamma)
        elif tecla == 11:
            monitor_brillo = min(MONITOR_BRILLO_MAX, monitor_brillo + MONITOR_BRILLO_PASO)
            _monitor_aplicar()
            print(f"[CONFIG] monitor_brillo={monitor_brillo}%", flush=True)
            forzar_redraw = True; _persist_save()
        elif tecla == 27:
            monitor_brillo = max(MONITOR_BRILLO_MIN, monitor_brillo - MONITOR_BRILLO_PASO)
            _monitor_aplicar()
            print(f"[CONFIG] monitor_brillo={monitor_brillo}%", flush=True)
            forzar_redraw = True; _persist_save()
        # Wallpaper: la rotación / apagado se maneja en boton_presionado
        # vía detección de press corto vs long-press (ver _wallpaper_evento).
        # Banner ON/OFF
        elif tecla == 13:
            banner_enabled = not banner_enabled
            print(f"[CONFIG] banner_enabled={banner_enabled}", flush=True)
            forzar_redraw = True; _persist_save()
        # Col 6 — Perfil visual (rota 1 → 2 → … → 1)
        # Col 6 — Perfil V: rotación unificada 1 → 2 → 3·<tema1> → 3·<tema2>
        # → ... → wrap a 1. En perfil 3, cada tap avanza al siguiente tema
        # del registry; al llegar al último, vuelve a perfil 1.
        elif tecla == 14:
            global tema_lcars
            theme_names = _theme_registry.names()
            if perfil_visual != 3:
                # 1 → 2 → 3 (entrando en LCARS con primer tema)
                if perfil_visual + 1 < 3:
                    perfil_visual += 1
                else:
                    perfil_visual = 3
                    if theme_names:
                        tema_lcars = theme_names[0]
            else:
                # En perfil 3: avanza tema; si era el último, sale a perfil 1.
                if theme_names:
                    try: i = theme_names.index(tema_lcars)
                    except ValueError: i = -1
                    if i + 1 >= len(theme_names):
                        perfil_visual = 1
                    else:
                        tema_lcars = theme_names[i + 1]
                else:
                    perfil_visual = 1
            _gear_cache.clear(); _app_cache.clear()
            _web_cache.clear(); _keys_cache.clear(); _vent_cache.clear()
            _invalidar_render_cache()
            print(f"[CONFIG] perfil_visual={perfil_visual} tema_lcars={tema_lcars}", flush=True)
            forzar_redraw = True; _persist_save()
        # Perfil Kiosko: pasa este deck (B) a AWA. Lanza awa_kiosk pineado
        # al mismo serial como servicio transient, luego para streamdeb.
        elif tecla == 15:
            serial_b = DECK_SERIAL or ""
            print(f"[CONFIG] deck {serial_b} → AWA kiosko", flush=True)
            unit = f"streamdeb-kiosk-b-{int(time.time())}"
            cmd_arranque = (
                f"sleep 1.5 && "
                f"STREAMDEB_DECK_SERIAL={serial_b} STREAMDEB_FORCE_DARK=1 "
                f"/home/jfqp/Documents/GitHub/streamdeb/.venv/bin/python "
                f"/home/jfqp/Documents/GitHub/streamdeb/awa_kiosk.py"
            )
            subprocess.Popen(
                ["systemd-run", "--user", "--no-block",
                 f"--unit={unit}",
                 "--description=AWA kiosko en deck B",
                 "--setenv=DISPLAY=:0",
                 "--setenv=STREAMDEB_API_HOST=http://192.168.18.10",
                 "--setenv=STREAMDEB_API_USER=Dinamo",
                 "bash", "-lc", cmd_arranque],
                start_new_session=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            subprocess.Popen(
                ["systemctl", "--user", "stop", "streamdeb.service"],
                start_new_session=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        # X de apagado en config
        elif tecla == 31:
            try:
                deck.set_brightness(0)
                modo_dim_activo = True
            except: pass
        return

_sis_press_t       = None  # timestamp del press en tecla SIS (0)
_wallpaper_press_t = None  # timestamp del press en tecla wallpaper (CONF/12)
_pomo_press_t      = None  # timestamp del press en tecla Pomodoro (SIS/15)

def _wallpaper_evento(held):
    """Procesa la liberación de la tecla wallpaper. held = segundos pulsada."""
    global forzar_redraw
    if held >= LONGPRESS_S:
        wp.set_idx(0)
        print(f"[WALLPAPER] long-press {held:.1f}s → OFF", flush=True)
    else:
        total = wp.total()
        if total <= 0:
            print("[WALLPAPER] sin imágenes disponibles", flush=True)
            return
        # 0→1, 1→2, …, total→1 (no vuelve a OFF por pulsación corta)
        wp.set_idx((wp.get_idx() % total) + 1)
        print(f"[WALLPAPER] idx={wp.get_idx()}/{total}", flush=True)
    _invalidar_render_cache()
    forzar_redraw = True
    _persist_save()

def _sis_evento(held):
    """Tecla SIS (0): corta = página SIS, larga ≥2s = página CONF."""
    global pagina_actual, forzar_redraw
    destino = 5 if held >= LONGPRESS_S else 1
    etiqueta = "long→CONF" if destino == 5 else "short→SIS"
    if pagina_actual != destino:
        pagina_actual = destino
        forzar_redraw = True
    print(f"[NAV] SIS {etiqueta} ({held:.2f}s)", flush=True)

def boton_presionado(deck, tecla, estado):
    global ultimo_toque, _despertar, _wallpaper_press_t, _sis_press_t, _pomo_press_t
    ultimo_toque = time.time()

    # Tecla SIS (0): corta = SIS, larga ≥2s = CONF (en cualquier página)
    if tecla == 0 and not modo_dim_activo:
        if estado:
            _sis_press_t = time.time()
        else:
            t0 = _sis_press_t
            _sis_press_t = None
            if t0 is not None:
                threading.Thread(target=_sis_evento,
                                 args=(time.time() - t0,), daemon=True).start()
        return

    # Tecla Pomodoro (SIS/27): corta = avanza estado, larga ≥2s = reset
    if pagina_actual == 1 and tecla == 27 and not modo_dim_activo:
        if estado:
            _pomo_press_t = time.time()
        else:
            t0 = _pomo_press_t
            _pomo_press_t = None
            if t0 is not None:
                threading.Thread(target=plugin_pomo.evento,
                                 args=(time.time() - t0,), daemon=True).start()
        return

    # Tecla wallpaper en CONF: corta = siguiente, larga ≥2s = OFF
    if pagina_actual == 5 and tecla == 12 and not modo_dim_activo:
        if estado:
            _wallpaper_press_t = time.time()
        else:
            t0 = _wallpaper_press_t
            _wallpaper_press_t = None
            if t0 is not None:
                threading.Thread(target=_wallpaper_evento,
                                 args=(time.time() - t0,), daemon=True).start()
        return

    if not estado:
        return
    if modo_dim_activo:
        _despertar = True
        return
    threading.Thread(target=_accion_boton, args=(deck, tecla), daemon=True).start()
    _redraw_event.set()  # despierta el main loop sin esperar el sleep


# --- Inicialización ---

class DummyDeck:
    """Mock de StreamDeck XL para iteración visual sin hardware.
    Decodifica los bytes JPEG de cada tecla y los compone en un mosaico
    PNG (8x4) en PREVIEW_DIR/deck.png. Activado con `--dummy`."""
    KEY_COUNT = 32
    KEY_COLS  = 8
    KEY_ROWS  = 4
    KEY_W, KEY_H = 96, 96

    def __init__(self):
        self._keys = {}
        self._dirty = False
        self._depth = 0
        self._serial = "DUMMY-" + str(os.getpid())
        os.makedirs(PREVIEW_DIR, exist_ok=True)
        print(f"[DUMMY] preview dir: {PREVIEW_DIR}", flush=True)

    # API mínima usada por dashboard_pro
    def open(self): pass
    def close(self): pass
    def reset(self): self._keys.clear(); self._save_mosaic()
    def is_open(self): return True
    def is_visual(self): return True
    def is_touch(self): return False
    def connected(self): return True
    def key_count(self): return self.KEY_COUNT
    def key_image_format(self):
        return {"size": (self.KEY_W, self.KEY_H), "format": "JPEG",
                "rotation": 0, "flip": (False, False)}
    def key_layout(self): return (self.KEY_ROWS, self.KEY_COLS)
    def get_serial_number(self): return self._serial
    def get_firmware_version(self): return "DUMMY 1.0"
    def set_brightness(self, n): pass
    def set_poll_frequency(self, hz): pass
    def set_key_callback(self, cb): pass
    def set_key_image(self, k, native_bytes):
        self._keys[k] = native_bytes
        if self._depth == 0:
            self._save_mosaic()
        else:
            self._dirty = True

    # `with deck:` agrupa writes; salvamos el mosaico una sola vez por bloque
    def __enter__(self):
        self._depth += 1
        return self
    def __exit__(self, *a):
        self._depth = max(0, self._depth - 1)
        if self._depth == 0 and self._dirty:
            self._save_mosaic()
            self._dirty = False

    def _save_mosaic(self):
        try:
            mosaic = Image.new("RGB",
                               (self.KEY_W * self.KEY_COLS, self.KEY_H * self.KEY_ROWS),
                               "black")
            for k, b in self._keys.items():
                if not b:
                    continue
                try:
                    img = Image.open(BytesIO(b)).convert("RGB")
                    if img.size != (self.KEY_W, self.KEY_H):
                        img = img.resize((self.KEY_W, self.KEY_H), Image.LANCZOS)
                    row, col = k // self.KEY_COLS, k % self.KEY_COLS
                    mosaic.paste(img, (col * self.KEY_W, row * self.KEY_H))
                except Exception:
                    pass
            mosaic.save(os.path.join(PREVIEW_DIR, "deck.png"))
        except Exception as e:
            print(f"[DUMMY] mosaic error: {e}", flush=True)


def _abrir_deck():
    if DUMMY_MODE:
        d = DummyDeck()
        d.set_brightness(brillo_actual)
        return d
    try:
        decks = DeviceManager().enumerate()
        if not decks:
            return None
        d = None
        for cand in decks:
            try:
                cand.open()
            except Exception as e:
                print(f"[WARN] open: {e}", flush=True)
                continue
            try:
                serial = cand.get_serial_number()
            except Exception:
                serial = ""
            if DECK_SERIAL and serial != DECK_SERIAL:
                print(f"[SKIP] serial={serial} (busco {DECK_SERIAL})", flush=True)
                cand.close()
                continue
            d = cand
            print(f"[DECK] abierto serial={serial}", flush=True)
            break
        if d is None:
            return None
        time.sleep(0.3)
        d.reset()
        d.set_brightness(brillo_actual)
        try:
            d.set_poll_frequency(POLL_HZ)
        except Exception as e:
            print(f"[WARN] set_poll_frequency({POLL_HZ}): {e}", flush=True)
        # Introspección: usar layout del deck en vez de hardcode 8x4
        try:
            global DECK_COLS, DECK_ROWS
            rows, cols = d.key_layout()
            if (rows, cols) != (DECK_ROWS, DECK_COLS):
                _invalidar_render_cache()
            DECK_ROWS, DECK_COLS = rows, cols
            wp.set_layout(cols, rows)
            # Chrome LCARS global usa el layout real del deck.
            render_core.set_lcars_config(lambda: perfil_visual == 3, cols, rows)
            # Aplicar wallpaper_idx persistido (ahora que el layout está listo)
            saved = persistence.load()
            wp.set_idx(int(saved.get("wallpaper_idx", 0)))
            visual = "visual" if d.is_visual() else "no-visual"
            print(f"[DECK] layout={cols}x{rows} {visual} firmware={d.get_firmware_version()} poll={POLL_HZ}Hz", flush=True)
        except Exception as e:
            print(f"[WARN] introspección: {e}", flush=True)
        return d
    except Exception as e:
        print(f"[WARN] _abrir_deck: {e}", flush=True)
        return None


# --- Renderizado por página ---

def botones_navegacion(deck, tam):
    ahora = datetime.datetime.now()
    fecha = ahora.strftime("%d/%m/%y")
    hora  = ahora.strftime("%H:%M")
    if api_info["online"]:
        estado_awa = api_info["estado"].upper()
        if api_info["estado"] == "Abierta" and api_info.get("segundos", 0) > 0:
            cuenta_awa = _fmt_tiempo(api_info["segundos"])
        else:
            cuenta_awa = str(api_info["cuenta"])
    else:
        estado_awa = "OFFLINE"
        cuenta_awa = "---"
    media_vol = f"{volumen_actual}%"

    p1 = dibujar_boton_nav(deck, tam, "SIS",   fecha, hora,
                           color="#ffaa00", activo=(pagina_actual == 1))
    p2 = dibujar_boton_nav(deck, tam, "AWA",   estado_awa, cuenta_awa,
                           color="#00ddff", activo=(pagina_actual == 2))
    p3 = dibujar_boton_nav(deck, tam, "MEDIA", media_vol,
                           color="#cc66ff", activo=(pagina_actual == 3))
    p4 = dibujar_boton_app_nav(deck, tam, activo=(pagina_actual == 4))
    # p_web ya no está en nav row — WEB se entra desde CTX cuando navegás un browser.
    p_keys = dibujar_boton_keys_nav(deck, tam, activo=(pagina_actual == 7))
    p_vent = dibujar_boton_vent_nav(deck, tam, activo=(pagina_actual == 8))
    p_ctx  = plugin_ctx.dibujar_boton_ctx_nav(deck, tam, activo=(pagina_actual == 12))
    # CONF se entra con long-press ≥2s en SIS (no tiene nav button).
    # WEB se entra desde CTX cuando hay un browser activo (Firefox/Brave).
    # GROWATT (page 17) se entra desde SIS tecla 11 (widget_para_sistema).
    return {0: p1, 1: p2, 2: p3, 3: p4, 4: p_ctx, 6: p_keys, 7: p_vent}

# Pomodoro / clima viven en plugins/. El plugin pomo necesita un hook
# para forzar redibujo tras cambio de estado:
def _pomo_forzar_redraw():
    global forzar_redraw
    forzar_redraw = True
plugin_pomo.set_forzar_redraw_fn(_pomo_forzar_redraw)

# CTX puede navegar a otras páginas (ej. WEB desde Firefox)
def _ctx_navigate(page_id):
    global pagina_actual, forzar_redraw
    if pagina_actual != page_id:
        pagina_actual = page_id
        forzar_redraw = True
plugin_ctx.set_navigate_fn(_ctx_navigate)

# CTX fuerza redraw cuando cambia la app activa (limpia teclas stale).
def _ctx_forzar_redraw():
    global forzar_redraw
    forzar_redraw = True
plugin_ctx.set_forzar_redraw_fn(_ctx_forzar_redraw)

# PEDAL: reusa el mismo patrón — al pulsar/soltar un pedal queremos
# refrescar los 6 tiles de SIS para mostrar el flash visual.
def _pedal_forzar_redraw():
    global forzar_redraw
    forzar_redraw = True
plugin_pedal.set_forzar_redraw_fn(_pedal_forzar_redraw)

# Pedal bindings context-aware: cada app activa puede tener su mapping
# de los 5 slots (tap_izq/tap_der/hold_izq/hold_der/double_cen). Plugin
# registry en plugins/pedal_apps/.
from plugins import pedal_apps as _pedal_apps
_pedal_apps.autoload()
_pedal_apps.add_listener(_pedal_forzar_redraw)
_pedal_apps.sync("default")   # estado inicial hasta que CTX detecte algo

def render_pagina_sistema(deck, tam, last_net, cur_net):
    widgets = {}
    widgets.update(plugin_pomo.widget_para_sistema(deck, tam))
    widgets.update(plugin_clima.widget_para_sistema(deck, tam))
    widgets.update(plugin_docker.widget_para_sistema(deck, tam))
    widgets.update(plugin_pedal.widget_para_sistema(deck, tam))
    widgets.update(plugin_growatt.widget_para_sistema(deck, tam))
    return plugin_sistema.render_pagina_sistema(
        deck, tam, botones_navegacion(deck, tam),
        last_net, cur_net, net_info, _ping_pct_relativo,
        widgets_extras=widgets,
    )

def render_pagina_api(deck, tam):
    return plugin_awa.render_pagina_api(
        deck, tam, botones_navegacion(deck, tam), net_info, _ping_pct_relativo,
    )

def render_pagina_media(deck, tam):
    return plugin_media.render_pagina_media(deck, tam, botones_navegacion(deck, tam), mute_activo)

def render_pagina_apps(deck, tam):
    return plugin_apps.render_pagina_apps(deck, tam, botones_navegacion(deck, tam))

def render_pagina_web(deck, tam):
    return plugin_web.render_pagina_web(deck, tam, botones_navegacion(deck, tam))

def render_pagina_keys(deck, tam):
    return plugin_keys.render_pagina_keys(deck, tam, botones_navegacion(deck, tam))

def render_pagina_clima(deck, tam):
    return plugin_clima.render_pagina_clima(deck, tam, botones_navegacion(deck, tam))

def render_pagina_docker(deck, tam):
    return plugin_docker.render_pagina_docker(deck, tam, botones_navegacion(deck, tam))

def render_pagina_cores(deck, tam):
    return plugin_sistema.render_pagina_cores(deck, tam, botones_navegacion(deck, tam))

def render_pagina_pings(deck, tam):
    return plugin_sistema.render_pagina_pings(
        deck, tam, botones_navegacion(deck, tam),
        net_info, ping_history, _ping_pct_relativo,
    )

def render_pagina_net(deck, tam):
    return plugin_sistema.render_pagina_net(deck, tam, botones_navegacion(deck, tam))

def render_pagina_temps(deck, tam):
    return plugin_sistema.render_pagina_temps(deck, tam, botones_navegacion(deck, tam))


def render_pagina_banner(deck, tam):
    return plugin_banner.render_pagina_banner(deck, tam, DECK_COLS, DECK_ROWS, api_info)

def render_pagina_contexto(deck, tam):
    return plugin_ctx.render_pagina_contexto(deck, tam, botones_navegacion(deck, tam))

def render_pagina_vent(deck, tam):
    return plugin_vent.render_pagina_vent(deck, tam, botones_navegacion(deck, tam))

def render_pagina_growatt(deck, tam):
    return plugin_growatt.render_pagina_growatt(deck, tam, botones_navegacion(deck, tam))

def render_pagina_config(deck, tam):
    return plugin_conf.render_pagina_config(
        deck, tam, botones_navegacion(deck, tam),
        brillo_actual=brillo_actual, tiempo_fallback=tiempo_fallback,
        tiempo_dim=tiempo_dim, perfil_visual=perfil_visual,
        wallpaper_idx=wp.get_idx(), wallpaper_total=wp.total(),
        banner_enabled=banner_enabled, monitor_brillo=monitor_brillo,
        tema_lcars=tema_lcars,
    )


# --- Registry: page_id → render(deck, tam). SIS (1) usa wrapper aparte por args extra. ---
PAGINAS_RENDER = {
    2:  render_pagina_api,
    3:  render_pagina_media,
    4:  render_pagina_apps,
    5:  render_pagina_config,
    6:  render_pagina_web,
    7:  render_pagina_keys,
    8:  render_pagina_vent,
    9:  render_pagina_banner,
    10: render_pagina_docker,
    11: render_pagina_clima,
    12: render_pagina_contexto,
    13: render_pagina_cores,
    14: render_pagina_pings,
    15: render_pagina_net,
    16: render_pagina_temps,
    17: render_pagina_growatt,
}


# --- Loop principal ---

def iniciar_dashboard():
    global modo_dim_activo, _despertar, forzar_redraw, pagina_actual

    deck = None
    while deck is None:
        deck = _abrir_deck()
        if deck is None:
            print("[WAIT] buscando Stream Deck...", flush=True)
            time.sleep(2)
    print("[OK] Stream Deck listo", flush=True)
    # Publica info del deck a /tmp/streamdeb-preview/deck.json — la GUI lo
    # lee al arrancar para saltar la enumeración (que falla con HID busy).
    try:
        import json as _json
        os.makedirs(PREVIEW_DIR, exist_ok=True)
        with open(os.path.join(PREVIEW_DIR, "deck.json"), "w") as f:
            _json.dump({
                "type": deck.deck_type(),
                "serial": deck.get_serial_number(),
                "firmware": deck.get_firmware_version(),
            }, f)
    except Exception as e:
        print(f"[DECK-INFO] dump error: {e}", flush=True)

    tam = deck.key_image_format()['size']
    deck.set_key_callback(boton_presionado)
    threading.Thread(target=tareas_red_fondo, daemon=True).start()
    threading.Thread(target=plugin_awa.tareas_api_fondo, daemon=True).start()
    threading.Thread(target=plugin_docker.tareas_fondo, daemon=True).start()
    threading.Thread(target=plugin_clima.tareas_fondo,  daemon=True).start()
    threading.Thread(target=plugin_pomo.tareas_fondo,   daemon=True).start()
    threading.Thread(target=plugin_ctx.tareas_fondo,    daemon=True).start()
    threading.Thread(target=plugin_sistema.tareas_fondo, daemon=True).start()
    threading.Thread(target=plugin_pedal.tareas_fondo,   daemon=True).start()
    threading.Thread(target=plugin_growatt.tareas_fondo, daemon=True).start()
    threading.Thread(target=tareas_userconfig_watch,     daemon=True).start()
    threading.Thread(target=tareas_press_inject, args=(deck,), daemon=True).start()
    last_net = psutil.net_io_counters()
    pagina_anterior = None

    try:
        # Hilo background: refresh cada 5s del listado de wallpapers (auto-detect
        # de archivos nuevos en ~/.cache/streamdeb/wallpapers/ sin restart).
        def _wp_refresh_loop():
            while True:
                try: wp.lista_paths()
                except Exception: pass
                time.sleep(5)
        threading.Thread(target=_wp_refresh_loop, daemon=True).start()

        while True:
            ahora = time.time()

            if _despertar:
                try:
                    deck.set_brightness(brillo_actual)
                    modo_dim_activo = False
                except Exception: pass
                _despertar = False
                # Notifica a plugins con polling que el deck volvió activo
                try: plugin_growatt.set_deck_dimmed(False)
                except Exception: pass

            # Fallback por inactividad: a banner si activado, si no a SIS.
            # Excluyo WEB(6) y KEYS(7) — uso prolongado — y banner (9) consigo mismo.
            if (pagina_actual not in (6, 7, 9, 17)
                    and (ahora - ultimo_toque) > tiempo_fallback):
                pagina_actual = 9 if banner_enabled else 1
                forzar_redraw = True

            # Auto-dim por inactividad
            if not modo_dim_activo and (ahora - ultimo_toque) > tiempo_dim:
                try: deck.set_brightness(0)
                except: pass
                modo_dim_activo = True
                print("[DIM] entrando en modo dim (sin actividad)", flush=True)
                # Avisa al plugin growatt para pausar polling inmediatamente.
                try: plugin_growatt.set_deck_dimmed(True)
                except Exception: pass

            # Si está dim (manual via X o auto), no renderizar
            if modo_dim_activo:
                time.sleep(1)
                continue

            try:
                # Snapshot de pagina_actual al inicio del iter: si un press
                # (físico o inyectado por la GUI) la cambia entre la
                # renderización y el dump, sin snapshot los imgs viejos
                # acabarían en el dir del page nuevo (mirror desync visto
                # como "tile MUTE de MEDIA aparece en APPS").
                page_now = pagina_actual

                cur_net = psutil.net_io_counters()
                if page_now == 1:
                    imgs = render_pagina_sistema(deck, tam, last_net, cur_net)
                else:
                    imgs = PAGINAS_RENDER.get(page_now, render_pagina_config)(deck, tam)
                last_net = cur_net

                # Wirea YA _current_page_id para que el dump de esta iter
                # vaya al subdir correcto, antes de cualquier _finalizar.
                render_core.set_current_page(page_now)

                # `with deck:` agrupa writes en un bloque atómico (lock interno
                # de la librería) — más robusto frente a reconexión USB y
                # señaliza al DummyDeck cuándo redibujar el mosaico.
                with deck:
                    if page_now != pagina_anterior or forzar_redraw:
                        if page_now != pagina_anterior:
                            # Cambio de página: descarta el dedup (mismo tecla
                            # con contenido distinto fuerza redraw real).
                            render_core._last_sent.clear()
                        for k in range(deck.key_count()):
                            if k not in imgs:
                                _push_key(deck, k, _finalizar(deck, tam, None, k))
                        pagina_anterior = page_now
                        forzar_redraw = False

                    for key, img in imgs.items():
                        _push_key(deck, key, _finalizar(deck, tam, img, key))

            except Exception as e:
                print(f"[ERR] {e} — intentando reconectar...", flush=True)
                try: deck.close()
                except: pass
                deck = None
                time.sleep(2)
                while deck is None:
                    deck = _abrir_deck()
                    if deck is None:
                        print("[WAIT] esperando deck...", flush=True)
                        time.sleep(2)
                tam = deck.key_image_format()['size']
                deck.set_key_callback(boton_presionado)
                pagina_anterior = None
                _invalidar_render_cache()
                print("[OK] reconectado", flush=True)

            # En vez de sleep fijo: wait hasta 1s O hasta que algo dispare
            # el event (press físico, inject, hooks de pomodoro/ctx/etc).
            _redraw_event.wait(timeout=1)
            _redraw_event.clear()

    finally:
        try: deck.reset()
        except: pass
        try: deck.close()
        except: pass


if __name__ == "__main__":
    import signal
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt))
    try:
        iniciar_dashboard()
    except KeyboardInterrupt:
        pass
