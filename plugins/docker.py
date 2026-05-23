"""Plugin DOCKER (página 10): lista y control de contenedores + daemon panel.

Layout (8x4):
  Row 0 (0-7):   nav (compartida)
  Row 1 (8-15):  hasta 8 containers — label=nombre, sub=CPU%
  Row 2 (16-23): aligned, RAM% + uptime del container en la misma columna
  Row 3 (24-31): acciones daemon
                 24:Imgs  25:Disco  26:Prune  27:Pull
                 28:Stop all  29:Start all  30:← pg  31:pg →

Widget en SIS tecla 26 muestra running/total y abre la página.
"""
import subprocess
import threading
import time

from core.widgets import (
    dibujar_panel_metrica, dibujar_panel_info, dibujar_panel_2lineas,
)


# Estado live (mutado por threads)
docker_info = {
    "available": False,
    "running":   0,
    "containers": [],   # [(name, is_running, image, status_str)]
    "stats":     {},    # name → {"cpu":float, "mem_pct":float, "mem_mb":float}
    "images":    0,     # # de imágenes
    "disk_used": 0.0,   # GB
    "msg":       "",    # último resultado de prune/pull para feedback
    "msg_until": 0.0,   # epoch hasta cuándo mostrar msg
}
_lock = threading.Lock()
_page = 0  # paginación cuando hay >8 containers

TECLA_SIS = 26
CONTAINERS_POR_PAGINA = 8


def _docker_ok(rc):
    return rc == 0


def tareas_fondo():
    """Polling de `docker ps -a` cada 10s + métricas globales cada 60s."""
    last_globals = 0.0
    while True:
        try:
            res = subprocess.run(
                ["docker", "ps", "-a", "--format",
                 "{{.Names}}\t{{.State}}\t{{.Image}}\t{{.Status}}"],
                capture_output=True, text=True, timeout=5,
            )
            if _docker_ok(res.returncode):
                containers = []
                running = 0
                for line in res.stdout.strip().splitlines():
                    parts = line.split("\t")
                    if len(parts) >= 2:
                        name, st = parts[0], parts[1]
                        image  = parts[2] if len(parts) > 2 else ""
                        status = parts[3] if len(parts) > 3 else ""
                        is_run = (st == "running")
                        if is_run:
                            running += 1
                        containers.append((name, is_run, image, status))
                with _lock:
                    docker_info["available"]  = True
                    docker_info["running"]    = running
                    docker_info["containers"] = containers
            else:
                with _lock:
                    docker_info["available"] = False
        except FileNotFoundError:
            with _lock:
                docker_info["available"] = False
        except Exception as e:
            with _lock:
                docker_info["available"] = False
            print(f"[DOCKER] error: {e}", flush=True)

        # Métricas globales (imágenes, disco) cada 60s — `system df` es lento
        ahora = time.time()
        if ahora - last_globals > 60:
            last_globals = ahora
            try:
                im = subprocess.run(["docker", "images", "-q"],
                                    capture_output=True, text=True, timeout=5)
                with _lock:
                    docker_info["images"] = len([l for l in im.stdout.splitlines() if l])
            except Exception: pass
            try:
                df = subprocess.run(
                    ["docker", "system", "df", "--format", "{{.Type}}\t{{.Size}}"],
                    capture_output=True, text=True, timeout=8,
                )
                total_gb = 0.0
                for ln in df.stdout.strip().splitlines():
                    _, size = (ln.split("\t") + [""])[:2]
                    total_gb += _size_to_gb(size)
                with _lock:
                    docker_info["disk_used"] = total_gb
            except Exception: pass

        time.sleep(10)


def tareas_stats():
    """Polling de `docker stats --no-stream` cada 15s (CPU/RAM por container)."""
    while True:
        try:
            res = subprocess.run(
                ["docker", "stats", "--no-stream",
                 "--format", "{{.Name}}\t{{.CPUPerc}}\t{{.MemPerc}}\t{{.MemUsage}}"],
                capture_output=True, text=True, timeout=12,
            )
            if _docker_ok(res.returncode):
                stats = {}
                for ln in res.stdout.strip().splitlines():
                    parts = ln.split("\t")
                    if len(parts) < 4:
                        continue
                    name, cpu_s, mem_s, usage = parts[0], parts[1], parts[2], parts[3]
                    cpu = _pct(cpu_s)
                    mem_pct = _pct(mem_s)
                    mem_mb  = _mem_used_mb(usage)
                    stats[name] = {"cpu": cpu, "mem_pct": mem_pct, "mem_mb": mem_mb}
                with _lock:
                    docker_info["stats"] = stats
        except FileNotFoundError:
            pass
        except subprocess.TimeoutExpired:
            print("[DOCKER] stats timeout", flush=True)
        except Exception as e:
            print(f"[DOCKER] stats error: {e}", flush=True)
        time.sleep(15)


def _pct(s):
    """'12.34%' → 12.34, vacío/error → 0.0"""
    s = (s or "").strip().rstrip("%").replace(",", ".")
    try: return float(s)
    except Exception: return 0.0


def _mem_used_mb(usage):
    """'123.4MiB / 1.95GiB' → 123.4 (MB del lado izq)"""
    try:
        left = usage.split("/")[0].strip()
        return _to_mb(left)
    except Exception:
        return 0.0


def _to_mb(s):
    s = s.strip()
    n = "".join(c for c in s if c.isdigit() or c in ".,").replace(",", ".")
    v = float(n) if n else 0.0
    su = s[len(n):].strip().lower()
    if   su.startswith("k"): v /= 1024.0
    elif su.startswith("g"): v *= 1024.0
    elif su.startswith("t"): v *= 1024.0 * 1024.0
    return v


def _size_to_gb(s):
    """'2.55GB' → 2.55, '170MB' → 0.17, 'B'/'kB' → ~0"""
    s = s.strip()
    n = "".join(c for c in s if c.isdigit() or c in ".,").replace(",", ".")
    v = float(n) if n else 0.0
    su = s[len(n):].strip().lower()
    if   su.startswith("k"): v /= 1024.0 * 1024.0
    elif su.startswith("m"): v /= 1024.0
    elif su.startswith("t"): v *= 1024.0
    elif su.startswith("g"): pass
    else:                    v /= 1024.0 * 1024.0 * 1024.0
    return v


def _fmt_uptime(status):
    """'Up 9 minutes (healthy)' → '9m'. 'Exited (0) 2 hours ago' → '2h'."""
    s = status or ""
    if s.startswith("Up "):
        parts = s.split()
        if len(parts) >= 3:
            n, unit = parts[1], parts[2]
            u = unit[0].lower()
            return f"{n}{u if u in 'smhd' else ''}"
    if "Exited" in s:
        return "off"
    if "Created" in s:
        return "new"
    return "?"


def _set_msg(txt, secs=5):
    with _lock:
        docker_info["msg"]       = txt
        docker_info["msg_until"] = time.time() + secs


def widget_para_sistema(deck, tam):
    """Tile entry en SIS (tecla 26). Tap → abre página DOCKER."""
    with _lock:
        avail = docker_info["available"]
        run   = docker_info["running"]
        tot   = len(docker_info["containers"])
    if avail:
        d_color = "#3399ff" if run > 0 else "#666666"
        d_val   = f"{run}/{tot}"
    else:
        d_color = "#444444"
        d_val   = "off"
    return {TECLA_SIS: dibujar_panel_metrica(deck, tam, "Docker", d_val, d_color)}


def render_pagina_docker(deck, tam, nav_imgs):
    """Render página 10."""
    imgs = dict(nav_imgs)
    with _lock:
        containers = list(docker_info["containers"])
        stats      = dict(docker_info["stats"])
        imgs_n     = docker_info["images"]
        disk_gb    = docker_info["disk_used"]
        msg        = docker_info["msg"] if time.time() < docker_info["msg_until"] else ""

    total = len(containers)
    n_pag = max(1, (total + CONTAINERS_POR_PAGINA - 1) // CONTAINERS_POR_PAGINA)
    page = max(0, min(_page, n_pag - 1))
    start = page * CONTAINERS_POR_PAGINA
    chunk = containers[start:start + CONTAINERS_POR_PAGINA]

    # Row 1: container (key 8..15). Row 2: stats alineado (key 16..23).
    for i, (name, running, _img, status) in enumerate(chunk):
        col = i  # 0..7
        tecla_top = 8 + col
        tecla_bot = 16 + col

        st = stats.get(name, {})
        cpu = st.get("cpu", 0.0)
        mem_pct = st.get("mem_pct", 0.0)
        mem_mb  = st.get("mem_mb", 0.0)

        color = "#33dd66" if running else "#888888"
        label = (name[:10] + "…") if len(name) > 11 else name
        if running:
            sub = f"{cpu:.0f}% CPU" if cpu > 0 else "ON"
        else:
            sub = _fmt_uptime(status)
        imgs[tecla_top] = dibujar_panel_metrica(deck, tam, label, sub, color)

        if running:
            mem_val = f"{int(mem_mb)}M" if mem_mb < 1024 else f"{mem_mb/1024:.1f}G"
            up_val  = _fmt_uptime(status)
            mem_col = "#ff9933" if mem_pct > 80 else "#33ccff"
            imgs[tecla_bot] = dibujar_panel_2lineas(
                deck, tam, "RAM", f"{mem_val} {up_val}", mem_col,
            )
        else:
            imgs[tecla_bot] = dibujar_panel_info(deck, tam, "—", "stopped", "#444444")

    # Row 3: daemon actions
    img_col = "#33ccff" if imgs_n else "#666666"
    disk_col = "#ff9933" if disk_gb > 20 else "#33ccff"
    imgs[24] = dibujar_panel_info(deck, tam, "Imgs",  str(imgs_n), img_col)
    imgs[25] = dibujar_panel_info(deck, tam, "Disco", f"{disk_gb:.1f}G", disk_col)
    imgs[26] = dibujar_panel_info(deck, tam, "Prune", msg if msg.startswith("prune") else "tap", "#ffaa33")
    imgs[27] = dibujar_panel_info(deck, tam, "Pull",  msg if msg.startswith("pull")  else "all", "#cc66ff")
    imgs[28] = dibujar_panel_info(deck, tam, "Stop",  "all", "#ff5544")
    imgs[29] = dibujar_panel_info(deck, tam, "Start", "all", "#33dd66")
    # Paginación: muestra sólo si hay >1 página
    if n_pag > 1:
        imgs[30] = dibujar_panel_info(deck, tam, "← Pg",
                                       f"{page+1}/{n_pag}", "#aaaaaa")
        imgs[31] = dibujar_panel_info(deck, tam, "Pg →",
                                       f"{page+1}/{n_pag}", "#aaaaaa")
    else:
        imgs[30] = dibujar_panel_info(deck, tam, "Pg", "1/1", "#444444")
        imgs[31] = dibujar_panel_info(deck, tam, "Pg", "1/1", "#444444")
    return imgs


def _run_async(cmd, label):
    """Ejecuta comando docker en thread y publica resultado en msg."""
    def _go():
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            ok = (r.returncode == 0)
            _set_msg(f"{label}:{'OK' if ok else 'err'}")
            print(f"[DOCKER] {label} rc={r.returncode}", flush=True)
        except Exception as e:
            _set_msg(f"{label}:err")
            print(f"[DOCKER] {label} exc: {e}", flush=True)
    threading.Thread(target=_go, daemon=True).start()


def on_press_dentro_pagina(tecla):
    """Página 10: tap toggle start/stop por container, row 3 = acciones daemon."""
    global _page
    with _lock:
        containers = list(docker_info["containers"])
    total = len(containers)
    n_pag = max(1, (total + CONTAINERS_POR_PAGINA - 1) // CONTAINERS_POR_PAGINA)

    # Row 1 / Row 2 → mismo container (idx por columna)
    if 8 <= tecla <= 23:
        col = (tecla - 8) % 8
        idx = _page * CONTAINERS_POR_PAGINA + col
        if not (0 <= idx < total):
            return False
        name, running, _img, _st = containers[idx]
        cmd = "stop" if running else "start"
        _run_async(["docker", cmd, name], f"{cmd[:4]}:{name[:8]}")
        return True

    # Row 3 — acciones daemon
    if tecla == 26:   # Prune
        _set_msg("prune:run", secs=120)
        _run_async(["docker", "system", "prune", "-f"], "prune")
        return True
    if tecla == 27:   # Pull all (re-pull de cada imagen única en uso)
        with _lock:
            imgs = sorted({c[2] for c in docker_info["containers"] if c[2]})
        if imgs:
            _set_msg(f"pull:{len(imgs)}", secs=300)
            def _pull():
                for i in imgs:
                    subprocess.run(["docker", "pull", i],
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, timeout=300)
                _set_msg("pull:OK")
            threading.Thread(target=_pull, daemon=True).start()
        return True
    if tecla == 28:   # Stop all running
        with _lock:
            running = [c[0] for c in docker_info["containers"] if c[1]]
        if running:
            _run_async(["docker", "stop"] + running, f"stop:{len(running)}")
        return True
    if tecla == 29:   # Start all stopped
        with _lock:
            stopped = [c[0] for c in docker_info["containers"] if not c[1]]
        if stopped:
            _run_async(["docker", "start"] + stopped, f"start:{len(stopped)}")
        return True
    if tecla == 30:   # ← pg
        if n_pag > 1:
            _page = (_page - 1) % n_pag
        return True
    if tecla == 31:   # pg →
        if n_pag > 1:
            _page = (_page + 1) % n_pag
        return True

    return False
