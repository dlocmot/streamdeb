#!/usr/bin/env bash
# Launcher de la GUI configuradora instalada en /usr/lib/streamdeb.
set -e
cd /usr/lib/streamdeb
exec /usr/bin/python3 -m streamdeb_config "$@"
