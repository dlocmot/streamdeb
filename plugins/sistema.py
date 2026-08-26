"""Plugin SIS (página 1): dashboard de sistema con CPU/RAM/red/pings.
Inyecta widgets de otros plugins (clima 19, docker 26, growatt 12, gridwatch 27).
Subpáginas: CORES (13), PINGS (14), NET (15), TEMPS (16)."""
import math
import os
import time
import threading
from collections import deque
from types import SimpleNamespace

import psutil

from core.config import CICLO_UPTIME
from core.helpers import _fmt_tiempo, _ip_2_lineas, obtener_color_rango
from core.widgets import dibujar_panel_metrica, dibujar_panel_cores, dibujar_panel_pings


# Escala de las barras de red. Antes era un máximo histórico que sólo crecía:
# bastaba una descarga para dejar la escala clavada y volver invisible todo el
# tráfico normal (medido: 391 kb/s contra un pico de 31 Mb/s = 1% de barra).
# Ahora es el pico de una ventana móvil, así que se recupera sola.
NET_VENTANA_S  = 300.0    # 5 min de historia para el pico

# Intervalo mínimo entre muestras. Por debajo de esto, Δbytes/Δt es ruido: un
# redibujado disparado por una pulsación puede caer a milisegundos del anterior
# y el cociente dispara valores absurdos (se midió un "pico" de 142 Mb/s con la
# red en reposo) que además contaminaban la escala durante minutos.
NET_DT_MIN = 0.5

# Escala logarítmica: el caudal abarca cinco órdenes de magnitud (reposo ~10 kb/s,
# descarga ~100 Mb/s) y ninguna barra lineal puede mostrar ambos extremos — con
# suelo bajo se satura al navegar, con suelo alto el uso normal es invisible.
NET_LOG_MIN =      1.0    # kb/s → barra vacía
NET_LOG_MAX = 100000.0    # kb/s (100 Mb/s) → barra llena

_NICS_TTL = 60.0
_nics_cache = {"lista": None, "ts": 0.0}


def _nics_fisicas():
    """Interfaces con hardware real: sólo ellas tienen `device` en sysfs.

    Excluye loopback, los puentes de Docker, veth y las VPN: su tráfico viaja
    además por la interfaz física, así que sumarlas lo contaría dos veces."""
    ahora = time.time()
    if _nics_cache["lista"] is None or ahora - _nics_cache["ts"] > _NICS_TTL:
        try:
            _nics_cache["lista"] = [n for n in os.listdir("/sys/class/net")
                                    if os.path.exists(f"/sys/class/net/{n}/device")]
        except OSError:
            _nics_cache["lista"] = []
        _nics_cache["ts"] = ahora
    return _nics_cache["lista"]


_NET_CAMPOS = ("bytes_recv", "bytes_sent", "packets_recv", "packets_sent",
               "errin", "errout", "dropin", "dropout")


def _net_contadores():
    """Contadores sumados de las interfaces físicas (fallback: todo el sistema)."""
    per = psutil.net_io_counters(pernic=True)
    nics = [n for n in _nics_fisicas() if n in per]
    if not nics:
        return psutil.net_io_counters()
    return SimpleNamespace(**{c: sum(getattr(per[n], c) for n in nics)
                              for c in _NET_CAMPOS})


def _fmt_caudal(kbps):
    """Caudal en 5 caracteres como mucho: la tipografía de las barras se
    dimensiona contra esa anchura y no debe desbordarla nunca."""
    if kbps >= 999_500:        # ≥ 1 Gb/s (el umbral evita "1000Mb", 6 car.)
        return f"{kbps/1_000_000:.1f}Gb"
    if kbps >= 9_950:          # 10–999 Mb/s (evita que 9,99 redondee a "10.0Mb")
        return f"{round(kbps/1000)}Mb"
    if kbps >= 1_000:          # 1–9,9 Mb/s
        return f"{kbps/1000:.1f}Mb"
    return f"{int(kbps)}Kb"


def _net_pct(kbps):
    """Altura de barra 0-100 en escala logarítmica."""
    v = max(NET_LOG_MIN, min(NET_LOG_MAX, kbps))
    return math.log10(v / NET_LOG_MIN) / math.log10(NET_LOG_MAX / NET_LOG_MIN) * 100

_net_hist = {"down": deque(), "up": deque()}   # clave → [(ts, kbps), ...]
_net_rate = {"down": 0.0, "up": 0.0, "cur": None, "ts": 0.0}


def _net_muestrear(ahora=None):
    """Muestrea los contadores del sistema y devuelve (dn_kbps, up_kbps).

    Si no ha pasado NET_DT_MIN desde la última muestra válida, devuelve la
    anterior sin recalcular ni tocar la historia."""
    ahora = ahora if ahora is not None else time.time()
    cur = _net_contadores()
    prev, prev_t = _net_rate["cur"], _net_rate["ts"]
    dt = ahora - prev_t
    if prev is None:
        _net_rate["cur"], _net_rate["ts"] = cur, ahora
        return 0.0, 0.0
    if dt < NET_DT_MIN:
        return _net_rate["down"], _net_rate["up"]
    dn = (cur.bytes_recv - prev.bytes_recv) * 8 / 1024 / dt
    up = (cur.bytes_sent - prev.bytes_sent) * 8 / 1024 / dt
    _net_rate.update(down=dn, up=up, cur=cur, ts=ahora)
    for clave, v in (("down", dn), ("up", up)):
        h = _net_hist[clave]
        h.append((ahora, v))
        limite = ahora - NET_VENTANA_S
        while h and h[0][0] < limite:
            h.popleft()
    return dn, up


def _net_pico(clave):
    """Pico de la ventana móvil. Sólo es un dato que muestra la página NET; la
    altura de las barras la decide _net_pct (logarítmica)."""
    return max((v for _, v in _net_hist[clave]), default=0.0)


def _fmt_uptime(segundos):
    """Uptime legible sin segundos (cambia como mucho cada minuto → el tile
    no repinta cada frame). 'Nd Nh' / 'Nh Nm' / 'Nm'."""
    s = max(0, int(segundos))
    d, rem = divmod(s, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:  return f"{d}d {h}h"
    if h:  return f"{h}h {m}m"
    return f"{m}m"


# Top procesos (mutado por tareas_fondo). Cada item: (nombre, valor_pct).
top_procs = {"cpu": [], "mem": []}
_procs_lock = threading.Lock()

# Sensores térmicos cacheados (poblado por tareas_fondo cada 6s). Leer
# sensors_temperatures() costaba ~9ms en cada frame de SIS; el térmico
# cambia lento, así que basta refrescarlo en background.
_sensores = {}


def _refrescar_sensores():
    global _sensores
    try:
        _sensores = psutil.sensors_temperatures()
    except Exception:
        _sensores = {}


def tareas_fondo():
    """Polling cada 6s de top 5 procesos (CPU/MEM) + sensores térmicos.
    cpu_percent(None) requiere priming: la primera pasada inicializa
    contadores y descarta resultados; las siguientes son válidas."""
    # Priming
    for p in psutil.process_iter():
        try: p.cpu_percent(None)
        except Exception: pass
    _refrescar_sensores()  # prime para que el primer render ya tenga temps
    time.sleep(1)
    total_ram = psutil.virtual_memory().total or 1
    while True:
        try:
            _refrescar_sensores()
            snap = []
            for p in psutil.process_iter(["name"]):
                try:
                    cpu = p.cpu_percent(None)
                    rss = p.memory_info().rss
                    nm  = p.info["name"] or "?"
                    snap.append((nm, cpu, rss))
                except Exception:
                    continue
            # Normaliza CPU dividiendo entre núcleos para obtener % global.
            # mem% se deriva de rss/total_ram (1 lectura) en vez de
            # memory_percent() por proceso (que re-lee el total cada vez).
            n_cpu = psutil.cpu_count() or 1
            top_cpu = sorted(snap, key=lambda x: x[1], reverse=True)[:5]
            top_mem = sorted(snap, key=lambda x: x[2], reverse=True)[:5]
            with _procs_lock:
                top_procs["cpu"] = [(n, c / n_cpu) for n, c, _ in top_cpu]
                top_procs["mem"] = [(n, r, r / total_ram * 100) for n, _, r in top_mem]
        except Exception as e:
            print(f"[SIS] top procs err: {e}", flush=True)
        time.sleep(6)


def _leer_sensores():
    """Devuelve el snapshot de sensores cacheado por tareas_fondo (cada 6s).
    Evita leer sysfs (~9ms) en cada render. El rebind de _sensores es
    atómico, así que el render ve siempre un dict completo."""
    return _sensores


def _temps_cores(s=None):
    """Devuelve (lista °C por core, critical°C) o ([], None) si no hay sensor."""
    if s is None:
        s = _leer_sensores()
    cores = s.get("coretemp") or []
    per_core = [e.current for e in cores if (e.label or "").startswith("Core")]
    crit = next((e.critical for e in cores if e.critical), None)
    return per_core, crit


def _temp_pkg(s=None):
    """Temperatura del package (Package id 0) o None."""
    if s is None:
        s = _leer_sensores()
    cores = s.get("coretemp") or []
    pkg = next((e for e in cores if (e.label or "").startswith("Package")), None)
    if pkg is None:
        return None, None
    return pkg.current, pkg.critical


# Fallbacks si el sensor no expone high/critical (algunos SoC no lo hacen).
TEMP_CRIT_FALLBACK = 100.0
TEMP_BAR_RANGO     = 35    # grados que abarca la barra por debajo del crítico


def _limites_termicos(s=None):
    """(high, crit) que reporta el propio coretemp, con fallback.

    Antes estaban cableados al Celeron J4105 (Tjmax 105). Derivarlos del sensor
    hace que la escala siga siendo correcta al cambiar de equipo: en el i7-9700T
    son high=92 y crit=100, que reproducen exactamente los mismos umbrales de
    color que la calibración vieja, pero con la barra llegando a llenarse."""
    if s is None:
        s = _leer_sensores()
    cores = s.get("coretemp") or []
    crit = next((e.critical for e in cores if e.critical), None) or TEMP_CRIT_FALLBACK
    high = next((e.high for e in cores if e.high), None) or (crit - 8)
    return high, crit


def _temp_color_pct(temp, crit=None):
    """% de llenado: los últimos TEMP_BAR_RANGO grados antes del crítico."""
    if crit is None:
        _high, crit = _limites_termicos()
    base = crit - TEMP_BAR_RANGO
    return min(100, max(0, (temp - base) / TEMP_BAR_RANGO * 100))


def temp_color(t, high=None, crit=None):
    """Color por temperatura absoluta, con los umbrales del propio sensor:
    verde hasta 10° antes del `high`, amarillo hasta `high`, ámbar hasta
    `critical` y rojo por encima (throttling)."""
    if high is None or crit is None:
        high, crit = _limites_termicos()
    if t <= high - 10: return "#33ff33"
    if t <= high:      return "#ddee33"
    if t <= crit:      return "#ffaa00"
    return "#ff3333"


def render_pagina_temps(deck, tam, nav_imgs):
    """Página TEMPS (id 16): detalle de sensores térmicos."""
    imgs = dict(nav_imgs)
    s = _leer_sensores()
    per_core, crit = _temps_cores(s)
    pkg, _ = _temp_pkg(s)

    high, _crit = _limites_termicos(s)

    # Fila 1 (8-15): un core por tecla, hasta 8.
    for i, t in enumerate(per_core[:8]):
        imgs[8+i] = dibujar_panel_metrica(deck, tam, f"Core {i}", f"{t:.0f}°",
                                            temp_color(t, high, crit),
                                            pct=_temp_color_pct(t, crit), sub="°C")

    # Fila 2: Package y crítico (que la fila 1 ya no puede alojar) + otros
    # sensores (acpitz / wifi / nvme...), reusando la lectura única.
    if pkg is not None:
        imgs[16] = dibujar_panel_metrica(deck, tam, "Package", f"{pkg:.0f}°",
                                           temp_color(pkg, high, crit),
                                           pct=_temp_color_pct(pkg, crit), sub="CPU")
    if crit:
        imgs[17] = dibujar_panel_metrica(deck, tam, "Crit", f"{crit:.0f}°", "#ff6666",
                                           sub="thr")
    extras = []
    for grupo, items in s.items():
        if grupo == "coretemp":
            continue
        for e in items:
            label = (e.label or grupo)[:9]
            extras.append((label, e.current, e.critical or crit))
    for i, (lbl, t, c) in enumerate(extras[:6]):
        imgs[18+i] = dibujar_panel_metrica(deck, tam, lbl, f"{t:.0f}°",
                                             temp_color(t, high, c),
                                             pct=_temp_color_pct(t, c), sub="°C")

    # Fila 3: ventiladores si los hay
    try:
        fans = psutil.sensors_fans() or {}
    except Exception:
        fans = {}
    fan_items = []
    for grupo, items in fans.items():
        for e in items:
            fan_items.append((((e.label or grupo)[:9]), e.current))
    for i, (lbl, rpm) in enumerate(fan_items[:8]):
        imgs[24+i] = dibujar_panel_metrica(deck, tam, lbl, f"{rpm}", "#33ccff", sub="rpm")
    return imgs


def render_pagina_net(deck, tam, nav_imgs):
    """Página NET (id 15): detalle throughput red — actual / pico / totales."""
    dn_kbps, up_kbps = _net_muestrear()
    cur = _net_contadores()
    pico_dn = _net_pico("down")
    pico_up = _net_pico("up")
    f_r = _fmt_caudal
    f_b = lambda v: (f"{v/(1024**3):.1f}G" if v >= 1024**3
                     else f"{v/(1024**2):.0f}M")

    imgs = dict(nav_imgs)
    # Fila 1: actuales + max
    imgs[8]  = dibujar_panel_metrica(deck, tam, "DOWN",  f_r(dn_kbps), "#cc66ff",
                                       pct=_net_pct(dn_kbps), sub="kbps")
    imgs[9]  = dibujar_panel_metrica(deck, tam, "UP",    f_r(up_kbps), "#0066ff",
                                       pct=_net_pct(up_kbps), sub="kbps")
    imgs[10] = dibujar_panel_metrica(deck, tam, "D max", f_r(pico_dn), "#9955cc",
                                       sub="pico 5m")
    imgs[11] = dibujar_panel_metrica(deck, tam, "U max", f_r(pico_up), "#003388",
                                       sub="pico 5m")
    # Fila 2: totales acumulados desde boot
    imgs[16] = dibujar_panel_metrica(deck, tam, "RX",    f_b(cur.bytes_recv), "#cc66ff",
                                       sub="total")
    imgs[17] = dibujar_panel_metrica(deck, tam, "TX",    f_b(cur.bytes_sent), "#0066ff",
                                       sub="total")
    imgs[18] = dibujar_panel_metrica(deck, tam, "Pkts R", f"{cur.packets_recv:,}".replace(",","."),
                                       "#cc66ff")
    imgs[19] = dibujar_panel_metrica(deck, tam, "Pkts T", f"{cur.packets_sent:,}".replace(",","."),
                                       "#0066ff")
    # Fila 3: errores / drops
    imgs[24] = dibujar_panel_metrica(deck, tam, "Err in",  str(cur.errin),
                                       "#ff6666" if cur.errin else "#33ff33")
    imgs[25] = dibujar_panel_metrica(deck, tam, "Err out", str(cur.errout),
                                       "#ff6666" if cur.errout else "#33ff33")
    imgs[26] = dibujar_panel_metrica(deck, tam, "Drop in",  str(cur.dropin),
                                       "#ff9933" if cur.dropin else "#33ff33")
    imgs[27] = dibujar_panel_metrica(deck, tam, "Drop out", str(cur.dropout),
                                       "#ff9933" if cur.dropout else "#33ff33")
    return imgs


def render_pagina_pings(deck, tam, nav_imgs, net_info, ping_history,
                          ping_pct_relativo_fn):
    """Página PINGS (id 14): detalle por target con actual / avg / max."""
    imgs = dict(nav_imgs)
    targets = [
        ("ping_gw",   "Gateway",  "#33ccff"),
        ("ping_dns1", "1.1.1.1",  "#33ccff"),
        ("ping_dns2", "8.8.8.8",  "#33ccff"),
        ("ping_api",  "API AWA",  "#ff9933"),
    ]
    # Cada target ocupa una columna (3 filas: actual, avg, max)
    for col, (cl, lb, base) in enumerate(targets):
        ms = net_info.get(cl, -1)
        hist = list(ping_history.get(cl, []) or [])
        if ms > 0:
            pct, color = ping_pct_relativo_fn(cl, ms)
            imgs[8+col]  = dibujar_panel_metrica(deck, tam, lb, f"{ms:.1f}",
                                                   color, pct=pct, sub="ms ahora")
        else:
            imgs[8+col]  = dibujar_panel_metrica(deck, tam, lb, "Err", "#666666", pct=0)
        if hist:
            avg = sum(hist) / len(hist)
            mx  = max(hist)
            mn  = min(hist)
            imgs[16+col] = dibujar_panel_metrica(deck, tam, "avg", f"{avg:.1f}",
                                                   base, sub="ms")
            imgs[24+col] = dibujar_panel_metrica(deck, tam, "max/min",
                                                   f"{mx:.0f} {mn:.0f}", base, sub="ms")
    # IPs — públicas y local en col 6,7 fila 1 (teclas 14, 15)
    imgs[14] = dibujar_panel_metrica(deck, tam, "Pública",
                                       _ip_2_lineas(net_info.get("ip_pub","")), "#33ccff")
    imgs[15] = dibujar_panel_metrica(deck, tam, "Local",
                                       _ip_2_lineas(net_info.get("ip_loc","")), "#33ccff")
    return imgs


def render_pagina_cores(deck, tam, nav_imgs):
    """Página CORES (id 13): un core por tecla + CPU total + top 5 CPU/MEM."""
    cores = psutil.cpu_percent(percpu=True)
    cpu_t = sum(cores) / max(1, len(cores))
    imgs = dict(nav_imgs)

    # Fila 1 (8-15): un core por tecla, hasta 8. CPU T se va a la 23 porque con
    # 8 cores la fila queda llena.
    for i, v in enumerate(cores[:8]):
        imgs[8+i] = dibujar_panel_metrica(deck, tam, f"C{i+1}", f"{int(v)}%",
                                            obtener_color_rango(v), pct=v)
    imgs[23] = dibujar_panel_metrica(deck, tam, "CPU T", f"{int(cpu_t)}%",
                                       obtener_color_rango(cpu_t), pct=cpu_t)

    # Fila 2: TOP CPU (16=label, 17-21=top5)
    with _procs_lock:
        cpu_list = list(top_procs["cpu"])
        mem_list = list(top_procs["mem"])
    imgs[16] = dibujar_panel_metrica(deck, tam, "TOP", "CPU", "#33ccff")
    for i in range(5):
        if i < len(cpu_list):
            nm, v = cpu_list[i]
            label = (nm[:9] + "…") if len(nm) > 10 else nm
            imgs[17+i] = dibujar_panel_metrica(deck, tam, label, f"{v:.1f}%",
                                                 obtener_color_rango(v), pct=min(100, v))

    # Fila 3: TOP MEM (24=label, 25-29=top5). Valor en GB/MB, barra usa %.
    imgs[24] = dibujar_panel_metrica(deck, tam, "TOP", "MEM", "#ff9933")
    for i in range(5):
        if i < len(mem_list):
            nm, rss, pct = mem_list[i]
            label = (nm[:9] + "…") if len(nm) > 10 else nm
            gb = rss / (1024**3)
            val = f"{gb:.2f}G" if gb >= 0.1 else f"{rss/(1024**2):.0f}M"
            imgs[25+i] = dibujar_panel_metrica(deck, tam, label, val,
                                                 obtener_color_rango(pct), pct=min(100, pct))
    return imgs


def render_pagina_sistema(deck, tam, nav_imgs, last_net, cur_net,
                            net_info, ping_pct_relativo_fn,
                            widgets_extras=None):
    """Render SIS. `widgets_extras`: dict {tecla: PIL} de plugins externos
    (clima, docker) — se mergea al final."""
    up_t  = (psutil.boot_time() and time.time() - psutil.boot_time()) or 0
    pct_u = (up_t % CICLO_UPTIME) / CICLO_UPTIME * 100
    cores = psutil.cpu_percent(percpu=True)
    ram   = psutil.virtual_memory().percent
    swp   = psutil.swap_memory().percent
    disk  = psutil.disk_usage('/')
    # El rate lo lleva _net_muestrear, que ignora los intervalos demasiado
    # cortos. Los contadores que pasa dashboard_pro (last_net/cur_net) se
    # mantienen en la firma por compatibilidad pero ya no se usan aquí.
    dn_kbps, up_kbps = _net_muestrear()
    f_r = _fmt_caudal

    imgs = dict(nav_imgs)
    imgs.update({
        # Fila 3: uptime, junto a GridW (la fila 1 la ocupan los 8 cores)
        28: dibujar_panel_metrica(deck, tam, "Uptime", _fmt_uptime(up_t), obtener_color_rango(pct_u), pct=pct_u),
        # Fila 2: RAM, SWAP, DISK
        16: dibujar_panel_metrica(deck, tam, "RAM",  f"{int(ram)}%", obtener_color_rango(ram), pct=ram),
        17: dibujar_panel_metrica(deck, tam, "SWAP", f"{int(swp)}%", obtener_color_rango(swp), pct=swp),
        18: dibujar_panel_metrica(deck, tam, "ROOT", f"{disk.free/(1024**3):.1f}G",
                                    obtener_color_rango(disk.percent), pct=disk.percent),
        # Fila 3: red consolidada en tecla 24 (DOWN+UP) → página NET
        # La etiqueta de cada barra ES el caudal: en un tile de 96 px el número
        # rinde más que una "D"/"U" que ya se deducen por posición y color.
        24: dibujar_panel_pings(deck, tam, "Net", [
            (f_r(dn_kbps), _net_pct(dn_kbps), "#cc66ff", ""),
            (f_r(up_kbps), _net_pct(up_kbps), "#0066ff", ""),
        ], color_marco="#33ccff"),
    })
    # Cores en grupos de 4 por tecla: 8 → 1-4, 9 → 5-8. Con 4 cores o menos el
    # segundo tile no se dibuja y la tecla queda libre.
    for i, base in enumerate(range(0, min(len(cores), 8), 4)):
        grupo = list(cores[base:base+4])
        avg_g = sum(grupo) / len(grupo)
        imgs[8+i] = dibujar_panel_cores(deck, tam, f"Cores {int(round(avg_g))}%",
                                        grupo, obtener_color_rango,
                                        etiqueta_base=base+1)

    # Temperatura por core, mismos grupos: 10 → 1-4, 11 → 5-8.
    temps_per_core, _crit = _temps_cores()
    if temps_per_core:
        high, crit = _limites_termicos()
        base_bar = crit - TEMP_BAR_RANGO
        # color_fn recibe el pct: lo invertimos a °C para usar temp_color absoluto.
        def _col(p):
            return temp_color(base_bar + (p/100) * TEMP_BAR_RANGO, high, crit)
        for i, base in enumerate(range(0, min(len(temps_per_core), 8), 4)):
            grupo = temps_per_core[base:base+4]
            pcts = [_temp_color_pct(t, crit) for t in grupo]
            avg = sum(grupo) / len(grupo)
            imgs[10+i] = dibujar_panel_cores(
                deck, tam, f"Temp {int(round(avg))}°",
                pcts, _col, etiqueta_base=base+1)
    # Pings gateway / 1.1.1.1 / 8.8.8.8 consolidados en tecla 28
    items = []
    for cl, lb in [("ping_gw","GW"), ("ping_dns1","CF"), ("ping_dns2","G")]:
        ms = net_info[cl]
        if ms > 0:
            pct, color = ping_pct_relativo_fn(cl, ms)
            items.append((lb, pct, color, f"{ms:.1f}"))
        else:
            items.append((lb, 0, "#666666", "Err"))
    imgs[25] = dibujar_panel_pings(deck, tam, "Pings", items)

    # Widgets inyectados por otros plugins (clima, docker)
    if widgets_extras:
        imgs.update(widgets_extras)
    return imgs
