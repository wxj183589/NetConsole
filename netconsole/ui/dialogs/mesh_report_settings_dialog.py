from __future__ import annotations

import os

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from netconsole.core.i18n import I18n
from netconsole.services.mesh_analysis_report import MeshReportOptions
from netconsole.services.mesh_quality_analysis import load_default_rules


class MeshReportSettingsDialog(QDialog):
    def __init__(self, i18n: I18n, default_name: str, parent=None) -> None:
        super().__init__(parent)
        self.i18n = i18n
        self.setWindowTitle("MR原始MESH日志分析报告设置")
        rules = load_default_rules()

        self.report_name_edit = QLineEdit(default_name)
        self.start_time_edit = QLineEdit()
        self.end_time_edit = QLineEdit()
        self.radio_edit = QLineEdit()

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
        basic_form.addRow("开始时间", self.start_time_edit)
        basic_form.addRow("结束时间", self.end_time_edit)
        basic_form.addRow("Radio", self.radio_edit)
        basic_form.addRow("导出格式", QLabel("Excel (.xlsx)"))

        options = QVBoxLayout()
        for checkbox in (self.include_raw_evidence, self.include_all_link_details, self.open_output_dir_after_done, self.include_parse_issues, self.include_busy_analysis):
            options.addWidget(checkbox)
        full_detail_hint = QLabel("全量链路明细可能显著增加报告生成时间和文件大小，大数据场景建议关闭。")
        full_detail_hint.setWordWrap(True)
        options.addWidget(full_detail_hint)

        advanced_box = QGroupBox("高级阈值")
        advanced_box.setCheckable(True)
        advanced_box.setChecked(False)
        advanced_form = QFormLayout(advanced_box)
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

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("生成报告")
        buttons.button(QDialogButtonBox.Cancel).setText(self.i18n.t("mesh_analysis.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(basic_form)
        layout.addLayout(options)
        layout.addWidget(mode_hint)
        layout.addWidget(advanced_box)
        layout.addWidget(performance_box)
        hint = QLabel("时间格式建议使用 yyyy-MM-dd HH:mm:ss；留空表示不限制。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(buttons)
        layout.addLayout(button_row)

    @staticmethod
    def _spin(minimum: int, maximum: int, value: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        return spin

    def options(self) -> MeshReportOptions:
        radio_text = self.radio_edit.text().strip()
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
        )
