from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHeaderView, QTableWidget

from netconsole.core.settings import SettingsStore


class MeshTableColumnState:
    def __init__(self, settings: SettingsStore, table: QTableWidget, key: str, default_widths: list[int]) -> None:
        self.settings = settings
        self.table = table
        self.key = key
        self.default_widths = default_widths
        self._restoring = False
        self._timer = QTimer(table)
        self._timer.setSingleShot(True)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._save_now)
        table.horizontalHeader().sectionResized.connect(self._schedule_save)

    def restore(self) -> None:
        widths = self.settings.get_value(self.key, None)
        if not isinstance(widths, list):
            widths = self.default_widths
        header = self.table.horizontalHeader()
        self._restoring = True
        try:
            header.setSectionResizeMode(QHeaderView.Interactive)
            header.setStretchLastSection(False)
            for column in range(self.table.columnCount()):
                width = widths[column] if column < len(widths) else (self.default_widths[column] if column < len(self.default_widths) else 120)
                try:
                    width = int(width)
                except (TypeError, ValueError):
                    width = 120
                if width >= 40:
                    self.table.setColumnWidth(column, width)
        finally:
            self._restoring = False

    def _schedule_save(self, *_args) -> None:
        if self._restoring:
            return
        self._timer.start()

    def _save_now(self) -> None:
        widths = [max(40, self.table.columnWidth(column)) for column in range(self.table.columnCount())]
        self.settings.set_value(self.key, widths)
