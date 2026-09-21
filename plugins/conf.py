"""Plugin CONF (página 5): UI de configuración en vivo.
Render puro — los handlers de press mutan globales y por ahora viven en
dashboard_pro.py (etapa de migración: state aún no extraído a contexto)."""
from core.config import (
    TIEMPO_FALLBACK_MIN, TIEMPO_FALLBACK_MAX,
    DIM_OPCIONES, DIM_TECLAS,
)
from core.helpers import _fmt_tiempo
from core.widgets import dibujar_panel_metrica, dibujar_boton_x


def render_pagina_config(deck, tam, nav_imgs, *,
                          brillo_actual, tiempo_fallback, tiempo_dim,
                          perfil_visual, wallpaper_idx, wallpaper_total,
                          monitor_brillo, tema_lcars="classic"):
    """Render de CONF. Recibe el snapshot de state actual como kwargs.
    `wallpaper_total` es el entero (no la función) para evitar import circular."""
    fb_pct  = (tiempo_fallback - TIEMPO_FALLBACK_MIN) / (TIEMPO_FALLBACK_MAX - TIEMPO_FALLBACK_MIN) * 100
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
        # Col 2 — Dim por inactividad: ver el bucle de abajo (una tecla por opción)
        # Col 3 — Brillo monitor (xrandr gamma): + arriba, valor centro, − abajo
        11: dibujar_panel_metrica(deck, tam, "Monitor", "+", "#ffd23f"),
        19: dibujar_panel_metrica(deck, tam, "Monitor", f"{monitor_brillo}%", "#ffd23f", pct=monitor_brillo),
        27: dibujar_panel_metrica(deck, tam, "Monitor", "−", "#ffd23f"),
        # Col 4 — Wallpaper (rotación / OFF)
        12: dibujar_panel_metrica(
            deck, tam, "Wallpaper",
            "OFF" if wallpaper_idx == 0 else f"{wallpaper_idx}/{wallpaper_total}",
            "#666666" if wallpaper_idx == 0 else "#ff66cc",
        ),
        # Col 6 — Perfil visual: en perfil 3 muestra el tema y rota entre
        # 1 → 2 → 3·<tema1> → 3·<tema2> → ... → wrap a 1.
        14: dibujar_panel_metrica(
            deck, tam, "Perfil V",
            (tema_lcars[:7].upper() if perfil_visual == 3 else str(perfil_visual)),
            "#33ff99" if perfil_visual != 3 else "#ff77cc",
        ),
        # X de apagado
        31: dibujar_boton_x(deck, tam),
    })
    # Col 2 — Dim: una tecla por opción, selección directa. La activa lleva el
    # color y la barra llena; las otras quedan apagadas en gris.
    for tecla, (segundos, etiqueta) in zip(DIM_TECLAS, DIM_OPCIONES):
        activa = (segundos == tiempo_dim)
        imgs[tecla] = dibujar_panel_metrica(
            deck, tam, "Dim", etiqueta,
            "#cc66ff" if activa else "#666666",
            pct=100 if activa else None,
        )
    return imgs
