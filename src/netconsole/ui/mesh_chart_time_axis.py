from __future__ import annotations

from datetime import datetime

from matplotlib import dates as mdates
from matplotlib.ticker import FuncFormatter

from netconsole.core.i18n import I18n
from netconsole.ui.mesh_chart_font import apply_cjk_font


def configure_mesh_time_axis(axis, visible_start_time: datetime | None, visible_end_time: datetime | None, i18n: I18n) -> None:
    axis.xaxis_date()
    axis.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=9, interval_multiples=False))
    axis.xaxis.set_major_formatter(FuncFormatter(lambda value, _pos: _format_tick(value, visible_start_time, visible_end_time)))
    axis.xaxis.get_offset_text().set_visible(False)
    axis.set_xlabel(_axis_label(visible_start_time, visible_end_time, i18n))
    axis.figure.autofmt_xdate(rotation=0, ha="center")
    apply_cjk_font(axis)


def full_sample_time_label(sample_time: str | datetime | None) -> str:
    if sample_time is None:
        return "-"
    try:
        parsed = sample_time if isinstance(sample_time, datetime) else datetime.fromisoformat(str(sample_time))
    except ValueError:
        return str(sample_time)
    return parsed.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _format_tick(value: float, start: datetime | None, end: datetime | None) -> str:
    try:
        tick = mdates.num2date(value, tz=None).replace(tzinfo=None)
    except (OverflowError, ValueError):
        return ""
    if start is None or end is None:
        return tick.strftime("%H:%M:%S")
    span = abs((end - start).total_seconds())
    has_subsecond = start.microsecond or end.microsecond
    if start.year != end.year:
        return tick.strftime("%Y-%m-%d %H:%M")
    if start.date() != end.date():
        return tick.strftime("%m-%d %H:%M:%S")
    if span <= 10 or has_subsecond:
        return tick.strftime("%H:%M:%S.%f")[:-3]
    return tick.strftime("%H:%M:%S")


def _axis_label(start: datetime | None, end: datetime | None, i18n: I18n) -> str:
    base = i18n.t("mesh_analysis.sample_time")
    if start is not None and end is not None and start.date() == end.date() and start.year == end.year:
        return f"{base} ({start:%Y-%m-%d})"
    return base
