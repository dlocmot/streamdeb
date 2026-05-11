"""Bindings pedal para Firefox / firefox-esr (instance: navigator)."""
from plugins.pedal_apps import register

BINDINGS = {
    "tap_izq":    ("Atrás",   "<Alt>Left"),
    "tap_der":    ("Adelan.", "<Alt>Right"),
    "hold_izq":   ("Tab×",    "<Ctrl>w"),       # cerrar tab
    "hold_der":   ("Reload",  "<Ctrl>r"),
    "double_cen": ("Find",    "<Ctrl>f"),
}
# Mismo binding bajo los 3 WM_CLASS posibles que xprop puede reportar.
for name in ("firefox", "firefox-esr", "navigator"):
    register(name, bindings=BINDINGS, description="Firefox / firefox-esr navegación")
