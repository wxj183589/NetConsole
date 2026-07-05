from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from netconsole.core.i18n import I18n
from netconsole.models.device import DEVICE_TYPES, DEVICE_VENDORS, Device
from netconsole.models.device_group import DeviceGroup
from netconsole.services.netmiko_connection import ConnectionTestResult, extract_sysname_from_prompt
from netconsole.services.device_import_export import SNMPV3_AUTH_PROTOCOLS, SNMPV3_PRIV_PROTOCOLS, SNMPV3_SECURITY_LEVELS
from netconsole.ui.connection_worker import DeviceConnectionTestThread
from netconsole.ui.dialogs.device_form_rules import validate_device_form_data
from netconsole.ui.windowing import fit_default_window_size


BASIC_FIELDS = ("name", "system_name", "group_id", "device_vendor", "device_type", "station", "remark")
CONNECTION_FIELDS = (
    "primary_address",
    "backup_address",
    "ssh_enabled",
    "ssh_port",
    "telnet_enabled",
    "telnet_port",
    "ssh_username",
    "ssh_password",
    "telnet_username",
    "telnet_password",
)
TUNNEL_FIELDS = (
    "tunnel_enabled",
    "tunnel1_enabled",
    "tunnel1_host",
    "tunnel1_port",
    "tunnel1_username",
    "tunnel1_password",
    "tunnel2_enabled",
    "tunnel2_host",
    "tunnel2_port",
    "tunnel2_username",
    "tunnel2_password",
)
SNMP_FIELDS = (
    "snmp_enabled",
    "snmp_v1_enabled",
    "snmp_v2c_enabled",
    "snmp_v3_enabled",
    "snmp_port",
    "snmp_ro_community",
    "snmp_rw_community",
    "snmpv3_username",
    "snmpv3_security_level",
    "snmpv3_auth_protocol",
    "snmpv3_auth_password",
    "snmpv3_priv_protocol",
    "snmpv3_priv_password",
    "snmp_context_name",
    "snmp_timeout_ms",
    "snmp_retries",
)


class DeviceDialog(QDialog):
    saved = Signal(object)

    def __init__(self, i18n: I18n, parent=None, device: Device | None = None, groups: list[DeviceGroup] | None = None) -> None:
        super().__init__(parent, Qt.Window)
        self.i18n = i18n
        self.original = device
        self.groups = list(groups or [])
        self.inputs: dict[str, object] = {}
        self.labels: dict[str, QLabel] = {}
        self.connection_test_thread: DeviceConnectionTestThread | None = None

        self.setModal(False)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setMinimumSize(760, 560)
        self.apply_initial_geometry()
        root = QVBoxLayout(self)
        top_layout = QHBoxLayout()
        self.title_label = QLabel()
        top_layout.addWidget(self.title_label)
        top_layout.addStretch(1)
        self.always_on_top_button = QPushButton()
        self.always_on_top_button.setCheckable(True)
        self.always_on_top_button.toggled.connect(self.set_always_on_top)
        top_layout.addWidget(self.always_on_top_button)
        root.addLayout(top_layout)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        columns = QHBoxLayout()
        scroll_layout.addLayout(columns)

        self.basic_group, basic_form = self._group_with_form()
        self.connection_group, connection_form = self._group_with_form()
        self.ssh_auth_group, ssh_auth_form = self._group_with_form()
        self.telnet_auth_group, telnet_auth_form = self._group_with_form()
        columns.addWidget(self.basic_group, 1)
        columns.addWidget(self.connection_group, 1)
        columns.addWidget(self.ssh_auth_group, 1)
        columns.addWidget(self.telnet_auth_group, 1)

        self._add_line(basic_form, "name")
        self._add_line(basic_form, "system_name")
        self._add_group_combo(basic_form)
        self._add_combo(basic_form, "device_vendor", DEVICE_VENDORS)
        self._add_combo(basic_form, "device_type", DEVICE_TYPES)
        self._add_line(basic_form, "station")
        self._add_text(basic_form, "remark")

        self._add_line(connection_form, "primary_address")
        self._add_line(connection_form, "backup_address")
        self._add_checkbox(connection_form, "ssh_enabled")
        self._add_spin(connection_form, "ssh_port", 1, 65535)
        self._add_checkbox(connection_form, "telnet_enabled")
        self._add_spin(connection_form, "telnet_port", 1, 65535)
        self._add_line(ssh_auth_form, "ssh_username")
        self._add_line(ssh_auth_form, "ssh_password", password=True)
        self._add_line(telnet_auth_form, "telnet_username")
        self._add_line(telnet_auth_form, "telnet_password", password=True)

        self.tunnel_group = QGroupBox()
        tunnel_layout = QHBoxLayout(self.tunnel_group)
        tunnel_global_form = QFormLayout()
        tunnel1_form = QFormLayout()
        tunnel2_form = QFormLayout()
        tunnel_layout.addLayout(tunnel_global_form, 1)
        tunnel_layout.addLayout(tunnel1_form, 1)
        tunnel_layout.addLayout(tunnel2_form, 1)
        self._add_checkbox(tunnel_global_form, "tunnel_enabled")
        self._add_checkbox(tunnel1_form, "tunnel1_enabled")
        self._add_line(tunnel1_form, "tunnel1_host")
        self._add_line(tunnel1_form, "tunnel1_port")
        self._add_line(tunnel1_form, "tunnel1_username")
        self._add_line(tunnel1_form, "tunnel1_password", password=True)
        self._add_checkbox(tunnel2_form, "tunnel2_enabled")
        self._add_line(tunnel2_form, "tunnel2_host")
        self._add_line(tunnel2_form, "tunnel2_port")
        self._add_line(tunnel2_form, "tunnel2_username")
        self._add_line(tunnel2_form, "tunnel2_password", password=True)
        scroll_layout.addWidget(self.tunnel_group)

        self.snmp_toggle = QToolButton()
        self.snmp_toggle.setCheckable(True)
        self.snmp_toggle.setChecked(False)
        self.snmp_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.snmp_toggle.setArrowType(Qt.RightArrow)
        self.snmp_toggle.clicked.connect(self._toggle_snmp)
        scroll_layout.addWidget(self.snmp_toggle)

        self.snmp_panel = QFrame()
        snmp_layout = QHBoxLayout(self.snmp_panel)
        left_snmp = QFormLayout()
        right_snmp = QFormLayout()
        snmp_layout.addLayout(left_snmp, 1)
        snmp_layout.addLayout(right_snmp, 1)
        self._add_checkbox(left_snmp, "snmp_enabled")
        self._add_checkbox(left_snmp, "snmp_v1_enabled")
        self._add_checkbox(left_snmp, "snmp_v2c_enabled")
        self._add_checkbox(left_snmp, "snmp_v3_enabled")
        self._add_spin(left_snmp, "snmp_port", 1, 65535)
        self._add_spin(left_snmp, "snmp_timeout_ms", 100, 60000)
        self._add_spin(left_snmp, "snmp_retries", 0, 10)
        self._add_line(left_snmp, "snmp_ro_community")
        self._add_line(left_snmp, "snmp_rw_community")
        self._add_line(right_snmp, "snmpv3_username")
        self._add_combo(right_snmp, "snmpv3_security_level", SNMPV3_SECURITY_LEVELS)
        self._add_combo(right_snmp, "snmpv3_auth_protocol", SNMPV3_AUTH_PROTOCOLS)
        self._add_line(right_snmp, "snmpv3_auth_password", password=True)
        self._add_combo(right_snmp, "snmpv3_priv_protocol", SNMPV3_PRIV_PROTOCOLS)
        self._add_line(right_snmp, "snmpv3_priv_password", password=True)
        self._add_line(right_snmp, "snmp_context_name")
        self.snmp_panel.setVisible(False)
        scroll_layout.addWidget(self.snmp_panel)
        scroll_layout.addStretch(1)
        self.scroll_area.setWidget(scroll_content)
        root.addWidget(self.scroll_area, 1)

        button_layout = QHBoxLayout()
        button_layout.addStretch(1)
        self.cancel_button = QPushButton()
        self.test_button = QPushButton()
        self.save_button = QPushButton()
        self.cancel_button.clicked.connect(self.reject)
        self.test_button.clicked.connect(self.test_connection)
        self.save_button.clicked.connect(self.accept)
        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.test_button)
        button_layout.addWidget(self.save_button)
        root.addLayout(button_layout)

        self.snmp_v3_checkbox.stateChanged.connect(self._update_snmpv3_visibility)
        self.snmpv3_security_combo.currentTextChanged.connect(self._update_snmpv3_visibility)
        tunnel1_host_widget = self.inputs.get("tunnel1_host")
        tunnel2_host_widget = self.inputs.get("tunnel2_host")
        if isinstance(tunnel1_host_widget, QLineEdit):
            tunnel1_host_widget.textChanged.connect(lambda _text: self._sync_tunnel_checkbox_from_host("tunnel1"))
        if isinstance(tunnel2_host_widget, QLineEdit):
            tunnel2_host_widget.textChanged.connect(lambda _text: self._sync_tunnel_checkbox_from_host("tunnel2"))
        self._load(device)
        self._update_snmpv3_visibility()
        self._sync_tunnel_checkbox_from_host("tunnel1")
        self._sync_tunnel_checkbox_from_host("tunnel2")
        self.retranslate()

    def apply_initial_geometry(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            self.resize(900, 680)
            return
        available = screen.availableGeometry()
        size = fit_default_window_size(available.width(), available.height(), 900, 680)
        self.resize(size.width, size.height)

    def _group_with_form(self) -> tuple[QGroupBox, QFormLayout]:
        group = QGroupBox()
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        group.setLayout(form)
        return group, form

    def _add_labelled_widget(self, form: QFormLayout, field: str, widget: QWidget) -> None:
        label = QLabel()
        self.labels[field] = label
        self.inputs[field] = widget
        form.addRow(label, widget)

    def _add_line(self, form: QFormLayout, field: str, password: bool = False) -> None:
        widget = QLineEdit()
        if password:
            widget.setEchoMode(QLineEdit.Password)
        self._add_labelled_widget(form, field, widget)

    def _add_text(self, form: QFormLayout, field: str) -> None:
        widget = QTextEdit()
        widget.setFixedHeight(72)
        self._add_labelled_widget(form, field, widget)

    def _add_combo(self, form: QFormLayout, field: str, values: tuple[str, ...]) -> None:
        widget = QComboBox()
        widget.addItems(values)
        if field == "snmpv3_security_level":
            self.snmpv3_security_combo = widget
        self._add_labelled_widget(form, field, widget)

    def _add_group_combo(self, form: QFormLayout) -> None:
        widget = QComboBox()
        widget.addItem(self.i18n.t("groups.ungrouped"), None)
        for group in self.groups:
            widget.addItem(group.name, group.id)
        self._add_labelled_widget(form, "group_id", widget)

    def _add_spin(self, form: QFormLayout, field: str, minimum: int, maximum: int) -> None:
        widget = QSpinBox()
        widget.setRange(minimum, maximum)
        self._add_labelled_widget(form, field, widget)

    def _add_checkbox(self, form: QFormLayout, field: str) -> None:
        widget = QCheckBox()
        if field == "snmp_v3_enabled":
            self.snmp_v3_checkbox = widget
        self._add_labelled_widget(form, field, widget)

    def _load(self, device: Device | None) -> None:
        values = device.to_record() if device else {
            "device_vendor": "H3C",
            "device_type": "SW",
            "ssh_enabled": 1,
            "ssh_port": 22,
            "telnet_enabled": 0,
            "telnet_port": 23,
            "tunnel_enabled": 0,
            "tunnel1_enabled": 0,
            "tunnel1_port": 22,
            "tunnel2_enabled": 0,
            "tunnel2_port": 22,
            "snmp_enabled": 1,
            "snmp_v1_enabled": 0,
            "snmp_v2c_enabled": 1,
            "snmp_v3_enabled": 0,
            "snmp_port": 161,
            "snmp_timeout_ms": 2000,
            "snmp_retries": 1,
            "snmpv3_security_level": "noAuthNoPriv",
            "snmpv3_auth_protocol": "SHA",
            "snmpv3_priv_protocol": "AES128",
        }
        for field, widget in self.inputs.items():
            value = values.get(field)
            if isinstance(widget, QLineEdit):
                widget.setText("" if value is None else str(value))
            elif isinstance(widget, QTextEdit):
                widget.setPlainText("" if value is None else str(value))
            elif isinstance(widget, QComboBox):
                index = widget.findData(value) if field == "group_id" else widget.findText("" if value is None else str(value))
                widget.setCurrentIndex(index if index >= 0 else 0)
            elif isinstance(widget, QSpinBox):
                widget.setValue(int(value or 0))
            elif isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))

    def retranslate(self) -> None:
        title = self.i18n.t("dialog.edit_device" if self.original else "dialog.add_device")
        self.setWindowTitle(title)
        self.title_label.setText(title)
        self.always_on_top_button.setText(self.i18n.t("window.cancel_always_on_top" if self.always_on_top_button.isChecked() else "window.always_on_top"))
        self.basic_group.setTitle(self.i18n.t("dialog.basic_info"))
        self.connection_group.setTitle(self.i18n.t("dialog.connection"))
        self.ssh_auth_group.setTitle(self.i18n.t("dialog.ssh_authentication"))
        self.telnet_auth_group.setTitle(self.i18n.t("dialog.telnet_authentication"))
        self.tunnel_group.setTitle(self.i18n.t("dialog.ssh_tunnel"))
        self.snmp_toggle.setText(self.i18n.t("dialog.snmp_reserved"))
        self.cancel_button.setText(self.i18n.t("dialog.cancel"))
        self.test_button.setText(self.i18n.t("dialog.test_connection"))
        self.test_button.setToolTip(self.i18n.t("dialog.test_connection_tip"))
        self.save_button.setText(self.i18n.t("dialog.save_device"))
        group_widget = self.inputs.get("group_id")
        if isinstance(group_widget, QComboBox) and group_widget.count():
            group_widget.setItemText(0, self.i18n.t("groups.ungrouped"))
        for field, label in self.labels.items():
            suffix = " *" if field in {"name", "primary_address"} else ""
            label.setText(self.i18n.t(f"field.{field}") + suffix)

    def accept(self) -> None:
        data = self.form_data()
        error_key = validate_device_form_data(data)
        if error_key:
            QMessageBox.warning(self, self.windowTitle(), self.i18n.t(error_key))
            return
        self.saved.emit(self.device())

    def test_connection(self) -> None:
        device = self.device()
        if not device.primary_address:
            QMessageBox.warning(self, self.windowTitle(), self.i18n.t("validation.host_required"))
            return
        self.test_button.setEnabled(False)
        self.test_button.setText(self.i18n.t("devices.testing_connection"))
        self.connection_test_thread = DeviceConnectionTestThread(device, self)
        self.connection_test_thread.result_ready.connect(self._show_connection_result)
        self.connection_test_thread.finished.connect(self.connection_test_thread.deleteLater)
        self.connection_test_thread.finished.connect(lambda: setattr(self, "connection_test_thread", None))
        self.connection_test_thread.start()

    def _show_connection_result(self, result: ConnectionTestResult) -> None:
        self.test_button.setEnabled(True)
        self.test_button.setText(self.i18n.t("dialog.test_connection"))
        if result.success:
            sysname = self.apply_test_connection_sysname(result)
            message = self.i18n.t(
                "connection.success_detail",
                protocol=result.protocol,
                host=f"{result.host}:{result.port}",
                prompt=result.prompt or "-",
                elapsed=result.elapsed_ms if result.elapsed_ms is not None else "-",
            )
            if sysname:
                message = f"{message}\n{self.i18n.t('field.system_name')}: {sysname}"
            QMessageBox.information(self, self.i18n.t("connection.success_title"), message)
        else:
            QMessageBox.warning(
                self,
                self.i18n.t("connection.failed_title"),
                self.i18n.t("connection.failed_detail", reason=result.message),
            )

    def apply_test_connection_sysname(self, result: ConnectionTestResult) -> str | None:
        return self.apply_test_connection_system_name(result)

    def apply_test_connection_system_name(self, result: ConnectionTestResult) -> str | None:
        sysname = extract_sysname_from_prompt(result.prompt or "")
        if not sysname:
            return None
        widget = self.inputs["system_name"]
        if isinstance(widget, QLineEdit):
            widget.setText(sysname)
        return sysname

    def set_always_on_top(self, enabled: bool) -> None:
        self.setWindowFlag(Qt.WindowStaysOnTopHint, enabled)
        self.always_on_top_button.setText(self.i18n.t("window.cancel_always_on_top" if enabled else "window.always_on_top"))
        self.show()
        if enabled:
            self.raise_()
            self.activateWindow()

    def form_data(self) -> dict[str, object | None]:
        data: dict[str, object | None] = {}
        if self.original:
            data.update(self.original.to_record())
        for field in BASIC_FIELDS + CONNECTION_FIELDS + TUNNEL_FIELDS + SNMP_FIELDS:
            widget = self.inputs[field]
            if isinstance(widget, (QLineEdit, QTextEdit, QComboBox)):
                if field == "group_id" and isinstance(widget, QComboBox):
                    data[field] = widget.currentData()
                elif field.endswith("_port"):
                    data[field] = self._optional_int(field)
                else:
                    data[field] = self._text(field) or None
            elif isinstance(widget, QSpinBox):
                data[field] = widget.value()
            elif isinstance(widget, QCheckBox):
                data[field] = 1 if widget.isChecked() else 0
        if data.get("ssh_enabled"):
            data["protocol"] = "SSH"
            data["port"] = data.get("ssh_port") or 22
        elif data.get("telnet_enabled"):
            data["protocol"] = "Telnet"
            data["port"] = data.get("telnet_port") or 23
        else:
            data["protocol"] = None
            data["port"] = None
        tunnel1_has_host = bool(str(data.get("tunnel1_host") or "").strip())
        tunnel2_has_host = bool(str(data.get("tunnel2_host") or "").strip())
        data["tunnel1_enabled"] = 1 if tunnel1_has_host else 0
        data["tunnel2_enabled"] = 1 if tunnel2_has_host else 0
        data["tunnel_enabled"] = 1 if tunnel1_has_host or tunnel2_has_host else 0
        return data

    def device(self) -> Device:
        return Device.from_mapping(self.form_data())

    def _toggle_snmp(self) -> None:
        expanded = self.snmp_toggle.isChecked()
        self.snmp_panel.setVisible(expanded)
        self.snmp_toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)

    def _update_snmpv3_visibility(self, *_args: object) -> None:
        enabled = self.snmp_v3_checkbox.isChecked()
        level = self.snmpv3_security_combo.currentText()
        show_auth = enabled and level in {"AuthNoPriv", "AuthPriv"}
        show_priv = enabled and level == "AuthPriv"
        visibility = {
            "snmpv3_username": enabled,
            "snmpv3_security_level": enabled,
            "snmpv3_auth_protocol": show_auth,
            "snmpv3_auth_password": show_auth,
            "snmpv3_priv_protocol": show_priv,
            "snmpv3_priv_password": show_priv,
            "snmp_context_name": enabled,
        }
        for field, visible in visibility.items():
            self.inputs[field].setVisible(visible)
            self.labels[field].setVisible(visible)

    def _text(self, field: str) -> str:
        widget = self.inputs[field]
        if isinstance(widget, QLineEdit):
            return widget.text().strip()
        if isinstance(widget, QTextEdit):
            return widget.toPlainText().strip()
        if isinstance(widget, QComboBox):
            return widget.currentText().strip()
        return ""

    def _optional_int(self, field: str) -> int | None:
        text = self._text(field)
        return int(text) if text else None

    def _sync_tunnel_checkbox_from_host(self, prefix: str) -> None:
        host_widget = self.inputs.get(f"{prefix}_host")
        enabled_widget = self.inputs.get(f"{prefix}_enabled")
        if isinstance(host_widget, QLineEdit) and isinstance(enabled_widget, QCheckBox):
            enabled_widget.setChecked(bool(host_widget.text().strip()))
