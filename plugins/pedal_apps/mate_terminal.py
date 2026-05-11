"""Bindings pedal para Mate Terminal (cualquier emulador GNOME-derivado)."""
from plugins.pedal_apps import register

BINDINGS = {
    "tap_izq":    ("Copy",    "<Ctrl><Shift>c"),
    "tap_der":    ("Paste",   "<Ctrl><Shift>v"),
    "hold_izq":   ("New T.",  "<Ctrl><Shift>t"),
    "hold_der":   ("Close",   "<Ctrl><Shift>w"),
    "double_cen": ("Clear",   "<Ctrl>l"),
}
for name in ("mate-terminal", "gnome-terminal-server", "xterm"):
    register(name, bindings=BINDINGS,
             description="Mate/Gnome Terminal — tabs + clear")
