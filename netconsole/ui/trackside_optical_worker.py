from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from threading import Event
from time import perf_counter

from PySide6.QtCore import QThread, Signal

from netconsole.core import app_logger
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
from netconsole.services.offline_ap_ledger import build_device_lookup_by_name, build_latest_ap_history_indexes, build_offline_ap_ledger
from netconsole.services.ap_online_overview import AP_ONLINE_OVERVIEW_COLUMNS, ApOnlineOverviewService
from netconsole.services.trackside_ap_business import (
    AP_OPTICAL_TREATMENT_RECORD_COLUMNS,
    NEW_ONLINE_AP_OVERVIEW_COLUMNS,
    TRACKSIDE_AP_BUSINESS_EXPORT_COLUMNS,
    build_ap_optical_treatment_records,
    build_new_online_ap_overview_rows,
    build_trackside_ap_business_rows,
    enrich_trackside_export_rows,
    export_trackside_ap_business_xlsx,
    filter_station_switch_devices,
)
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
    devices = filter_station_switch_devices(repository.list(), repository.database, site_name)
    interfaces_by_device = {str(device.device_uuid or ""): fact_repository.list_device_interfaces(str(device.device_uuid or "")) for device in devices}
    optical_by_device = {str(device.device_uuid or ""): fact_repository.list_optical_modules(str(device.device_uuid or "")) for device in devices}
    lldp_by_device = {str(device.device_uuid or ""): fact_repository.list_lldp_neighbors(str(device.device_uuid or "")) for device in devices}
    fit_ap_optical_rows = ac_repository.list_all_fit_ap_optical()
    fit_ap_resource_rows = ac_repository.list_all_fit_ap_resources_with_metadata()
    active_plan = ac_repository.get_active_trackside_pvid_plan()
    switch_lookup = build_switch_data_lookup(devices, optical_by_device)
    latest_lldp, latest_optical = build_latest_ap_history_indexes(ac_repository, fit_ap_resource_rows)
    _offline_stats, offline_ledger_rows = build_offline_ap_ledger(
        fit_ap_resources=fit_ap_resource_rows,
        latest_lldp_by_ap=latest_lldp,
        latest_optical_by_ap=latest_optical,
        device_lookup_by_name=build_device_lookup_by_name(devices),
    )
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
        switch_lookup,
        active_plan,
        offline_ledger_rows,
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


class TracksideApBusinessExportThread(QThread):
    stage_changed = Signal(str)
    export_finished = Signal(object)
    export_failed = Signal(str)

    def __init__(
        self,
        repository: DeviceRepository,
        site_name: str,
        path: Path,
        headers: list[str],
        overview_headers: list[str],
        new_online_headers: list[str],
        new_online_sheet_title: str,
        optical_treatment_headers: list[str],
        optical_treatment_sheet_title: str,
        offline_stats_headers: list[str],
        offline_ledger_headers: list[str],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.repository = repository
        self.site_name = site_name
        self.path = Path(path)
        self.headers = headers
        self.overview_headers = overview_headers
        self.new_online_headers = new_online_headers
        self.new_online_sheet_title = new_online_sheet_title
        self.optical_treatment_headers = optical_treatment_headers
        self.optical_treatment_sheet_title = optical_treatment_sheet_title
        self.offline_stats_headers = offline_stats_headers
        self.offline_ledger_headers = offline_ledger_headers

    def run(self) -> None:
        tmp_path = self.path.with_name(f"{self.path.stem}.tmp{self.path.suffix}")
        profile_start = perf_counter()

        def log_phase(phase: str, start: float, **values: object) -> None:
            elapsed_ms = int((perf_counter() - start) * 1000)
            details = " ".join(f"{key}={value}" for key, value in values.items())
            app_logger.log_info("TRACKSIDE_EXPORT_PROFILE", f"phase={phase} elapsed_ms={elapsed_ms}" + (f" {details}" if details else ""))

        try:
            self.stage_changed.emit("trackside.export.progress_load")
            phase_start = perf_counter()
            snapshot = load_trackside_ap_business_snapshot(self.repository, self.site_name, generation=0)
            log_phase("load_trackside_rows", phase_start, rows=len(snapshot.rows))
            ac_repository = AcRepository(self.repository.database)
            fact_repository = DeviceFactRepository(self.repository.database)
            phase_start = perf_counter()
            resources = ac_repository.list_all_fit_ap_resources_with_metadata()
            log_phase("load_fit_ap_resources", phase_start, rows=len(resources))
            phase_start = perf_counter()
            ac_device_names = {str(device.device_uuid or ""): device.name for device in self.repository.list() if str(device.device_uuid or "")}
            resources = [
                {
                    **row,
                    "ac_device_name": row.get("ac_device_name") or ac_device_names.get(str(row.get("ac_device_uuid") or "")),
                }
                for row in resources
            ]
            log_phase("load_ac_devices", phase_start, rows=len(ac_device_names))
            phase_start = perf_counter()
            optical_rows = ac_repository.list_all_fit_ap_optical()
            log_phase("load_fit_ap_optical", phase_start, rows=len(optical_rows))
            phase_start = perf_counter()
            resource_history_rows = ac_repository.list_all_fit_ap_resource_history()
            log_phase("load_fit_ap_resource_history", phase_start, rows=len(resource_history_rows))
            phase_start = perf_counter()
            ap_optical_history_rows = ac_repository.list_all_ap_optical_history()
            log_phase("load_ap_optical_history", phase_start, rows=len(ap_optical_history_rows))
            phase_start = perf_counter()
            capacity_details = ac_repository.list_active_trackside_plan_capacity_details()
            if not capacity_details:
                capacity_details = ac_repository.list_station_ap_capacity_details()
            log_phase("load_capacity_details", phase_start, rows=len(capacity_details))
            phase_start = perf_counter()
            overview_rows = ApOnlineOverviewService.build_rows(
                metadata_rows=ac_repository.list_fit_ap_metadata(),
                fit_ap_resources=resources,
                optical_rows=optical_rows,
                capacity_details=capacity_details,
            )
            log_phase("build_ap_online_overview", phase_start, rows=len(overview_rows))
            phase_start = perf_counter()
            latest_lldp, latest_optical = build_latest_ap_history_indexes(ac_repository, resources)
            log_phase("build_latest_ap_history_indexes", phase_start, resources=len(resources))
            phase_start = perf_counter()
            devices = filter_station_switch_devices(self.repository.list(), self.repository.database, self.site_name)
            switch_optical_history_rows = fact_repository.list_all_optical_history([str(device.device_uuid or "") for device in devices])
            log_phase("load_switch_optical_history", phase_start, devices=len(devices), rows=len(switch_optical_history_rows))
            phase_start = perf_counter()
            offline_stats, offline_ledger_rows = build_offline_ap_ledger(
                fit_ap_resources=resources,
                latest_lldp_by_ap=latest_lldp,
                latest_optical_by_ap=latest_optical,
                device_lookup_by_name=build_device_lookup_by_name(devices),
                resource_history_rows=resource_history_rows,
            )
            log_phase("build_offline_ap_ledger", phase_start, rows=len(offline_ledger_rows))
            phase_start = perf_counter()
            rows = enrich_trackside_export_rows(
                snapshot.rows,
                fact_repository,
                ac_repository,
                switch_optical_history_rows=switch_optical_history_rows,
                ap_optical_history_rows=ap_optical_history_rows,
            )
            log_phase("build_history_compare", phase_start, rows=len(rows))
            phase_start = perf_counter()
            new_online_ap_rows = build_new_online_ap_overview_rows(resources, resource_history_rows, snapshot.rows)
            log_phase("build_new_online_ap_overview", phase_start, rows=len(new_online_ap_rows))
            phase_start = perf_counter()
            optical_treatment_rows = build_ap_optical_treatment_records(
                rows,
                ap_optical_history_rows,
                switch_optical_history_rows,
                resources,
                resource_history_rows,
                offline_ledger_rows=offline_ledger_rows,
            )
            log_phase("build_optical_treatment", phase_start, rows=len(optical_treatment_rows), ap_history=len(ap_optical_history_rows), switch_history=len(switch_optical_history_rows))
            self.stage_changed.emit("trackside.export.progress_write")
            tmp_path.parent.mkdir(parents=True, exist_ok=True)
            phase_start = perf_counter()
            export_trackside_ap_business_xlsx(
                tmp_path,
                rows,
                TRACKSIDE_AP_BUSINESS_EXPORT_COLUMNS,
                self.headers,
                overview_rows,
                AP_ONLINE_OVERVIEW_COLUMNS,
                self.overview_headers,
                new_online_ap_rows,
                NEW_ONLINE_AP_OVERVIEW_COLUMNS,
                self.new_online_headers,
                self.new_online_sheet_title,
                optical_treatment_rows,
                AP_OPTICAL_TREATMENT_RECORD_COLUMNS,
                self.optical_treatment_headers,
                self.optical_treatment_sheet_title,
                offline_stats,
                offline_ledger_rows,
                self.offline_stats_headers,
                self.offline_ledger_headers,
                progress_callback=self.stage_changed.emit,
            )
            log_phase("write_excel", phase_start, rows=len(rows), treatment_rows=len(optical_treatment_rows))
            phase_start = perf_counter()
            os.replace(tmp_path, self.path)
            log_phase("save_excel", phase_start, path=self.path.name)
        except Exception as exc:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception:
                pass
            self.export_failed.emit(str(exc))
            return
        log_phase("total", profile_start)
        self.export_finished.emit({"path": self.path, "row_count": len(rows)})


class TracksideOpticalCollectThread(QThread):
    progress_changed = Signal(int, int)
    stage_changed = Signal(str)
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
        target_station: str | None = None,
        target_ap_uuid: str | None = None,
        target_ap_mac: str | None = None,
        target_ap_name: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.repository = repository
        self.site_name = site_name
        self.paths = paths
        self.trackside_rows = trackside_rows
        self.concurrency = concurrency
        self.target_station = target_station
        self.target_ap_uuid = target_ap_uuid
        self.target_ap_mac = target_ap_mac
        self.target_ap_name = target_ap_name
        self._cancel_event = Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            self.stage_changed.emit("trackside_ap.stage_prepare")
            result: TracksideOpticalSessionResult = collect_trackside_optical(
                self.repository,
                self.site_name,
                self.paths,
                self.trackside_rows,
                self.concurrency,
                self._cancel_event,
                self.progress_changed.emit,
                self.stage_changed.emit,
                target_station=self.target_station,
                target_ap_uuid=self.target_ap_uuid,
                target_ap_mac=self.target_ap_mac,
                target_ap_name=self.target_ap_name,
            )
        except Exception as exc:
            self.collect_failed.emit(str(exc))
            return
        self.stage_changed.emit("trackside_ap.stage_done")
        self.collect_finished.emit(result)
