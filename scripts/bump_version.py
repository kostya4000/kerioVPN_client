#!/usr/bin/env python3
"""Увеличивает APP_VERSION в kerio_vpn_gui/core.py."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "kerio_vpn_gui" / "core.py"
PATTERN = re.compile(r'^APP_VERSION = "(\d+)\.(\d+)\.(\d+)"$', re.MULTILINE)


def main() -> int:
    part = (sys.argv[1] if len(sys.argv) > 1 else "patch").strip().lower()
    if part not in ("major", "minor", "patch"):
        print("Использование: bump_version.py [major|minor|patch]", file=sys.stderr)
        return 2

    text = CORE.read_text(encoding="utf-8")
    match = PATTERN.search(text)
    if match is None:
        print("APP_VERSION не найден в core.py", file=sys.stderr)
        return 1

    major, minor, patch = (int(value) for value in match.groups())
    if part == "major":
        major, minor, patch = major + 1, 0, 0
    elif part == "minor":
        minor, patch = minor + 1, 0
    else:
        patch += 1

    new_version = f"{major}.{minor}.{patch}"
    text = PATTERN.sub(f'APP_VERSION = "{new_version}"', text, count=1)
    CORE.write_text(text, encoding="utf-8")
    print(new_version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
