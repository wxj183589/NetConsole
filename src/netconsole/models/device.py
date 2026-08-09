from __future__ import annotations

from dataclasses import MISSING, dataclass, fields
from enum import StrEnum
from uuid import UUID, uuid4


class DeviceVendor(StrEnum):
    H3C = "H3C"
    ZTE = "ZTE"
    HUAWEI = "Huawei"
    RUIJIE = "Ruijie"
    CISCO = "Cisco"
    OTHER = "Other"


DEVICE_VENDORS = tuple(vendor.value for vendor in DeviceVendor)
DEVICE_VENDOR_LABELS = {
    DeviceVendor.H3C.value: "新华三 H3C",
    DeviceVendor.ZTE.value: "中兴 ZTE",
    DeviceVendor.HUAWEI.value: "华为 Huawei",
    DeviceVendor.RUIJIE.value: "锐捷 Ruijie",
    DeviceVendor.CISCO.value: "思科 Cisco",
    DeviceVendor.OTHER.value: "其他",
}
_DEVICE_VENDOR_ALIASES = {
    "h3c": "h3c",
    "新华三": "h3c",
    "zte": "zte",
    "中兴": "zte",
    "中兴通讯": "zte",
    "huawei": "huawei",
    "华为": "huawei",
    "mexon": "mexon",
    "兆越": "mexon",
    "ruijie": "ruijie",
    "锐捷": "ruijie",
    "cisco": "cisco",
    "思科": "cisco",
    "other": "other",
    "其他": "other",
}
DEVICE_TYPES = ("AC", "SW", "FW", "Route", "Cloud-AP", "FAT-AP", "MR", "Other")


class ProjectPhase(StrEnum):
    PHASE_1 = "phase_1"
    PHASE_2 = "phase_2"
    PHASE_3 = "phase_3"
    OTHER = "other"
    UNSPECIFIED = "unspecified"


class WorkScopeStatus(StrEnum):
    INCLUDED = "included"
    EXCLUDED = "excluded"


PROJECT_PHASE_LABELS = {
    ProjectPhase.PHASE_1.value: "一期",
    ProjectPhase.PHASE_2.value: "二期",
    ProjectPhase.PHASE_3.value: "三期",
    ProjectPhase.OTHER.value: "其他",
    ProjectPhase.UNSPECIFIED.value: "未指定",
}
WORK_SCOPE_STATUS_LABELS = {
    WorkScopeStatus.INCLUDED.value: "参与当前调试",
    WorkScopeStatus.EXCLUDED.value: "暂不参与",
}
LEGACY_OPERATION_STATUS_LABELS = {
    "in_service": "在用",
    "not_integrated": "未并网",
    "commissioning": "调试中",
    "suspended": "暂停使用",
    "retired": "已退役",
}
LEGACY_OPERATION_STATUS_TO_WORK_SCOPE = {
    "in_service": WorkScopeStatus.INCLUDED.value,
    "not_integrated": WorkScopeStatus.EXCLUDED.value,
    "commissioning": WorkScopeStatus.EXCLUDED.value,
    "suspended": WorkScopeStatus.EXCLUDED.value,
    "retired": WorkScopeStatus.EXCLUDED.value,
}


def _normalize_enum_value(
    value: object, enum_type: type[StrEnum], labels: dict[str, str], field_label: str
) -> str:
    text = str(value or "").strip()
    aliases = {member.value.casefold(): member.value for member in enum_type}
    aliases.update({label: value for value, label in labels.items()})
    normalized = aliases.get(text.casefold())
    if normalized is None:
        raise ValueError(f"不支持的{field_label}：{text or '空值'}")
    return normalized


def normalize_project_phase(value: object) -> str:
    return _normalize_enum_value(value, ProjectPhase, PROJECT_PHASE_LABELS, "建设阶段")


def normalize_work_scope_status(value: object) -> str:
    text = str(value or "").strip()
    aliases = {
        WorkScopeStatus.INCLUDED.value: WorkScopeStatus.INCLUDED.value,
        WorkScopeStatus.EXCLUDED.value: WorkScopeStatus.EXCLUDED.value,
        "参与当前调试": WorkScopeStatus.INCLUDED.value,
        "参与当前工作": WorkScopeStatus.INCLUDED.value,
        "暂不参与": WorkScopeStatus.EXCLUDED.value,
        "暂不参与当前工作": WorkScopeStatus.EXCLUDED.value,
    }
    normalized = aliases.get(text.casefold())
    if normalized is None:
        raise ValueError(f"不支持的当前工作状态：{text or '空值'}")
    return normalized


def legacy_operation_status_to_work_scope_status(value: object) -> str:
    text = str(value or "").strip()
    aliases = {
        stable.casefold(): stable
        for stable in LEGACY_OPERATION_STATUS_TO_WORK_SCOPE
    }
    aliases.update(
        {label.casefold(): stable for stable, label in LEGACY_OPERATION_STATUS_LABELS.items()}
    )
    legacy_status = aliases.get(text.casefold())
    if legacy_status is None:
        raise ValueError(f"不支持的旧投运状态：{text or '空值'}")
    return LEGACY_OPERATION_STATUS_TO_WORK_SCOPE[legacy_status]


def is_device_eligible_for_automatic_collection(device: "Device") -> bool:
    return device.work_scope_status == WorkScopeStatus.INCLUDED.value


def normalize_device_vendor(value: object) -> str:
    """Legacy canonical form retained for existing callers."""

    text = normalize_device_vendor_text(value)
    normalized = _DEVICE_VENDOR_ALIASES.get(text.casefold())
    if normalized is None:
        raise ValueError(f"不支持的设备厂商：{text}")
    return {
        "h3c": DeviceVendor.H3C.value,
        "zte": DeviceVendor.ZTE.value,
        "huawei": DeviceVendor.HUAWEI.value,
        "ruijie": DeviceVendor.RUIJIE.value,
        "cisco": DeviceVendor.CISCO.value,
        "other": DeviceVendor.OTHER.value,
    }[normalized]


def normalize_device_vendor_text(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("设备厂商不能为空")
    if len(text) > 40:
        raise ValueError("设备厂商长度不能超过 40 个字符")
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise ValueError("设备厂商不能包含控制字符")
    return text


def normalize_device_vendor_key(value: object) -> str:
    """Return the stable key used exclusively for driver matching.

    ``device_vendor`` remains the user supplied value so imports and exports do
    not lose spelling or language. Unknown values deliberately resolve to the
    non-driver key ``unknown``; callers must never select a fallback driver.
    """

    text = normalize_device_vendor_text(value)
    return _DEVICE_VENDOR_ALIASES.get(text.casefold(), "unknown")


def validate_device_vendor_type(vendor: object, device_type: object) -> tuple[str, str]:
    normalized_vendor = normalize_device_vendor_text(vendor)
    normalized_type = str(device_type or "").strip()
    if normalized_type not in DEVICE_TYPES:
        raise ValueError(f"不支持的设备类型：{normalized_type or '空值'}")
    return normalized_vendor, normalized_type


@dataclass(init=False)
class Device:
    id: int | None = None
    device_uuid: str | None = None
    name: str = ""
    system_name: str | None = None
    mac_address: str | None = None
    station: str | None = None
    station_id: str = ""
    location: str | None = None
    group_id: int | None = None
    device_vendor: str = "H3C"
    device_type: str | None = "SW"
    project_phase: str = ProjectPhase.UNSPECIFIED.value
    work_scope_status: str = WorkScopeStatus.INCLUDED.value
    work_scope_reason: str | None = None
    work_scope_updated_at: str | None = None
    work_scope_updated_by: str | None = None
    primary_address: str = ""
    normalized_primary_address: str | None = None
    backup_address: str | None = None
    protocol: str | None = None
    port: int | None = 22
    username: str | None = None
    password: str | None = None
    snmp_enabled: int = 1
    ssh_enabled: int = 1
    ssh_port: int = 22
    telnet_enabled: int = 0
    telnet_port: int = 23
    ssh_username: str | None = None
    ssh_password: str | None = None
    telnet_username: str | None = None
    telnet_password: str | None = None
    snmp_v1_enabled: int = 0
    snmp_v2c_enabled: int = 1
    snmp_port: int | None = 161
    snmp_ro_community: str | None = None
    snmp_timeout_ms: int | None = 2000
    snmp_retries: int | None = 1
    https_port: int | None = None
    tunnel_enabled: int = 0
    tunnel1_enabled: int = 0
    tunnel1_host: str | None = None
    tunnel1_port: int | None = 22
    tunnel1_username: str | None = None
    tunnel1_password: str | None = None
    tunnel1_local_port_mode: str | None = "auto"
    tunnel1_local_port: int | None = None
    tunnel2_enabled: int = 0
    tunnel2_host: str | None = None
    tunnel2_port: int | None = 22
    tunnel2_username: str | None = None
    tunnel2_password: str | None = None
    tunnel2_local_port_mode: str | None = "auto"
    tunnel2_local_port: int | None = None
    remark: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def __init__(self, **kwargs):
        if "primary_address" not in kwargs and "ip_address" in kwargs:
            kwargs["primary_address"] = kwargs.pop("ip_address")
        if "system_name" not in kwargs and "sysname" in kwargs:
            kwargs["system_name"] = kwargs.pop("sysname")
        if "username" not in kwargs:
            kwargs["username"] = kwargs.get("ssh_username") or kwargs.get("telnet_username")
        if "password" not in kwargs:
            kwargs["password"] = kwargs.get("ssh_password") or kwargs.get("telnet_password")
        if "port" not in kwargs:
            kwargs["port"] = kwargs.get("ssh_port") or kwargs.get("telnet_port") or 22
        if kwargs.get("device_type") == "FIT-AP":
            kwargs["device_type"] = "Cloud-AP"
        if "device_vendor" in kwargs:
            kwargs["device_vendor"] = normalize_device_vendor_text(kwargs["device_vendor"])
        if "project_phase" in kwargs:
            kwargs["project_phase"] = normalize_project_phase(kwargs["project_phase"])
        if "work_scope_status" in kwargs:
            kwargs["work_scope_status"] = normalize_work_scope_status(
                kwargs["work_scope_status"]
            )
        field_names = set(self.field_names())
        unknown = set(kwargs) - field_names
        if unknown:
            raise TypeError(f"Unexpected Device fields: {', '.join(sorted(unknown))}")
        for field in fields(self):
            if field.name in kwargs:
                setattr(self, field.name, kwargs[field.name])
            elif field.default is not MISSING:
                setattr(self, field.name, field.default)
            elif field.default_factory is not MISSING:
                setattr(self, field.name, field.default_factory())
            else:
                setattr(self, field.name, None)

    @classmethod
    def field_names(cls) -> list[str]:
        return [field.name for field in fields(cls)]

    @classmethod
    def data_field_names(cls) -> list[str]:
        return [name for name in cls.field_names() if name not in {"id", "created_at", "updated_at"}]

    @staticmethod
    def new_uuid() -> str:
        return str(uuid4())

    @staticmethod
    def is_valid_uuid(value: str | None) -> bool:
        if not value:
            return False
        try:
            parsed = UUID(value, version=4)
        except (TypeError, ValueError):
            return False
        return str(parsed) == value.lower()

    def ensure_device_uuid(self) -> None:
        if not self.device_uuid:
            self.device_uuid = self.new_uuid()
        if not self.is_valid_uuid(self.device_uuid):
            raise ValueError(f"Invalid device_uuid: {self.device_uuid}")

    @classmethod
    def from_mapping(cls, data: dict[str, object]) -> "Device":
        normalized = dict(data)
        if "work_scope_status" not in normalized and "operation_status" in normalized:
            normalized["work_scope_status"] = (
                legacy_operation_status_to_work_scope_status(
                    normalized.get("operation_status")
                )
            )
        for current, legacy in (
            ("work_scope_reason", "operation_status_reason"),
            ("work_scope_updated_at", "operation_status_updated_at"),
            ("work_scope_updated_by", "operation_status_updated_by"),
        ):
            if current not in normalized and legacy in normalized:
                normalized[current] = normalized.get(legacy)
        if "primary_address" not in normalized and "ip_address" in normalized:
            normalized["primary_address"] = normalized.get("ip_address")
        if "system_name" not in normalized and "sysname" in normalized:
            normalized["system_name"] = normalized.get("sysname")
        if "username" not in normalized:
            normalized["username"] = normalized.get("ssh_username") or normalized.get("telnet_username")
        if "password" not in normalized:
            normalized["password"] = normalized.get("ssh_password") or normalized.get("telnet_password")
        values = {name: normalized.get(name) for name in cls.field_names() if name in normalized}
        return cls(**values)  # type: ignore[arg-type]

    def to_record(self) -> dict[str, object | None]:
        return {name: getattr(self, name) for name in self.field_names()}

    @property
    def vendor_key(self) -> str:
        return normalize_device_vendor_key(self.device_vendor)

    @property
    def ip_address(self) -> str:
        return self.primary_address

    @ip_address.setter
    def ip_address(self, value: str) -> None:
        self.primary_address = value

    @property
    def sysname(self) -> str | None:
        return self.system_name

    @sysname.setter
    def sysname(self, value: str | None) -> None:
        self.system_name = value
