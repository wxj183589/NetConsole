from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from netconsole.core import app_logger
from netconsole.models.device import Device
from netconsole.services.device_batch_operations import (
    BATCH_CONNECTION_CONCURRENCY_OPTIONS,
    BATCH_CONNECTION_DEFAULT_CONCURRENCY,
    BATCH_CONNECTION_MAX_CONCURRENCY,
    BatchConnectionTestItemResult,
    run_batch_connection_tests,
)


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
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True
        self.requestInterruption()

    def _should_cancel(self) -> bool:
        return self._cancel_requested or self.isInterruptionRequested()

    def run(self) -> None:
        app_logger.log_info("BATCH_TEST_CONNECTION_STARTED", f"count={len(self.devices)}")
        success_count = 0
        failed_count = 0

        def on_result(item: BatchConnectionTestItemResult) -> None:
            nonlocal success_count, failed_count
            if self._should_cancel():
                return
            if item.success:
                success_count += 1
                app_logger.log_info("BATCH_TEST_CONNECTION_DEVICE_SUCCESS", f"device={item.device_name} primary_address={item.primary_address} protocol={item.protocol} method={item.method}")
            else:
                failed_count += 1
                app_logger.log_error("BATCH_TEST_CONNECTION_DEVICE_FAILED", f"device={item.device_name} primary_address={item.primary_address} protocol={item.protocol} method={item.method} error={item.error_message or ''}")
            self.device_finished.emit(item)

        run_batch_connection_tests(self.devices, max_workers=self.concurrency, result_callback=on_result, should_cancel=self._should_cancel)
        app_logger.log_info("BATCH_TEST_CONNECTION_FINISHED", f"success={success_count} failed={failed_count}")
        self.batch_finished.emit(success_count, failed_count)
