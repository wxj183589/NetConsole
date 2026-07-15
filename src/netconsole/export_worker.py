from __future__ import annotations

import argparse
import io
import json
import os
import sys
import traceback
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from typing import Any

from netconsole.repositories.mesh_mr_repository import MeshMrRepository
from netconsole.services.export.common_exporters import ExportCancelled
from netconsole.services.export import error_event, finished_event, progress_event
from netconsole.services.export.export_handlers import GENERIC_EXPORT_TASK_TYPES, run_generic_export_handler
from netconsole.services.export.export_job import ExportJob
from netconsole.services.mesh_link_detail_export import MeshLinkDetailExportCancelled, export_mesh_link_details_xlsx
from netconsole.services.job_center.job_events import (
    cancelled_event as task_cancelled_event,
    error_event as task_error_event,
    finished_event as task_finished_event,
    log_event,
)
from netconsole.services.job_center.web_export_event_safety import (
    redact_web_export_text,
    sanitize_web_export_value,
)
from netconsole.services.job_center.worker_protocol import write_event
from netconsole.services.mesh_analysis_report import MeshReportOptions
from netconsole.services.mesh_report_process import MeshReportProcessRequest, run_mesh_report_process
from netconsole.services.trackside_ap_business import TracksideApExportCancelled
from netconsole.services.trackside_ap_export_service import export_trackside_ap_business_from_database
from netconsole.services.file_contract import attach_export_metadata


def _emit(event: dict[str, Any]) -> None:
    write_event(event)


def _emit_progress(job: ExportJob, current: int, total: int, stage: str, message: str | None = None) -> None:
    _emit(progress_event(job.job_id, stage, current=current, total=total, message=message or stage))


def _should_cancel(job: ExportJob) -> bool:
    return bool(job.cancel_path and Path(job.cancel_path).exists())


def _web_public_result(job: ExportJob, *, row_count: int) -> dict[str, object] | None:
    value = job.params.get("_web_public_result")
    if not isinstance(value, dict):
        return None
    sanitized = sanitize_web_export_value(value)
    if not isinstance(sanitized, dict):
        raise ValueError("Web 导出公开结果无效")
    result = dict(sanitized)
    result["row_count"] = int(row_count or 0)
    result["artifact_pending"] = True
    return result


def _finished(job: ExportJob, output_path: str, *, message: str = "导出完成", row_count: int = 0) -> dict[str, Any]:
    public_result = _web_public_result(job, row_count=row_count)
    if public_result is not None:
        return task_finished_event(job.job_id, public_result, message)
    return finished_event(job.job_id, output_path, message=message, row_count=row_count)


def _error(job: ExportJob, message: str, *, traceback_text: str = "", cancelled: bool = False) -> dict[str, Any]:
    if _web_public_result(job, row_count=0) is not None:
        safe_message = redact_web_export_text(message)
        return task_cancelled_event(job.job_id, safe_message) if cancelled else task_error_event(job.job_id, safe_message)
    return error_event(
        job.job_id,
        message,
        traceback_text=traceback_text,
        output_path=job.output_path,
        cancelled=cancelled,
    )


def _run_trackside_ap_business(job: ExportJob) -> None:
    job.validate()
    if not job.db_path:
        raise ValueError("轨旁AP业务导出缺少数据库路径")
    language = str(job.params.get("language") or "zh_CN")
    result = export_trackside_ap_business_from_database(
        database_path=job.db_path,
        site_name=job.site_name,
        output_path=job.output_path,
        tmp_path=job.tmp_path,
        language=language,
        progress_callback=lambda stage, current, total, message: _emit_progress(job, current, total, stage, message),
        should_cancel=lambda: _should_cancel(job),
    )
    _emit(
        _finished(
            job,
            str(result.get("path") or job.output_path),
            message="导出完成",
            row_count=int(result.get("row_count") or 0),
        )
    )


def _run_mesh_link_detail(job: ExportJob) -> None:
    job.validate()
    db_path = Path(job.db_path)
    output_path = Path(job.output_path)
    tmp_path = Path(job.tmp_path)
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    repo = MeshMrRepository(db_path)
    filters = dict(job.filters or {})
    params = dict(job.params or {})
    context = dict(job.context or {})
    source_file_id = context.get("source_file_id")
    radio = context.get("radio")
    analysis_params = params.get("analysis_params") if isinstance(params.get("analysis_params"), dict) else None
    fallback_analysis_params = params.get("fallback_analysis_params") if isinstance(params.get("fallback_analysis_params"), dict) else None

    _emit_progress(job, 0, 0, "mesh_analysis.export_progress_query_links", "正在统计链路明细")
    total = repo.count_link_details(filters)
    _emit_progress(job, 0, total, "mesh_analysis.export_progress_query_links", f"正在导出链路明细：0 / {total}")
    if total <= 0:
        raise RuntimeError("暂无可导出的链路明细数据")
    if _should_cancel(job):
        raise MeshLinkDetailExportCancelled("导出已取消")

    _emit_progress(job, 0, total, "mesh_analysis.export_progress_query_build_order", "正在生成主链路建链顺序")
    active_build_order_rows = repo.query_active_link_build_order(
        source_file_id,
        radio,
        analysis_params,
        fallback_analysis_params,
    )
    _source_total, source_files = repo.query_source_files(100000, 0)
    try:
        event_rows = repo.export_rows("switch_events")
    except Exception:
        event_rows = []
    if _should_cancel(job):
        raise MeshLinkDetailExportCancelled("导出已取消")

    _emit_progress(job, 0, total, "mesh_analysis.export_progress_write_links", f"正在导出链路明细：0 / {total}")
    rows = repo.iter_link_details(filters, batch_size=2000)
    merged_params = {**(fallback_analysis_params or {}), **(analysis_params or {})}
    export_context = {
        "site_name": context.get("site_name") or "",
        "mr_name": context.get("mr_name") or "",
        "source_label": context.get("source_label") or ("全部源文件" if source_file_id in (None, "") else str(source_file_id)),
        "exported_at": context.get("exported_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    export_result = export_mesh_link_details_xlsx(
        tmp_path,
        rows,
        active_build_order_rows,
        total_rows=total,
        source_files=source_files,
        event_rows=event_rows,
        analysis_params=merged_params,
        export_context=export_context,
        progress_callback=lambda done, row_total, key: _emit_progress(job, done, row_total, key, f"正在导出链路明细：{done} / {row_total}"),
        should_cancel=lambda: _should_cancel(job),
    )
    if _should_cancel(job):
        raise MeshLinkDetailExportCancelled("导出已取消")
    _emit_progress(job, total, total, "mesh_analysis.export_progress_save", "正在保存链路明细 Excel")
    attach_export_metadata(
        tmp_path,
        effective_suffix=output_path.suffix,
        export_type=job.job_type,
        payload={"source_module": "rail.mesh_link_detail"},
    )
    os.replace(tmp_path, output_path)
    event = _finished(job, str(output_path), row_count=total)
    result = event.get("result")
    if isinstance(result, dict):
        result.update(export_result)
    _emit(event)


class _MeshProgressQueue:
    def __init__(self, job: ExportJob) -> None:
        self.job = job
        self.terminal: dict[str, Any] = {}
        self.generated_files: list[str] = []

    def put(self, payload: dict[str, Any]) -> None:
        kind = str(payload.get("kind") or "")
        self.generated_files = [str(value) for value in payload.get("generated_files") or self.generated_files]
        if kind == "progress":
            value = int(payload.get("value") or 0)
            _emit_progress(self.job, value, 100, str(payload.get("stage") or "mesh_report"))
        elif kind in {"completed", "failed", "cancelled"}:
            self.terminal = dict(payload)


class _MeshCancelEvent:
    def __init__(self, job: ExportJob) -> None:
        self.job = job

    def is_set(self) -> bool:
        return _should_cancel(self.job)


def _run_mesh_analysis_report(job: ExportJob) -> None:
    job.validate()
    output_root = Path(job.output_path).resolve().parent
    payload = dict(job.params.get("payload") or job.params or {})
    option_values = dict(payload.get("options") or {})
    option_values.update(use_multi_core=False, open_output_dir_after_done=False, separate_reports_by_source_file=True)
    options = MeshReportOptions(**option_values)
    source_ids = tuple(int(value) for value in payload.get("source_file_ids") or ())
    if len(source_ids) != 1:
        raise ValueError("Web MESH 报告必须绑定一个来源文件")
    queue = _MeshProgressQueue(job)
    request = MeshReportProcessRequest(
        db_path=job.db_path,
        mr_name=str(payload.get("mr_name") or ""),
        output_path=job.output_path,
        temp_path=job.tmp_path,
        options=options,
        source_file_ids=source_ids,
    )
    try:
        run_mesh_report_process(request, queue, _MeshCancelEvent(job))
        kind = str(queue.terminal.get("kind") or "")
        if kind == "cancelled" or _should_cancel(job):
            raise ExportCancelled("导出已取消")
        if kind != "completed":
            raise RuntimeError(str(queue.terminal.get("error") or "MESH 报告生成失败"))
        if len(queue.generated_files) != 1:
            raise RuntimeError("MESH 报告输出数量异常")
        generated = Path(queue.generated_files[0]).resolve()
        if generated.is_symlink() or output_root not in generated.parents:
            raise RuntimeError("MESH 报告输出路径无效")
        tmp_path = Path(job.tmp_path)
        tmp_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(generated, tmp_path)
        os.replace(tmp_path, job.output_path)
        _emit(_finished(job, job.output_path, row_count=1))
    except Exception:
        for value in queue.generated_files:
            path = Path(value).resolve()
            try:
                if output_root in path.parents and path.is_file() and not path.is_symlink():
                    path.unlink()
            except OSError:
                pass
        raise


def run_job(job: ExportJob) -> int:
    diagnostics = sys.stderr or getattr(sys, "__stderr__", None) or io.StringIO()
    with redirect_stdout(diagnostics):
        return _run_job(job)


def _run_job(job: ExportJob) -> int:
    try:
        if job.job_type in GENERIC_EXPORT_TASK_TYPES:
            result = run_generic_export_handler(
                job,
                progress_callback=lambda stage, current, total, message: _emit_progress(job, current, total, stage, message),
                should_cancel=lambda: _should_cancel(job),
            )
            _emit(_finished(job, str(result.get("path") or job.output_path), row_count=int(result.get("row_count") or 0)))
            return 0
        if job.job_type == "trackside_ap_business":
            _run_trackside_ap_business(job)
            return 0
        if job.job_type == "mesh_link_detail":
            _run_mesh_link_detail(job)
            return 0
        if job.job_type == "mesh_analysis_report":
            _run_mesh_analysis_report(job)
            return 0
        raise ValueError(f"不支持的导出任务类型：{job.job_type}")
    except (MeshLinkDetailExportCancelled, TracksideApExportCancelled, ExportCancelled) as exc:
        _cleanup_tmp(job)
        _emit(_error(job, str(exc), cancelled=True))
        return 2
    except Exception as exc:
        _cleanup_tmp(job)
        stack = traceback.format_exc()
        message = _friendly_error_message(exc)
        _emit(
            log_event(
                job.job_id,
                "Web 报告导出失败" if _web_public_result(job, row_count=0) is not None else stack,
                level="error",
            )
        )
        _emit(_error(job, message, traceback_text=stack, cancelled=False))
        return 1


def _friendly_error_message(exc: Exception) -> str:
    text = str(exc) or exc.__class__.__name__
    lowered = text.lower()
    if isinstance(exc, PermissionError) or any(token in lowered for token in ("permission", "access is denied", "另一个程序", "占用")):
        return "导出失败：目标文件可能已被 WPS/Excel 打开，请关闭后重试。"
    return text if text.startswith("导出失败") else f"导出失败：{text}"


def _cleanup_tmp(job: ExportJob) -> None:
    try:
        tmp_path = Path(job.tmp_path)
        if tmp_path.exists():
            tmp_path.unlink()
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NetConsole export worker")
    parser.add_argument("--job", required=True, help="导出任务 JSON 文件")
    args = parser.parse_args(argv)
    job_path = Path(args.job)
    with job_path.open("r", encoding="utf-8") as handle:
        job = ExportJob.from_dict(json.load(handle))
    return run_job(job)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
