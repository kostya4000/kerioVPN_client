"""Всплывающие уведомления в стиле приложения (вместо системных)."""

from __future__ import annotations

from typing import Callable, Optional

from PyQt5.QtCore import (
    QEasingCurve,
    QObject,
    QPropertyAnimation,
    QTimer,
    Qt,
    pyqtSignal,
)
from PyQt5.QtGui import QColor, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

KIND_COLORS = {
    "info": "#4f8cff",
    "success": "#2ecc71",
    "warning": "#f1c40f",
    "error": "#e74c3c",
}


def _kind_pixmap(kind: str, size: int = 22) -> QPixmap:
    color = QColor(KIND_COLORS.get(kind, KIND_COLORS["info"]))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)
    painter.drawEllipse(2, 2, size - 4, size - 4)
    painter.end()
    return pixmap


class Toast(QWidget):
    """Самостоятельное всплывающее уведомление с темой приложения."""

    activated = pyqtSignal()
    closed = pyqtSignal(object)

    def __init__(
        self,
        title: str,
        message: str,
        kind: str = "info",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._closing = False
        self._fade_in: Optional[QPropertyAnimation] = None
        self._fade_out: Optional[QPropertyAnimation] = None

        self.setWindowFlags(
            Qt.Tool
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(410)
        self.setCursor(Qt.PointingHandCursor)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)

        frame = QFrame(self)
        frame.setObjectName("toast")
        shadow = QGraphicsDropShadowEffect(frame)
        shadow.setBlurRadius(30)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 110))
        frame.setGraphicsEffect(shadow)
        outer.addWidget(frame)

        frame_layout = QHBoxLayout(frame)
        frame_layout.setContentsMargins(14, 12, 10, 12)
        frame_layout.setSpacing(10)

        icon = QLabel(frame)
        icon.setPixmap(_kind_pixmap(kind, 24))
        icon.setFixedSize(24, 24)
        icon.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        frame_layout.addWidget(icon, 0, Qt.AlignTop)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        self.title_label = QLabel(title, frame)
        self.title_label.setObjectName("toastTitle")
        self.title_label.setWordWrap(True)
        self.body_label = QLabel(message, frame)
        self.body_label.setObjectName("toastBody")
        self.body_label.setWordWrap(True)
        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.body_label)
        frame_layout.addLayout(text_layout, 1)

        close_button = QToolButton(frame)
        close_button.setObjectName("toastClose")
        close_button.setText("×")
        close_button.setToolTip("Закрыть")
        close_button.setCursor(Qt.PointingHandCursor)
        close_button.clicked.connect(self.close_animated)
        frame_layout.addWidget(close_button, 0, Qt.AlignTop)

        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.setInterval(6500)
        self._auto_timer.timeout.connect(self.close_animated)

    def show_animated(self) -> None:
        self.adjustSize()
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self._auto_timer.start()
        self._fade_in = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_in.setDuration(180)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setEasingCurve(QEasingCurve.OutCubic)
        self._fade_in.start()

    def close_animated(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._auto_timer.stop()
        self._fade_out = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_out.setDuration(160)
        self._fade_out.setStartValue(self.windowOpacity())
        self._fade_out.setEndValue(0.0)
        self._fade_out.setEasingCurve(QEasingCurve.InCubic)
        self._fade_out.finished.connect(self._finish_close)
        self._fade_out.start()

    def _finish_close(self) -> None:
        self.closed.emit(self)
        self.close()
        self.deleteLater()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._auto_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        if not self._closing:
            self._auto_timer.start()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.activated.emit()
            self.close_animated()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class ToastManager(QObject):
    """Показывает и складывает уведомления в правом нижнем углу."""

    def __init__(
        self,
        on_activate: Optional[Callable[[], None]] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._on_activate = on_activate
        self._toasts: list[Toast] = []

    def show_message(self, title: str, message: str, kind: str = "info") -> None:
        toast = Toast(title, message, kind)
        toast.activated.connect(self._activate)
        toast.closed.connect(self._remove)
        self._toasts.append(toast)
        self._reposition()
        toast.show_animated()
        # После показа QLabel может пересчитать высоту — поправляем позиции.
        QTimer.singleShot(0, self._reposition)

    def _activate(self) -> None:
        if self._on_activate is not None:
            self._on_activate()

    def _remove(self, toast: Toast) -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
        self._reposition()

    def _reposition(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geometry = screen.availableGeometry()
        y = geometry.top() + 16
        for toast in reversed(self._toasts):
            toast.adjustSize()
            x = geometry.right() - toast.width() - 16
            toast.move(x, y)
            y += toast.height() + 8

    def close_all(self) -> None:
        for toast in list(self._toasts):
            toast.close_animated()
