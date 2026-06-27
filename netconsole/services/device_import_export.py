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
    "主用地址",
    "备用地址",
    "协议",
    "端口",
    "用户名",
    "密码",
    "厂商",
    "设备类型",
    "分组",
    "归属站点",
    "是否启用SSH隧道",
    "隧道主机1地址",
    "隧道主机1端口",
    "隧道主机1用户名",
    "隧道主机1密码",
    "隧道主机2地址",
    "隧道主机2端口",
    "隧道主机2用户名",
    "隧道主机2密码",
    "备注",
]

TEMPLATE_EXAMPLE_ROWS = [
    ["核心交换机-示例", "192.168.1.1", "", "SSH", "22", "admin", "Admin@123", "H3C", "SW", "COCC", "控制中心", "否", "", "", "", "", "", "", "", "", "SSH设备示例"],
    ["无线控制器-示例", "192.168.1.10", "192.168.2.10", "SSH", "22", "admin", "Admin@123", "H3C", "AC", "COCC", "控制中心", "是", "10.0.0.10", "22", "jump", "Jump@123", "", "", "", "", "主备地址+隧道示例"],
]

TEMPLATE_FIELD_MAP = {
    "设备名称": "name",
    "主用地址": "primary_address",
    "备用地址": "backup_address",
    "厂商": "device_vendor",
    "归属站点": "station",
    "分组": "group_name",
    "设备类型": "device_type",
    "协议": "protocol",
    "端口": "port",
    "用户名": "username",
    "密码": "password",
    "SSH启用": "ssh_enabled",
    "SSH端口": "ssh_port",
    "Telnet启用": "telnet_enabled",
    "Telnet端口": "telnet_port",
    "SSH用户名": "ssh_username",
    "SSH密码": "ssh_password",
    "Telnet用户名": "telnet_username",
    "Telnet密码": "telnet_password",
    "是否启用SSH隧道": "tunnel_enabled",
    "隧道主机1地址": "tunnel1_host",
    "隧道主机1端口": "tunnel1_port",
    "隧道主机1用户名": "tunnel1_username",
    "隧道主机1密码": "tunnel1_password",
    "隧道主机2地址": "tunnel2_host",
    "隧道主机2端口": "tunnel2_port",
    "隧道主机2用户名": "tunnel2_username",
    "隧道主机2密码": "tunnel2_password",
    "备注": "remark",
}

EXPORT_FIELDS = list(TEMPLATE_FIELDS)

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
        group_names = self._group_names_by_id()
        with Path(path).open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            writer.writerow(EXPORT_FIELDS)
            for device in devices:
                writer.writerow([self._export_value(device, field, group_names) for field in EXPORT_FIELDS])

    def export_template_csv(self, path: Path) -> None:
        with Path(path).open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            writer.writerow(TEMPLATE_FIELDS)
            writer.writerows(TEMPLATE_EXAMPLE_ROWS)

    def _group_names_by_id(self) -> dict[int, str]:
        if self.group_repository is None:
            return {}
        return {int(group.id): group.name for group in self.group_repository.list() if group.id is not None}

    @staticmethod
    def _export_value(device: Device, field: str, group_names: dict[int, str]) -> object:
        mapped = TEMPLATE_FIELD_MAP[field]
        if mapped == "group_name":
            return group_names.get(int(device.group_id or 0), "")
        if mapped == "tunnel_enabled":
            return "是" if getattr(device, mapped) else "否"
        return getattr(device, mapped) or ""

    def _import_rows(self, rows: Iterable[tuple[int, dict[str, object | None]]]) -> ImportResult:
        created = 0
        skipped = 0
        groups_created = 0
        errors: list[str] = []
        for line_number, payload in rows:
            if not payload.get("name") or not payload.get("primary_address"):
                skipped += 1
                errors.append(f"Row {line_number}: name and primary_address are required")
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
        if payload.get("device_type") == "FIT-AP":
            payload["device_type"] = "Cloud-AP"
        payload.setdefault("ssh_enabled", 1)
        payload.setdefault("ssh_port", 22)
        payload.setdefault("telnet_enabled", 0)
        payload.setdefault("telnet_port", 23)
        payload.setdefault("snmp_v1_enabled", 0)
        payload.setdefault("snmp_v2c_enabled", 1)
        payload.setdefault("snmp_v3_enabled", 0)
        payload.setdefault("snmp_port", 161)
        protocol_value = payload.get("protocol")
        if protocol_value:
            protocol = str(protocol_value).casefold()
            if protocol == "telnet":
                payload["telnet_enabled"] = 1
                payload["ssh_enabled"] = 0
                payload["telnet_port"] = int(payload.get("port") or payload.get("telnet_port") or 23)
                payload["telnet_username"] = payload.get("username") or payload.get("telnet_username")
                payload["telnet_password"] = payload.get("password") or payload.get("telnet_password")
            else:
                payload["ssh_enabled"] = 1
                payload["telnet_enabled"] = int(payload.get("telnet_enabled") or 0)
                payload["ssh_port"] = int(payload.get("port") or payload.get("ssh_port") or 22)
                payload["ssh_username"] = payload.get("username") or payload.get("ssh_username")
                payload["ssh_password"] = payload.get("password") or payload.get("ssh_password")
        if payload.get("tunnel_enabled"):
            if payload.get("tunnel1_host") and "tunnel1_enabled" not in payload:
                payload["tunnel1_enabled"] = 1
            if payload.get("tunnel2_host") and "tunnel2_enabled" not in payload:
                payload["tunnel2_enabled"] = 1

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
        for field in ("ssh_enabled", "telnet_enabled", "snmp_v1_enabled", "snmp_v2c_enabled", "snmp_v3_enabled", "tunnel_enabled", "tunnel1_enabled", "tunnel2_enabled"):
            if field not in payload:
                continue
            payload[field] = self._parse_bool(payload[field])
        self._normalize_snmpv3_fields(payload)
        if not payload["ssh_enabled"] and not payload["telnet_enabled"]:
            raise ValueError("At least one of SSH or Telnet must be enabled")
        for field in ("port", "ssh_port", "telnet_port", "snmp_port", "https_port", "tunnel1_port", "tunnel2_port"):
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
        if headers == TEMPLATE_FIELDS:
            return "template"
        raise ValueError("当前版本使用全新设备模板，请下载最新模板后重新填写。")

    @staticmethod
    def _map_row(headers: list[str], values: list[object], mode: str) -> dict[str, object | None]:
        result: dict[str, object | None] = {}
        field_map = TEMPLATE_FIELD_MAP
        for index, header in enumerate(headers):
            field = field_map[header]
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
