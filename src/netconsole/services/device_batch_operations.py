from __future__ import annotations

import inspect
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from time import monotonic
from typing import Callable

from netconsole.models.device import Device
from netconsole.services.h3c_collect_service import CollectDeviceResult, collect_h3c_device_details
from netconsole.services.netmiko_connection import ConnectionTestResult, extract_cli_prompt, test_device_connection


ConnectionTester = Callable[[Device], ConnectionTestResult]
Collector = Callable[..., CollectDeviceResult]
BATCH_CONNECTION_DEFAULT_CONCURRENCY = 50
BATCH_CONNECTION_MAX_CONCURRENCY = 200
BATCH_CONNECTION_CONCURRENCY_OPTIONS = (10, 20, 50, 100, 200)
BATCH_COLLECT_DEFAULT_CONCURRENCY = 20
BATCH_COLLECT_MAX_CONCURRENCY = 50
BATCH_CONCURRENCY = 50


@dataclass(frozen=True)
class BatchConnectionTestItemResult:
    device_name: str
    primary_address: str
    protocol: str
    method: str
    success: bool
    prompt: str | None
    elapsed_ms: int | None
    error_message: str | None


@dataclass(frozen=True)
class BatchCollectProgressUpdate:
    device_key: str
    device_name: str
    primary_address: str
    percent: int
    status_text: str
    stage: str
    command: str = ""
    message: str = ""
    elapsed_ms: int | None = None


@dataclass(frozen=True)
class BatchCollectItemResult:
    device_name: str
    primary_address: str
    success: bool
    result_text: str
    collect_run_uuid: str | None
    raw_log_path: str | None
    elapsed_ms: int | None = None
    device_key: str = ""


def run_batch_connection_tests(
    devices: list[Device],
    tester: ConnectionTester = test_device_connection,
    max_workers: int = BATCH_CONNECTION_DEFAULT_CONCURRENCY,
    result_callback: Callable[[BatchConnectionTestItemResult], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> list[BatchConnectionTestItemResult]:
    results: list[BatchConnectionTestItemResult] = []
    worker_count = max(1, min(int(max_workers or 1), BATCH_CONNECTION_MAX_CONCURRENCY, len(devices) or 1))
    executor = ThreadPoolExecutor(max_workers=worker_count)
    try:
        futures = {executor.submit(tester, device): device for device in devices}
        started_at = {future: monotonic() for future in futures}
        for future in as_completed(futures):
            if should_cancel is not None and should_cancel():
                for pending in futures:
                    pending.cancel()
                break
            device = futures[future]
            fallback_elapsed = int((monotonic() - started_at[future]) * 1000)
            try:
                result = future.result()
                item = BatchConnectionTestItemResult(
                    device_name=str(device.name or ""),
                    primary_address=str(device.primary_address or ""),
                    protocol=result.protocol,
                    method=result.method,
                    success=result.success,
                    prompt=extract_cli_prompt(result.prompt or "") or None,
                    elapsed_ms=result.elapsed_ms if result.elapsed_ms is not None else fallback_elapsed,
                    error_message=None if result.success else result.message,
                )
            except Exception as exc:
                item = BatchConnectionTestItemResult(
                    device_name=str(device.name or ""),
                    primary_address=str(device.primary_address or ""),
                    protocol="",
                    method="",
                    success=False,
                    prompt=None,
                    elapsed_ms=fallback_elapsed,
                    error_message=str(exc),
                )
            results.append(item)
            if result_callback is not None:
                result_callback(item)
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
    return results


def device_key(device: Device) -> str:
    return str(device.id or device.device_uuid or device.primary_address or device.name)


def _collector_supports_progress_callback(collector: Collector) -> bool:
    try:
        parameters = inspect.signature(collector).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(parameter.name == "progress_callback" or parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters)


def run_batch_collect(
    devices: list[Device],
    site_name: str,
    collector: Collector = collect_h3c_device_details,
    max_workers: int = BATCH_COLLECT_DEFAULT_CONCURRENCY,
    result_callback: Callable[[BatchCollectItemResult], None] | None = None,
    progress_callback: Callable[[BatchCollectProgressUpdate], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> list[BatchCollectItemResult]:
    results: list[BatchCollectItemResult] = []
    worker_count = max(1, min(int(max_workers or 1), BATCH_COLLECT_MAX_CONCURRENCY, len(devices) or 1))
    supports_progress = _collector_supports_progress_callback(collector)

    def emit_progress(device: Device, started_at: float, percent: int, stage: str, command: str = "", message: str = "") -> None:
        if progress_callback is None:
            return
        progress_callback(
            BatchCollectProgressUpdate(
                device_key=device_key(device),
                device_name=str(device.name or ""),
                primary_address=str(device.primary_address or ""),
                percent=percent,
                status_text="batch_collect.status.running",
                stage=stage,
                command=command,
                message=message,
                elapsed_ms=int((monotonic() - started_at) * 1000),
            )
        )

    def collect_one(device: Device) -> CollectDeviceResult:
        started_at = monotonic()
        if supports_progress:
            return collector(
                device,
                site_name,
                progress_callback=lambda percent, stage, command="", message="": emit_progress(device, started_at, percent, stage, command, message),
            )
        return collector(device, site_name)

    if progress_callback is not None:
        for device in devices:
            if should_cancel is not None and should_cancel():
                return results
            progress_callback(
                BatchCollectProgressUpdate(
                    device_key=device_key(device),
                    device_name=str(device.name or ""),
                    primary_address=str(device.primary_address or ""),
                    percent=0,
                    status_text="batch_collect.status.waiting",
                    stage="batch_collect.stage.waiting",
                )
            )
    executor = ThreadPoolExecutor(max_workers=worker_count)
    try:
        futures = {executor.submit(collect_one, device): device for device in devices}
        started_at = {future: monotonic() for future in futures}
        for future in as_completed(futures):
            if should_cancel is not None and should_cancel():
                for pending in futures:
                    pending.cancel()
                break
            device = futures[future]
            elapsed_ms = int((monotonic() - started_at[future]) * 1000)
            try:
                collect_result = future.result()
                item = BatchCollectItemResult(
                    device_name=str(device.name or ""),
                    primary_address=str(device.primary_address or ""),
                    success=bool(collect_result.success),
                    result_text=collect_result.error_message or ("success" if collect_result.success else "failed"),
                    collect_run_uuid=collect_result.collect_run_uuid,
                    raw_log_path=collect_result.raw_log_path,
                    elapsed_ms=elapsed_ms,
                    device_key=device_key(device),
                )
            except Exception as exc:
                if progress_callback is not None:
                    progress_callback(
                        BatchCollectProgressUpdate(
                            device_key=device_key(device),
                            device_name=str(device.name or ""),
                            primary_address=str(device.primary_address or ""),
                            percent=100,
                            status_text="batch_collect.status.failed",
                            stage="batch_collect.stage.failed",
                            message=str(exc),
                            elapsed_ms=elapsed_ms,
                        )
                    )
                item = BatchCollectItemResult(
                    device_name=str(device.name or ""),
                    primary_address=str(device.primary_address or ""),
                    success=False,
                    result_text=str(exc),
                    collect_run_uuid=None,
                    raw_log_path=None,
                    elapsed_ms=elapsed_ms,
                    device_key=device_key(device),
                )
            results.append(item)
            if result_callback is not None:
                result_callback(item)
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
    return results
