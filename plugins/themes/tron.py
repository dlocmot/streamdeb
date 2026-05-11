"""Tron — circuito sci-fi, cian eléctrico sobre azul nocturno."""
from plugins.themes import register
from plugins.themes._chromes import tron_chrome

register("tron", palette={
    "primary": "#6FC3DF",
    "alert":   "#FF6F00",
    "warn":    "#F9D923",
    "ok":      "#00E5FF",
    "info":    "#6FC3DF",
    "violet":  "#1F51FF",
    "neutral": "#3A4A6A",
    "ribs":   ("#00E5FF", "#1F51FF", "#6FC3DF"),
}, chrome=tron_chrome, description="Tron (cian sobre azul nocturno)",
   chrome_style="neon")
