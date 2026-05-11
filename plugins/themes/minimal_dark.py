"""Minimal Dark — monocromo + acento menta. Sobrio."""
from plugins.themes import register
from plugins.themes._chromes import minimal_chrome

register("minimal_dark", palette={
    "primary": "#E6E6E6",
    "alert":   "#FF5555",
    "warn":    "#F1FA8C",
    "ok":      "#50FA7B",
    "info":    "#8BE9FD",
    "violet":  "#BD93F9",
    "neutral": "#44475A",
    "ribs":   ("#50FA7B", "#8BE9FD", "#44475A"),
}, chrome=minimal_chrome, description="Minimal Dark (monocromo + acento)",
   chrome_style="flat")
