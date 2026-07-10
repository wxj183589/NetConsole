from __future__ import annotations

from typing import Callable

from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.models.snmp_models import SnmpCollectionRequest, SnmpCollectionResult, SnmpCollectionTarget, SnmpProfile
from netconsole.repositories.ac_repository import AcRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.ac.ac_models import AcResourceRefreshRequest, AcResourceRefreshResult, AcResourceSnapshot
from netconsole.services.h3c_ac_collect_service import AcResourceCollectResult, collect_h3c_fit_ap_resources
from netconsole.services.snmp.snmp_collection_service import SnmpCollectionService


ProgressCallback = Callable[[str, int, int, str], None]
CancelCallback = Callable[[], bool]
SnmpResourceMapper = Callable[[SnmpCollectionResult], tuple[dict[str, object | None], list[dict[str, object | None]]]]


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
        snmp_collection_service: SnmpCollectionService | None = None,
        snmp_resource_mapper: SnmpResourceMapper | None = None,
    ) -> None:
        self.device_repository = device_repository
        self.ac_repository = ac_repository
        self.paths = paths
        self.cli_collector = cli_collector
        self.snmp_collection_service = snmp_collection_service
        self.snmp_resource_mapper = snmp_resource_mapper

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
        source = self._select_source(request)
        if self._cancelled(should_cancel):
            raise AcResourceRefreshCancelled("用户已取消更新")
        if source == "snmp":
            return self._refresh_snmp(device, request, progress_callback, should_cancel)
        return self._refresh_cli(device, request, progress_callback, should_cancel)

    def _refresh_cli(
        self,
        device: Device,
        request: AcResourceRefreshRequest,
        progress_callback: ProgressCallback | None,
        should_cancel: CancelCallback | None,
    ) -> AcResourceRefreshResult:
        self._progress(progress_callback, "ac_fit_ap_collect", 0, 0, "正在通过 H3C CLI 更新 FIT-AP 资源...")
        result: AcResourceCollectResult = self.cli_collector(
            device,
            request.site_name,
            repository=self.ac_repository,
            paths=self.paths,
            progress=lambda message: self._progress(progress_callback, "ac_fit_ap_collect", 0, 0, message),
            should_cancel=should_cancel,
        )
        if self._cancelled(should_cancel) or result.error_message == "用户已取消更新":
            raise AcResourceRefreshCancelled("用户已取消更新")
        snapshot = self.load_snapshot(request.device_uuid)
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
            error_message=str(result.error_message or ""),
        )

    def _refresh_snmp(
        self,
        device: Device,
        request: AcResourceRefreshRequest,
        progress_callback: ProgressCallback | None,
        should_cancel: CancelCallback | None,
    ) -> AcResourceRefreshResult:
        if self.snmp_collection_service is None or self.snmp_resource_mapper is None:
            raise ValueError("当前 AC 型号未配置已验证的 SNMP AP 资源映射，请使用 CLI 采集")
        collection = SnmpCollectionRequest(
            devices=[
                SnmpCollectionTarget(
                    device_id=str(device.device_uuid or ""),
                    device_name=device.name,
                    profile=SnmpProfile.from_device(device),
                )
            ],
            oids=list(request.snmp_oids),
            operation=request.snmp_operation,
            concurrency=request.snmp_concurrency,
            timeout_ms=request.snmp_timeout_ms,
            retries=request.snmp_retries,
            max_repetitions=request.snmp_max_repetitions,
            max_rows=request.snmp_max_rows,
        )
        result = self.snmp_collection_service.execute(
            collection,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
        )
        if result.cancelled or self._cancelled(should_cancel):
            raise AcResourceRefreshCancelled("用户已取消更新")
        if result.failed_devices:
            error = next((item.error_message for item in result.device_results if item.error_message), "SNMP AP 资源采集失败")
            return AcResourceRefreshResult(False, "snmp", self.load_snapshot(request.device_uuid), error_message=error)
        summary, resources = self.snmp_resource_mapper(result)
        if summary:
            self.ac_repository.upsert_ac_ap_dynamic_summary(request.device_uuid, summary)
        if resources:
            self.ac_repository.replace_fit_ap_resources(request.device_uuid, resources)
        return AcResourceRefreshResult(
            success=bool(summary or resources),
            source="snmp",
            snapshot=self.load_snapshot(request.device_uuid),
            fit_ap_resources_updated=len(resources),
            error_message="" if summary or resources else "SNMP AP 资源映射未返回有效数据",
        )

    def _load_device(self, device_uuid: str) -> Device:
        device = next(
            (item for item in self.device_repository.list(device_type="AC") if str(item.device_uuid or "") == device_uuid),
            None,
        )
        if device is None:
            raise KeyError(f"AC device not found: {device_uuid}")
        return device

    def _select_source(self, request: AcResourceRefreshRequest) -> str:
        source = str(request.source or "auto").strip().lower()
        if source in {"cli", "ssh"}:
            return "cli"
        if source == "snmp":
            if not request.snmp_oids:
                raise ValueError("SNMP AP 资源采集缺少 OID 列表")
            return "snmp"
        if source != "auto":
            raise ValueError(f"不支持的 AC 资源采集来源：{request.source}")
        if request.snmp_oids and self.snmp_collection_service is not None and self.snmp_resource_mapper is not None:
            return "snmp"
        return "cli"

    @staticmethod
    def _progress(callback: ProgressCallback | None, stage: str, current: int, total: int, message: str) -> None:
        if callback is not None:
            callback(stage, current, total, message)

    @staticmethod
    def _cancelled(callback: CancelCallback | None) -> bool:
        return bool(callback is not None and callback())
