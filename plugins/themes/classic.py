"""LCARS Classic TNG — paleta cálida Okuda canon (ha-lcars)."""
from plugins.themes import register
from plugins.themes._chromes import lcars_chrome

PALETTE = {
    "primary": "#FF7700",  # lcars-orange
    "alert":   "#DD4444",  # lcars-red
    "warn":    "#FFAA00",  # lcars-gold
    "ok":      "#FF7744",  # lcars-pumpkinshade
    "info":    "#7788FF",  # lcars-bluey
    "violet":  "#CC88FF",  # lcars-african-violet
    "neutral": "#FFBBAA",  # lcars-almond-creme
    "ribs":   ("#FFAA44", "#CC88FF", "#7788FF"),  # harvest, af-violet, bluey
}

register("classic", palette=PALETTE,
         chrome=lcars_chrome,
         description="LCARS Classic TNG (Okuda cálido)")
