from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class LoadingSpinner(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.angle = 0
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._tick)
        self.setFixedSize(48, 48)

    def start(self) -> None:
        self.timer.start()
        self.show()

    def stop(self) -> None:
        self.timer.stop()
        self.hide()

    def _tick(self) -> None:
        self.angle = (self.angle + 30) % 360
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        center = QPointF(self.width() / 2, self.height() / 2)
        radius = min(self.width(), self.height()) / 2 - 6
        for index in range(12):
            alpha = 45 + index * 17
            pen = QPen(QColor(96, 165, 250, alpha), 4, Qt.SolidLine, Qt.RoundCap)
            painter.setPen(pen)
            painter.save()
            painter.translate(center)
            painter.rotate(self.angle + index * 30)
            painter.drawLine(QPointF(0, -radius), QPointF(0, -radius + 10))
            painter.restore()
        super().paintEvent(event)


class LoadingOverlay(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("loadingOverlay")
        self.setStyleSheet(
            """
            QWidget#loadingOverlay {
                background: rgba(17, 24, 39, 165);
                border: 1px solid rgba(148, 163, 184, 80);
            }
            QLabel {
                color: #f8fafc;
                background: transparent;
            }
            """
        )
        self.spinner = LoadingSpinner(self)
        self.message_label = QLabel()
        self.message_label.setAlignment(Qt.AlignCenter)
        font = QFont()
        font.setPointSize(12)
        font.setBold(True)
        self.message_label.setFont(font)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.spinner, 0, Qt.AlignCenter)
        layout.addWidget(self.message_label, 0, Qt.AlignCenter)
        self.hide()

    def show_loading(self, message: str) -> None:
        self.message_label.setText(message)
        self._fit_parent()
        self.raise_()
        self.show()
        self.spinner.start()

    def hide_loading(self) -> None:
        self.spinner.stop()
        self.hide()

    def resizeEvent(self, event) -> None:
        self._fit_parent()
        super().resizeEvent(event)

    def _fit_parent(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(QRect(0, 0, parent.width(), parent.height()))
