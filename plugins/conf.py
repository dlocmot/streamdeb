"""Plugin CONF (página 5): UI de configuración en vivo.
Render puro — los handlers de press mutan globales y por ahora viven en
dashboard_pro.py (etapa de migración: state aún no extraído a contexto)."""
from core.config import (
    TIEMPO_FALLBACK_MIN, TIEMPO_FALLBACK_MAX,
    TIEMPO_DIM_MIN, TIEMPO_DIM_MAX,
)
from core.helpers import _fmt_tiempo
from core.widgets import dibujar_panel_metrica, dibujar_boton_x


def render_pagina_config(deck, tam, nav_imgs, *,
                          brillo_actual, tiempo_fallback, tiempo_dim,
                          perfil_visual, wallpaper_idx, wallpaper_total,
                          banner_enabled):
    """Render de CONF. Recibe el snapshot de state actual como kwargs.
    `wallpaper_total` es el entero (no la función) para evitar import circular."""
    fb_pct  = (tiempo_fallback - TIEMPO_FALLBACK_MIN) / (TIEMPO_FALLBACK_MAX - TIEMPO_FALLBACK_MIN) * 100
    dim_pct = (tiempo_dim - TIEMPO_DIM_MIN) / (TIEMPO_DIM_MAX - TIEMPO_DIM_MIN) * 100
    imgs = dict(nav_imgs)
    imgs.update({
        # Col 0 — Brillo
        8:  dibujar_panel_metrica(deck, tam, "Brillo", "+", "#ffaa00"),
        16: dibujar_panel_metrica(deck, tam, "Brillo", f"{brillo_actual}%", "#ffaa00", pct=brillo_actual),
        24: dibujar_panel_metrica(deck, tam, "Brillo", "−", "#ffaa00"),
        # Col 1 — Fallback a SIS
        9:  dibujar_panel_metrica(deck, tam, "Fallback", "+", "#33ccff"),
        17: dibujar_panel_metrica(deck, tam, "Fallback", _fmt_tiempo(tiempo_fallback), "#33ccff", pct=fb_pct),
        25: dibujar_panel_metrica(deck, tam, "Fallback", "−", "#33ccff"),
        # Col 2 — Dim por inactividad
        10: dibujar_panel_metrica(deck, tam, "Dim", "+", "#cc66ff"),
        18: dibujar_panel_metrica(deck, tam, "Dim", _fmt_tiempo(tiempo_dim), "#cc66ff", pct=dim_pct),
        26: dibujar_panel_metrica(deck, tam, "Dim", "−", "#cc66ff"),
        # Col 3 — Perfil visual
        11: dibujar_panel_metrica(deck, tam, "Perfil V", f"{perfil_visual}", "#33ff99"),
        # Col 4 — Wallpaper (rotación / OFF)
        12: dibujar_panel_metrica(
            deck, tam, "Wallpaper",
            "OFF" if wallpaper_idx == 0 else f"{wallpaper_idx}/{wallpaper_total}",
            "#666666" if wallpaper_idx == 0 else "#ff66cc",
        ),
        # Col 5 — Banner idle ON/OFF
        13: dibujar_panel_metrica(
            deck, tam, "Banner",
            "ON" if banner_enabled else "OFF",
            "#ffaa66" if banner_enabled else "#666666",
        ),
        # Col 7 fila 1 — perfil Kiosko
        15: dibujar_panel_metrica(deck, tam, "Perfil", "Kiosko", "#00ddff"),
        # X de apagado
        31: dibujar_boton_x(deck, tam),
    })
    return imgs
