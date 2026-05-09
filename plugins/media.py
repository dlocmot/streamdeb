"""Plugin MEDIA (página 3): control de volumen y reproducción."""
from core.helpers import _run
from core.iconos import buscar_icono as _buscar_icono
from core.widgets import dibujar_lanzador_web


def render_pagina_media(deck, tam, nav_imgs, mute_activo):
    """Layout: VOL+ (15), MUTE (23), VOL- (31) en la última columna · PLAY (22) al centro."""
    imgs = dict(nav_imgs)
    icon_volup   = _buscar_icono("audio-volume-high")
    icon_voldown = _buscar_icono("audio-volume-low")
    icon_mute    = _buscar_icono("audio-volume-muted" if mute_activo else "audio-volume-medium")
    icon_play    = _buscar_icono("media-playback-start")
    imgs[15] = dibujar_lanzador_web(deck, tam, "VOL+", "#663399", icon_volup)
    imgs[23] = dibujar_lanzador_web(deck, tam, "MUTE", "#cc0000", icon_mute)
    imgs[31] = dibujar_lanzador_web(deck, tam, "VOL-", "#663399", icon_voldown)
    imgs[22] = dibujar_lanzador_web(deck, tam, "PLAY", "#0099ff", icon_play)
    return imgs


def on_press(tecla):
    """Devuelve True si la tecla pertenece a MEDIA y se manejó."""
    if tecla == 15:
        _run("pactl set-sink-volume @DEFAULT_SINK@ +5%")
    elif tecla == 23:
        _run("pactl set-sink-mute @DEFAULT_SINK@ toggle")
    elif tecla == 31:
        _run("pactl set-sink-volume @DEFAULT_SINK@ -5%")
    elif tecla == 22:
        _run("playerctl play-pause")
    else:
        return False
    return True
