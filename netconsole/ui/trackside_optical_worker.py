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
from netconsole.services.trackside_ap_business import is_trackside_ap_interface


@dataclass(frozen=True)
class TracksideApBusinessLoadResult:
    generation: int
    site_name: str
    rows: list[dict[str, object | None]]
    device_count: int
    query_ms: int
    build_ms: int
    interface_count: int = 0
    optical_count: int = 0
    lldp_count: int = 0
    fit_ap_optical_count: int = 0
    fit_ap_resource_count: int = 0
    candidate_ap_interface_count: int = 0
    row_count: int = 0
    empty_reason: str = ""


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
    active_plan = ac_repository.get_active_trackside_pvid_plan()
    interface_count = sum(len(rows) for rows in interfaces_by_device.values())
    optical_count = sum(len(rows) for rows in optical_by_device.values())
    lldp_count = sum(len(rows) for rows in lldp_by_device.values())
    candidate_ap_interface_count = sum(
        1
        for device in devices
        for row in interfaces_by_device.get(str(device.device_uuid or ""), [])
        if is_trackside_ap_interface(device, row, active_plan)[0]
    )
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
        active_plan,
    )
    build_ms = int((perf_counter() - build_start) * 1000)
    row_count = len(rows)
    empty_reason = ""
    if row_count == 0:
        empty_reason = _trackside_empty_reason(
            len(devices),
            interface_count,
            candidate_ap_interface_count,
            optical_count,
            lldp_count,
            len(fit_ap_optical_rows),
            len(fit_ap_resource_rows),
        )
    return TracksideApBusinessLoadResult(
        generation,
        site_name,
        rows,
        len(devices),
        query_ms,
        build_ms,
        interface_count,
        optical_count,
        lldp_count,
        len(fit_ap_optical_rows),
        len(fit_ap_resource_rows),
        candidate_ap_interface_count,
        row_count,
        empty_reason,
    )


def _trackside_empty_reason(
    device_count: int,
    interface_count: int,
    candidate_ap_interface_count: int,
    optical_count: int,
    lldp_count: int,
    fit_ap_optical_count: int,
    fit_ap_resource_count: int,
) -> str:
    if device_count == 0:
        return "trackside.empty.no_devices"
    if interface_count == 0:
        return "trackside.empty.no_interfaces"
    if candidate_ap_interface_count == 0:
        return "trackside.empty.no_ap_interfaces"
    if optical_count == 0 and fit_ap_optical_count == 0 and fit_ap_resource_count == 0:
        return "trackside.empty.no_optical_or_fit"
    if lldp_count == 0 and fit_ap_optical_count == 0:
        return "trackside.empty.no_lldp_or_fit"
    if fit_ap_resource_count == 0:
        return "trackside.empty.no_fit_ap_resource"
    if fit_ap_optical_count == 0:
        return "trackside.empty.no_fit_ap_optical"
    return "trackside.empty.no_rows"


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
