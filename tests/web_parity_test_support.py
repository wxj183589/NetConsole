from __future__ import annotations

import json
from pathlib import Path

from netconsole.services.background_job import BackgroundJob
from netconsole.services.export.export_job import ExportJob
from netconsole.services.job_center.local_process_adapter import LocalProcessCompletion
from netconsole.services.job_center.task_application_service import TaskApplicationService


class FakeLocalProcessAdapter:
    def __init__(self, tasks: TaskApplicationService) -> None:
        self.tasks = tasks
        self.jobs: dict[str, BackgroundJob] = {}
        self.callbacks = {}

    def start_job(self, job: BackgroundJob, *, on_complete=None) -> str:
        self.jobs[job.job_id] = job
        self.callbacks[job.job_id] = on_complete
        launch = self.tasks.prepare(job)
        self.tasks.mark_running(launch.job.job_id)
        return launch.job.job_id

    def is_running(self, job_id: str) -> bool:
        return job_id in self.jobs

    def cancel_job(self, job_id: str) -> bool:
        if job_id not in self.jobs:
            return False
        self.tasks.request_cancel(job_id)
        payload = self.tasks.complete(job_id, 2)
        self._finish(job_id, 2, payload, True)
        return True

    def complete(self, job_id: str, result: dict[str, object] | None = None) -> None:
        event = {"type": "finished", "job_id": job_id, "message": "fixture completed", "result": result or {}}
        self.tasks.feed_stdout(job_id, (json.dumps(event) + "\n").encode("utf-8"))
        payload = self.tasks.complete(job_id, 0)
        self._finish(job_id, 0, payload, False)

    def _finish(self, job_id: str, exit_code: int, payload, cancelled: bool) -> None:
        job = self.jobs.pop(job_id)
        callback = self.callbacks.pop(job_id, None)
        if callback is not None:
            callback(
                LocalProcessCompletion(
                    job_id=job_id,
                    task_type=job.task_type,
                    exit_code=exit_code,
                    payload=payload,
                    cancelled=cancelled,
                    forced=False,
                )
            )


class FakeExportProcessAdapter:
    def __init__(self, tasks: TaskApplicationService) -> None:
        self.tasks = tasks
        self.jobs: dict[str, ExportJob] = {}
        self.callbacks = {}

    def start_export(self, job: ExportJob, *, task_name: str, owner: str, on_complete=None) -> str:
        self.jobs[job.job_id] = job
        self.callbacks[job.job_id] = on_complete
        launch = self.tasks.prepare(
            BackgroundJob(
                job_id=job.job_id,
                task_type=f"web_export_{job.job_type}",
                params={
                    "site_name": job.site_name,
                    "task_name": task_name,
                    "owner": owner,
                    "task_source": "local",
                },
            )
        )
        self.tasks.mark_running(launch.job.job_id)
        return launch.job.job_id

    def is_running(self, job_id: str) -> bool:
        return job_id in self.jobs

    def cancel_job(self, job_id: str) -> bool:
        if job_id not in self.jobs:
            return False
        self.tasks.request_cancel(job_id)
        payload = self.tasks.complete(job_id, 2)
        self._finish(job_id, 2, payload, True)
        return True

    def complete(self, job_id: str, content: bytes = b"fixture-report") -> Path:
        job = self.jobs[job_id]
        path = Path(job.output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        event = {
            "type": "finished",
            "job_id": job_id,
            "message": "fixture export completed",
            "result": {"output_path": str(path)},
        }
        self.tasks.feed_stdout(job_id, (json.dumps(event) + "\n").encode("utf-8"))
        payload = self.tasks.complete(job_id, 0)
        self._finish(job_id, 0, payload, False)
        return path

    def _finish(self, job_id: str, exit_code: int, payload, cancelled: bool) -> None:
        job = self.jobs.pop(job_id)
        callback = self.callbacks.pop(job_id, None)
        if callback is not None:
            callback(
                LocalProcessCompletion(
                    job_id=job_id,
                    task_type=f"web_export_{job.job_type}",
                    exit_code=exit_code,
                    payload=payload,
                    cancelled=cancelled,
                    forced=False,
                )
            )


__all__ = ["FakeExportProcessAdapter", "FakeLocalProcessAdapter"]
