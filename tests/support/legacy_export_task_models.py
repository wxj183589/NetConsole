from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from netconsole.services.export.export_job import ExportJob, normalize_export_path
from netconsole.services.export.export_progress import error_event, finished_event, progress_event


@dataclass(frozen=True)
class ExportProgress:
    job_id: str
    stage: str
    done: int
    total: int
    message: str

    def to_event(self) -> dict[str, Any]:
        return progress_event(
            self.job_id,
            self.stage,
            current=self.done,
            total=self.total,
            message=self.message,
        )


@dataclass(frozen=True)
class ExportResult:
    job_id: str
    ok: bool
    output_path: str
    error: str = ""
    cancelled: bool = False

    def to_event(self) -> dict[str, Any]:
        if self.ok:
            event = finished_event(self.job_id, self.output_path)
        else:
            event = error_event(self.job_id, self.error or "导出失败", output_path=self.output_path, cancelled=self.cancelled)
        event["type"] = "result"
        return event


__all__ = [
    "ExportJob",
    "ExportProgress",
    "ExportResult",
    "normalize_export_path",
]
