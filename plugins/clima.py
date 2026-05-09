"""Plugin CLIMA Arequipa (página 11 + widget en SIS 20-23).
Fuente: Open-Meteo (sin API key). Refresh cada 15 min."""
import datetime
import json
import os
import time
import urllib.request
from PIL import Image, ImageDraw, ImageFont

from core.config import FONT_PATH
from core.iconos import iconify_png as _iconify_png
from core.widgets import _nuevo_lienzo, dibujar_panel_metrica, dibujar_lanzador_web


CLIMA_LAT, CLIMA_LON = -16.4090, -71.5375  # Arequipa, Perú
TECLAS_SIS = (20, 21, 22, 23)  # 4 tiles del widget en SIS

clima_info = {
    "online": False, "temp": None, "temp_min": None, "temp_max": None,
    "humedad": None, "viento": None, "weather_code": None, "ts": 0,
    "hourly": [],
}


def tareas_fondo():
    """Polling Open-Meteo cada 15 min."""
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={CLIMA_LAT}&longitude={CLIMA_LON}"
        f"&current=temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code"
        f"&daily=temperature_2m_max,temperature_2m_min"
        f"&hourly=temperature_2m,weather_code,precipitation_probability"
        f"&forecast_days=2"
        f"&timezone=America/Lima"
    )
    while True:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "streamdeb/1.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode("utf-8"))
            cur    = data.get("current", {})
            daily  = data.get("daily", {})
            hourly = data.get("hourly", {})
            h_times = hourly.get("time", []) or []
            h_temps = hourly.get("temperature_2m", []) or []
            h_codes = hourly.get("weather_code", []) or []
            h_precs = hourly.get("precipitation_probability", []) or []
            now_iso = datetime.datetime.now().strftime("%Y-%m-%dT%H:00")
            inicio = 0
            for i, t in enumerate(h_times):
                if t >= now_iso:
                    inicio = i
                    break
            hourly_list = []
            for i in range(inicio, min(inicio + 24, len(h_times))):
                hourly_list.append({
                    "hora":   h_times[i][-5:],
                    "temp":   h_temps[i] if i < len(h_temps) else None,
                    "code":   h_codes[i] if i < len(h_codes) else None,
                    "precip": h_precs[i] if i < len(h_precs) else None,
                })
            clima_info.update({
                "online": True,
                "temp":         cur.get("temperature_2m"),
                "humedad":      cur.get("relative_humidity_2m"),
                "viento":       cur.get("wind_speed_10m"),
                "weather_code": cur.get("weather_code"),
                "temp_min":     (daily.get("temperature_2m_min") or [None])[0],
                "temp_max":     (daily.get("temperature_2m_max") or [None])[0],
                "hourly":       hourly_list,
                "ts": time.time(),
            })
        except Exception as e:
            clima_info["online"] = False
            print(f"[CLIMA] error: {e}", flush=True)
        time.sleep(15 * 60)


# --- Helpers visuales ---

def icono_wmo(code):
    """Mapea WMO weather_code a (iconify_name, color_hex)."""
    if code is None: return ("mdi:weather-cloudy-alert", "888888")
    if code == 0:                  return ("mdi:weather-sunny",            "ffcc33")
    if code in (1, 2):             return ("mdi:weather-partly-cloudy",    "ffaa66")
    if code == 3:                  return ("mdi:weather-cloudy",           "aaaaaa")
    if code in (45, 48):           return ("mdi:weather-fog",              "999999")
    if 51 <= code <= 57:           return ("mdi:weather-pouring",          "66aadd")
    if 61 <= code <= 67:           return ("mdi:weather-rainy",            "4488cc")
    if 71 <= code <= 77:           return ("mdi:weather-snowy",            "ddeeff")
    if 80 <= code <= 82:           return ("mdi:weather-pouring",          "4488cc")
    if 85 <= code <= 86:           return ("mdi:weather-snowy-heavy",      "ddeeff")
    if 95 <= code <= 99:           return ("mdi:weather-lightning",        "cc66ff")
    return ("mdi:weather-cloudy", "aaaaaa")


def descripcion_wmo(code):
    if code is None: return "—"
    return {
        0: "Despejado", 1: "Mayorment.", 2: "Parc nubl.", 3: "Nublado",
        45: "Niebla", 48: "Niebla esc",
        51: "Llov susv", 53: "Llov susv", 55: "Llov susv",
        61: "Lluvia",  63: "Lluvia",     65: "Lluv fuer",
        71: "Nieve",   73: "Nieve",      75: "Nieve int",
        80: "Chubasco",81: "Chubasco",   82: "Chub fuer",
        95: "Tormenta",96: "Torm gran",  99: "Torm gran",
    }.get(code, "—")


_TEMP_GRADIENT = [
    (-10, (59, 91, 219)), (0, (77, 171, 247)), (15, (169, 227, 75)),
    (22, (255, 212, 59)), (30, (255, 146, 43)), (38, (224, 49, 49)),
]

def temp_color(t):
    if t is None: return (136, 136, 136)
    g = _TEMP_GRADIENT
    if t <= g[0][0]: return g[0][1]
    if t >= g[-1][0]: return g[-1][1]
    for i in range(len(g) - 1):
        (t1, c1), (t2, c2) = g[i], g[i + 1]
        if t1 <= t < t2:
            r = (t - t1) / (t2 - t1)
            return tuple(int(c1[k] + (c2[k] - c1[k]) * r) for k in range(3))
    return (255, 255, 255)


def _icono_pil(code, size):
    name, col = icono_wmo(code)
    p = _iconify_png(name, col, 256)
    if not p or not os.path.exists(p):
        return None
    try:
        ico = Image.open(p).convert("RGBA")
        return ico.resize((size, size), Image.LANCZOS)
    except Exception:
        return None


def _trocear_banner(imagen_full, tecla_base, W, H, cols, imgs):
    for i in range(cols):
        tile = imagen_full.crop((i * W, 0, (i + 1) * W, H)).convert("RGBA")
        tile._streamdeb_stable = False
        imgs[tecla_base + i] = tile


# --- Widgets en SIS (4 tiles 20-23) ---

def widget_para_sistema(deck, tam):
    """Widget consolidado en SIS tecla 20: icono + temp + min/max.
    Tap abre página CLIMA (id 11) con el detalle completo."""
    imgs = {}
    if clima_info["online"] and clima_info["temp"] is not None:
        ico_name, ico_color = icono_wmo(clima_info["weather_code"])
        ico_path = _iconify_png(ico_name, ico_color, 256)
        tmin = int(round(clima_info['temp_min'] or 0))
        tmax = int(round(clima_info['temp_max'] or 0))
        imgs[20] = dibujar_lanzador_web(
            deck, tam,
            f"{clima_info['temp']:.0f}° {tmin}/{tmax}",
            "#" + ico_color, ico_path,
        )
    else:
        imgs[20] = dibujar_panel_metrica(deck, tam, "Clima", "—", "#666666")
    return imgs


# --- Página CLIMA (11): banner ahora + meteograma + strip 12h ---

def render_pagina_clima(deck, tam, nav_imgs):
    W, H = tam
    imgs  = dict(nav_imgs)
    horas = clima_info.get("hourly", [])

    # === BANDA 1: AHORA (768×96) ===
    banner = Image.new("RGB", (8 * W, H), (13, 27, 42))
    d = ImageDraw.Draw(banner)
    if clima_info.get("online") and clima_info.get("temp") is not None:
        ico = _icono_pil(clima_info["weather_code"], 64)
        if ico is not None:
            banner.paste(ico, (12, 16), ico)
        f_temp = ImageFont.truetype(FONT_PATH, 64)
        f_cond = ImageFont.truetype(FONT_PATH, 14)
        col_temp = temp_color(clima_info["temp"])
        d.text((92, 36), f"{int(round(clima_info['temp']))}°",
               font=f_temp, fill=col_temp, anchor="lm")
        d.text((92, 78), descripcion_wmo(clima_info["weather_code"]),
               font=f_cond, fill=(180, 180, 180), anchor="lm")

        x_right = 8 * W - 16
        f_mm   = ImageFont.truetype(FONT_PATH, 22)
        f_lbl  = ImageFont.truetype(FONT_PATH, 11)
        f_det  = ImageFont.truetype(FONT_PATH, 14)
        f_city = ImageFont.truetype(FONT_PATH, 12)

        tmin = clima_info.get("temp_min")
        tmax = clima_info.get("temp_max")
        if tmin is not None and tmax is not None:
            d.text((x_right, 22), "MIN/MAX", font=f_lbl, fill=(140, 140, 140), anchor="rm")
            d.text((x_right, 42), f"{int(round(tmin))}° / {int(round(tmax))}°",
                   font=f_mm, fill=(220, 220, 220), anchor="rm")

        hum = clima_info.get("humedad") or 0
        vie = clima_info.get("viento") or 0
        d.text((x_right, 64), f"💧 {int(hum)}%   💨 {int(vie)} km/h",
               font=f_det, fill=(120, 180, 220), anchor="rm")
        ahora = datetime.datetime.now().strftime("%H:%M")
        d.text((x_right, 84), f"AREQUIPA · {ahora}",
               font=f_city, fill=(160, 160, 160), anchor="rm")
    else:
        f = ImageFont.truetype(FONT_PATH, 24)
        d.text((4 * W, H // 2), "Clima · sin datos",
               font=f, fill=(120, 120, 120), anchor="mm")
    _trocear_banner(banner, 8, W, H, 8, imgs)

    # === BANDA 2: METEOGRAMA 12h (768×96) ===
    meteo = Image.new("RGB", (8 * W, H), (10, 10, 10))
    d = ImageDraw.Draw(meteo)
    h12 = horas[:12]
    if len(h12) >= 2:
        temps = [h["temp"] for h in h12 if h.get("temp") is not None]
        precs = [(h.get("precip") or 0) for h in h12]
        if temps:
            tmin_g = min(temps)
            tmax_g = max(temps)
            rango = max(1.0, tmax_g - tmin_g)
            margen_x = 24
            graph_w = 8 * W - 2 * margen_x
            graph_top = 22
            graph_bot = H - 14
            graph_h = graph_bot - graph_top
            n = len(h12)

            def x_de(i): return margen_x + int(i * graph_w / (n - 1))
            def y_de(t): return graph_bot - int((t - tmin_g) / rango * graph_h)

            for i, p in enumerate(precs):
                if p > 0:
                    bar_h = int(p / 100 * graph_h * 0.9)
                    cx = x_de(i)
                    d.rectangle((cx - 8, graph_bot - bar_h, cx + 8, graph_bot),
                                fill=(77, 171, 247))

            for i in range(n - 1):
                t0, t1 = h12[i].get("temp"), h12[i + 1].get("temp")
                if t0 is None or t1 is None: continue
                col = temp_color((t0 + t1) / 2)
                d.line([(x_de(i), y_de(t0)), (x_de(i + 1), y_de(t1))],
                       fill=col, width=3)

            for i, h in enumerate(h12):
                t = h.get("temp")
                if t is None: continue
                col = temp_color(t)
                cx, cy = x_de(i), y_de(t)
                d.ellipse((cx - 3, cy - 3, cx + 3, cy + 3), fill=col)

            f_hr = ImageFont.truetype(FONT_PATH, 11)
            for i in range(0, n, 3):
                d.text((x_de(i), 8), h12[i]["hora"][:2] + "h",
                       font=f_hr, fill=(140, 140, 140), anchor="mm")
            f_t = ImageFont.truetype(FONT_PATH, 11)
            d.text((4, graph_top), f"{int(round(tmax_g))}°",
                   font=f_t, fill=(180, 180, 180), anchor="lm")
            d.text((4, graph_bot), f"{int(round(tmin_g))}°",
                   font=f_t, fill=(180, 180, 180), anchor="lm")
    else:
        f = ImageFont.truetype(FONT_PATH, 14)
        d.text((4 * W, H // 2), "meteograma sin datos",
               font=f, fill=(100, 100, 100), anchor="mm")
    _trocear_banner(meteo, 16, W, H, 8, imgs)

    # === BANDA 3: Strip horario 12h paso 2h ===
    paso = 2
    for i in range(8):
        h_idx = i * paso
        tecla = 24 + i
        if h_idx >= len(horas):
            imgs[tecla] = _nuevo_lienzo(tam)
            continue
        h = horas[h_idx]
        tile = Image.new("RGBA", tam, (10, 10, 10, 255))
        td = ImageDraw.Draw(tile)
        f_hr = ImageFont.truetype(FONT_PATH, 13)
        td.text((W // 2, 12), h["hora"][:2] + "h",
                font=f_hr, fill=(170, 170, 170), anchor="mm")
        t = h.get("temp")
        if t is not None:
            f_t = ImageFont.truetype(FONT_PATH, 26)
            td.text((W // 2, 38), f"{int(round(t))}°",
                    font=f_t, fill=temp_color(t), anchor="mm")
        ico = _icono_pil(h.get("code"), 30)
        if ico is not None:
            tile.paste(ico, ((W - 30) // 2, 56), ico)
        p = h.get("precip") or 0
        if p > 40:
            f_p = ImageFont.truetype(FONT_PATH, 11)
            td.text((W - 4, H - 4), f"{int(p)}%",
                    font=f_p, fill=(77, 171, 247), anchor="rb")
        imgs[tecla] = tile
    return imgs
