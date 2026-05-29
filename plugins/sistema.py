"""Plugin SIS (página 1): dashboard de sistema con CPU/RAM/red/pings.
Inyecta widgets de clima (20-23) y docker entry (31).
Subpágina CORES (id 13): detalle C1-C4 + top 5 CPU + top 5 MEM."""
import time
import threading
import psutil

from core.config import CICLO_UPTIME
from core.helpers import _fmt_tiempo, _ip_2_lineas, obtener_color_rango
from core.widgets import dibujar_panel_metrica, dibujar_panel_cores, dibujar_panel_pings


# Highwater de throughput de red para escalar las barras de DOWN/UP.
max_visto_down = 1024.0
max_visto_up   = 1024.0


# Top procesos (mutado por tareas_fondo). Cada item: (nombre, valor_pct).
top_procs = {"cpu": [], "mem": []}
_procs_lock = threading.Lock()


def tareas_fondo():
    """Polling cada 3s de top 5 procesos por CPU y por MEM.
    cpu_percent(None) requiere priming: la primera pasada inicializa
    contadores y descarta resultados; las siguientes son válidas."""
    # Priming
    for p in psutil.process_iter():
        try: p.cpu_percent(None)
        except Exception: pass
    time.sleep(1)
    total_ram = psutil.virtual_memory().total or 1
    while True:
        try:
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
    """Lectura única de sensores térmicos; {} si no hay/falla.
    sensors_temperatures() lee sysfs en cada llamada — leer una vez por
    render y pasar el dict a los helpers evita 2-3 lecturas redundantes."""
    try:
        return psutil.sensors_temperatures()
    except Exception:
        return {}


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


TEMP_BAR_MIN = 65   # base de la barra (todo abajo de aquí queda vacío)
TEMP_BAR_MAX = 105  # tope de la barra (Tjmax del J4105)


def _temp_color_pct(temp, crit=None):
    """% de llenado de la barra: rango [TEMP_BAR_MIN .. TEMP_BAR_MAX] → 0-100.
    Argumento `crit` se ignora (mantenido por compat); usamos límites fijos
    para que la franja útil (65-105°C) ocupe toda la barra."""
    rng = TEMP_BAR_MAX - TEMP_BAR_MIN
    return min(100, max(0, (temp - TEMP_BAR_MIN) / rng * 100))


def temp_color(t):
    """Color por temperatura absoluta °C, calibrado para Intel Celeron J4105
    (SoC fanless, Tjmax 105°C). Validado con stress test 60s 4 cores:
      - idle real medido: 76-79°C
      - stress sostenido: ramp a 86→93°C (sin throttle en 60s)
      - cooldown: lento, queda 80-85°C
    Por eso la franja verde llega hasta 82°C (idle + margen).
    ≤82 verde · 82-92 amarillo · 92-100 ámbar · >100 rojo (throttling)."""
    if t <= 82:  return "#33ff33"
    if t <= 92:  return "#ddee33"
    if t <= 100: return "#ffaa00"
    return "#ff3333"


def render_pagina_temps(deck, tam, nav_imgs):
    """Página TEMPS (id 16): detalle de sensores térmicos."""
    imgs = dict(nav_imgs)
    s = _leer_sensores()
    per_core, crit = _temps_cores(s)
    pkg, _ = _temp_pkg(s)

    # Fila 1: Package + 4 cores. Barra escala vs critical, color absoluto °C.
    if pkg is not None:
        imgs[8] = dibujar_panel_metrica(deck, tam, "Package", f"{pkg:.0f}°",
                                          temp_color(pkg),
                                          pct=_temp_color_pct(pkg, crit), sub="CPU")
    for i, t in enumerate(per_core[:4]):
        imgs[9+i] = dibujar_panel_metrica(deck, tam, f"Core {i}", f"{t:.0f}°",
                                            temp_color(t),
                                            pct=_temp_color_pct(t, crit), sub="°C")
    if crit:
        imgs[15] = dibujar_panel_metrica(deck, tam, "Crit", f"{crit:.0f}°", "#ff6666",
                                           sub="thr")

    # Fila 2: otros sensores (acpitz / wifi / nvme...) — reusa la lectura única
    extras = []
    for grupo, items in s.items():
        if grupo == "coretemp":
            continue
        for e in items:
            label = (e.label or grupo)[:9]
            extras.append((label, e.current, e.critical or 100))
    for i, (lbl, t, c) in enumerate(extras[:8]):
        imgs[16+i] = dibujar_panel_metrica(deck, tam, lbl, f"{t:.0f}°",
                                             temp_color(t),
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


_net_last = {"sample": None, "ts": 0.0}


def render_pagina_net(deck, tam, nav_imgs):
    """Página NET (id 15): detalle throughput red — actual / max / totales."""
    global max_visto_down, max_visto_up
    cur = psutil.net_io_counters()
    now = time.time()
    prev = _net_last["sample"]
    prev_t = _net_last["ts"]
    _net_last["sample"] = cur
    _net_last["ts"] = now

    dn_kbps = up_kbps = 0.0
    if prev is not None and now > prev_t:
        dt = now - prev_t
        dn_kbps = ((cur.bytes_recv - prev.bytes_recv) * 8) / 1024 / dt
        up_kbps = ((cur.bytes_sent - prev.bytes_sent) * 8) / 1024 / dt
    max_visto_down = max(max_visto_down, dn_kbps)
    max_visto_up   = max(max_visto_up,   up_kbps)
    f_r = lambda v: f"{int(v/1000)}Mb" if v >= 1000 else f"{int(v)}Kb"
    f_b = lambda v: (f"{v/(1024**3):.1f}G" if v >= 1024**3
                     else f"{v/(1024**2):.0f}M")

    imgs = dict(nav_imgs)
    # Fila 1: actuales + max
    imgs[8]  = dibujar_panel_metrica(deck, tam, "DOWN",  f_r(dn_kbps), "#33ccff",
                                       pct=(dn_kbps/max_visto_down)*100, sub="kbps")
    imgs[9]  = dibujar_panel_metrica(deck, tam, "UP",    f_r(up_kbps), "#0066ff",
                                       pct=(up_kbps/max_visto_up)*100, sub="kbps")
    imgs[10] = dibujar_panel_metrica(deck, tam, "D max", f_r(max_visto_down), "#3399cc",
                                       sub="pico")
    imgs[11] = dibujar_panel_metrica(deck, tam, "U max", f_r(max_visto_up), "#003388",
                                       sub="pico")
    # Fila 2: totales acumulados desde boot
    imgs[16] = dibujar_panel_metrica(deck, tam, "RX",    f_b(cur.bytes_recv), "#33ccff",
                                       sub="total")
    imgs[17] = dibujar_panel_metrica(deck, tam, "TX",    f_b(cur.bytes_sent), "#0066ff",
                                       sub="total")
    imgs[18] = dibujar_panel_metrica(deck, tam, "Pkts R", f"{cur.packets_recv:,}".replace(",","."),
                                       "#33ccff")
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
    """Página CORES (id 13): C1-C4 detalle + CPU total + top 5 CPU + top 5 MEM."""
    cores = psutil.cpu_percent(percpu=True)
    cpu_t = sum(cores) / max(1, len(cores))
    imgs = dict(nav_imgs)

    # Fila 1: C1..C4 (8-11), CPU T (15)
    for i, v in enumerate(cores[:4]):
        imgs[8+i] = dibujar_panel_metrica(deck, tam, f"C{i+1}", f"{int(v)}%",
                                            obtener_color_rango(v), pct=v)
    imgs[15] = dibujar_panel_metrica(deck, tam, "CPU T", f"{int(cpu_t)}%",
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
    global max_visto_down, max_visto_up
    up_t  = (psutil.boot_time() and time.time() - psutil.boot_time()) or 0
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
        # Fila 1: uptime
        8:  dibujar_panel_metrica(deck, tam, "Uptime", _fmt_tiempo(up_t), obtener_color_rango(pct_u), pct=pct_u),
        # Fila 2: RAM, SWAP, DISK
        16: dibujar_panel_metrica(deck, tam, "RAM",  f"{int(ram)}%", obtener_color_rango(ram), pct=ram),
        17: dibujar_panel_metrica(deck, tam, "SWAP", f"{int(swp)}%", obtener_color_rango(swp), pct=swp),
        18: dibujar_panel_metrica(deck, tam, "ROOT", f"{disk.free/(1024**3):.1f}G",
                                    obtener_color_rango(disk.percent), pct=disk.percent),
        # Fila 3: red consolidada en tecla 24 (DOWN+UP) → página NET
        24: dibujar_panel_pings(deck, tam, "Net", [
            ("D", (dn_kbps/max_visto_down)*100, "#33ccff", f_r(dn_kbps)),
            ("U", (up_kbps/max_visto_up)*100,   "#0066ff", f_r(up_kbps)),
        ]),
    })
    # Cores 1..4 consolidados en una tecla con barras verticales (CPU total en título)
    imgs[9] = dibujar_panel_cores(deck, tam, f"Cores {int(cpu_t)}%",
                                    list(cores[:4]), obtener_color_rango)
    # Temperatura por core (tecla 10). Barra escala [65..105]→0..100, color °C.
    temps_per_core, _crit = _temps_cores()
    if temps_per_core:
        pcts = [_temp_color_pct(t) for t in temps_per_core[:4]]
        # color_fn recibe el pct: lo invertimos a °C para usar temp_color absoluto.
        def _col(p):
            t = TEMP_BAR_MIN + (p/100) * (TEMP_BAR_MAX - TEMP_BAR_MIN)
            return temp_color(t)
        avg = sum(temps_per_core[:4]) / len(temps_per_core[:4])
        imgs[10] = dibujar_panel_cores(deck, tam, f"Temp {int(round(avg))}°",
                                          pcts, _col)
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
