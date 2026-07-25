from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class ScheduleWindow:
    active: bool
    run_date: str
    current_start: datetime | None
    current_end: datetime | None
    next_start: datetime
    next_end: datetime


def resolve_timezone(value: str) -> tzinfo:
    name = str(value or "system").strip()
    if name.casefold() == "system":
        return datetime.now().astimezone().tzinfo or ZoneInfo("UTC")
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("时区名称无效") from exc


def schedule_window(
    now: datetime,
    schedule_start_time: str,
    schedule_end_time: str,
    timezone: str,
) -> ScheduleWindow:
    zone = resolve_timezone(timezone)
    local_now = now.astimezone(zone) if now.tzinfo else now.replace(tzinfo=zone)
    start_clock = _parse_clock(schedule_start_time)
    end_clock = _parse_clock(schedule_end_time)
    if start_clock == end_clock:
        raise ValueError("开始时间和结束时间不能相同")

    today = local_now.date()
    start_today = datetime.combine(today, start_clock, zone)
    end_today = datetime.combine(today, end_clock, zone)
    crosses_midnight = start_clock > end_clock

    if not crosses_midnight:
        active = start_today <= local_now < end_today
        if active:
            current_start, current_end = start_today, end_today
            next_start = start_today + timedelta(days=1)
            next_end = end_today
            run_date = today.isoformat()
        elif local_now < start_today:
            current_start = current_end = None
            next_start, next_end = start_today, end_today
            run_date = today.isoformat()
        else:
            current_start = current_end = None
            next_start = start_today + timedelta(days=1)
            next_end = end_today + timedelta(days=1)
            run_date = next_start.date().isoformat()
    else:
        if local_now >= start_today:
            current_start = start_today
            current_end = end_today + timedelta(days=1)
            active = True
        elif local_now < end_today:
            current_start = start_today - timedelta(days=1)
            current_end = end_today
            active = True
        else:
            current_start = current_end = None
            active = False
        if active:
            run_date = current_start.date().isoformat()
            next_start = current_start + timedelta(days=1)
            next_end = current_end
        else:
            run_date = today.isoformat()
            next_start = start_today
            next_end = end_today + timedelta(days=1)

    return ScheduleWindow(
        active=active,
        run_date=run_date,
        current_start=current_start,
        current_end=current_end,
        next_start=next_start,
        next_end=next_end,
    )


def _parse_clock(value: str) -> time:
    try:
        return datetime.strptime(str(value), "%H:%M").time()
    except ValueError as exc:
        raise ValueError("时间必须使用 HH:MM 格式") from exc


__all__ = ["ScheduleWindow", "resolve_timezone", "schedule_window"]
