"""Synthwave 80s — magenta/cian sobre violeta profundo, retrowave."""
from plugins.themes import register
from plugins.themes._chromes import synthwave_chrome

register("synthwave", palette={
    "primary": "#FF2A6D",
    "alert":   "#FF124F",
    "warn":    "#FF9F1C",
    "ok":      "#05D9E8",
    "info":    "#01C5C4",
    "violet":  "#B967FF",
    "neutral": "#7A6AB9",
    "ribs":   ("#FF2A6D", "#B967FF", "#05D9E8"),
}, chrome=synthwave_chrome, description="Synthwave 80s (retrowave magenta/cian)",
   chrome_style="neon")
