#!/usr/bin/env bash
# Установка Kerio VPN GUI для текущего пользователя.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${PREFIX:-$HOME/.local}"
APP_DIR="$PREFIX/share/kerio-vpn-gui"
BIN="$PREFIX/bin/kerio-vpn-gui"
ICON_DIR="$PREFIX/share/icons/hicolor/scalable/apps"
APPS_DIR="$PREFIX/share/applications"
DESKTOP="$APPS_DIR/kerio-vpn-gui.desktop"
HELPER_DIR="/usr/local/lib/kerio-vpn-gui"
HELPER="$HELPER_DIR/kvc-helper"

if [ "$(id -u)" -eq 0 ]; then
    SUDO=""
else
    SUDO="sudo"
fi

echo "==> Проверка зависимостей"
if ! command -v python3 >/dev/null 2>&1; then
    echo "Ошибка: не найден python3." >&2
    exit 1
fi
if ! python3 -c "import PyQt5" >/dev/null 2>&1; then
    echo "Ошибка: не установлен PyQt5." >&2
    echo "Установите: sudo apt install python3-pyqt5" >&2
    exit 1
fi
if ! command -v pkexec >/dev/null 2>&1; then
    echo "Предупреждение: не найден pkexec (policykit-1)." >&2
    echo "Установите: sudo apt install policykit-1" >&2
fi
if ! dpkg -s kerio-control-vpnclient >/dev/null 2>&1; then
    echo "Предупреждение: пакет kerio-control-vpnclient не найден." >&2
fi

echo "==> Установка приложения в $APP_DIR"
mkdir -p "$APP_DIR" "$PREFIX/bin" "$ICON_DIR" "$APPS_DIR"
rm -rf "$APP_DIR/kerio_vpn_gui"
cp -a "$ROOT/kerio_vpn_gui" "$APP_DIR/kerio_vpn_gui"
find "$APP_DIR" -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
find "$APP_DIR" -type f -name "*.pyc" -delete 2>/dev/null || true

cat >"$BIN" <<EOF
#!/bin/bash
# Сгенерировано install.sh Kerio VPN GUI
export PYTHONPATH="$APP_DIR\${PYTHONPATH:+:\$PYTHONPATH}"
exec -a kerio-vpn-gui python3 -m kerio_vpn_gui "\$@"
EOF
chmod 755 "$BIN"

install -m 644 "$ROOT/assets/kerio-vpn-gui.svg" "$ICON_DIR/kerio-vpn-gui.svg"

cat >"$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=Kerio VPN
Comment=Управление подключениями Kerio Control VPN
Exec=$BIN
Icon=$ICON_DIR/kerio-vpn-gui.svg
Terminal=false
Categories=Network;VPN;
Keywords=kerio;vpn;control;
StartupNotify=true
StartupWMClass=kerio-vpn-gui
EOF
chmod 755 "$DESKTOP"
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "$PREFIX/share/icons/hicolor" >/dev/null 2>&1 || true
fi

echo "==> Установка служебного помощника в $HELPER_DIR"
echo "    (потребуется пароль администратора)"
helper_ok=1
if [ -z "$SUDO" ] || command -v sudo >/dev/null 2>&1; then
    if $SUDO install -d -m 755 "$HELPER_DIR" \
        && $SUDO install -m 755 -o root -g root "$ROOT/helper/kvc-helper" "$HELPER"; then
        helper_ok=0
    fi
fi

if [ "$helper_ok" -ne 0 ]; then
    echo
    echo "ВНИМАНИЕ: не удалось установить помощника автоматически." >&2
    echo "Приложение установлено, но подключение работать не будет." >&2
    echo "Выполните вручную:" >&2
    echo "  sudo install -D -m 755 '$ROOT/helper/kvc-helper' '$HELPER'" >&2
fi

echo
echo "Готово."
echo "  Запуск:            $BIN"
echo "  Меню приложений:   Kerio VPN"
echo "  Профили и настройки: ~/.config/kerio-vpn-gui/"
if ! echo ":$PATH:" | grep -q ":$PREFIX/bin:"; then
    echo
    echo "Примечание: $PREFIX/bin отсутствует в PATH."
    echo "Добавьте в ~/.profile строку:"
    echo "  export PATH=\"$PREFIX/bin:\$PATH\""
fi
