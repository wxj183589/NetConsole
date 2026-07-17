from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from netconsole.core import app_logger
from netconsole.models.device import Device
from netconsole.services.device_batch_operations import (
    BATCH_COLLECT_DEFAULT_CONCURRENCY,
    BATCH_COLLECT_MAX_CONCURRENCY,
    BATCH_CONCURRENCY,
    BatchCollectItemResult,
    BatchCollectProgressUpdate,
    device_key,
    run_batch_collect,
)


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
