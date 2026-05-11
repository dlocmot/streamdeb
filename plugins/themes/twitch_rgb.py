"""Twitch RGB — gaming streamer, púrpura Twitch + neón."""
from plugins.themes import register
from plugins.themes._chromes import twitch_chrome

register("twitch_rgb", palette={
    "primary": "#9146FF",
    "alert":   "#FF4654",
    "warn":    "#FFA800",
    "ok":      "#00FF7F",
    "info":    "#18A0FB",
    "violet":  "#E91E63",
    "neutral": "#3D3A4F",
    "ribs":   ("#9146FF", "#E91E63", "#00FF7F"),
}, chrome=twitch_chrome, description="Twitch RGB (gaming streamer)",
   chrome_style="neon")
