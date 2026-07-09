from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from netconsole.services.export.export_job import ExportJob

INLINE_ROW_LIMIT = 5000


@dataclass(frozen=True)
class ExportTaskSpec:
    task_type: str
    output_path: str
    payload: dict[str, Any] = field(default_factory=dict)
    title: str = ""
    open_dir_on_success: bool = False
    site_name: str = ""
    db_path: str = ""
    filters: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)

    def to_job(self, job_id: str | None = None) -> ExportJob:
        return ExportJob(
            job_id=job_id or uuid.uuid4().hex,
            job_type=self.task_type,
            site_name=self.site_name,
            output_path=self.output_path,
            db_path=self.db_path,
            params={
                "payload": self.payload,
                "title": self.title,
                "open_dir_on_success": self.open_dir_on_success,
            },
            filters=self.filters,
            context=self.context,
        )


def column_specs(columns: Iterable[tuple[str, str] | Mapping[str, Any]], headers: Iterable[str] | None = None) -> list[dict[str, Any]]:
    header_list = list(headers or [])
    result: list[dict[str, Any]] = []
    for index, column in enumerate(columns):
        if isinstance(column, Mapping):
            key = str(column.get("key") or column.get("field") or "")
            title = str(column.get("title") or column.get("header") or (header_list[index] if index < len(header_list) else key))
            result.append({"key": key, "title": title, "width": column.get("width"), "text": bool(column.get("text", True))})
            continue
        title_key, field = column
        result.append({"key": str(field), "title": header_list[index] if index < len(header_list) else str(title_key), "text": True})
    return result


def inline_rows_source(rows: Iterable[Mapping[str, Any]], *, limit: int = INLINE_ROW_LIMIT) -> dict[str, Any]:
    materialized = [dict(row) for row in rows]
    if len(materialized) > limit:
        raise ValueError(f"inline_rows 导出最多支持 {limit} 行，请改用 repository_query 数据源")
    return {"type": "inline_rows", "rows": materialized}


def repository_query_source(
    *,
    db_path: str | Path,
    repository: str,
    method: str,
    filters: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "type": "repository_query",
        "db_path": str(db_path),
        "repository": str(repository),
        "method": str(method),
        "filters": dict(filters or {}),
    }


def file_or_directory_source(
    paths: Iterable[str | Path],
    *,
    base_dir: str | Path | None = None,
    exclude_names: Iterable[str] | None = None,
) -> dict[str, Any]:
    source: dict[str, Any] = {
        "type": "file_or_directory",
        "paths": [str(path) for path in paths],
        "exclude_names": [str(name) for name in exclude_names or []],
    }
    if base_dir:
        source["base_dir"] = str(base_dir)
    return source


def table_xlsx_spec(
    output_path: str | Path,
    *,
    columns: Iterable[tuple[str, str] | Mapping[str, Any]],
    rows: Iterable[Mapping[str, Any]],
    headers: Iterable[str] | None = None,
    sheet_name: str = "Sheet1",
    title: str = "",
    row_fill_field: str = "",
    row_fill_colors: Mapping[str, str] | None = None,
    open_dir_on_success: bool = True,
) -> ExportTaskSpec:
    return ExportTaskSpec(
        task_type="table_xlsx",
        output_path=str(output_path),
        title=title,
        open_dir_on_success=open_dir_on_success,
        payload={
            "columns": column_specs(columns, headers),
            "source": inline_rows_source(rows),
            "sheet_name": sheet_name,
            "title": title,
            "auto_width": True,
            "freeze_header": True,
            "auto_filter": True,
            "row_fill_field": row_fill_field,
            "row_fill_colors": dict(row_fill_colors or {}),
        },
    )


def table_csv_spec(
    output_path: str | Path,
    *,
    columns: Iterable[tuple[str, str] | Mapping[str, Any]],
    rows: Iterable[Mapping[str, Any]],
    headers: Iterable[str] | None = None,
    title: str = "",
    open_dir_on_success: bool = True,
) -> ExportTaskSpec:
    return ExportTaskSpec(
        task_type="table_csv",
        output_path=str(output_path),
        title=title,
        open_dir_on_success=open_dir_on_success,
        payload={"columns": column_specs(columns, headers), "source": inline_rows_source(rows)},
    )


def markdown_text_spec(output_path: str | Path, *, text: str, title: str = "", open_dir_on_success: bool = True) -> ExportTaskSpec:
    return ExportTaskSpec(
        task_type="markdown_text",
        output_path=str(output_path),
        title=title,
        open_dir_on_success=open_dir_on_success,
        payload={"text": text},
    )


def zip_files_spec(
    output_path: str | Path,
    *,
    paths: Iterable[str | Path],
    base_dir: str | Path | None = None,
    exclude_names: Iterable[str] | None = None,
    title: str = "",
    open_dir_on_success: bool = True,
) -> ExportTaskSpec:
    return ExportTaskSpec(
        task_type="zip_files",
        output_path=str(output_path),
        title=title,
        open_dir_on_success=open_dir_on_success,
        payload={"source": file_or_directory_source(paths, base_dir=base_dir, exclude_names=exclude_names)},
    )


def config_snapshots_zip_spec(
    output_path: str | Path,
    *,
    db_path: str | Path,
    site_name: str,
    snapshot_entries: Iterable[Mapping[str, Any]],
    file_entries: Iterable[Mapping[str, Any]] | None = None,
    failures_text: str = "",
    title: str = "",
    open_dir_on_success: bool = True,
) -> ExportTaskSpec:
    return ExportTaskSpec(
        task_type="config_snapshots_zip",
        output_path=str(output_path),
        title=title,
        open_dir_on_success=open_dir_on_success,
        payload={
            "db_path": str(db_path),
            "site_name": site_name,
            "snapshot_entries": [dict(entry) for entry in snapshot_entries],
            "file_entries": [dict(entry) for entry in file_entries or []],
            "failures_text": failures_text,
        },
    )


def copy_file_spec(output_path: str | Path, *, source: str | Path, title: str = "", open_dir_on_success: bool = True) -> ExportTaskSpec:
    return ExportTaskSpec(
        task_type="copy_file",
        output_path=str(output_path),
        title=title,
        open_dir_on_success=open_dir_on_success,
        payload={"source": str(source)},
    )


def device_csv_spec(
    output_path: str | Path,
    *,
    db_path: str | Path,
    site_name: str = "",
    selected_devices: Iterable[Mapping[str, Any]] | None = None,
    filters: Mapping[str, Any] | None = None,
    title: str = "",
    open_dir_on_success: bool = True,
) -> ExportTaskSpec:
    payload: dict[str, Any] = {
        "db_path": str(db_path),
        "site_name": site_name,
        "filters": dict(filters or {}),
    }
    if selected_devices is not None:
        payload["devices"] = inline_rows_source(selected_devices)["rows"]
    else:
        payload["source"] = repository_query_source(
            db_path=db_path,
            repository="device_repository",
            method="list",
            filters=filters,
        )
    return ExportTaskSpec(
        task_type="device_csv",
        output_path=str(output_path),
        title=title,
        open_dir_on_success=open_dir_on_success,
        payload=payload,
    )


def device_template_csv_spec(output_path: str | Path, *, title: str = "", open_dir_on_success: bool = True) -> ExportTaskSpec:
    return ExportTaskSpec(
        task_type="device_template_csv",
        output_path=str(output_path),
        title=title,
        open_dir_on_success=open_dir_on_success,
    )


def securecrt_sessions_spec(
    output_dir: str | Path,
    *,
    devices: Iterable[Mapping[str, Any]],
    site_name: str,
    group_names: Mapping[int, str] | Mapping[str, str] | None = None,
    template_ini: str | Path | None = None,
    title: str = "",
    open_dir_on_success: bool = True,
) -> ExportTaskSpec:
    output_dir_path = Path(output_dir)
    return ExportTaskSpec(
        task_type="securecrt_sessions",
        output_path=str(output_dir_path / ".netconsole_securecrt_export.txt"),
        title=title,
        open_dir_on_success=open_dir_on_success,
        payload={
            "output_dir": str(output_dir_path),
            "devices": inline_rows_source(devices)["rows"],
            "site_name": site_name,
            "group_names": {str(key): value for key, value in dict(group_names or {}).items()},
            "template_ini": str(template_ini or ""),
        },
    )


def wifi_survey_csv_spec(
    output_path: str | Path,
    *,
    db_path: str | Path,
    session_id: int,
    session_name: str,
    fields: Iterable[str],
    title: str = "",
    open_dir_on_success: bool = True,
) -> ExportTaskSpec:
    return ExportTaskSpec(
        task_type="wifi_survey_csv",
        output_path=str(output_path),
        title=title,
        open_dir_on_success=open_dir_on_success,
        payload={
            "db_path": str(db_path),
            "session_id": int(session_id),
            "session_name": session_name,
            "fields": [str(field) for field in fields],
        },
    )


def snmp_query_result_spec(
    output_path: str | Path,
    *,
    result: Mapping[str, Any],
    title: str = "",
    open_dir_on_success: bool = True,
) -> ExportTaskSpec:
    return ExportTaskSpec(
        task_type="snmp_query_result",
        output_path=str(output_path),
        title=title,
        open_dir_on_success=open_dir_on_success,
        payload={"result": dict(result)},
    )


def mib_product_compare_spec(
    output_path: str | Path,
    *,
    db_path: str | Path,
    left_reference_id: int,
    right_reference_id: int,
    title: str = "",
    open_dir_on_success: bool = True,
) -> ExportTaskSpec:
    return ExportTaskSpec(
        task_type="mib_product_compare",
        output_path=str(output_path),
        title=title,
        open_dir_on_success=open_dir_on_success,
        payload={
            "db_path": str(db_path),
            "left_reference_id": int(left_reference_id),
            "right_reference_id": int(right_reference_id),
        },
    )


def fit_ap_csv_spec(
    output_path: str | Path,
    *,
    db_path: str | Path,
    rows: Iterable[Mapping[str, Any]],
    title: str = "",
    open_dir_on_success: bool = True,
) -> ExportTaskSpec:
    return ExportTaskSpec(
        task_type="fit_ap_csv",
        output_path=str(output_path),
        title=title,
        open_dir_on_success=open_dir_on_success,
        payload={"db_path": str(db_path), "rows": inline_rows_source(rows)["rows"]},
    )


def fit_ap_extension_xlsx_spec(
    output_path: str | Path,
    *,
    db_path: str | Path,
    rows: Iterable[Mapping[str, Any]],
    title: str = "",
    open_dir_on_success: bool = True,
) -> ExportTaskSpec:
    return ExportTaskSpec(
        task_type="fit_ap_extension_xlsx",
        output_path=str(output_path),
        title=title,
        open_dir_on_success=open_dir_on_success,
        payload={"db_path": str(db_path), "rows": inline_rows_source(rows)["rows"]},
    )


def fit_ap_extension_template_xlsx_spec(
    output_path: str | Path,
    *,
    db_path: str | Path,
    rows: Iterable[Mapping[str, Any]],
    ap_entities: Iterable[Mapping[str, Any]],
    title: str = "",
    open_dir_on_success: bool = True,
) -> ExportTaskSpec:
    return ExportTaskSpec(
        task_type="fit_ap_extension_template_xlsx",
        output_path=str(output_path),
        title=title,
        open_dir_on_success=open_dir_on_success,
        payload={
            "db_path": str(db_path),
            "rows": inline_rows_source(rows)["rows"],
            "ap_entities": inline_rows_source(ap_entities)["rows"],
        },
    )


def ap_online_overview_xlsx_spec(
    output_path: str | Path,
    *,
    rows: Iterable[Mapping[str, Any]],
    headers: Iterable[str],
    offline_ap_stats: Mapping[str, Any],
    offline_ap_ledger_rows: Iterable[Mapping[str, Any]],
    offline_ap_stats_headers: Iterable[str],
    offline_ap_ledger_headers: Iterable[str],
    title: str = "",
    open_dir_on_success: bool = True,
) -> ExportTaskSpec:
    return ExportTaskSpec(
        task_type="ap_online_overview_xlsx",
        output_path=str(output_path),
        title=title,
        open_dir_on_success=open_dir_on_success,
        payload={
            "rows": inline_rows_source(rows)["rows"],
            "headers": [str(value) for value in headers],
            "offline_ap_stats": dict(offline_ap_stats),
            "offline_ap_ledger_rows": inline_rows_source(offline_ap_ledger_rows)["rows"],
            "offline_ap_stats_headers": [str(value) for value in offline_ap_stats_headers],
            "offline_ap_ledger_headers": [str(value) for value in offline_ap_ledger_headers],
        },
    )


def omnipeek_name_table_spec(
    output_path: str | Path,
    *,
    items: Iterable[Mapping[str, Any]],
    config: Mapping[str, Any],
    source_counts: Mapping[str, int],
    title: str = "",
    open_dir_on_success: bool = True,
) -> ExportTaskSpec:
    config_payload = dict(config)
    config_payload["output_path"] = str(output_path)
    if config_payload.get("mod_time") is not None:
        config_payload["mod_time"] = str(config_payload["mod_time"])
    return ExportTaskSpec(
        task_type="omnipeek_name_table",
        output_path=str(output_path),
        title=title,
        open_dir_on_success=open_dir_on_success,
        payload={
            "items": inline_rows_source(items)["rows"],
            "config": config_payload,
            "source_counts": {str(key): int(value) for key, value in dict(source_counts).items()},
        },
    )


def online_mr_report_xlsx_spec(
    output_path: str | Path,
    *,
    session_dir: str | Path,
    title: str = "",
    open_dir_on_success: bool = True,
) -> ExportTaskSpec:
    return ExportTaskSpec(
        task_type="online_mr_report_xlsx",
        output_path=str(output_path),
        title=title,
        open_dir_on_success=open_dir_on_success,
        payload={"session_dir": str(session_dir)},
    )


def app_logs_csv_spec(
    output_path: str | Path,
    *,
    log_path: str | Path,
    keyword: str | None = None,
    level: str | None = None,
    title: str = "",
    open_dir_on_success: bool = True,
) -> ExportTaskSpec:
    return ExportTaskSpec(
        task_type="app_logs_csv",
        output_path=str(output_path),
        title=title,
        open_dir_on_success=open_dir_on_success,
        payload={"log_path": str(log_path), "keyword": keyword or "", "level": level or ""},
    )
