from __future__ import annotations

from pathlib import Path

from netconsole.core.optical_severity_engine import display_optical_status
from netconsole.services.export.common_exporters import export_table_xlsx
from netconsole.services.fit_ap_link_info import lldp_source_label


OPTICAL_HISTORY_COLORS = {
    "normal": "#dcfce7",
    "warning": "#fef9c3",
    "alarm": "#fee2e2",
    "link_abnormal": "#ffe4e6",
    "no_light": "#e5e7eb",
    "skipped": "#f3f4f6",
}


def export_ap_history_xlsx(
    path: Path,
    rows: list[dict[str, object | None]],
    columns: tuple[tuple[str, str], ...],
    headers: list[str],
    color_field: str | None = None,
) -> None:
    prepared_rows: list[dict[str, object | None]] = []
    for row in rows:
        prepared = {
            field: history_display_value(row, field, color_field)
            for _key, field in columns
        }
        if color_field:
            prepared["__row_fill"] = OPTICAL_HISTORY_COLORS.get(str(row.get(color_field) or ""), "")
        prepared_rows.append(prepared)
    export_table_xlsx(
        Path(path),
        {
            "sheet_name": "AP History",
            "columns": [{"key": field, "title": headers[index] if index < len(headers) else field} for index, (_key, field) in enumerate(columns)],
            "rows": prepared_rows,
            "row_fill_field": "__row_fill",
        },
    )


def export_station_online_history_xlsx(path: Path, rows: list[dict[str, object | None]], columns: tuple[tuple[str, str], ...], headers: list[str]) -> None:
    export_table_xlsx(
        Path(path),
        {
            "sheet_name": "AP Online History",
            "columns": [{"key": field, "title": headers[index] if index < len(headers) else field} for index, (_key, field) in enumerate(columns)],
            "rows": [dict(row) for row in rows],
        },
    )


def export_interface_history_xlsx(path: Path, rows: list[dict[str, object | None]], columns: tuple[tuple[str, str], ...], headers: list[str]) -> None:
    export_table_xlsx(
        Path(path),
        {
            "sheet_name": "Interface History",
            "columns": [{"key": field, "title": headers[index] if index < len(headers) else field} for index, (_key, field) in enumerate(columns)],
            "rows": [dict(row) for row in rows],
        },
    )


def history_display_value(row: dict[str, object | None], field: str, color_field: str | None = None, language: str = "zh") -> str:
    if color_field and field == color_field:
        return display_optical_status(row.get(field), language)
    if field == "source":
        return lldp_source_label(row.get(field))
    if field == "is_changed":
        return "是" if str(row.get(field) or "") not in {"", "0"} else "否"
    if field == "conflict_flag":
        return "冲突" if str(row.get(field) or "") not in {"", "0"} else "正常"
    return str(row.get(field) or "")
