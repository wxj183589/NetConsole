from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from netconsole.core.paths import PathResolver
from netconsole.services.command_reference_service import CommandReference, export_command_references_markdown, load_command_references, unique_values
from netconsole.ui.shell.fluent_bridge import ComboBox, InfoBar, InfoBarPosition, PushButton
from netconsole.ui.table_utils import auto_resize_table_columns_to_contents, configure_readonly_table, make_table_item


FILTER_FIELDS = (
    ("module", "模块"),
    ("device_scope", "设备类型"),
    ("vendor", "厂商"),
    ("protocol", "协议"),
    ("category", "类别"),
    ("risk_level", "风险级别"),
)

TABLE_COLUMNS = (
    ("category", "类别"),
    ("command_template", "命令"),
    ("purpose", "当前用途"),
    ("module", "模块"),
    ("device_scope", "设备类型"),
    ("vendor", "厂商"),
    ("pre_commands", "前置条件"),
    ("risk_level", "风险级别"),
    ("notes", "备注"),
)


class CommandReferencePage(QWidget):
    def __init__(self, paths: PathResolver | None = None) -> None:
        super().__init__()
        self.paths = paths or PathResolver()
        self.references: list[CommandReference] = []
        self.filtered_references: list[CommandReference] = []
        self.filter_combos: dict[str, ComboBox | object] = {}
        self.setObjectName("commandReferencePage")

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("搜索命令、用途、模块、源码位置")
        self.table = QTableWidget(0, len(TABLE_COLUMNS))
        self.detail_text = QPlainTextEdit()
        self.detail_text.setReadOnly(True)
        self.summary_label = QLabel("命令清单加载中...")
        self.copy_button = self._button("复制命令模板")
        self.export_button = self._button("导出 Markdown")

        self._build_ui()
        self._connect_signals()
        self.load_references()

    def load_references(self) -> None:
        try:
            self.references = load_command_references(self.paths)
        except Exception as exc:
            self.references = []
            self._show_error("命令说明加载失败", str(exc))
        self._populate_filters()
        self.apply_filters()

    def apply_filters(self) -> None:
        keyword = self.search_edit.text().strip().casefold()
        result: list[CommandReference] = []
        for item in self.references:
            if keyword and keyword not in self._search_blob(item):
                continue
            if not self._passes_combo_filters(item):
                continue
            result.append(item)
        self.filtered_references = result
        self._populate_table(result)
        self._update_summary()

    def copy_selected_command(self) -> None:
        item = self._selected_reference()
        if item is None:
            self._show_info("未选择命令", "请先选择一条命令说明。")
            return
        QApplication.clipboard().setText(item.command_template)
        self._show_info("已复制", "命令模板已复制到剪贴板。")

    def export_markdown(self) -> None:
        default_path = Path.home() / "NetConsole_软件使用命令清单.md"
        path_text, _ = QFileDialog.getSaveFileName(self, "导出命令说明", str(default_path), "Markdown (*.md)")
        if not path_text:
            return
        target = Path(path_text)
        target.write_text(export_command_references_markdown(self.filtered_references), encoding="utf-8")
        self._show_info("导出完成", f"已导出：{target}")

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 0, 10, 10)
        layout.setSpacing(10)

        filter_bar = QFrame()
        filter_bar.setObjectName("commandReferenceFilterBar")
        filter_layout = QHBoxLayout(filter_bar)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(8)
        filter_layout.addWidget(self.search_edit, 2)
        for field_name, label in FILTER_FIELDS:
            combo = self._combo()
            combo.setMinimumWidth(128)
            combo.setToolTip(label)
            self.filter_combos[field_name] = combo
            filter_layout.addWidget(combo)
        filter_layout.addWidget(self.copy_button)
        filter_layout.addWidget(self.export_button)
        layout.addWidget(filter_bar)
        layout.addWidget(self.summary_label)

        self.table.setHorizontalHeaderLabels([title for _field, title in TABLE_COLUMNS])
        self.table.setProperty("netconsole_column_fields", [field for field, _title in TABLE_COLUMNS])
        configure_readonly_table(self.table)
        self.table.setAlternatingRowColors(True)

        self.detail_text.setMinimumWidth(360)
        self.detail_text.setPlaceholderText("选择左侧命令后查看详情。")

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.table)
        splitter.addWidget(self.detail_text)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)

    def _connect_signals(self) -> None:
        self.search_edit.textChanged.connect(self.apply_filters)
        for combo in self.filter_combos.values():
            combo.currentIndexChanged.connect(self.apply_filters)
        self.table.itemSelectionChanged.connect(self._show_selected_detail)
        self.copy_button.clicked.connect(self.copy_selected_command)
        self.export_button.clicked.connect(self.export_markdown)

    def _populate_filters(self) -> None:
        for field_name, _label in FILTER_FIELDS:
            combo = self.filter_combos[field_name]
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("全部")
            combo.addItems(unique_values(self.references, field_name))
            if current:
                index = combo.findText(current)
                combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)

    def _populate_table(self, rows: list[CommandReference]) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        for row_index, item in enumerate(rows):
            for column_index, (field_name, _title) in enumerate(TABLE_COLUMNS):
                value = getattr(item, field_name)
                if isinstance(value, list):
                    value = ", ".join(str(part) for part in value)
                table_item = make_table_item(value, align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                table_item.setData(Qt.ItemDataRole.UserRole, item.id)
                self.table.setItem(row_index, column_index, table_item)
        self.table.blockSignals(False)
        auto_resize_table_columns_to_contents(
            self.table,
            column_min_widths={1: 220, 2: 220, 3: 150, 6: 160, 8: 240},
            column_max_widths={1: 520, 2: 520, 8: 520},
        )
        if rows:
            self.table.selectRow(0)
        else:
            self.detail_text.clear()

    def _show_selected_detail(self) -> None:
        item = self._selected_reference()
        if item is None:
            self.detail_text.clear()
            return
        self.detail_text.setPlainText(self._detail_text(item))

    def _selected_reference(self) -> CommandReference | None:
        selected = self.table.selectedItems()
        if not selected:
            return None
        row = selected[0].row()
        if not 0 <= row < len(self.filtered_references):
            return None
        return self.filtered_references[row]

    def _passes_combo_filters(self, item: CommandReference) -> bool:
        for field_name, combo in self.filter_combos.items():
            value = combo.currentText()
            if value and value != "全部" and str(getattr(item, field_name, "")) != value:
                return False
        return True

    def _search_blob(self, item: CommandReference) -> str:
        parts = [
            item.id,
            item.module,
            item.device_scope,
            item.vendor,
            item.protocol,
            item.category,
            item.command_template,
            item.purpose,
            item.parser,
            item.consumer,
            item.notes,
            " ".join(item.source_locations),
        ]
        return " ".join(parts).casefold()

    def _detail_text(self, item: CommandReference) -> str:
        parameters = "\n".join(f"- {row.get('name', '')}: {row.get('description', '')}" for row in item.parameters) or "-"
        return "\n".join(
            [
                f"命令模板：{item.command_template}",
                f"模块：{item.module}",
                f"设备类型：{item.device_scope}",
                f"厂商 / 协议：{item.vendor} / {item.protocol}",
                f"类别：{item.category}",
                f"当前用途：{item.purpose}",
                f"风险级别：{item.risk_level}",
                f"是否只读：{'否' if item.risk_level == 'config_write' else '是' if item.risk_level == 'read_only' else '需按风险级别判断'}",
                f"是否修改设备配置：{'是' if item.risk_level == 'config_write' else '否'}",
                f"是否存在交互确认：{'是' if item.interactive_input else '否'}",
                "",
                "参数说明：",
                parameters,
                "",
                f"前置命令：{', '.join(item.pre_commands) if item.pre_commands else '-'}",
                f"输出文件 / 日志文件：{item.output_log or '-'}",
                f"对应解析器 / 消费模块：{item.parser or '-'} / {item.consumer or '-'}",
                f"源码位置：{', '.join(item.source_locations) if item.source_locations else '-'}",
                "",
                f"Comware 命令：{item.comware_command or '-'}",
                f"ZTE 命令：{item.zte_command or '-'}",
                f"中兴适配状态：{item.zte_adaptation_status}",
                f"解析器状态：{item.parser_status or '-'}",
                f"注意事项：{item.notes or '-'}",
            ]
        )

    def _update_summary(self) -> None:
        total = len(self.references)
        shown = len(self.filtered_references)
        switch_count = sum(1 for item in self.references if item.device_scope.startswith("交换机"))
        non_cli = sum(1 for item in self.references if not item.is_cli)
        self.summary_label.setText(f"已归档 {total} 条，当前显示 {shown} 条；交换机 {switch_count} 条，非 CLI / 本地工具 {non_cli} 条。")

    def _combo(self):
        combo_class = ComboBox if ComboBox is not None else None
        return combo_class(self) if combo_class is not None else QComboBox(self)

    def _button(self, text: str) -> QPushButton:
        button = PushButton(text, self) if PushButton is not None else QPushButton(text, self)
        button.setToolTip(text)
        button.setMinimumWidth(112)
        return button

    def _show_info(self, title: str, message: str) -> None:
        if InfoBar is not None and InfoBarPosition is not None:
            InfoBar.success(title, message, parent=self, position=InfoBarPosition.TOP_RIGHT)
            return
        QMessageBox.information(self, title, message)

    def _show_error(self, title: str, message: str) -> None:
        if InfoBar is not None and InfoBarPosition is not None:
            InfoBar.error(title, message, parent=self, position=InfoBarPosition.TOP_RIGHT)
            return
        QMessageBox.warning(self, title, message)
