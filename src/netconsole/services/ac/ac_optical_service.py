from __future__ import annotations

from collections.abc import Mapping
from typing import Callable

from netconsole.core.paths import PathResolver
from netconsole.core.sources.switch_source import build_switch_data_lookup, compute_switch_status
from netconsole.models.device import Device
from netconsole.repositories.ac_repository import AcRepository
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.ac.ac_models import AcOpticalRefreshRequest, AcOpticalRefreshResult, AcOpticalSnapshot
from netconsole.services.h3c_ac_collect_service import FitApOpticalCollectResult, collect_h3c_fit_ap_optical
from netconsole.services.ac.fit_ap_optical_partial_success import install_fit_ap_optical_partial_success
from netconsole.services.offline_ap_ledger import OFFLINE_AP_STATUS_TEXT, is_fit_ap_offline
from netconsole.services.ap_identity.normalizers import normalize_mac
from netconsole.utils.interface_sort import interface_sort_key


install_fit_ap_optical_partial_success()


ProgressMessage = str | Mapping[str, object]
ProgressCallback = Callable[[str, int, int, ProgressMessage], None]
CancelCallback = Callable[[], bool]


class AcOpticalRefreshCancelled(RuntimeError):
    pass


def enrich_fit_ap_optical_rows(
    rows: list[dict[str, object | None]],
    resources: list[dict[str, object | None]],
    device_optical_status_lookup: dict[tuple[str, str], dict[str, object | None]] | None = None,
    *,
    should_cancel: CancelCallback | None = None,
) -> list[dict[str, object | None]]:
    resources_by_uuid = {str(row.get("ap_uuid") or ""): row for row in resources if row.get("ap_uuid")}
    resources_by_mac = {normalize_mac(row.get("ap_mac")): row for row in resources if normalize_mac(row.get("ap_mac"))}
    lookup = device_optical_status_lookup or {}
    result: list[dict[str, object | None]] = []
    for row in rows:
        if should_cancel is not None and should_cancel():
            raise AcOpticalRefreshCancelled("用户已取消更新")
        resource = resources_by_uuid.get(str(row.get("ap_uuid") or "")) or resources_by_mac.get(normalize_mac(row.get("ap_mac")), {})
        result.append(_classify_optical_status(row, resource, lookup))
    return result


def _classify_optical_status(
    row: dict[str, object | None],
    resource: dict[str, object | None],
    switch_lookup: dict[tuple[str, str], dict[str, object | None]],
) -> dict[str, object | None]:
    neighbor_name = row.get("neighbor_device_name")
    lowered = str(neighbor_name or "").casefold()
    if any(token.casefold() in lowered for token in ("Nearest", "Chassis ID", "Default", "customer bridge", "nontpmr")):
        neighbor_name = None
    switch_status = compute_switch_status(
        device_name=neighbor_name,
        interface_name=row.get("neighbor_interface"),
        lookup=switch_lookup,
    )
    merged = _merge_ap_online_status(row, resource)
    return {
        **merged,
        "ap_mac": row.get("ap_mac") or resource.get("ap_mac"),
        "site": row.get("site") or resource.get("site_name") or resource.get("site") or "未归属",
        "neighbor_device_name": neighbor_name,
        "switch_optical_status": switch_status,
    }


def _merge_ap_online_status(
    row: dict[str, object | None],
    resource: dict[str, object | None],
) -> dict[str, object | None]:
    is_offline = is_fit_ap_offline(resource) or bool(row.get("is_ap_offline"))
    return {
        **row,
        "is_ap_offline": is_offline,
        "optical_alarm_status": OFFLINE_AP_STATUS_TEXT if is_offline else row.get("optical_alarm_status"),
        "ap_optical_status": "offline" if is_offline else row.get("ap_optical_status"),
        "data_source": "historical" if is_offline else row.get("data_source"),
    }


class AcOpticalService:
    def __init__(
        self,
        device_repository: DeviceRepository,
        ac_repository: AcRepository,
        fact_repository: DeviceFactRepository,
        paths: PathResolver,
        *,
        cli_collector=collect_h3c_fit_ap_optical,
    ) -> None:
        self.device_repository = device_repository
        self.ac_repository = ac_repository
        self.fact_repository = fact_repository
        self.paths = paths
        self.cli_collector = cli_collector

    def refresh_fit_ap_optical(
        self,
        request: AcOpticalRefreshRequest,
        *,
        progress_callback: ProgressCallback | None = None,
        should_cancel: CancelCallback | None = None,
    ) -> AcOpticalRefreshResult:
        source = str(request.source or "auto").strip().lower()
        if source not in {"auto", "cli", "ssh"}:
            raise ValueError(f"不支持的 AC 光衰采集来源：{request.source}")
        self._check_cancelled(should_cancel)
        device = self._load_device(request.device_uuid)
        self._progress(progress_callback, "ac_fit_ap_optical_collect", 0, 0, "正在通过 H3C CLI 更新 FIT-AP 光衰...")

        def item_progress(payload: Mapping[str, object]) -> None:
            stage = _fit_ap_stage_from_event(payload, default="ac_fit_ap_optical_collect")
            current = _int_value(payload.get("completed"))
            total = _int_value(payload.get("total"))
            self._progress(progress_callback, stage, current, total, payload)

        result: FitApOpticalCollectResult = self.cli_collector(
            device,
            request.site_name,
            repository=self.ac_repository,
            paths=self.paths,
            max_workers=max(1, int(request.max_workers or 1)),
            progress=lambda message: self._progress(progress_callback, "ac_fit_ap_optical_collect", 0, 0, message),
            item_progress=item_progress,
            should_cancel=should_cancel,
            target_ap_uuids=list(request.target_ap_uuids) or None,
            target_ap_macs=list(request.target_ap_macs) or None,
            target_ap_names=list(request.target_ap_names) or None,
        )
        if self._cancelled(should_cancel) or result.error_message == "用户已取消更新":
            raise AcOpticalRefreshCancelled("用户已取消更新")
        snapshot = self.load_optical_snapshot(
            request.device_uuid,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
        )
        return AcOpticalRefreshResult(
            success=result.success,
            partial_success=result.partial_success,
            source="cli",
            refresh_scope=request.refresh_scope,
            snapshot=snapshot,
            collect_run_uuid=result.collect_run_uuid,
            optical_rows_updated=result.optical_rows_updated,
            failed_aps=result.failed_aps,
            error_message=str(result.error_message or ""),
            requested_concurrency=result.requested_concurrency,
            effective_concurrency=result.effective_concurrency,
            platform_concurrency_limit=result.platform_concurrency_limit,
            round_summaries=list(result.round_summaries),
        )

    def refresh_single_ap_optical(
        self,
        request: AcOpticalRefreshRequest,
        *,
        progress_callback: ProgressCallback | None = None,
        should_cancel: CancelCallback | None = None,
    ) -> AcOpticalRefreshResult:
        if not any((request.target_ap_uuids, request.target_ap_macs)):
            if request.target_ap_names:
                raise ValueError("AP 名称仅用于展示兼容，单 AP 光衰刷新必须提供 AP UUID 或规范化 MAC")
            raise ValueError("单 AP 光衰刷新缺少 AP 标识")
        return self.refresh_fit_ap_optical(
            request,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
        )

    def load_optical_snapshot(
        self,
        ac_device_uuid: str,
        *,
        progress_callback: ProgressCallback | None = None,
        should_cancel: CancelCallback | None = None,
    ) -> AcOpticalSnapshot:
        self._progress(progress_callback, "ac_fit_ap_optical_load", 0, 3, "正在读取 FIT-AP 资源和光衰")
        self._check_cancelled(should_cancel)
        resources = self.ac_repository.list_fit_ap_resources_with_metadata(ac_device_uuid)
        optical_rows = self.ac_repository.list_fit_ap_optical(ac_device_uuid)
        self._progress(progress_callback, "ac_fit_ap_optical_load", 1, 3, "正在读取交换机光模块状态")
        self._check_cancelled(should_cancel)
        devices = self.device_repository.list()
        optical_by_device = {
            str(device.device_uuid or ""): self.fact_repository.list_optical_modules(str(device.device_uuid or ""))
            for device in devices
        }
        lookup = build_switch_data_lookup(devices, optical_by_device)
        enriched = enrich_fit_ap_optical_rows(optical_rows, resources, lookup, should_cancel=should_cancel)
        enriched.sort(
            key=lambda row: (
                1 if str(row.get("neighbor_device_name") or "").strip() in {"", "-"} else 0,
                str(row.get("neighbor_device_name") or "").casefold(),
                interface_sort_key(row.get("neighbor_interface")),
                str(row.get("ap_name") or ""),
            )
        )
        self._progress(progress_callback, "ac_fit_ap_optical_load", 3, 3, "FIT-AP 光衰刷新完成")
        return AcOpticalSnapshot(
            ac_device_uuid=ac_device_uuid,
            summary=self.ac_repository.get_ac_ap_summary(ac_device_uuid) or {},
            resources=[dict(row) for row in resources],
            optical_rows=enriched,
        )

    def classify_optical_status(
        self,
        row: dict[str, object | None],
        resource: dict[str, object | None],
        switch_lookup: dict[tuple[str, str], dict[str, object | None]],
    ) -> dict[str, object | None]:
        return _classify_optical_status(row, resource, switch_lookup)

    @staticmethod
    def merge_ap_online_status(
        row: dict[str, object | None],
        resource: dict[str, object | None],
    ) -> dict[str, object | None]:
        return _merge_ap_online_status(row, resource)

    def _load_device(self, device_uuid: str) -> Device:
        device = next(
            (item for item in self.device_repository.list(device_type="AC") if str(item.device_uuid or "") == device_uuid),
            None,
        )
        if device is None:
            raise KeyError(f"AC device not found: {device_uuid}")
        return device

    @staticmethod
    def _progress(callback: ProgressCallback | None, stage: str, current: int, total: int, message: ProgressMessage) -> None:
        if callback is not None:
            callback(stage, current, total, message)

    @classmethod
    def _check_cancelled(cls, callback: CancelCallback | None) -> None:
        if cls._cancelled(callback):
            raise AcOpticalRefreshCancelled("用户已取消更新")

    @staticmethod
    def _cancelled(callback: CancelCallback | None) -> bool:
        return bool(callback is not None and callback())


def _fit_ap_stage_from_event(payload: Mapping[str, object], *, default: str) -> str:
    event = str(payload.get("event") or "")
    if event == "ap_retry_started":
        return "ac_fit_ap_optical.retry"
    if event in {"ap_started", "ap_completed"}:
        return "ac_fit_ap_optical.collect"
    if event == "plan_ready":
        return "ac_fit_ap_optical.plan"
    return default


def _int_value(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
