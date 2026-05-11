"""LCARS Nemesis Blue — paleta fría dominada por azules."""
from plugins.themes import register
from plugins.themes._chromes import lcars_chrome

register("nemesis", palette={
    "primary": "#7788FF",
    "alert":   "#DD4444",
    "warn":    "#FFAA00",
    "ok":      "#7788FF",
    "info":    "#CC88FF",
    "violet":  "#9944FF",
    "neutral": "#DDBBFF",
    "ribs":   ("#7788FF", "#9944FF", "#FFAA90"),
}, chrome=lcars_chrome, description="LCARS Nemesis (azul/violeta)")
