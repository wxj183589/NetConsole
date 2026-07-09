from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from threading import Event

from PySide6.QtCore import QThread, Signal

from netconsole.core import app_logger
from netconsole.core.paths import PathResolver
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.rail_transit.trackside_optical_collection import (
    DEFAULT_TRACKSIDE_OPTICAL_CONCURRENCY,
    TracksideOpticalSessionResult,
    collect_trackside_optical,
)
from netconsole.services.h3c_ac_collect_service import collect_h3c_fit_ap_optical, collect_h3c_fit_ap_resources
from netconsole.services.trackside_ap_business import filter_station_switch_devices
from netconsole.services.trackside_ap_export_service import TracksideApBusinessLoadResult, load_trackside_ap_business_snapshot
from netconsole.ui.batch_collect_worker import BATCH_CONCURRENCY, run_batch_collect


@dataclass(frozen=True)
class TracksideApFullUpdateResult:
    station_switch_total: int = 0
    station_switch_success: int = 0
    station_switch_failed: int = 0
    ac_total: int = 0
    ac_resource_success: int = 0
    ac_resource_failed: int = 0
    fit_ap_resource_count: int = 0
    fit_ap_optical_success: int = 0
    fit_ap_optical_failed: int = 0
    fit_ap_optical_rows_updated: int = 0
    skipped_messages: tuple[str, ...] = ()
    error_messages: tuple[str, ...] = ()

    @property
    def has_failures(self) -> bool:
        return bool(self.station_switch_failed or self.ac_resource_failed or self.fit_ap_optical_failed or self.error_messages)

    def summary_text(self) -> str:
        parts = [
            f"交换机详情成功 {self.station_switch_success}/{self.station_switch_total}",
            f"AC资源成功 {self.ac_resource_success}/{self.ac_total}",
            f"FIT-AP资源 {self.fit_ap_resource_count} 条",
            f"FIT-AP光衰成功 {self.fit_ap_optical_success}，失败 {self.fit_ap_optical_failed}",
        ]
        if self.skipped_messages:
            parts.append("；".join(self.skipped_messages))
        if self.error_messages:
            parts.append("；".join(self.error_messages[:3]))
        return "；".join(parts)

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


class TracksideApFullUpdateThread(QThread):
    stage_changed = Signal(str)
    progress_changed = Signal(str)
    full_update_finished = Signal(object)
    full_update_failed = Signal(str)

    def __init__(
        self,
        repository: DeviceRepository,
        site_name: str,
        paths: PathResolver,
        device_concurrency: int = BATCH_CONCURRENCY,
        fit_ap_concurrency: int = BATCH_CONCURRENCY,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.repository = repository
        self.site_name = site_name
        self.paths = paths
        self.device_concurrency = int(device_concurrency or BATCH_CONCURRENCY)
        self.fit_ap_concurrency = int(fit_ap_concurrency or BATCH_CONCURRENCY)
        self._cancel_event = Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        app_logger.log_info("TRACKSIDE_AP_FULL_UPDATE_STARTED", f"site={self.site_name}")
        self.stage_changed.emit("trackside_ap.full_stage_prepare")
        try:
            result = self._run_full_update()
        except Exception as exc:
            app_logger.log_error("TRACKSIDE_AP_FULL_UPDATE_FAILED", f"site={self.site_name}, error={exc}")
            self.full_update_failed.emit(str(exc))
            return
        app_logger.log_info("TRACKSIDE_AP_FULL_UPDATE_PREREQUISITES_COMPLETED", f"site={self.site_name}, {result.summary_text()}")
        self.full_update_finished.emit(result)

    def _run_full_update(self) -> TracksideApFullUpdateResult:
        station_switches = filter_station_switch_devices(self.repository.list(), self.repository.database, self.site_name)
        ac_devices = [
            device
            for device in self.repository.list(vendor="H3C", device_type="AC")
            if str(device.device_vendor or "").strip().upper() == "H3C" and str(device.device_type or "").strip().upper() == "AC"
        ]
        skipped: list[str] = []
        if not station_switches:
            skipped.append("当前局点没有分组为“车站”的交换机，已跳过交换机详情更新")
            app_logger.log_warning("TRACKSIDE_AP_FULL_UPDATE_SWITCH_DETAIL_SKIPPED", f"site={self.site_name}, reason=no_station_switch")
        if not ac_devices:
            skipped.append("当前局点没有无线控制器，已跳过AC FIT-AP资源和光衰更新")
            app_logger.log_warning("TRACKSIDE_AP_FULL_UPDATE_AC_RESOURCE_SKIPPED", f"site={self.site_name}, reason=no_ac")

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {}
            if station_switches:
                futures[executor.submit(self._run_switch_detail_branch, station_switches)] = "switch"
            if ac_devices:
                futures[executor.submit(self._run_ac_branch, ac_devices)] = "ac"
            branch_results: dict[str, dict[str, object]] = {}
            for future in as_completed(futures):
                branch = futures[future]
                try:
                    branch_results[branch] = future.result()
                except Exception as exc:
                    branch_results[branch] = {"errors": [str(exc)]}
                    event = "TRACKSIDE_AP_FULL_UPDATE_SWITCH_DETAIL_FAILED" if branch == "switch" else "TRACKSIDE_AP_FULL_UPDATE_AC_RESOURCE_FAILED"
                    app_logger.log_error(event, f"site={self.site_name}, error={exc}")

        switch_result = branch_results.get("switch", {})
        ac_result = branch_results.get("ac", {})
        errors = [str(item) for item in switch_result.get("errors", [])] + [str(item) for item in ac_result.get("errors", [])]
        return TracksideApFullUpdateResult(
            station_switch_total=len(station_switches),
            station_switch_success=int(switch_result.get("success", 0) or 0),
            station_switch_failed=int(switch_result.get("failed", 0) or 0),
            ac_total=len(ac_devices),
            ac_resource_success=int(ac_result.get("resource_success", 0) or 0),
            ac_resource_failed=int(ac_result.get("resource_failed", 0) or 0),
            fit_ap_resource_count=int(ac_result.get("fit_ap_resource_count", 0) or 0),
            fit_ap_optical_success=int(ac_result.get("optical_success", 0) or 0),
            fit_ap_optical_failed=int(ac_result.get("optical_failed", 0) or 0),
            fit_ap_optical_rows_updated=int(ac_result.get("optical_rows_updated", 0) or 0),
            skipped_messages=tuple(skipped),
            error_messages=tuple(errors),
        )

    def _run_switch_detail_branch(self, station_switches: list) -> dict[str, object]:
        if self._cancel_event.is_set():
            return {"success": 0, "failed": 0, "errors": ["用户已取消更新"]}
        self.stage_changed.emit("trackside_ap.full_stage_switch_detail")
        app_logger.log_info("TRACKSIDE_AP_FULL_UPDATE_SWITCH_DETAIL_STARTED", f"site={self.site_name}, count={len(station_switches)}")
        success = 0
        failed = 0

        def on_result(item) -> None:
            nonlocal success, failed
            if item.success:
                success += 1
            else:
                failed += 1
            self.progress_changed.emit(f"更新车站交换机详情：成功 {success}，失败 {failed}，共 {len(station_switches)}")

        run_batch_collect(
            station_switches,
            self.site_name,
            max_workers=self.device_concurrency,
            result_callback=on_result,
        )
        app_logger.log_info("TRACKSIDE_AP_FULL_UPDATE_SWITCH_DETAIL_COMPLETED", f"site={self.site_name}, success={success}, failed={failed}")
        return {"success": success, "failed": failed, "errors": []}

    def _run_ac_branch(self, ac_devices: list) -> dict[str, object]:
        errors: list[str] = []
        resource_success = 0
        resource_failed = 0
        fit_ap_resource_count = 0
        optical_success = 0
        optical_failed = 0
        optical_rows_updated = 0
        for ac_device in ac_devices:
            if self._cancel_event.is_set():
                errors.append("用户已取消更新")
                break
            label = str(ac_device.name or ac_device.primary_address or ac_device.device_uuid or "AC")
            self.stage_changed.emit("trackside_ap.full_stage_ac_resource")
            app_logger.log_info("TRACKSIDE_AP_FULL_UPDATE_AC_RESOURCE_STARTED", f"site={self.site_name}, ac={label}")
            try:
                resource_result = collect_h3c_fit_ap_resources(
                    ac_device,
                    self.site_name,
                    progress=self.progress_changed.emit,
                    should_cancel=self._cancel_event.is_set,
                )
                if resource_result.success:
                    resource_success += 1
                    fit_ap_resource_count += int(resource_result.fit_ap_resources_updated or 0)
                else:
                    resource_failed += 1
                    if resource_result.error_message:
                        errors.append(f"{label} FIT-AP资源失败：{resource_result.error_message}")
            except Exception as exc:
                resource_failed += 1
                errors.append(f"{label} FIT-AP资源失败：{exc}")
                app_logger.log_error("TRACKSIDE_AP_FULL_UPDATE_AC_RESOURCE_FAILED", f"site={self.site_name}, ac={label}, error={exc}")

            if self._cancel_event.is_set():
                errors.append("用户已取消更新")
                break
            self.stage_changed.emit("trackside_ap.full_stage_optical")
            app_logger.log_info("TRACKSIDE_AP_FULL_UPDATE_OPTICAL_STARTED", f"site={self.site_name}, ac={label}")
            try:
                optical_result = collect_h3c_fit_ap_optical(
                    ac_device,
                    self.site_name,
                    max_workers=self.fit_ap_concurrency,
                    progress=self.progress_changed.emit,
                    should_cancel=self._cancel_event.is_set,
                )
                if optical_result.success or optical_result.partial_success:
                    optical_success += 1
                if not optical_result.success:
                    optical_failed += int(optical_result.failed_aps or 0) or 1
                    if optical_result.error_message:
                        errors.append(f"{label} FIT-AP光衰失败：{optical_result.error_message}")
                optical_rows_updated += int(optical_result.optical_rows_updated or 0)
            except Exception as exc:
                optical_failed += 1
                errors.append(f"{label} FIT-AP光衰失败：{exc}")
                app_logger.log_error("TRACKSIDE_AP_FULL_UPDATE_OPTICAL_FAILED", f"site={self.site_name}, ac={label}, error={exc}")
        return {
            "resource_success": resource_success,
            "resource_failed": resource_failed,
            "fit_ap_resource_count": fit_ap_resource_count,
            "optical_success": optical_success,
            "optical_failed": optical_failed,
            "optical_rows_updated": optical_rows_updated,
            "errors": errors,
        }


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
