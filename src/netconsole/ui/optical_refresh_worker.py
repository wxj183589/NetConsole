from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from netconsole.models.device import Device
from netconsole.services.h3c_optical_refresh_service import refresh_h3c_device_optical


class OpticalRefreshThread(QThread):
    refresh_started = Signal()
    refresh_finished = Signal(object)
    refresh_failed = Signal(str)

    def __init__(self, device: Device, site_name: str, concurrency: int = 20, parent=None) -> None:
        super().__init__(parent)
        self.device = device
        self.site_name = site_name
        self.concurrency = concurrency

    def run(self) -> None:
        self.refresh_started.emit()
        try:
            result = refresh_h3c_device_optical(self.device, self.site_name)
        except Exception as exc:
            self.refresh_failed.emit(str(exc))
            return
        self.refresh_finished.emit(result)
