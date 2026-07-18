from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import RLock
from typing import Protocol

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.models.device import Device
from netconsole.models.device_detail import (
    DeviceCapability,
    DeviceOperationTask,
    DevicePlatformFacts,
    identify_device_platform,
)
from netconsole.models.task_snapshot import TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.repositories.device_detail_repository import DeviceDetailDataGateway
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.background_job import BackgroundJob
from netconsole.services.device_command_profile_service import (
    DEVICE_INVENTORY_OPERATION_ID,
    DeviceCommandProfile,
    bind_submitted_device_inventory_profile,
    device_operation_capability,
    resolve_device_operation_profile,
)
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.job_center.local_process_adapter import LocalProcessAdapter
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.job_center.web_export_event_safety import redact_web_task_text
from netconsole.services.netmiko_connection import sanitize_sensitive_text


DEVICE_DETAIL_TASK_TYPE = "device_detail_collect"
DEVICE_DETAIL_TASK_OWNER = "web_device_management"
_ACTIVE_STATES = frozenset(
    {TaskState.PENDING, TaskState.STARTING, TaskState.RUNNING, TaskState.STOPPING}
)


class DeviceProcessAdapter(Protocol):
    def start_job(self, job: BackgroundJob, **kwargs: object) -> str: ...


class DeviceInventoryRefreshFailed(RuntimeError):
    def __init__(self, summary: dict[str, object]) -> None:
        self.summary = summary
        results = list(summary.get("results") or [])
        first_error = next(
            (
                str(item.get("error_message") or "")
                for item in results
                if isinstance(item, dict) and not item.get("success")
            ),
            "设备采集失败",
        )
        failed_item = next(
            (
                item
                for item in results
                if isinstance(item, dict) and not item.get("success")
            ),
            {},
        )
        super().__init__(
            "设备详情刷新失败："
            f"total={summary.get('total', 0)}, "
            f"success={summary.get('success', 0)}, "
            f"failed={summary.get('failed', 0)}, "
            f"device_uuid={failed_item.get('device_uuid', '')}, "
            f"collect_run_uuid={failed_item.get('collect_run_uuid', '')}, "
            f"facts_updated={failed_item.get('facts_updated', False)}, "
            f"interfaces_updated={failed_item.get('interfaces_updated', 0)}, "
            f"optical_modules_updated={failed_item.get('optical_modules_updated', 0)}, "
            f"lldp_neighbors_updated={failed_item.get('lldp_neighbors_updated', 0)}；"
            f"{first_error}"
        )


class DeviceOperationService:
    """唯一受控设备详情采集入口；请求只能选择稳定 Operation ID。"""

    def __init__(
        self,
        paths: PathResolver,
        gateway: DeviceDetailDataGateway,
        task_service: TaskApplicationService,
        process_adapter: DeviceProcessAdapter | None = None,
    ) -> None:
        self.paths = paths
        self.gateway = gateway
        self.task_service = task_service
        self.process_adapter = process_adapter or LocalProcessAdapter(task_service)
        self._start_lock = RLock()

    def capability(
        self, device: Device, fact: dict[str, object | None] | None = None
    ) -> DeviceCapability:
        platform_facts = self._platform_facts(device, fact)
        return device_operation_capability(
            device,
            DEVICE_INVENTORY_OPERATION_ID,
            platform_facts=platform_facts,
            paths=self.paths,
        )

    def start(
        self,
        device_uuid: str,
        operation_id: str,
        *,
        idempotency_key: str | None = None,
    ) -> DeviceOperationTask:
        plan = self._plan(device_uuid, operation_id)
        return self._start_planned(plan, idempotency_key=idempotency_key)

    def start_many(
        self,
        device_uuids: list[str],
        operation_id: str,
        *,
        idempotency_key: str,
    ) -> list[DeviceOperationTask]:
        values = _unique_ids(device_uuids)
        plans = [self._plan(device_uuid, operation_id) for device_uuid in values]
        return [
            self._start_planned(
                plan, idempotency_key=f"{idempotency_key}:{index}"
            )
            for index, plan in enumerate(plans, start=1)
        ]

    def _plan(
        self, device_uuid: str, operation_id: str
    ) -> tuple[Device, DevicePlatformFacts, DeviceCommandProfile]:
        device = self.gateway.get_device(device_uuid)
        if device is None:
            raise KeyError(device_uuid)
        fact = self.gateway.get_fact(device_uuid)
        platform_facts = self._platform_facts(device, fact)
        profile = resolve_device_operation_profile(
            device,
            operation_id,
            platform_facts=platform_facts,
            paths=self.paths,
        )
        return device, platform_facts, profile

    def _start_planned(
        self,
        plan: tuple[Device, DevicePlatformFacts, DeviceCommandProfile],
        *,
        idempotency_key: str | None,
    ) -> DeviceOperationTask:
        device, platform_facts, profile = plan
        operation_id = str(profile.operation_id)
        device_uuid = str(device.device_uuid or "")
        site = self.gateway.current_site_id()
        repository = self.task_service.repository(site)
        requested_id = self._task_id(site, device_uuid, operation_id, idempotency_key)

        with self._start_lock:
            if requested_id:
                existing = repository.get(requested_id)
                if existing is not None:
                    self._assert_owned(existing, site, device_uuid)
                    return self._task(existing, operation_id, reused=True)

            active = next(
                iter(
                    repository.list_filtered(
                        statuses=_ACTIVE_STATES,
                        owner=DEVICE_DETAIL_TASK_OWNER,
                        source="local",
                        site_name=site,
                        task_types={DEVICE_DETAIL_TASK_TYPE},
                        device=device_uuid,
                        limit=1,
                    )
                ),
                None,
            )
            if active is not None:
                return self._task(active, operation_id, reused=True)

            task_id = requested_id or f"device-detail-{uuid.uuid4().hex}"
            job = BackgroundJob(
                job_id=task_id,
                task_type=DEVICE_DETAIL_TASK_TYPE,
                params={
                    "site_name": site,
                    "device_uuids": [device_uuid],
                    "device": device_uuid,
                    "operation_id": operation_id,
                    "profile_id": profile.profile_id,
                    "profile_version": profile.profile_version,
                    "software_version": platform_facts.software_version,
                    "platform_vendor": platform_facts.vendor,
                    "platform_role": platform_facts.role,
                    "platform": platform_facts.platform,
                    "platform_source": platform_facts.source,
                    "platform_confidence": platform_facts.confidence,
                    "platform_collected_at": platform_facts.collected_at,
                    "idempotency_key": str(idempotency_key or "") or None,
                    "task_name": f"设备详情刷新 · {device.name}",
                    "owner": DEVICE_DETAIL_TASK_OWNER,
                    "task_source": "local",
                    "app_root": str(self.paths.app_root),
                    "data_root": str(self.paths.data_root),
                    "_cancel_grace_ms": 2000,
                },
            )
            self.process_adapter.start_job(job)
            snapshot = repository.get(task_id)
            if snapshot is None:
                raise RuntimeError("设备详情刷新任务创建后未写入任务中心")
            return self._task(snapshot, operation_id, reused=False)

    @staticmethod
    def _platform_facts(
        device: Device, fact: dict[str, object | None] | None
    ) -> DevicePlatformFacts:
        return identify_device_platform(
            vendor=(fact or {}).get("vendor") or device.device_vendor,
            device_type=device.device_type,
            software_version=(fact or {}).get("software_version"),
            collected_at=(fact or {}).get("collected_at"),
        )

    @staticmethod
    def _task_id(
        site: str,
        device_uuid: str,
        operation_id: str,
        idempotency_key: str | None,
    ) -> str:
        key = str(idempotency_key or "").strip()
        if not key:
            return ""
        digest = uuid.uuid5(
            uuid.NAMESPACE_URL, f"netconsole:{site}:{device_uuid}:{operation_id}:{key}"
        )
        return f"device-detail-{digest.hex}"

    @staticmethod
    def _is_owned(snapshot: TaskSnapshot, site: str) -> bool:
        return (
            snapshot.site_name == site
            and snapshot.owner == DEVICE_DETAIL_TASK_OWNER
            and snapshot.source == "local"
            and snapshot.task_type == DEVICE_DETAIL_TASK_TYPE
        )

    @classmethod
    def _assert_owned(
        cls, snapshot: TaskSnapshot, site: str, device_uuid: str
    ) -> None:
        if not cls._is_owned(snapshot, site) or snapshot.device != device_uuid:
            raise ValueError("幂等任务标识已被其他设备操作占用")

    @staticmethod
    def _task(
        snapshot: TaskSnapshot, operation_id: str, *, reused: bool
    ) -> DeviceOperationTask:
        return DeviceOperationTask(
            task_id=snapshot.task_id,
            operation_id=operation_id,
            status=snapshot.status.value,
            reused=reused,
            message=redact_web_task_text(
                snapshot.message or snapshot.error_message
            )
            or None,
        )


def run_device_inventory_refresh(context: JobContext) -> dict[str, object]:
    """Worker handler：按稳定 Profile 校验后调用现有正式采集器。"""

    from netconsole.services.h3c_collect_service import collect_h3c_device_details

    site = SiteManager(context.paths).validate_site_name(
        str(context.params.get("site_name") or "")
    )
    operation_id = str(
        context.params.get("operation_id") or DEVICE_INVENTORY_OPERATION_ID
    )
    values = _unique_ids(list(context.params.get("device_uuids") or []))
    if len(values) != 1:
        raise ValueError("受控设备详情刷新任务必须且只能包含一台设备")
    database = Database(context.paths.site_db_path(site))
    devices = DeviceRepository(database)
    facts = DeviceFactRepository(database)
    selected = [_require_device(devices, value) for value in values]
    results: list[dict[str, object]] = []
    context.progress("device_detail_collect", 0, len(selected), "正在采集设备详情")

    def collect(device: Device):
        context.check_cancelled()
        submitted_facts = DevicePlatformFacts(
            vendor=str(context.params.get("platform_vendor") or ""),
            role=str(context.params.get("platform_role") or "unknown"),  # type: ignore[arg-type]
            platform=str(context.params.get("platform") or "unknown"),
            software_version=str(context.params.get("software_version") or "")
            or None,
            software_major=None,
            source=str(context.params.get("platform_source") or "submitted_job"),
            confidence=str(context.params.get("platform_confidence") or "unknown"),  # type: ignore[arg-type]
            collected_at=str(context.params.get("platform_collected_at") or "")
            or None,
        )
        profile = resolve_device_operation_profile(
            device,
            operation_id,
            platform_facts=submitted_facts,
            paths=context.paths,
        )
        if (
            profile.profile_id != str(context.params.get("profile_id") or "")
            or profile.profile_version
            != int(context.params.get("profile_version") or 0)
        ):
            raise ValueError("提交时命令 Profile 与 Worker 校验结果不一致")
        bind_submitted_device_inventory_profile(device, profile, submitted_facts)
        return collect_h3c_device_details(
            device, site, repository=facts, paths=context.paths
        )

    worker_count = max(1, min(20, len(selected)))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {executor.submit(collect, device): device for device in selected}
        for index, future in enumerate(as_completed(futures), start=1):
            context.check_cancelled()
            device = futures[future]
            try:
                result = future.result()
                item = {
                    "device_uuid": str(device.device_uuid or ""),
                    "success": bool(result.success),
                    "collect_run_uuid": result.collect_run_uuid,
                    "facts_updated": bool(result.facts_updated),
                    "interfaces_updated": int(result.interfaces_updated),
                    "optical_modules_updated": int(result.optical_modules_updated),
                    "lldp_neighbors_updated": int(result.lldp_neighbors_updated),
                    "error_message": sanitize_sensitive_text(
                        result.error_message or "", device
                    ),
                }
                item["error_message"] = redact_web_task_text(
                    item["error_message"]
                )
            except Exception as exc:
                item = {
                    "device_uuid": str(device.device_uuid or ""),
                    "success": False,
                    "error_message": redact_web_task_text(
                        sanitize_sensitive_text(str(exc), device)
                    ),
                }
            results.append(item)
            context.progress(
                "device_detail_collect",
                index,
                len(selected),
                f"设备详情采集 {index}/{len(selected)}",
            )
    summary: dict[str, object] = {
        "total": len(results),
        "success": sum(1 for item in results if item["success"]),
        "failed": sum(1 for item in results if not item["success"]),
        "results": results,
    }
    if int(summary["failed"]) > 0:
        context.progress(
            "device_detail_collect",
            len(results),
            len(results),
            str(DeviceInventoryRefreshFailed(summary)),
        )
        raise DeviceInventoryRefreshFailed(summary)
    return summary


def _unique_ids(values: list[object]) -> list[str]:
    return list(
        dict.fromkeys(
            str(value).strip() for value in values if str(value or "").strip()
        )
    )


def _require_device(repository: DeviceRepository, device_uuid: str) -> Device:
    device = repository.get_by_uuid(device_uuid)
    if device is None:
        raise KeyError(device_uuid)
    return device


__all__ = [
    "DEVICE_DETAIL_TASK_OWNER",
    "DEVICE_DETAIL_TASK_TYPE",
    "DeviceInventoryRefreshFailed",
    "DeviceOperationService",
    "run_device_inventory_refresh",
]
