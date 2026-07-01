from __future__ import annotations

import os

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QApplication,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from netconsole.core.i18n import I18n
from netconsole.services.mesh_analysis_report import MeshReportOptions
from netconsole.services.mesh_quality_analysis import get_threshold_template, load_threshold_templates


class MeshReportSettingsDialog(QDialog):
    def __init__(self, i18n: I18n, default_name: str, parent=None) -> None:
        super().__init__(parent)
        self.i18n = i18n
        self.setWindowTitle("MR原始MESH日志分析报告设置")
        self.setMinimumWidth(520)
        self.threshold_templates = load_threshold_templates()
        default_template = get_threshold_template("pis_wifi6_40_80_standard")
        rules = default_template.rules

        self.report_name_edit = QLineEdit(default_name)
        self.start_time_edit = QLineEdit()
        self.end_time_edit = QLineEdit()
        self.radio_edit = QLineEdit()
        self.excluded_region_keywords_edit = QLineEdit("车辆段, 停车场, CLD, TCC")
        self.threshold_template_combo = QComboBox()
        for key, template in self.threshold_templates.items():
            self.threshold_template_combo.addItem(template.label, key)
        self.threshold_template_combo.setCurrentIndex(0)

        self.business_type_combo = self._combo(["PIS", "DCS/信号", "自定义"])
        self.working_mode_combo = self._combo(["Wi-Fi6 / 11ax", "Wi-Fi5 / 11ac", "强制 dot11a", "802.11a", "未知"])
        self.bandwidth_combo = self._combo(["20M", "40M", "80M", "40M / 80M 混合", "未知"])
        self.ap_spacing_combo = self._combo(["80~120m", "80~150m", "100~150m", "150~180m 或更远", "未知"])
        self.template_description = QLabel(default_template.description)
        self.template_description.setWordWrap(True)

        self.rssi_excellent_spin = self._spin(0, 100, rules.rssi_excellent_threshold)
        self.rssi_good_spin = self._spin(0, 100, rules.rssi_good_threshold)
        self.rssi_warning_spin = self._spin(0, 100, rules.rssi_warning_threshold)
        self.rssi_bad_spin = self._spin(0, 100, rules.rssi_bad_threshold)
        self.backup_available_spin = self._spin(0, 100, rules.backup_available_threshold)
        self.backup_strong_spin = self._spin(0, 100, rules.backup_strong_threshold)
        self.busy_warning_spin = self._spin(0, 100, rules.busy_warning_threshold)
        self.busy_bad_spin = self._spin(0, 100, rules.busy_bad_threshold)
        self.no_backup_spin = self._spin(0, 3600, rules.no_backup_min_seconds)
        self.weak_active_spin = self._spin(0, 3600, rules.weak_active_min_seconds)
        self.switch_late_spin = self._spin(1, 3600, rules.switch_late_window_seconds)
        self.switch_target_spin = self._spin(1, 3600, rules.switch_target_window_seconds)
        self.flap_window_spin = self._spin(1, 3600, rules.flap_window_seconds)
        self.short_segment_spin = self._spin(1, 3600, rules.short_active_segment_seconds)

        self.include_raw_evidence = QCheckBox("包含原始证据片段")
        self.include_all_link_details = QCheckBox("导出全量链路明细")
        self.include_parse_issues = QCheckBox("包含解析问题")
        self.include_busy_analysis = QCheckBox("包含空口繁忙度分析")
        self.open_output_dir_after_done = QCheckBox("生成完成后打开输出目录")
        self.open_output_dir_after_done.setChecked(True)
        for checkbox in (self.include_raw_evidence, self.include_parse_issues, self.include_busy_analysis):
            checkbox.setChecked(True)

        self.use_multi_core = QCheckBox("使用多核处理")
        self.use_multi_core.setChecked(True)
        self.worker_processes_spin = self._spin(0, min(os.cpu_count() or 1, 16), 0)
        self.stream_large_excel = QCheckBox("大数据导出模式")
        self.stream_large_excel.setChecked(True)
        self.autofit_scan_limit_spin = self._spin(500, 5000, 2000)

        basic_form = QFormLayout()
        basic_form.addRow("报告名称", self.report_name_edit)
        basic_form.addRow("评估模板", self.threshold_template_combo)
        basic_form.addRow("开始时间", self.start_time_edit)
        basic_form.addRow("结束时间", self.end_time_edit)
        basic_form.addRow("Radio", self.radio_edit)
        basic_form.addRow("统计/评分排除区域关键词", self.excluded_region_keywords_edit)
        basic_form.addRow("导出格式", QLabel("Excel (.xlsx)"))

        options = QVBoxLayout()
        for checkbox in (
            self.include_raw_evidence,
            self.include_all_link_details,
            self.open_output_dir_after_done,
            self.include_parse_issues,
            self.include_busy_analysis,
        ):
            options.addWidget(checkbox)
        full_detail_hint = QLabel("全量链路明细可能显著增加报告生成时间和文件大小，大数据场景建议关闭。")
        full_detail_hint.setWordWrap(True)
        options.addWidget(full_detail_hint)

        advanced_box = QGroupBox("高级阈值")
        advanced_box.setCheckable(True)
        advanced_box.setChecked(False)
        advanced_form = QFormLayout(advanced_box)
        advanced_form.addRow("业务类型", self.business_type_combo)
        advanced_form.addRow("实际工作模式", self.working_mode_combo)
        advanced_form.addRow("频宽", self.bandwidth_combo)
        advanced_form.addRow("典型 AP 间隔", self.ap_spacing_combo)
        advanced_form.addRow("模板说明", self.template_description)
        advanced_form.addRow("RSSI 优秀阈值", self.rssi_excellent_spin)
        advanced_form.addRow("RSSI 良好阈值", self.rssi_good_spin)
        advanced_form.addRow("RSSI 关注阈值", self.rssi_warning_spin)
        advanced_form.addRow("RSSI 差阈值", self.rssi_bad_spin)
        advanced_form.addRow("可用备份 RSSI 阈值", self.backup_available_spin)
        advanced_form.addRow("强备份 RSSI 阈值", self.backup_strong_spin)
        advanced_form.addRow("Busy 关注阈值", self.busy_warning_spin)
        advanced_form.addRow("Busy 严重阈值", self.busy_bad_spin)
        advanced_form.addRow("无备份最小持续秒数", self.no_backup_spin)
        advanced_form.addRow("弱主链路最小持续秒数", self.weak_active_spin)
        advanced_form.addRow("切换滞后窗口秒数", self.switch_late_spin)
        advanced_form.addRow("切入质量判断窗口秒数", self.switch_target_spin)
        advanced_form.addRow("乒乓切换窗口秒数", self.flap_window_spin)
        advanced_form.addRow("短时 Active 区段秒数", self.short_segment_spin)

        performance_box = QGroupBox("性能设置")
        performance_box.setCheckable(True)
        performance_box.setChecked(False)
        performance_form = QFormLayout(performance_box)
        performance_form.addRow(self.use_multi_core)
        performance_form.addRow("工作进程数（0=自动）", self.worker_processes_spin)
        performance_form.addRow(self.stream_large_excel)
        performance_form.addRow("列宽扫描行数", self.autofit_scan_limit_spin)
        performance_hint = QLabel("自动模式会保留 2 个 CPU 核心，最多使用 8 个进程；Excel 写入始终在独立子进程内完成。")
        performance_hint.setWordWrap(True)
        performance_form.addRow(performance_hint)

        mode_hint = QLabel("当前会按每个 meshlog/source_file 单独生成分析报告，避免多个日志混在一起影响问题定位。")
        mode_hint.setWordWrap(True)
        scenario_hint = QLabel("设备代际不等于评估模板；如果实际工作在 dot11a / 20M，应按 DCS / 802.11a / 20M 场景评估。")
        scenario_hint.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("生成报告")
        buttons.button(QDialogButtonBox.Cancel).setText(self.i18n.t("mesh_analysis.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.threshold_template_combo.currentIndexChanged.connect(self._apply_threshold_template)
        self._apply_threshold_template()

        content = QWidget(self)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addLayout(basic_form)
        content_layout.addLayout(options)
        content_layout.addWidget(mode_hint)
        content_layout.addWidget(scenario_hint)
        content_layout.addWidget(advanced_box)
        content_layout.addWidget(performance_box)
        hint = QLabel("时间格式建议使用 yyyy-MM-dd HH:mm:ss；留空表示不限制。")
        hint.setWordWrap(True)
        content_layout.addWidget(hint)

        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.NoFrame)
        scroll_area.setWidget(content)

        layout = QVBoxLayout(self)
        layout.addWidget(scroll_area, 1)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(buttons)
        layout.addLayout(button_row)
        self._resize_to_available_screen()

    def _resize_to_available_screen(self) -> None:
        screen = self.screen() or QApplication.primaryScreen()
        available_height = screen.availableGeometry().height() if screen is not None else 760
        height = max(520, min(720, int(available_height * 0.82)))
        self.resize(560, height)

    @staticmethod
    def _combo(values: list[str]) -> QComboBox:
        combo = QComboBox()
        combo.addItems(values)
        return combo

    @staticmethod
    def _set_combo_text(combo: QComboBox, text: str) -> None:
        index = combo.findText(text)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _apply_threshold_template(self) -> None:
        key = str(self.threshold_template_combo.currentData() or "custom")
        template = self.threshold_templates.get(key)
        if template is None:
            return
        rules = template.rules
        self._set_combo_text(self.business_type_combo, template.business_type)
        self._set_combo_text(self.working_mode_combo, template.working_mode)
        self._set_combo_text(self.bandwidth_combo, template.bandwidth)
        self._set_combo_text(self.ap_spacing_combo, template.ap_spacing)
        self.template_description.setText(template.description)
        self.rssi_excellent_spin.setValue(rules.rssi_excellent_threshold)
        self.rssi_good_spin.setValue(rules.rssi_good_threshold)
        self.rssi_warning_spin.setValue(rules.rssi_warning_threshold)
        self.rssi_bad_spin.setValue(rules.rssi_bad_threshold)
        self.backup_available_spin.setValue(rules.backup_available_threshold)
        self.backup_strong_spin.setValue(rules.backup_strong_threshold)
        self.busy_warning_spin.setValue(rules.busy_warning_threshold)
        self.busy_bad_spin.setValue(rules.busy_bad_threshold)
        self.no_backup_spin.setValue(rules.no_backup_min_seconds)
        self.weak_active_spin.setValue(rules.weak_active_min_seconds)
        self.switch_late_spin.setValue(rules.switch_late_window_seconds)
        self.switch_target_spin.setValue(rules.switch_target_window_seconds)
        self.flap_window_spin.setValue(rules.flap_window_seconds)
        self.short_segment_spin.setValue(rules.short_active_segment_seconds)

    @staticmethod
    def _spin(minimum: int, maximum: int, value: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        return spin

    def options(self) -> MeshReportOptions:
        radio_text = self.radio_edit.text().strip()
        template_key = str(self.threshold_template_combo.currentData() or "custom")
        template = self.threshold_templates.get(template_key) or get_threshold_template("custom")
        return MeshReportOptions(
            report_name=self.report_name_edit.text().strip(),
            start_time=self.start_time_edit.text().strip() or None,
            end_time=self.end_time_edit.text().strip() or None,
            radio_filter=int(radio_text) if radio_text.isdigit() else None,
            rssi_excellent_threshold=self.rssi_excellent_spin.value(),
            rssi_good_threshold=self.rssi_good_spin.value(),
            rssi_warning_threshold=self.rssi_warning_spin.value(),
            rssi_bad_threshold=self.rssi_bad_spin.value(),
            backup_available_threshold=self.backup_available_spin.value(),
            backup_strong_threshold=self.backup_strong_spin.value(),
            busy_warning_threshold=self.busy_warning_spin.value(),
            busy_bad_threshold=self.busy_bad_spin.value(),
            no_backup_min_seconds=self.no_backup_spin.value(),
            weak_active_min_seconds=self.weak_active_spin.value(),
            switch_late_window_seconds=self.switch_late_spin.value(),
            switch_target_window_seconds=self.switch_target_spin.value(),
            flap_window_seconds=self.flap_window_spin.value(),
            short_active_segment_seconds=self.short_segment_spin.value(),
            include_raw_evidence=self.include_raw_evidence.isChecked(),
            include_all_link_details=self.include_all_link_details.isChecked(),
            include_raw_events=False,
            include_parse_issues=self.include_parse_issues.isChecked(),
            include_peer_lifecycle=False,
            include_link_establishment=False,
            include_flap_analysis=True,
            include_busy_analysis=self.include_busy_analysis.isChecked(),
            use_multi_core=self.use_multi_core.isChecked(),
            worker_processes=self.worker_processes_spin.value(),
            stream_large_excel=self.stream_large_excel.isChecked(),
            autofit_scan_limit=self.autofit_scan_limit_spin.value(),
            open_output_dir_after_done=self.open_output_dir_after_done.isChecked(),
            separate_reports_by_source_file=True,
            export_format="excel",
            excluded_region_keywords=tuple(
                keyword.strip()
                for keyword in self.excluded_region_keywords_edit.text().replace("；", ",").replace(";", ",").split(",")
                if keyword.strip()
            ),
            threshold_template_key=template_key,
            business_type=self.business_type_combo.currentText(),
            working_mode=self.working_mode_combo.currentText(),
            bandwidth=self.bandwidth_combo.currentText(),
            ap_spacing=self.ap_spacing_combo.currentText(),
            threshold_template_description=template.description,
        )
