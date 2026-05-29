"""Bindings pedal para VS Code / Code-OSS — navegación entre archivos."""
from plugins.pedal_apps import register

BINDINGS = {
    # alt: navegación entre archivos con <Ctrl><PageUp>/<PageDown>
    "tap_izq":    ("← Tab",  "<Ctrl><Shift>Tab"),
    "tap_der":    ("Tab →",  "<Ctrl>Tab"),
    "hold_izq":   ("Find",    "<Ctrl>f"),
    "hold_der":   ("Replace", "<Ctrl>h"),
    "double_cen": ("Save",    "<Ctrl>s"),
}
for name in ("code", "code-oss", "vscode"):
    register(name, bindings=BINDINGS, description="VS Code — tabs + find + save")
