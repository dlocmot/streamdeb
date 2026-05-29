#!/usr/bin/env bash
# Instala el hook de resume (reinicia streamdeb al salir de suspensión).
# Uso:  sudo bash systemd/install-resume-hook.sh
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
install -m 644 "$DIR/streamdeb-resume.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable streamdeb-resume.service
echo "OK — streamdeb-resume.service instalado y habilitado."
systemctl is-enabled streamdeb-resume.service
