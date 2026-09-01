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
    DEVICE_SFTP_ENABLE_OPERATION_ID,
    DeviceCommandProfile,
    bind_device_sftp_enable_commands,
    bind_submitted_device_inventory_profile,
    device_operation_capability,
    resolve_device_operation_profile,
)
from netconsole.services.device_collection_support import resolve_device_collection_support
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.job_center.local_process_adapter import LocalProcessAdapter
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.job_center.web_export_event_safety import redact_web_task_text
from netconsole.services.netmiko_connection import sanitize_sensitive_text
from netconsole.services import netmiko_connection
from netconsole.services.netmiko_connection import safe_send_command


DEVICE_DETAIL_TASK_TYPE = "device_detail_collect"
DEVICE_DETAIL_TASK_OWNER = "web_device_management"
DEVICE_SFTP_TASK_TYPE = "device_sftp_enable"
DEVICE_SFTP_TASK_OWNER = "web_file_management"
_OPERATION_METADATA = {
    DEVICE_INVENTORY_OPERATION_ID: (DEVICE_DETAIL_TASK_TYPE, DEVICE_DETAIL_TASK_OWNER, "设备详情刷新"),
    DEVICE_SFTP_ENABLE_OPERATION_ID: (DEVICE_SFTP_TASK_TYPE, DEVICE_SFTP_TASK_OWNER, "启用设备 SFTP"),
}
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


class DeviceSftpEnableProfileUnresolved(ValueError):
    """受控写入前无法从可信设备事实确认精确软件版本。"""


class DeviceOperationService:
    """统一受控设备操作入口；请求只能选择稳定 Operation ID。"""

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
        support = resolve_device_collection_support(
            device,
            DEVICE_INVENTORY_OPERATION_ID,
            platform_facts=platform_facts,
            paths=self.paths,
        )
        if not support.supported:
            return DeviceCapability(
                capability_id=DEVICE_INVENTORY_OPERATION_ID,
                available=False,
                executable=False,
                source="device_collection_support",
                reason=support.reason_message,
            )
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
        device = self.gateway.get_device(device_uuid)
        if device is None:
            raise KeyError(device_uuid)
        facts = self._platform_facts(device, self.gateway.get_fact(device_uuid))
        if operation_id == DEVICE_SFTP_ENABLE_OPERATION_ID and not facts.software_major:
            raise DeviceSftpEnableProfileUnresolved(
                "无法确认设备的软件版本，未执行 SFTP 配置命令。"
            )
        support = resolve_device_collection_support(
            device,
            operation_id,
            platform_facts=facts,
            paths=self.paths,
        )
        if not support.supported:
            return DeviceOperationTask(
                task_id="",
                operation_id=operation_id,
                status="SKIPPED",
                reused=False,
                message=support.reason_message,
                profile_id=None,
                profile_version=None,
                reason_code=support.reason_code,
            )
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
        if operation_id == DEVICE_SFTP_ENABLE_OPERATION_ID and not platform_facts.software_major:
            raise DeviceSftpEnableProfileUnresolved(
                "无法确认设备的软件版本，未执行 SFTP 配置命令。"
            )
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
        task_type, task_owner, task_label = _OPERATION_METADATA.get(
            operation_id,
            (DEVICE_DETAIL_TASK_TYPE, DEVICE_DETAIL_TASK_OWNER, "设备操作"),
        )
        repository = self.task_service.repository(site)
        requested_id = self._task_id(site, device_uuid, operation_id, idempotency_key)

        with self._start_lock:
            if requested_id:
                existing = repository.get(requested_id)
                if existing is not None:
                    self._assert_owned(existing, site, device_uuid, operation_id)
                    return self._task(
                        existing, operation_id, reused=True, profile=profile
                    )

            active = next(
                iter(
                    repository.list_filtered(
                        statuses=_ACTIVE_STATES,
                        owner=task_owner,
                        source="local",
                        site_name=site,
                        task_types={task_type},
                        device=device_uuid,
                        limit=1,
                    )
                ),
                None,
            )
            if active is not None:
                return self._task(active, operation_id, reused=True, profile=profile)

            task_id = requested_id or f"device-operation-{uuid.uuid4().hex}"
            job = BackgroundJob(
                job_id=task_id,
                task_type=task_type,
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
                    "task_name": f"{task_label} · {device.name}",
                    "owner": task_owner,
                    "task_source": "local",
                    "app_root": str(self.paths.app_root),
                    "data_root": str(self.paths.data_root),
                    "_cancel_grace_ms": 2000,
                },
            )
            self.process_adapter.start_job(job)
            snapshot = repository.get(task_id)
            if snapshot is None:
                raise RuntimeError("设备操作任务创建后未写入任务中心")
            return self._task(snapshot, operation_id, reused=False, profile=profile)

    def cancel(self, task_id: str, *, site: str | None = None) -> bool:
        selected_site = str(site or self.gateway.current_site_id() or "demo")
        snapshot = self.task_service.repository(selected_site).get(str(task_id or ""))
        if snapshot is None:
            return False
        if (snapshot.owner, snapshot.task_type) not in {
            (DEVICE_DETAIL_TASK_OWNER, DEVICE_DETAIL_TASK_TYPE),
            (DEVICE_SFTP_TASK_OWNER, DEVICE_SFTP_TASK_TYPE),
        }:
            return False
        adapter_cancel = getattr(self.process_adapter, "cancel_job", None)
        if callable(adapter_cancel):
            return bool(adapter_cancel(snapshot.task_id))
        return bool(self.task_service.cancel_task(snapshot.task_id, site_name=selected_site))

    @staticmethod
    def _platform_facts(
        device: Device, fact: dict[str, object | None] | None
    ) -> DevicePlatformFacts:
        return identify_device_platform(
            # Driver selection is always anchored to the managed device record.
            # A stale fact must never redirect an unsupported vendor to H3C/ZTE.
            vendor=device.vendor_key,
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
        return f"device-operation-{digest.hex}"

    @staticmethod
    def _is_owned(snapshot: TaskSnapshot, site: str, operation_id: str) -> bool:
        task_type, owner, _label = _OPERATION_METADATA.get(
            operation_id,
            (DEVICE_DETAIL_TASK_TYPE, DEVICE_DETAIL_TASK_OWNER, "设备操作"),
        )
        return (
            snapshot.site_name == site
            and snapshot.owner == owner
            and snapshot.source == "local"
            and snapshot.task_type == task_type
        )

    @classmethod
    def _assert_owned(
        cls, snapshot: TaskSnapshot, site: str, device_uuid: str, operation_id: str
    ) -> None:
        if not cls._is_owned(snapshot, site, operation_id) or snapshot.device != device_uuid:
            raise ValueError("幂等任务标识已被其他设备操作占用")

    @staticmethod
    def _task(
        snapshot: TaskSnapshot,
        operation_id: str,
        *,
        reused: bool,
        profile: DeviceCommandProfile,
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
            profile_id=profile.profile_id,
            profile_version=profile.profile_version,
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
            device,
            site,
            repository=facts,
            paths=context.paths,
            cancel_check=context.should_cancel,
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
                    "device_name": str(device.name or ""),
                    "primary_address": str(device.primary_address or ""),
                    "vendor": str(device.device_vendor or ""),
                    "device_type": str(device.device_type or ""),
                    "profile_id": str(context.params.get("profile_id") or ""),
                    "profile_version": int(
                        context.params.get("profile_version") or 0
                    ),
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
                collect_run = facts.get_collect_run(result.collect_run_uuid)
                item["collect_status"] = str(
                    (collect_run or {}).get("status")
                    or ("success" if result.success else "failed")
                )
                item["started_at"] = str((collect_run or {}).get("started_at") or "")
                item["finished_at"] = str((collect_run or {}).get("ended_at") or "")
                fact = facts.get_device_fact(str(device.device_uuid or ""))
                item["last_collected_at"] = str(
                    (fact or {}).get("collected_at") or ""
                )
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
        summary["terminal_state"] = "FAILED"
    return summary


def run_device_sftp_enable(context: JobContext) -> dict[str, object]:
    """Worker handler：按统一 Profile 执行已授权的 H3C SFTP 启用步骤。"""

    site = SiteManager(context.paths).validate_site_name(
        str(context.params.get("site_name") or "")
    )
    operation_id = str(context.params.get("operation_id") or DEVICE_SFTP_ENABLE_OPERATION_ID)
    values = _unique_ids(list(context.params.get("device_uuids") or []))
    if operation_id != DEVICE_SFTP_ENABLE_OPERATION_ID or len(values) != 1:
        raise ValueError("受控 SFTP 启用任务参数无效")
    database = Database(context.paths.site_db_path(site))
    device = _require_device(DeviceRepository(database), values[0])
    submitted_facts = DevicePlatformFacts(
        vendor=str(context.params.get("platform_vendor") or ""),
        role=str(context.params.get("platform_role") or "unknown"),  # type: ignore[arg-type]
        platform=str(context.params.get("platform") or "unknown"),
        software_version=str(context.params.get("software_version") or "") or None,
        software_major=None,
        source=str(context.params.get("platform_source") or "submitted_job"),
        confidence=str(context.params.get("platform_confidence") or "unknown"),  # type: ignore[arg-type]
        collected_at=str(context.params.get("platform_collected_at") or "") or None,
    )
    profile = resolve_device_operation_profile(
        device,
        operation_id,
        platform_facts=submitted_facts,
        paths=context.paths,
    )
    if (
        profile.profile_id != str(context.params.get("profile_id") or "")
        or profile.profile_version != int(context.params.get("profile_version") or 0)
    ):
        raise ValueError("提交时命令 Profile 与 Worker 校验结果不一致")
    commands = bind_device_sftp_enable_commands(
        profile,
        username=str(device.ssh_username or "").strip(),
    )
    context.progress("device_sftp_enable", 0, len(commands), "正在通过受控操作启用设备 SFTP")

    def operation(connection, _target):
        outputs: list[str] = []
        for index, command in enumerate(commands, start=1):
            context.check_cancelled()
            output = safe_send_command(
                connection,
                command,
                read_timeout=30,
                strip_prompt=False,
                strip_command=False,
                use_timing=True,
            )
            lowered = output.casefold()
            if any(marker in lowered for marker in ("% unrecognized", "% incomplete", "% ambiguous", "% wrong parameter", "% permission denied", "error:")):
                raise RuntimeError("设备拒绝 SFTP 配置命令")
            outputs.append(output)
            context.progress("device_sftp_enable", index, len(commands), f"启用设备 SFTP {index}/{len(commands)}")
        return outputs

    netmiko_connection.run_netmiko_with_retry(device, operation)
    return {
        "operation_id": operation_id,
        "profile_id": profile.profile_id,
        "profile_version": profile.profile_version,
        "device_uuid": str(device.device_uuid or ""),
        "real_device_status": profile.real_device_status,
        "message": "设备 SFTP 启用命令已执行",
    }


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
    "DEVICE_SFTP_ENABLE_OPERATION_ID",
    "DEVICE_SFTP_TASK_OWNER",
    "DEVICE_SFTP_TASK_TYPE",
    "DeviceInventoryRefreshFailed",
    "DeviceOperationService",
    "DeviceSftpEnableProfileUnresolved",
    "run_device_inventory_refresh",
    "run_device_sftp_enable",
]
