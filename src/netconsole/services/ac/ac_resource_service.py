from __future__ import annotations

from typing import Callable

from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.repositories.ac_repository import AcRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.ac.ac_models import (
    AcFitApDetailRefreshRequest,
    AcResourceRefreshRequest,
    AcResourceRefreshResult,
    AcResourceSnapshot,
)
from netconsole.services.h3c_ac_collect_service import (
    AcResourceCollectResult,
    collect_h3c_ac_info,
    collect_h3c_fit_ap_resources,
    collect_h3c_fit_ap_verbose,
)


ProgressCallback = Callable[[str, int, int, str], None]
CancelCallback = Callable[[], bool]


class AcResourceRefreshCancelled(RuntimeError):
    pass


class AcResourceService:
    def __init__(
        self,
        device_repository: DeviceRepository,
        ac_repository: AcRepository,
        paths: PathResolver,
        *,
        cli_collector=collect_h3c_fit_ap_resources,
        detail_cli_collector=collect_h3c_fit_ap_resources,
        info_collector=collect_h3c_ac_info,
    ) -> None:
        self.device_repository = device_repository
        self.ac_repository = ac_repository
        self.paths = paths
        self.cli_collector = cli_collector
        self.detail_cli_collector = detail_cli_collector
        self.info_collector = info_collector

    def load_snapshot(self, ac_device_uuid: str) -> AcResourceSnapshot:
        return AcResourceSnapshot(
            ac_device_uuid=ac_device_uuid,
            summary=self.ac_repository.get_ac_ap_summary(ac_device_uuid) or {},
            resources=self.ac_repository.list_fit_ap_resources_with_metadata(ac_device_uuid),
        )

    def refresh(
        self,
        request: AcResourceRefreshRequest,
        *,
        progress_callback: ProgressCallback | None = None,
        should_cancel: CancelCallback | None = None,
    ) -> AcResourceRefreshResult:
        device = self._load_device(request.device_uuid)
        self._validate_source(request)
        if self._cancelled(should_cancel):
            raise AcResourceRefreshCancelled("用户已取消更新")
        return self._refresh_cli(device, request, progress_callback, should_cancel)

    def refresh_ac_info(
        self,
        request: AcResourceRefreshRequest,
        *,
        progress_callback: ProgressCallback | None = None,
        should_cancel: CancelCallback | None = None,
    ) -> AcResourceRefreshResult:
        device = self._load_device(request.device_uuid)
        self._progress(progress_callback, "ac_info_collect", 0, 2, "正在通过 H3C CLI 更新 AC 信息...")
        result: AcResourceCollectResult = self.info_collector(
            device,
            request.site_name,
            repository=self.ac_repository,
            paths=self.paths,
            progress=lambda message: self._progress(progress_callback, "ac_info_collect", 1, 2, message),
            should_cancel=should_cancel,
        )
        if self._cancelled(should_cancel) or result.error_message == "用户已取消更新":
            raise AcResourceRefreshCancelled("用户已取消更新")
        self._progress(progress_callback, "ac_info_collect", 2, 2, "AC 信息已持久化")
        return AcResourceRefreshResult(
            success=result.success,
            source="cli",
            snapshot=self.load_snapshot(request.device_uuid),
            collect_run_uuid=result.collect_run_uuid,
            raw_log_path=result.raw_log_path,
            failed_commands=[item.command for item in getattr(result, "command_results", []) if not item.success],
            summary_updated=result.summary_updated,
            https_port=result.https_port,
            https_port_persisted=result.https_port_persisted,
            error_message=str(result.error_message or ""),
            fit_ap_snapshot_status=str(
                getattr(result, "fit_ap_snapshot_status", "NOT_COLLECTED")
            ),
        )

    def refresh_ap_detail(
        self,
        request: AcFitApDetailRefreshRequest,
        *,
        progress_callback: ProgressCallback | None = None,
        should_cancel: CancelCallback | None = None,
    ) -> AcResourceRefreshResult:
        device = self._load_device(request.device_uuid)
        self._progress(progress_callback, "ac_fit_ap_detail_collect", 0, 2, "正在深度更新选中的 FIT-AP...")
        result: AcResourceCollectResult = self.detail_cli_collector(
            device,
            request.site_name,
            repository=self.ac_repository,
            paths=self.paths,
            progress=lambda message: self._progress(progress_callback, "ac_fit_ap_detail_collect", 1, 2, message),
            should_cancel=should_cancel,
            target_ap_uuid=request.ap_uuid,
        )
        if self._cancelled(should_cancel) or result.error_message == "用户已取消更新":
            raise AcResourceRefreshCancelled("用户已取消更新")
        self._progress(progress_callback, "ac_fit_ap_detail_collect", 2, 2, "FIT-AP 深度信息已持久化")
        return AcResourceRefreshResult(
            success=result.success,
            source="cli",
            snapshot=self.load_snapshot(request.device_uuid),
            collect_run_uuid=result.collect_run_uuid,
            raw_log_path=result.raw_log_path,
            fit_ap_resources_updated=result.fit_ap_resources_updated,
            bbssid_rows_parsed=result.bbssid_rows_parsed,
            lldp_rows_parsed=result.lldp_rows_parsed,
            bbssid_collect_status=str(
                getattr(result, "bbssid_collect_status", "not_collected")
            ),
            bbssid_error=str(getattr(result, "bbssid_error", "") or ""),
            failed_commands=[item.command for item in getattr(result, "command_results", []) if not item.success],
            target_ap_uuid=request.ap_uuid,
            error_message=str(result.error_message or ""),
            detail_rows_updated=int(getattr(result, "detail_rows_updated", 0)),
            detail_failed_count=int(getattr(result, "detail_failed_count", 0)),
            detail_mode=str(getattr(result, "detail_mode", "") or ""),
            batch_serial_duplicates=int(getattr(result, "batch_serial_duplicates", 0)),
            batch_serial_merged=int(getattr(result, "batch_serial_merged", 0)),
            serial_identity_conflicts=int(getattr(result, "serial_identity_conflicts", 0)),
            duplicate_ap_entity_created=int(getattr(result, "duplicate_ap_entity_created", 0)),
            fit_ap_snapshot_status=str(
                getattr(result, "fit_ap_snapshot_status", "NOT_COLLECTED")
            ),
        )

    def refresh_fit_ap_verbose(
        self,
        request: AcResourceRefreshRequest,
        *,
        target_ap_uuids: list[str] | None = None,
        progress_callback: ProgressCallback | None = None,
        should_cancel: CancelCallback | None = None,
    ) -> AcResourceRefreshResult:
        device = self._load_device(request.device_uuid)
        result = collect_h3c_fit_ap_verbose(
            device,
            request.site_name,
            repository=self.ac_repository,
            paths=self.paths,
            progress=lambda message: self._progress(progress_callback, "ac_fit_ap_verbose_collect", 1, 2, message),
            should_cancel=should_cancel,
            target_ap_uuids=target_ap_uuids,
        )
        if self._cancelled(should_cancel) or result.error_message == "用户已取消更新":
            raise AcResourceRefreshCancelled("用户已取消更新")
        return AcResourceRefreshResult(
            success=result.success,
            source="cli",
            snapshot=self.load_snapshot(request.device_uuid),
            collect_run_uuid=result.collect_run_uuid,
            raw_log_path=result.raw_log_path,
            failed_commands=[item.command for item in result.command_results if not item.success],
            detail_rows_updated=result.detail_rows_updated,
            detail_failed_count=result.detail_failed_count,
            detail_mode=result.detail_mode,
            error_message=str(result.error_message or ""),
        )

    def _refresh_cli(
        self,
        device: Device,
        request: AcResourceRefreshRequest,
        progress_callback: ProgressCallback | None,
        should_cancel: CancelCallback | None,
    ) -> AcResourceRefreshResult:
        self._progress(progress_callback, "ac_fit_ap_collect", 0, 2, "正在通过 H3C CLI 更新 FIT-AP 资源...")
        result: AcResourceCollectResult = self.cli_collector(
            device,
            request.site_name,
            repository=self.ac_repository,
            paths=self.paths,
            progress=lambda message: self._progress(progress_callback, "ac_fit_ap_collect", 1, 2, message),
            should_cancel=should_cancel,
        )
        if self._cancelled(should_cancel) or result.error_message == "用户已取消更新":
            raise AcResourceRefreshCancelled("用户已取消更新")
        snapshot = self.load_snapshot(request.device_uuid)
        self._progress(progress_callback, "ac_fit_ap_collect", 2, 2, "FIT-AP 资源已持久化")
        return AcResourceRefreshResult(
            success=result.success,
            source="cli",
            snapshot=snapshot,
            collect_run_uuid=result.collect_run_uuid,
            raw_log_path=result.raw_log_path,
            fit_ap_resources_updated=result.fit_ap_resources_updated,
            unauthenticated_rows_updated=result.unauthenticated_rows_updated,
            bbssid_rows_parsed=result.bbssid_rows_parsed,
            lldp_rows_parsed=result.lldp_rows_parsed,
            bbssid_collect_status=str(
                getattr(result, "bbssid_collect_status", "not_collected")
            ),
            bbssid_error=str(getattr(result, "bbssid_error", "") or ""),
            failed_commands=[item.command for item in getattr(result, "command_results", []) if not item.success],
            error_message=str(result.error_message or ""),
            batch_serial_duplicates=int(getattr(result, "batch_serial_duplicates", 0)),
            batch_serial_merged=int(getattr(result, "batch_serial_merged", 0)),
            serial_identity_conflicts=int(getattr(result, "serial_identity_conflicts", 0)),
            duplicate_ap_entity_created=int(getattr(result, "duplicate_ap_entity_created", 0)),
            fit_ap_snapshot_status=str(
                getattr(result, "fit_ap_snapshot_status", "NOT_COLLECTED")
            ),
        )

    def _load_device(self, device_uuid: str) -> Device:
        device = next(
            (item for item in self.device_repository.list(device_type="AC") if str(item.device_uuid or "") == device_uuid),
            None,
        )
        if device is None:
            raise KeyError(f"AC device not found: {device_uuid}")
        return device

    def _validate_source(self, request: AcResourceRefreshRequest) -> None:
        source = str(request.source or "auto").strip().lower()
        if source not in {"auto", "cli", "ssh"}:
            raise ValueError(f"不支持的 AC 资源采集来源：{request.source}")

    @staticmethod
    def _progress(callback: ProgressCallback | None, stage: str, current: int, total: int, message: str) -> None:
        if callback is not None:
            callback(stage, current, total, message)

    @staticmethod
    def _cancelled(callback: CancelCallback | None) -> bool:
        return bool(callback is not None and callback())
