from __future__ import annotations

from time import monotonic

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QDialog, QLabel, QMessageBox, QProgressBar, QPushButton, QTextEdit, QVBoxLayout

from netconsole.core.shutdown_manager import ShutdownManager, shutdown_manager
from netconsole.ui.window_registry import window_registry


class ShutdownProgressDialog(QDialog):
    finished = Signal()

    def __init__(self, manager: ShutdownManager | None = None, parent=None) -> None:
        super().__init__(parent)
        self.manager = manager or shutdown_manager
        self.started_at = monotonic()
        self.phase_started_at = self.started_at
        self.phase = 0
        self.tasks_stop_requested = False
        self.process_terminate_requested = False
        self.setWindowTitle("正在退出 NetConsole")
        self.setModal(True)
        self.setMinimumWidth(520)
        self.status_label = QLabel("正在安全关闭，请稍候...")
        self.detail_label = QLabel("")
        self.progress = QProgressBar()
        self.progress.setRange(0, 6)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.background_button = QPushButton("最小化到后台等待")
        self.kill_process_button = QPushButton("强制结束外部进程")
        self.kill_process_button.setEnabled(False)

        layout = QVBoxLayout(self)
        layout.addWidget(self.status_label)
        layout.addWidget(self.detail_label)
        layout.addWidget(self.progress)
        layout.addWidget(self.log_text)
        layout.addWidget(self.background_button)
        layout.addWidget(self.kill_process_button)

        self.timer = QTimer(self)
        self.timer.setInterval(80)
        self.timer.timeout.connect(self._step)
        self.background_button.clicked.connect(self.hide)
        self.kill_process_button.clicked.connect(self._kill_processes)

    def start(self) -> None:
        self._log("开始退出流程")
        self.show()
        self.raise_()
        self.timer.start()

    def _step(self) -> None:
        snapshot = self.manager.snapshot()
        elapsed = monotonic() - self.started_at
        self.detail_label.setText(f"剩余任务: {snapshot.task_count} | 剩余进程: {snapshot.process_count} | 已耗时: {elapsed:.1f}s")
        if self.phase == 0:
            self._set_phase(1, "正在准备关闭页面...")
            prepared = window_registry.prepare_all("app_exit", root=self.parent(), exclude={self}, include_unregistered=True)
            self._log(f"已准备关闭页面: {prepared}")
            self.phase = 1
            return
        if self.phase == 1:
            self._set_phase(2, "正在停止后台任务...")
            if not self.tasks_stop_requested:
                self.manager.request_stop_tasks()
                self.tasks_stop_requested = True
            if self.manager.wait_tasks_once(0.02):
                self._log("后台任务已停止")
                self.phase = 2
            elif monotonic() - self.phase_started_at > 8:
                self._log("后台任务等待超时，继续退出流程")
                self.phase = 2
            return
        if self.phase == 2:
            self._set_phase(3, "正在等待内部进程退出...")
            if not self.process_terminate_requested:
                self.manager.terminate_processes()
                self.process_terminate_requested = True
            if self.manager.wait_processes_once(0.02):
                self._log("内部进程已退出")
                self.phase = 3
            elif monotonic() - self.phase_started_at > 8:
                self._log("内部进程等待超时，继续退出流程")
                self.phase = 3
            elif elapsed > 5:
                self.kill_process_button.setEnabled(True)
            return
        if self.phase == 3:
            self._set_phase(4, "正在关闭子窗口...")
            closed = window_registry.close_all("app_exit", main_window=self.parent(), exclude={self}, include_unregistered=True)
            self._log(f"已请求关闭子窗口: {closed}")
            self.phase = 4
            return
        if self.phase == 4:
            self._set_phase(5, "正在保存状态...")
            self.phase = 5
            return
        self._set_phase(6, "即将退出...")
        self.timer.stop()
        self.finished.emit()

    def _set_phase(self, value: int, text: str) -> None:
        if self.progress.value() != value:
            self.progress.setValue(value)
            self.phase_started_at = monotonic()
            self._log(text)
        self.status_label.setText(text)

    def _kill_processes(self) -> None:
        answer = QMessageBox.question(self, "强制结束外部进程", "确认强制结束仍未退出的外部进程？")
        if answer != QMessageBox.Yes:
            return
        self._log("用户确认后强制结束外部进程")
        self.manager.kill_processes()
        self.kill_process_button.setEnabled(False)

    def _log(self, text: str) -> None:
        self.log_text.append(text)

