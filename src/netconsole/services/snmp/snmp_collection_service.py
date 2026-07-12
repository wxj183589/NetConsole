from __future__ import annotations

import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import replace
from datetime import datetime
from typing import Callable

from netconsole.models.snmp_models import (
    SnmpCollectionDeviceResult,
    SnmpCollectionItemResult,
    SnmpCollectionRequest,
    SnmpCollectionResult,
    SnmpCollectionTarget,
    SnmpQueryRequest,
)
from netconsole.services.snmp.request_builder import normalize_operation, operation_key
from netconsole.services.snmp_query_service import SnmpQueryService


ProgressCallback = Callable[[str, int, int, str], None]
CancelCallback = Callable[[], bool]
QueryServiceFactory = Callable[[SnmpCollectionTarget], SnmpQueryService]

_READ_OPERATIONS = {"GET", "GETNEXT", "GETBULK", "WALK"}
_RETRYABLE_STATUSES = {"timeout", "failed"}


class SnmpCollectionService:
    def __init__(self, query_service_factory: QueryServiceFactory) -> None:
        self.query_service_factory = query_service_factory

    def execute(
        self,
        request: SnmpCollectionRequest,
        *,
        progress_callback: ProgressCallback | None = None,
        should_cancel: CancelCallback | None = None,
    ) -> SnmpCollectionResult:
        self._validate(request)
        started = time.perf_counter()
        total = len(request.devices)
        worker_count = min(max(5, min(50, request.concurrency)), total)
        completed = 0
        submitted = 0
        cancelled = False
        stopped_early = False
        results: dict[int, SnmpCollectionDeviceResult] = {}
        self._progress(progress_callback, "snmp_collection", 0, total, f"准备采集 {total} 台设备...")

        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="snmp-collection") as executor:
            futures: dict[Future[SnmpCollectionDeviceResult], int] = {}

            def submit_available() -> None:
                nonlocal submitted
                while len(futures) < worker_count and submitted < total:
                    if cancelled or stopped_early or self._cancelled(should_cancel):
                        return
                    index = submitted
                    target = request.devices[index]
                    futures[executor.submit(self._collect_device, target, request, should_cancel)] = index
                    submitted += 1

            submit_available()
            while futures:
                if not cancelled and self._cancelled(should_cancel):
                    cancelled = True
                    self._progress(
                        progress_callback,
                        "snmp_collection_stopping",
                        completed,
                        total,
                        "已请求取消，正在等待当前 SNMP 请求结束...",
                    )
                done, _pending = wait(tuple(futures), timeout=0.05, return_when=FIRST_COMPLETED)
                if not done:
                    continue
                for future in done:
                    index = futures.pop(future)
                    target = request.devices[index]
                    try:
                        device_result = future.result()
                    except Exception as exc:
                        device_result = self._failed_device(target, str(exc))
                    results[index] = device_result
                    completed += 1
                    self._progress(
                        progress_callback,
                        "snmp_collection",
                        completed,
                        total,
                        f"已完成 {completed}/{total} 台，成功 {sum(item.status == 'success' for item in results.values())} 台。",
                    )
                    if request.stop_on_failure and device_result.status not in {"success", "cancelled"}:
                        stopped_early = True
                if not cancelled and not stopped_early:
                    submit_available()

        ordered = [results[index] for index in sorted(results)]
        success_devices = sum(item.status == "success" for item in ordered)
        failed_devices = sum(item.status not in {"success", "cancelled"} for item in ordered)
        pending_devices = max(0, total - success_devices - failed_devices)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return SnmpCollectionResult(
            request=request,
            device_results=ordered,
            total_devices=total,
            success_devices=success_devices,
            failed_devices=failed_devices,
            pending_devices=pending_devices,
            cancelled=cancelled or any(item.status == "cancelled" for item in ordered),
            stopped_early=stopped_early,
            elapsed_ms=elapsed_ms,
            completed_at=datetime.now().isoformat(timespec="seconds"),
        )

    def _collect_device(
        self,
        target: SnmpCollectionTarget,
        request: SnmpCollectionRequest,
        should_cancel: CancelCallback | None,
    ) -> SnmpCollectionDeviceResult:
        started = time.perf_counter()
        if self._cancelled(should_cancel):
            return self._cancelled_device(target)
        service = self.query_service_factory(target)
        items: list[SnmpCollectionItemResult] = []
        try:
            for oid in request.oids:
                if self._cancelled(should_cancel):
                    return self._device_result(target, items, "cancelled", "SNMP 批量采集已取消。", started)
                item = self._collect_item(service, target, oid, request, should_cancel)
                items.append(item)
                if item.status == "cancelled":
                    return self._device_result(target, items, "cancelled", item.error_message, started)
            failures = [item for item in items if item.status != "success"]
            status = "success" if not failures else "failed"
            error = "; ".join(item.error_message for item in failures if item.error_message)
            return self._device_result(target, items, status, error, started)
        finally:
            close = getattr(getattr(service, "client", None), "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

    def _collect_item(
        self,
        service: SnmpQueryService,
        target: SnmpCollectionTarget,
        oid: str,
        collection: SnmpCollectionRequest,
        should_cancel: CancelCallback | None,
    ) -> SnmpCollectionItemResult:
        started = time.perf_counter()
        method = normalize_operation(collection.operation)
        profile = replace(target.profile, timeout_ms=collection.timeout_ms, retries=0)
        last_status = "failed"
        last_error = "SNMP 查询失败。"
        last_rows = []
        attempts = 0
        for attempts in range(1, collection.retries + 2):
            if self._cancelled(should_cancel):
                return SnmpCollectionItemResult(
                    target.device_id,
                    target.device_name,
                    profile.host,
                    oid,
                    operation_key(method),
                    status="cancelled",
                    error_message="SNMP 批量采集已取消。",
                    attempts=max(1, attempts),
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                )
            query = SnmpQueryRequest(
                profile=profile,
                method=method,
                oid=oid,
                max_repetitions=collection.max_repetitions,
                non_repeaters=collection.non_repeaters,
                max_rows=collection.max_rows,
                save_history=False,
                device_id=target.device_id,
                device_name=target.device_name,
                source="collection",
                started_at=collection.started_at,
            )
            try:
                result = service.run(query, cancel_checker=should_cancel)
                last_status = result.status
                last_error = result.error_message
                last_rows = result.rows
            except Exception as exc:
                last_status = "failed"
                last_error = str(exc)
                last_rows = []
            if last_status == "success" or last_status not in _RETRYABLE_STATUSES:
                break
        return SnmpCollectionItemResult(
            device_id=target.device_id,
            device_name=target.device_name,
            host=profile.host,
            oid=oid,
            operation=operation_key(method),
            rows=list(last_rows),
            status=last_status,
            error_message=last_error,
            attempts=attempts,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            timestamp=datetime.now().isoformat(timespec="seconds"),
        )

    @staticmethod
    def _validate(request: SnmpCollectionRequest) -> None:
        if not request.devices:
            raise ValueError("SNMP 批量采集缺少设备列表")
        if not request.oids:
            raise ValueError("SNMP 批量采集缺少 OID 列表")
        operation = operation_key(request.operation)
        if operation not in _READ_OPERATIONS:
            raise ValueError(f"SNMP 批量采集不支持操作：{operation}")
        if any(not target.profile.host for target in request.devices):
            raise ValueError("SNMP 批量采集设备地址不能为空")
        if not 100 <= request.timeout_ms <= 60000:
            raise ValueError("SNMP 批量采集 timeout_ms 必须在 100～60000 之间")
        if not 0 <= request.retries <= 10:
            raise ValueError("SNMP 批量采集 retries 必须在 0～10 之间")

    @staticmethod
    def _progress(callback: ProgressCallback | None, stage: str, current: int, total: int, message: str) -> None:
        if callback is not None:
            callback(stage, current, total, message)

    @staticmethod
    def _cancelled(callback: CancelCallback | None) -> bool:
        return bool(callback is not None and callback())

    @classmethod
    def _device_result(
        cls,
        target: SnmpCollectionTarget,
        items: list[SnmpCollectionItemResult],
        status: str,
        error: str,
        started: float,
    ) -> SnmpCollectionDeviceResult:
        return SnmpCollectionDeviceResult(
            target.device_id,
            target.device_name,
            target.profile.host,
            items=list(items),
            status=status,
            error_message=error,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )

    @classmethod
    def _failed_device(cls, target: SnmpCollectionTarget, error: str) -> SnmpCollectionDeviceResult:
        return SnmpCollectionDeviceResult(
            target.device_id,
            target.device_name,
            target.profile.host,
            status="failed",
            error_message=error,
        )

    @classmethod
    def _cancelled_device(cls, target: SnmpCollectionTarget) -> SnmpCollectionDeviceResult:
        return SnmpCollectionDeviceResult(
            target.device_id,
            target.device_name,
            target.profile.host,
            status="cancelled",
            error_message="SNMP 批量采集已取消。",
        )
