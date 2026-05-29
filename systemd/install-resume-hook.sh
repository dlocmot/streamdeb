#!/usr/bin/env bash
# Instala el hook que reinicia streamdeb al salir de suspensión.
# Ejecutar como root:   sudo bash systemd/install-resume-hook.sh
# Validación verbose en cada paso; aborta al primer fallo.
set -uo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)/streamdeb-resume.service"
DST="/etc/systemd/system/streamdeb-resume.service"
USER_SVC="streamdeb.service"
RUN_USER="jfqp"

ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
fail() { printf '  \033[31m✗ %s\033[0m\n' "$1"; exit 1; }
step() { printf '\n\033[1m== %s ==\033[0m\n' "$1"; }

step "0. Pre-requisitos"
[ "$(id -u)" -eq 0 ] || fail "hay que correrlo como root (sudo bash $0)"
ok "ejecutando como root"
[ -f "$SRC" ] || fail "no encuentro el unit fuente: $SRC"
ok "unit fuente presente: $SRC"
command -v systemctl >/dev/null || fail "systemctl no está en PATH"
ok "systemctl disponible"
id "$RUN_USER" >/dev/null 2>&1 || fail "el usuario $RUN_USER no existe"
ok "usuario $RUN_USER existe (uid $(id -u "$RUN_USER"))"

step "1. Copiar unit a /etc/systemd/system/"
install -m 644 "$SRC" "$DST" || fail "no pude copiar a $DST"
[ -f "$DST" ] || fail "tras copiar, $DST no existe"
ok "copiado: $DST ($(stat -c '%a %s bytes' "$DST"))"

step "2. Recargar systemd"
systemctl daemon-reload || fail "daemon-reload falló"
ok "daemon-reload OK"

step "3. Habilitar el hook"
systemctl enable streamdeb-resume.service 2>&1 | sed 's/^/    /'
en="$(systemctl is-enabled streamdeb-resume.service 2>&1)"
[ "$en" = "enabled" ] || fail "is-enabled devolvió '$en' (esperaba 'enabled')"
ok "is-enabled = enabled"

step "4. Verificar symlinks en los targets de sleep"
found=0
for tgt in suspend hibernate hybrid-sleep suspend-then-hibernate; do
    if [ -L "/etc/systemd/system/${tgt}.target.wants/streamdeb-resume.service" ]; then
        ok "enganchado a ${tgt}.target"
        found=1
    fi
done
[ "$found" -eq 1 ] || fail "no se creó ningún symlink en *.target.wants (¿WantedBy?)"

step "5. Probar el comando de restart (en seco, ahora mismo)"
echo "    ejecutando: su $RUN_USER -c 'XDG_RUNTIME_DIR=/run/user/$(id -u "$RUN_USER") systemctl --user restart $USER_SVC'"
if su "$RUN_USER" -c "XDG_RUNTIME_DIR=/run/user/$(id -u "$RUN_USER") systemctl --user restart $USER_SVC"; then
    ok "restart del servicio de usuario OK"
    sleep 4
    act="$(su "$RUN_USER" -c "XDG_RUNTIME_DIR=/run/user/$(id -u "$RUN_USER") systemctl --user is-active $USER_SVC")"
    [ "$act" = "active" ] && ok "streamdeb.service is-active = active" \
                          || fail "tras restart, streamdeb.service quedó '$act'"
else
    fail "no pude reiniciar el servicio de usuario (revisar XDG_RUNTIME_DIR/linger)"
fi

printf '\n\033[1;32m✓ TODO OK\033[0m — el hook está instalado, habilitado y el restart funciona.\n'
printf 'Suspende y despierta la PC para probarlo en vivo.\n'
