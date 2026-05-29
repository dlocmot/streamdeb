"""Plugin BANNER (página 9): pantalla idle full-deck con reloj, CPU/RAM y estado AWA."""
import datetime
import psutil
from PIL import Image, ImageDraw, ImageFont

from core.config import FONT_PATH
from core.helpers import cargar_fuente


def render_pagina_banner(deck, tam, cols, rows, api_info):
    """Imagen full-deck (cols*W × rows*H) con reloj grande, fecha,
    CPU%/RAM% y estado AWA. Troceada en cols*rows tiles RGBA."""
    W, H = tam
    full = Image.new("RGB", (cols * W, rows * H), "black")
    d = ImageDraw.Draw(full)

    ahora = datetime.datetime.now()
    hora  = ahora.strftime("%H:%M")
    fecha = ahora.strftime("%a %d %b %Y").upper()
    cw, ch = full.size

    fclock = cargar_fuente(int(H * 1.9))
    d.text((cw // 2, int(ch * 0.42)), hora, font=fclock, fill="#ffffff", anchor="mm")
    ffecha = cargar_fuente(int(H * 0.42))
    d.text((cw // 2, int(ch * 0.78)), fecha, font=ffecha, fill="#888888", anchor="mm")

    cpu = int(psutil.cpu_percent())
    ram = int(psutil.virtual_memory().percent)
    fstats = cargar_fuente(int(H * 0.30))
    d.text((W // 2, ch - int(H * 0.35)), f"CPU {cpu}%   RAM {ram}%",
           font=fstats, fill="#33ccff", anchor="lm")

    if api_info.get("online"):
        awa_txt = api_info["estado"].upper()
        awa_col = "#33ff33" if api_info["estado"] == "Abierta" else "#ff3333"
    else:
        awa_txt = "AWA OFFLINE"
        awa_col = "#666666"
    d.text((cw - W // 2, ch - int(H * 0.35)),
           awa_txt, font=fstats, fill=awa_col, anchor="rm")

    fhint = cargar_fuente(int(H * 0.20))
    d.text((cw - 12, int(H * 0.30)), "tap any key", font=fhint, fill="#444444", anchor="rm")

    imgs = {}
    for k in range(cols * rows):
        row, col = k // cols, k % cols
        tile = full.crop((col * W, row * H, (col + 1) * W, (row + 1) * H)).convert("RGBA")
        imgs[k] = tile
    return imgs
