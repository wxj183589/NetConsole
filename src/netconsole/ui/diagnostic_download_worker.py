from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from netconsole.models.device import Device
from netconsole.services.diagnostic_download_service import DiagnosticDownloadService, run_batch_diagnostic_download


class DiagnosticDownloadWorker(QThread):
    result_ready = Signal(object)

    def __init__(self, site_name: str, devices: list[Device], parent=None) -> None:
        super().__init__(parent)
        self.site_name = site_name
        self.devices = list(devices)

    def run(self) -> None:
        service = DiagnosticDownloadService(self.site_name)
        if len(self.devices) == 1:
            result = [service.download(self.devices[0])]
        else:
            result = run_batch_diagnostic_download(self.devices, lambda: service)
        self.result_ready.emit(result)
