"""Terminal IDE — sobrio para uso diario (VS Code-ish)."""
from plugins.themes import register
from plugins.themes._chromes import ide_chrome

register("terminal_ide", palette={
    "primary": "#D4D4D4",
    "alert":   "#F44747",
    "warn":    "#FFCC00",
    "ok":      "#4EC9B0",
    "info":    "#569CD6",
    "violet":  "#C586C0",
    "neutral": "#666666",
    "ribs":   ("#569CD6", "#4EC9B0", "#C586C0"),
}, chrome=ide_chrome, description="Terminal IDE (VS Code-like)",
   chrome_style="flat")
