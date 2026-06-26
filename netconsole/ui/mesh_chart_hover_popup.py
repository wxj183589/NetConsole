from __future__ import annotations

from html import escape

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QVBoxLayout


class MeshChartHoverPopup(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent, Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.label = QLabel()
        self.label.setTextFormat(Qt.RichText)
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(Qt.NoTextInteraction)
        self.label.setMinimumWidth(280)
        self.label.setMaximumWidth(520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.addWidget(self.label)
        self._last_text = ""
        self.apply_palette()

    def set_tooltip_text(self, text: str) -> bool:
        if text == self._last_text:
            return False
        self._last_text = text
        self.label.setText(_plain_text_to_html(text))
        self.adjustSize()
        return True

    def show_at(self, global_pos: QPoint, *, resize: bool = True) -> None:
        if resize:
            self.adjustSize()
        position = self._best_position(global_pos)
        if not self.isVisible():
            self.move(position)
            self.show()
        elif (self.pos() - position).manhattanLength() >= 4:
            self.move(position)

    def clear_cached_text(self) -> None:
        self._last_text = ""

    def apply_palette(self) -> None:
        self.setStyleSheet(
            """
            MeshChartHoverPopup {{
                background: #111827;
                color: #f9fafb;
                border: 1px solid #38bdf8;
                border-radius: 8px;
            }}
            QLabel {{
                background: transparent;
                color: #f9fafb;
                font-size: 14px;
                line-height: 1.45;
            }}
            """
        )

    def _best_position(self, global_pos: QPoint) -> QPoint:
        screen = QGuiApplication.screenAt(global_pos) or QGuiApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else QApplication.primaryScreen().availableGeometry()
        width = self.width()
        height = self.height()
        offset_x = 16
        offset_y = 18
        x = global_pos.x() + offset_x if global_pos.x() + offset_x + width <= available.right() else global_pos.x() - offset_x - width
        y = global_pos.y() + offset_y if global_pos.y() + offset_y + height <= available.bottom() else global_pos.y() - offset_y - height
        x = max(available.left(), min(x, available.right() - width))
        y = max(available.top(), min(y, available.bottom() - height))
        return QPoint(x, y)


def _plain_text_to_html(text: str) -> str:
    blocks: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            blocks.append("<hr/>")
            continue
        safe = escape(stripped)
        if stripped.endswith(":"):
            blocks.append(f"<p style='margin:6px 0 2px 0;'><b>{safe}</b></p>")
        elif ":" in stripped:
            label, value = safe.split(":", 1)
            blocks.append(f"<p style='margin:3px 0;'><b>{label}:</b><b>{value}</b></p>")
        else:
            blocks.append(f"<p style='margin:3px 0;'><b>{safe}</b></p>")
    return "<div style='white-space:normal;'>" + "".join(blocks) + "</div>"
