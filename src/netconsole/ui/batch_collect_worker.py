from __future__ import annotations

import inspect
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from time import monotonic
from typing import Callable

from PySide6.QtCore import QThread, Signal

from netconsole.core import app_logger
from netconsole.models.device import Device
from netconsole.services.h3c_collect_service import CollectDeviceResult, collect_h3c_device_details


Collector = Callable[..., CollectDeviceResult]
BATCH_COLLECT_DEFAULT_CONCURRENCY = 20
BATCH_COLLECT_MAX_CONCURRENCY = 50
# 兼容轨旁 AP 存量调用；设备详情批量更新使用上面的默认值。
BATCH_CONCURRENCY = 50


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


class BatchCollectWorker(QThread):
    device_progress = Signal(object)
    device_finished = Signal(object)
    batch_finished = Signal(int, int)

    def __init__(
        self,
        devices: list[Device],
        site_name: str,
        concurrency: int = BATCH_COLLECT_DEFAULT_CONCURRENCY,
        parent=None,
        max_workers: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.devices = list(devices)
        self.site_name = site_name
        self.max_workers = int(max_workers if max_workers is not None else concurrency)
        self.concurrency = self.max_workers
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True
        self.requestInterruption()

    def _should_cancel(self) -> bool:
        return self._cancel_requested or self.isInterruptionRequested()

    def run(self) -> None:
        app_logger.log_info("BATCH_COLLECT_STARTED", f"count={len(self.devices)} concurrency={self.max_workers}")
        success_count = 0
        failed_count = 0

        def on_result(item: BatchCollectItemResult) -> None:
            nonlocal success_count, failed_count
            if self._should_cancel():
                return
            if item.success:
                success_count += 1
                app_logger.log_info(
                    "BATCH_COLLECT_DEVICE_SUCCESS",
                    f"device={item.device_name} primary_address={item.primary_address} collect_run_uuid={item.collect_run_uuid or ''} raw_log_path={item.raw_log_path or ''}",
                )
            else:
                failed_count += 1
                app_logger.log_error(
                    "BATCH_COLLECT_DEVICE_FAILED",
                    f"device={item.device_name} primary_address={item.primary_address} collect_run_uuid={item.collect_run_uuid or ''} raw_log_path={item.raw_log_path or ''}",
                )
            self.device_finished.emit(item)

        run_batch_collect(
            self.devices,
            self.site_name,
            max_workers=self.max_workers,
            result_callback=on_result,
            progress_callback=self.device_progress.emit,
            should_cancel=self._should_cancel,
        )
        app_logger.log_info("BATCH_COLLECT_FINISHED", f"success={success_count} failed={failed_count}")
        self.batch_finished.emit(success_count, failed_count)
