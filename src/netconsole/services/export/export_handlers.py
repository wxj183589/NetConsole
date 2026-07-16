from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from netconsole.services.export.common_exporters import (
    ExportCancelled,
    copy_file_export,
    export_config_diff_text,
    export_config_snapshots_zip,
    export_ap_online_overview_xlsx_task,
    export_device_csv,
    export_device_template_csv,
    export_markdown_text,
    export_mib_product_compare,
    export_omnipeek_name_table_task,
    export_online_mr_report_xlsx,
    export_open_source_notices,
    export_app_logs_csv,
    export_car_network_point_table,
    export_command_reference_markdown,
    export_fit_ap_csv_task,
    export_fit_ap_extension_template_xlsx_task,
    export_fit_ap_extension_xlsx_task,
    export_fit_ap_optical_xlsx_task,
    export_multi_sheet_xlsx,
    export_securecrt_sessions_task,
    export_snmp_query_result,
    export_table_csv,
    export_table_xlsx,
    export_wifi_survey_csv,
    export_wifi_survey_heatmap_png,
    export_vehicle_mr_history_xlsx,
    export_zip_files,
    replace_output,
)
from netconsole.services.export.export_job import ExportJob
from netconsole.services.file_contract import attach_export_metadata

ProgressCallback = Callable[[str, int, int, str], None]
CancelCallback = Callable[[], bool]


GENERIC_EXPORT_TASK_TYPES = {
    "table_xlsx",
    "table_csv",
    "multi_sheet_xlsx",
    "markdown_text",
    "config_diff_text",
    "zip_files",
    "copy_logs",
    "copy_file",
    "app_logs_csv",
    "open_source_notices",
    "device_csv",
    "device_template_csv",
    "securecrt_sessions",
    "config_snapshots_zip",
    "wifi_survey_csv",
    "wifi_survey_heatmap_png",
    "snmp_query_result",
    "mib_product_compare",
    "fit_ap_csv",
    "fit_ap_optical_xlsx",
    "fit_ap_extension_xlsx",
    "fit_ap_extension_template_xlsx",
    "ap_online_overview_xlsx",
    "omnipeek_name_table",
    "online_mr_report_xlsx",
    "car_network_point_table",
    "command_reference_markdown",
    "vehicle_mr_history_xlsx",
}


def run_generic_export_handler(job: ExportJob, progress_callback: ProgressCallback | None = None, should_cancel: CancelCallback | None = None) -> dict[str, Any]:
    job.validate()
    payload = dict(job.params.get("payload") or job.params or {})
    tmp_path = Path(job.tmp_path)
    output_path = Path(job.output_path)
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    row_count = 0
    if job.job_type == "table_xlsx":
        row_count = export_table_xlsx(tmp_path, payload, progress_callback, should_cancel)
    elif job.job_type == "multi_sheet_xlsx":
        row_count = export_multi_sheet_xlsx(tmp_path, payload, progress_callback, should_cancel)
    elif job.job_type == "table_csv":
        row_count = export_table_csv(tmp_path, payload, progress_callback, should_cancel)
    elif job.job_type == "markdown_text":
        row_count = export_markdown_text(tmp_path, payload, progress_callback, should_cancel)
    elif job.job_type == "config_diff_text":
        row_count = export_config_diff_text(tmp_path, payload, progress_callback, should_cancel)
    elif job.job_type == "zip_files":
        row_count = export_zip_files(tmp_path, payload, progress_callback, should_cancel)
    elif job.job_type in {"copy_logs", "copy_file"}:
        row_count = copy_file_export(tmp_path, payload, progress_callback, should_cancel)
    elif job.job_type == "app_logs_csv":
        row_count = export_app_logs_csv(tmp_path, payload, progress_callback, should_cancel)
    elif job.job_type == "open_source_notices":
        row_count = export_open_source_notices(tmp_path, payload, progress_callback, should_cancel)
    elif job.job_type == "device_csv":
        row_count = export_device_csv(tmp_path, payload, progress_callback, should_cancel)
    elif job.job_type == "device_template_csv":
        row_count = export_device_template_csv(tmp_path, payload, progress_callback, should_cancel)
    elif job.job_type == "securecrt_sessions":
        result = export_securecrt_sessions_task(tmp_path, payload, progress_callback, should_cancel)
        row_count = int(result.get("row_count") or 0)
    elif job.job_type == "config_snapshots_zip":
        row_count = export_config_snapshots_zip(tmp_path, payload, progress_callback, should_cancel)
    elif job.job_type == "wifi_survey_csv":
        row_count = export_wifi_survey_csv(tmp_path, payload, progress_callback, should_cancel)
    elif job.job_type == "wifi_survey_heatmap_png":
        row_count = export_wifi_survey_heatmap_png(tmp_path, payload, progress_callback, should_cancel)
    elif job.job_type == "snmp_query_result":
        row_count = export_snmp_query_result(tmp_path, payload, progress_callback, should_cancel)
    elif job.job_type == "mib_product_compare":
        row_count = export_mib_product_compare(tmp_path, payload, progress_callback, should_cancel)
    elif job.job_type == "fit_ap_csv":
        row_count = export_fit_ap_csv_task(tmp_path, payload, progress_callback, should_cancel)
    elif job.job_type == "fit_ap_optical_xlsx":
        row_count = export_fit_ap_optical_xlsx_task(tmp_path, payload, progress_callback, should_cancel)
    elif job.job_type == "fit_ap_extension_xlsx":
        row_count = export_fit_ap_extension_xlsx_task(tmp_path, payload, progress_callback, should_cancel)
    elif job.job_type == "fit_ap_extension_template_xlsx":
        row_count = export_fit_ap_extension_template_xlsx_task(tmp_path, payload, progress_callback, should_cancel)
    elif job.job_type == "ap_online_overview_xlsx":
        row_count = export_ap_online_overview_xlsx_task(tmp_path, payload, progress_callback, should_cancel)
    elif job.job_type == "omnipeek_name_table":
        result = export_omnipeek_name_table_task(output_path, payload, progress_callback, should_cancel)
        return {"path": str(result.get("path") or output_path), "row_count": int(result.get("row_count") or 0)}
    elif job.job_type == "online_mr_report_xlsx":
        row_count = export_online_mr_report_xlsx(tmp_path, payload, progress_callback, should_cancel)
    elif job.job_type == "car_network_point_table":
        row_count = export_car_network_point_table(tmp_path, payload, progress_callback, should_cancel)
    elif job.job_type == "command_reference_markdown":
        row_count = export_command_reference_markdown(tmp_path, payload, progress_callback, should_cancel)
    elif job.job_type == "vehicle_mr_history_xlsx":
        row_count = export_vehicle_mr_history_xlsx(tmp_path, payload, progress_callback, should_cancel)
    else:
        raise ValueError(f"不支持的通用导出任务类型：{job.job_type}")
    if should_cancel and should_cancel():
        raise ExportCancelled("导出已取消")
    attach_export_metadata(
        tmp_path,
        effective_suffix=output_path.suffix,
        export_type=job.job_type,
        payload=payload,
    )
    replace_output(tmp_path, output_path)
    if job.job_type == "securecrt_sessions":
        return {"path": str(result.get("path") or output_path), "row_count": row_count}
    return {"path": str(output_path), "row_count": row_count}
