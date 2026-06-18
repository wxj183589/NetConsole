from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from netconsole.models.device import Device
from netconsole.services.h3c_ac_collect_service import collect_h3c_ac_resources, collect_h3c_fit_ap_optical
from netconsole.ui.batch_collect_worker import BATCH_CONCURRENCY


class AcResourceCollectThread(QThread):
    collect_started = Signal()
    collect_finished = Signal(object)
    collect_failed = Signal(str)

    def __init__(self, device: Device, site_name: str, concurrency: int = BATCH_CONCURRENCY, parent=None, max_workers: int | None = None) -> None:
        super().__init__(parent)
        self.device = device
        self.site_name = site_name
        self.concurrency = int(max_workers if max_workers is not None else concurrency)

    def run(self) -> None:
        self.collect_started.emit()
        try:
            result = collect_h3c_ac_resources(self.device, self.site_name)
        except Exception as exc:
            self.collect_failed.emit(str(exc))
            return
        self.collect_finished.emit(result)


class FitApOpticalCollectThread(QThread):
    collect_started = Signal()
    collect_finished = Signal(object)
    collect_failed = Signal(str)

    def __init__(self, device: Device, site_name: str, concurrency: int = BATCH_CONCURRENCY, parent=None, max_workers: int | None = None) -> None:
        super().__init__(parent)
        self.device = device
        self.site_name = site_name
        self.concurrency = int(max_workers if max_workers is not None else concurrency)

    def run(self) -> None:
        self.collect_started.emit()
        try:
            result = collect_h3c_fit_ap_optical(self.device, self.site_name, max_workers=self.concurrency)
        except Exception as exc:
            self.collect_failed.emit(str(exc))
            return
        self.collect_finished.emit(result)
