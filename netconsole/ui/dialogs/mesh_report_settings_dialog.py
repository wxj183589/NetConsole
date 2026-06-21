from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from netconsole.core.i18n import I18n
from netconsole.services.mesh_analysis_report import MeshReportOptions


class MeshReportSettingsDialog(QDialog):
    def __init__(self, i18n: I18n, default_name: str, parent=None) -> None:
        super().__init__(parent)
        self.i18n = i18n
        self.setWindowTitle(self.i18n.t("mesh_report.settings_title"))
        self.report_name_edit = QLineEdit(default_name)
        self.start_time_edit = QLineEdit()
        self.end_time_edit = QLineEdit()
        self.radio_edit = QLineEdit()
        self.flap_window_spin = QSpinBox()
        self.flap_window_spin.setRange(1, 3600)
        self.flap_window_spin.setValue(5)
        self.include_raw_events = QCheckBox(self.i18n.t("mesh_report.include_raw_events"))
        self.include_parse_issues = QCheckBox(self.i18n.t("mesh_report.include_parse_issues"))
        self.include_peer_lifecycle = QCheckBox(self.i18n.t("mesh_report.include_peer_lifecycle"))
        self.include_link_establishment = QCheckBox(self.i18n.t("mesh_report.include_link_establishment"))
        self.include_flap_analysis = QCheckBox(self.i18n.t("mesh_report.include_flap_analysis"))
        for checkbox in (
            self.include_raw_events,
            self.include_parse_issues,
            self.include_peer_lifecycle,
            self.include_link_establishment,
            self.include_flap_analysis,
        ):
            checkbox.setChecked(True)

        form = QFormLayout()
        form.addRow(self.i18n.t("mesh_report.report_name"), self.report_name_edit)
        form.addRow(self.i18n.t("mesh_report.start_time"), self.start_time_edit)
        form.addRow(self.i18n.t("mesh_report.end_time"), self.end_time_edit)
        form.addRow("Radio", self.radio_edit)
        form.addRow(self.i18n.t("mesh_report.flap_window_seconds"), self.flap_window_spin)
        form.addRow(self.i18n.t("mesh_report.export_format"), QLabel("Excel (.xlsx)"))

        options = QVBoxLayout()
        for checkbox in (
            self.include_raw_events,
            self.include_parse_issues,
            self.include_peer_lifecycle,
            self.include_link_establishment,
            self.include_flap_analysis,
        ):
            options.addWidget(checkbox)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(self.i18n.t("mesh_report.export_excel"))
        buttons.button(QDialogButtonBox.Cancel).setText(self.i18n.t("mesh_analysis.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(options)
        hint = QLabel(self.i18n.t("mesh_report.time_range_hint"))
        hint.setWordWrap(True)
        layout.addWidget(hint)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(buttons)
        layout.addLayout(button_row)

    def options(self) -> MeshReportOptions:
        radio_text = self.radio_edit.text().strip()
        return MeshReportOptions(
            report_name=self.report_name_edit.text().strip(),
            start_time=self.start_time_edit.text().strip() or None,
            end_time=self.end_time_edit.text().strip() or None,
            radio_filter=int(radio_text) if radio_text.isdigit() else None,
            include_raw_events=self.include_raw_events.isChecked(),
            include_parse_issues=self.include_parse_issues.isChecked(),
            include_peer_lifecycle=self.include_peer_lifecycle.isChecked(),
            include_link_establishment=self.include_link_establishment.isChecked(),
            include_flap_analysis=self.include_flap_analysis.isChecked(),
            flap_window_seconds=self.flap_window_spin.value(),
            export_format="excel",
        )
