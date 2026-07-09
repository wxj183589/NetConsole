from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QProgressDialog, QWidget

from netconsole.core.paths import PathResolver
from netconsole.services.export.export_job import ExportJob
from netconsole.services.export.export_process_manager import ExportProcessManager
from netconsole.services.export.export_task_builders import ExportTaskSpec
from netconsole.ui.dialogs.message_service import MessageBox


def submit_export_task(
    parent: QWidget,
    task_spec: ExportTaskSpec | ExportJob,
    *,
    success_title: str = "导出完成",
    paths: PathResolver | None = None,
) -> str:
    job = task_spec.to_job() if isinstance(task_spec, ExportTaskSpec) else task_spec
    controller = ExportTaskController(parent, job, success_title=success_title, paths=paths)
    controllers = getattr(parent, "_netconsole_export_controllers", None)
    if not isinstance(controllers, list):
        controllers = []
        setattr(parent, "_netconsole_export_controllers", controllers)
    controllers.append(controller)
    controller.finished.connect(lambda _payload=None, item=controller: _remove_controller(parent, item))
    controller.start()
    return job.job_id


class ExportTaskController(QObject):
    finished = Signal(object)

    def __init__(self, parent: QWidget, job: ExportJob, *, success_title: str, paths: PathResolver | None = None) -> None:
        super().__init__(parent)
        self.parent_widget = parent
        self.job = job
        self.success_title = success_title
        self.manager = ExportProcessManager(self, paths=paths or PathResolver())
        self.dialog = QProgressDialog("准备导出...", "取消", 0, 100, parent)
        self.dialog.setWindowTitle("正在导出")
        self.dialog.setWindowModality(Qt.WindowModality.NonModal)
        self.dialog.setAutoClose(False)
        self.dialog.setAutoReset(False)
        self.dialog.setMinimumDuration(0)
        self.dialog.canceled.connect(self.cancel)
        self.manager.progress.connect(self._on_progress)
        self.manager.finished.connect(self._on_finished)
        self.manager.failed.connect(self._on_failed)

    def start(self) -> None:
        self.dialog.show()
        try:
            self.manager.start_export(self.job)
        except Exception as exc:
            self.dialog.close()
            MessageBox.warning(self.parent_widget, "导出失败", str(exc))
            self.deleteLater()

    def cancel(self) -> None:
        self.dialog.setLabelText("正在取消导出...")
        self.manager.cancel_export(self.job.job_id)

    def _on_progress(self, event: dict[str, Any]) -> None:
        if str(event.get("job_id") or "") != self.job.job_id:
            return
        total = int(event.get("total") or 0)
        current = int(event.get("current", event.get("done", 0)) or 0)
        if total > 0:
            self.dialog.setRange(0, total)
            self.dialog.setValue(min(current, total))
        else:
            self.dialog.setRange(0, 0)
        message = str(event.get("message") or event.get("stage") or "正在导出")
        self.dialog.setLabelText(message)

    def _on_finished(self, payload: dict[str, Any]) -> None:
        if str(payload.get("job_id") or "") != self.job.job_id:
            return
        self.dialog.close()
        output_path = Path(str(payload.get("output_path") or self.job.output_path))
        self._show_success(output_path)
        if bool(self.job.params.get("open_dir_on_success")):
            open_target = output_path if output_path.is_dir() else output_path.parent
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(open_target)))
        self.finished.emit(payload)
        self.deleteLater()

    def _show_success(self, output_path: Path) -> None:
        try:
            from qfluentwidgets import InfoBar, InfoBarPosition

            InfoBar.success(
                title=self.success_title,
                content=f"已导出：{output_path}",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP_RIGHT,
                duration=3600,
                parent=self.parent_widget,
            )
            return
        except Exception:
            pass
        box = MessageBox(self.parent_widget)
        box.setIcon(MessageBox.Information)
        box.setWindowTitle(self.success_title)
        box.setText(f"已导出：{output_path}")
        box.setStandardButtons(MessageBox.Ok)
        box.open()
        box.finished.connect(box.deleteLater)

    def _on_failed(self, payload: dict[str, Any]) -> None:
        if str(payload.get("job_id") or "") != self.job.job_id:
            return
        self.dialog.close()
        if bool(payload.get("cancelled")):
            MessageBox.information(self.parent_widget, "导出已取消", str(payload.get("message") or "已取消导出"))
        else:
            MessageBox.warning(self.parent_widget, "导出失败", str(payload.get("message") or payload.get("error") or "导出失败"))
        self.finished.emit(payload)
        self.deleteLater()


def _remove_controller(parent: QWidget, controller: ExportTaskController) -> None:
    controllers = getattr(parent, "_netconsole_export_controllers", None)
    if isinstance(controllers, list) and controller in controllers:
        controllers.remove(controller)
