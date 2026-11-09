#!/usr/bin/env bash
# Сборка .deb-пакета Kerio VPN GUI.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-$(sed -n 's/^APP_VERSION = "\(.*\)"$/\1/p' "$ROOT/kerio_vpn_gui/core.py")}"
if [ -z "$VERSION" ]; then
    echo "Не удалось определить версию приложения" >&2
    exit 1
fi
if ! command -v dpkg-deb >/dev/null 2>&1; then
    echo "Не найден dpkg-deb. Установите пакет dpkg." >&2
    exit 1
fi

DEB_VERSION="${VERSION}-1"
PACKAGE="kerio-vpn-gui"
DIST="$ROOT/dist"
STAGE="$DIST/deb-build"
DEB="$DIST/${PACKAGE}_${DEB_VERSION}_all.deb"

rm -rf "$STAGE"
mkdir -p \
    "$STAGE/DEBIAN" \
    "$STAGE/usr/bin" \
    "$STAGE/usr/lib/kerio-vpn-gui" \
    "$STAGE/usr/share/kerio-vpn-gui" \
    "$STAGE/usr/share/applications" \
    "$STAGE/usr/share/icons/hicolor/scalable/apps" \
    "$STAGE/usr/share/doc/kerio-vpn-gui"

cp -a "$ROOT/kerio_vpn_gui" "$STAGE/usr/share/kerio-vpn-gui/"
find "$STAGE/usr/share/kerio-vpn-gui" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$STAGE/usr/share/kerio-vpn-gui" -type f -name '*.pyc' -delete

install -m 755 "$ROOT/helper/kvc-helper" "$STAGE/usr/lib/kerio-vpn-gui/kvc-helper"
install -m 644 "$ROOT/assets/kerio-vpn-gui.svg" \
    "$STAGE/usr/share/icons/hicolor/scalable/apps/kerio-vpn-gui.svg"
install -m 644 "$ROOT/README.md" "$STAGE/usr/share/doc/kerio-vpn-gui/README.md"

cat >"$STAGE/usr/bin/kerio-vpn-gui" <<'EOF'
#!/bin/bash
export PYTHONPATH="/usr/share/kerio-vpn-gui${PYTHONPATH:+:$PYTHONPATH}"
export KERIO_GUI_HELPER="/usr/lib/kerio-vpn-gui/kvc-helper"
exec -a kerio-vpn-gui python3 -m kerio_vpn_gui "$@"
EOF
chmod 755 "$STAGE/usr/bin/kerio-vpn-gui"

cat >"$STAGE/usr/share/applications/kerio-vpn-gui.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Kerio VPN
Comment=Управление подключениями Kerio Control VPN
Exec=/usr/bin/kerio-vpn-gui
Icon=kerio-vpn-gui
Terminal=false
Categories=Network;VPN;
Keywords=kerio;vpn;control;
StartupNotify=true
StartupWMClass=kerio-vpn-gui
EOF

cat >"$STAGE/DEBIAN/control" <<EOF
Package: $PACKAGE
Version: $DEB_VERSION
Section: net
Priority: optional
Architecture: all
Depends: python3 (>= 3.9), python3-pyqt5, pkexec | policykit-1, openssl, iproute2, procps, libglib2.0-bin
Recommends: kerio-control-vpnclient
Maintainer: kostya4000 <kostya4000@users.noreply.github.com>
Installed-Size: $(du -sk "$STAGE" | cut -f1)
Homepage: https://github.com/kostya4000/kerioVPN_client
Description: GUI for Kerio Control VPN Client
 Graphical application for managing Kerio Control VPN client profiles,
 importing existing .conf/.sh files, connecting through pkexec/polkit,
 viewing logs, switching light/dark themes and changing the font size.
EOF

cat >"$STAGE/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor >/dev/null 2>&1 || true
fi
exit 0
EOF

cat >"$STAGE/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "purge" ]; then
    rm -f /etc/polkit-1/rules.d/49-kerio-vpn-gui.rules
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor >/dev/null 2>&1 || true
fi
exit 0
EOF

chmod 755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/postrm"

# Нормализуем права: каталоги 755, файлы 644, исполняемые — 755.
find "$STAGE/usr" -type d -exec chmod 755 {} +
find "$STAGE/usr" -type f -exec chmod 644 {} +
chmod 755 "$STAGE/usr/bin/kerio-vpn-gui" "$STAGE/usr/lib/kerio-vpn-gui/kvc-helper"

(
    cd "$STAGE"
    find usr -type f -print0 | sort -z | xargs -0 md5sum > DEBIAN/md5sums
)

dpkg-deb --build --root-owner-group "$STAGE" "$DEB" >/dev/null
rm -rf "$STAGE"
echo "$DEB"
