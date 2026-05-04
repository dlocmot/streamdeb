#!/bin/bash
# Cambia entre perfil "main" (dashboard_pro) y "kiosk" (awa_kiosk) en dinamo.
# El nuevo servicio se lanza como transient (cgroup propio) para sobrevivir
# al cgroup-kill del actual al hacer stop.
set -e
target="${1:-}"
case "$target" in
  main)   to_start="streamdeb";        to_stop="streamdeb-kiosk" ;;
  kiosk)  to_start="streamdeb-kiosk";  to_stop="streamdeb" ;;
  *) echo "uso: $0 {main|kiosk}" >&2; exit 2 ;;
esac

# Servicio transient inmediato (cgroup independiente). Espera a que el otro
# muera limpio y libere el USB, luego arranca el nuevo.
systemd-run --user --no-block \
  --unit="streamdeb-switch-$(date +%s)" \
  --description="Switch a $to_start" \
  bash -c "sleep 1.5 && systemctl --user start $to_start"

exec systemctl --user stop "$to_stop"
