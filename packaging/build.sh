#!/usr/bin/env bash
# Construye streamdeb-config_<version>_all.deb desde el repo.
# Uso: ./packaging/build.sh [version]
#      sudo dpkg -i streamdeb-config_<version>_all.deb
set -euo pipefail

VERSION="${1:-1.0.0}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$(mktemp -d)/streamdeb-config_${VERSION}"
OUT="$REPO/streamdeb-config_${VERSION}_all.deb"

mkdir -p "$BUILD/DEBIAN" "$BUILD/usr/bin" "$BUILD/usr/lib/streamdeb" \
         "$BUILD/usr/share/applications" "$BUILD/usr/share/icons/hicolor/scalable/apps" \
         "$BUILD/usr/share/doc/streamdeb-config"

# Reemplaza la versión en el control si difiere
sed "s/^Version: .*/Version: ${VERSION}/" "$REPO/packaging/control" \
    > "$BUILD/DEBIAN/control"

install -m 755 "$REPO/packaging/launcher.sh" "$BUILD/usr/bin/streamdeb-config"
install -m 644 "$REPO/packaging/streamdeb-config.desktop" \
               "$BUILD/usr/share/applications/streamdeb-config.desktop"
install -m 644 "$REPO/packaging/icon.svg" \
               "$BUILD/usr/share/icons/hicolor/scalable/apps/streamdeb-config.svg"

# Código (la detección de decks está inline en streamdeb_config/wizard.py;
# ya no se empaqueta bin/detect-decks).
for d in core plugins streamdeb_config config fonts; do
    cp -r "$REPO/$d" "$BUILD/usr/lib/streamdeb/"
done

# Limpia caches
find "$BUILD/usr/lib/streamdeb" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
find "$BUILD/usr/lib/streamdeb" -name "*.pyc" -delete

# Docs
install -m 644 "$REPO/README.md" \
               "$BUILD/usr/share/doc/streamdeb-config/README.md"
install -m 644 "$REPO/LICENSE" \
               "$BUILD/usr/share/doc/streamdeb-config/copyright"

dpkg-deb --root-owner-group --build "$BUILD" "$OUT"
echo
echo "✓ Built: $OUT"
echo "  sudo dpkg -i $(basename "$OUT")"
echo "  sudo apt -f install   # resuelve deps si falta algo"
