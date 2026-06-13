from __future__ import annotations

from dataclasses import dataclass, fields
from uuid import UUID, uuid4


DEVICE_VENDORS = ("H3C", "Huawei", "Ruijie", "Cisco", "Other")
DEVICE_TYPES = ("AC", "SW", "FW", "Route", "FIT-AP", "FAT-AP", "Other")


@dataclass
class Device:
    id: int | None = None
    device_uuid: str | None = None
    name: str = ""
    sysname: str | None = None
    station: str | None = None
    device_vendor: str = "H3C"
    device_type: str | None = "SW"
    ip_address: str = ""
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
    snmp_v3_enabled: int = 0
    snmp_port: int | None = 161
    snmp_ro_community: str | None = None
    snmp_rw_community: str | None = None
    snmpv3_security_level: str | None = None
    snmpv3_auth_protocol: str | None = None
    snmpv3_auth_password: str | None = None
    snmpv3_priv_protocol: str | None = None
    snmpv3_priv_password: str | None = None
    tags: str | None = None
    remark: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

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
        values = {name: data.get(name) for name in cls.field_names() if name in data}
        return cls(**values)  # type: ignore[arg-type]

    def to_record(self) -> dict[str, object | None]:
        return {name: getattr(self, name) for name in self.field_names()}
