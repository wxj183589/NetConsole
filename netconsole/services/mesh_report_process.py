from __future__ import annotations

import json
import os
import re
import sqlite3
import traceback
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import dataclass, replace
from pathlib import Path
from time import monotonic
from typing import Any

from netconsole.services.mesh_analysis_excel_report import MeshAnalysisExcelReportExporter
from netconsole.services.mesh_analysis_report import MeshAnalysisReportService, MeshReportOptions
from netconsole.models.mesh_analysis_params import MeshAnalysisParams, normalize_mesh_analysis_params


@dataclass(frozen=True)
class MeshReportProcessRequest:
    db_path: str
    mr_name: str
    output_path: str
    temp_path: str
    options: MeshReportOptions
    source_file_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class MeshReportProcessProgress:
    kind: str
    value: int = 0
    stage: str = ""
    path: str = ""
    output_dir: str = ""
    generated_files: tuple[str, ...] = ()
    file_index: int = 0
    file_total: int = 0
    file_name: str = ""
    error: str = ""
    traceback_summary: str = ""


def run_mesh_report_process(request: MeshReportProcessRequest, progress_queue: Any, cancel_event: Any) -> None:
    def emit(
        kind: str,
        value: int = 0,
        stage: str = "",
        path: str = "",
        output_dir: str = "",
        generated_files: list[str] | None = None,
        file_index: int = 0,
        file_total: int = 0,
        file_name: str = "",
        error: str = "",
        traceback_summary: str = "",
    ) -> None:
        progress_queue.put(
            {
                "kind": kind,
                "value": int(value or 0),
                "stage": stage,
                "path": path,
                "output_dir": output_dir,
                "generated_files": list(generated_files or []),
                "file_index": int(file_index or 0),
                "file_total": int(file_total or 0),
                "file_name": file_name,
                "error": error,
                "traceback_summary": traceback_summary,
            }
        )

    def should_cancel() -> bool:
        return bool(cancel_event.is_set())

    output_dir = Path(request.output_path).parent
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_files: list[str] = []
    try:
        if should_cancel():
            emit("cancelled", output_dir=str(output_dir), generated_files=generated_files)
            return
        emit("progress", 1, "source_files", output_dir=str(output_dir))
        source_files = _list_source_files(Path(request.db_path), request.source_file_ids)
        if not source_files:
            raise RuntimeError("当前数据缺少源文件关联，无法按 meshlog 单独生成报告。")
        workers = calculate_worker_count(request.options)
        total = len(source_files)
        emit("progress", 2, f"workers:{workers}", output_dir=str(output_dir), file_total=total)
        if workers > 1 and total > 1:
            _run_parallel_reports(request, output_dir, source_files, workers, generated_files, emit, should_cancel)
            return
        _run_sequential_reports(request, output_dir, source_files, generated_files, emit, should_cancel)
    except RuntimeError as exc:
        _cleanup_tmp_files(output_dir)
        if str(exc) == "cancelled" or should_cancel():
            emit("cancelled", output_dir=str(output_dir), generated_files=generated_files)
            return
        emit("failed", error=str(exc), traceback_summary=traceback.format_exc(limit=12), output_dir=str(output_dir), generated_files=generated_files)
    except BaseException as exc:
        _cleanup_tmp_files(output_dir)
        emit("failed", error=str(exc), traceback_summary=traceback.format_exc(limit=12), output_dir=str(output_dir), generated_files=generated_files)


def _run_parallel_reports(
    request: MeshReportProcessRequest,
    output_dir: Path,
    source_files: list[dict[str, object]],
    workers: int,
    generated_files: list[str],
    emit,
    should_cancel,
) -> None:
    total = len(source_files)
    jobs = _build_report_jobs(output_dir, request, source_files)
    emit("progress", 3, "parallel_workers", output_dir=str(output_dir), file_total=total)
    with ProcessPoolExecutor(max_workers=min(workers, total)) as executor:
        future_map = {executor.submit(_generate_source_report_task, job): job for job in jobs}
        pending = set(future_map)
        completed = 0
        last_heartbeat = 0.0
        while pending:
            if should_cancel():
                executor.shutdown(wait=False, cancel_futures=True)
                _cleanup_tmp_files(output_dir)
                emit("cancelled", output_dir=str(output_dir), generated_files=generated_files)
                return
            done, pending = wait(pending, timeout=0.2, return_when=FIRST_COMPLETED)
            now = monotonic()
            if not done and now - last_heartbeat >= 0.5:
                last_heartbeat = now
                emit(
                    "progress",
                    _combined_progress(completed + 1, total, 10),
                    "parallel_running",
                    output_dir=str(output_dir),
                    generated_files=generated_files,
                    file_index=completed,
                    file_total=total,
                    file_name="并行生成中",
                )
                continue
            for future in done:
                result = future.result()
                completed += 1
                generated_files.append(str(result["report_path"]))
                emit(
                    "progress",
                    _combined_progress(completed, total, 100),
                    "done",
                    output_dir=str(output_dir),
                    generated_files=generated_files,
                    file_index=completed,
                    file_total=total,
                    file_name=str(result["file_label"]),
                )
    emit("completed", 100, "done", str(output_dir), str(output_dir), generated_files)


def _run_sequential_reports(
    request: MeshReportProcessRequest,
    output_dir: Path,
    source_files: list[dict[str, object]],
    generated_files: list[str],
    emit,
    should_cancel,
) -> None:
    total = len(source_files)
    for index, source_file in enumerate(source_files, 1):
        if should_cancel():
            emit("cancelled", output_dir=str(output_dir), generated_files=generated_files)
            return
        file_label = str(source_file.get("original_filename") or source_file.get("archived_filename") or source_file.get("id") or "")
        emit("progress", _combined_progress(index, total, 0), "loading", output_dir=str(output_dir), file_index=index, file_total=total, file_name=file_label)
        report_path = _unique_report_path(output_dir, request.mr_name, source_file)
        temp_path = report_path.with_name(report_path.stem + ".tmp.xlsx")
        params = _analysis_params_for_report(request.options, source_file)
        options = replace(
            request.options,
            source_file_id=int(source_file["id"]),
            source_file_name=file_label,
            report_name=request.options.report_name or f"{request.mr_name} {file_label}",
            short_active_segment_seconds=params.short_link_threshold_ms / 1000.0,
            business_type=params.service_type,
            working_mode=params.wifi_type,
        )
        service = MeshAnalysisReportService(Path(request.db_path), request.mr_name)

        def progress(value: int, stage: str, *, current_index: int = index, current_total: int = total, current_file: str = file_label) -> None:
            emit(
                "progress",
                _combined_progress(current_index, current_total, value),
                stage,
                output_dir=str(output_dir),
                file_index=current_index,
                file_total=current_total,
                file_name=current_file,
            )

        model = service.build_report(options, progress=progress, should_cancel=should_cancel)
        if should_cancel():
            _cleanup_temp(temp_path)
            emit("cancelled", output_dir=str(output_dir), generated_files=generated_files)
            return
        MeshAnalysisExcelReportExporter().export(model, temp_path, progress=progress, should_cancel=should_cancel)
        if should_cancel():
            _cleanup_temp(temp_path)
            emit("cancelled", output_dir=str(output_dir), generated_files=generated_files)
            return
        temp_path.replace(report_path)
        generated_files.append(str(report_path))
        emit("progress", _combined_progress(index, total, 100), "done", output_dir=str(output_dir), generated_files=generated_files, file_index=index, file_total=total, file_name=file_label)
    emit("completed", 100, "done", str(output_dir), str(output_dir), generated_files)


def calculate_worker_count(options: MeshReportOptions) -> int:
    config = _load_performance_config()
    if not options.use_multi_core:
        return 1
    manual = int(options.worker_processes or 0)
    if manual > 0:
        return max(1, min(manual, min(os.cpu_count() or 1, 16)))
    reserve = int(config.get("reserve_cpu_cores", 2))
    maximum = int(config.get("max_worker_processes", 8))
    cpu_count = os.cpu_count() or 1
    return min(max(1, cpu_count - reserve), maximum)


def _build_report_jobs(output_dir: Path, request: MeshReportProcessRequest, source_files: list[dict[str, object]]) -> list[dict[str, object]]:
    reserved_paths: set[Path] = set()
    jobs: list[dict[str, object]] = []
    total = len(source_files)
    for index, source_file in enumerate(source_files, 1):
        file_label = str(source_file.get("original_filename") or source_file.get("archived_filename") or source_file.get("id") or "")
        report_path = _unique_report_path(output_dir, request.mr_name, source_file, reserved_paths)
        reserved_paths.add(report_path)
        options = replace(
            request.options,
            source_file_id=int(source_file["id"]),
            source_file_name=file_label,
            report_name=request.options.report_name or f"{request.mr_name} {file_label}",
        )
        jobs.append(
            {
                "index": index,
                "total": total,
                "db_path": request.db_path,
                "mr_name": request.mr_name,
                "file_label": file_label,
                "report_path": str(report_path),
                "temp_path": str(report_path.with_name(report_path.stem + ".tmp.xlsx")),
                "options": options,
            }
        )
    return jobs


def _generate_source_report_task(job: dict[str, object]) -> dict[str, object]:
    report_path = Path(str(job["report_path"]))
    temp_path = Path(str(job["temp_path"]))
    try:
        service = MeshAnalysisReportService(Path(str(job["db_path"])), str(job["mr_name"]))
        options = job["options"]
        if not isinstance(options, MeshReportOptions):
            raise TypeError("invalid report options")
        model = service.build_report(options)
        MeshAnalysisExcelReportExporter().export(model, temp_path)
        temp_path.replace(report_path)
        return {
            "index": int(job["index"]),
            "file_label": str(job["file_label"]),
            "report_path": str(report_path),
        }
    except BaseException:
        _cleanup_temp(temp_path)
        raise


def _list_source_files(db_path: Path, source_file_ids: tuple[int, ...] = ()) -> list[dict[str, object]]:
    clauses = ["COALESCE(parsed_deleted_at, '') = ''", "COALESCE(records_parsed, 0) > 0"]
    values: list[object] = []
    if source_file_ids:
        placeholders = ",".join("?" for _ in source_file_ids)
        clauses.append(f"id IN ({placeholders})")
        values.extend(source_file_ids)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT id, original_filename, archived_filename, first_sample_time, last_sample_time,
                   records_parsed, records_skipped, issue_count, sha256, analysis_params_json
            FROM source_files
            WHERE {" AND ".join(clauses)}
            ORDER BY COALESCE(first_sample_time, imported_at) ASC, id ASC
            """,
            values,
        ).fetchall()
    return [dict(row) for row in rows]


def _analysis_params_for_report(options: MeshReportOptions, source_file: dict[str, object]) -> MeshAnalysisParams:
    if options.analysis_params_override:
        return normalize_mesh_analysis_params(options.analysis_params_override)
    if str(source_file.get("analysis_params_json") or "").strip():
        return normalize_mesh_analysis_params(source_file.get("analysis_params_json"))
    return normalize_mesh_analysis_params(options.site_analysis_params)


def _unique_report_path(output_dir: Path, mr_name: str, source_file: dict[str, object], reserved_paths: set[Path] | None = None) -> Path:
    reserved_paths = reserved_paths or set()
    timestamp = _timestamp()
    source_stem = _strip_log_suffix(str(source_file.get("original_filename") or source_file.get("archived_filename") or source_file.get("id") or "meshlog"))
    base = f"{_safe_filename(mr_name)}_{_safe_filename(source_stem)}_MR原始MESH日志分析报告_{timestamp}"
    path = output_dir / f"{base}.xlsx"
    if not path.exists() and path not in reserved_paths:
        return path
    source_id = str(source_file.get("id") or "")
    sha = str(source_file.get("sha256") or "")[:8]
    base = f"{base}_{_safe_filename(source_id or sha or 'source')}"
    path = output_dir / f"{base}.xlsx"
    if not path.exists() and path not in reserved_paths:
        return path
    for index in range(1, 1000):
        candidate = output_dir / f"{base}_{index:03d}.xlsx"
        if not candidate.exists() and candidate not in reserved_paths:
            return candidate
    raise RuntimeError("无法生成不冲突的报告文件名。")


def _strip_log_suffix(filename: str) -> str:
    name = filename
    lower = name.lower()
    for suffix in (".log.gz", ".txt.gz", ".meshlog.gz", ".gz", ".log", ".txt", ".meshlog"):
        if lower.endswith(suffix):
            return name[: -len(suffix)]
    return Path(name).stem or name


def _safe_filename(value: str) -> str:
    safe = re.sub(r'[\\/:*?"<>|]+', "_", str(value)).strip(" ._")
    return safe or "MR"


def _timestamp() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _combined_progress(index: int, total: int, inner_value: int) -> int:
    total = max(total, 1)
    base = (index - 1) / total
    current = max(0, min(inner_value, 100)) / 100 / total
    return min(99, int((base + current) * 100))


def _load_performance_config() -> dict[str, object]:
    path = Path(__file__).resolve().parents[1] / "resources" / "mesh_quality_rules.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    performance = data.get("performance")
    return performance if isinstance(performance, dict) else {}


def _cleanup_temp(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def _cleanup_tmp_files(output_dir: Path) -> None:
    for path in output_dir.glob("*.tmp.xlsx"):
        _cleanup_temp(path)
