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


def inline_rows_source(
    rows: Iterable[Mapping[str, Any]],
    *,
    allow_inline_rows: bool = False,
    inline_reason: str = "",
    limit: int = INLINE_ROW_LIMIT,
) -> dict[str, Any]:
    reason = str(inline_reason or "").strip()
    if not allow_inline_rows or not reason:
        raise ValueError("inline_rows_source 默认禁用；小型运行期数据必须显式传入 allow_inline_rows=True 和 inline_reason")
    materialized = [dict(row) for row in rows]
    if len(materialized) > limit:
        raise ValueError(f"inline_rows 导出最多支持 {limit} 行，请改用 repository_query 数据源")
    return {"type": "inline_rows", "rows": materialized, "inline_reason": reason}


def result_file_rows_source(result_file: str | Path) -> dict[str, Any]:
    return {"type": "jsonl_rows", "result_file": str(result_file)}


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
    allow_inline_rows: bool = False,
    inline_reason: str = "",
) -> ExportTaskSpec:
    return table_xlsx_source_spec(
        output_path,
        columns=columns,
        source=inline_rows_source(rows, allow_inline_rows=allow_inline_rows, inline_reason=inline_reason),
        headers=headers,
        sheet_name=sheet_name,
        title=title,
        row_fill_field=row_fill_field,
        row_fill_colors=row_fill_colors,
        open_dir_on_success=open_dir_on_success,
    )


def table_xlsx_source_spec(
    output_path: str | Path,
    *,
    columns: Iterable[tuple[str, str] | Mapping[str, Any]],
    source: Mapping[str, Any],
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
            "source": dict(source),
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
    allow_inline_rows: bool = False,
    inline_reason: str = "",
) -> ExportTaskSpec:
    return table_csv_source_spec(
        output_path,
        columns=columns,
        source=inline_rows_source(rows, allow_inline_rows=allow_inline_rows, inline_reason=inline_reason),
        headers=headers,
        title=title,
        open_dir_on_success=open_dir_on_success,
    )


def table_csv_source_spec(
    output_path: str | Path,
    *,
    columns: Iterable[tuple[str, str] | Mapping[str, Any]],
    source: Mapping[str, Any],
    headers: Iterable[str] | None = None,
    title: str = "",
    open_dir_on_success: bool = True,
) -> ExportTaskSpec:
    return ExportTaskSpec(
        task_type="table_csv",
        output_path=str(output_path),
        title=title,
        open_dir_on_success=open_dir_on_success,
        payload={"columns": column_specs(columns, headers), "source": dict(source)},
    )


def markdown_text_spec(
    output_path: str | Path,
    *,
    text: str,
    title: str = "",
    open_dir_on_success: bool = True,
    inline_reason: str = "",
) -> ExportTaskSpec:
    payload: dict[str, Any] = {"text": text}
    if inline_reason:
        payload["inline_reason"] = inline_reason
    return ExportTaskSpec(
        task_type="markdown_text",
        output_path=str(output_path),
        title=title,
        open_dir_on_success=open_dir_on_success,
        payload=payload,
    )


def markdown_text_file_spec(
    output_path: str | Path,
    *,
    text_file: str | Path,
    title: str = "",
    open_dir_on_success: bool = True,
) -> ExportTaskSpec:
    return ExportTaskSpec(
        task_type="markdown_text",
        output_path=str(output_path),
        title=title,
        open_dir_on_success=open_dir_on_success,
        payload={"text_file": str(text_file)},
    )


def config_diff_text_spec(
    output_path: str | Path,
    *,
    db_path: str | Path,
    site_name: str,
    app_root: str | Path | None = None,
    data_root: str | Path | None = None,
    left_snapshot_id: int,
    right_snapshot_id: int,
    title: str = "",
    open_dir_on_success: bool = True,
) -> ExportTaskSpec:
    return ExportTaskSpec(
        task_type="config_diff_text",
        output_path=str(output_path),
        title=title,
        open_dir_on_success=open_dir_on_success,
        db_path=str(db_path),
        site_name=site_name,
        payload={
            "db_path": str(db_path),
            "site_name": site_name,
            "app_root": str(app_root) if app_root is not None else "",
            "data_root": str(data_root) if data_root is not None else "",
            "left_snapshot_id": int(left_snapshot_id),
            "right_snapshot_id": int(right_snapshot_id),
        },
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
        payload["devices"] = inline_rows_source(
            selected_devices,
            allow_inline_rows=True,
            inline_reason="设备管理勾选导出为用户当前显式选择的小型集合",
        )["rows"]
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
    db_path: str | Path,
    site_name: str,
    selected_device_uuids: Iterable[str] | None = None,
    filters: Mapping[str, Any] | None = None,
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
            "db_path": str(db_path),
            "site_name": site_name,
            "selected_device_uuids": [str(value) for value in selected_device_uuids or []],
            "filters": dict(filters or {}),
            "template_ini": str(template_ini or ""),
        },
    )


def fit_ap_csv_spec(
    output_path: str | Path,
    *,
    db_path: str | Path,
    ac_uuid: str = "",
    filters: Mapping[str, Any] | None = None,
    selected_ap_keys: Iterable[str] | None = None,
    title: str = "",
    open_dir_on_success: bool = True,
) -> ExportTaskSpec:
    return ExportTaskSpec(
        task_type="fit_ap_csv",
        output_path=str(output_path),
        title=title,
        open_dir_on_success=open_dir_on_success,
        payload={
            "db_path": str(db_path),
            "ac_uuid": ac_uuid,
            "filters": dict(filters or {}),
            "selected_ap_keys": [str(key) for key in selected_ap_keys or []],
        },
    )


def fit_ap_resource_xlsx_spec(
    output_path: str | Path,
    *,
    db_path: str | Path,
    site_name: str,
    ac_uuid: str,
    scope: str,
    selected_ap_ids: Iterable[str] | None = None,
    filters: Mapping[str, Any] | None = None,
    requested_at: str = "",
    app_root: str | Path | None = None,
    data_root: str | Path | None = None,
    title: str = "",
    open_dir_on_success: bool = True,
) -> ExportTaskSpec:
    return ExportTaskSpec(
        task_type="fit_ap_resource_xlsx",
        output_path=str(output_path),
        title=title,
        open_dir_on_success=open_dir_on_success,
        payload={
            "db_path": str(db_path),
            "site_name": site_name,
            "ac_uuid": ac_uuid,
            "scope": scope,
            "selected_ap_ids": [str(value) for value in selected_ap_ids or [] if str(value)],
            "filters": dict(filters or {}),
            "requested_at": requested_at,
            "app_root": str(app_root) if app_root is not None else "",
            "data_root": str(data_root) if data_root is not None else "",
        },
    )


def fit_ap_extension_xlsx_spec(
    output_path: str | Path,
    *,
    db_path: str | Path,
    ac_uuid: str = "",
    search: str = "",
    filters: Mapping[str, Any] | None = None,
    title: str = "",
    open_dir_on_success: bool = True,
) -> ExportTaskSpec:
    return ExportTaskSpec(
        task_type="fit_ap_extension_xlsx",
        output_path=str(output_path),
        title=title,
        open_dir_on_success=open_dir_on_success,
        payload={
            "db_path": str(db_path),
            "ac_uuid": ac_uuid,
            "search": search,
            "filters": dict(filters or {}),
        },
    )


def fit_ap_extension_template_xlsx_spec(
    output_path: str | Path,
    *,
    db_path: str | Path,
    ac_uuid: str = "",
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
            "ac_uuid": ac_uuid,
        },
    )


def ap_online_overview_xlsx_spec(
    output_path: str | Path,
    *,
    db_path: str | Path,
    site_name: str,
    ac_uuid: str,
    headers: Iterable[str],
    offline_ap_stats_headers: Iterable[str],
    offline_ap_ledger_headers: Iterable[str],
    app_root: str | Path | None = None,
    data_root: str | Path | None = None,
    title: str = "",
    open_dir_on_success: bool = True,
) -> ExportTaskSpec:
    return ExportTaskSpec(
        task_type="ap_online_overview_xlsx",
        output_path=str(output_path),
        title=title,
        open_dir_on_success=open_dir_on_success,
        payload={
            "db_path": str(db_path),
            "site_name": site_name,
            "ac_uuid": ac_uuid,
            "headers": [str(value) for value in headers],
            "offline_ap_stats_headers": [str(value) for value in offline_ap_stats_headers],
            "offline_ap_ledger_headers": [str(value) for value in offline_ap_ledger_headers],
            "app_root": str(app_root) if app_root is not None else "",
            "data_root": str(data_root) if data_root is not None else "",
        },
    )


def fit_ap_optical_xlsx_spec(
    output_path: str | Path,
    *,
    db_path: str | Path,
    site_name: str,
    ac_uuid: str,
    columns: Iterable[tuple[str, str] | Mapping[str, Any]],
    headers: Iterable[str],
    overview_headers: Iterable[str],
    filters: Mapping[str, Any] | None = None,
    app_root: str | Path | None = None,
    data_root: str | Path | None = None,
    title: str = "",
    open_dir_on_success: bool = True,
) -> ExportTaskSpec:
    return ExportTaskSpec(
        task_type="fit_ap_optical_xlsx",
        output_path=str(output_path),
        title=title,
        open_dir_on_success=open_dir_on_success,
        payload={
            "db_path": str(db_path),
            "site_name": site_name,
            "ac_uuid": ac_uuid,
            "filters": dict(filters or {}),
            "columns": column_specs(columns, headers),
            "headers": [str(value) for value in headers],
            "overview_headers": [str(value) for value in overview_headers],
            "app_root": str(app_root) if app_root is not None else "",
            "data_root": str(data_root) if data_root is not None else "",
        },
    )


def omnipeek_name_table_spec(
    output_path: str | Path,
    *,
    db_path: str | Path,
    site_name: str,
    source: Mapping[str, Any],
    config: Mapping[str, Any],
    selected_item_keys: Iterable[str] | None = None,
    excluded_item_keys: Iterable[str] | None = None,
    force_export_keys: Iterable[str] | None = None,
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
            "db_path": str(db_path),
            "site_name": site_name,
            "source": dict(source),
            "config": config_payload,
            "selected_item_keys": [str(value) for value in selected_item_keys or [] if str(value)],
            "excluded_item_keys": [str(value) for value in excluded_item_keys or [] if str(value)],
            "force_export_keys": [str(value) for value in force_export_keys or [] if str(value)],
        },
    )


def car_network_point_table_spec(
    output_path: str | Path,
    *,
    site_name: str,
    title: str = "",
    open_dir_on_success: bool = True,
) -> ExportTaskSpec:
    return ExportTaskSpec(
        task_type="car_network_point_table",
        output_path=str(output_path),
        title=title,
        open_dir_on_success=open_dir_on_success,
        payload={"site_name": site_name},
        site_name=site_name,
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
    log_paths: Iterable[str | Path] | None = None,
    keyword: str | None = None,
    level: str | None = None,
    offset: int = 0,
    limit: int = 0,
    snapshot_size: int | None = None,
    redact_web: bool = False,
    title: str = "",
    open_dir_on_success: bool = True,
) -> ExportTaskSpec:
    source_path = Path(log_path)
    if snapshot_size is None:
        try:
            snapshot_size = source_path.stat().st_size
        except OSError:
            snapshot_size = 0
    sources = [Path(value) for value in (log_paths or [source_path])]
    snapshots: list[dict[str, object]] = []
    for source in sources:
        try:
            size = source.stat().st_size
        except OSError:
            size = 0
        snapshots.append({"path": str(source), "size": max(0, int(size))})
    return ExportTaskSpec(
        task_type="app_logs_csv",
        output_path=str(output_path),
        title=title,
        open_dir_on_success=open_dir_on_success,
        payload={
            "log_path": str(source_path),
            "log_files": snapshots,
            "keyword": keyword or "",
            "level": level or "",
            "offset": max(0, int(offset)),
            "limit": max(0, int(limit)),
            "snapshot_size": max(0, int(snapshot_size)),
            "redact_web": bool(redact_web),
        },
    )


def open_source_notices_spec(
    output_path: str | Path,
    *,
    base_dir: str | Path,
    format: str,
    title: str = "",
) -> ExportTaskSpec:
    if format not in {"txt", "xlsx"}:
        raise ValueError("开源许可导出格式仅支持 txt/xlsx")
    return ExportTaskSpec(
        task_type="open_source_notices",
        output_path=str(output_path),
        title=title,
        payload={"base_dir": str(base_dir), "format": format},
    )


def command_reference_markdown_spec(
    output_path: str | Path,
    *,
    resource_path: str | Path,
    selected_ids: Iterable[str] | None = None,
    title: str = "",
    open_dir_on_success: bool = True,
) -> ExportTaskSpec:
    return ExportTaskSpec(
        task_type="command_reference_markdown",
        output_path=str(output_path),
        title=title,
        open_dir_on_success=open_dir_on_success,
        payload={
            "resource_path": str(resource_path),
            "selected_ids": [str(value) for value in selected_ids or [] if str(value)],
        },
    )


def vehicle_mr_history_xlsx_spec(
    output_path: str | Path,
    *,
    app_root: str | Path,
    data_root: str | Path,
    site_name: str,
    train_id: str,
    filters: Mapping[str, Any],
    title: str = "",
    open_dir_on_success: bool = True,
) -> ExportTaskSpec:
    return ExportTaskSpec(
        task_type="vehicle_mr_history_xlsx",
        output_path=str(output_path),
        title=title,
        open_dir_on_success=open_dir_on_success,
        site_name=site_name,
        payload={
            "app_root": str(app_root),
            "data_root": str(data_root),
            "site_name": site_name,
            "train_id": train_id,
            "filters": dict(filters),
        },
    )
