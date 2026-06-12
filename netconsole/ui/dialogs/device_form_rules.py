from __future__ import annotations


def to_bool_int(value: object) -> int:
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int):
        return 1 if value else 0
    text = str(value or "").strip().lower()
    return 1 if text in {"1", "true", "yes", "y", "是", "启用"} else 0


def validate_device_form_data(data: dict[str, object | None]) -> str | None:
    name = str(data.get("name") or "").strip()
    ip_address = str(data.get("ip_address") or "").strip()
    ssh_enabled = to_bool_int(data.get("ssh_enabled"))
    telnet_enabled = to_bool_int(data.get("telnet_enabled"))

    if not name:
        return "validation.name_required"
    if not ip_address:
        return "validation.host_required"
    if not ssh_enabled and not telnet_enabled:
        return "validation.connection_required"
    try:
        if ssh_enabled:
            int(data.get("ssh_port") or 0)
        if telnet_enabled:
            int(data.get("telnet_port") or 0)
    except (TypeError, ValueError):
        return "validation.port_invalid"
    return None
