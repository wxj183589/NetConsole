from __future__ import annotations

from dataclasses import MISSING, dataclass, fields
from uuid import UUID, uuid4


DEVICE_VENDORS = ("H3C", "Huawei", "Ruijie", "Cisco", "Other")
DEVICE_TYPES = ("AC", "SW", "FW", "Route", "Cloud-AP", "FAT-AP", "MR", "Other")


@dataclass(init=False)
class Device:
    id: int | None = None
    device_uuid: str | None = None
    name: str = ""
    system_name: str | None = None
    mac_address: str | None = None
    station: str | None = None
    location: str | None = None
    group_id: int | None = None
    device_vendor: str = "H3C"
    device_type: str | None = "SW"
    primary_address: str = ""
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
