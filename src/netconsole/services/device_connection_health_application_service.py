from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Callable

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.api.device_management import (
    DeviceConnectionHealthCheckItemDTO,
    DeviceConnectionHealthCheckSummaryDTO,
    DeviceConnectionHealthCheckTaskDTO,
    DeviceConnectionTestDTO,
)
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.device_health_check_application_service import (
    DEVICE_HEALTH_COMMAND_TIMEOUT_SECONDS,
    DEVICE_HEALTH_CONNECTION_TIMEOUT_SECONDS,
    DeviceHealthCheckApplicationService,
    run_device_health_check,
)
from netconsole.services.job_center.job_context import BackgroundTaskCancelled, JobContext
from netconsole.services.netmiko_connection import sanitize_sensitive_text


DIRECT_CONNECTION_HEALTH_TASK_TYPE = "device_connection_health_check"
_TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}


class DeviceConnectionHealthCheckApplicationService:
    """Run the device-page connection gate and health observation locally.

    This operation intentionally does not use TaskApplicationService or write a
    Job Center snapshot. Its short-lived state is scoped by site and retained
    only while the device page polls the result.
    """

    def __init__(
        self,
        paths: PathResolver,
        *,
        site_provider: Callable[[], str] | None = None,
        max_workers: int = 8,
    ) -> None:
        self.paths = paths
        self.site_provider = site_provider
        self._lock = threading.RLock()
        self._states: dict[str, dict[str, object]] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="device-page-check")

    def start(
        self,
        device_uuids: list[str],
        *,
        concurrency_limit: int = 4,
        site_name: str | None = None,
    ) -> DeviceConnectionHealthCheckTaskDTO:
        site = str(site_name or (self.site_provider() if self.site_provider else "demo"))
        values = list(dict.fromkeys(str(value).strip() for value in device_uuids if str(value).strip()))
        if not values:
            raise ValueError("至少选择一台设备")
        repository = DeviceRepository(Database(self.paths.site_db_path(site)))
        selected = repository.get_by_uuids(values)
        missing = [value for value in values if value not in selected]
        if missing:
            raise KeyError(missing[0])
        task_id = f"device-page-check-{uuid.uuid4().hex}"
        items = [
            {
                "device_uuid": value,
                "device_name": str(selected[value].name or ""),
                "primary_address": str(selected[value].primary_address or ""),
            }
            for value in values
        ]
        state: dict[str, object] = {
            "site": site,
            "status": "RUNNING",
            "stage": "queued",
            "current": 0,
            "total": len(values),
            "message": "已开始测试连接；连接成功后执行健康检查",
            "items": items,
        }
        event = threading.Event()
        with self._lock:
            self._states[task_id] = state
            self._cancel_events[task_id] = event
        self._executor.submit(
            self._run,
            task_id,
            site,
            values,
            max(1, min(8, int(concurrency_limit))),
            event,
        )
        return self.get(task_id, site_name=site)

    def get(self, task_id: str, *, site_name: str | None = None) -> DeviceConnectionHealthCheckTaskDTO:
        site = str(site_name or (self.site_provider() if self.site_provider else "demo"))
        with self._lock:
            state = self._states.get(str(task_id or ""))
            if state is None or str(state.get("site") or "") != site:
                raise KeyError(task_id)
            return self._dto(str(task_id), state)

    def cancel(self, task_id: str, *, site_name: str | None = None) -> DeviceConnectionHealthCheckTaskDTO:
        site = str(site_name or (self.site_provider() if self.site_provider else "demo"))
        with self._lock:
            state = self._states.get(str(task_id or ""))
            if state is None or str(state.get("site") or "") != site:
                raise KeyError(task_id)
            event = self._cancel_events.get(str(task_id))
            if event is not None:
                event.set()
            if str(state.get("status") or "") not in _TERMINAL:
                state["message"] = "正在取消，当前设备连接操作返回后停止后续检查"
            return self._dto(str(task_id), state)

    def stop(self) -> None:
        with self._lock:
            for event in self._cancel_events.values():
                event.set()
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _run(
        self,
        task_id: str,
        site: str,
        values: list[str],
        concurrency_limit: int,
        cancel_event: threading.Event,
    ) -> None:
        # Each device is sequentially gated (connection first, health second),
        # while the bounded pool keeps a batch responsive.
        executor = ThreadPoolExecutor(max_workers=min(concurrency_limit, len(values)), thread_name_prefix="device-page-item")
        futures = {executor.submit(self._run_one, task_id, site, value, cancel_event): value for value in values}
        try:
            for future in futures:
                if cancel_event.is_set():
                    break
                try:
                    future.result()
                except Exception as exc:
                    self._mark_item_failed(task_id, futures[future], sanitize_sensitive_text(str(exc)))
                self._advance(task_id, cancel_event)
            if cancel_event.is_set():
                for future, device_uuid in futures.items():
                    if not future.done():
                        future.cancel()
                        self._mark_item_cancelled(task_id, device_uuid)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
            with self._lock:
                state = self._states.get(task_id)
                if state is not None:
                    state["status"] = "CANCELLED" if cancel_event.is_set() else "COMPLETED"
                    state["stage"] = "cancelled" if cancel_event.is_set() else "completed"
                    state["message"] = "已取消" if cancel_event.is_set() else "测试连接与健康检查已完成"

    def _run_one(self, task_id: str, site: str, device_uuid: str, cancel_event: threading.Event) -> None:
        if cancel_event.is_set():
            self._mark_item_cancelled(task_id, device_uuid)
            return
        repository = DeviceRepository(Database(self.paths.site_db_path(site)))
        device = repository.get_by_uuid(device_uuid)
        if device is None:
            self._mark_item_failed(task_id, device_uuid, "设备不存在")
            return
        protocol = "SSH" if device.ssh_enabled else "TELNET" if device.telnet_enabled else "SNMP" if device.snmp_enabled else ""
        if not protocol:
            self._mark_item_failed(task_id, device_uuid, "设备未启用可用连接协议")
            return
        self._set_item(task_id, device_uuid, connection_status="RUNNING", message="正在测试连接")
        self._set_state(task_id, stage="connection", message=f"正在测试连接：{device.name or device_uuid}")
        from netconsole.services.device_management_web_service import run_device_connection_test

        context = JobContext(
            job_id=f"{task_id}:{device_uuid}",
            task_type="device_connection_test",
            params={"site_name": site, "device_uuid": device_uuid, "protocol": protocol},
            progress_callback=lambda stage, current, total, message: self._set_state(
                task_id, stage=f"connection:{stage}", message=str(message or "正在测试连接")
            ),
            should_cancel=cancel_event.is_set,
            paths=self.paths,
        )
        try:
            payload = run_device_connection_test(context)
        except BackgroundTaskCancelled:
            self._mark_item_cancelled(task_id, device_uuid)
            return
        except Exception as exc:
            self._mark_item_failed(task_id, device_uuid, sanitize_sensitive_text(str(exc), device))
            return
        connection = self._connection_dto(task_id, device_uuid, payload, device)
        if not bool(connection.success):
            self._set_item(
                task_id,
                device_uuid,
                connection_status="FAILED",
                connection=connection,
                health_status="SKIPPED",
                message=connection.safe_message or connection.message or "连接测试失败，未执行健康检查",
            )
            return
        self._set_item(task_id, device_uuid, connection_status="SUCCESS", connection=connection, health_status="RUNNING", message="连接成功，正在执行健康检查")
        self._set_state(task_id, stage="health", message=f"正在健康检查：{device.name or device_uuid}")
        try:
            planner = DeviceHealthCheckApplicationService.__new__(DeviceHealthCheckApplicationService)
            planner.paths = self.paths
            planner.site_provider = None
            plans = planner.build_plans([device_uuid], site_name=site)
            health_context = JobContext(
                job_id=f"{task_id}:{device_uuid}:health",
                task_type="device_health_check",
                params={"site_name": site, "plans": plans, "concurrency_limit": 1},
                progress_callback=lambda stage, current, total, message: self._set_state(
                    task_id, stage=f"health:{stage}", message=str(message or "正在健康检查")
                ),
                should_cancel=cancel_event.is_set,
                paths=self.paths,
            )
            result = run_device_health_check(health_context)
            health_items = [item for item in list(result.get("items") or []) if isinstance(item, dict)]
            health = health_items[0] if health_items else {"status": "FAILED", "message": "健康检查没有返回结果"}
            self._set_item(
                task_id,
                device_uuid,
                health_status=str(health.get("status") or "FAILED"),
                health_state=str(health.get("health_state") or "UNKNOWN"),
                profile_id=str(health.get("profile_id") or ""),
                metrics=list(health.get("metrics") or []),
                message=str(health.get("message") or ""),
            )
        except BackgroundTaskCancelled:
            self._mark_item_cancelled(task_id, device_uuid)
        except Exception as exc:
            self._set_item(task_id, device_uuid, health_status="FAILED", message=sanitize_sensitive_text(str(exc), device))

    def _connection_dto(self, task_id: str, device_uuid: str, payload: dict[str, object], device) -> DeviceConnectionTestDTO:
        protocol = str(payload.get("protocol") or "").upper()
        return DeviceConnectionTestDTO(
            task_id=f"{task_id}:{device_uuid}",
            task_status="SUCCESS" if payload.get("success") is True else "FAILED",
            device_uuid=device_uuid,
            protocol=protocol or None,
            success=payload.get("success") if isinstance(payload.get("success"), bool) else None,
            result_status=str(payload.get("status") or ""),
            failure_category=str(payload.get("failure_category") or ""),
            error_code=str(payload.get("error_code") or ""),
            summary=str(payload.get("summary") or ""),
            retryable=bool(payload.get("retryable")),
            suggested_action=sanitize_sensitive_text(str(payload.get("suggested_action") or payload.get("suggestion") or ""), device),
            message=sanitize_sensitive_text(str(payload.get("message") or ""), device),
            safe_message=sanitize_sensitive_text(str(payload.get("safe_message") or payload.get("message") or ""), device),
            method=str(payload.get("method") or ""),
            host=str(payload.get("host") or ""),
            port=int(payload["port"]) if payload.get("port") is not None else None,
            latency_ms=int(payload["latency_ms"]) if payload.get("latency_ms") is not None else None,
            elapsed_ms=int(payload["elapsed_ms"]) if payload.get("elapsed_ms") is not None else None,
            tested_at=str(payload.get("tested_at") or ""),
            system_name=str(payload.get("system_name") or ""),
            model=str(payload.get("model") or ""),
            os_family=str(payload.get("os_family") or ""),
            interface_count=int(payload["interface_count"]) if payload.get("interface_count") is not None else None,
            error_type=str(payload.get("error_type") or ""),
            suggestion=sanitize_sensitive_text(str(payload.get("suggestion") or ""), device),
            created_time=datetime.now(UTC).isoformat(),
            updated_time=datetime.now(UTC).isoformat(),
        )

    def _advance(self, task_id: str, cancel_event: threading.Event) -> None:
        with self._lock:
            state = self._states.get(task_id)
            if state is not None:
                state["current"] = min(int(state.get("total") or 0), int(state.get("current") or 0) + 1)
                if cancel_event.is_set():
                    state["message"] = "正在取消，未启动的设备已停止"

    def _set_state(self, task_id: str, **values: object) -> None:
        with self._lock:
            state = self._states.get(task_id)
            if state is not None:
                state.update(values)

    def _set_item(self, task_id: str, device_uuid: str, **values: object) -> None:
        with self._lock:
            state = self._states.get(task_id)
            if state is None:
                return
            for item in list(state.get("items") or []):
                if str(item.get("device_uuid") or "") == device_uuid:
                    item.update(values)
                    return

    def _mark_item_failed(self, task_id: str, device_uuid: str, message: str) -> None:
        self._set_item(task_id, device_uuid, connection_status="FAILED", health_status="SKIPPED", message=message or "设备检查失败")

    def _mark_item_cancelled(self, task_id: str, device_uuid: str) -> None:
        self._set_item(task_id, device_uuid, connection_status="CANCELLED", health_status="CANCELLED", message="已取消")

    def _dto(self, task_id: str, state: dict[str, object]) -> DeviceConnectionHealthCheckTaskDTO:
        raw_items = [DeviceConnectionHealthCheckItemDTO.model_validate(item) for item in list(state.get("items") or [])]
        summary = DeviceConnectionHealthCheckSummaryDTO(
            total=len(raw_items),
            connection_success=sum(item.connection_status == "SUCCESS" for item in raw_items),
            connection_failed=sum(item.connection_status == "FAILED" for item in raw_items),
            health_success=sum(item.health_status == "SUCCESS" for item in raw_items),
            health_partial_success=sum(item.health_status == "PARTIAL_SUCCESS" for item in raw_items),
            health_failed=sum(item.health_status == "FAILED" for item in raw_items),
            health_not_supported=sum(item.health_status == "NOT_SUPPORTED" for item in raw_items),
            cancelled=sum(item.connection_status == "CANCELLED" or item.health_status == "CANCELLED" for item in raw_items),
        )
        status = str(state.get("status") or "RUNNING")
        return DeviceConnectionHealthCheckTaskDTO(
            task_id=task_id,
            task_status=status,
            terminal=status in _TERMINAL,
            stage=str(state.get("stage") or ""),
            current=int(state.get("current") or 0),
            total=int(state.get("total") or 0),
            message=str(state.get("message") or ""),
            connection_timeout_seconds=DEVICE_HEALTH_CONNECTION_TIMEOUT_SECONDS,
            command_timeout_seconds=DEVICE_HEALTH_COMMAND_TIMEOUT_SECONDS,
            summary=summary,
            items=raw_items,
        )


__all__ = ["DIRECT_CONNECTION_HEALTH_TASK_TYPE", "DeviceConnectionHealthCheckApplicationService"]
