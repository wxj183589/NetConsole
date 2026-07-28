from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


_DATE_RE = re.compile(r"\b(?P<month>\d{1,2})/(?P<day>\d{1,2})/(?P<year>\d{4})\b")
_TIME_RE = re.compile(r"\b(?P<hour>\d{1,2}):(?P<minute>\d{2}):(?P<second>\d{2})\b")
_ZONE_RE = re.compile(
    r"^\s*time\s+zone\s*:\s*(?P<name>.+?)\s+"
    r"(?P<direction>add|minus)\s+"
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2}):(?P<second>\d{2})\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_INLINE_OFFSET_RE = re.compile(r"(?P<sign>[+-])(?P<hour>\d{2}):(?P<minute>\d{2})\b")
_WEEKDAY_RE = re.compile(
    r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class H3cDeviceClock:
    timestamp: datetime
    timezone_name: str
    utc_offset_seconds: int
    raw: str


def parse_h3c_device_clock(output: str) -> H3cDeviceClock:
    """Parse ``display clock`` without falling back to the workstation clock."""

    text = str(output or "")
    date_match = _DATE_RE.search(text)
    time_match = _TIME_RE.search(text)
    if date_match is None or time_match is None:
        raise ValueError("display clock 未返回可解析的设备日期和时间")

    zone_match = _ZONE_RE.search(text)
    timezone_name = ""
    offset_seconds: int | None = None
    if zone_match is not None:
        timezone_name = zone_match.group("name").strip()
        offset_seconds = (
            int(zone_match.group("hour")) * 3600
            + int(zone_match.group("minute")) * 60
            + int(zone_match.group("second"))
        )
        if zone_match.group("direction").casefold() == "minus":
            offset_seconds *= -1
    else:
        inline_offset = _INLINE_OFFSET_RE.search(text)
        if inline_offset is not None:
            offset_seconds = (
                int(inline_offset.group("hour")) * 3600
                + int(inline_offset.group("minute")) * 60
            )
            if inline_offset.group("sign") == "-":
                offset_seconds *= -1
        first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
        before_weekday = _WEEKDAY_RE.split(first_line, maxsplit=1)[0]
        timezone_name = _TIME_RE.sub("", before_weekday).strip()

    if offset_seconds is None:
        raise ValueError("display clock 未返回可解析的设备 UTC 偏移")
    if abs(offset_seconds) > 24 * 3600:
        raise ValueError("display clock 返回的设备 UTC 偏移超出范围")

    timestamp = datetime(
        int(date_match.group("year")),
        int(date_match.group("month")),
        int(date_match.group("day")),
        int(time_match.group("hour")),
        int(time_match.group("minute")),
        int(time_match.group("second")),
        tzinfo=timezone(timedelta(seconds=offset_seconds)),
    )
    return H3cDeviceClock(
        timestamp=timestamp,
        timezone_name=timezone_name,
        utc_offset_seconds=offset_seconds,
        raw=text,
    )


__all__ = ["H3cDeviceClock", "parse_h3c_device_clock"]
