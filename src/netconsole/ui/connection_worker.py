from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from netconsole.models.device import Device
from netconsole.services.netmiko_connection import test_device_connection


class DeviceConnectionTestThread(QThread):
    result_ready = Signal(object)

    def __init__(self, device: Device, parent=None) -> None:
        super().__init__(parent)
        self.device = device

    def run(self) -> None:
        self.result_ready.emit(test_device_connection(self.device))
