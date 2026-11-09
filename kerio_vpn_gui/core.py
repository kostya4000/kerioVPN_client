"""Модель данных, хранение профилей и импорт конфигураций Kerio VPN.

Профили хранятся в ~/.config/kerio-vpn-gui/profiles.json с правами 0600.
Пароль кодируется тем же способом, что и в /etc/kerio-kvc.conf (XOR 0x55),
то есть является обфускацией, а не надёжным шифрованием.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

APP_ID = "kerio-vpn-gui"
APP_NAME = "Kerio VPN"
APP_VERSION = "1.2.6"
# Нейтральный каталог по умолчанию. Реальный путь пользователь выбирает
# в диалоге импорта; после первого импорта он сохраняется в настройках.
DEFAULT_IMPORT_DIR = str(Path.home() / "kerio")
XOR_KEY = 0x55
PASSWORD_PREFIX = "XOR:"
PROFILES_VERSION = 1

_FP_CLEAN_RE = re.compile(r"[^0-9a-fA-F]")
_MAC_CLEAN_RE = re.compile(r"[^0-9a-fA-F]")


class StoreError(RuntimeError):
    """Ошибка чтения/записи хранилища профилей."""


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def config_dir() -> Path:
    """Каталог с пользовательскими настройками (можно переопределить для тестов)."""
    override = os.environ.get("KERIO_GUI_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / APP_ID


def profiles_path() -> Path:
    return config_dir() / "profiles.json"


# ---------------------------------------------------------------------------
# Кодирование пароля (совместимо с Kerio)
# ---------------------------------------------------------------------------


def xor_encode(text: str) -> str:
    """Кодирует строку в hex-XOR с ключом 0x55 (формат Kerio)."""
    return "".join(f"{byte ^ XOR_KEY:02x}" for byte in (text or "").encode("utf-8"))


def xor_decode(encoded: str) -> str:
    """Декодирует пароль из формата Kerio (hex-XOR 0x55)."""
    value = (encoded or "").strip()
    if value.upper().startswith(PASSWORD_PREFIX):
        value = value[len(PASSWORD_PREFIX):]
    value = re.sub(r"\s+", "", value)
    if not value:
        return ""
    if len(value) % 2:
        raise ValueError("Некорректная длина XOR-строки пароля")
    try:
        data = bytes(int(value[i:i + 2], 16) ^ XOR_KEY for i in range(0, len(value), 2))
    except ValueError as exc:
        raise ValueError("Пароль содержит некорректные hex-символы") from exc
    return data.decode("utf-8", "replace")


# ---------------------------------------------------------------------------
# Нормализация полей
# ---------------------------------------------------------------------------


def normalize_fingerprint(value: str) -> str:
    """Приводит отпечаток к виду AA:BB:...:FF (16 байт)."""
    cleaned = (value or "").strip()
    # Поддержка вывода вида "md5 Fingerprint=AA:BB:..."
    if "=" in cleaned:
        cleaned = cleaned.rsplit("=", 1)[1]
    raw = _FP_CLEAN_RE.sub("", cleaned)
    if not raw:
        return ""
    if len(raw) != 32:
        raise ValueError("Отпечаток должен содержать 32 hex-символа (16 байт)")
    return ":".join(raw[i:i + 2].upper() for i in range(0, 32, 2))


def normalize_mac(value: str) -> str:
    raw = _MAC_CLEAN_RE.sub("", value or "")
    if len(raw) != 12:
        raise ValueError("MAC-адрес должен содержать 12 hex-символов")
    return ":".join(raw[i:i + 2].lower() for i in range(0, 12, 2))


def parse_server(value: str, default_port: int = 4090) -> tuple[str, int]:
    """Разбирает 'host', 'host:port', 'https://host/' или '[ipv6]:port'."""
    result = (value or "").strip()
    result = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", result)
    result = result.split("/", 1)[0].strip()
    if not result:
        raise ValueError("Укажите адрес сервера")
    if result.startswith("["):
        match = re.match(r"^\[([^\]]+)\](?::(\d+))?$", result)
        if not match:
            raise ValueError("Некорректный IPv6-адрес сервера")
        host = match.group(1)
        port = int(match.group(2)) if match.group(2) else default_port
    elif result.count(":") == 1:
        host, maybe_port = result.rsplit(":", 1)
        if maybe_port.isdigit():
            port = int(maybe_port)
        else:
            host, port = result, default_port
    else:
        host, port = result, default_port
    if not host:
        raise ValueError("Укажите адрес сервера")
    if not 1 <= port <= 65535:
        raise ValueError("Порт должен быть в диапазоне 1–65535")
    return host.strip(), port


def format_endpoint(server: str, port: int) -> str:
    if ":" in server and not server.startswith("["):
        return f"[{server}]:{port}"
    return f"{server}:{port}"


def format_duration(seconds: Optional[int]) -> str:
    if seconds is None:
        return ""
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


# ---------------------------------------------------------------------------
# Профиль
# ---------------------------------------------------------------------------


@dataclass
class Profile:
    name: str
    server: str
    username: str = ""
    password_enc: str = ""
    fingerprint: str = ""
    port: int = 4090
    mac_fix: bool = False
    notes: str = ""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created: str = field(default_factory=now_iso)
    last_used: str = ""

    # -- пароль ------------------------------------------------------------
    @property
    def password(self) -> str:
        try:
            return xor_decode(self.password_enc)
        except ValueError:
            return ""

    @password.setter
    def password(self, value: str) -> None:
        self.password_enc = xor_encode(value or "")

    @property
    def endpoint(self) -> str:
        return format_endpoint(self.server, self.port)

    # -- сериализация ------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Profile":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        values = {key: value for key, value in (data or {}).items() if key in known}
        profile = cls(**values)
        try:
            profile.port = int(profile.port)
        except (TypeError, ValueError):
            profile.port = 4090
        profile.mac_fix = bool(profile.mac_fix)
        profile.name = str(profile.name or "").strip()
        profile.server = str(profile.server or "").strip()
        profile.username = str(profile.username or "")
        profile.password_enc = str(profile.password_enc or "")
        profile.notes = str(profile.notes or "")
        if not profile.id:
            profile.id = str(uuid.uuid4())
        if not profile.name:
            profile.name = profile.server or "Профиль"
        try:
            if profile.fingerprint:
                profile.fingerprint = normalize_fingerprint(profile.fingerprint)
        except ValueError:
            pass
        return profile

    # -- Kerio XML ---------------------------------------------------------
    def to_kerio_xml(self) -> str:
        server = _xml_escape(self.server.strip())
        username = _xml_escape(self.username)
        fingerprint = _xml_escape(normalize_fingerprint(self.fingerprint))
        password = re.sub(r"\s+", "", self.password_enc or "").lower()
        lines = [
            "<config>",
            "  <connections>",
            '    <connection type="persistent">',
            f"      <server>{server}</server>",
            f"      <port>{int(self.port)}</port>",
            f"      <username>{username}</username>",
            f"      <password>{PASSWORD_PREFIX}{password}</password>",
            f"      <fingerprint>{fingerprint}</fingerprint>",
            "      <active>1</active>",
            "    </connection>",
            "  </connections>",
            "</config>",
            "",
        ]
        return "\n".join(lines)

    @classmethod
    def from_kerio_xml(
        cls,
        text: str,
        *,
        name: str,
        mac_fix: bool = False,
        notes: str = "",
    ) -> "Profile":
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            raise ValueError(f"Некорректный XML конфигурации: {exc}") from exc
        connection = root.find(".//connection")
        if connection is None:
            raise ValueError("В конфигурации не найдено соединение <connection>")

        def text_of(tag: str, default: str = "") -> str:
            element = connection.find(tag)
            return (element.text or "").strip() if element is not None else default

        server = text_of("server")
        if not server:
            raise ValueError("В конфигурации не указан сервер")
        try:
            port = int(text_of("port", "4090") or 4090)
        except ValueError:
            port = 4090
        password_raw = text_of("password")
        if password_raw.upper().startswith(PASSWORD_PREFIX):
            try:
                password = xor_decode(password_raw)
            except ValueError:
                password = password_raw
        else:
            password = password_raw
        fingerprint = text_of("fingerprint")
        try:
            fingerprint = normalize_fingerprint(fingerprint)
        except ValueError:
            pass
        profile = cls(
            name=name,
            server=server,
            username=text_of("username"),
            password_enc=xor_encode(password),
            fingerprint=fingerprint,
            port=port,
            mac_fix=mac_fix,
            notes=notes,
        )
        return profile

    @property
    def dedupe_key(self) -> tuple[str, int, str]:
        return (self.server.strip().lower(), int(self.port), self.username.strip().lower())

    def clone(self, new_name: str) -> "Profile":
        return Profile(
            name=new_name,
            server=self.server,
            username=self.username,
            password_enc=self.password_enc,
            fingerprint=self.fingerprint,
            port=self.port,
            mac_fix=self.mac_fix,
            notes=self.notes,
        )


def _xml_escape(value: str) -> str:
    return (
        (value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# ---------------------------------------------------------------------------
# Настройки и хранилище
# ---------------------------------------------------------------------------

DEFAULT_SETTINGS: dict[str, Any] = {
    "close_to_tray": True,
    "show_notifications": True,
    "poll_interval_ms": 3000,
    "connect_timeout_sec": 30,
    "import_dir": DEFAULT_IMPORT_DIR,
    "autostart": False,
    "theme": "auto",
    "font_size": 14,
    "passwordless": False,
}


@dataclass
class ScannedConfig:
    path: Path
    name: str
    profile: Optional[Profile]
    mac_fix: bool = False
    sh_path: Optional[Path] = None
    error: Optional[str] = None
    duplicate: bool = False


class ProfileStore:
    """JSON-хранилище профилей и настроек пользователя."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path else profiles_path()
        self.profiles: list[Profile] = []
        self.settings: dict[str, Any] = dict(DEFAULT_SETTINGS)
        self.load_error: Optional[str] = None
        self.load()

    # -- загрузка/сохранение ----------------------------------------------
    def load(self) -> None:
        self.load_error = None
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            backup = self.path.with_name(self.path.name + ".broken")
            try:
                self.path.replace(backup)
            except OSError:
                pass
            self.load_error = (
                f"Не удалось прочитать файл профилей: {exc}.\n"
                f"Повреждённый файл сохранён как {backup.name}. "
                "Приложение запущено с пустым списком профилей."
            )
            return

        raw_profiles = data.get("profiles") if isinstance(data, dict) else None
        profiles: list[Profile] = []
        seen_ids: set[str] = set()
        for item in raw_profiles or []:
            if not isinstance(item, dict):
                continue
            try:
                profile = Profile.from_dict(item)
            except Exception:
                continue
            if profile.id in seen_ids:
                profile.id = str(uuid.uuid4())
            seen_ids.add(profile.id)
            profiles.append(profile)
        self.profiles = profiles

        raw_settings = data.get("settings") if isinstance(data, dict) else None
        self.settings = dict(DEFAULT_SETTINGS)
        if isinstance(raw_settings, dict):
            for key, value in raw_settings.items():
                if key in DEFAULT_SETTINGS:
                    self.settings[key] = value
        self._coerce_settings()

    def _coerce_settings(self) -> None:
        try:
            self.settings["poll_interval_ms"] = max(1000, min(60000, int(self.settings.get("poll_interval_ms", 3000))))
        except (TypeError, ValueError):
            self.settings["poll_interval_ms"] = 3000
        try:
            self.settings["connect_timeout_sec"] = max(5, min(180, int(self.settings.get("connect_timeout_sec", 30))))
        except (TypeError, ValueError):
            self.settings["connect_timeout_sec"] = 30
        self.settings["close_to_tray"] = bool(self.settings.get("close_to_tray", True))
        self.settings["show_notifications"] = bool(self.settings.get("show_notifications", True))
        self.settings["autostart"] = bool(self.settings.get("autostart", False))
        self.settings["import_dir"] = str(self.settings.get("import_dir") or DEFAULT_IMPORT_DIR)
        theme = str(self.settings.get("theme", "auto")).strip().lower()
        self.settings["theme"] = theme if theme in ("auto", "light", "dark") else "auto"
        try:
            self.settings["font_size"] = max(11, min(18, int(self.settings.get("font_size", 14))))
        except (TypeError, ValueError):
            self.settings["font_size"] = 14
        self.settings["passwordless"] = bool(self.settings.get("passwordless", False))

    def save(self) -> None:
        payload = {
            "version": PROFILES_VERSION,
            "profiles": [profile.to_dict() for profile in self.profiles],
            "settings": self.settings,
        }
        data = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
        try:
            _atomic_write(self.path, data)
        except OSError as exc:
            raise StoreError(f"Не удалось сохранить профили в {self.path}: {exc}") from exc

    # -- операции с профилями ---------------------------------------------
    def get(self, profile_id: str) -> Optional[Profile]:
        for profile in self.profiles:
            if profile.id == profile_id:
                return profile
        return None

    def add(self, profile: Profile) -> Profile:
        self.profiles.append(profile)
        return profile

    def remove(self, profile_id: str) -> bool:
        before = len(self.profiles)
        self.profiles = [p for p in self.profiles if p.id != profile_id]
        return len(self.profiles) != before

    def update(self, profile: Profile) -> None:
        for index, existing in enumerate(self.profiles):
            if existing.id == profile.id:
                self.profiles[index] = profile
                return
        self.profiles.append(profile)

    def unique_name(self, base: str) -> str:
        base = (base or "Профиль").strip() or "Профиль"
        names = {profile.name.casefold() for profile in self.profiles}
        if base.casefold() not in names:
            return base
        index = 2
        while f"{base} ({index})".casefold() in names:
            index += 1
        return f"{base} ({index})"

    def find_matching(self, server: str, port: int, username: str) -> Optional[Profile]:
        key = (server.strip().lower(), int(port), username.strip().lower())
        for profile in self.profiles:
            if profile.dedupe_key == key:
                return profile
        return None

    def is_duplicate(self, profile: Profile) -> bool:
        return self.find_matching(profile.server, profile.port, profile.username) is not None

    def find_by_name(self, value: str) -> Optional[Profile]:
        value = (value or "").strip()
        for profile in self.profiles:
            if profile.id == value:
                return profile
        for profile in self.profiles:
            if profile.name.casefold() == value.casefold():
                return profile
        return None


def _atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Импорт существующих конфигураций
# ---------------------------------------------------------------------------


def scan_directory(directory: str | Path, existing: Iterable[Profile] = ()) -> list[ScannedConfig]:
    """Сканирует каталог с *.conf/*.sh (формат старых скриптов) и возвращает найденное."""
    folder = Path(directory).expanduser()
    if not folder.is_dir():
        raise ValueError(f"Каталог не найден: {folder}")

    known_keys = {profile.dedupe_key for profile in existing}
    results: list[ScannedConfig] = []
    try:
        entries = sorted(folder.iterdir(), key=lambda item: item.name.casefold())
    except OSError as exc:
        raise ValueError(f"Не удалось прочитать каталог {folder}: {exc}") from exc

    for path in entries:
        if not path.is_file() or path.name.startswith(".") or path.name.endswith("~"):
            continue
        if path.suffix.lower() != ".conf":
            continue
        try:
            if path.stat().st_size == 0:
                continue
        except OSError:
            continue

        sh_path = path.with_suffix(".sh")
        mac_fix = False
        if sh_path.is_file():
            try:
                sh_text = sh_path.read_text(encoding="utf-8", errors="replace")
                mac_fix = "ip link set kvnet" in sh_text
            except OSError:
                pass

        name = path.stem
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            profile = Profile.from_kerio_xml(text, name=name, mac_fix=mac_fix)
        except (OSError, ValueError) as exc:
            results.append(
                ScannedConfig(
                    path=path,
                    name=name,
                    profile=None,
                    mac_fix=mac_fix,
                    sh_path=sh_path if sh_path.is_file() else None,
                    error=str(exc),
                )
            )
            continue

        results.append(
            ScannedConfig(
                path=path,
                name=name,
                profile=profile,
                mac_fix=mac_fix,
                sh_path=sh_path if sh_path.is_file() else None,
                duplicate=profile.dedupe_key in known_keys,
            )
        )
    return results


def read_current_config(path: str | Path = "/etc/kerio-kvc.conf") -> Profile:
    conf_path = Path(path)
    try:
        text = conf_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ValueError(f"Не удалось прочитать {conf_path}: {exc}") from exc
    return Profile.from_kerio_xml(text, name="Текущий конфиг")
