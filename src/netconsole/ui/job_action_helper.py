from __future__ import annotations

import uuid
from typing import Any, Callable

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QProgressDialog, QWidget

from netconsole.core import app_logger
from netconsole.core.paths import PathResolver
from netconsole.services.background_job import BackgroundJob
from netconsole.services.background_process_manager import BackgroundProcessManager
from netconsole.ui.dialogs.message_service import MessageBox

EventCallback = Callable[[dict[str, Any]], None]


def submit_background_job(
    parent: QWidget,
    job: BackgroundJob,
    *,
    success_title: str = "任务完成",
    progress_title: str = "正在执行后台任务",
    paths: PathResolver | None = None,
    environment: dict[str, str] | None = None,
    on_progress: EventCallback | None = None,
    on_finished: EventCallback | None = None,
    on_failed: EventCallback | None = None,
    on_cancelled: EventCallback | None = None,
) -> str:
    if not job.job_id:
        job = BackgroundJob.from_dict({**job.to_dict(), "job_id": uuid.uuid4().hex})
    controller = BackgroundJobController(
        parent,
        job,
        success_title=success_title,
        progress_title=progress_title,
        paths=paths,
        environment=environment,
        on_progress=on_progress,
        on_finished=on_finished,
        on_failed=on_failed,
        on_cancelled=on_cancelled,
    )
    controllers = getattr(parent, "_netconsole_background_job_controllers", None)
    if not isinstance(controllers, list):
        controllers = []
        setattr(parent, "_netconsole_background_job_controllers", controllers)
    controllers.append(controller)
    controller.terminal.connect(lambda _payload=None, item=controller: _remove_controller(parent, item))
    controller.start()
    return job.job_id


class BackgroundJobController(QObject):
    terminal = Signal(object)

    def __init__(
        self,
        parent: QWidget,
        job: BackgroundJob,
        *,
        success_title: str,
        progress_title: str,
        paths: PathResolver | None = None,
        environment: dict[str, str] | None = None,
        on_progress: EventCallback | None = None,
        on_finished: EventCallback | None = None,
        on_failed: EventCallback | None = None,
        on_cancelled: EventCallback | None = None,
    ) -> None:
        super().__init__(parent)
        self.parent_widget = parent
        self.job = job
        self.success_title = success_title
        self.on_progress = on_progress
        self.on_finished = on_finished
        self.on_failed = on_failed
        self.on_cancelled = on_cancelled
        self._terminal = False
        self._environment = dict(environment or {})
        self.manager = BackgroundProcessManager(self, paths=paths or PathResolver())
        self.dialog = QProgressDialog("准备执行...", "取消", 0, 100, parent)
        self.dialog.setWindowTitle(progress_title)
        self.dialog.setWindowModality(Qt.WindowModality.NonModal)
        self.dialog.setAutoClose(False)
        self.dialog.setAutoReset(False)
        self.dialog.setMinimumDuration(0)
        self.dialog.canceled.connect(self.cancel)
        self.manager.progress.connect(self._on_progress)
        self.manager.finished.connect(self._on_finished)
        self.manager.failed.connect(self._on_failed)
        self.manager.cancelled.connect(self._on_cancelled)

    def start(self) -> None:
        self.dialog.show()
        try:
            self.manager.start_job(self.job, environment=self._environment)
            self._environment.clear()
        except Exception as exc:
            self._environment.clear()
            payload = self._error_payload(str(exc), cancelled=False)
            self._finish_terminal(payload, self.on_failed)
            MessageBox.warning(self.parent_widget, "任务启动失败", str(exc))

    def cancel(self) -> None:
        if self._terminal:
            return
        self.dialog.setLabelText("正在取消任务...")
        self.manager.cancel_job(self.job.job_id)

    def _on_progress(self, event: dict[str, Any]) -> None:
        if self._terminal or str(event.get("job_id") or "") != self.job.job_id:
            return
        total = int(event.get("total") or 0)
        current = int(event.get("current") or 0)
        if total > 0:
            self.dialog.setRange(0, total)
            self.dialog.setValue(min(max(current, 0), total))
        else:
            self.dialog.setRange(0, 0)
        self.dialog.setLabelText(str(event.get("message") or event.get("stage") or "正在执行"))
        self._call(self.on_progress, event)

    def _on_finished(self, payload: dict[str, Any]) -> None:
        if self._terminal or str(payload.get("job_id") or "") != self.job.job_id:
            return
        self._show_success(str(payload.get("message") or "后台任务已完成"))
        self._finish_terminal(payload, self.on_finished)

    def _on_failed(self, payload: dict[str, Any]) -> None:
        if self._terminal or str(payload.get("job_id") or "") != self.job.job_id:
            return
        if bool(payload.get("cancelled")):
            self._on_cancelled(payload)
            return
        MessageBox.warning(self.parent_widget, "任务失败", str(payload.get("message") or payload.get("error") or "后台任务失败"))
        self._finish_terminal(payload, self.on_failed)

    def _on_cancelled(self, payload: dict[str, Any]) -> None:
        if self._terminal or str(payload.get("job_id") or "") != self.job.job_id:
            return
        MessageBox.information(self.parent_widget, "任务已取消", str(payload.get("message") or "后台任务已取消"))
        self._finish_terminal(payload, self.on_cancelled)

    def _finish_terminal(self, payload: dict[str, Any], callback: EventCallback | None) -> None:
        if self._terminal:
            return
        self._terminal = True
        self.dialog.close()
        self._call(callback, payload)
        self.terminal.emit(payload)
        self.deleteLater()

    def _show_success(self, message: str) -> None:
        try:
            from qfluentwidgets import InfoBar, InfoBarPosition

            InfoBar.success(
                title=self.success_title,
                content=message,
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP_RIGHT,
                duration=3600,
                parent=self.parent_widget,
            )
            return
        except Exception:
            pass
        MessageBox.information(self.parent_widget, self.success_title, message)

    def _error_payload(self, message: str, *, cancelled: bool) -> dict[str, Any]:
        return {
            "type": "cancelled" if cancelled else "error",
            "job_id": self.job.job_id,
            "message": message,
            "error": message,
            "traceback": "",
            "cancelled": cancelled,
        }

    @staticmethod
    def _call(callback: EventCallback | None, payload: dict[str, Any]) -> None:
        if callback is not None:
            try:
                callback(payload)
            except Exception as exc:
                app_logger.log_error("BACKGROUND_JOB_UI_CALLBACK_FAILED", str(exc))


def _remove_controller(parent: QWidget, controller: BackgroundJobController) -> None:
    controllers = getattr(parent, "_netconsole_background_job_controllers", None)
    if isinstance(controllers, list) and controller in controllers:
        controllers.remove(controller)
