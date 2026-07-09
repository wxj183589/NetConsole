from __future__ import annotations

from netconsole.ui.dialogs.message_service import MessageBox
import json
import traceback

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from netconsole.core import app_logger
from netconsole.core.feature_flags import FeatureGate, default_profile, load_profile, normalize_feature_state, project_root, save_profile, validate_feature_states
from netconsole.core.feature_registry import list_features
from netconsole.core.i18n import I18n
from netconsole.ui.shell.fluent_bridge import InfoBar, InfoBarPosition
from netconsole.ui.widgets.table_check_delegate import create_checkable_table_item, install_checkbox_only_delegate


VISIBLE_COLUMN = 4
ENABLED_COLUMN = 5
CUSTOMER_COLUMN = 6
INTERNAL_COLUMN = 7
CHECK_COLUMNS = {VISIBLE_COLUMN, ENABLED_COLUMN, CUSTOMER_COLUMN, INTERNAL_COLUMN}


class FeatureFlagsPage(QWidget):
    def __init__(self, i18n: I18n, feature_gate: FeatureGate, on_profile_saved=None) -> None:
        super().__init__()
        self.i18n = i18n
        self.feature_gate = feature_gate
        self.on_profile_saved = on_profile_saved
        self._updating_table = False
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
        self.table.itemChanged.connect(self._on_item_changed)
        self._configure_table()
        self.retranslate()
        self.reload_from_gate()

    def reload_from_gate(self) -> None:
        self.session_label.setVisible(self.feature_gate.is_session_override_active() or self.feature_gate.is_customer_preview_active())
        if self.feature_gate.is_customer_preview_active():
            self.session_label.setText("当前为客户版预览。")
            self.preview_button.setText("退出客户版预览")
        else:
            self.session_label.setText("当前为临时完整模式，本次启动有效。")
            self.preview_button.setText(self.i18n.t("feature_flags.preview_customer"))
        features = self.feature_gate.features if self.feature_gate.is_customer_preview_active() else self._saved_customer_features()
        self._reload_table(features)

    def _reload_table(self, features: dict[str, dict[str, bool]]) -> None:
        items = list_features()
        normalized_features = {
            item.feature_id: normalize_feature_state(item, features.get(item.feature_id))
            for item in items
        }
        self.table.blockSignals(True)
        self._updating_table = True
        try:
            self.table.setRowCount(len(items))
            for row, item in enumerate(items):
                state = normalized_features[item.feature_id]
                values = (
                    item.feature_id,
                    self.i18n.t(item.title_key),
                    item.item_type,
                    item.parent_id or "",
                    state["visible"],
                    state["enabled"],
                    state["client_package"],
                    state["internal_only"],
                    self.i18n.t(item.description_key) if item.description_key else "",
                )
                for column, value in enumerate(values):
                    if column in CHECK_COLUMNS:
                        enabled = not (column == CUSTOMER_COLUMN and bool(state["internal_only"]))
                        if column == INTERNAL_COLUMN and item.internal_only:
                            enabled = False
                        cell = create_checkable_table_item(bool(value), enabled=enabled)
                    else:
                        cell = QTableWidgetItem(str(value))
                        cell.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                        cell.setTextAlignment(Qt.AlignCenter)
                    self.table.setItem(row, column, cell)
            self.table.resizeColumnsToContents()
            for column, width in ((VISIBLE_COLUMN, 56), (ENABLED_COLUMN, 56), (CUSTOMER_COLUMN, 88), (INTERNAL_COLUMN, 88)):
                self.table.setColumnWidth(column, width)
        finally:
            self._updating_table = False
            self.table.blockSignals(False)

    def reload_defaults(self) -> None:
        answer = MessageBox.question(
            self,
            self.i18n.t("feature_flags.reload_defaults"),
            "确认恢复默认客户版功能配置？当前未保存修改会被覆盖。",
        )
        if answer != MessageBox.Yes:
            return
        self._reload_table(default_profile("customer")["features"])

    def save_customer_profile(self) -> None:
        features = self._customer_features()
        error = self._validate_customer_features(features) or validate_feature_states(features)
        if error:
            app_logger.log_warning("FEATURE_SWITCH_VALIDATION_ERROR", error)
            print(f"[FeatureSwitch] validation error: {error}")
            MessageBox.warning(self, self.i18n.t("feature_flags.title"), error)
            return
        try:
            save_profile(project_root() / "profiles" / "features" / "customer.json", "customer", features)
            self.feature_gate.reload()
            if callable(self.on_profile_saved):
                self.on_profile_saved()
            self._show_success(self.i18n.t("feature_flags.profile_saved"))
        except Exception as exc:
            detail = traceback.format_exc()
            app_logger.log_error("FEATURE_SWITCH_SAVE_FAILED", detail)
            self._show_error("保存失败", str(exc))

    def preview_customer_profile(self) -> None:
        if self.feature_gate.is_customer_preview_active():
            self.feature_gate.disable_session_customer_preview()
            if callable(self.on_profile_saved):
                self.on_profile_saved()
            self.reload_from_gate()
            self._show_success("已退出客户版预览")
            return
        payload = default_profile("customer")
        payload["features"] = self._customer_features()
        error = self._validate_customer_features(payload["features"]) or validate_feature_states(payload["features"])
        if error:
            MessageBox.warning(self, self.i18n.t("feature_flags.title"), error)
            return
        self.feature_gate.enable_session_customer_preview(payload["features"])
        if callable(self.on_profile_saved):
            self.on_profile_saved()
        self.reload_from_gate()
        self._show_success("当前为客户版预览")

    def retranslate(self) -> None:
        self.save_button.setText(self.i18n.t("feature_flags.save_profile"))
        self.reload_button.setText(self.i18n.t("feature_flags.reload_defaults"))
        self.preview_button.setText("退出客户版预览" if self.feature_gate.is_customer_preview_active() else self.i18n.t("feature_flags.preview_customer"))
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
            raw_state = {
                "visible": self._is_checked(row, VISIBLE_COLUMN),
                "enabled": self._is_checked(row, ENABLED_COLUMN),
                "client_package": self._is_checked(row, CUSTOMER_COLUMN),
                "internal_only": self._is_checked(row, INTERNAL_COLUMN),
            }
            features[item.feature_id] = normalize_feature_state(item, raw_state)
        return features

    @staticmethod
    def _validate_customer_features(features: dict[str, dict[str, bool]]) -> str:
        module_states = {
            item.feature_id: features.get(item.feature_id, {})
            for item in list_features()
            if item.item_type == "module" and not item.internal_only
        }
        if not any(bool(state.get("visible")) and bool(state.get("enabled")) for state in module_states.values()):
            return "至少需要保留一个可显示、可启用的主模块。"
        system_settings = features.get("module.system_settings", {})
        feature_switch = features.get("module.feature_switch", {})
        if not (
            (bool(system_settings.get("visible")) and bool(system_settings.get("enabled")))
            or (bool(feature_switch.get("visible")) and bool(feature_switch.get("enabled")))
        ):
            return "不能同时隐藏功能开关配置和系统设置。"
        return ""

    def _saved_customer_features(self) -> dict[str, dict[str, bool]]:
        return load_profile(project_root() / "profiles" / "features" / "customer.json", "customer")

    def _configure_table(self) -> None:
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        for column in CHECK_COLUMNS:
            install_checkbox_only_delegate(self.table, column)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating_table or item.column() not in CHECK_COLUMNS:
            return
        self._updating_table = True
        try:
            row = item.row()
            column = item.column()
            if column == VISIBLE_COLUMN and not self._is_checked(row, VISIBLE_COLUMN):
                self._set_checked(row, ENABLED_COLUMN, False)
            elif column == ENABLED_COLUMN and self._is_checked(row, ENABLED_COLUMN):
                self._set_checked(row, VISIBLE_COLUMN, True)
            elif column == CUSTOMER_COLUMN and self._is_checked(row, CUSTOMER_COLUMN):
                self._set_checked(row, VISIBLE_COLUMN, True)
                self._set_checked(row, ENABLED_COLUMN, True)
                self._set_checked(row, INTERNAL_COLUMN, False)
                self._show_success("客户版打包功能已自动设为显示和启用。")
            elif column == INTERNAL_COLUMN and self._is_checked(row, INTERNAL_COLUMN):
                self._set_checked(row, CUSTOMER_COLUMN, False)
                self._show_success("内部专用功能不能进入客户版打包。")
            self._sync_customer_cell_enabled(row)
        finally:
            self._updating_table = False

    def _sync_customer_cell_enabled(self, row: int) -> None:
        cell = self.table.item(row, CUSTOMER_COLUMN)
        if cell is None:
            return
        enabled = not self._is_checked(row, INTERNAL_COLUMN)
        flags = Qt.ItemIsUserCheckable | Qt.ItemIsSelectable
        if enabled:
            flags |= Qt.ItemIsEnabled
        cell.setFlags(flags)

    def _is_checked(self, row: int, column: int) -> bool:
        cell = self.table.item(row, column)
        return cell is not None and cell.checkState() == Qt.Checked

    def _set_checked(self, row: int, column: int, checked: bool) -> None:
        cell = self.table.item(row, column)
        if cell is not None:
            cell.setCheckState(Qt.Checked if checked else Qt.Unchecked)

    def _show_success(self, message: str) -> None:
        if InfoBar is not None:
            InfoBar.success(title=self.i18n.t("feature_flags.title"), content=message, duration=2500, position=InfoBarPosition.TOP_RIGHT, parent=self.window())
            return
        MessageBox.information(self, self.i18n.t("feature_flags.title"), message)

    def _show_error(self, title: str, message: str) -> None:
        if InfoBar is not None:
            InfoBar.error(title=title, content=message, duration=4000, position=InfoBarPosition.TOP_RIGHT, parent=self.window())
            return
        MessageBox.critical(self, title, message)
