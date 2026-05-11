"""Halloween — naranja calabaza + púrpura + verde tóxico."""
from plugins.themes import register
from plugins.themes._chromes import halloween_chrome

register("halloween", palette={
    "primary": "#FF6A00",
    "alert":   "#FF1744",
    "warn":    "#FFD000",
    "ok":      "#76FF03",
    "info":    "#7C4DFF",
    "violet":  "#B14AED",
    "neutral": "#5A2D6A",
    "ribs":   ("#FF6A00", "#B14AED", "#76FF03"),
}, chrome=halloween_chrome, description="Halloween (calabaza/púrpura)",
   chrome_style="neon")
