from __future__ import annotations

from netconsole.ui.dialogs.message_service import MessageBox
import json
from dataclasses import dataclass

from ipaddress import ip_address

from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QScrollArea, QVBoxLayout, QWidget


SET_DATA_TYPES = [
    "OctetString",
    "Integer",
    "OID",
    "Gauge",
    "Counter32",
    "IpAddress",
    "TimeTicks",
    "Counter64",
    "UnsignedInteger",
    "BITS",
    "Float",
    "DateAndTime",
]


@dataclass(frozen=True)
class SnmpSetDialogResult:
    oid: str
    data_type: str
    value: str


class SnmpSetDialog(QDialog):
    def __init__(
        self,
        *,
        oid: str,
        object_name: str = "",
        module_name: str = "",
        access: str = "",
        syntax: str = "",
        current_value: str = "",
        write_community: str = "",
        target_name: str = "",
        description: str = "",
        enum_map_json: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("SNMP SET")
        self.resize(720, 560)
        self.setMinimumSize(640, 480)
        self.oid_input = QLineEdit(oid)
        self.object_name_label = QLabel(object_name or "-")
        self.module_label = QLabel(module_name or "-")
        self.access_label = QLabel(access or "未识别")
        self.current_value_label = QLabel(current_value or "-")
        self.current_value_label.setWordWrap(True)
        self.target_label = QLabel(target_name or "-")
        self.write_community_label = QLabel(write_community or "未配置")
        self.type_combo = QComboBox()
        self.type_combo.addItems(SET_DATA_TYPES)
        self.type_combo.setCurrentText(recommend_set_data_type(syntax))
        self.value_input = QLineEdit()
        self.value_input.setPlaceholderText(value_placeholder(self.type_combo.currentText()))
        self.type_combo.currentTextChanged.connect(lambda text: self.value_input.setPlaceholderText(value_placeholder(text)))
        self.value_combo: QComboBox | None = None
        self._enum_map = parse_enum_map(enum_map_json)
        value_widget = self.value_input
        if self._enum_map:
            self.value_combo = QComboBox()
            for raw, label in self._enum_map.items():
                self.value_combo.addItem(f"{label} ({raw})", raw)
            value_widget = self.value_combo
            self.type_combo.setCurrentText("Integer")
        desc_label = QLabel(description or "-")
        desc_label.setWordWrap(True)
        risk = QLabel("风险提示：SNMP Set 会修改设备运行状态，请确认该 OID 和写入值正确。")
        risk.setWordWrap(True)
        form_widget = QWidget()
        form = QFormLayout(form_widget)
        form.addRow("OID", self.oid_input)
        form.addRow("对象名称", self.object_name_label)
        form.addRow("MIB模块", self.module_label)
        form.addRow("访问权限", self.access_label)
        form.addRow("目标设备", self.target_label)
        form.addRow("写团体字", self.write_community_label)
        form.addRow("当前值", self.current_value_label)
        form.addRow("Data Type", self.type_combo)
        form.addRow("Value", value_widget)
        form.addRow("说明", desc_label)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(form_widget)
        layout = QVBoxLayout(self)
        layout.addWidget(scroll, 1)
        layout.addWidget(risk)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self) -> None:
        oid = self.oid_input.text().strip()
        data_type = self.type_combo.currentText()
        value = str(self.value_combo.currentData()) if self.value_combo is not None else self.value_input.text()
        if not oid:
            MessageBox.information(self, "SNMP SET", "OID 不能为空。")
            return
        if value == "" and data_type not in {"OctetString"}:
            MessageBox.information(self, "SNMP SET", "Value 不能为空。")
            return
        access = self.access_label.text().strip().lower()
        if access and access not in {"read-write", "read-create", "write-only"}:
            MessageBox.information(self, "SNMP SET", "当前 MIB 节点不是可写对象，不能执行 SET")
            return
        if self.write_community_label.text().strip() in {"", "未配置"}:
            MessageBox.information(self, "SNMP SET", "未配置写团体字，无法执行 SNMP SET")
            return
        if data_type == "IpAddress":
            try:
                ip_address(value.strip())
            except ValueError:
                MessageBox.information(self, "SNMP SET", "IP 地址格式不合法。")
                return
        if data_type == "DateAndTime":
            MessageBox.information(self, "SNMP SET", "DateAndTime 将按 SNMP DateAndTime OCTET STRING 编码")
        super().accept()

    def result_data(self) -> SnmpSetDialogResult:
        value = str(self.value_combo.currentData()) if self.value_combo is not None else self.value_input.text().strip()
        return SnmpSetDialogResult(oid=self.oid_input.text().strip(), data_type=self.type_combo.currentText(), value=value)


def recommend_set_data_type(syntax: str) -> str:
    text = str(syntax or "").strip().lower()
    if "truthvalue" in text:
        return "Integer"
    if "integer32" in text or text == "integer":
        return "Integer"
    if "unsigned32" in text:
        return "UnsignedInteger"
    if "gauge32" in text:
        return "Gauge"
    if "counter64" in text:
        return "Counter64"
    if "counter32" in text:
        return "Counter32"
    if "dateandtime" in text:
        return "DateAndTime"
    if "octet string" in text or "displaystring" in text:
        return "OctetString"
    if "ipaddress" in text:
        return "IpAddress"
    if "object identifier" in text:
        return "OID"
    if "timeticks" in text:
        return "TimeTicks"
    if "bits" in text:
        return "BITS"
    if "float" in text:
        return "Float"
    if "integer" in text:
        return "Integer"
    return "OctetString"


def parse_enum_map(enum_map_json: str) -> dict[str, str]:
    if not enum_map_json:
        return {}
    try:
        data = json.loads(enum_map_json)
    except json.JSONDecodeError:
        return {}
    return {str(key): str(value) for key, value in data.items()} if isinstance(data, dict) else {}


def value_placeholder(data_type: str) -> str:
    return {
        "IpAddress": "IPv4 地址，例如 192.168.1.1",
        "DateAndTime": "26-07-05,15:28:44 或 2026-07-05 15:28:44",
        "OID": "数字 OID，例如 1.3.6.1.2.1.1.5.0",
        "Integer": "整数值",
        "UnsignedInteger": "非负整数",
        "Gauge": "非负整数",
        "Counter32": "非负整数",
        "Counter64": "非负整数",
        "TimeTicks": "TimeTicks 非负整数",
    }.get(data_type, "")
