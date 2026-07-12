from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from netconsole.core.paths import PathResolver
from netconsole.core.settings import SettingsStore
from netconsole.models.omnipeek_name_table import (
    ENTRY_KIND_GROUP_SUFFIX,
    ENTRY_KIND_LABELS,
    OMNIPEEK_ENTRY_KIND_ORDER,
    SOURCE_AC_FIT_AP,
    SOURCE_AP_EXTENSION,
    SOURCE_DEVICE_MANAGEMENT,
    OmniPeekDeviceItem,
    OmniPeekEntryKind,
    OmniPeekExportConfig,
)
from netconsole.services.omnipeek_name_table_service import (
    infer_line_name_from_items,
    load_omnipeek_color_settings,
    load_omnipeek_last_export_dir,
    make_omnipeek_filename,
    prepare_omnipeek_items,
    save_omnipeek_color_settings,
    save_omnipeek_last_export_dir,
)
from netconsole.ui.dialogs.message_service import MessageBox
from netconsole.services.export.export_task_builders import omnipeek_name_table_spec
from netconsole.ui.export_action_helper import submit_export_task
from netconsole.ui.export_path import default_export_dir, remember_export_path
from netconsole.ui.table_utils import auto_fit_table_columns, configure_readable_table_columns
from netconsole.ui.widgets.table_check_delegate import create_checkable_table_item, install_checkbox_only_delegate, is_checked_value


PREVIEW_COLUMNS = (
    "勾选",
    "类型",
    "名称",
    "归属站点 / 归属区间",
    "物理MAC",
    "R1导出MAC",
    "R2导出MAC",
    "R1来源",
    "R2来源",
    "导出内容",
    "Group",
    "Color",
    "数据来源",
    "状态",
)

RADIO_MODE_LABELS = {
    "auto": "自动",
    "r1_only": "只导出R1",
    "r2_only": "只导出R2",
    "r1_r2": "同时导出R1+R2",
    "none": "不导出R1R2",
}

PREVIEW_COLUMN_MIN_WIDTHS = {
    0: 70,
    1: 90,
    2: 180,
    3: 160,
    4: 150,
    5: 150,
    6: 150,
    7: 120,
    8: 120,
    9: 130,
    10: 260,
    11: 120,
    12: 120,
    13: 180,
}
PREVIEW_COLUMN_MAX_WIDTHS = {
    0: 70,
    1: 90,
    2: 320,
    3: 300,
    4: 170,
    5: 170,
    6: 170,
    7: 180,
    8: 180,
    9: 220,
    10: 520,
    11: 160,
    12: 240,
    13: 300,
}
PREVIEW_FIXED_COLUMNS = {0, 1}
PREVIEW_FILTER_LABELS = {
    "all": "全部",
    "selected": "已选",
    "abnormal": "异常",
    "mac_conflict": "MAC冲突",
    "r2_failed": "R2推导失败",
    "missing_mac": "缺少物理MAC",
}


class OmniPeekExportDialog(QDialog):
    def __init__(
        self,
        items: list[OmniPeekDeviceItem],
        source_counts: dict[str, int],
        *,
        default_line_name: str,
        source: dict[str, object] | None = None,
        preview_stats: dict[str, int] | None = None,
        settings: SettingsStore | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("导出 OmniPeek 名称表")
        self.settings = settings or SettingsStore(PathResolver())
        self.items = items
        self.source_counts = dict(source_counts)
        self.source = dict(source or {})
        self.preview_stats = dict(preview_stats or {})
        self._initial_item_selection = {item.key: bool(item.selected) for item in items}
        self.colors = load_omnipeek_color_settings(self.settings)
        self.preview_items: list[OmniPeekDeviceItem] = []
        self.visible_preview_items: list[OmniPeekDeviceItem] = []
        self._updating_preview = False
        self.preview_filter = "all"

        self.line_name_input = QLineEdit(infer_line_name_from_items(items, default_line_name))
        self.file_name_input = QLineEdit(make_omnipeek_filename(self.line_name_input.text()))
        self.output_dir_input = QLineEdit(str(load_omnipeek_last_export_dir(self.settings) or default_export_dir()))
        self.browse_dir_button = QPushButton("浏览")

        self.ac_source_check = QCheckBox(f"AC FIT-AP资源：{self.source_counts.get(SOURCE_AC_FIT_AP, 0)} 条")
        self.extension_source_check = QCheckBox(f"AP扩展信息：{self.source_counts.get(SOURCE_AP_EXTENSION, 0)} 条")
        self.device_source_check = QCheckBox(f"设备管理车载MR：{self.source_counts.get(SOURCE_DEVICE_MANAGEMENT, 0)} 条")
        for checkbox in (self.ac_source_check, self.extension_source_check, self.device_source_check):
            checkbox.setChecked(True)

        self.trackside_physical_check = QCheckBox("导出轨旁AP物理MAC")
        self.trackside_r1_check = QCheckBox("导出轨旁AP R1")
        self.trackside_r2_check = QCheckBox("导出轨旁AP R2")
        self.onboard_physical_check = QCheckBox("导出车载MR物理MAC")
        self.onboard_r1_check = QCheckBox("导出车载MR R1")
        self.onboard_r2_check = QCheckBox("导出车载MR R2")
        for checkbox in (
            self.trackside_physical_check,
            self.trackside_r1_check,
            self.trackside_r2_check,
            self.onboard_physical_check,
            self.onboard_r1_check,
            self.onboard_r2_check,
        ):
            checkbox.setChecked(True)

        self.radio_mode_combo = QComboBox()
        for value, label in RADIO_MODE_LABELS.items():
            self.radio_mode_combo.addItem(label, value)
        self.h3c_derivation_check = QCheckBox("启用 H3C 物理MAC推导 R1/R2")
        self.h3c_derivation_check.setChecked(True)

        self.color_buttons: dict[OmniPeekEntryKind, QPushButton] = {}
        self.preview_table = QTableWidget(0, len(PREVIEW_COLUMNS))
        self.preview_summary_label = QLabel()
        self.preview_summary_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.preview_filter_buttons: dict[str, QPushButton] = {}
        self.preview_filter_group = QButtonGroup(self)
        self.preview_filter_group.setExclusive(True)
        self.preview_search_input = QLineEdit()
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.setVisible(False)
        self.export_button = QPushButton("导出")
        self.open_dir_button = QPushButton("打开目录")
        self.close_button = QPushButton("取消")

        self._build_layout()
        self._apply_initial_geometry()

        self.line_name_input.textChanged.connect(self._sync_filename_from_line_name)
        self.browse_dir_button.clicked.connect(self._browse_output_dir)
        self.open_dir_button.clicked.connect(self._open_output_dir)
        for widget in (
            self.ac_source_check,
            self.extension_source_check,
            self.device_source_check,
            self.trackside_physical_check,
            self.trackside_r1_check,
            self.trackside_r2_check,
            self.onboard_physical_check,
            self.onboard_r1_check,
            self.onboard_r2_check,
            self.radio_mode_combo,
            self.h3c_derivation_check,
        ):
            if isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(self.refresh_preview)
            else:
                widget.stateChanged.connect(self.refresh_preview)
        self.preview_table.itemChanged.connect(self._handle_preview_item_changed)
        self.preview_search_input.textChanged.connect(self._apply_preview_filter)
        self.export_button.clicked.connect(self.export)
        self.close_button.clicked.connect(self.reject)
        self.refresh_preview()

    def _build_layout(self) -> None:
        self.setMinimumSize(900, 620)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)
        scroll_content = QWidget(self)
        scroll_content.setMinimumWidth(900)
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(10)

        config_content = QWidget(self)
        config_layout = QVBoxLayout(config_content)
        config_layout.setContentsMargins(0, 0, 0, 0)
        config_layout.setSpacing(8)
        config_layout.addWidget(self._build_basic_group())
        config_layout.addWidget(self._build_source_group())
        config_layout.addWidget(self._build_content_group())
        config_layout.addWidget(self._build_rule_group())
        config_layout.addWidget(self._build_color_group())

        config_scroll = QScrollArea(self)
        config_scroll.setObjectName("omnipeekConfigScrollArea")
        config_scroll.setWidgetResizable(True)
        config_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        config_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        config_scroll.setFrameShape(QFrame.NoFrame)
        config_scroll.setMaximumHeight(300)
        config_scroll.setMinimumHeight(96)
        config_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        config_content.setMinimumWidth(680)
        config_scroll.setWidget(config_content)

        scroll_layout.addWidget(config_scroll, 0)
        scroll_layout.addWidget(self._build_preview_group(), 1)

        body_scroll = QScrollArea(self)
        body_scroll.setObjectName("omnipeekBodyScrollArea")
        body_scroll.setWidgetResizable(True)
        body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        body_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        body_scroll.setFrameShape(QFrame.NoFrame)
        body_scroll.setWidget(scroll_content)
        body_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        root.addWidget(body_scroll, 1)
        root.addWidget(self.progress, 0)
        root.addWidget(self._build_footer(), 0)

    def _apply_initial_geometry(self) -> None:
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            self.resize(1200, 760)
            return
        available = screen.availableGeometry()
        width = min(max(1000, int(available.width() * 0.8)), max(900, available.width() - 40))
        height = min(max(700, int(available.height() * 0.8)), max(620, available.height() - 40))
        self.resize(width, height)
        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        self.move(frame.topLeft())

    def _build_basic_group(self) -> QGroupBox:
        group = QGroupBox("基础信息")
        form = QFormLayout(group)
        self.line_name_input.setMinimumWidth(260)
        self.file_name_input.setMinimumWidth(260)
        self.output_dir_input.setMinimumWidth(360)
        output_row = QHBoxLayout()
        output_row.addWidget(self.output_dir_input, 1)
        output_row.addWidget(self.browse_dir_button)
        form.addRow("线路名称", self.line_name_input)
        form.addRow("输出文件名", self.file_name_input)
        form.addRow("输出目录", output_row)
        return group

    def _build_source_group(self) -> QGroupBox:
        group = QGroupBox("数据源选择")
        layout = QHBoxLayout(group)
        for checkbox in (self.ac_source_check, self.extension_source_check, self.device_source_check):
            layout.addWidget(checkbox)
        layout.addStretch(1)
        return group

    def _build_content_group(self) -> QGroupBox:
        group = QGroupBox("导出内容")
        layout = QGridLayout(group)
        widgets = (
            self.trackside_physical_check,
            self.trackside_r1_check,
            self.trackside_r2_check,
            self.onboard_physical_check,
            self.onboard_r1_check,
            self.onboard_r2_check,
        )
        for index, widget in enumerate(widgets):
            layout.addWidget(widget, index // 3, index % 3)
        layout.addWidget(QLabel("车载 MR 射频导出模式"), 2, 0)
        layout.addWidget(self.radio_mode_combo, 2, 1)
        return group

    def _build_rule_group(self) -> QGroupBox:
        group = QGroupBox("H3C 推导规则")
        layout = QVBoxLayout(group)
        label = QLabel("R1 = 物理MAC最后一位改为F\nR2 = 物理MAC倒数第二位十六进制+1，最后一位改为F")
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(label)
        layout.addWidget(self.h3c_derivation_check)
        return group

    def _build_color_group(self) -> QGroupBox:
        group = QGroupBox("颜色设置")
        layout = QGridLayout(group)
        for index, kind in enumerate(OMNIPEEK_ENTRY_KIND_ORDER):
            label = QLabel(ENTRY_KIND_LABELS[kind])
            button = QPushButton(self.colors[kind])
            button.setMinimumWidth(110)
            button.clicked.connect(lambda _=False, entry_kind=kind: self._choose_color(entry_kind))
            self.color_buttons[kind] = button
            self._apply_color_button_style(kind)
            layout.addWidget(label, index // 3, (index % 3) * 2)
            layout.addWidget(button, index // 3, (index % 3) * 2 + 1)
        return group

    def _build_preview_group(self) -> QGroupBox:
        group = QGroupBox("预览表")
        group.setMinimumHeight(420)
        group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(self._build_preview_filter_bar(), 0)
        self.preview_table.setHorizontalHeaderLabels(PREVIEW_COLUMNS)
        self.preview_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.preview_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.preview_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.preview_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.preview_table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.preview_table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.preview_table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.preview_table.setMinimumHeight(380)
        self.preview_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview_table.verticalHeader().setDefaultSectionSize(33)
        self.preview_table.verticalHeader().setMinimumSectionSize(30)
        install_checkbox_only_delegate(self.preview_table, 0)
        configure_readable_table_columns(self.preview_table)
        self.preview_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.preview_table.horizontalHeader().setStretchLastSection(False)
        layout.addWidget(self.preview_table, 1)
        return group

    def _build_preview_filter_bar(self) -> QWidget:
        bar = QWidget(self)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.preview_summary_label)
        for key, label in PREVIEW_FILTER_LABELS.items():
            button = QPushButton(label)
            button.setCheckable(True)
            button.setMinimumWidth(74 if key != "r2_failed" else 100)
            if key == "all":
                button.setChecked(True)
            if key in {"abnormal", "mac_conflict", "r2_failed", "missing_mac"}:
                button.setObjectName("omnipeekWarningFilterButton")
                button.setStyleSheet(
                    "QPushButton { color: #B91C1C; border: 1px solid #FCA5A5; padding: 4px 8px; }"
                    "QPushButton:checked { background: #FEE2E2; color: #991B1B; }"
                )
            button.clicked.connect(lambda _checked=False, value=key: self._set_preview_filter(value))
            self.preview_filter_group.addButton(button)
            self.preview_filter_buttons[key] = button
            layout.addWidget(button)
        self.preview_search_input.setPlaceholderText("搜索名称、MAC、归属站点")
        self.preview_search_input.setMinimumWidth(220)
        layout.addWidget(self.preview_search_input, 1)
        return bar

    def _build_footer(self) -> QWidget:
        footer = QWidget(self)
        footer.setMinimumHeight(56)
        footer.setMaximumHeight(64)
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(12)
        layout.addStretch(1)
        for button in (self.open_dir_button, self.export_button, self.close_button):
            button.setMinimumWidth(88)
            button.setMinimumHeight(36)
            layout.addWidget(button)
        return footer

    def _sync_filename_from_line_name(self) -> None:
        self.file_name_input.setText(make_omnipeek_filename(self.line_name_input.text()))
        self.refresh_preview()

    def _browse_output_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "选择输出目录", self.output_dir_input.text())
        if selected:
            self.output_dir_input.setText(selected)

    def _open_output_dir(self) -> None:
        directory = Path(self.output_dir_input.text().strip() or str(default_export_dir()))
        directory.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))

    def _choose_color(self, kind: OmniPeekEntryKind) -> None:
        color = QColorDialog.getColor(QColor(self.colors[kind]), self, ENTRY_KIND_LABELS[kind])
        if not color.isValid():
            return
        self.colors[kind] = color.name().upper()
        self._apply_color_button_style(kind)
        self.refresh_preview()

    def _apply_color_button_style(self, kind: OmniPeekEntryKind) -> None:
        button = self.color_buttons[kind]
        color = self.colors[kind]
        button.setText(color)
        button.setStyleSheet(f"QPushButton {{ background: {color}; color: #111827; min-width: 100px; }}")

    def refresh_preview(self) -> None:
        config = self._config()
        prepared = prepare_omnipeek_items(self._filtered_items(), config)
        self.preview_items = prepared
        self._refresh_preview_filter_labels()
        self._populate_preview_table(self._visible_items())

    def _populate_preview_table(self, rows: list[OmniPeekDeviceItem]) -> None:
        config = self._config()
        self.visible_preview_items = rows
        self._updating_preview = True
        with QSignalBlocker(self.preview_table):
            self.preview_table.setRowCount(len(rows))
            for row, item in enumerate(rows):
                self.preview_table.setItem(row, 0, create_checkable_table_item(item.selected, user_data=item.key, enabled=True))
                values = self._preview_values(item, config)
                for column, value in enumerate(values, start=1):
                    table_item = QTableWidgetItem(value)
                    table_item.setToolTip(value)
                    table_item.setFlags(table_item.flags() & ~Qt.ItemIsEditable)
                    if column == 11 and value:
                        table_item.setBackground(QColor(value.split(",")[0].strip()))
                    self.preview_table.setItem(row, column, table_item)
        self._updating_preview = False
        self._update_preview_summary()
        self._apply_preview_table_layout()

    def _filtered_items(self) -> list[OmniPeekDeviceItem]:
        include_sources = {
            SOURCE_AC_FIT_AP: self.ac_source_check.isChecked(),
            SOURCE_AP_EXTENSION: self.extension_source_check.isChecked(),
            SOURCE_DEVICE_MANAGEMENT: self.device_source_check.isChecked(),
        }
        result = []
        for item in self.items:
            item_sources = item.sources or [item.source]
            if any(include_sources.get(source, False) for source in item_sources):
                result.append(item)
        return result

    def _preview_values(self, item: OmniPeekDeviceItem, config: OmniPeekExportConfig) -> list[str]:
        export_kinds = self._export_kinds_for_item(item, config)
        groups = [f"{config.line_name}{ENTRY_KIND_GROUP_SUFFIX[kind]}" for kind in export_kinds]
        colors = [self.colors[kind] for kind in export_kinds]
        return [
            "轨旁AP" if item.role == "trackside_ap" else "车载MR",
            item.name,
            item.location,
            item.normalized_physical_mac,
            item.r1_mac,
            item.r2_mac,
            item.r1_source,
            item.r2_source,
            " / ".join(ENTRY_KIND_LABELS[kind].replace("轨旁AP", "").replace("车载MR", "").strip() for kind in export_kinds),
            " / ".join(groups),
            ", ".join(colors),
            " / ".join(item.sources or [item.source]),
            item.status,
        ]

    def _export_kinds_for_item(self, item: OmniPeekDeviceItem, config: OmniPeekExportConfig) -> list[OmniPeekEntryKind]:
        if item.role == "trackside_ap":
            candidates = (
                ("trackside_physical", config.export_trackside_physical and bool(item.normalized_physical_mac)),
                ("trackside_r1", config.export_trackside_r1 and bool(item.r1_mac)),
                ("trackside_r2", config.export_trackside_r2 and bool(item.r2_mac)),
            )
        else:
            mode = config.onboard_radio_mode
            r1_enabled = mode in {"auto", "r1_only", "r1_r2"}
            r2_enabled = mode in {"auto", "r2_only", "r1_r2"}
            candidates = (
                ("onboard_physical", config.export_onboard_physical and bool(item.normalized_physical_mac)),
                ("onboard_r1", config.export_onboard_r1 and r1_enabled and bool(item.r1_mac)),
                ("onboard_r2", config.export_onboard_r2 and r2_enabled and bool(item.r2_mac)),
            )
        return [kind for kind, enabled in candidates if enabled]  # type: ignore[list-item]

    def _handle_preview_item_changed(self, table_item: QTableWidgetItem) -> None:
        if self._updating_preview or table_item.column() != 0:
            return
        key = str(table_item.data(Qt.UserRole) or "")
        checked = is_checked_value(table_item.checkState())
        for item in self.items:
            if item.key == key:
                item.selected = checked
                if checked and item.status == "MAC冲突":
                    item.force_export = True
                break
        for item in self.preview_items:
            if item.key == key:
                item.selected = checked
                if checked and item.status == "MAC冲突":
                    item.force_export = True
                break
        self._refresh_preview_filter_labels()
        self._update_preview_summary()

    def _update_preview_summary(self) -> None:
        all_sources_enabled = self.ac_source_check.isChecked() and self.extension_source_check.isChecked() and self.device_source_check.isChecked()
        use_full_stats = all_sources_enabled and "total" in self.preview_stats
        total_count = int(self.preview_stats.get("total") or len(self.preview_items)) if use_full_stats else len(self.preview_items)
        if use_full_stats:
            selection_delta = sum(
                int(bool(item.selected)) - int(self._initial_item_selection.get(item.key, bool(item.selected)))
                for item in self.items
            )
            selected_count = max(0, int(self.preview_stats.get("selected") or 0) + selection_delta)
            abnormal_count = int(self.preview_stats.get("abnormal") or 0)
        else:
            selected_count = sum(1 for item in self.preview_items if item.selected)
            abnormal_count = sum(1 for item in self.preview_items if self._is_abnormal_item(item))
        exportable_count = selected_count
        text = f"共 {total_count} 条｜已选 {selected_count} 条｜异常 {abnormal_count} 条｜可导出 {exportable_count} 条"
        if len(self.items) < total_count:
            text += f"｜预览 {len(self.items)} 条"
        if len(self.visible_preview_items) != len(self.preview_items):
            text += f"｜当前显示 {len(self.visible_preview_items)} 条"
        self.preview_summary_label.setText(text)

    def _refresh_preview_filter_labels(self) -> None:
        all_sources_enabled = self.ac_source_check.isChecked() and self.extension_source_check.isChecked() and self.device_source_check.isChecked()
        use_full_stats = all_sources_enabled and "total" in self.preview_stats
        counts = {
            "all": int(self.preview_stats.get("total") or len(self.preview_items)) if use_full_stats else len(self.preview_items),
            "selected": sum(1 for item in self.preview_items if item.selected),
            "abnormal": int(self.preview_stats.get("abnormal") or 0) if use_full_stats else sum(1 for item in self.preview_items if self._is_abnormal_item(item)),
            "mac_conflict": int(self.preview_stats.get("mac_conflict") or 0) if use_full_stats else sum(1 for item in self.preview_items if item.status == "MAC冲突"),
            "r2_failed": int(self.preview_stats.get("r2_failed") or 0) if use_full_stats else sum(1 for item in self.preview_items if item.status == "R2推导失败"),
            "missing_mac": int(self.preview_stats.get("missing_mac") or 0) if use_full_stats else sum(1 for item in self.preview_items if item.status == "缺少物理MAC"),
        }
        for key, button in self.preview_filter_buttons.items():
            button.setText(f"{PREVIEW_FILTER_LABELS[key]} {counts.get(key, 0)}")

    def _set_preview_filter(self, filter_key: str) -> None:
        self.preview_filter = filter_key if filter_key in PREVIEW_FILTER_LABELS else "all"
        self._apply_preview_filter()

    def _apply_preview_filter(self, *_args: object) -> None:
        self._populate_preview_table(self._visible_items())

    def _visible_items(self) -> list[OmniPeekDeviceItem]:
        search = self.preview_search_input.text().strip().casefold()
        return [item for item in self.preview_items if self._matches_preview_filter(item) and self._matches_preview_search(item, search)]

    def _matches_preview_filter(self, item: OmniPeekDeviceItem) -> bool:
        if self.preview_filter == "selected":
            return item.selected
        if self.preview_filter == "abnormal":
            return self._is_abnormal_item(item)
        if self.preview_filter == "mac_conflict":
            return item.status == "MAC冲突"
        if self.preview_filter == "r2_failed":
            return item.status == "R2推导失败"
        if self.preview_filter == "missing_mac":
            return item.status == "缺少物理MAC"
        return True

    @staticmethod
    def _is_abnormal_item(item: OmniPeekDeviceItem) -> bool:
        return item.status != "正常"

    @staticmethod
    def _matches_preview_search(item: OmniPeekDeviceItem, search: str) -> bool:
        if not search:
            return True
        fields = (
            item.name,
            item.location,
            item.physical_mac,
            item.normalized_physical_mac,
            item.r1_mac,
            item.r2_mac,
            " / ".join(item.sources or [item.source]),
            item.status,
        )
        return any(search in str(value or "").casefold() for value in fields)

    def _apply_preview_table_layout(self) -> None:
        auto_fit_table_columns(
            self.preview_table,
            max_rows=100,
            min_widths=PREVIEW_COLUMN_MIN_WIDTHS,
            max_widths=PREVIEW_COLUMN_MAX_WIDTHS,
            padding=28,
        )
        header = self.preview_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(60)
        for column in range(self.preview_table.columnCount()):
            mode = QHeaderView.Fixed if column in PREVIEW_FIXED_COLUMNS else QHeaderView.Interactive
            header.setSectionResizeMode(column, mode)
            if column in PREVIEW_FIXED_COLUMNS:
                self.preview_table.setColumnWidth(column, PREVIEW_COLUMN_MIN_WIDTHS[column])
        self.preview_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.preview_table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

    def _config(self) -> OmniPeekExportConfig:
        filename = self.file_name_input.text().strip() or make_omnipeek_filename(self.line_name_input.text())
        if not filename.lower().endswith(".nam"):
            filename += ".nam"
        output_path = Path(self.output_dir_input.text().strip() or str(default_export_dir())) / filename
        return OmniPeekExportConfig(
            line_name=self.line_name_input.text().strip() or "线路",
            output_path=output_path,
            include_ac_fit_ap=self.ac_source_check.isChecked(),
            include_ap_extensions=self.extension_source_check.isChecked(),
            include_device_mr=self.device_source_check.isChecked(),
            export_trackside_physical=self.trackside_physical_check.isChecked(),
            export_trackside_r1=self.trackside_r1_check.isChecked(),
            export_trackside_r2=self.trackside_r2_check.isChecked(),
            export_onboard_physical=self.onboard_physical_check.isChecked(),
            export_onboard_r1=self.onboard_r1_check.isChecked(),
            export_onboard_r2=self.onboard_r2_check.isChecked(),
            onboard_radio_mode=str(self.radio_mode_combo.currentData() or "auto"),
            enable_h3c_derivation=self.h3c_derivation_check.isChecked(),
            colors=dict(self.colors),
        )

    def export(self) -> None:
        self._sync_item_selection_from_table()
        config = self._config()
        if not self.preview_items:
            MessageBox.warning(self, "导出 OmniPeek 名称表", "当前没有可预览的数据。")
            return
        save_omnipeek_color_settings(self.settings, self.colors)
        save_omnipeek_last_export_dir(self.settings, config.output_path.parent)
        remember_export_path(config.output_path)
        self.export_button.setEnabled(False)
        self.close_button.setEnabled(False)
        self.progress.setVisible(True)
        try:
            submit_export_task(
                self,
                omnipeek_name_table_spec(
                    config.output_path,
                    db_path=str(self.source.get("db_path") or ""),
                    site_name=str(self.source.get("site_name") or ""),
                    source={
                        **self.source,
                        "ac_uuid": str(self.source.get("ac_uuid") or ""),
                    },
                    config={**asdict(config), "output_path": str(config.output_path)},
                    selected_item_keys=[item.key for item in self.items if item.selected],
                    excluded_item_keys=[item.key for item in self.items if not item.selected],
                    force_export_keys=[item.key for item in self.items if item.force_export],
                    title="导出 OmniPeek 名称表",
                    open_dir_on_success=True,
                ),
                success_title="导出 OmniPeek 名称表",
                paths=self.settings.paths,
            )
        finally:
            self.progress.setVisible(False)
            self.export_button.setEnabled(True)
            self.close_button.setEnabled(True)

    def _sync_item_selection_from_table(self) -> None:
        states: dict[str, bool] = {}
        for row in range(self.preview_table.rowCount()):
            item = self.preview_table.item(row, 0)
            if item is None:
                continue
            states[str(item.data(Qt.UserRole) or "")] = is_checked_value(item.checkState())
        for item in self.items:
            if item.key in states:
                item.selected = states[item.key]
