"""Bindings pedal para VLC media player — control reproducción."""
from plugins.pedal_apps import register

register("vlc", bindings={
    "tap_izq":    ("-10s",    "<Alt>Left"),
    "tap_der":    ("+10s",    "<Alt>Right"),
    "hold_izq":   ("-1min",   "<Ctrl>Left"),
    "hold_der":   ("+1min",   "<Ctrl>Right"),
    "double_cen": ("Play/⏸",  "space"),
}, description="VLC — seek + play/pause")
