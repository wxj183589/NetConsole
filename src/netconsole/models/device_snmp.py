from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from netconsole.models.device import Device


@dataclass(frozen=True)
class DeviceSnmpProfile:
    """设备管理专用的 SNMP v1/v2c 只读连接参数。"""

    host: str
    version: str = "v2c"
    port: int = 161
    community_ro: str = "public"
    timeout_ms: int = 2000
    retries: int = 1

    def __post_init__(self) -> None:
        host = str(self.host or "").strip()
        if not host:
            raise ValueError("设备 SNMP 地址不能为空。")
        version = self.version.lower()
        if version == "v2":
            version = "v2c"
        if version not in {"v1", "v2c"}:
            raise ValueError("设备管理仅支持 SNMP v1 和 v2c。")
        if not 1 <= int(self.port) <= 65535:
            raise ValueError("设备 SNMP 端口必须在 1 到 65535 之间。")
        if not str(self.community_ro or ""):
            raise ValueError("设备 SNMP 只读团体字不能为空。")
        if not 100 <= int(self.timeout_ms) <= 60000:
            raise ValueError("设备 SNMP 超时必须在 100 到 60000 毫秒之间。")
        if not 0 <= int(self.retries) <= 10:
            raise ValueError("设备 SNMP 重试次数必须在 0 到 10 之间。")
        object.__setattr__(self, "host", host)
        object.__setattr__(self, "version", version)

    @classmethod
    def from_device(cls, device: Device) -> "DeviceSnmpProfile":
        if not device.snmp_enabled:
            raise ValueError("设备未启用 SNMP。")
        if device.snmp_v2c_enabled:
            version = "v2c"
        elif device.snmp_v1_enabled:
            version = "v1"
        else:
            raise ValueError("设备未启用 SNMP v1 或 v2c。")
        return cls(
            host=str(device.primary_address or ""),
            version=version,
            port=int(device.snmp_port or 161),
            community_ro=str(device.snmp_ro_community or "public"),
            timeout_ms=int(device.snmp_timeout_ms or 2000),
            retries=int(device.snmp_retries or 0),
        )


@dataclass(frozen=True)
class DeviceSnmpVarBind:
    oid: str
    value: Any
    value_type: str = ""
    status: str = "success"
    error_message: str = ""


@dataclass(frozen=True)
class DeviceSnmpQueryResult:
    rows: list[DeviceSnmpVarBind] = field(default_factory=list)
    status: str = "success"
    error_message: str = ""
    elapsed_ms: int = 0


@dataclass(frozen=True)
class DeviceSnmpProfileResult:
    device_name: str = ""
    vendor: str = ""
    device_type: str = ""
    model: str = ""
    system: str = ""
    system_version: str = ""
    os_family: str = ""
    os_major: str = ""
    release: str = ""
    release_number: str = ""
    release_patch: str = ""
    release_series: str = ""
    sys_name: str = ""
    sys_object_id: str = ""
    sys_descr: str = ""
    sys_up_time: str = ""
    serial_number: str = ""
    source: str = "SNMP"
    status: str = "success"
    latency_ms: int = 0
    interface_count: int = 0
    error_message: str = ""
