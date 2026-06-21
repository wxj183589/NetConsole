from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from time import perf_counter

from PySide6.QtCore import QThread, Signal

from netconsole.core.sources.switch_source import build_switch_data_lookup
from netconsole.core.paths import PathResolver
from netconsole.repositories.ac_repository import AcRepository
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.rail_transit.trackside_optical_collection import (
    DEFAULT_TRACKSIDE_OPTICAL_CONCURRENCY,
    TracksideOpticalSessionResult,
    collect_trackside_optical,
)
from netconsole.services.trackside_ap_business import build_trackside_ap_business_rows


@dataclass(frozen=True)
class TracksideApBusinessLoadResult:
    generation: int
    site_name: str
    rows: list[dict[str, object | None]]
    device_count: int
    query_ms: int
    build_ms: int


def load_trackside_ap_business_snapshot(repository: DeviceRepository, site_name: str, generation: int) -> TracksideApBusinessLoadResult:
    query_start = perf_counter()
    fact_repository = DeviceFactRepository(repository.database)
    ac_repository = AcRepository(repository.database)
    devices = repository.list()
    interfaces_by_device = {str(device.device_uuid or ""): fact_repository.list_device_interfaces(str(device.device_uuid or "")) for device in devices}
    optical_by_device = {str(device.device_uuid or ""): fact_repository.list_optical_modules(str(device.device_uuid or "")) for device in devices}
    lldp_by_device = {str(device.device_uuid or ""): fact_repository.list_lldp_neighbors(str(device.device_uuid or "")) for device in devices}
    fit_ap_optical_rows = ac_repository.list_all_fit_ap_optical()
    fit_ap_resource_rows = ac_repository.list_all_fit_ap_resources_with_metadata()
    query_ms = int((perf_counter() - query_start) * 1000)

    build_start = perf_counter()
    rows = build_trackside_ap_business_rows(
        devices,
        interfaces_by_device,
        optical_by_device,
        fit_ap_optical_rows,
        lldp_by_device,
        fit_ap_resource_rows,
        build_switch_data_lookup(devices, optical_by_device),
    )
    build_ms = int((perf_counter() - build_start) * 1000)
    return TracksideApBusinessLoadResult(generation, site_name, rows, len(devices), query_ms, build_ms)


class TracksideApBusinessLoadThread(QThread):
    load_finished = Signal(object)
    load_failed = Signal(int, str)

    def __init__(self, repository: DeviceRepository, site_name: str, generation: int, parent=None) -> None:
        super().__init__(parent)
        self.repository = repository
        self.site_name = site_name
        self.generation = generation

    def run(self) -> None:
        try:
            result = load_trackside_ap_business_snapshot(self.repository, self.site_name, self.generation)
        except Exception as exc:
            self.load_failed.emit(self.generation, str(exc))
            return
        self.load_finished.emit(result)


class TracksideOpticalCollectThread(QThread):
    progress_changed = Signal(int, int)
    collect_finished = Signal(object)
    collect_failed = Signal(str)

    def __init__(
        self,
        repository: DeviceRepository,
        site_name: str,
        paths: PathResolver,
        trackside_rows: list[dict[str, object | None]],
        concurrency: int = DEFAULT_TRACKSIDE_OPTICAL_CONCURRENCY,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.repository = repository
        self.site_name = site_name
        self.paths = paths
        self.trackside_rows = trackside_rows
        self.concurrency = concurrency
        self._cancel_event = Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            result: TracksideOpticalSessionResult = collect_trackside_optical(
                self.repository,
                self.site_name,
                self.paths,
                self.trackside_rows,
                self.concurrency,
                self._cancel_event,
                self.progress_changed.emit,
            )
        except Exception as exc:
            self.collect_failed.emit(str(exc))
            return
        self.collect_finished.emit(result)
