"""LCARS Cardassia — violetas + rojizos militares."""
from plugins.themes import register
from plugins.themes._chromes import lcars_chrome

register("cardassia", palette={
    "primary": "#CC88FF",
    "alert":   "#DD4444",
    "warn":    "#FFAA00",
    "ok":      "#FF7744",
    "info":    "#7788FF",
    "violet":  "#9944FF",
    "neutral": "#FF977B",
    "ribs":   ("#9944FF", "#FF7744", "#FFCC66"),
}, chrome=lcars_chrome, description="LCARS Cardassia (violeta)")
