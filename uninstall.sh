#!/usr/bin/env bash
# Удаление Kerio VPN GUI.
set -euo pipefail

PREFIX="${PREFIX:-$HOME/.local}"
APP_DIR="$PREFIX/share/kerio-vpn-gui"
BIN="$PREFIX/bin/kerio-vpn-gui"
ICON="$PREFIX/share/icons/hicolor/scalable/apps/kerio-vpn-gui.svg"
DESKTOP="$PREFIX/share/applications/kerio-vpn-gui.desktop"
HELPER_DIR="/usr/local/lib/kerio-vpn-gui"
HELPER="$HELPER_DIR/kvc-helper"
CONFIG_DIR="$HOME/.config/kerio-vpn-gui"
AUTOSTART="$HOME/.config/autostart/kerio-vpn-gui.desktop"

if [ "$(id -u)" -eq 0 ]; then
    SUDO=""
else
    SUDO="sudo"
fi

echo "==> Удаление файлов приложения"
rm -rf "$APP_DIR"
rm -f "$BIN" "$ICON" "$DESKTOP" "$AUTOSTART"

if [ "${1:-}" = "--purge" ]; then
    echo "==> Удаление профилей и настроек"
    rm -rf "$CONFIG_DIR"
fi

if [ -x "$HELPER" ]; then
    echo "==> Удаление служебного помощника (нужен пароль администратора)"
    if [ -z "$SUDO" ] || command -v sudo >/dev/null 2>&1; then
        $SUDO rm -f "$HELPER" || echo "Не удалось удалить $HELPER" >&2
        $SUDO rmdir "$HELPER_DIR" 2>/dev/null || true
    else
        echo "Удалите вручную: sudo rm -f '$HELPER'" >&2
    fi
fi

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$PREFIX/share/applications" >/dev/null 2>&1 || true
fi

echo
echo "Готово."
if [ "${1:-}" != "--purge" ]; then
    echo "Профили сохранены в $CONFIG_DIR (для удаления: ./uninstall.sh --purge)."
fi
