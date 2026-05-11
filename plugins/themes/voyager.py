"""LCARS Voyager — dorados + violetas suaves."""
from plugins.themes import register
from plugins.themes._chromes import lcars_chrome

register("voyager", palette={
    "primary": "#FFCC66",
    "alert":   "#DD4444",
    "warn":    "#FFAA44",
    "ok":      "#FFCC66",
    "info":    "#CC88FF",
    "violet":  "#9944FF",
    "neutral": "#FFAA90",
    "ribs":   ("#FFAA00", "#FF8866", "#7788FF"),
}, chrome=lcars_chrome, description="LCARS Voyager (dorado)")
