from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from time import monotonic
from typing import Callable

from PySide6.QtCore import QThread, Signal

from netconsole.core import app_logger
from netconsole.models.device import Device
from netconsole.services.netmiko_connection import ConnectionTestResult, extract_cli_prompt, test_device_connection


Tester = Callable[[Device], ConnectionTestResult]
BATCH_CONNECTION_DEFAULT_CONCURRENCY = 50
BATCH_CONNECTION_MAX_CONCURRENCY = 200
BATCH_CONNECTION_CONCURRENCY_OPTIONS = (10, 20, 50, 100, 200)


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


def run_batch_connection_tests(
    devices: list[Device],
    tester: Tester = test_device_connection,
    max_workers: int = BATCH_CONNECTION_DEFAULT_CONCURRENCY,
    result_callback: Callable[[BatchConnectionTestItemResult], None] | None = None,
) -> list[BatchConnectionTestItemResult]:
    results: list[BatchConnectionTestItemResult] = []
    worker_count = max(1, min(int(max_workers or 1), BATCH_CONNECTION_MAX_CONCURRENCY, len(devices) or 1))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {executor.submit(tester, device): device for device in devices}
        started_at = {future: monotonic() for future in futures}
        for future in as_completed(futures):
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
    return results


class BatchConnectionTestWorker(QThread):
    device_finished = Signal(object)
    batch_finished = Signal(int, int)

    def __init__(
        self,
        devices: list[Device],
        site_name: str | None = None,
        concurrency: int = BATCH_CONNECTION_DEFAULT_CONCURRENCY,
        parent=None,
        max_workers: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.devices = list(devices)
        self.site_name = site_name
        self.concurrency = max(1, min(int(max_workers if max_workers is not None else concurrency), BATCH_CONNECTION_MAX_CONCURRENCY))
        self.max_workers = self.concurrency

    def run(self) -> None:
        app_logger.log_info("BATCH_TEST_CONNECTION_STARTED", f"count={len(self.devices)}")
        success_count = 0
        failed_count = 0

        def on_result(item: BatchConnectionTestItemResult) -> None:
            nonlocal success_count, failed_count
            if item.success:
                success_count += 1
                app_logger.log_info("BATCH_TEST_CONNECTION_DEVICE_SUCCESS", f"device={item.device_name} primary_address={item.primary_address} protocol={item.protocol} method={item.method}")
            else:
                failed_count += 1
                app_logger.log_error("BATCH_TEST_CONNECTION_DEVICE_FAILED", f"device={item.device_name} primary_address={item.primary_address} protocol={item.protocol} method={item.method} error={item.error_message or ''}")
            self.device_finished.emit(item)

        run_batch_connection_tests(self.devices, max_workers=self.concurrency, result_callback=on_result)
        app_logger.log_info("BATCH_TEST_CONNECTION_FINISHED", f"success={success_count} failed={failed_count}")
        self.batch_finished.emit(success_count, failed_count)
