"""Bindings por defecto cuando la app activa no tiene plugin propio.
Acciones genéricas de productividad / sistema."""
from plugins.pedal_apps import register

register("default", bindings={
    "tap_izq":    ("← Tab",  "<Ctrl><Shift>Tab"),  # tab anterior
    "tap_der":    ("Tab →",  "<Ctrl>Tab"),         # tab siguiente
    "hold_izq":   ("Undo",   "<Ctrl>z"),
    "hold_der":   ("Redo",   "<Ctrl>y"),
    "double_cen": ("Save",   "<Ctrl>s"),
}, description="Genérico — navegación tab + undo/redo + save")
