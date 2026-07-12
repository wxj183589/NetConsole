from __future__ import annotations

from datetime import datetime
from typing import Iterable

from netconsole.services.fping_legacy_parser import parse_fping_lines, parse_fping_summary


def parse_lines(lines: Iterable[str], session_started_at: datetime, default_target: str = "") -> list[dict[str, object]]:
    return parse_fping_lines(lines, session_started_at, default_target)


def parse_summary(text: str, target_ip: str = "") -> dict[str, object]:
    return parse_fping_summary(text, target_ip)
