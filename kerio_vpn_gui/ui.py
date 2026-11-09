"""Графический интерфейс Kerio VPN GUI (PyQt5)."""

from __future__ import annotations

import traceback
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import (
    QPointF,
    QRectF,
    QSettings,
    QSize,
    Qt,
    QThread,
    QTimer,
    pyqtSignal,
)
from PyQt5.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QIcon,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
)
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QAction,
    QActionGroup,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStyle,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from . import backend
from .core import (
    APP_NAME,
    APP_VERSION,
    DEFAULT_IMPORT_DIR,
    Profile,
    ProfileStore,
    ScannedConfig,
    StoreError,
    config_dir,
    format_duration,
    normalize_fingerprint,
    now_iso,
    parse_server,
    read_current_config,
    scan_directory,
)
from .theme import THEME_LABELS, THEME_MODES, ThemeManager, normalize_mode
from .toast import ToastManager

LOGS_DIR = backend.LOG_DIR
ICON_COLORS = {
    "connected": "#2ecc71",
    "connecting": "#f1c40f",
    "disconnected": "#aab2bd",
}


# ---------------------------------------------------------------------------
# Иконки и мелкие виджеты
# ---------------------------------------------------------------------------


def make_app_icon(connected: bool = False, connecting: bool = False) -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    gradient = QLinearGradient(0, 0, 0, 64)
    gradient.setColorAt(0.0, QColor("#3478e5"))
    gradient.setColorAt(1.0, QColor("#173f86"))
    painter.setPen(Qt.NoPen)
    painter.setBrush(gradient)
    painter.drawRoundedRect(QRectF(5, 5, 54, 54), 15, 15)

    font = QFont()
    font.setBold(True)
    font.setPixelSize(34)
    painter.setFont(font)
    painter.setPen(QColor("#ffffff"))
    painter.drawText(QRectF(5, 2, 54, 50), Qt.AlignCenter, "K")

    color = "#2ecc71" if connected else ("#f1c40f" if connecting else "#b6bec9")
    painter.setBrush(QColor(color))
    painter.setPen(QPen(QColor("#ffffff"), 3))
    painter.drawEllipse(QPointF(51, 51), 8, 8)
    painter.end()
    return QIcon(pixmap)


def dot_icon(color: str, size: int = 10) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(1, 1, size - 2, size - 2)
    painter.end()
    return QIcon(pixmap)


class StatusBadge(QFrame):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("statusBadge")
        self.setMinimumHeight(30)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 14, 0)
        layout.setSpacing(8)
        self.dot = QLabel(self)
        self.dot.setFixedSize(10, 10)
        self.text = QLabel("Не подключено", self)
        self.text.setStyleSheet("font-weight: 600;")
        layout.addWidget(self.dot)
        layout.addWidget(self.text)
        self.set_state("disconnected", "Не подключено")

    def set_state(self, state: str, text: str, dark: bool = False) -> None:
        if dark:
            palette = {
                "connected": ("#153a2a", "#7ee2a8", "#2ecc71"),
                "connecting": ("#3a2f12", "#ffd166", "#f1c40f"),
                "disconnected": ("#282c33", "#b8c0c8", "#8b949e"),
                "error": ("#3a1f1f", "#ff9b9b", "#ff6b6b"),
            }
        else:
            palette = {
                "connected": ("#e7f7ed", "#17683a", "#2ecc71"),
                "connecting": ("#fff5df", "#8a5a00", "#f1c40f"),
                "disconnected": ("#eef1f5", "#59636e", "#aab2bd"),
                "error": ("#fdecea", "#9c231e", "#e74c3c"),
            }
        background, foreground, dot = palette.get(state, palette["disconnected"])
        self.setStyleSheet(
            "QFrame#statusBadge {"
            f"background: {background}; border-radius: 15px;"
            "}"
            f"QLabel {{ color: {foreground}; }}"
        )
        self.dot.setStyleSheet(f"background: {dot}; border-radius: 5px;")
        self.text.setText(text)


class Worker(QThread):
    done = pyqtSignal(object)
    failed = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, function, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._function = function

    def run(self) -> None:  # noqa: D401
        try:
            result = self._function(self.progress.emit)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            message = str(exc) or exc.__class__.__name__
            self.failed.emit(message)
        else:
            self.done.emit(result)


# ---------------------------------------------------------------------------
# Диалог профиля
# ---------------------------------------------------------------------------


class ProfileDialog(QDialog):
    def __init__(
        self,
        store: ProfileStore,
        profile: Optional[Profile] = None,
        parent: Optional[QWidget] = None,
        *,
        importing: bool = False,
    ) -> None:
        super().__init__(parent)
        self.store = store
        self._profile = profile
        self._original_id = profile.id if profile is not None else None
        self.result_profile: Optional[Profile] = None
        self._fetch_worker: Optional[Worker] = None

        if importing:
            title = "Импорт профиля"
        elif profile is None:
            title = "Новый профиль"
        else:
            title = "Изменить профиль"
        self.setWindowTitle(title)
        self.setWindowIcon(make_app_icon())
        self.setMinimumWidth(720)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        connection_box = QGroupBox("Подключение", self)
        form = QFormLayout(connection_box)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.name_edit = QLineEdit(self)
        self.name_edit.setPlaceholderText("Например, Офис или Резерв")
        if profile:
            self.name_edit.setText(profile.name)
        form.addRow("Название:", self.name_edit)

        self.server_edit = QLineEdit(self)
        self.server_edit.setPlaceholderText("vpn.example.com или 1.2.3.4:4090")
        if profile:
            self.server_edit.setText(profile.server)
        self.server_edit.editingFinished.connect(self._normalize_server_field)
        form.addRow("Сервер:", self.server_edit)

        self.port_spin = QSpinBox(self)
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(profile.port if profile else 4090)
        form.addRow("Порт:", self.port_spin)

        self.username_edit = QLineEdit(self)
        self.username_edit.setPlaceholderText("Имя пользователя Kerio")
        if profile:
            self.username_edit.setText(profile.username)
        form.addRow("Пользователь:", self.username_edit)

        self.password_edit = QLineEdit(self)
        self.password_edit.setEchoMode(QLineEdit.Password)
        if profile:
            self.password_edit.setText(profile.password)
        form.addRow("Пароль:", self.password_edit)

        self.show_password = QCheckBox("Показать пароль", self)
        self.show_password.toggled.connect(self._toggle_password)
        form.addRow("", self.show_password)

        fingerprint_row = QWidget(self)
        fingerprint_layout = QHBoxLayout(fingerprint_row)
        fingerprint_layout.setContentsMargins(0, 0, 0, 0)
        fingerprint_layout.setSpacing(8)
        self.fingerprint_edit = QLineEdit(self)
        self.fingerprint_edit.setPlaceholderText("AA:BB:CC:…:FF")
        self.fingerprint_edit.setFont(
            QFontDatabase.systemFont(QFontDatabase.FixedFont)
        )
        if profile:
            self.fingerprint_edit.setText(profile.fingerprint)
            self.fingerprint_edit.setCursorPosition(0)
        self.fetch_button = QPushButton("Получить с сервера", self)
        self.fetch_button.clicked.connect(self._fetch_fingerprint)
        fingerprint_layout.addWidget(self.fingerprint_edit, 1)
        fingerprint_layout.addWidget(self.fetch_button)
        form.addRow("Отпечаток:", fingerprint_row)

        self.mac_fix = QCheckBox(
            "Исправлять MAC-адрес kvnet после подключения",
            self,
        )
        self.mac_fix.setToolTip(
            "Нужно только для отдельных серверов. После запуска службы помощник "
            "возьмёт MAC-адрес из журнала Kerio и назначит его интерфейсу kvnet."
        )
        if profile:
            self.mac_fix.setChecked(profile.mac_fix)
        form.addRow("", self.mac_fix)

        layout.addWidget(connection_box)

        notes_box = QGroupBox("Заметка", self)
        notes_layout = QVBoxLayout(notes_box)
        self.notes_edit = QPlainTextEdit(self)
        self.notes_edit.setFixedHeight(74)
        self.notes_edit.setPlaceholderText("Необязательная заметка о профиле")
        if profile:
            self.notes_edit.setPlainText(profile.notes)
        notes_layout.addWidget(self.notes_edit)
        layout.addWidget(notes_box)

        self.warning_label = QLabel(self)
        self.warning_label.setObjectName("warningLabel")
        self.warning_label.setWordWrap(True)
        self.warning_label.hide()
        layout.addWidget(self.warning_label)

        self.fingerprint_edit.textChanged.connect(self._update_warning)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel, self
        )
        buttons.button(QDialogButtonBox.Save).setText("Сохранить")
        buttons.button(QDialogButtonBox.Cancel).setText("Отмена")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._update_warning()
        self.name_edit.setFocus()

    def _toggle_password(self, shown: bool) -> None:
        self.password_edit.setEchoMode(QLineEdit.Normal if shown else QLineEdit.Password)

    def _normalize_server_field(self) -> None:
        value = self.server_edit.text().strip()
        if not value:
            return
        try:
            host, port = parse_server(value, self.port_spin.value())
        except ValueError:
            return
        display = f"[{host}]" if ":" in host else host
        if self.server_edit.text() != display:
            self.server_edit.setText(display)
        self.port_spin.setValue(port)

    def _update_warning(self) -> None:
        value = self.fingerprint_edit.text().strip()
        self.fingerprint_edit.setToolTip(value)
        if not value:
            self.warning_label.setText(
                "Отпечаток не указан. Нажмите «Получить с сервера», иначе "
                "подключение будет невозможно."
            )
            self.warning_label.show()
            return
        try:
            normalize_fingerprint(value)
        except ValueError as exc:
            self.warning_label.setText(str(exc))
            self.warning_label.show()
            return
        self.warning_label.hide()

    def _fetch_fingerprint(self) -> None:
        try:
            host, port = parse_server(self.server_edit.text(), self.port_spin.value())
        except ValueError as exc:
            QMessageBox.warning(self, "Проверьте адрес", str(exc))
            self.server_edit.setFocus()
            return
        self.fetch_button.setEnabled(False)
        self.fetch_button.setText("Получение…")
        self._fetch_worker = Worker(
            lambda progress: backend.fetch_fingerprint(host, port, timeout=12),
            self,
        )
        self._fetch_worker.done.connect(self._fingerprint_received)
        self._fetch_worker.failed.connect(self._fingerprint_failed)
        self._fetch_worker.finished.connect(self._fetch_finished)
        self._fetch_worker.start()

    def _fingerprint_received(self, fingerprint: object) -> None:
        self.fingerprint_edit.setText(str(fingerprint))
        self.fingerprint_edit.setCursorPosition(0)

    def _fingerprint_failed(self, message: str) -> None:
        QMessageBox.warning(self, "Не удалось получить отпечаток", message)

    def _fetch_finished(self) -> None:
        self.fetch_button.setEnabled(True)
        self.fetch_button.setText("Получить с сервера")
        if self._fetch_worker is not None:
            self._fetch_worker.deleteLater()
            self._fetch_worker = None

    def _accept(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Проверьте данные", "Укажите название профиля.")
            self.name_edit.setFocus()
            return
        for existing in self.store.profiles:
            if existing.id != self._original_id and existing.name.casefold() == name.casefold():
                QMessageBox.warning(
                    self,
                    "Имя занято",
                    f"Профиль с названием «{name}» уже существует. Выберите другое имя.",
                )
                self.name_edit.setFocus()
                return

        try:
            host, port = parse_server(self.server_edit.text(), self.port_spin.value())
        except ValueError as exc:
            QMessageBox.warning(self, "Проверьте данные", str(exc))
            self.server_edit.setFocus()
            return
        if not self.username_edit.text().strip():
            answer = QMessageBox.question(
                self,
                "Пользователь не указан",
                "Имя пользователя пустое. Продолжить?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                self.username_edit.setFocus()
                return

        try:
            fingerprint = normalize_fingerprint(self.fingerprint_edit.text())
        except ValueError as exc:
            QMessageBox.warning(self, "Проверьте отпечаток", str(exc))
            self.fingerprint_edit.setFocus()
            return
        if not fingerprint:
            answer = QMessageBox.question(
                self,
                "Отпечаток не указан",
                "Без отпечатка сертификата подключение не будет работать.\n"
                "Сохранить профиль всё равно?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                self.fingerprint_edit.setFocus()
                return

        if self._profile is None:
            profile = Profile(name=name, server=host, port=port)
        else:
            profile = self._profile

        profile.name = name
        profile.server = host
        profile.port = port
        profile.username = self.username_edit.text().strip()
        profile.password = self.password_edit.text()
        profile.fingerprint = fingerprint
        profile.mac_fix = self.mac_fix.isChecked()
        profile.notes = self.notes_edit.toPlainText().strip()

        self.result_profile = profile
        self.accept()


# ---------------------------------------------------------------------------
# Импорт профилей
# ---------------------------------------------------------------------------


class ImportDialog(QDialog):
    def __init__(
        self,
        store: ProfileStore,
        directory: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.store = store
        self.directory = directory
        self._scans: list[ScannedConfig] = []
        self.selected: list[Profile] = []

        self.setWindowTitle("Импорт профилей")
        self.setWindowIcon(make_app_icon())
        self.resize(820, 520)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        hint = QLabel(
            "Найдите каталог с существующими *.conf и *.sh (например, /path/to/kerio_config). "
            "Пароли будут прочитаны из конфигураций автоматически.",
            self,
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        path_row = QHBoxLayout()
        self.path_edit = QLineEdit(self)
        self.path_edit.setText(directory)
        self.browse_button = QPushButton("Обзор…", self)
        self.browse_button.clicked.connect(self._browse)
        self.scan_button = QPushButton("Сканировать", self)
        self.scan_button.clicked.connect(self._scan)
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(self.browse_button)
        path_row.addWidget(self.scan_button)
        layout.addLayout(path_row)

        self.info_label = QLabel("", self)
        self.info_label.setObjectName("mutedLabel")
        layout.addWidget(self.info_label)

        self.table = QTableWidget(0, 6, self)
        self.table.setHorizontalHeaderLabels(
            ["", "Имя", "Сервер", "Пользователь", "MAC", "Состояние"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        layout.addWidget(self.table, 1)

        selection_row = QHBoxLayout()
        select_all = QPushButton("Выбрать всё", self)
        select_all.clicked.connect(lambda: self._set_all_checked(True))
        select_none = QPushButton("Снять всё", self)
        select_none.clicked.connect(lambda: self._set_all_checked(False))
        selection_row.addWidget(select_all)
        selection_row.addWidget(select_none)
        selection_row.addStretch(1)
        layout.addLayout(selection_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self
        )
        self.ok_button = buttons.button(QDialogButtonBox.Ok)
        self.ok_button.setText("Импортировать")
        buttons.button(QDialogButtonBox.Cancel).setText("Отмена")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        QTimer.singleShot(0, self._scan)

    def _browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Каталог с конфигурациями", self.path_edit.text() or str(Path.home())
        )
        if chosen:
            self.path_edit.setText(chosen)
            self._scan()

    def _scan(self) -> None:
        directory = self.path_edit.text().strip()
        if not directory:
            QMessageBox.warning(self, "Каталог не указан", "Укажите каталог для поиска.")
            return
        error_message: Optional[str] = None
        scans: list[ScannedConfig] = []
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            scans = scan_directory(directory, self.store.profiles)
        except ValueError as exc:
            error_message = str(exc)
        finally:
            QApplication.restoreOverrideCursor()
        if error_message is not None:
            QMessageBox.warning(self, "Ошибка сканирования", error_message)
            return

        self._scans = scans
        self.directory = directory
        self.table.setRowCount(0)
        valid = 0
        duplicates = 0
        errors = 0
        for scan in scans:
            row = self.table.rowCount()
            self.table.insertRow(row)
            check_item = QTableWidgetItem("")
            if scan.error is not None:
                check_item.setFlags(Qt.ItemIsEnabled)
                errors += 1
            else:
                valid += 1
                check_item.setFlags(
                    Qt.ItemIsEnabled | Qt.ItemIsUserCheckable
                )
                check_item.setCheckState(
                    Qt.Unchecked if scan.duplicate else Qt.Checked
                )
                if scan.duplicate:
                    duplicates += 1
            self.table.setItem(row, 0, check_item)

            name_item = QTableWidgetItem(scan.name)
            name_item.setToolTip(str(scan.path))
            self.table.setItem(row, 1, name_item)

            if scan.profile is not None:
                self.table.setItem(row, 2, QTableWidgetItem(scan.profile.endpoint))
                self.table.setItem(
                    row, 3, QTableWidgetItem(scan.profile.username or "—")
                )
                mac_item = QTableWidgetItem("да" if scan.mac_fix else "—")
                mac_item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, 4, mac_item)
                if scan.duplicate:
                    state = "уже добавлен"
                elif scan.sh_path is not None:
                    state = "готов к импорту (есть .sh)"
                else:
                    state = "готов к импорту"
            else:
                for column in (2, 3, 4):
                    self.table.setItem(row, column, QTableWidgetItem("—"))
                state = f"ошибка: {scan.error}"
            self.table.setItem(row, 5, QTableWidgetItem(state))

        self.info_label.setText(
            f"Найдено: {len(scans)} · новых: {valid - duplicates} · "
            f"уже добавлены: {duplicates} · с ошибками: {errors}"
        )
        self.table.resizeColumnToContents(5)

    def _set_all_checked(self, checked: bool) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None:
                continue
            if item.flags() & Qt.ItemIsUserCheckable:
                item.setCheckState(Qt.Checked if checked else Qt.Unchecked)

    def _accept(self) -> None:
        chosen: list[Profile] = []
        used_names = {profile.name.casefold() for profile in self.store.profiles}
        for row, scan in enumerate(self._scans):
            item = self.table.item(row, 0)
            if item is None or scan.profile is None:
                continue
            if item.checkState() != Qt.Checked:
                continue
            profile = scan.profile
            base = profile.name
            name = base
            index = 2
            while name.casefold() in used_names:
                name = f"{base} ({index})"
                index += 1
            profile.name = name
            used_names.add(name.casefold())
            chosen.append(profile)

        if not chosen:
            QMessageBox.information(
                self, "Ничего не выбрано", "Отметьте хотя бы один профиль для импорта."
            )
            return
        self.selected = chosen
        self.accept()


# ---------------------------------------------------------------------------
# Настройки
# ---------------------------------------------------------------------------


class SettingsDialog(QDialog):
    def __init__(self, store: ProfileStore, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Настройки")
        self.setWindowIcon(make_app_icon())
        self.setMinimumWidth(680)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        behavior = QGroupBox("Поведение", self)
        behavior_layout = QVBoxLayout(behavior)
        self.close_to_tray = QCheckBox(
            "Закрывать окно в трей, а не выходить из приложения", self
        )
        self.close_to_tray.setChecked(bool(store.settings.get("close_to_tray", True)))
        behavior_layout.addWidget(self.close_to_tray)

        self.notifications = QCheckBox("Показывать уведомления о подключении", self)
        self.notifications.setChecked(
            bool(store.settings.get("show_notifications", True))
        )
        behavior_layout.addWidget(self.notifications)

        self.autostart = QCheckBox("Запускать Kerio VPN при входе в систему (в трее)", self)
        self.autostart.setChecked(backend.autostart_enabled())
        behavior_layout.addWidget(self.autostart)

        self.passwordless = QCheckBox(
            "Не запрашивать пароль администратора при подключении", self
        )
        self.passwordless.setToolTip(
            "Устанавливает правило polkit, разрешающее вашему пользователю "
            "запускать только служебный помощник kvc-helper без пароля. "
            "Действует для подключения, отключения и перезапуска службы."
        )
        self.passwordless.setChecked(
            bool(store.settings.get("passwordless", False))
            or backend.passwordless_enabled()
        )
        if not backend.helper_supports_passwordless():
            self.passwordless.setEnabled(False)
            self.passwordless.setToolTip(
                "Установленный помощник не поддерживает эту функцию. "
                "Обновите его командой ./install.sh."
            )
        behavior_layout.addWidget(self.passwordless)
        layout.addWidget(behavior)

        theme_box = QGroupBox("Оформление", self)
        theme_layout = QFormLayout(theme_box)
        self.theme_combo = QComboBox(self)
        for mode in THEME_MODES:
            self.theme_combo.addItem(THEME_LABELS[mode], mode)
        current_theme = normalize_mode(str(store.settings.get("theme", "auto")))
        self.theme_combo.setCurrentIndex(
            max(0, self.theme_combo.findData(current_theme))
        )
        theme_layout.addRow("Тема:", self.theme_combo)

        self.font_spin = QSpinBox(self)
        self.font_spin.setRange(11, 18)
        self.font_spin.setSuffix(" px")
        self.font_spin.setValue(int(store.settings.get("font_size", 14)))
        theme_layout.addRow("Размер шрифта:", self.font_spin)
        layout.addWidget(theme_box)

        polling = QGroupBox("Обновление и подключение", self)
        form = QFormLayout(polling)
        self.poll_spin = QSpinBox(self)
        self.poll_spin.setRange(1, 60)
        self.poll_spin.setSuffix(" с")
        self.poll_spin.setValue(int(store.settings.get("poll_interval_ms", 3000)) // 1000)
        form.addRow("Интервал проверки статуса:", self.poll_spin)

        self.timeout_spin = QSpinBox(self)
        self.timeout_spin.setRange(5, 180)
        self.timeout_spin.setSuffix(" с")
        self.timeout_spin.setValue(
            int(store.settings.get("connect_timeout_sec", 30))
        )
        form.addRow("Ожидание туннеля:", self.timeout_spin)

        import_row = QWidget(self)
        import_layout = QHBoxLayout(import_row)
        import_layout.setContentsMargins(0, 0, 0, 0)
        self.import_edit = QLineEdit(self)
        self.import_edit.setText(str(store.settings.get("import_dir", DEFAULT_IMPORT_DIR)))
        browse = QPushButton("Обзор…", self)
        browse.clicked.connect(self._browse_import)
        import_layout.addWidget(self.import_edit, 1)
        import_layout.addWidget(browse)
        form.addRow("Каталог импорта:", import_row)
        layout.addWidget(polling)

        helper_box = QGroupBox("Служебный помощник", self)
        helper_layout = QVBoxLayout(helper_box)
        helper_path = backend.helper_path()
        pkexec = backend.pkexec_path()
        if helper_path and pkexec:
            text = f"Готов к работе: {helper_path}"
            helper_state = "ok"
        elif helper_path:
            text = f"Помощник найден ({helper_path}), но не найден pkexec."
            helper_state = "error"
        else:
            text = "Не установлен. Запустите ./install.sh из каталога приложения."
            helper_state = "error"
        helper_label = QLabel(text, self)
        helper_label.setWordWrap(True)
        helper_label.setProperty("state", helper_state)
        helper_label.style().unpolish(helper_label)
        helper_label.style().polish(helper_label)
        helper_layout.addWidget(helper_label)
        open_config = QPushButton("Открыть каталог настроек", self)
        open_config.clicked.connect(self._open_config_dir)
        helper_layout.addWidget(open_config)
        layout.addWidget(helper_box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel, self
        )
        buttons.button(QDialogButtonBox.Save).setText("Сохранить")
        buttons.button(QDialogButtonBox.Cancel).setText("Отмена")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse_import(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Каталог с конфигурациями", self.import_edit.text()
        )
        if chosen:
            self.import_edit.setText(chosen)

    def _open_config_dir(self) -> None:
        from PyQt5.QtCore import QUrl
        from PyQt5.QtGui import QDesktopServices

        path = config_dir()
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _accept(self) -> None:
        current_passwordless = (
            bool(self.store.settings.get("passwordless", False))
            or backend.passwordless_enabled()
        )
        passwordless_changed = self.passwordless.isChecked() != current_passwordless
        if passwordless_changed:
            try:
                backend.set_passwordless(self.passwordless.isChecked())
            except backend.BackendError as exc:
                QMessageBox.warning(self, "Правило polkit", str(exc))
                self.passwordless.setChecked(current_passwordless)
                return
        self.store.settings["passwordless"] = self.passwordless.isChecked()

        autostart_changed = self.autostart.isChecked() != backend.autostart_enabled()
        try:
            if autostart_changed:
                backend.set_autostart(self.autostart.isChecked())
        except backend.BackendError as exc:
            QMessageBox.warning(self, "Автозапуск", str(exc))
            return

        self.store.settings["close_to_tray"] = self.close_to_tray.isChecked()
        self.store.settings["show_notifications"] = self.notifications.isChecked()
        self.store.settings["poll_interval_ms"] = self.poll_spin.value() * 1000
        self.store.settings["connect_timeout_sec"] = self.timeout_spin.value()
        self.store.settings["import_dir"] = self.import_edit.text().strip() or DEFAULT_IMPORT_DIR
        self.store.settings["autostart"] = self.autostart.isChecked()
        self.store.settings["theme"] = self.theme_combo.currentData() or "auto"
        self.store.settings["font_size"] = self.font_spin.value()
        self.accept()


# ---------------------------------------------------------------------------
# Главное окно
# ---------------------------------------------------------------------------


class MainWindow(QMainWindow):
    def __init__(
        self,
        store: ProfileStore,
        *,
        minimized: bool = False,
        connect_name: Optional[str] = None,
    ) -> None:
        super().__init__()
        self.store = store
        self.theme_manager = ThemeManager(
            str(store.settings.get("theme", "auto")),
            int(store.settings.get("font_size", 14)),
            self,
        )
        self._last_font_size = self.theme_manager.font_size
        self._busy = False
        self._worker: Optional[Worker] = None
        self._fetch_worker: Optional[Worker] = None
        self._active_profile_id: Optional[str] = None
        self._running = False
        self._connected = False
        self._tunnel = None
        self._pending_profile: Optional[Profile] = None
        self._closing = False
        self._tray_hint_shown = False
        self._tray_signature = None
        self._notified_connected: Optional[bool] = None
        self._connect_name = connect_name
        self._settings = QSettings("kerio-vpn-gui", "kerio-vpn-gui")

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(make_app_icon())
        self.resize(1080, 800)
        self.setMinimumSize(900, 650)

        self._icon_connected = make_app_icon(True, False)
        self._icon_connecting = make_app_icon(False, True)
        self._icon_disconnected = make_app_icon(False, False)
        self._dot_green = dot_icon(ICON_COLORS["connected"])
        self._dot_yellow = dot_icon(ICON_COLORS["connecting"])

        self._build_actions()
        self._build_ui()
        self._build_menus()
        self._build_toolbar()
        self._build_tray()
        self.theme_manager.style_changed.connect(self._on_theme_changed)
        self._sync_theme_actions()
        self.toast_manager = ToastManager(self._show_window, self)
        self._restore_window_state()

        self._refresh_table()
        self._refresh_status(initial=True)
        self._refresh_logs(force=True)

        self._timer = QTimer(self)
        self._timer.setInterval(int(self.store.settings.get("poll_interval_ms", 3000)))
        self._timer.timeout.connect(self._refresh_status)
        self._timer.start()

        self._log_timer = QTimer(self)
        self._log_timer.setInterval(2000)
        self._log_timer.timeout.connect(self._refresh_logs)
        self._log_timer.start()

        if self.store.load_error:
            QMessageBox.warning(self, "Профили", self.store.load_error)

        if minimized and self._tray_visible():
            self.hide()
        else:
            self.show()

        QTimer.singleShot(100, self._after_start)

    # -- построение интерфейса --------------------------------------------
    def _theme_icon(self, names: tuple[str, ...], fallback: QStyle.StandardPixmap) -> QIcon:
        for name in names:
            icon = QIcon.fromTheme(name)
            if not icon.isNull():
                return icon
        return self.style().standardIcon(fallback)

    def _build_actions(self) -> None:
        self.act_add = QAction(
            self._theme_icon(("list-add", "add"), QStyle.SP_FileIcon),
            "Добавить",
            self,
        )
        self.act_add.setShortcut(QKeySequence("Ctrl+N"))
        self.act_add.triggered.connect(self._add_profile)

        self.act_edit = QAction(
            self._theme_icon(
                ("document-edit", "accessories-text-editor"),
                QStyle.SP_FileDialogDetailedView,
            ),
            "Изменить",
            self,
        )
        self.act_edit.setShortcut(QKeySequence("Ctrl+E"))
        self.act_edit.triggered.connect(self._edit_profile)

        self.act_duplicate = QAction(
            self._theme_icon(("edit-copy", "edit-duplicate"), QStyle.SP_FileIcon),
            "Дублировать",
            self,
        )
        self.act_duplicate.setShortcut(QKeySequence("Ctrl+Shift+D"))
        self.act_duplicate.triggered.connect(self._duplicate_profile)

        self.act_delete = QAction(
            self._theme_icon(("edit-delete", "user-trash"), QStyle.SP_TrashIcon),
            "Удалить",
            self,
        )
        self.act_delete.setShortcut(QKeySequence("Delete"))
        self.act_delete.triggered.connect(self._delete_profile)

        self.act_connect = QAction(
            self._theme_icon(
                ("network-vpn", "network-connect"), QStyle.SP_DialogYesButton
            ),
            "Подключить",
            self,
        )
        self.act_connect.setShortcut(QKeySequence("Ctrl+Return"))
        self.act_connect.triggered.connect(self._connect_selected)

        self.act_disconnect = QAction(
            self._theme_icon(
                ("network-vpn-disconnected", "network-disconnect"),
                QStyle.SP_DialogNoButton,
            ),
            "Отключить",
            self,
        )
        self.act_disconnect.setShortcut(QKeySequence("Ctrl+D"))
        self.act_disconnect.triggered.connect(self._disconnect)

        self.act_toggle = QAction(
            self.act_connect.icon(), "Подключить", self
        )
        self.act_toggle.setToolTip("Подключить выбранный профиль")
        self.act_toggle.triggered.connect(self._toggle_connection)

        self.act_restart = QAction(
            self._theme_icon(("view-refresh", "reload"), QStyle.SP_BrowserReload),
            "Перезапустить службу",
            self,
        )
        self.act_restart.triggered.connect(self._restart_service)

        self.act_import = QAction(
            self._theme_icon(
                ("document-open", "folder-open"), QStyle.SP_DirOpenIcon
            ),
            "Импорт из папки…",
            self,
        )
        self.act_import.setShortcut(QKeySequence("Ctrl+I"))
        self.act_import.triggered.connect(self._import_directory)

        self.act_import_file = QAction(
            self._theme_icon(("document-open", "folder-open"), QStyle.SP_FileIcon),
            "Импорт из файла…",
            self,
        )
        self.act_import_file.triggered.connect(self._import_file)

        self.act_import_current = QAction(
            self._theme_icon(("document-import", "document-open"), QStyle.SP_FileIcon),
            "Импорт текущего /etc/kerio-kvc.conf",
            self,
        )
        self.act_import_current.triggered.connect(self._import_current)

        self.act_settings = QAction(
            self._theme_icon(
                ("preferences-system", "settings"), QStyle.SP_FileDialogInfoView
            ),
            "Настройки…",
            self,
        )
        self.act_settings.setShortcut(QKeySequence("Ctrl+,"))
        self.act_settings.triggered.connect(self._open_settings)

        self.act_refresh = QAction(
            self._theme_icon(("view-refresh", "reload"), QStyle.SP_BrowserReload),
            "Обновить журнал",
            self,
        )
        self.act_refresh.setShortcut(QKeySequence("F5"))
        self.act_refresh.triggered.connect(lambda: self._refresh_logs(force=True))

        self.act_quit = QAction(
            self._theme_icon(("application-exit", "system-log-out"), QStyle.SP_DialogCloseButton),
            "Выход",
            self,
        )
        self.act_quit.setShortcut(QKeySequence("Ctrl+Q"))
        self.act_quit.triggered.connect(self._quit_app)

        self.act_about = QAction("О программе", self)
        self.act_about.triggered.connect(self._show_about)

        self.theme_group = QActionGroup(self)
        self.theme_group.setExclusive(True)
        self._theme_actions: dict[str, QAction] = {}
        for mode in THEME_MODES:
            action = QAction(THEME_LABELS[mode], self)
            action.setCheckable(True)
            action.setData(mode)
            action.setChecked(mode == self.theme_manager.mode)
            action.triggered.connect(
                lambda checked=False, selected=mode: self._set_theme(selected)
            )
            self.theme_group.addAction(action)
            self._theme_actions[mode] = action

        self._profile_actions = [
            self.act_edit,
            self.act_duplicate,
            self.act_delete,
            self.act_connect,
        ]
        self._busy_actions = [
            self.act_add,
            self.act_edit,
            self.act_duplicate,
            self.act_delete,
            self.act_connect,
            self.act_disconnect,
            self.act_toggle,
            self.act_restart,
            self.act_import,
            self.act_import_file,
            self.act_import_current,
        ]

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 12, 14, 10)
        root.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(12)
        self.header_icon = QLabel(self)
        self.header_icon.setPixmap(self._icon_disconnected.pixmap(46, 46))
        header.addWidget(self.header_icon)

        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel(APP_NAME, self)
        title_font = title.font()
        title_font.setPointSize(title_font.pointSize() + 7)
        title_font.setBold(True)
        title.setFont(title_font)
        subtitle = QLabel("Профили Kerio Control VPN", self)
        subtitle.setObjectName("mutedLabel")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch(1)

        right_box = QVBoxLayout()
        right_box.setSpacing(2)
        right_box.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.status_badge = StatusBadge(self)
        self.uptime_label = QLabel("", self)
        self.uptime_label.setObjectName("mutedLabel")
        self.uptime_label.setAlignment(Qt.AlignRight)
        right_box.addWidget(self.status_badge, 0, Qt.AlignRight)
        right_box.addWidget(self.uptime_label, 0, Qt.AlignRight)
        header.addLayout(right_box)
        root.addLayout(header)

        splitter = QSplitter(Qt.Vertical, self)
        self.main_splitter = splitter
        root.addWidget(splitter, 1)

        top_splitter = QSplitter(Qt.Horizontal, splitter)
        top_splitter.setChildrenCollapsible(False)
        splitter.addWidget(top_splitter)

        # Левая часть: список профилей
        profiles_box = QGroupBox("Профили", top_splitter)
        profiles_layout = QVBoxLayout(profiles_box)
        profiles_layout.setContentsMargins(10, 8, 10, 10)
        profiles_layout.setSpacing(6)

        self.filter_edit = QLineEdit(profiles_box)
        self.filter_edit.setPlaceholderText("Поиск по имени, серверу или пользователю…")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._refresh_table)
        profiles_layout.addWidget(self.filter_edit)

        self.table = QTableWidget(0, 4, profiles_box)
        self.table.setHorizontalHeaderLabels(
            ["Профиль", "Сервер", "Пользователь", "MAC-фикс"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setWordWrap(False)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(QHeaderView.Interactive)
        header_view.setMinimumSectionSize(55)
        header_view.setStretchLastSection(False)
        scale = self.theme_manager.font_size / 14.0
        for column, width in enumerate((150, 190, 115, 90)):
            self.table.setColumnWidth(column, max(55, int(round(width * scale))))
        self.table.itemSelectionChanged.connect(self._update_details)
        self.table.itemDoubleClicked.connect(lambda *_: self._connect_selected())
        profiles_layout.addWidget(self.table, 1)
        top_splitter.addWidget(profiles_box)

        # Правая часть: детали профиля
        details_box = QGroupBox("Выбранный профиль", top_splitter)
        details_layout = QVBoxLayout(details_box)
        details_layout.setContentsMargins(14, 8, 14, 8)
        details_layout.setSpacing(6)

        self.detail_name = QLabel("Профиль не выбран", details_box)
        name_font = self.detail_name.font()
        name_font.setPointSize(name_font.pointSize() + 4)
        name_font.setBold(True)
        self.detail_name.setFont(name_font)
        self.detail_name.setWordWrap(True)
        details_layout.addWidget(self.detail_name)

        self.detail_sub = QLabel("", details_box)
        self.detail_sub.setObjectName("mutedLabel")
        self.detail_sub.setWordWrap(False)
        details_layout.addWidget(self.detail_sub)

        line = QFrame(details_box)
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        details_layout.addWidget(line)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignTop)
        self.detail_server = self._value_label(details_box)
        self.detail_user = self._value_label(details_box)
        self.detail_fingerprint = QLineEdit(details_box)
        self.detail_fingerprint.setReadOnly(True)
        self.detail_fingerprint.setFrame(False)
        self.detail_fingerprint.setFont(
            QFontDatabase.systemFont(QFontDatabase.FixedFont)
        )
        self.detail_fingerprint.setStyleSheet(
            "QLineEdit { background: transparent; padding: 0; }"
        )
        self.detail_fingerprint.setToolTip("Отпечаток сертификата")
        self.detail_notes = self._value_label(details_box)
        self.detail_notes.setMaximumHeight(42)
        form.addRow("Сервер:", self.detail_server)
        form.addRow("Пользователь:", self.detail_user)
        form.addRow("Отпечаток:", self.detail_fingerprint)
        form.addRow("Заметка:", self.detail_notes)
        details_layout.addLayout(form)

        self.detail_state = QLabel("", details_box)
        self.detail_state.setTextFormat(Qt.RichText)
        self.detail_state.setWordWrap(True)
        details_layout.addWidget(self.detail_state)
        details_layout.addStretch(1)

        buttons_grid = QGridLayout()
        buttons_grid.setSpacing(6)
        self.connect_button = QPushButton("Подключить", details_box)
        self.connect_button.setObjectName("connectButton")
        self.connect_button.setMinimumHeight(34)
        self.connect_button.clicked.connect(self._primary_action)
        buttons_grid.addWidget(self.connect_button, 0, 0, 1, 2)

        self.edit_button = QPushButton("Изменить", details_box)
        self.edit_button.clicked.connect(self._edit_profile)
        self.duplicate_button = QPushButton("Дублировать", details_box)
        self.duplicate_button.clicked.connect(self._duplicate_profile)
        self.delete_button = QPushButton("Удалить", details_box)
        self.delete_button.clicked.connect(self._delete_profile)
        self.copy_button = QPushButton("Копировать конфиг", details_box)
        self.copy_button.clicked.connect(self._copy_config)
        buttons_grid.addWidget(self.edit_button, 1, 0)
        buttons_grid.addWidget(self.duplicate_button, 1, 1)
        buttons_grid.addWidget(self.delete_button, 2, 0)
        buttons_grid.addWidget(self.copy_button, 2, 1)
        details_layout.addLayout(buttons_grid)

        top_splitter.addWidget(details_box)
        top_splitter.setStretchFactor(0, 3)
        top_splitter.setStretchFactor(1, 2)
        top_splitter.setSizes([560, 440])

        # Нижняя часть: журналы
        logs_box = QGroupBox("Журналы", splitter)
        logs_layout = QVBoxLayout(logs_box)
        logs_layout.setContentsMargins(10, 8, 10, 10)
        logs_layout.setSpacing(6)

        self.log_tabs = QTabWidget(logs_box)
        fixed_font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        self.client_log_view = QPlainTextEdit(logs_box)
        self.client_log_view.setReadOnly(True)
        self.client_log_view.setFont(fixed_font)
        self.client_log_view.setMaximumBlockCount(2000)
        self.error_log_view = QPlainTextEdit(logs_box)
        self.error_log_view.setReadOnly(True)
        self.error_log_view.setFont(fixed_font)
        self.error_log_view.setMaximumBlockCount(1000)
        self.log_tabs.addTab(self.client_log_view, "Журнал клиента")
        self.log_tabs.addTab(self.error_log_view, "Ошибки")
        logs_layout.addWidget(self.log_tabs, 1)

        log_buttons = QHBoxLayout()
        self.auto_log = QCheckBox("Автообновление", logs_box)
        self.auto_log.setChecked(True)
        log_buttons.addWidget(self.auto_log)
        log_buttons.addStretch(1)
        copy_log = QPushButton("Копировать", logs_box)
        copy_log.clicked.connect(self._copy_log)
        refresh_log = QPushButton("Обновить", logs_box)
        refresh_log.clicked.connect(lambda: self._refresh_logs(force=True))
        open_logs = QPushButton("Открыть папку журналов", logs_box)
        open_logs.clicked.connect(self._open_logs_dir)
        log_buttons.addWidget(copy_log)
        log_buttons.addWidget(refresh_log)
        log_buttons.addWidget(open_logs)
        logs_layout.addLayout(log_buttons)

        splitter.addWidget(logs_box)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([620, 140])

        self.helper_label = QLabel("", self)
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFixedWidth(150)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        self.count_label = QLabel("", self)
        self.statusBar().addPermanentWidget(self.helper_label)
        self.statusBar().addPermanentWidget(self.progress_bar)
        self.statusBar().addPermanentWidget(self.count_label)
        self._update_helper_label()
        self.statusBar().showMessage("Готово", 3000)

    @staticmethod
    def _wrap_fingerprint(fingerprint: str) -> str:
        parts = (fingerprint or "").split(":")
        if len(parts) == 16:
            return ":".join(parts[:8]) + "\n" + ":".join(parts[8:])
        return fingerprint

    def _set_fingerprint_label(self, text: str) -> None:
        flat = text.replace("\n", "")
        self.detail_fingerprint.setText(flat)
        self.detail_fingerprint.setCursorPosition(0)
        self.detail_fingerprint.setToolTip(flat)
    @staticmethod
    def _value_label(parent: QWidget, monospace: bool = False) -> QLabel:
        label = QLabel("—", parent)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        if monospace:
            label.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        return label

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&Файл")
        file_menu.addAction(self.act_add)
        file_menu.addAction(self.act_import)
        file_menu.addAction(self.act_import_file)
        file_menu.addAction(self.act_import_current)
        file_menu.addSeparator()
        file_menu.addAction(self.act_settings)
        file_menu.addSeparator()
        file_menu.addAction(self.act_quit)

        profile_menu = self.menuBar().addMenu("&Профиль")
        profile_menu.addAction(self.act_edit)
        profile_menu.addAction(self.act_duplicate)
        profile_menu.addAction(self.act_delete)
        profile_menu.addSeparator()
        profile_menu.addAction(self.act_connect)
        profile_menu.addAction(self.act_disconnect)
        profile_menu.addSeparator()
        profile_menu.addAction(self.act_restart)

        view_menu = self.menuBar().addMenu("&Вид")
        for mode in THEME_MODES:
            view_menu.addAction(self._theme_actions[mode])

        log_menu = self.menuBar().addMenu("&Журнал")
        log_menu.addAction(self.act_refresh)

        help_menu = self.menuBar().addMenu("&Справка")
        help_menu.addAction(self.act_about)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Основная", self)
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(18, 18))
        toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.addToolBar(toolbar)
        for action in (
            self.act_add,
            self.act_edit,
            self.act_delete,
            None,
            self.act_toggle,
            None,
            self.act_import,
            self.act_settings,
        ):
            if action is None:
                toolbar.addSeparator()
            else:
                toolbar.addAction(action)

    def _build_tray(self) -> None:
        self.tray: Optional[QSystemTrayIcon] = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(self._icon_disconnected, self)
        self.tray.setToolTip(APP_NAME)
        self._tray_menu = self.tray.contextMenu() or None
        self.tray.activated.connect(self._tray_activated)
        self._rebuild_tray_menu()
        self.tray.show()

    def _tray_visible(self) -> bool:
        return self.tray is not None and self.tray.isVisible()

    # -- восстановление геометрии -----------------------------------------
    def _restore_window_state(self) -> None:
        geometry = self._settings.value("window/geometry_v2")
        if geometry is not None:
            self.restoreGeometry(geometry)
        state = self._settings.value("window/splitter_v2")
        if state is not None:
            self.main_splitter.restoreState(state)
        horizontal = self._settings.value("window/top_splitter_v2")
        if horizontal is not None and self.main_splitter.widget(0) is not None:
            top = self.main_splitter.widget(0)
            if isinstance(top, QSplitter):
                top.restoreState(horizontal)
        header_state = self._settings.value("window/table_header_v2")
        if header_state is not None:
            self.table.horizontalHeader().restoreState(header_state)
            saved_font = self._settings.value("window/table_font_size")
            try:
                saved_font_size = int(saved_font)
            except (TypeError, ValueError):
                saved_font_size = self._last_font_size
            if saved_font_size > 0 and saved_font_size != self._last_font_size:
                ratio = self._last_font_size / float(saved_font_size)
                for column in range(self.table.columnCount()):
                    width = max(55, int(round(self.table.columnWidth(column) * ratio)))
                    self.table.setColumnWidth(column, width)

    def _save_window_state(self) -> None:
        self._settings.setValue("window/geometry_v2", self.saveGeometry())
        self._settings.setValue("window/splitter_v2", self.main_splitter.saveState())
        top = self.main_splitter.widget(0)
        if isinstance(top, QSplitter):
            self._settings.setValue("window/top_splitter_v2", top.saveState())
        self._settings.setValue(
            "window/table_header_v2", self.table.horizontalHeader().saveState()
        )
        self._settings.setValue(
            "window/table_font_size", self.theme_manager.font_size
        )

    # -- журналы -----------------------------------------------------------
    def _refresh_logs(self, force: bool = False) -> None:
        if not force and not self.auto_log.isChecked():
            return
        if not force and not self.isVisible():
            return
        self._set_log_text(self.client_log_view, backend.client_log(300))
        errors = backend.error_log(80)
        self._set_log_text(
            self.error_log_view,
            errors if errors else "Журнал ошибок пуст.",
        )

    @staticmethod
    def _set_log_text(view: QPlainTextEdit, text: str) -> None:
        if view.toPlainText() == text:
            return
        scrollbar = view.verticalScrollBar()
        at_bottom = scrollbar.value() >= scrollbar.maximum() - 4
        view.setPlainText(text)
        if at_bottom:
            scrollbar.setValue(scrollbar.maximum())

    def _copy_log(self) -> None:
        view = self.log_tabs.currentWidget()
        if isinstance(view, QPlainTextEdit):
            QApplication.clipboard().setText(view.toPlainText())
            self.statusBar().showMessage("Журнал скопирован в буфер обмена", 4000)

    def _open_logs_dir(self) -> None:
        from PyQt5.QtCore import QUrl
        from PyQt5.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(LOGS_DIR)))

    # -- таблица профилей --------------------------------------------------
    def _refresh_table(self) -> None:
        selected = self._selected_profile()
        selected_id = selected.id if selected else None
        query = self.filter_edit.text().strip().casefold() if hasattr(self, "filter_edit") else ""
        visible = [
            profile
            for profile in self.store.profiles
            if not query
            or query in profile.name.casefold()
            or query in profile.server.casefold()
            or query in profile.username.casefold()
            or query in profile.endpoint.casefold()
        ]
        self.table.blockSignals(True)
        self.table.setRowCount(len(visible))
        for row, profile in enumerate(visible):
            name_item = QTableWidgetItem(profile.name)
            name_item.setData(Qt.UserRole, profile.id)
            tooltip_lines = [profile.name, profile.endpoint, profile.username]
            if profile.notes:
                tooltip_lines.append(profile.notes)
            if profile.last_used:
                tooltip_lines.append(f"Последнее подключение: {profile.last_used}")
            name_item.setToolTip("\n".join(line for line in tooltip_lines if line))
            self.table.setItem(row, 0, name_item)

            server_item = QTableWidgetItem(profile.endpoint)
            self.table.setItem(row, 1, server_item)

            user_item = QTableWidgetItem(profile.username or "—")
            self.table.setItem(row, 2, user_item)

            mac_item = QTableWidgetItem("да" if profile.mac_fix else "—")
            mac_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 3, mac_item)
        self.table.blockSignals(False)

        if query:
            self.count_label.setText(
                f"Профилей: {len(self.store.profiles)} · показано: {len(visible)}"
            )
        else:
            self.count_label.setText(f"Профилей: {len(self.store.profiles)}")
        if selected_id:
            self._select_profile(selected_id)
        if self.table.currentRow() < 0 and visible:
            self.table.selectRow(0)
        self._update_active_marker()
        self._update_details()
        self._rebuild_tray_menu()

    def _selected_profile(self) -> Optional[Profile]:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        profile_id = item.data(Qt.UserRole)
        return self.store.get(str(profile_id)) if profile_id else None

    def _select_profile(self, profile_id: str) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.data(Qt.UserRole) == profile_id:
                self.table.selectRow(row)
                return

    def _update_active_marker(self) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None:
                continue
            active = (
                self._active_profile_id is not None
                and item.data(Qt.UserRole) == self._active_profile_id
            )
            if active and self._connected:
                item.setIcon(self._dot_green)
            elif active:
                item.setIcon(self._dot_yellow)
            else:
                item.setIcon(QIcon())
            font = item.font()
            font.setBold(active)
            item.setFont(font)

    def _update_details(self) -> None:
        profile = self._selected_profile()
        has_profile = profile is not None
        for action in (self.act_edit, self.act_duplicate, self.act_delete):
            action.setEnabled(has_profile and not self._busy)
        self.act_connect.setEnabled(has_profile and not self._busy)

        if not has_profile:
            self.detail_name.setText("Профиль не выбран")
            self.detail_sub.setText("Добавьте профиль или выберите его в списке")
            self.detail_server.setText("—")
            self.detail_user.setText("—")
            self._set_fingerprint_label("—")
            self.detail_notes.setText("—")
            self.detail_state.setText("")
            self.connect_button.setText("Подключить")
            self._set_connect_button_danger(False)
            self.connect_button.setEnabled(False)
            self.edit_button.setEnabled(False)
            self.duplicate_button.setEnabled(False)
            self.delete_button.setEnabled(False)
            self.copy_button.setEnabled(False)
            self._update_toggle_action()
            return

        self.detail_name.setText(profile.name)
        self.detail_sub.setText(f"{profile.endpoint} · {profile.username or 'без пользователя'}")
        self.detail_server.setText(profile.endpoint)
        self.detail_server.setToolTip(profile.endpoint)
        self.detail_user.setText(profile.username or "—")
        self.detail_user.setToolTip(profile.username or "")
        self._set_fingerprint_label(
            self._wrap_fingerprint(profile.fingerprint) if profile.fingerprint else "не задан"
        )
        self.detail_notes.setText(profile.notes or "—")
        self.detail_notes.setToolTip(profile.notes or "")

        colors = self.theme_manager.colors
        active_here = self._active_profile_id == profile.id
        if active_here and self._connected and self._tunnel:
            self.detail_state.setText(
                f"<span style='color:{colors.success}; font-weight:600;'>Подключено</span>"
                f" · IP {self._tunnel.address}"
            )
        elif active_here and self._running:
            self.detail_state.setText(
                f"<span style='color:{colors.warning};'>Служба запущена, туннель не поднят</span>"
            )
        elif self._running:
            self.detail_state.setText(
                f"<span style='color:{colors.warning};'>Активно другое подключение</span>"
            )
        else:
            self.detail_state.setText(
                f"<span style='color:{colors.muted};'>Не подключено</span>"
            )

        if self._running and active_here:
            self.connect_button.setText("Отключить")
            self._set_connect_button_danger(True)
        elif self._running:
            self.connect_button.setText("Переключиться")
            self._set_connect_button_danger(False)
        else:
            self.connect_button.setText("Подключить")
            self._set_connect_button_danger(False)

        self.connect_button.setEnabled(not self._busy)
        for button in (
            self.edit_button,
            self.duplicate_button,
            self.delete_button,
            self.copy_button,
        ):
            button.setEnabled(not self._busy)
        self._update_toggle_action()

    def _set_connect_button_danger(self, danger: bool) -> None:
        if bool(self.connect_button.property("danger")) == danger:
            return
        self.connect_button.setProperty("danger", danger)
        self.connect_button.style().unpolish(self.connect_button)
        self.connect_button.style().polish(self.connect_button)

    def _update_toggle_action(self) -> None:
        running = self._running
        profile = self._selected_profile()
        active_here = (
            profile is not None and self._active_profile_id == profile.id
        )
        if running and active_here:
            text = "Отключить"
            icon = self.act_disconnect.icon()
            tooltip = "Отключить VPN для выбранного профиля"
        elif running and profile is not None:
            text = "Переключиться"
            icon = self.act_connect.icon()
            tooltip = "Переключиться на выбранный профиль"
        elif running:
            text = "Отключить"
            icon = self.act_disconnect.icon()
            tooltip = "Отключить VPN"
        else:
            text = "Подключить"
            icon = self.act_connect.icon()
            tooltip = "Подключить выбранный профиль"

        self.act_toggle.setText(text)
        self.act_toggle.setIcon(icon)
        self.act_toggle.setToolTip(tooltip)
        self.act_toggle.setEnabled(
            not self._busy and (running or profile is not None)
        )

    # -- статус ------------------------------------------------------------
    def _refresh_status(self, initial: bool = False) -> None:
        try:
            running = backend.service_running()
        except backend.BackendError:
            running = False
        tunnel = backend.tunnel_info() if running else None
        connected = bool(tunnel is not None and tunnel.ip)

        active = backend.active_connection() if running else None
        active_profile = (
            self.store.find_matching(active.server, active.port, active.username)
            if active is not None
            else None
        )
        self._active_profile_id = active_profile.id if active_profile else None

        self._running = running
        self._connected = connected
        self._tunnel = tunnel

        if connected and tunnel is not None:
            if not self._busy:
                self.status_badge.set_state(
                    "connected",
                    f"Подключено · {tunnel.ip}",
                    dark=self.theme_manager.is_dark,
                )
            uptime = backend.service_uptime()
            self.uptime_label.setText(
                f"В сети {format_duration(uptime)}" if uptime is not None and not self._busy else ""
            )
            window_title = f"{APP_NAME} — {active_profile.name if active_profile else 'VPN'}"
        elif running:
            if not self._busy:
                self.status_badge.set_state(
                    "connecting",
                    "Служба запущена, нет туннеля",
                    dark=self.theme_manager.is_dark,
                )
            self.uptime_label.setText("")
            window_title = f"{APP_NAME} — подключение…"
        else:
            if not self._busy:
                self.status_badge.set_state(
                    "disconnected", "Не подключено", dark=self.theme_manager.is_dark
                )
            self.uptime_label.setText("")
            window_title = APP_NAME
        if not self._busy:
            self.setWindowTitle(window_title)

        icon = (
            self._icon_connected
            if connected
            else (self._icon_connecting if running else self._icon_disconnected)
        )
        if self.windowIcon().cacheKey() != icon.cacheKey():
            self.setWindowIcon(icon)
        self.header_icon.setPixmap(icon.pixmap(46, 46))
        if self.tray is not None:
            self.tray.setIcon(icon)
            if self._busy:
                pass
            elif connected and tunnel is not None:
                name = active_profile.name if active_profile else "VPN"
                self.tray.setToolTip(
                    f"{APP_NAME}: подключено\n{name}\nIP {tunnel.ip}"
                )
            elif running:
                self.tray.setToolTip(f"{APP_NAME}: служба запущена, туннель не поднят")
            else:
                self.tray.setToolTip(f"{APP_NAME}: не подключено")

        self.act_disconnect.setEnabled(running and not self._busy)
        self._update_active_marker()
        self._update_details()
        self._rebuild_tray_menu()

        if initial or self._notified_connected is None:
            self._notified_connected = connected
        elif not self._busy and connected != self._notified_connected:
            if connected:
                name = active_profile.name if active_profile else "VPN"
                self._notify(
                    "VPN подключён",
                    f"{name}\nIP: {tunnel.ip}" if tunnel is not None else name,
                    "success",
                )
            else:
                self._notify(
                    "VPN отключён",
                    "Соединение с Kerio Control прервано.",
                    "warning",
                )
            self._notified_connected = connected

    # -- трей --------------------------------------------------------------
    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            if self.isVisible() and self.isActiveWindow():
                self.hide()
            else:
                self._show_window()

    def _rebuild_tray_menu(self) -> None:
        if self.tray is None:
            return
        signature = (
            tuple((profile.id, profile.name) for profile in self.store.profiles),
            self._active_profile_id,
            self._connected,
            self._running,
            self._busy,
            self._tunnel.ip if self._tunnel is not None else None,
        )
        if signature == self._tray_signature:
            return
        self._tray_signature = signature

        menu = self._tray_menu if getattr(self, "_tray_menu", None) else None
        if menu is None:
            from PyQt5.QtWidgets import QMenu

            menu = QMenu()
            self._tray_menu = menu
            self.tray.setContextMenu(menu)
        menu.clear()

        if self._connected and self._tunnel is not None:
            header = QAction(f"Подключено · {self._tunnel.ip}", menu)
        elif self._running:
            header = QAction("Служба запущена, нет туннеля", menu)
        else:
            header = QAction("Не подключено", menu)
        header.setEnabled(False)
        menu.addAction(header)

        active_profile = self.store.get(self._active_profile_id) if self._active_profile_id else None
        if active_profile is not None:
            profile_header = QAction(f"Профиль: {active_profile.name}", menu)
            profile_header.setEnabled(False)
            menu.addAction(profile_header)
        menu.addSeparator()

        connect_menu = menu.addMenu("Подключиться")
        if not self.store.profiles:
            empty = connect_menu.addAction("Нет профилей")
            empty.setEnabled(False)
        for profile in self.store.profiles:
            action = QAction(profile.name, connect_menu)
            action.setCheckable(True)
            action.setChecked(profile.id == self._active_profile_id and self._connected)
            action.triggered.connect(
                lambda checked=False, profile_id=profile.id: self._connect_profile_id(profile_id)
            )
            connect_menu.addAction(action)

        disconnect_action = QAction("Отключиться", menu)
        disconnect_action.setEnabled(self._running and not self._busy)
        disconnect_action.triggered.connect(self._disconnect)
        menu.addAction(disconnect_action)

        menu.addSeparator()
        show_action = QAction("Показать окно", menu)
        show_action.triggered.connect(self._show_window)
        menu.addAction(show_action)

        settings_action = QAction("Настройки…", menu)
        settings_action.triggered.connect(self._open_settings)
        menu.addAction(settings_action)

        menu.addSeparator()
        quit_action = QAction("Выход", menu)
        quit_action.triggered.connect(self._quit_app)
        menu.addAction(quit_action)

    def _notify(self, title: str, message: str, kind: str = "info") -> None:
        if not self.store.settings.get("show_notifications", True):
            return
        self.toast_manager.show_message(title, message, kind)

    # -- занятость ---------------------------------------------------------
    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._busy = busy
        self.progress_bar.setVisible(busy)
        for action in self._busy_actions:
            action.setEnabled(not busy)
        if busy:
            self.status_badge.set_state(
                "connecting",
                message or "Выполняется…",
                dark=self.theme_manager.is_dark,
            )
            self.uptime_label.setText("")
        self.table.setEnabled(not busy)
        for action in (self.act_edit, self.act_duplicate, self.act_delete, self.act_connect):
            action.setEnabled(not busy and self._selected_profile() is not None)
        self._update_details()
        if not busy:
            self._refresh_status()

    # -- подключение -------------------------------------------------------
    def _after_start(self) -> None:
        if self._connect_name:
            profile = self.store.find_by_name(self._connect_name)
            if profile is None:
                QMessageBox.warning(
                    self,
                    "Профиль не найден",
                    f"Профиль «{self._connect_name}» не найден.",
                )
            else:
                self._connect_profile(profile)

    def _connect_selected(self) -> None:
        profile = self._selected_profile()
        if profile is not None:
            self._connect_profile(profile)

    def _toggle_connection(self) -> None:
        self._primary_action()

    def _primary_action(self) -> None:
        if self._busy:
            return
        profile = self._selected_profile()
        if profile is None:
            if self._running:
                self._disconnect()
            return
        if self._running and self._active_profile_id == profile.id:
            self._disconnect()
        else:
            self._connect_profile(profile)

    def _connect_profile_id(self, profile_id: str) -> None:
        profile = self.store.get(profile_id)
        if profile is not None:
            self._connect_profile(profile)

    def _connect_profile(self, profile: Profile) -> None:
        if self._busy or profile is None:
            return
        if not backend.helper_ready():
            QMessageBox.warning(self, "Нужен служебный помощник", backend.helper_problem())
            return

        try:
            running = backend.service_running()
        except backend.BackendError:
            running = False
        if running:
            active = backend.active_connection()
            same = (
                active is not None
                and (active.server.lower(), active.port, active.username.lower())
                == profile.dedupe_key
            )
            tunnel = backend.tunnel_info()
            if same and tunnel is not None and tunnel.ip:
                QMessageBox.information(
                    self,
                    "Уже подключено",
                    f"Профиль «{profile.name}» уже подключён.\nIP: {tunnel.ip}",
                )
                return
            answer = QMessageBox.question(
                self,
                "Переключение подключения",
                "Текущее VPN-подключение будет разорвано.\n"
                f"Подключиться к «{profile.name}»?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if answer != QMessageBox.Yes:
                return

        timeout = int(self.store.settings.get("connect_timeout_sec", 30))
        self._pending_profile = profile
        self._set_busy(True, f"Подключение: {profile.name}")
        self.statusBar().showMessage(f"Подключение к {profile.name}…")

        worker = Worker(
            lambda progress: backend.connect(profile, timeout, progress),
            self,
        )
        worker.progress.connect(
            lambda message: self._set_busy(True, message), Qt.QueuedConnection
        )
        worker.done.connect(
            lambda result: self._connect_finished(profile, result),
            Qt.QueuedConnection,
        )
        worker.failed.connect(self._connect_failed, Qt.QueuedConnection)
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        worker.start()

    def _connect_finished(self, profile: Profile, result: object) -> None:
        self._worker = None
        self._pending_profile = None
        profile.last_used = now_iso()
        try:
            self.store.save()
        except StoreError as exc:
            QMessageBox.warning(self, "Профили", str(exc))
        self._notified_connected = True
        self._set_busy(False)
        self._refresh_table()
        self._select_profile(profile.id)
        self._refresh_status()

        tunnel = getattr(result, "tunnel", None)
        ip = getattr(tunnel, "ip", None)
        self.statusBar().showMessage(
            f"Подключено: {profile.name}" + (f" · IP {ip}" if ip else ""), 10000
        )
        self._notify(
            "VPN подключён",
            f"{profile.name}\nIP: {ip}" if ip else profile.name,
            "success",
        )

    def _connect_failed(self, message: str) -> None:
        self._worker = None
        self._pending_profile = None
        self._set_busy(False)
        self._refresh_status()
        self._refresh_logs(force=True)
        self.log_tabs.setCurrentIndex(1)
        QMessageBox.critical(self, "Не удалось подключиться", message)
        self.statusBar().showMessage("Ошибка подключения", 8000)

    def _disconnect(self) -> None:
        if self._busy:
            return
        try:
            running = backend.service_running()
        except backend.BackendError:
            running = False
        if not running:
            self._refresh_status()
            self.statusBar().showMessage("VPN уже отключён", 4000)
            return

        self._set_busy(True, "Отключение…")
        worker = Worker(lambda progress: backend.disconnect(progress=progress), self)
        worker.progress.connect(
            lambda message: self._set_busy(True, message), Qt.QueuedConnection
        )
        worker.done.connect(self._disconnect_finished, Qt.QueuedConnection)
        worker.failed.connect(self._operation_failed, Qt.QueuedConnection)
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        worker.start()

    def _disconnect_finished(self, _result: object = None) -> None:
        self._worker = None
        self._notified_connected = False
        self._set_busy(False)
        self._refresh_status()
        self.statusBar().showMessage("VPN отключён", 6000)
        self._notify("VPN отключён", "Служба Kerio VPN остановлена.", "info")

    def _restart_service(self) -> None:
        if self._busy:
            return
        answer = QMessageBox.question(
            self,
            "Перезапуск службы",
            "Перезапустить службу Kerio VPN с текущей конфигурацией?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer != QMessageBox.Yes:
            return
        timeout = int(self.store.settings.get("connect_timeout_sec", 30))
        self._set_busy(True, "Перезапуск службы…")

        def operation(progress):
            backend.restart(progress)
            return backend.wait_for_tunnel(timeout, progress)

        worker = Worker(operation, self)
        worker.progress.connect(
            lambda message: self._set_busy(True, message), Qt.QueuedConnection
        )
        worker.done.connect(self._restart_finished, Qt.QueuedConnection)
        worker.failed.connect(self._operation_failed, Qt.QueuedConnection)
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        worker.start()

    def _restart_finished(self, result: object) -> None:
        self._worker = None
        self._set_busy(False)
        self._refresh_status()
        ip = getattr(result, "ip", None)
        self.statusBar().showMessage(
            "Служба перезапущена" + (f" · IP {ip}" if ip else ""), 8000
        )

    def _operation_failed(self, message: str) -> None:
        self._worker = None
        self._set_busy(False)
        self._refresh_status()
        self._refresh_logs(force=True)
        self.log_tabs.setCurrentIndex(1)
        QMessageBox.critical(self, "Ошибка", message)

    # -- CRUD профилей -----------------------------------------------------
    def _add_profile(self) -> None:
        dialog = ProfileDialog(self.store, None, self)
        if dialog.exec_() == QDialog.Accepted and dialog.result_profile is not None:
            self.store.add(dialog.result_profile)
            self._save_store()
            self.filter_edit.clear()
            self._refresh_table()
            self._select_profile(dialog.result_profile.id)
            self.statusBar().showMessage(
                f"Профиль «{dialog.result_profile.name}» добавлен", 5000
            )

    def _edit_profile(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        dialog = ProfileDialog(self.store, profile, self)
        if dialog.exec_() == QDialog.Accepted and dialog.result_profile is not None:
            self._save_store()
            self._refresh_table()
            self._select_profile(profile.id)
            self.statusBar().showMessage("Профиль сохранён", 5000)

    def _duplicate_profile(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        clone = profile.clone(self.store.unique_name(profile.name + " (копия)"))
        self.store.add(clone)
        self._save_store()
        self.filter_edit.clear()
        self._refresh_table()
        self._select_profile(clone.id)
        self.statusBar().showMessage(f"Создана копия «{clone.name}»", 5000)

    def _delete_profile(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        answer = QMessageBox.question(
            self,
            "Удалить профиль",
            f"Удалить профиль «{profile.name}»?\n"
            "Файлы конфигурации на диске затронуты не будут.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.store.remove(profile.id)
        self._save_store()
        self._refresh_table()
        self.statusBar().showMessage("Профиль удалён", 5000)

    def _copy_config(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        QApplication.clipboard().setText(profile.to_kerio_xml())
        self.statusBar().showMessage("Конфигурация скопирована в буфер обмена", 5000)

    def _save_store(self) -> None:
        try:
            self.store.save()
        except StoreError as exc:
            QMessageBox.critical(self, "Не удалось сохранить", str(exc))

    # -- импорт ------------------------------------------------------------
    def _import_directory(self) -> None:
        start = str(self.store.settings.get("import_dir", DEFAULT_IMPORT_DIR))
        dialog = ImportDialog(self.store, start, self)
        if dialog.exec_() != QDialog.Accepted or not dialog.selected:
            return
        for profile in dialog.selected:
            self.store.add(profile)
        self.store.settings["import_dir"] = dialog.directory
        self._save_store()
        self.filter_edit.clear()
        self._refresh_table()
        self._select_profile(dialog.selected[-1].id)
        self.statusBar().showMessage(
            f"Импортировано профилей: {len(dialog.selected)}", 7000
        )

    def _import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Импорт конфигурации Kerio",
            str(Path.home()),
            "Конфигурации Kerio (*.conf);;Все файлы (*)",
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
            profile = Profile.from_kerio_xml(text, name=Path(path).stem)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Не удалось прочитать профиль", str(exc))
            return
        profile.name = self.store.unique_name(profile.name)
        dialog = ProfileDialog(self.store, profile, self, importing=True)
        if dialog.exec_() == QDialog.Accepted and dialog.result_profile is not None:
            self.store.add(dialog.result_profile)
            self._save_store()
            self.filter_edit.clear()
            self._refresh_table()
            self._select_profile(dialog.result_profile.id)

    def _import_current(self) -> None:
        try:
            profile = read_current_config()
        except ValueError as exc:
            QMessageBox.warning(self, "Текущий конфиг", str(exc))
            return
        profile.name = self.store.unique_name("Текущий конфиг")
        dialog = ProfileDialog(self.store, profile, self, importing=True)
        if dialog.exec_() == QDialog.Accepted and dialog.result_profile is not None:
            self.store.add(dialog.result_profile)
            self._save_store()
            self.filter_edit.clear()
            self._refresh_table()
            self._select_profile(dialog.result_profile.id)

    # -- прочее ------------------------------------------------------------
    def _set_theme(self, mode: str) -> None:
        selected = normalize_mode(mode)
        self.store.settings["theme"] = selected
        self._save_store()
        self.theme_manager.set_mode(selected)
        self._sync_theme_actions()

    def _sync_theme_actions(self) -> None:
        mode = self.theme_manager.mode
        for action_mode, action in self._theme_actions.items():
            action.setChecked(action_mode == mode)

    def _on_theme_changed(self, _mode: str = "", _dark: bool = False) -> None:
        new_size = self.theme_manager.font_size
        if new_size != self._last_font_size:
            delta = new_size - self._last_font_size
            if delta and not self.isMaximized():
                self.resize(
                    max(self.minimumWidth(), self.width() + delta * 60),
                    max(self.minimumHeight(), self.height() + delta * 8),
                )
            ratio = new_size / float(self._last_font_size)
            for column in range(self.table.columnCount()):
                width = max(55, int(round(self.table.columnWidth(column) * ratio)))
                self.table.setColumnWidth(column, width)
            self._last_font_size = new_size
        self._sync_theme_actions()
        self._update_helper_label()
        self._refresh_status(initial=True)

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.store, self)
        if dialog.exec_() == QDialog.Accepted:
            self._save_store()
            self._timer.setInterval(
                int(self.store.settings.get("poll_interval_ms", 3000))
            )
            self.theme_manager.set_mode(
                str(self.store.settings.get("theme", "auto"))
            )
            self.theme_manager.set_font_size(
                int(self.store.settings.get("font_size", 14))
            )
            self._sync_theme_actions()
            self._update_helper_label()
            self.statusBar().showMessage("Настройки сохранены", 5000)

    def _update_helper_label(self) -> None:
        ready = backend.helper_ready()
        if ready:
            self.helper_label.setText("Помощник: установлен")
            self.helper_label.setToolTip("")
        else:
            self.helper_label.setText("Помощник не установлен")
            self.helper_label.setToolTip(backend.helper_problem())
        self.helper_label.setProperty("state", "ok" if ready else "error")
        self.helper_label.style().unpolish(self.helper_label)
        self.helper_label.style().polish(self.helper_label)

    def _show_about(self) -> None:
        helper = backend.helper_path()
        helper_text = str(helper) if helper else "не установлен"
        QMessageBox.about(
            self,
            f"О {APP_NAME}",
            f"<h3>{APP_NAME} {APP_VERSION}</h3>"
            "<p>Графическое управление подключениями Kerio Control VPN.</p>"
            f"<p><b>Профили:</b> {self.store.path}<br>"
            f"<b>Помощник:</b> {helper_text}</p>"
            "<p>Приложение не является официальным продуктом Kerio Technologies. "
            "Конфигурация записывается в /etc/kerio-kvc.conf через pkexec.</p>",
        )

    def _show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit_app(self) -> None:
        if self._busy:
            self._show_window()
            QMessageBox.information(
                self,
                "Операция выполняется",
                "Дождитесь завершения подключения или отключения, затем закройте приложение.",
            )
            return
        self._closing = True
        self._save_window_state()
        self.toast_manager.close_all()
        if self.tray is not None:
            self.tray.hide()
        QApplication.quit()

    def handle_ipc(self, message: str) -> None:
        message = (message or "").strip()
        if message.startswith("connect:"):
            name = message.split(":", 1)[1].strip()
            profile = self.store.find_by_name(name)
            self._show_window()
            if profile is None:
                QMessageBox.warning(
                    self, "Профиль не найден", f"Профиль «{name}» не найден."
                )
                return
            QTimer.singleShot(100, lambda: self._connect_profile(profile))
            return
        self._show_window()

    # -- события -----------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802
        self._save_window_state()
        if self._closing:
            event.accept()
            return
        if self._tray_visible() and self.store.settings.get("close_to_tray", True):
            event.ignore()
            self.hide()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self._notify(
                    "Приложение свёрнуто в трей",
                    "Kerio VPN продолжит работать. Выход — через меню иконки в трее.",
                )
            return
        if self._busy:
            event.ignore()
            QMessageBox.information(
                self,
                "Операция выполняется",
                "Дождитесь завершения подключения или отключения.",
            )
            return
        event.accept()
        QApplication.quit()
