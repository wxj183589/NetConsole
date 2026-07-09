from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class BackgroundJob:
    job_id: str = ""
    task_type: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    cancel_path: str = ""

    def with_runtime_paths(self, *, cancel_path: str) -> "BackgroundJob":
        return BackgroundJob(
            job_id=self.job_id or uuid.uuid4().hex,
            task_type=self.task_type,
            params=dict(self.params or {}),
            cancel_path=cancel_path,
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
    def from_dict(cls, data: dict[str, Any]) -> "BackgroundJob":
        return cls(
            job_id=str(data.get("job_id") or ""),
            task_type=str(data.get("task_type") or data.get("job_type") or ""),
            params=dict(data.get("params") or {}),
            cancel_path=str(data.get("cancel_path") or ""),
        )
