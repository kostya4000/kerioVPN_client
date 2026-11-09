"""Системные операции Kerio VPN: статус, подключение, отключение, журналы.

Привилегированные действия (запись /etc/kerio-kvc.conf, перезапуск службы,
смена MAC) выполняет маленький helper через pkexec.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import socket
import ssl
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .core import Profile, normalize_fingerprint

KERIO_CONF = Path("/etc/kerio-kvc.conf")
KERIO_INIT = Path("/etc/init.d/kerio-kvc")
LOG_DIR = Path("/var/log/kerio-kvc")
DEBUG_LOG = LOG_DIR / "debug.log"
ERROR_LOG = LOG_DIR / "error.log"
TUNNEL_IFACE = "kvnet"
HELPER_CANDIDATES = (
    Path("/usr/local/lib/kerio-vpn-gui/kvc-helper"),
    Path("/usr/lib/kerio-vpn-gui/kvc-helper"),
)


def autostart_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "autostart" / "kerio-vpn-gui.desktop"

ProgressCallback = Optional[Callable[[str], None]]


class BackendError(RuntimeError):
    """Понятная пользователю ошибка системной операции."""


@dataclass
class TunnelInfo:
    interface: str
    ip: Optional[str] = None
    prefix: Optional[int] = None
    mac: Optional[str] = None

    @property
    def address(self) -> str:
        if self.ip is None:
            return ""
        return f"{self.ip}/{self.prefix}" if self.prefix else self.ip


@dataclass
class ActiveConnection:
    server: str
    port: int
    username: str


@dataclass
class ConnectResult:
    tunnel: TunnelInfo
    elapsed: float


def _progress(callback: ProgressCallback, message: str) -> None:
    if callback is not None:
        try:
            callback(message)
        except Exception:
            pass


def _run(
    command: list[str],
    *,
    timeout: float = 30,
    input_data: Optional[bytes] = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            input=input_data,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise BackendError(f"Команда не найдена: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise BackendError(
            f"Истекло время ожидания команды: {' '.join(map(str, command))}"
        ) from exc
    except OSError as exc:
        raise BackendError(f"Не удалось выполнить {command[0]}: {exc}") from exc


# ---------------------------------------------------------------------------
# Helper / pkexec
# ---------------------------------------------------------------------------


def helper_path() -> Optional[Path]:
    override = os.environ.get("KERIO_GUI_HELPER")
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override).expanduser())
    candidates.extend(HELPER_CANDIDATES)
    for path in candidates:
        try:
            if path.is_file() and os.access(path, os.X_OK):
                return path
        except OSError:
            continue
    return None


def pkexec_path() -> Optional[str]:
    return shutil.which("pkexec")


def helper_ready() -> bool:
    return helper_path() is not None and pkexec_path() is not None


def helper_problem() -> str:
    if helper_path() is None:
        return (
            "Не установлен служебный помощник.\n\n"
            "Запустите ./install.sh из каталога приложения — он установит\n"
            "/usr/local/lib/kerio-vpn-gui/kvc-helper (потребуется пароль администратора)."
        )
    if pkexec_path() is None:
        return (
            "Не найден pkexec. Установите пакет policykit-1:\n\n"
            "sudo apt install policykit-1"
        )
    return ""


def _run_helper(action: str, *arguments: object, timeout: float = 180) -> str:
    helper = helper_path()
    if helper is None:
        raise BackendError(helper_problem())
    pkexec = pkexec_path()
    if pkexec is None:
        raise BackendError(helper_problem())

    command = [pkexec, str(helper), action]
    command.extend(str(argument) for argument in arguments)
    result = _run(command, timeout=timeout)
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()

    if result.returncode != 0:
        if result.returncode == 126:
            raise BackendError(
                "Авторизация отменена или не удалась.\n"
                "Для подключения нужно подтвердить запрос polkit."
            )
        if result.returncode == 127:
            raise BackendError(
                "Нет прав на запуск служебного помощника.\n\n"
                "Переустановите его командой ./install.sh (файл должен принадлежать root).\n"
                + (stderr or stdout)
            )
        message = stderr or stdout or f"Помощник завершился с кодом {result.returncode}"
        raise BackendError(message)
    return stdout


# ---------------------------------------------------------------------------
# Состояние службы и туннеля
# ---------------------------------------------------------------------------


def service_pid() -> Optional[int]:
    result = _run(["pgrep", "-x", "kvpncsvc"], timeout=5)
    if result.returncode != 0:
        return None
    for line in (result.stdout or "").split():
        if line.isdigit():
            return int(line)
    return None


def service_running() -> bool:
    return service_pid() is not None


def service_uptime() -> Optional[int]:
    pid = service_pid()
    if pid is None:
        return None
    result = _run(["ps", "-o", "etimes=", "-p", str(pid)], timeout=5)
    try:
        return int((result.stdout or "").strip())
    except (TypeError, ValueError):
        return None


def tunnel_info() -> Optional[TunnelInfo]:
    sysfs = Path("/sys/class/net") / TUNNEL_IFACE
    try:
        if not sysfs.exists():
            return None
    except OSError:
        return None

    ip_address: Optional[str] = None
    prefix: Optional[int] = None
    result = _run(["ip", "-4", "-o", "addr", "show", "dev", TUNNEL_IFACE], timeout=5)
    if result.returncode == 0:
        match = re.search(r"\binet\s+([0-9.]+)/(\d+)", result.stdout or "")
        if match:
            ip_address = match.group(1)
            prefix = int(match.group(2))

    mac: Optional[str] = None
    try:
        mac = (sysfs / "address").read_text(encoding="ascii").strip()
    except OSError:
        pass
    return TunnelInfo(interface=TUNNEL_IFACE, ip=ip_address, prefix=prefix, mac=mac)


def active_connection() -> Optional[ActiveConnection]:
    try:
        text = KERIO_CONF.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    try:
        profile = Profile.from_kerio_xml(text, name="active")
    except ValueError:
        return None
    return ActiveConnection(server=profile.server, port=profile.port, username=profile.username)


def tail_text(path: Path, lines: int = 200, max_bytes: int = 262_144) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            start = max(0, size - max_bytes)
            handle.seek(start)
            data = handle.read()
    except OSError:
        return ""
    text = data.decode("utf-8", "replace")
    if start > 0:
        # Первая строка может быть обрезана — выбрасываем её.
        if "\n" in text:
            text = text.split("\n", 1)[1]
    return "\n".join(text.splitlines()[-lines:])


def client_log(lines: int = 250) -> str:
    return tail_text(DEBUG_LOG, lines=lines)


def error_log(lines: int = 80) -> str:
    text = tail_text(ERROR_LOG, lines=lines)
    if text:
        return text
    return tail_text(DEBUG_LOG, lines=lines)


# ---------------------------------------------------------------------------
# Отпечаток сертификата
# ---------------------------------------------------------------------------


def _fingerprint_from_der(der: bytes) -> str:
    digest = hashlib.md5(der).hexdigest().upper()
    return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2))


def fetch_fingerprint(server: str, port: int = 4090, timeout: float = 12) -> str:
    """Получает MD5-отпечаток сертификата Kerio Control."""
    server = (server or "").strip()
    if not server:
        raise BackendError("Укажите адрес сервера")
    try:
        port = int(port)
    except (TypeError, ValueError):
        port = 4090

    errors: list[str] = []

    # 1) Пытаемся штатным Python TLS (быстрее и не зависит от вывода openssl).
    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        try:
            context.set_ciphers("DEFAULT:@SECLEVEL=0")
        except ssl.SSLError:
            pass
        with socket.create_connection((server, port), timeout=timeout) as raw:
            with context.wrap_socket(raw, server_hostname=None) as tls:
                der = tls.getpeercert(binary_form=True)
        if der:
            return _fingerprint_from_der(der)
    except Exception as exc:  # noqa: BLE001 — нужен fallback на openssl
        errors.append(str(exc))

    # 2) Fallback: openssl s_client.
    try:
        connect_host = f"[{server}]" if ":" in server else server
        result = subprocess.run(
            ["openssl", "s_client", "-connect", f"{connect_host}:{port}", "-showcerts"],
            input=b"",
            capture_output=True,
            timeout=timeout + 5,
        )
        output = (result.stdout or b"").decode("utf-8", "replace")
        match = re.search(
            r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----",
            output,
            re.S,
        )
        if not match:
            stderr = (result.stderr or b"").decode("utf-8", "replace").strip()
            raise BackendError(stderr or "Сервер не вернул сертификат")
        cert = match.group(0).encode("ascii")
        result2 = subprocess.run(
            ["openssl", "x509", "-fingerprint", "-md5", "-noout"],
            input=cert,
            capture_output=True,
            timeout=10,
        )
        text = (result2.stdout or b"").decode("utf-8", "replace")
        match2 = re.search(r"=([0-9A-Fa-f:]{47})", text)
        if not match2:
            raise BackendError("Не удалось разобрать отпечаток из ответа openssl")
        return normalize_fingerprint(match2.group(1))
    except FileNotFoundError as exc:
        raise BackendError(
            "Не удалось получить отпечаток: не найден openssl.\n"
            "Установите пакет openssl: sudo apt install openssl"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise BackendError(
            f"Сервер {server}:{port} не ответил за {int(timeout)} секунд"
        ) from exc
    except BackendError:
        raise
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc))
        raise BackendError(
            "Не удалось получить отпечаток сертификата:\n" + "\n".join(errors)
        ) from exc


# ---------------------------------------------------------------------------
# Подключение / отключение
# ---------------------------------------------------------------------------


def wait_for_tunnel(timeout: float, progress: ProgressCallback = None) -> TunnelInfo:
    deadline = time.monotonic() + max(1, timeout)
    while time.monotonic() < deadline:
        info = tunnel_info()
        if info is not None and info.ip:
            return info
        remaining = max(0, int(deadline - time.monotonic()))
        _progress(
            progress,
            f"Ожидание туннеля… осталось {remaining} с",
        )
        time.sleep(0.4)

    info = tunnel_info()
    if info is not None and info.ip:
        return info

    details = error_log(40)
    message = (
        f"Туннель не поднялся за {int(timeout)} с.\n\n"
        "Проверьте адрес сервера, логин/пароль и отпечаток сертификата."
    )
    if details:
        message += "\n\nПоследние строки журнала ошибок:\n" + details
    raise BackendError(message)


def connect(
    profile: Profile,
    connect_timeout: float = 30,
    progress: ProgressCallback = None,
) -> ConnectResult:
    if not profile.server:
        raise BackendError("В профиле не указан адрес сервера")
    if not profile.fingerprint:
        raise BackendError(
            "В профиле не указан отпечаток сертификата.\n"
            "Откройте профиль и нажмите «Получить с сервера»."
        )
    if helper_path() is None:
        raise BackendError(helper_problem())

    started = time.monotonic()
    config_text = profile.to_kerio_xml()
    fd, temp_name = tempfile.mkstemp(prefix="kerio-vpn-", suffix=".conf")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(config_text)
        os.chmod(temp_name, 0o600)

        _progress(progress, "Запрос прав администратора…")
        _run_helper(
            "connect",
            temp_name,
            "1" if profile.mac_fix else "0",
            timeout=150,
        )
        _progress(progress, "Служба запущена, ждём выдачи адреса…")
        info = wait_for_tunnel(connect_timeout, progress)
        active = active_connection()
        if active is not None:
            active_key = (
                active.server.strip().lower(),
                int(active.port),
                active.username.strip().lower(),
            )
            if active_key != profile.dedupe_key:
                raise BackendError(
                    "Туннель поднят, но активная конфигурация не совпадает с профилем.\n"
                    f"В /etc/kerio-kvc.conf: {active.server}:{active.port} / {active.username}.\n"
                    "Проверьте журнал ошибок и попробуйте перезапустить службу."
                )
        return ConnectResult(tunnel=info, elapsed=time.monotonic() - started)
    finally:
        try:
            os.unlink(temp_name)
        except OSError:
            pass


def disconnect(timeout: float = 20, progress: ProgressCallback = None) -> None:
    _progress(progress, "Запрос прав администратора…")
    _run_helper("disconnect", timeout=60)
    _progress(progress, "Ожидание остановки службы…")
    deadline = time.monotonic() + max(2, timeout)
    while time.monotonic() < deadline:
        if not service_running():
            return
        time.sleep(0.4)
    if service_running():
        raise BackendError(
            "Служба Kerio VPN всё ещё работает после команды остановки.\n"
            "Попробуйте: sudo /etc/init.d/kerio-kvc stop"
        )


def restart(progress: ProgressCallback = None) -> None:
    _progress(progress, "Перезапуск службы…")
    _run_helper("restart", timeout=90)


# ---------------------------------------------------------------------------
# Автозапуск
# ---------------------------------------------------------------------------


def autostart_enabled() -> bool:
    return autostart_path().is_file()


def set_autostart(enabled: bool) -> None:
    autostart_file = autostart_path()
    if not enabled:
        try:
            autostart_file.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise BackendError(f"Не удалось удалить автозапуск: {exc}") from exc
        return

    executable = shutil.which("kerio-vpn-gui")
    if not executable:
        candidate = Path.home() / ".local" / "bin" / "kerio-vpn-gui"
        if candidate.is_file():
            executable = str(candidate)
    if not executable:
        raise BackendError(
            "Не найден исполняемый файл kerio-vpn-gui. Сначала запустите ./install.sh."
        )
    autostart_file.parent.mkdir(parents=True, exist_ok=True)
    content = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Kerio VPN\n"
        "Comment=Подключение к Kerio Control VPN\n"
        f"Exec={executable} --minimized\n"
        "Icon=kerio-vpn-gui\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
    )
    try:
        autostart_file.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise BackendError(f"Не удалось создать автозапуск: {exc}") from exc
