from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from netconsole.models.device import Device
from netconsole.services.h3c_ac_collect_service import collect_h3c_ac_resources, collect_h3c_fit_ap_optical
from netconsole.ui.batch_collect_worker import BATCH_CONCURRENCY


class AcResourceCollectThread(QThread):
    collect_started = Signal()
    progress = Signal(str)
    collect_finished = Signal(object)
    collect_failed = Signal(str)

    def __init__(self, device: Device, site_name: str, concurrency: int = BATCH_CONCURRENCY, parent=None, max_workers: int | None = None) -> None:
        super().__init__(parent)
        self.device = device
        self.site_name = site_name
        self.concurrency = int(max_workers if max_workers is not None else concurrency)
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        self.collect_started.emit()
        try:
            result = collect_h3c_ac_resources(
                self.device,
                self.site_name,
                progress=self.progress.emit,
                should_cancel=lambda: self._cancel_requested,
            )
        except Exception as exc:
            self.collect_failed.emit(str(exc))
            return
        self.collect_finished.emit(result)


class FitApOpticalCollectThread(QThread):
    collect_started = Signal()
    progress = Signal(str)
    collect_finished = Signal(object)
    collect_failed = Signal(str)

    def __init__(
        self,
        device: Device,
        site_name: str,
        concurrency: int = BATCH_CONCURRENCY,
        parent=None,
        max_workers: int | None = None,
        target_ap_uuids: list[str] | None = None,
        target_ap_macs: list[str] | None = None,
        target_ap_names: list[str] | None = None,
        target_stations: list[str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.device = device
        self.site_name = site_name
        self.concurrency = int(max_workers if max_workers is not None else concurrency)
        self.target_ap_uuids = target_ap_uuids
        self.target_ap_macs = target_ap_macs
        self.target_ap_names = target_ap_names
        self.target_stations = target_stations
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        self.collect_started.emit()
        try:
            result = collect_h3c_fit_ap_optical(
                self.device,
                self.site_name,
                max_workers=self.concurrency,
                progress=self.progress.emit,
                should_cancel=lambda: self._cancel_requested,
                target_ap_uuids=self.target_ap_uuids,
                target_ap_macs=self.target_ap_macs,
                target_ap_names=self.target_ap_names,
                target_stations=self.target_stations,
            )
        except Exception as exc:
            self.collect_failed.emit(str(exc))
            return
        self.collect_finished.emit(result)
