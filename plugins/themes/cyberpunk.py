"""Cyberpunk 2077 — amarillo brutal sobre negro, magenta/cian acento."""
from plugins.themes import register
from plugins.themes._chromes import cyberpunk_chrome

register("cyberpunk", palette={
    "primary": "#FCEE0A",
    "alert":   "#FF003C",
    "warn":    "#FF8A00",
    "ok":      "#00F0FF",
    "info":    "#00F0FF",
    "violet":  "#FF00A8",
    "neutral": "#666666",
    "ribs":   ("#FCEE0A", "#FF003C", "#00F0FF"),
}, chrome=cyberpunk_chrome, description="Cyberpunk 2077 (amarillo/cian/magenta)",
   chrome_style="neon")
