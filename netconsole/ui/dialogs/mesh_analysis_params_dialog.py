from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from netconsole.models.mesh_analysis_params import (
    SERVICE_TYPE_CHOICES,
    WIFI_TYPE_CHOICES,
    MeshAnalysisParams,
    normalize_mesh_analysis_params,
)
from netconsole.ui.widgets.no_wheel import NoWheelSpinBox


class MeshAnalysisParamsEditor(QWidget):
    def __init__(self, params: MeshAnalysisParams | None = None, parent=None) -> None:
        super().__init__(parent)
        params = params or MeshAnalysisParams()
        self.switch_time_spin = self._spin(100, 60000, params.main_link_switch_time_ms)
        self.tolerance_spin = self._spin(0, 60000, params.short_link_tolerance_ms)
        self.merge_dual_radio_check = QCheckBox("开启")
        self.merge_dual_radio_check.setChecked(params.merge_same_physical_ap_dual_radio)
        self.include_boundary_check = QCheckBox("开启")
        self.include_boundary_check.setChecked(params.include_log_boundary_segments)
        self.sample_interval_spin = self._spin(0, 60000, params.sample_interval_ms or 0)
        self.sample_interval_spin.setSpecialValueText("自动识别")
        self.service_type_combo = QComboBox()
        self.service_type_combo.addItems(SERVICE_TYPE_CHOICES)
        self.wifi_type_combo = QComboBox()
        self.wifi_type_combo.addItems(WIFI_TYPE_CHOICES)
        self._set_combo_text(self.service_type_combo, params.service_type)
        self._set_combo_text(self.wifi_type_combo, params.wifi_type)

        layout = QFormLayout(self)
        layout.addRow("主链路切换时间(ms)", self.switch_time_spin)
        layout.addRow("短时判定容差(ms)", self.tolerance_spin)
        layout.addRow("是否合并同AP双射频口", self.merge_dual_radio_check)
        layout.addRow("是否将日志边界段纳入短时建链统计", self.include_boundary_check)
        layout.addRow("采样间隔(ms)", self.sample_interval_spin)
        layout.addRow("业务类型", self.service_type_combo)
        layout.addRow("WiFi类型", self.wifi_type_combo)

    def params(self) -> MeshAnalysisParams:
        return normalize_mesh_analysis_params(
            {
                "main_link_switch_time_ms": self.switch_time_spin.value(),
                "short_link_tolerance_ms": self.tolerance_spin.value(),
                "merge_same_physical_ap_dual_radio": self.merge_dual_radio_check.isChecked(),
                "include_log_boundary_segments": self.include_boundary_check.isChecked(),
                "sample_interval_ms": self.sample_interval_spin.value() or None,
                "service_type": self.service_type_combo.currentText(),
                "wifi_type": self.wifi_type_combo.currentText(),
            }
        )

    @staticmethod
    def _spin(minimum: int, maximum: int, value: int) -> NoWheelSpinBox:
        spin = NoWheelSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        return spin

    @staticmethod
    def _set_combo_text(combo: QComboBox, text: str) -> None:
        index = combo.findText(text)
        if index >= 0:
            combo.setCurrentIndex(index)


class MeshAnalysisParamsDialog(QDialog):
    def __init__(self, site_name: str, params: MeshAnalysisParams, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("MR / MESH 分析参数")
        self.setMinimumWidth(520)
        self.editor = MeshAnalysisParamsEditor(params, self)
        self.temporary_only_check = QCheckBox("仅本次分析使用，不修改局点配置")
        self.temporary_only_check.setChecked(True)
        hint = QLabel(
            "参数优先级：本次临时覆盖 > 导入时快照 > 当前局点配置 > 全局默认值。"
        )
        hint.setWordWrap(True)
        site_label = QLabel(f"当前局点：{site_name}")
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("应用")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(site_label)
        layout.addWidget(self.editor)
        layout.addWidget(self.temporary_only_check)
        layout.addWidget(hint)
        layout.addWidget(buttons)

    def params(self) -> MeshAnalysisParams:
        return self.editor.params()

    def temporary_only(self) -> bool:
        return self.temporary_only_check.isChecked()
