from __future__ import annotations

from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QSpinBox


class NoWheelSpinBox(QSpinBox):
    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 - Qt override
        event.ignore()


class NoWheelDoubleSpinBox(QDoubleSpinBox):
    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 - Qt override
        event.ignore()


class NoWheelComboBox(QComboBox):
    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 - Qt override
        if self.view().isVisible():
            super().wheelEvent(event)
            return
        event.ignore()
