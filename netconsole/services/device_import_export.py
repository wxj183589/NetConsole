from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from netconsole.models.device import DEVICE_TYPES, DEVICE_VENDORS, Device
from netconsole.repositories.device_repository import DeviceRepository


SNMPV3_SECURITY_LEVELS = ("noAuthNoPriv", "AuthNoPriv", "AuthPriv")
SNMPV3_AUTH_PROTOCOLS = ("MD5", "SHA")
SNMPV3_PRIV_PROTOCOLS = ("DES56", "3DES", "AES128", "AES192", "AES256")

TEMPLATE_FIELDS = [
    "设备名称",
    "IP地址",
    "厂商",
    "站点/位置",
    "设备类型",
    "SSH启用",
    "SSH端口",
    "Telnet启用",
    "Telnet端口",
    "用户名",
    "密码",
    "Enable密码",
    "SNMPv1",
    "SNMPv2c",
    "SNMPv3",
    "SNMP端口",
    "SNMP只读团体字",
    "SNMP读写团体字",
    "标签",
    "备注",
]

TEMPLATE_EXAMPLE_ROW = [
    "核心交换机-示例",
    "192.168.1.1",
    "H3C",
    "控制中心",
    "SW",
    "是",
    "22",
    "否",
    "23",
    "admin",
    "admin123",
    "",
    "否",
    "是",
    "否",
    "161",
    "hw_public",
    "",
    "核心",
    "演示设备，可删除",
]

TEMPLATE_FIELD_MAP = {
    "设备名称": "name",
    "IP地址": "ip_address",
    "厂商": "device_vendor",
    "站点/位置": "station",
    "设备类型": "device_type",
    "SSH启用": "ssh_enabled",
    "SSH端口": "ssh_port",
    "Telnet启用": "telnet_enabled",
    "Telnet端口": "telnet_port",
    "用户名": "username",
    "密码": "password",
    "Enable密码": "auth_mode",
    "SNMPv1": "snmp_v1_enabled",
    "SNMPv2c": "snmp_v2c_enabled",
    "SNMPv3": "snmp_v3_enabled",
    "SNMP端口": "snmp_port",
    "SNMP只读团体字": "snmp_ro_community",
    "SNMP读写团体字": "snmp_rw_community",
    "标签": "tags",
    "备注": "remark",
    "协议": "legacy_protocol",
    "端口": "legacy_port",
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
    "auth_mode",
    "username",
    "password",
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
    "tags",
    "remark",
    "created_at",
    "updated_at",
]


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


class DeviceImportExportService:
    def __init__(self, repository: DeviceRepository) -> None:
        self.repository = repository

    def import_csv(self, path: Path) -> ImportResult:
        with Path(path).open("r", newline="", encoding="utf-8-sig") as file:
            rows = list(csv.reader(file))
        if not rows:
            return ImportResult(created=0, skipped=0, errors=[])

        headers = [header.strip() for header in rows[0]]
        mode = self._detect_mode(headers)
        mapped_rows = [
            (line_number, self._map_row(headers, values, mode))
            for line_number, values in enumerate(rows[1:], start=2)
        ]
        return self._import_rows(mapped_rows)

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
            writer.writerow(TEMPLATE_EXAMPLE_ROW)

    def _import_rows(self, rows: Iterable[tuple[int, dict[str, object | None]]]) -> ImportResult:
        created = 0
        skipped = 0
        errors: list[str] = []
        for line_number, payload in rows:
            if not payload.get("name") or not payload.get("ip_address"):
                skipped += 1
                errors.append(f"Row {line_number}: name and ip_address are required")
                continue
            try:
                compact_payload = {key: value for key, value in payload.items() if value is not None}
                self._apply_defaults(compact_payload)
                self._validate_payload(compact_payload)
                self.repository.create(Device.from_mapping(compact_payload))
                created += 1
            except Exception as exc:
                skipped += 1
                errors.append(f"Row {line_number}: {exc}")
        return ImportResult(created=created, skipped=skipped, errors=errors)

    def _apply_defaults(self, payload: dict[str, object]) -> None:
        payload.setdefault("device_vendor", "H3C")
        payload.setdefault("device_type", "SW")
        legacy_protocol = str(payload.pop("legacy_protocol", "") or "").lower()
        legacy_port = payload.pop("legacy_port", None)
        if legacy_protocol == "telnet":
            payload.setdefault("ssh_enabled", 0)
            payload.setdefault("telnet_enabled", 1)
            if legacy_port is not None:
                payload.setdefault("telnet_port", legacy_port)
        elif legacy_protocol == "ssh":
            payload.setdefault("ssh_enabled", 1)
            payload.setdefault("telnet_enabled", 0)
            if legacy_port is not None:
                payload.setdefault("ssh_port", legacy_port)
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
        for field in ("ssh_port", "telnet_port", "snmp_port"):
            if payload.get(field) is not None:
                payload[field] = int(payload[field])

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
        if "设备名称" in headers and "IP地址" in headers:
            return "template"
        if "name" in headers and "ip_address" in headers:
            return "export"
        raise ValueError("Unsupported CSV header")

    @staticmethod
    def _map_row(headers: list[str], values: list[object], mode: str) -> dict[str, object | None]:
        result: dict[str, object | None] = {}
        field_map = TEMPLATE_FIELD_MAP if mode == "template" else {field: field for field in EXPORT_FIELDS}
        for index, header in enumerate(headers):
            field = field_map.get(header)
            if field is None:
                continue
            value = values[index] if index < len(values) else None
            result[field] = DeviceImportExportService._clean_value(value)
        return result

    @staticmethod
    def _clean_value(value: object) -> object | None:
        if value is None:
            return None
        if isinstance(value, str):
            text = value.strip()
            return text if text else None
        return value
