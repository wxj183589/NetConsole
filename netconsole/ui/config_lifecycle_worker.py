from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from netconsole.models.device import Device
from netconsole.services.config_lifecycle_service import ConfigLifecycleService, ConfigOperationResult, run_batch_config_download


class ConfigLifecycleWorker(QThread):
    result_ready = Signal(object)

    def __init__(self, action: str, service: ConfigLifecycleService, device: Device | None = None, devices: list[Device] | None = None, parent=None) -> None:
        super().__init__(parent)
        self.action = action
        self.service = service
        self.device = device
        self.devices = list(devices or [])

    def run(self) -> None:
        if self.action == "batch_fetch":
            result = run_batch_config_download(self.devices, lambda: self.service)
        elif self.device is None:
            result = ConfigOperationResult(False, "", "", [], error_message="No device selected.")
        elif self.action == "save":
            result = self.service.save_force(self.device)
        elif self.action == "fetch":
            result = self.service.fetch_configs(self.device)
        else:
            result = ConfigOperationResult(False, str(self.device.device_uuid or ""), "", [], error_message=f"Unknown action: {self.action}")
        self.result_ready.emit(result)
