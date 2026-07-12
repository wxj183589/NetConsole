from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from typing import Any


@dataclass(frozen=True)
class JobSpec:
    job_id: str = ""
    task_type: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    cancel_path: str = ""

    @property
    def job_type(self) -> str:
        return self.task_type

    def with_runtime_paths(self, *, cancel_path: str) -> "JobSpec":
        return replace(
            self,
            job_id=self.job_id or uuid.uuid4().hex,
            params=dict(self.params or {}),
            cancel_path=str(cancel_path),
        )

    def validate(self) -> None:
        if not self.task_type:
            raise ValueError("后台任务缺少 task_type")

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "task_type": self.task_type,
            "params": dict(self.params or {}),
            "cancel_path": self.cancel_path,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JobSpec":
        return cls(
            job_id=str(data.get("job_id") or ""),
            task_type=str(data.get("task_type") or data.get("job_type") or ""),
            params=dict(data.get("params") or {}),
            cancel_path=str(data.get("cancel_path") or ""),
        )


BackgroundJob = JobSpec


@dataclass(frozen=True)
class JobProgress:
    job_id: str
    stage: str
    current: int = 0
    total: int = 0
    message: str = ""

    def to_event(self) -> dict[str, Any]:
        from netconsole.services.job_center.job_events import progress_event

        return progress_event(self.job_id, self.stage, self.current, self.total, self.message)


@dataclass(frozen=True)
class JobError:
    job_id: str
    message: str
    traceback: str = ""
    cancelled: bool = False

    def to_event(self) -> dict[str, Any]:
        from netconsole.services.job_center.job_events import cancelled_event, error_event

        if self.cancelled:
            return cancelled_event(self.job_id, self.message)
        return error_event(self.job_id, self.message, traceback_text=self.traceback)


@dataclass(frozen=True)
class JobResult:
    job_id: str
    ok: bool
    result: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    error: str = ""
    traceback: str = ""
    cancelled: bool = False

    def to_event(self) -> dict[str, Any]:
        from netconsole.services.job_center.job_events import cancelled_event, error_event, finished_event

        if self.cancelled:
            return cancelled_event(self.job_id, self.message or self.error or "后台任务已取消")
        if not self.ok:
            return error_event(
                self.job_id,
                self.error or self.message or "后台任务失败",
                traceback_text=self.traceback,
            )
        return finished_event(self.job_id, self.result, self.message or "后台任务完成")
