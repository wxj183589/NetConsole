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
from netconsole.services.device_import_export import SNMPV3_AUTH_PROTOCOLS, SNMPV3_PRIV_PROTOCOLS, SNMPV3_SECURITY_LEVELS
from netconsole.ui.dialogs.device_form_rules import validate_device_form_data
from netconsole.ui.windowing import fit_default_window_size


BASIC_FIELDS = ("name", "sysname", "device_vendor", "device_type", "station", "tags", "remark")
CONNECTION_FIELDS = (
    "ip_address",
    "ssh_enabled",
    "ssh_port",
    "telnet_enabled",
    "telnet_port",
    "ssh_username",
    "ssh_password",
    "telnet_username",
    "telnet_password",
)
SNMP_FIELDS = (
    "snmp_v1_enabled",
    "snmp_v2c_enabled",
    "snmp_v3_enabled",
    "snmp_port",
    "snmp_ro_community",
    "snmp_rw_community",
    "snmpv3_security_level",
    "snmpv3_auth_protocol",
    "snmpv3_auth_password",
    "snmpv3_priv_protocol",
    "snmpv3_priv_password",
)


class DeviceDialog(QDialog):
    saved = Signal(object)

    def __init__(self, i18n: I18n, parent=None, device: Device | None = None) -> None:
        super().__init__(parent, Qt.Window)
        self.i18n = i18n
        self.original = device
        self.inputs: dict[str, object] = {}
        self.labels: dict[str, QLabel] = {}

        self.setModal(False)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setMinimumSize(760, 560)
        self.apply_initial_geometry()
        self.setStyleSheet(
            """
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border: 1px solid #8a8f99;
                border-radius: 3px;
                background: #ffffff;
            }
            QCheckBox::indicator:unchecked:hover {
                border: 1px solid #2563eb;
                background: #f8fbff;
            }
            QCheckBox::indicator:checked {
                background: #2563eb;
                border: 1px solid #2563eb;
                image: none;
            }
            QCheckBox::indicator:checked:hover {
                background: #1d4ed8;
                border: 1px solid #1d4ed8;
            }
            QCheckBox::indicator:disabled {
                background: #e5e7eb;
                border: 1px solid #cbd5e1;
            }
            """
        )

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
        self._add_line(basic_form, "sysname")
        self._add_combo(basic_form, "device_vendor", DEVICE_VENDORS)
        self._add_combo(basic_form, "device_type", DEVICE_TYPES)
        self._add_line(basic_form, "station")
        self._add_line(basic_form, "tags")
        self._add_text(basic_form, "remark")

        self._add_checkbox(connection_form, "ssh_enabled")
        self._add_spin(connection_form, "ssh_port", 1, 65535)
        self._add_checkbox(connection_form, "telnet_enabled")
        self._add_spin(connection_form, "telnet_port", 1, 65535)
        self._add_line(connection_form, "ip_address")
        self._add_line(ssh_auth_form, "ssh_username")
        self._add_line(ssh_auth_form, "ssh_password", password=True)
        self._add_line(telnet_auth_form, "telnet_username")
        self._add_line(telnet_auth_form, "telnet_password", password=True)

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
        self._add_checkbox(left_snmp, "snmp_v1_enabled")
        self._add_checkbox(left_snmp, "snmp_v2c_enabled")
        self._add_checkbox(left_snmp, "snmp_v3_enabled")
        self._add_spin(left_snmp, "snmp_port", 1, 65535)
        self._add_line(left_snmp, "snmp_ro_community")
        self._add_line(left_snmp, "snmp_rw_community")
        self._add_combo(right_snmp, "snmpv3_security_level", SNMPV3_SECURITY_LEVELS)
        self._add_combo(right_snmp, "snmpv3_auth_protocol", SNMPV3_AUTH_PROTOCOLS)
        self._add_line(right_snmp, "snmpv3_auth_password", password=True)
        self._add_combo(right_snmp, "snmpv3_priv_protocol", SNMPV3_PRIV_PROTOCOLS)
        self._add_line(right_snmp, "snmpv3_priv_password", password=True)
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
        self.test_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.reject)
        self.save_button.clicked.connect(self.accept)
        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.test_button)
        button_layout.addWidget(self.save_button)
        root.addLayout(button_layout)

        self.snmp_v3_checkbox.stateChanged.connect(self._update_snmpv3_visibility)
        self.snmpv3_security_combo.currentTextChanged.connect(self._update_snmpv3_visibility)
        self._load(device)
        self._update_snmpv3_visibility()
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
            "snmp_v1_enabled": 0,
            "snmp_v2c_enabled": 1,
            "snmp_v3_enabled": 0,
            "snmp_port": 161,
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
                index = widget.findText("" if value is None else str(value))
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
        self.snmp_toggle.setText(self.i18n.t("dialog.snmp_reserved"))
        self.cancel_button.setText(self.i18n.t("dialog.cancel"))
        self.test_button.setText(self.i18n.t("dialog.test_connection"))
        self.test_button.setToolTip(self.i18n.t("dialog.test_connection_tip"))
        self.save_button.setText(self.i18n.t("dialog.save_device"))
        for field, label in self.labels.items():
            suffix = " *" if field in {"name", "ip_address"} else ""
            label.setText(self.i18n.t(f"field.{field}") + suffix)

    def accept(self) -> None:
        data = self.form_data()
        error_key = validate_device_form_data(data)
        if error_key:
            QMessageBox.warning(self, self.windowTitle(), self.i18n.t(error_key))
            return
        self.saved.emit(self.device())

    def set_always_on_top(self, enabled: bool) -> None:
        self.setWindowFlag(Qt.WindowStaysOnTopHint, enabled)
        self.always_on_top_button.setText(self.i18n.t("window.cancel_always_on_top" if enabled else "window.always_on_top"))
        self.show()
        self.raise_()
        self.activateWindow()

    def form_data(self) -> dict[str, object | None]:
        data: dict[str, object | None] = {}
        if self.original:
            data.update(self.original.to_record())
        for field in BASIC_FIELDS + CONNECTION_FIELDS + SNMP_FIELDS:
            widget = self.inputs[field]
            if isinstance(widget, (QLineEdit, QTextEdit, QComboBox)):
                data[field] = self._text(field) or None
            elif isinstance(widget, QSpinBox):
                data[field] = widget.value()
            elif isinstance(widget, QCheckBox):
                data[field] = 1 if widget.isChecked() else 0
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
            "snmpv3_security_level": enabled,
            "snmpv3_auth_protocol": show_auth,
            "snmpv3_auth_password": show_auth,
            "snmpv3_priv_protocol": show_priv,
            "snmpv3_priv_password": show_priv,
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
