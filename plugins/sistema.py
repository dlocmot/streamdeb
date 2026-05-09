"""Plugin SIS (página 1): dashboard de sistema con CPU/RAM/red/pings.
Inyecta widgets de pomodoro (15), clima (20-23) y docker entry (31)."""
import psutil

from core.config import CICLO_UPTIME
from core.helpers import _fmt_tiempo, _ip_2_lineas, obtener_color_rango
from core.widgets import dibujar_panel_metrica


# Highwater de throughput de red para escalar las barras de DOWN/UP.
max_visto_down = 1024.0
max_visto_up   = 1024.0


def render_pagina_sistema(deck, tam, nav_imgs, last_net, cur_net,
                            net_info, ping_pct_relativo_fn,
                            widgets_extras=None):
    """Render SIS. `widgets_extras`: dict {tecla: PIL} de plugins externos
    (pomodoro, clima, docker) — se mergea al final."""
    global max_visto_down, max_visto_up
    up_t  = (psutil.boot_time() and __import__('time').time() - psutil.boot_time()) or 0
    pct_u = (up_t % CICLO_UPTIME) / CICLO_UPTIME * 100
    cpu_t = psutil.cpu_percent()
    cores = psutil.cpu_percent(percpu=True)
    ram   = psutil.virtual_memory().percent
    swp   = psutil.swap_memory().percent
    disk  = psutil.disk_usage('/')
    dn_kbps = ((cur_net.bytes_recv - last_net.bytes_recv) * 8) / 1024
    up_kbps = ((cur_net.bytes_sent - last_net.bytes_sent) * 8) / 1024
    max_visto_down = max(max_visto_down, dn_kbps)
    max_visto_up   = max(max_visto_up,   up_kbps)
    f_r = lambda v: f"{int(v/1000)}Mb" if v >= 1000 else f"{int(v)}Kb"

    imgs = dict(nav_imgs)
    imgs.update({
        # Fila 1: uptime, CPU total
        8:  dibujar_panel_metrica(deck, tam, "Uptime", _fmt_tiempo(up_t), obtener_color_rango(pct_u), pct=pct_u),
        9:  dibujar_panel_metrica(deck, tam, "CPU T",  f"{int(cpu_t)}%", obtener_color_rango(cpu_t), pct=cpu_t),
        # Fila 2: RAM, SWAP, DISK
        16: dibujar_panel_metrica(deck, tam, "RAM",  f"{int(ram)}%", obtener_color_rango(ram), pct=ram),
        17: dibujar_panel_metrica(deck, tam, "SWAP", f"{int(swp)}%", obtener_color_rango(swp), pct=swp),
        18: dibujar_panel_metrica(deck, tam, "ROOT", f"{disk.free/(1024**3):.1f}G",
                                    obtener_color_rango(disk.percent), pct=disk.percent),
        # Fila 3: red
        24: dibujar_panel_metrica(deck, tam, "DOWN", f_r(dn_kbps), "#33ccff",
                                    pct=(dn_kbps/max_visto_down)*100),
        25: dibujar_panel_metrica(deck, tam, "UP",   f_r(up_kbps), "#0066ff",
                                    pct=(up_kbps/max_visto_up)*100),
        26: dibujar_panel_metrica(deck, tam, "Pública", _ip_2_lineas(net_info["ip_pub"]), "#33ccff"),
        27: dibujar_panel_metrica(deck, tam, "Local",   _ip_2_lineas(net_info["ip_loc"]), "#33ccff"),
    })
    # Cores 1..4
    for i, v in enumerate(cores[:4]):
        imgs[10+i] = dibujar_panel_metrica(deck, tam, f"C{i+1}", f"{int(v)}%",
                                            obtener_color_rango(v), pct=v)
    # Pings gateway / 1.1.1.1 / 8.8.8.8
    for idx, (cl, lb) in enumerate([("ping_gw","Gateway"),("ping_dns1","1.1.1.1"),("ping_dns2","8.8.8.8")]):
        ms = net_info[cl]
        if ms > 0:
            pct, color = ping_pct_relativo_fn(cl, ms)
            imgs[28+idx] = dibujar_panel_metrica(deck, tam, lb, f"{ms:.1f}", color, pct=pct, sub="ms")
        else:
            imgs[28+idx] = dibujar_panel_metrica(deck, tam, lb, "Err", "#666666", pct=0)

    # Widgets inyectados por otros plugins (pomodoro, clima, docker)
    if widgets_extras:
        imgs.update(widgets_extras)
    return imgs
