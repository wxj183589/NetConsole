from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from netconsole.core.feature_flags import FeatureGate, default_profile, load_profile, project_root, save_profile
from netconsole.core.feature_registry import list_features
from netconsole.core.i18n import I18n


VISIBLE_COLUMN = 4
ENABLED_COLUMN = 5
CUSTOMER_COLUMN = 6


class FeatureFlagsPage(QWidget):
    def __init__(self, i18n: I18n, feature_gate: FeatureGate) -> None:
        super().__init__()
        self.i18n = i18n
        self.feature_gate = feature_gate
        self.session_label = QLabel("当前为临时完整模式，本次启动有效。")
        self.session_label.setObjectName("featureGateSessionOverrideLabel")
        self.table = QTableWidget(0, 9)
        self.save_button = QPushButton()
        self.reload_button = QPushButton()
        self.preview_button = QPushButton()

        actions = QHBoxLayout()
        actions.addWidget(self.save_button)
        actions.addWidget(self.reload_button)
        actions.addWidget(self.preview_button)
        actions.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(self.session_label)
        layout.addLayout(actions)
        layout.addWidget(self.table, 1)

        self.save_button.clicked.connect(self.save_customer_profile)
        self.reload_button.clicked.connect(self.reload_defaults)
        self.preview_button.clicked.connect(self.preview_customer_profile)
        self.retranslate()
        self.reload_from_gate()

    def reload_from_gate(self) -> None:
        self.session_label.setVisible(self.feature_gate.is_session_override_active())
        self._reload_table(self._saved_customer_features())

    def _reload_table(self, features: dict[str, dict[str, bool]]) -> None:
        items = list_features()
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(items))
            for row, item in enumerate(items):
                customer_state = features.get(item.feature_id, {})
                customer_included = bool(customer_state.get("visible")) or bool(customer_state.get("enabled"))
                values = (
                    item.feature_id,
                    self.i18n.t(item.title_key),
                    item.item_type,
                    item.parent_id or "",
                    bool(customer_state.get("visible")),
                    bool(customer_state.get("enabled")),
                    customer_included,
                    item.internal_only,
                    self.i18n.t(item.description_key) if item.description_key else "",
                )
                for column, value in enumerate(values):
                    cell = QTableWidgetItem("" if isinstance(value, bool) else str(value))
                    cell.setTextAlignment(Qt.AlignCenter)
                    if column in {VISIBLE_COLUMN, ENABLED_COLUMN, CUSTOMER_COLUMN, 7}:
                        cell.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
                        cell.setCheckState(Qt.Checked if bool(value) else Qt.Unchecked)
                        if column == 7:
                            cell.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                    else:
                        cell.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                    self.table.setItem(row, column, cell)
            self.table.resizeColumnsToContents()
        finally:
            self.table.blockSignals(False)

    def reload_defaults(self) -> None:
        self._reload_table(default_profile("customer")["features"])

    def save_customer_profile(self) -> None:
        features = self._customer_features()
        save_profile(project_root() / "profiles" / "features" / "customer.json", "customer", features)
        QMessageBox.information(self, self.i18n.t("feature_flags.title"), self.i18n.t("feature_flags.profile_saved"))

    def preview_customer_profile(self) -> None:
        payload = default_profile("customer")
        payload["features"] = self._customer_features()
        QMessageBox.information(
            self,
            self.i18n.t("feature_flags.preview_customer"),
            json.dumps(payload, ensure_ascii=False, indent=2),
        )

    def retranslate(self) -> None:
        self.session_label.setText("当前为临时完整模式，本次启动有效。")
        self.save_button.setText(self.i18n.t("feature_flags.save_profile"))
        self.reload_button.setText(self.i18n.t("feature_flags.reload_defaults"))
        self.preview_button.setText(self.i18n.t("feature_flags.preview_customer"))
        self.table.setHorizontalHeaderLabels(
            [
                self.i18n.t("feature_flags.feature_id"),
                self.i18n.t("feature_flags.feature_name"),
                self.i18n.t("feature_flags.type"),
                self.i18n.t("feature_flags.parent"),
                self.i18n.t("feature_flags.visible"),
                self.i18n.t("feature_flags.enabled"),
                self.i18n.t("feature_flags.customer_package"),
                self.i18n.t("feature_flags.internal_only"),
                self.i18n.t("feature_flags.description"),
            ]
        )

    def _customer_features(self) -> dict[str, dict[str, bool]]:
        features: dict[str, dict[str, bool]] = {}
        for row, item in enumerate(list_features()):
            include_item = self.table.item(row, CUSTOMER_COLUMN)
            visible_item = self.table.item(row, VISIBLE_COLUMN)
            enabled_item = self.table.item(row, ENABLED_COLUMN)
            included = include_item is not None and include_item.checkState() == Qt.Checked
            visible = included and visible_item is not None and visible_item.checkState() == Qt.Checked
            enabled = included and enabled_item is not None and enabled_item.checkState() == Qt.Checked
            if item.internal_only:
                visible = False
                enabled = False
            features[item.feature_id] = {"visible": visible, "enabled": enabled}
        return features

    def _saved_customer_features(self) -> dict[str, dict[str, bool]]:
        return load_profile(project_root() / "profiles" / "features" / "customer.json", "customer")
