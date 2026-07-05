from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from netconsole.models.device import Device


SNMP_STATUS_LABELS = {
    "success": "成功",
    "timeout": "超时",
    "auth_failed": "认证失败",
    "no_such_object": "OID 不存在",
    "no_such_instance": "实例不存在",
    "end_of_mib_view": "MIB 视图结束",
    "mib_not_loaded": "MIB 未加载",
    "decode_failed": "解码失败",
    "empty_table": "表为空",
    "cancelled": "已取消",
    "unsupported": "不支持",
    "library_unavailable": "SNMP 库不可用",
    "failed": "失败",
}


@dataclass(frozen=True)
class SnmpProfile:
    host: str
    version: str = "v2c"
    port: int = 161
    community_ro: str = "public"
    community_rw: str = ""
    username: str = ""
    security_level: str = "noAuthNoPriv"
    auth_protocol: str = "SHA"
    auth_key: str = ""
    priv_protocol: str = "AES128"
    priv_key: str = ""
    context_name: str = ""
    timeout_ms: int = 2000
    retries: int = 1

    @classmethod
    def from_device(cls, device: Device) -> "SnmpProfile":
        version = str(device.snmp_version or "").lower()
        if not version:
            if getattr(device, "snmp_v3_enabled", 0):
                version = "v3"
            elif getattr(device, "snmp_v1_enabled", 0):
                version = "v1"
            else:
                version = "v2c"
        return cls(
            host=str(device.primary_address or ""),
            version=version,
            port=int(device.snmp_port or 161),
            community_ro=str(device.snmp_ro_community or "public"),
            community_rw=str(device.snmp_rw_community or ""),
            username=str(getattr(device, "snmpv3_username", "") or ""),
            security_level=str(device.snmpv3_security_level or "noAuthNoPriv"),
            auth_protocol=str(device.snmpv3_auth_protocol or "SHA"),
            auth_key=str(device.snmpv3_auth_password or ""),
            priv_protocol=str(device.snmpv3_priv_protocol or "AES128"),
            priv_key=str(device.snmpv3_priv_password or ""),
            context_name=str(getattr(device, "snmp_context_name", "") or ""),
            timeout_ms=int(getattr(device, "snmp_timeout_ms", None) or 2000),
            retries=int(getattr(device, "snmp_retries", None) or 1),
        )


@dataclass(frozen=True)
class SnmpVarBind:
    oid: str
    value: Any
    value_type: str = ""
    name: str = ""
    decoded_value: str = ""
    instance: str = ""
    latency_ms: int = 0
    status: str = "success"
    error_message: str = ""


@dataclass(frozen=True)
class SnmpQueryRequest:
    profile: SnmpProfile
    method: str
    oid: str
    max_repetitions: int = 10
    max_rows: int = 200
    decode: bool = True
    save_history: bool = True
    device_id: str = ""
    device_name: str = ""
    started_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


@dataclass(frozen=True)
class SnmpQueryResult:
    request: SnmpQueryRequest
    rows: list[SnmpVarBind] = field(default_factory=list)
    status: str = "success"
    error_message: str = ""
    elapsed_ms: int = 0


@dataclass(frozen=True)
class SnmpSetRequest:
    profile: SnmpProfile
    oid: str
    data_type: str
    value: str
    device_id: str = ""
    device_name: str = ""
    object_name: str = ""
    module_name: str = ""
    access: str = ""
    old_value: str = ""
    started_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


@dataclass(frozen=True)
class SnmpSetResult:
    request: SnmpSetRequest
    old_value: str = ""
    new_value: str = ""
    result_value: str = ""
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


@dataclass(frozen=True)
class DictionaryRecommendation:
    dictionary_set_id: int
    name: str
    score: int
    reasons: list[str]
    status: str = "recommended"


@dataclass(frozen=True)
class ProductReferenceRecommendation:
    reference_id: int
    reference_name: str
    score: int
    reasons: list[str]
    status: str = "recommended"
