from __future__ import annotations


def to_bool_int(value: object) -> int:
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int):
        return 1 if value else 0
    text = str(value or "").strip().lower()
    return 1 if text in {"1", "true", "yes", "y", "是", "启用"} else 0


def format_auth_user(ssh_username: object | None, telnet_username: object | None, empty: str = "-") -> str:
    ssh_text = str(ssh_username or "").strip() or empty
    telnet_text = str(telnet_username or "").strip() or empty
    return f"SSH:{ssh_text} / Telnet:{telnet_text}"
