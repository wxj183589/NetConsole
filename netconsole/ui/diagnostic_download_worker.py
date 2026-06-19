from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from netconsole.models.device import Device
from netconsole.services.diagnostic_download_service import DiagnosticDownloadService, run_batch_diagnostic_download


class DiagnosticDownloadWorker(QThread):
    result_ready = Signal(object)

    def __init__(self, service: DiagnosticDownloadService, devices: list[Device], parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.devices = list(devices)

    def run(self) -> None:
        if len(self.devices) == 1:
            result = [self.service.download(self.devices[0])]
        else:
            result = run_batch_diagnostic_download(self.devices, lambda: self.service)
        self.result_ready.emit(result)
