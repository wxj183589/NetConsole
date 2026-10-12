from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import replace
from pathlib import Path

from netconsole.services.background_job import BackgroundJob
from netconsole.services.export.export_job import ExportJob
from netconsole.services.job_center.local_process_adapter import (
    CompletionCallback,
    LocalProcessAdapter,
    LocalProcessCompletion,
)
from netconsole.services.job_center.runtime.task_runtime import TaskLaunch
from netconsole.services.job_center.task_application_service import TaskApplicationService


_SAFE_JOB_ID = re.compile(r"^[0-9A-Za-z_-]{1,100}$")
_SAFE_TASK_TYPE = re.compile(r"^web_export_[0-9a-z_]{1,100}$")


class WebExportProcessAdapter(LocalProcessAdapter):
    """让独立 export_worker 复用统一 Task 与本地进程生命周期。"""

    def __init__(self, task_service: TaskApplicationService) -> None:
        super().__init__(task_service)
        self._exports: dict[str, ExportJob] = {}
        self._export_job_paths: dict[str, Path] = {}

    def start_export(
        self,
        job: ExportJob,
        *,
        task_name: str,
        owner: str,
        task_type: str = "",
        public_result: dict[str, object] | None = None,
        resource_keys: list[str] | None = None,
        on_complete: CompletionCallback | None = None,
    ) -> str:
        if not _SAFE_JOB_ID.fullmatch(job.job_id):
            raise ValueError("导出任务标识无效")
        if job.job_id in self._exports:
            raise RuntimeError("同一导出任务正在执行")
        safe_result = self._safe_public_result(public_result)
        export = replace(
            job,
            params={**dict(job.params or {}), "_web_public_result": safe_result},
        )
        self._exports[job.job_id] = export

        def completed(value: LocalProcessCompletion) -> None:
            self._cleanup_export_runtime(value.job_id, failed=value.exit_code != 0 or value.cancelled)
            if on_complete is not None:
                on_complete(value)

        selected_task_type = task_type or f"web_export_{job.job_type}"
        if not _SAFE_TASK_TYPE.fullmatch(selected_task_type):
            self._cleanup_export_runtime(job.job_id, failed=True)
            raise ValueError("Web 导出任务类型无效")
        background = BackgroundJob(
            job_id=job.job_id,
            task_type=selected_task_type,
            params={
                "site_name": job.site_name,
                "task_name": task_name,
                "owner": owner,
                "task_source": "local",
                "_cancel_grace_ms": 3_000,
                "resource_keys": list(resource_keys or ()),
                "resource_conflict_message": "当前会话已有解析、报告或删除任务正在执行，请等待任务完成。",
            },
        )
        try:
            return super().start_job(background, on_complete=completed)
        except Exception:
            self._cleanup_export_runtime(job.job_id, failed=True)
            raise

    @staticmethod
    def _safe_public_result(value: dict[str, object] | None) -> dict[str, object]:
        allowed = {"artifact_id", "artifact_name", "artifact_source", "artifact_type"}
        payload = dict(value or {})
        if set(payload) != allowed or not all(isinstance(payload[key], str) and payload[key] for key in allowed):
            raise ValueError("Web 导出缺少安全 Artifact 结果")
        name = str(payload["artifact_name"])
        if Path(name).is_absolute() or Path(name).name != name:
            raise ValueError("Web 导出 Artifact 名称无效")
        if any("/" in str(payload[key]) or "\\" in str(payload[key]) for key in allowed - {"artifact_name"}):
            raise ValueError("Web 导出 Artifact 标识无效")
        return {key: str(payload[key]) for key in sorted(allowed)}

    def _start_process(self, launch: TaskLaunch):
        export = self._exports.get(launch.job.job_id)
        if export is None:
            return super()._start_process(launch)
        output = Path(export.output_path).resolve()
        temporary = output.with_name(f"{output.name}.{launch.job.job_id}.tmp")
        runtime_job = export.with_runtime_paths(
            tmp_path=str(temporary),
            cancel_path=str(launch.cancel_path),
        )
        runtime_job.validate()
        job_root = self.task_service.paths.runtime_cache_dir / "export_jobs"
        job_root.mkdir(parents=True, exist_ok=True)
        job_path = (job_root / f"{launch.job.job_id}.json").resolve()
        if job_root.resolve() not in job_path.parents:
            raise ValueError("导出任务路径无效")
        self._export_job_paths[launch.job.job_id] = job_path
        pending = job_path.with_suffix(".json.tmp")
        pending.write_text(json.dumps(runtime_job.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(pending, job_path)
        arguments = (
            ("--export-worker", "--job", str(job_path))
            if getattr(sys, "frozen", False)
            else ("-m", "netconsole.export_worker", "--job", str(job_path))
        )
        return super()._start_process(replace(launch, program=sys.executable, arguments=arguments))

    def _cleanup_export_runtime(self, job_id: str, *, failed: bool) -> None:
        export = self._exports.pop(job_id, None)
        job_path = self._export_job_paths.pop(job_id, None)
        if job_path is not None:
            for path in (job_path, job_path.with_suffix(".json.tmp")):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
        if export is not None and failed:
            output = Path(export.output_path)
            temporary = output.with_name(f"{output.name}.{job_id}.tmp")
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


__all__ = ["WebExportProcessAdapter"]
