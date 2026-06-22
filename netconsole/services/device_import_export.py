from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from netconsole.models.device import DEVICE_TYPES, DEVICE_VENDORS, Device
from netconsole.repositories.device_group_repository import DeviceGroupRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.utils.text_encoding import FILE_ENCODING_ERROR, TEXT_ENCODINGS


SNMPV3_SECURITY_LEVELS = ("noAuthNoPriv", "AuthNoPriv", "AuthPriv")
SNMPV3_AUTH_PROTOCOLS = ("MD5", "SHA")
SNMPV3_PRIV_PROTOCOLS = ("DES56", "3DES", "AES128", "AES192", "AES256")

TEMPLATE_FIELDS = [
    "设备名称",
    "IP地址",
    "厂商",
    "站点/位置",
    "分组",
    "设备类型",
    "SSH启用",
    "SSH端口",
    "Telnet启用",
    "Telnet端口",
    "SSH用户名",
    "SSH密码",
    "Telnet用户名",
    "Telnet密码",
    "备注",
]

TEMPLATE_EXAMPLE_ROWS = [
    ["核心交换机-示例", "192.168.1.1", "H3C", "控制中心", "COCC", "SW", "是", "22", "否", "23", "admin", "Admin@123", "", "", "SSH设备示例"],
    ["接入交换机-示例", "192.168.1.2", "H3C", "车站A", "车站", "SW", "是", "22", "是", "23", "admin", "Admin@123", "admin", "Admin@123", "SSH+Telnet示例"],
    ["无线控制器-示例", "192.168.1.10", "H3C", "控制中心", "COCC", "AC", "是", "22", "否", "23", "admin", "Admin@123", "", "", "AC设备示例"],
    ["FIT-AP-示例", "192.168.1.20", "H3C", "站台层", "车载", "FIT-AP", "否", "22", "是", "23", "", "Admin@123", " ", "Admin@123", "Telnet设备示例"],
    ["防火墙-示例", "192.168.1.254", "H3C", "控制中心", "BOCC", "FW", "是", "22", "否", "23", "admin", "Admin@123", "", "", "防火墙示例"],
]

TEMPLATE_FIELD_MAP = {
    "设备名称": "name",
    "IP地址": "ip_address",
    "厂商": "device_vendor",
    "站点/位置": "station",
    "分组": "group_name",
    "设备类型": "device_type",
    "SSH启用": "ssh_enabled",
    "SSH端口": "ssh_port",
    "Telnet启用": "telnet_enabled",
    "Telnet端口": "telnet_port",
    "SSH用户名": "ssh_username",
    "SSH密码": "ssh_password",
    "Telnet用户名": "telnet_username",
    "Telnet密码": "telnet_password",
    "备注": "remark",
}

EXPORT_FIELDS = [
    "id",
    "device_uuid",
    "name",
    "sysname",
    "station",
    "device_vendor",
    "device_type",
    "ip_address",
    "ssh_enabled",
    "ssh_port",
    "telnet_enabled",
    "telnet_port",
    "ssh_username",
    "ssh_password",
    "telnet_username",
    "telnet_password",
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
    "https_port",
    "remark",
    "created_at",
    "updated_at",
]

CSV_IMPORT_ENCODINGS = TEXT_ENCODINGS
CSV_ENCODING_ERROR = FILE_ENCODING_ERROR


def make_device_export_filename(site_name: str, now: datetime | None = None) -> str:
    timestamp = (now or datetime.now()).strftime("%Y-%m-%d-%H%M")
    safe_site_name = "".join("_" if char in '<>:"/\\|?*' or ord(char) < 32 else char for char in site_name)
    safe_site_name = safe_site_name.strip().strip(".") or "site"
    return f"{safe_site_name}_{timestamp}.csv"


@dataclass(frozen=True)
class ImportResult:
    created: int
    skipped: int
    errors: list[str]
    groups_created: int = 0


class DeviceImportExportService:
    def __init__(self, repository: DeviceRepository, group_repository: DeviceGroupRepository | None = None) -> None:
        self.repository = repository
        self.group_repository = group_repository

    def import_csv(self, path: Path) -> ImportResult:
        rows = self._read_csv_rows(Path(path))
        if not rows:
            return ImportResult(created=0, skipped=0, errors=[])

        headers = [header.strip() for header in rows[0]]
        mode = self._detect_mode(headers)
        mapped_rows = [
            (line_number, self._map_row(headers, values, mode))
            for line_number, values in enumerate(rows[1:], start=2)
        ]
        return self._import_rows(mapped_rows)

    @staticmethod
    def _read_csv_rows(path: Path) -> list[list[str]]:
        for encoding in CSV_IMPORT_ENCODINGS:
            try:
                with path.open("r", newline="", encoding=encoding) as file:
                    return list(csv.reader(file))
            except UnicodeError:
                continue
        raise ValueError(CSV_ENCODING_ERROR)

    def export_csv(self, path: Path, devices: Iterable[Device] | None = None) -> None:
        devices = list(devices if devices is not None else self.repository.list())
        with Path(path).open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            writer.writerow(EXPORT_FIELDS)
            for device in devices:
                writer.writerow([getattr(device, field) or "" for field in EXPORT_FIELDS])

    def export_template_csv(self, path: Path) -> None:
        with Path(path).open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            writer.writerow(TEMPLATE_FIELDS)
            writer.writerows(TEMPLATE_EXAMPLE_ROWS)

    def _import_rows(self, rows: Iterable[tuple[int, dict[str, object | None]]]) -> ImportResult:
        created = 0
        skipped = 0
        groups_created = 0
        errors: list[str] = []
        for line_number, payload in rows:
            if not payload.get("name") or not payload.get("ip_address"):
                skipped += 1
                errors.append(f"Row {line_number}: name and ip_address are required")
                continue
            try:
                compact_payload = {key: value for key, value in payload.items() if value is not None}
                group_created = self._apply_group(compact_payload)
                groups_created += group_created
                self._apply_defaults(compact_payload)
                self._validate_payload(compact_payload)
                self.repository.create(Device.from_mapping(compact_payload))
                created += 1
            except Exception as exc:
                skipped += 1
                errors.append(f"Row {line_number}: {exc}")
        return ImportResult(created=created, skipped=skipped, errors=errors, groups_created=groups_created)

    def _apply_group(self, payload: dict[str, object]) -> int:
        group_name = payload.pop("group_name", None)
        if group_name is None:
            return 0
        group_text = str(group_name).strip()
        if not group_text or self.group_repository is None:
            payload.pop("group_id", None)
            return 0
        group = self.group_repository.find_by_name(group_text)
        created = 0
        if group is None:
            group = self.group_repository.create(group_text)
            created = 1
        payload["group_id"] = group.id
        return created

    def _apply_defaults(self, payload: dict[str, object]) -> None:
        payload.setdefault("device_vendor", "H3C")
        payload.setdefault("device_type", "SW")
        payload.setdefault("ssh_enabled", 1)
        payload.setdefault("ssh_port", 22)
        payload.setdefault("telnet_enabled", 0)
        payload.setdefault("telnet_port", 23)
        payload.setdefault("snmp_v1_enabled", 0)
        payload.setdefault("snmp_v2c_enabled", 1)
        payload.setdefault("snmp_v3_enabled", 0)
        payload.setdefault("snmp_port", 161)

    def _validate_payload(self, payload: dict[str, object]) -> None:
        device_uuid = payload.get("device_uuid")
        if device_uuid is not None and not Device.is_valid_uuid(str(device_uuid)):
            raise ValueError(f"Invalid device_uuid: {device_uuid}")
        if device_uuid is not None and self.repository.exists_by_uuid(str(device_uuid)):
            raise ValueError(f"Duplicate device_uuid: {device_uuid}")
        if payload["device_vendor"] not in DEVICE_VENDORS:
            raise ValueError(f"Invalid device_vendor: {payload['device_vendor']}")
        if payload["device_type"] not in DEVICE_TYPES:
            raise ValueError(f"Invalid device_type: {payload['device_type']}")
        for field in ("ssh_enabled", "telnet_enabled", "snmp_v1_enabled", "snmp_v2c_enabled", "snmp_v3_enabled"):
            payload[field] = self._parse_bool(payload[field])
        self._normalize_snmpv3_fields(payload)
        if not payload["ssh_enabled"] and not payload["telnet_enabled"]:
            raise ValueError("At least one of SSH or Telnet must be enabled")
        for field in ("ssh_port", "telnet_port", "snmp_port", "https_port"):
            if payload.get(field) is not None:
                payload[field] = int(payload[field])
                if field == "https_port" and not 1 <= int(payload[field]) <= 65535:
                    raise ValueError(f"Invalid https_port: {payload[field]}")

    @staticmethod
    def _normalize_snmpv3_fields(payload: dict[str, object]) -> None:
        if not payload["snmp_v3_enabled"]:
            return

        security_level = str(payload.get("snmpv3_security_level") or "")
        if not security_level:
            payload["snmpv3_security_level"] = "noAuthNoPriv"
            security_level = "noAuthNoPriv"
        if security_level not in SNMPV3_SECURITY_LEVELS:
            raise ValueError(f"Invalid snmpv3_security_level: {security_level}")

        auth_protocol = str(payload.get("snmpv3_auth_protocol") or "")
        priv_protocol = str(payload.get("snmpv3_priv_protocol") or "")
        if priv_protocol == "DES":
            payload["snmpv3_priv_protocol"] = "DES56"
            priv_protocol = "DES56"
        elif priv_protocol == "AES":
            payload["snmpv3_priv_protocol"] = "AES128"
            priv_protocol = "AES128"

        if not auth_protocol:
            payload["snmpv3_auth_protocol"] = "SHA"
            auth_protocol = "SHA"
        if not priv_protocol:
            payload["snmpv3_priv_protocol"] = "AES128"
            priv_protocol = "AES128"

        if auth_protocol and auth_protocol not in SNMPV3_AUTH_PROTOCOLS:
            raise ValueError(f"Invalid snmpv3_auth_protocol: {auth_protocol}")
        if priv_protocol and priv_protocol not in SNMPV3_PRIV_PROTOCOLS:
            raise ValueError(f"Invalid snmpv3_priv_protocol: {priv_protocol}")

    @staticmethod
    def _parse_bool(value: object) -> int:
        if isinstance(value, bool):
            return 1 if value else 0
        if isinstance(value, int):
            return 1 if value else 0
        text = str(value or "").strip().lower()
        if text in {"1", "true", "yes", "y", "是", "启用"}:
            return 1
        if text in {"0", "false", "no", "n", "否", "禁用"}:
            return 0
        return 1 if text else 0

    @staticmethod
    def _detect_mode(headers: list[str]) -> str:
        if headers and all(header in TEMPLATE_FIELD_MAP for header in headers):
            fields = {TEMPLATE_FIELD_MAP[header] for header in headers}
            if {"name", "ip_address"}.issubset(fields):
                return "template"
        if headers == EXPORT_FIELDS:
            return "export"
        raise ValueError("Unsupported CSV header: use the current device template or full export CSV")

    @staticmethod
    def _map_row(headers: list[str], values: list[object], mode: str) -> dict[str, object | None]:
        result: dict[str, object | None] = {}
        field_map = TEMPLATE_FIELD_MAP if mode == "template" else {field: field for field in EXPORT_FIELDS}
        if mode == "template" and "分组" in headers and (
            len(values) == len(headers) - 1 or DeviceImportExportService._looks_like_legacy_template_row(headers, values)
        ):
            values = list(values)
            values.insert(headers.index("分组"), None)
        for index, header in enumerate(headers):
            field = field_map[header]
            value = values[index] if index < len(values) else None
            result[field] = DeviceImportExportService._clean_value(value)
        return result

    @staticmethod
    def _looks_like_legacy_template_row(headers: list[str], values: list[object]) -> bool:
        if "分组" not in headers or len(values) != len(headers):
            return False
        telnet_port_index = headers.index("Telnet端口")
        if telnet_port_index >= len(values):
            return False
        text = str(values[telnet_port_index] or "").strip()
        if not text:
            return False
        try:
            int(text)
            return False
        except ValueError:
            return True

    @staticmethod
    def _clean_value(value: object) -> object | None:
        if value is None:
            return None
        if isinstance(value, str):
            text = value.strip()
            return text if text else None
        return value
