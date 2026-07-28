from __future__ import annotations

from typing import Mapping

from netconsole.models.device import Device


class DeviceConnectionPreflightError(ValueError):
    def __init__(self, code: str, message: str, details: dict[str, object]) -> None:
        self.code = code
        self.message = message
        self.details = dict(details)
        super().__init__(message)

    def __str__(self) -> str:
        return self.message


def validate_device_connection_preflight(
    device: Device,
    protocol: str,
    *,
    credential_sources: Mapping[str, str] | None = None,
) -> None:
    selected = str(protocol or "").strip().upper()
    details = _base_details(device, selected)
    if selected not in {"SSH", "TELNET", "SNMP"}:
        _raise("DEVICE_TYPE_MISMATCH", "不支持的连接测试协议。", details)
    if not str(device.primary_address or device.backup_address or "").strip():
        _raise("CREDENTIAL_MISSING", "请先填写主用地址或备用地址。", details)
    if not str(device.device_type or "").strip():
        _raise(
            "DEVICE_TYPE_MISMATCH",
            "请先选择正确的设备类型后再测试连接。",
            details,
        )

    port = _protocol_port(device, selected)
    if not 1 <= port <= 65535:
        _raise(
            "TCP_UNREACHABLE",
            f"{selected} 端口无效，请填写 1 到 65535 之间的端口。",
            {**details, "port": port},
        )

    secret_field = _protocol_secret_field(selected)
    if selected == "SSH" and not str(device.ssh_username or "").strip():
        _raise_missing(details, selected, "ssh_username", "请先录入 SSH 用户名和密码。")
    if selected == "TELNET" and not str(device.telnet_username or "").strip():
        _raise_missing(
            details,
            selected,
            "telnet_username",
            "请先录入 Telnet 用户名和密码。",
        )

    _require_secret(
        device,
        selected,
        secret_field,
        details,
        credential_sources=credential_sources,
    )
    if selected in {"SSH", "TELNET"}:
        for prefix, label in (("tunnel1", "第一跳"), ("tunnel2", "第二跳")):
            if not bool(getattr(device, f"{prefix}_enabled")):
                continue
            if not str(getattr(device, f"{prefix}_host") or "").strip():
                _raise_missing(
                    details,
                    selected,
                    f"{prefix}_host",
                    f"请先录入 SSH 隧道{label}主机。",
                )
            if not str(getattr(device, f"{prefix}_username") or "").strip():
                _raise_missing(
                    details,
                    selected,
                    f"{prefix}_username",
                    f"请先录入 SSH 隧道{label}用户名和密码。",
                )
            _require_secret(
                device,
                selected,
                f"{prefix}_password",
                details,
                credential_sources=credential_sources,
                label=f"SSH 隧道{label}",
            )


def credential_status_message(status: str, error_code: str = "") -> str:
    if status == "needs_reentry" or error_code == "CREDENTIAL_REENTRY_REQUIRED":
        return "该设备来自脱敏包或旧无凭据包，请重新录入凭据后再测试连接。"
    if status == "missing":
        return "设备连接凭据尚未配置。"
    if status == "key_file_missing":
        return "SSH 密钥文件不存在，请重新选择。"
    return ""


def _require_secret(
    device: Device,
    protocol: str,
    field: str,
    details: dict[str, object],
    *,
    credential_sources: Mapping[str, str] | None,
    label: str = "",
) -> None:
    source = str((credential_sources or {}).get(field) or "")
    states = getattr(device, "credential_field_statuses", {})
    status = str(states.get(field) or "") if isinstance(states, dict) else ""
    if source == "needs_reentry" or status == "needs_reentry":
        _raise(
            "CREDENTIAL_REENTRY_REQUIRED",
            "该设备来自脱敏包或旧无凭据包，缺少可用凭据。请重新录入后再测试连接。",
            {
                **details,
                "field": field,
                "credential_status": "needs_reentry",
                "suggested_action": "编辑设备并重新录入连接凭据",
            },
        )
    has_secret = source in {"ephemeral", "saved_device"} or bool(
        getattr(device, field, None)
    )
    if source == "none" or not has_secret:
        name = label or protocol
        if field == "snmp_ro_community":
            message = "请输入 SNMP 只读团体字；连接凭据未配置。"
        else:
            message = f"请输入 {name} 密码；连接凭据未配置。"
        _raise_missing(
            details,
            protocol,
            field,
            message,
        )


def _raise_missing(
    details: dict[str, object],
    protocol: str,
    field: str,
    message: str,
) -> None:
    _raise(
        "CREDENTIAL_MISSING",
        message,
        {
            **details,
            "protocol": protocol,
            "field": field,
            "credential_status": "missing",
            "suggested_action": "编辑设备并补全连接凭据",
        },
    )


def _raise(code: str, message: str, details: dict[str, object]) -> None:
    raise DeviceConnectionPreflightError(code, message, details)


def _base_details(device: Device, protocol: str) -> dict[str, object]:
    return {
        "device_uuid": str(device.device_uuid or ""),
        "device_name": str(device.name or ""),
        "protocol": protocol,
    }


def _protocol_port(device: Device, protocol: str) -> int:
    value = {
        "SSH": device.ssh_port,
        "TELNET": device.telnet_port,
        "SNMP": device.snmp_port,
    }.get(protocol)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _protocol_secret_field(protocol: str) -> str:
    return {
        "SSH": "ssh_password",
        "TELNET": "telnet_password",
        "SNMP": "snmp_ro_community",
    }[protocol]


__all__ = [
    "DeviceConnectionPreflightError",
    "credential_status_message",
    "validate_device_connection_preflight",
]
