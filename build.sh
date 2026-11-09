#!/usr/bin/env bash
# Сборка Kerio VPN GUI: тесты, автоматическое повышение версии и архив.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PART="${1:-patch}"

case "$PART" in
    major|minor|patch) ;;
    *)
        echo "Использование: ./build.sh [major|minor|patch]" >&2
        exit 2
        ;;
esac

echo "==> Тесты"
PYTHONPATH="$ROOT" python3 -m unittest discover -s "$ROOT/tests" -v

echo "==> Повышение версии ($PART)"
NEW_VERSION="$(python3 "$ROOT/scripts/bump_version.py" "$PART")"
echo "Версия: $NEW_VERSION"

echo "==> Сборка архива"
mkdir -p "$ROOT/dist"
ARCHIVE="$ROOT/dist/kerio-vpn-gui-$NEW_VERSION.tar.gz"
tar \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='dist' \
    --exclude='profiles.json' \
    -czf "$ARCHIVE" \
    -C "$ROOT" \
    kerio_vpn_gui bin helper assets tests scripts \
    build.sh install.sh uninstall.sh README.md .gitignore

echo
echo "Готово: $ARCHIVE"
echo "Установка из исходников: ./install.sh"
