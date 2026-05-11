"""LCARS Lower Decks — pastel claro."""
from plugins.themes import register
from plugins.themes._chromes import lcars_chrome

register("lowerdecks", palette={
    "primary": "#FFBBAA",
    "alert":   "#DD4444",
    "warn":    "#FFAA00",
    "ok":      "#FF8866",
    "info":    "#DDBBFF",
    "violet":  "#CC88FF",
    "neutral": "#FFAA90",
    "ribs":   ("#FFCC66", "#CC88FF", "#7788FF"),
}, chrome=lcars_chrome, description="LCARS Lower Decks (pastel)")
