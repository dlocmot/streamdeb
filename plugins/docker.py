"""Plugin DOCKER (página 10): lista y control de contenedores.
Widget en SIS tecla 26 muestra running/total y abre la página."""
import subprocess
import time

from core.widgets import dibujar_panel_metrica


# Estado live del daemon docker (mutado por tareas_fondo)
docker_info = {"available": False, "running": 0, "containers": []}
TECLA_SIS = 26  # entry button en SIS que abre la página DOCKER


def tareas_fondo():
    """Polling cada 10s de `docker ps -a`. Si docker no está, queda available=False."""
    while True:
        try:
            res = subprocess.run(
                ["docker", "ps", "-a", "--format", "{{.Names}}\t{{.State}}\t{{.Image}}"],
                capture_output=True, text=True, timeout=3,
            )
            if res.returncode == 0:
                containers = []
                running = 0
                for line in res.stdout.strip().splitlines():
                    parts = line.split("\t")
                    if len(parts) >= 2:
                        name, st = parts[0], parts[1]
                        image = parts[2] if len(parts) > 2 else ""
                        is_run = (st == "running")
                        if is_run:
                            running += 1
                        containers.append((name, is_run, image))
                docker_info["available"]  = True
                docker_info["running"]    = running
                docker_info["containers"] = containers
            else:
                docker_info["available"] = False
        except FileNotFoundError:
            docker_info["available"] = False
        except Exception as e:
            docker_info["available"] = False
            print(f"[DOCKER] error: {e}", flush=True)
        time.sleep(10)


def widget_para_sistema(deck, tam):
    """Tile entry en SIS (tecla 31). Tap → abre página DOCKER."""
    if docker_info["available"]:
        d_color = "#3399ff" if docker_info["running"] > 0 else "#666666"
        d_val   = f"{docker_info['running']}/{len(docker_info['containers'])}"
    else:
        d_color = "#444444"
        d_val   = "off"
    return {TECLA_SIS: dibujar_panel_metrica(deck, tam, "Docker", d_val, d_color)}


def render_pagina_docker(deck, tam, nav_imgs):
    """Página DOCKER (id 10): hasta 24 contenedores en filas 1-3 (8 cols × 3 filas).
    Tap en cada uno alterna start/stop."""
    imgs = dict(nav_imgs)
    containers = docker_info["containers"][:24]
    for i, (name, running, _img) in enumerate(containers):
        tecla = 8 + i
        color = "#33dd66" if running else "#888888"
        label = (name[:10] + "…") if len(name) > 11 else name
        sub   = "ON" if running else "off"
        imgs[tecla] = dibujar_panel_metrica(deck, tam, label, sub, color)
    return imgs


def on_press_dentro_pagina(tecla):
    """En página DOCKER: tap → toggle start/stop del contenedor en esa tecla."""
    idx = tecla - 8
    if not (0 <= idx < len(docker_info["containers"])):
        return False
    name, running, _ = docker_info["containers"][idx]
    cmd = "stop" if running else "start"
    try:
        subprocess.run(["docker", cmd, name], timeout=10,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[DOCKER] {cmd} {name}", flush=True)
    except Exception as e:
        print(f"[DOCKER] error {cmd} {name}: {e}", flush=True)
    return True
