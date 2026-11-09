"""Точка входа приложения kerio-vpn-gui."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Optional

from PyQt5.QtNetwork import QLocalServer, QLocalSocket
from PyQt5.QtWidgets import QApplication

from .core import APP_NAME, APP_VERSION, ProfileStore
from .ui import MainWindow, make_app_icon

IPC_NAME = f"kerio-vpn-gui-ipc-{os.getuid()}"


def _send_to_running(command: str) -> bool:
    """Передаёт команду уже запущенному экземпляру."""
    socket = QLocalSocket()
    socket.connectToServer(IPC_NAME)
    if not socket.waitForConnected(300):
        return False
    socket.write(command.encode("utf-8"))
    socket.flush()
    socket.waitForBytesWritten(800)
    # Ждём подтверждения, чтобы команда гарантированно дошла до обработчика.
    socket.waitForReadyRead(1500)
    socket.disconnectFromServer()
    return True


def _install_ipc_server(window: MainWindow) -> Optional[QLocalServer]:
    server = QLocalServer(window)
    QLocalServer.removeServer(IPC_NAME)
    if not server.listen(IPC_NAME):
        return None

    def handle_connection() -> None:
        connection = server.nextPendingConnection()
        if connection is None:
            return

        def read_command() -> None:
            data = bytes(connection.readAll()).decode("utf-8", "replace").strip()
            if not data:
                return
            try:
                window.handle_ipc(data)
            finally:
                connection.write(b"OK")
                connection.flush()
                connection.disconnectFromServer()

        connection.readyRead.connect(read_command)
        connection.disconnected.connect(connection.deleteLater)
        if connection.bytesAvailable() > 0:
            read_command()

    server.newConnection.connect(handle_connection)
    return server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kerio-vpn-gui",
        description="Графическое управление подключениями Kerio Control VPN.",
    )
    parser.add_argument(
        "--minimized",
        action="store_true",
        help="запустить свёрнутым в трей",
    )
    parser.add_argument(
        "--connect",
        metavar="ПРОФИЛЬ",
        help="сразу подключиться к указанному профилю (имя или id)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {APP_VERSION}",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(arguments)

    app = QApplication([sys.argv[0]])
    app.setApplicationName("kerio-vpn-gui")
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName("kerio-vpn-gui")
    app.setDesktopFileName("kerio-vpn-gui")
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(make_app_icon())

    command = f"connect:{args.connect}" if args.connect else "show"
    if _send_to_running(command):
        return 0

    store = ProfileStore()
    window = MainWindow(
        store,
        minimized=bool(args.minimized),
        connect_name=args.connect,
    )
    window._ipc_server = _install_ipc_server(window)  # type: ignore[attr-defined]
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
