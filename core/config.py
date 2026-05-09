"""Constantes globales del proyecto. Inmutables después de import."""
import os
import sys
from urllib.parse import urlparse

FONT_PATH    = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# Identificación de hardware
DECK_SERIAL  = os.environ.get("STREAMDEB_DECK_SERIAL", "").strip()
POLL_HZ      = int(os.environ.get("STREAMDEB_POLL_HZ", "30"))

# Modo dummy (preview sin hardware) — `--dummy` en argv
DUMMY_MODE   = "--dummy" in sys.argv
PREVIEW_DIR  = os.environ.get("STREAMDEB_PREVIEW_DIR", "/tmp/streamdeb-preview")

# Texto password root para botón "RO123" (página SIS)
ROOT_TEXT    = "REDACTED"

# API ESP32 AWAhorro
API_HOST     = "http://192.168.18.10"   # editar según red
API_USER     = "StreamDeck"
API_IP       = urlparse(API_HOST).hostname or "192.168.18.10"

# Timing / rangos
CICLO_UPTIME           = 14400
BRILLO_MIN             = 10
BRILLO_MAX             = 100
BRILLO_PASO            = 10
# Brillo monitor externo (xrandr gamma). 10..100 en %, se traduce a 0.1..1.0
MONITOR_BRILLO_MIN     = 10
MONITOR_BRILLO_MAX     = 100
MONITOR_BRILLO_PASO    = 10
MONITOR_OUTPUT         = os.environ.get("STREAMDEB_MONITOR_OUTPUT", "")  # "" = auto-detect
TIEMPO_PASO            = 60       # paso de los +/- en CONF (1 min)
TIEMPO_FALLBACK_MIN    = 60
TIEMPO_FALLBACK_MAX    = 1800
TIEMPO_DIM_MIN         = 60
TIEMPO_DIM_MAX         = 7200     # 2 h
LONGPRESS_S            = 2.0      # umbral pulsación larga

# Wallpaper
WALLPAPER_BRILLO     = 0.4        # 1.0 = original · 0.4 = 40% (oscurecido)
WALLPAPER_SATURACION = 1.25       # 1.0 = original · 1.25 = +25%
