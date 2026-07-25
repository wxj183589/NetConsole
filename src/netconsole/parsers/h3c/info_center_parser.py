from __future__ import annotations

import re
from dataclasses import asdict, dataclass


_STATUS_RE = re.compile(
    r"^\s*(?P<label>information\s+center|console|monitor|log\s*host|log\s*buffer)\s*:\s*"
    r"(?P<value>enabled|disabled)\b",
    re.IGNORECASE | re.MULTILINE,
)
_HOST_RE = re.compile(
    r"^\s*(?P<ip>\d{1,3}(?:\.\d{1,3}){3})\s*,?\s*$"
    r"\s*^\s*port\s+number\s*:\s*(?P<port>\d+)\s*,?\s*"
    r"host\s+facility\s*:\s*(?P<facility>[A-Za-z0-9_.-]+)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_METRIC_PATTERNS = {
    "max_buffer_size": re.compile(r"\bmax\s+buffer\s+size\s+(?P<value>\d+)\b", re.IGNORECASE),
    "current_buffer_size": re.compile(r"\bcurrent\s+buffer\s+size\s+(?P<value>\d+)\b", re.IGNORECASE),
    "current_messages": re.compile(r"\bcurrent\s+messages\s+(?P<value>\d+)\b", re.IGNORECASE),
    "dropped_messages": re.compile(r"\bdropped\s+messages\s+(?P<value>\d+)\b", re.IGNORECASE),
    "overwritten_messages": re.compile(r"\boverwritten\s+messages\s+(?P<value>\d+)\b", re.IGNORECASE),
}
_TIMESTAMP_FORMAT_RE = re.compile(
    r"^\s*(?:log\s*host\s*)?timestamp\s+format\s*:\s*(?P<value>.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_TIMESTAMP_DESTINATION_RE = re.compile(
    r"^\s*(?P<label>log\s*host|other\s+output\s+destination)\s*:\s*(?P<value>.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass(frozen=True)
class InfoCenterLogHost:
    ip: str
    port: int
    facility: str = ""


@dataclass(frozen=True)
class InfoCenterRuntime:
    information_center_enabled: bool | None = None
    console_enabled: bool | None = None
    monitor_enabled: bool | None = None
    loghost_enabled: bool | None = None
    log_buffer_enabled: bool | None = None
    log_hosts: tuple[InfoCenterLogHost, ...] = ()
    max_buffer_size: int | None = None
    current_buffer_size: int | None = None
    current_messages: int | None = None
    dropped_messages: int | None = None
    overwritten_messages: int | None = None
    loghost_timestamp_format: str = ""
    other_output_timestamp_format: str = ""

    def as_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["log_hosts"] = [asdict(item) for item in self.log_hosts]
        return result


def parse_info_center_runtime(output: str) -> InfoCenterRuntime:
    """Parse the H3C/Comware ``display info-center`` runtime report.

    The command has minor label and whitespace differences across releases.  Missing
    fields remain ``None`` rather than being treated as disabled.
    """

    text = str(output or "")
    states: dict[str, bool | None] = {
        "information_center_enabled": None,
        "console_enabled": None,
        "monitor_enabled": None,
        "loghost_enabled": None,
        "log_buffer_enabled": None,
    }
    label_map = {
        "information center": "information_center_enabled",
        "console": "console_enabled",
        "monitor": "monitor_enabled",
        "log host": "loghost_enabled",
        "loghost": "loghost_enabled",
        "log buffer": "log_buffer_enabled",
        "logbuffer": "log_buffer_enabled",
    }
    for match in _STATUS_RE.finditer(text):
        key = label_map[" ".join(match.group("label").casefold().split())]
        states[key] = match.group("value").casefold() == "enabled"

    hosts = tuple(
        InfoCenterLogHost(
            ip=match.group("ip"),
            port=int(match.group("port")),
            facility=match.group("facility").casefold(),
        )
        for match in _HOST_RE.finditer(text)
    )
    metrics: dict[str, int | None] = {}
    for key, pattern in _METRIC_PATTERNS.items():
        match = pattern.search(text)
        metrics[key] = int(match.group("value")) if match else None
    timestamp_match = _TIMESTAMP_FORMAT_RE.search(text)
    timestamp_formats: dict[str, str] = {}
    for match in _TIMESTAMP_DESTINATION_RE.finditer(text):
        label = " ".join(match.group("label").casefold().split())
        timestamp_formats[label] = match.group("value").strip()
    return InfoCenterRuntime(
        **states,
        log_hosts=hosts,
        **metrics,
        loghost_timestamp_format=(
            timestamp_formats.get("log host")
            or (timestamp_match.group("value").strip() if timestamp_match else "")
        ),
        other_output_timestamp_format=timestamp_formats.get("other output destination", ""),
    )


__all__ = ["InfoCenterLogHost", "InfoCenterRuntime", "parse_info_center_runtime"]
