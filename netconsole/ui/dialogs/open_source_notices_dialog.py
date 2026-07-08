from __future__ import annotations

import webbrowser
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QDialog

from netconsole.core import app_logger
from netconsole.services.open_source_notice_service import OpenSourceComponent, OpenSourceNoticeService
from netconsole.ui.table_utils import auto_resize_table_columns_to_contents, setup_readable_table


class OpenSourceNoticeThread(QThread):
    result_ready = Signal(object)
    failed = Signal(str)

    def __init__(self, base_dir: Path | None = None) -> None:
        super().__init__()
        self.base_dir = base_dir

    def run(self) -> None:
        try:
            self.result_ready.emit(OpenSourceNoticeService(self.base_dir).list_components())
        except Exception as exc:
            app_logger.log_warning("OPEN_SOURCE_NOTICE_SCAN_FAILED", str(exc))
            self.failed.emit(str(exc))


class OpenSourceNoticesDialog(QDialog):
    HEADERS = ("组件名称", "版本", "许可证", "用途", "项目地址", "备注")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.components: list[OpenSourceComponent] = []
        self.worker: OpenSourceNoticeThread | None = None
        self.setModal(False)
        self.setWindowTitle("开源许可")
        self.setMinimumSize(920, 560)

        layout = QVBoxLayout(self)
        title = QLabel("开源许可")
        title.setObjectName("fluentPageTitle")
        subtitle = QLabel("NetConsole 使用的第三方开源组件及其许可证信息。")
        subtitle.setWordWrap(True)
        warning = QLabel("本软件使用 GPL/LGPL 等开源组件。请在分发软件时遵守对应开源许可证要求。")
        warning.setObjectName("settingRowDescription")
        warning.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(warning)

        actions = QHBoxLayout()
        self.refresh_button = QPushButton("刷新组件列表")
        self.export_button = QPushButton("导出开源许可说明")
        self.copy_button = QPushButton("复制组件信息")
        self.open_homepage_button = QPushButton("打开项目地址")
        for button in (self.refresh_button, self.export_button, self.copy_button, self.open_homepage_button):
            actions.addWidget(button)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.status_label = QLabel("未加载")
        layout.addWidget(self.status_label)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        setup_readable_table(self.table, horizontal_scroll=True, interactive=True, stretch_last_section=False)
        layout.addWidget(self.table, 1)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        self.close_button = QPushButton("关闭")
        close_row.addWidget(self.close_button)
        layout.addLayout(close_row)

        self.refresh_button.clicked.connect(self.refresh_components)
        self.export_button.clicked.connect(self.export_notices)
        self.copy_button.clicked.connect(self.copy_selected_component)
        self.open_homepage_button.clicked.connect(self.open_selected_homepage)
        self.close_button.clicked.connect(self.close)
        self.refresh_components()

    def refresh_components(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        self._set_busy(True, "正在扫描第三方组件...")
        worker = OpenSourceNoticeThread()
        self.worker = worker
        worker.result_ready.connect(self._on_components_loaded)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(lambda: setattr(self, "worker", None))
        worker.start()

    def export_notices(self) -> None:
        if not self.components:
            QMessageBox.information(self, "开源许可", "没有可导出的组件信息。")
            return
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "导出开源许可说明",
            "open_source_notices.xlsx",
            "Excel 文件 (*.xlsx);;文本文件 (*.txt)",
        )
        if not path:
            return
        output = Path(path)
        if selected_filter.startswith("文本") or output.suffix.lower() == ".txt":
            self._export_text(output)
        else:
            if output.suffix.lower() != ".xlsx":
                output = output.with_suffix(".xlsx")
            self._export_xlsx(output)
        QMessageBox.information(self, "导出完成", f"开源许可说明已导出：{output}")

    def copy_selected_component(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.components):
            return
        component = self.components[row]
        QGuiApplication.clipboard().setText(
            "\n".join(
                [
                    f"组件名称：{component.name}",
                    f"版本：{component.version}",
                    f"许可证：{component.license}",
                    f"用途：{component.purpose}",
                    f"项目地址：{component.homepage}",
                    f"备注：{component.note}",
                ]
            )
        )

    def open_selected_homepage(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.components):
            return
        homepage = self.components[row].homepage
        if homepage:
            webbrowser.open(homepage)

    def _on_components_loaded(self, components: list[OpenSourceComponent]) -> None:
        self.components = components
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(0)
        for component in components:
            row = self.table.rowCount()
            self.table.insertRow(row)
            for column, value in enumerate((component.name, component.version, component.license, component.purpose, component.homepage, component.note)):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setToolTip(value)
                self.table.setItem(row, column, item)
        auto_resize_table_columns_to_contents(self.table)
        self.table.setUpdatesEnabled(True)
        self._set_busy(False, f"已加载 {len(components)} 个第三方组件。")

    def _on_failed(self, message: str) -> None:
        self._set_busy(False, f"扫描失败：{message}")
        QMessageBox.warning(self, "开源许可扫描失败", message)

    def _export_text(self, output: Path) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        lines = ["NetConsole 开源许可说明", ""]
        for component in self.components:
            lines.extend(
                [
                    f"组件名称：{component.name}",
                    f"版本：{component.version}",
                    f"许可证：{component.license}",
                    f"用途：{component.purpose}",
                    f"项目地址：{component.homepage}",
                    f"备注：{component.note}",
                    "",
                ]
            )
        output.write_text("\n".join(lines), encoding="utf-8")

    def _export_xlsx(self, output: Path) -> None:
        from openpyxl import Workbook

        output.parent.mkdir(parents=True, exist_ok=True)
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "开源许可"
        sheet.append(list(self.HEADERS))
        for component in self.components:
            sheet.append([component.name, component.version, component.license, component.purpose, component.homepage, component.note])
        for column_cells in sheet.columns:
            max_length = max(len(str(cell.value or "")) for cell in column_cells)
            sheet.column_dimensions[column_cells[0].column_letter].width = min(max(max_length + 2, 12), 48)
        workbook.save(output)

    def _set_busy(self, busy: bool, status: str) -> None:
        self.status_label.setText(status)
        self.refresh_button.setEnabled(not busy)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self.worker is not None and self.worker.isRunning():
            self.worker.requestInterruption()
            self.worker.quit()
            self.worker.wait(1000)
        super().closeEvent(event)
