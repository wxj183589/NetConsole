from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHeaderView, QTableWidget

from netconsole.core.settings import SettingsStore


class TableColumnState:
    def __init__(self, settings: SettingsStore, table: QTableWidget, key: str, default_widths: dict[str, int], minimum_widths: dict[str, int] | None = None) -> None:
        self.settings = settings
        self.table = table
        self.key = key
        self.default_widths = default_widths
        self.minimum_widths = minimum_widths or {}
        self._restoring = False
        self._timer = QTimer(table)
        self._timer.setSingleShot(True)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self.save_now)
        table.horizontalHeader().sectionResized.connect(self._schedule_save)

    def restore(self) -> None:
        stored = self.settings.get_value(self.key, {})
        if not isinstance(stored, dict):
            stored = {}
        header = self.table.horizontalHeader()
        fields = self._fields()
        self._restoring = True
        try:
            header.setSectionResizeMode(QHeaderView.Interactive)
            header.setStretchLastSection(False)
            for column, field in enumerate(fields):
                width = stored.get(field, self.default_widths.get(field, 120))
                self.table.setColumnWidth(column, self._clamp(field, width))
        finally:
            self._restoring = False

    def save_now(self) -> None:
        fields = self._fields()
        widths = {field: self._clamp(field, self.table.columnWidth(column)) for column, field in enumerate(fields)}
        self.settings.set_value(self.key, widths)

    def _schedule_save(self, *_args) -> None:
        if not self._restoring:
            self._timer.start()

    def _clamp(self, field: str, width: object) -> int:
        try:
            value = int(width)
        except (TypeError, ValueError):
            value = self.default_widths.get(field, 120)
        return max(50, self.minimum_widths.get(field, 50), value)

    def _fields(self) -> list[str]:
        fields = self.table.property("netconsole_column_fields")
        if isinstance(fields, (list, tuple)):
            return [str(field) for field in fields][: self.table.columnCount()]
        return [str(column) for column in range(self.table.columnCount())]
