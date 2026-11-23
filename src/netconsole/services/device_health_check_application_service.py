from __future__ import annotations

import uuid
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Protocol

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.api.device_management import (
    DeviceHealthCheckItemDTO,
    DeviceHealthCheckSummaryDTO,
    DeviceHealthCheckTaskDTO,
)
from netconsole.models.device_detail import identify_device_platform
from netconsole.models.task_snapshot import TaskSnapshot
from netconsole.models.task_state import TERMINAL_TASK_STATES
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.background_job import BackgroundJob
from netconsole.services.device_collection_support import resolve_device_collection_support
from netconsole.services.device_command_profile_service import (
    DEVICE_INVENTORY_OPERATION_ID,
    bind_submitted_device_inventory_profile,
    resolve_device_inventory_profile,
)
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.job_center.local_process_adapter import LocalProcessAdapter
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.netmiko_connection import sanitize_sensitive_text


DEVICE_HEALTH_CHECK_TASK_TYPE = "device_health_check"
DEVICE_HEALTH_CHECK_OWNER = "web_device_management"
DEVICE_HEALTH_CONNECTION_TIMEOUT_SECONDS = 10
DEVICE_HEALTH_COMMAND_TIMEOUT_SECONDS = 120


class DeviceHealthProcessAdapter(Protocol):
    def start_job(self, job: BackgroundJob, **kwargs: object) -> str: ...


class DeviceHealthCheckApplicationService:
    """Submit and inspect read-only device health observation jobs."""

    def __init__(
        self,
        paths: PathResolver,
        task_service: TaskApplicationService,
        *,
        process_adapter: DeviceHealthProcessAdapter | None = None,
        site_provider: Callable[[], str] | None = None,
    ) -> None:
        self.paths = paths
        self.task_service = task_service
        self.process_adapter = process_adapter or LocalProcessAdapter(task_service)
        self.site_provider = site_provider

    def start(
        self,
        device_uuids: list[str],
        *,
        concurrency_limit: int = 4,
        site_name: str | None = None,
    ) -> DeviceHealthCheckTaskDTO:
        site = str(site_name or (self.site_provider() if self.site_provider else "demo"))
        values = list(dict.fromkeys(str(value).strip() for value in device_uuids if str(value).strip()))
        if not values:
            raise ValueError("至少选择一台设备")
        devices = DeviceRepository(Database(self.paths.site_db_path(site)))
        facts = DeviceFactRepository(Database(self.paths.site_db_path(site)))
        selected = devices.get_by_uuids(values)
        missing = [value for value in values if value not in selected]
        if missing:
            raise KeyError(missing[0])
        plans: list[dict[str, object]] = []
        for device_uuid in values:
            device = selected[device_uuid]
            fact = facts.get_device_fact(device_uuid)
            platform_facts = identify_device_platform(
                vendor=device.vendor_key,
                device_type=device.device_type,
                software_version=(fact or {}).get("software_version"),
                collected_at=(fact or {}).get("collected_at"),
            )
            support = resolve_device_collection_support(
                device,
                DEVICE_INVENTORY_OPERATION_ID,
                platform_facts=platform_facts,
                paths=self.paths,
            )
            plan: dict[str, object] = {
                "device_uuid": device_uuid,
                "device_name": str(device.name or ""),
                "primary_address": str(device.primary_address or ""),
                "supported": bool(support.supported),
                "reason_code": str(support.reason_code or ""),
                "reason_message": str(support.reason_message or ""),
                "platform_vendor": platform_facts.vendor,
                "platform_role": platform_facts.role,
                "platform": platform_facts.platform,
                "software_version": platform_facts.software_version,
                "platform_collected_at": platform_facts.collected_at,
            }
            if support.supported:
                profile = resolve_device_inventory_profile(
                    device,
                    platform_facts=platform_facts,
                    paths=self.paths,
                )
                plan.update(
                    profile_id=profile.profile_id,
                    profile_version=profile.profile_version,
                )
            plans.append(plan)
        task_id = f"device-health-{uuid.uuid4().hex}"
        job = BackgroundJob(
            job_id=task_id,
            task_type=DEVICE_HEALTH_CHECK_TASK_TYPE,
            params={
                "site_name": site,
                "plans": plans,
                "device_uuids": values,
                "device": values[0],
                "concurrency_limit": max(1, min(8, int(concurrency_limit))),
                "connection_timeout_seconds": DEVICE_HEALTH_CONNECTION_TIMEOUT_SECONDS,
                "command_timeout_seconds": DEVICE_HEALTH_COMMAND_TIMEOUT_SECONDS,
                "task_name": f"设备健康检查 · {len(values)} 台",
                "owner": DEVICE_HEALTH_CHECK_OWNER,
                "task_source": "local",
                "app_root": str(self.paths.app_root),
                "data_root": str(self.paths.data_root),
                "_cancel_grace_ms": 3000,
            },
        )
        self.process_adapter.start_job(job)
        return self.get(task_id, site_name=site)

    def get(self, task_id: str, *, site_name: str | None = None) -> DeviceHealthCheckTaskDTO:
        site = str(site_name or (self.site_provider() if self.site_provider else "demo"))
        snapshot = self.task_service.repository(site).get(str(task_id or ""))
        if snapshot is None or not self._owned(snapshot, site):
            raise KeyError(task_id)
        return _task_dto(snapshot)

    def cancel(self, task_id: str, *, site_name: str | None = None) -> DeviceHealthCheckTaskDTO:
        site = str(site_name or (self.site_provider() if self.site_provider else "demo"))
        snapshot = self.task_service.repository(site).get(str(task_id or ""))
        if snapshot is None or not self._owned(snapshot, site):
            raise KeyError(task_id)
        cancel_job = getattr(self.process_adapter, "cancel_job", None)
        if callable(cancel_job):
            cancel_job(snapshot.task_id)
        else:
            self.task_service.cancel_task(snapshot.task_id, site_name=site)
        return self.get(task_id, site_name=site)

    @staticmethod
    def _owned(snapshot: TaskSnapshot, site: str) -> bool:
        return (
            snapshot.site_name == site
            and snapshot.owner == DEVICE_HEALTH_CHECK_OWNER
            and snapshot.task_type == DEVICE_HEALTH_CHECK_TASK_TYPE
            and snapshot.source == "local"
        )


def run_device_health_check(context: JobContext) -> dict[str, object]:
    """Worker handler using only existing read-only inventory profiles."""

    from netconsole.services.h3c_collect_service import collect_h3c_device_details

    site = str(context.params.get("site_name") or "")
    plans = [dict(value) for value in list(context.params.get("plans") or []) if isinstance(value, dict)]
    concurrency = max(1, min(8, int(context.params.get("concurrency_limit") or 4)))
    database = Database(context.paths.site_db_path(site))
    devices = DeviceRepository(database)
    facts = DeviceFactRepository(database)
    results: list[dict[str, object]] = []
    supported = [plan for plan in plans if bool(plan.get("supported"))]
    for plan in plans:
        if not bool(plan.get("supported")):
            results.append(_unsupported_result(plan))
    context.progress("health_check", len(results), len(plans), "正在检查设备运行状态")

    def check(plan: dict[str, object]) -> dict[str, object]:
        context.check_cancelled()
        device_uuid = str(plan.get("device_uuid") or "")
        device = devices.get_by_uuid(device_uuid)
        if device is None:
            return _failed_result(plan, "设备不存在")
        platform_facts = identify_device_platform(
            vendor=device.vendor_key,
            device_type=device.device_type,
            software_version=plan.get("software_version"),
            collected_at=plan.get("platform_collected_at"),
        )
        profile = resolve_device_inventory_profile(
            device,
            platform_facts=platform_facts,
            paths=context.paths,
        )
        if (
            profile.profile_id != str(plan.get("profile_id") or "")
            or profile.profile_version != int(plan.get("profile_version") or 0)
        ):
            return _failed_result(plan, "提交时只读 Profile 与执行时不一致")
        bind_submitted_device_inventory_profile(device, profile, platform_facts)
        collected = collect_h3c_device_details(
            device,
            site,
            repository=facts,
            paths=context.paths,
            cancel_check=context.should_cancel,
        )
        context.check_cancelled()
        fact = facts.get_device_fact(device_uuid) or {}
        collect_run = facts.get_collect_run(collected.collect_run_uuid) or {}
        collect_status = str(collect_run.get("status") or ("success" if collected.success else "failed"))
        status = "SUCCESS" if collect_status == "success" else "PARTIAL_SUCCESS" if collected.success else "FAILED"
        # A failed attempt must not promote a stale fact from an earlier run to
        # an observation made by this health-check task.
        uptime = str(fact.get("uptime") or "") if collected.success else ""
        metrics = [
            _metric("accessibility", "设备可访问性", "PASS" if collected.success else "FAIL", message=collected.error_message or ""),
            _metric(
                "uptime",
                "系统运行时间",
                "OBSERVED" if uptime else "NOT_SUPPORTED",
                value=uptime,
                message=("" if collected.success else "本次只读采集未取得系统运行时间"),
            ),
            _metric(
                "running_state",
                "设备运行状态",
                "NOT_SUPPORTED",
                message="当前只读 Profile 未登记设备运行状态命令",
            ),
            _metric("cpu", "CPU 状态", "NOT_SUPPORTED", message="当前只读 Profile 未登记 CPU 命令"),
            _metric("memory", "内存状态", "NOT_SUPPORTED", message="当前只读 Profile 未登记内存命令"),
        ]
        return {
            "device_uuid": device_uuid,
            "device_name": str(device.name or ""),
            "primary_address": str(device.primary_address or ""),
            "status": status,
            "health_state": "OBSERVED" if collected.success else "UNKNOWN",
            "profile_id": profile.profile_id,
            "metrics": metrics,
            "message": sanitize_sensitive_text(collected.error_message or "", device),
        }

    pending = iter(supported)
    futures: dict[Future[dict[str, object]], dict[str, object]] = {}
    executor = ThreadPoolExecutor(max_workers=min(concurrency, max(1, len(supported))))
    try:
        for _ in range(min(concurrency, len(supported))):
            plan = next(pending, None)
            if plan is not None:
                futures[executor.submit(check, plan)] = plan
        while futures:
            context.check_cancelled()
            done, _waiting = wait(futures, timeout=0.2, return_when=FIRST_COMPLETED)
            if not done:
                continue
            for future in done:
                plan = futures.pop(future)
                try:
                    results.append(future.result())
                except Exception as exc:
                    results.append(_failed_result(plan, str(exc)))
                context.progress("health_check", len(results), len(plans), f"设备健康检查 {len(results)}/{len(plans)}")
                context.check_cancelled()
                next_plan = next(pending, None)
                if next_plan is not None:
                    futures[executor.submit(check, next_plan)] = next_plan
    finally:
        for future in futures:
            future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)
    return {
        "summary": _summary(results),
        "items": results,
        "connection_timeout_seconds": DEVICE_HEALTH_CONNECTION_TIMEOUT_SECONDS,
        "command_timeout_seconds": DEVICE_HEALTH_COMMAND_TIMEOUT_SECONDS,
        "check_semantics": {
            "connection_validation": "separate",
            "availability": "read_only_collection",
            "health": "observed_metrics_only",
        },
    }


def _metric(code: str, label: str, status: str, *, value: str = "", message: str = "") -> dict[str, str]:
    return {"code": code, "label": label, "status": status, "value": value, "message": message}


def _unsupported_result(plan: dict[str, object]) -> dict[str, object]:
    message = str(plan.get("reason_message") or "当前设备没有已验证的只读健康检查 Profile")
    return {
        "device_uuid": str(plan.get("device_uuid") or ""),
        "device_name": str(plan.get("device_name") or ""),
        "primary_address": str(plan.get("primary_address") or ""),
        "status": "NOT_SUPPORTED",
        "health_state": "UNKNOWN",
        "profile_id": "",
        "metrics": [],
        "message": message,
    }


def _failed_result(plan: dict[str, object], message: str) -> dict[str, object]:
    safe_message = sanitize_sensitive_text(message)
    return {
        "device_uuid": str(plan.get("device_uuid") or ""),
        "device_name": str(plan.get("device_name") or ""),
        "primary_address": str(plan.get("primary_address") or ""),
        "status": "FAILED",
        "health_state": "UNKNOWN",
        "profile_id": str(plan.get("profile_id") or ""),
        "metrics": [
            _metric("accessibility", "设备可访问性", "FAIL", message=safe_message)
        ],
        "message": safe_message,
    }


def _summary(items: list[dict[str, object]]) -> dict[str, int]:
    return {
        "total": len(items),
        "success": sum(item.get("status") == "SUCCESS" for item in items),
        "partial_success": sum(item.get("status") == "PARTIAL_SUCCESS" for item in items),
        "failed": sum(item.get("status") == "FAILED" for item in items),
        "not_supported": sum(item.get("status") == "NOT_SUPPORTED" for item in items),
        "cancelled": sum(item.get("status") == "CANCELLED" for item in items),
    }


def _task_dto(snapshot: TaskSnapshot) -> DeviceHealthCheckTaskDTO:
    result = dict(snapshot.result or {})
    items = [DeviceHealthCheckItemDTO(**item) for item in list(result.get("items") or []) if isinstance(item, dict)]
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else _summary([item.model_dump() for item in items])
    return DeviceHealthCheckTaskDTO(
        task_id=snapshot.task_id,
        task_status=snapshot.status.value,
        terminal=snapshot.status in TERMINAL_TASK_STATES,
        stage=snapshot.stage,
        current=snapshot.current,
        total=snapshot.total,
        message=snapshot.message or snapshot.error_message,
        connection_timeout_seconds=int(result.get("connection_timeout_seconds") or DEVICE_HEALTH_CONNECTION_TIMEOUT_SECONDS),
        command_timeout_seconds=int(result.get("command_timeout_seconds") or DEVICE_HEALTH_COMMAND_TIMEOUT_SECONDS),
        summary=DeviceHealthCheckSummaryDTO(**summary),
        items=items,
    )


__all__ = [
    "DEVICE_HEALTH_CHECK_OWNER",
    "DEVICE_HEALTH_CHECK_TASK_TYPE",
    "DeviceHealthCheckApplicationService",
    "run_device_health_check",
]
