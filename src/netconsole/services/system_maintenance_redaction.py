from __future__ import annotations

import ipaddress
import re

from netconsole.services.job_center.web_export_event_safety import redact_web_task_text


_IPV4_RE = re.compile(r"(?<![0-9.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9.])")


def redact_system_maintenance_text(value: object) -> str:
    text = redact_web_task_text(value)

    def replace(match: re.Match[str]) -> str:
        try:
            address = ipaddress.ip_address(match.group(0))
        except ValueError:
            return match.group(0)
        return "<redacted-ip>" if address.is_private else match.group(0)

    return _IPV4_RE.sub(replace, text)


__all__ = ["redact_system_maintenance_text"]
