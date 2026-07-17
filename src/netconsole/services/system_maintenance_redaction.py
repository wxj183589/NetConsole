from __future__ import annotations

import ipaddress
import re

from netconsole.services.job_center.web_export_event_safety import redact_web_task_text


_IPV4_RE = re.compile(r"(?<![0-9.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9.])")
_IPV6_RE = re.compile(
    r"(?ix)(?<![0-9a-f:])(?:[0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}(?![0-9a-f:])"
)
_SECRET_KEY = (
    r"(?:snmpv3_auth_password|snmpv3_priv_password|ssh_password|telnet_password|"
    r"auth_password|priv_password|auth_secret|priv_secret|password|"
    r"secret|token|community|authorization|x-agent-token|auth|priv)"
)
_QUOTED_SECRET_RE = re.compile(
    rf"(?is)(?P<prefix>(?<![A-Za-z0-9_])[\"']?{_SECRET_KEY}[\"']?\s*[:=]\s*)"
    r"(?P<quote>[\"'])(?:\\.|(?!(?P=quote)).)*?(?P=quote)"
)
_UNQUOTED_SECRET_RE = re.compile(
    rf"(?i)(?P<prefix>\b{_SECRET_KEY}\b\s*[:=]\s*(?:bearer\s+)?)"
    r"[^\s,;}}\]]+"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")


def redact_system_maintenance_text(value: object) -> str:
    text = redact_web_task_text(value)
    text = _QUOTED_SECRET_RE.sub(
        lambda match: f"{match.group('prefix')}{match.group('quote')}<redacted>{match.group('quote')}",
        text,
    )
    text = _UNQUOTED_SECRET_RE.sub(lambda match: f"{match.group('prefix')}<redacted>", text)
    text = _BEARER_RE.sub("Bearer <redacted>", text)
    text = _IPV4_RE.sub(_redact_ip, text)
    return _IPV6_RE.sub(_redact_ip, text)


def _redact_ip(match: re.Match[str]) -> str:
    try:
        address = ipaddress.ip_address(match.group(0))
    except ValueError:
        return match.group(0)
    if address.is_private or address.is_loopback or address.is_link_local:
        return "<redacted-ip>"
    return match.group(0)


__all__ = ["redact_system_maintenance_text"]
