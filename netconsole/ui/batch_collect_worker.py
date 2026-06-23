from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from time import monotonic
from typing import Callable

from PySide6.QtCore import QThread, Signal

from netconsole.core import app_logger
from netconsole.models.device import Device
from netconsole.services.h3c_collect_service import CollectDeviceResult, collect_h3c_device_details


Collector = Callable[[Device, str], CollectDeviceResult]
BATCH_CONCURRENCY = 50


@dataclass(frozen=True)
class BatchCollectItemResult:
    device_name: str
    primary_address: str
    success: bool
    result_text: str
    collect_run_uuid: str | None
    raw_log_path: str | None
    elapsed_ms: int | None = None


def run_batch_collect(
    devices: list[Device],
    site_name: str,
    collector: Collector = collect_h3c_device_details,
    max_workers: int = BATCH_CONCURRENCY,
    result_callback: Callable[[BatchCollectItemResult], None] | None = None,
) -> list[BatchCollectItemResult]:
    results: list[BatchCollectItemResult] = []
    worker_count = max(1, min(int(max_workers or 1), 100, len(devices) or 1))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {executor.submit(collector, device, site_name): device for device in devices}
        started_at = {future: monotonic() for future in futures}
        for future in as_completed(futures):
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
                )
            except Exception as exc:
                item = BatchCollectItemResult(
                    device_name=str(device.name or ""),
                    primary_address=str(device.primary_address or ""),
                    success=False,
                    result_text=str(exc),
                    collect_run_uuid=None,
                    raw_log_path=None,
                    elapsed_ms=elapsed_ms,
                )
            results.append(item)
            if result_callback is not None:
                result_callback(item)
    return results


class BatchCollectWorker(QThread):
    device_finished = Signal(object)
    batch_finished = Signal(int, int)

    def __init__(
        self,
        devices: list[Device],
        site_name: str,
        concurrency: int = BATCH_CONCURRENCY,
        parent=None,
        max_workers: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.devices = list(devices)
        self.site_name = site_name
        self.max_workers = int(max_workers if max_workers is not None else concurrency)
        self.concurrency = self.max_workers

    def run(self) -> None:
        app_logger.log_info("BATCH_COLLECT_STARTED", f"count={len(self.devices)}")
        success_count = 0
        failed_count = 0

        def on_result(item: BatchCollectItemResult) -> None:
            nonlocal success_count, failed_count
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

        run_batch_collect(self.devices, self.site_name, max_workers=self.max_workers, result_callback=on_result)
        app_logger.log_info("BATCH_COLLECT_FINISHED", f"success={success_count} failed={failed_count}")
        self.batch_finished.emit(success_count, failed_count)
