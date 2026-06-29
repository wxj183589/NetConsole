from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class AppEvents(QObject):
    ac_summary_changed = Signal(str)


app_events = AppEvents()
