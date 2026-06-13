from __future__ import annotations

from netconsole.models.device_credentials import format_auth_user, to_bool_int


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
