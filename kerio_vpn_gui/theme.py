"""Темы оформления Kerio VPN GUI (светлая, тёмная, как в системе)."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QObject, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import QApplication

THEME_MODES = ("auto", "light", "dark")
THEME_LABELS = {
    "auto": "Как в системе",
    "light": "Светлая",
    "dark": "Тёмная",
}
_THEME_ALIASES = {
    "auto": "auto",
    "system": "auto",
    "система": "auto",
    "light": "light",
    "светлая": "light",
    "dark": "dark",
    "тёмная": "dark",
    "темная": "dark",
}
_DARK_NAME_MARKERS = (
    "dark",
    "nokto",      # Adapta-Nokto
    "night",
    "black",
    "midnight",
    "darker",
    "sweet",
    "dracula",
    "gruvbox",
    "nord",
    "tokyo",
    "catppuccin",
    "mocha",
    "oblivion",
    "palenight",
)

_CHECK_ICON = (Path(__file__).resolve().parent / "assets" / "check.png").as_posix()


def normalize_mode(value: str) -> str:
    return _THEME_ALIASES.get((value or "").strip().lower(), "auto")


@dataclass(frozen=True)
class ThemeColors:
    window: str
    base: str
    alternate: str
    card: str
    header: str
    text: str
    muted: str
    border: str
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_text: str
    success: str
    danger: str
    warning: str
    tooltip_bg: str
    tooltip_text: str


LIGHT = ThemeColors(
    window="#f3f5f8",
    base="#ffffff",
    alternate="#f7f9fc",
    card="#ffffff",
    header="#eef2f7",
    text="#1f2328",
    muted="#66707a",
    border="#d8dee6",
    accent="#2d6cdf",
    accent_hover="#2459b8",
    accent_pressed="#1d4a9c",
    accent_text="#ffffff",
    success="#1e8e4a",
    danger="#c0392b",
    warning="#a86400",
    tooltip_bg="#1f2328",
    tooltip_text="#ffffff",
)

DARK = ThemeColors(
    window="#17191d",
    base="#202329",
    alternate="#262a31",
    card="#202329",
    header="#2b3038",
    text="#e7eaee",
    muted="#9aa4af",
    border="#363c45",
    accent="#4f8cff",
    accent_hover="#6ba0ff",
    accent_pressed="#3c6fd6",
    accent_text="#ffffff",
    success="#4cd07d",
    danger="#ff6b6b",
    warning="#ffb74d",
    tooltip_bg="#0f1115",
    tooltip_text="#f2f4f7",
)


def _gsettings(schema: str, key: str) -> str:
    try:
        result = subprocess.run(
            ["gsettings", "get", schema, key],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    return (result.stdout or "").strip().strip("'")


def system_is_dark() -> bool:
    """Определяет тёмную тему рабочего стола (Cinnamon/GNOME/GTK)."""
    gtk_env = os.environ.get("GTK_THEME", "").lower()
    if "dark" in gtk_env:
        return True
    if gtk_env.endswith(":light"):
        return False

    scheme = _gsettings("org.gnome.desktop.interface", "color-scheme").lower()
    if "prefer-dark" in scheme:
        return True

    for schema in (
        "org.cinnamon.desktop.interface",
        "org.gnome.desktop.interface",
    ):
        theme = _gsettings(schema, "gtk-theme").lower()
        if theme:
            return any(marker in theme for marker in _DARK_NAME_MARKERS)

    if "prefer-light" in scheme:
        return False

    app = QApplication.instance()
    if app is not None:
        return app.palette().color(QPalette.Window).lightness() < 128
    return False


def _palette(colors: ThemeColors) -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(colors.window))
    palette.setColor(QPalette.WindowText, QColor(colors.text))
    palette.setColor(QPalette.Base, QColor(colors.base))
    palette.setColor(QPalette.AlternateBase, QColor(colors.alternate))
    palette.setColor(QPalette.ToolTipBase, QColor(colors.tooltip_bg))
    palette.setColor(QPalette.ToolTipText, QColor(colors.tooltip_text))
    palette.setColor(QPalette.Text, QColor(colors.text))
    palette.setColor(QPalette.Button, QColor(colors.card))
    palette.setColor(QPalette.ButtonText, QColor(colors.text))
    palette.setColor(QPalette.BrightText, QColor("#ffffff"))
    palette.setColor(QPalette.Light, QColor(colors.header))
    palette.setColor(QPalette.Midlight, QColor(colors.border))
    palette.setColor(QPalette.Mid, QColor(colors.border))
    palette.setColor(QPalette.Dark, QColor(colors.border))
    palette.setColor(QPalette.Shadow, QColor(colors.tooltip_bg))
    palette.setColor(QPalette.Highlight, QColor(colors.accent))
    palette.setColor(QPalette.HighlightedText, QColor(colors.accent_text))
    palette.setColor(QPalette.Link, QColor(colors.accent))
    palette.setColor(QPalette.LinkVisited, QColor(colors.accent_hover))
    if hasattr(QPalette, "PlaceholderText"):
        palette.setColor(QPalette.PlaceholderText, QColor(colors.muted))

    for group in (QPalette.Disabled,):
        palette.setColor(group, QPalette.WindowText, QColor(colors.muted))
        palette.setColor(group, QPalette.Text, QColor(colors.muted))
        palette.setColor(group, QPalette.ButtonText, QColor(colors.muted))
        palette.setColor(group, QPalette.Base, QColor(colors.alternate))
        palette.setColor(group, QPalette.Button, QColor(colors.alternate))
    return palette


def _stylesheet(c: ThemeColors, font_size: int = 14) -> str:
    return f"""
    * {{ outline: 0; }}

    QWidget {{
        color: {c.text};
        font-size: {font_size}px;
    }}
    QMainWindow, QDialog {{ background: {c.window}; }}

    QMenuBar {{
        background: {c.window};
        border-bottom: 1px solid {c.border};
        padding: 2px 4px;
    }}
    QMenuBar::item {{
        background: transparent;
        padding: 6px 10px;
        border-radius: 6px;
    }}
    QMenuBar::item:selected {{ background: {c.header}; }}
    QMenu {{
        background: {c.card};
        border: 1px solid {c.border};
        border-radius: 8px;
        padding: 6px;
    }}
    QMenu::item {{
        padding: 7px 26px 7px 12px;
        border-radius: 5px;
    }}
    QMenu::item:selected {{
        background: {c.accent};
        color: {c.accent_text};
    }}
    QMenu::separator {{
        height: 1px;
        background: {c.border};
        margin: 4px 8px;
    }}

    QToolBar {{
        background: {c.window};
        border: none;
        border-bottom: 1px solid {c.border};
        spacing: 4px;
        padding: 4px 6px;
    }}
    QToolBar::separator {{
        width: 1px;
        background: {c.border};
        margin: 4px 6px;
    }}
    QToolButton {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: 7px;
        padding: 5px 9px;
    }}
    QToolButton:hover {{
        background: {c.header};
        border-color: {c.border};
    }}
    QToolButton:pressed {{ background: {c.alternate}; }}

    QGroupBox {{
        background: {c.card};
        border: 1px solid {c.border};
        border-radius: 10px;
        margin-top: 13px;
        padding-top: 8px;
        font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 4px;
        color: {c.muted};
    }}

    QLineEdit, QPlainTextEdit, QTextEdit {{
        background: {c.base};
        border: 1px solid {c.border};
        border-radius: 6px;
        padding: 5px 7px;
        selection-background-color: {c.accent};
        selection-color: {c.accent_text};
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
        border-color: {c.accent};
    }}
    QPlainTextEdit, QTextEdit {{ padding: 4px; }}
    QComboBox QAbstractItemView {{
        background: {c.base};
        border: 1px solid {c.border};
        selection-background-color: {c.accent};
        selection-color: {c.accent_text};
    }}

    QPushButton {{
        background: {c.card};
        border: 1px solid {c.border};
        border-radius: 7px;
        padding: 6px 14px;
        min-height: 18px;
    }}
    QPushButton:hover {{
        background: {c.header};
        border-color: {c.accent};
    }}
    QPushButton:pressed {{ background: {c.alternate}; }}
    QPushButton:disabled {{
        color: {c.muted};
        background: {c.alternate};
        border-color: {c.border};
    }}
    QPushButton#connectButton {{
        background: {c.accent};
        color: {c.accent_text};
        border: none;
        border-radius: 8px;
        padding: 8px 18px;
        font-weight: 600;
    }}
    QPushButton#connectButton:hover {{ background: {c.accent_hover}; }}
    QPushButton#connectButton:pressed {{ background: {c.accent_pressed}; }}
    QPushButton#connectButton:disabled {{
        background: {c.border};
        color: {c.muted};
    }}

    QTableWidget, QTableView, QTreeWidget, QListWidget {{
        background: {c.base};
        alternate-background-color: {c.alternate};
        border: 1px solid {c.border};
        border-radius: 8px;
        gridline-color: transparent;
        selection-background-color: {c.accent};
        selection-color: {c.accent_text};
    }}
    QTableWidget::item, QTableView::item {{
        padding: 4px 6px;
        border: none;
    }}
    QTableWidget::item:selected, QTableView::item:selected {{
        background: {c.accent};
        color: {c.accent_text};
    }}
    QHeaderView::section {{
        background: {c.header};
        color: {c.muted};
        border: none;
        border-bottom: 1px solid {c.border};
        border-right: 1px solid {c.border};
        padding: 6px 8px;
        font-weight: 600;
    }}
    QTableCornerButton::section {{
        background: {c.header};
        border: none;
    }}

    QTabWidget::pane {{
        border: 1px solid {c.border};
        border-radius: 8px;
        top: -1px;
        background: {c.base};
    }}
    QTabBar::tab {{
        background: transparent;
        color: {c.muted};
        padding: 7px 14px;
        border: 1px solid transparent;
        border-top-left-radius: 7px;
        border-top-right-radius: 7px;
    }}
    QTabBar::tab:selected {{
        background: {c.base};
        color: {c.text};
        border-color: {c.border};
        border-bottom-color: {c.base};
    }}
    QTabBar::tab:hover {{ color: {c.text}; }}

    QStatusBar {{
        background: {c.window};
        border-top: 1px solid {c.border};
    }}
    QStatusBar::item {{ border: none; }}

    QSplitter::handle {{ background: {c.border}; }}
    QSplitter::handle:horizontal {{ width: 3px; }}
    QSplitter::handle:vertical {{ height: 3px; }}

    QProgressBar {{
        background: {c.alternate};
        border: none;
        border-radius: 3px;
    }}
    QProgressBar::chunk {{
        background: {c.accent};
        border-radius: 3px;
    }}

    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {c.border};
        border-radius: 4px;
        min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {c.muted}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 10px;
        margin: 2px;
    }}
    QScrollBar::handle:horizontal {{
        background: {c.border};
        border-radius: 4px;
        min-width: 24px;
    }}
    QScrollBar::handle:horizontal:hover {{ background: {c.muted}; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}

    QToolTip {{
        background: {c.tooltip_bg};
        color: {c.tooltip_text};
        border: 1px solid {c.border};
        border-radius: 6px;
        padding: 5px 7px;
        font-size: {font_size}px;
    }}

    QLabel#mutedLabel {{ color: {c.muted}; }}
    QLabel#warningLabel {{ color: {c.warning}; }}
    QLabel[state="ok"] {{ color: {c.success}; }}
    QLabel[state="error"] {{ color: {c.danger}; }}

    QFrame#toast {{
        background: {c.card};
        border: 1px solid {c.border};
        border-radius: 12px;
    }}
    QLabel#toastTitle {{
        color: {c.text};
        font-size: {font_size + 1}px;
        font-weight: 600;
    }}
    QLabel#toastBody {{
        color: {c.muted};
        font-size: {font_size}px;
    }}
    QToolButton#toastClose {{
        background: transparent;
        border: none;
        color: {c.muted};
        font-size: {font_size + 4}px;
        padding: 0 4px;
        min-width: 18px;
    }}
    QToolButton#toastClose:hover {{ color: {c.text}; }}

    QCheckBox {{ spacing: 7px; }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid {c.muted};
        border-radius: 4px;
        background: {c.base};
    }}
    QCheckBox::indicator:hover {{ border-color: {c.accent}; }}
    QCheckBox::indicator:checked {{
        background: {c.accent};
        border-color: {c.accent};
        image: url("{_CHECK_ICON}");
    }}
    QCheckBox::indicator:disabled {{
        background: {c.alternate};
        border-color: {c.border};
    }}
    QRadioButton::indicator {{
        width: 16px;
        height: 16px;
    }}
    """


class ThemeManager(QObject):
    mode_changed = pyqtSignal(str, bool)
    style_changed = pyqtSignal()

    def __init__(
        self,
        mode: str = "auto",
        font_size: int = 14,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._mode = normalize_mode(mode)
        self._font_size = self._clamp_font_size(font_size)
        self._dark = False
        self._timer = QTimer(self)
        self._timer.setInterval(8000)
        self._timer.timeout.connect(self._check_system)
        self._timer.start()
        self.apply()

    @staticmethod
    def _clamp_font_size(value: int) -> int:
        try:
            return max(11, min(18, int(value)))
        except (TypeError, ValueError):
            return 14

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def font_size(self) -> int:
        return self._font_size

    @property
    def is_dark(self) -> bool:
        return self._dark

    @property
    def colors(self) -> ThemeColors:
        return DARK if self._dark else LIGHT

    def set_mode(self, mode: str) -> None:
        normalized = normalize_mode(mode)
        if normalized == self._mode:
            # На случай, если тема системы изменилась и нужен перерасчёт.
            self.apply()
            return
        self._mode = normalized
        self.apply()

    def set_font_size(self, size: int) -> None:
        clamped = self._clamp_font_size(size)
        if clamped == self._font_size:
            return
        self._font_size = clamped
        self.apply()

    def apply(self) -> None:
        app = QApplication.instance()
        if app is None:
            return
        dark = system_is_dark() if self._mode == "auto" else self._mode == "dark"
        if app.style().objectName().lower() != "fusion":
            app.setStyle("Fusion")
        app.setPalette(_palette(DARK if dark else LIGHT))
        app.setStyleSheet(_stylesheet(DARK if dark else LIGHT, self._font_size))
        changed = dark != self._dark
        self._dark = dark
        self.style_changed.emit()
        if changed or self._mode == "auto":
            self.mode_changed.emit(self._mode, dark)

    def _check_system(self) -> None:
        if self._mode != "auto":
            return
        dark = system_is_dark()
        if dark != self._dark:
            self.apply()
