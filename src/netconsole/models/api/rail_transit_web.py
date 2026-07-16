from __future__ import annotations

from pydantic import Field

from netconsole.models.api.common import ApiModel


class RailTransitTaskDTO(ApiModel):
    task_id: str
    status: str = "PENDING"
    action: str
    artifact_id: str = ""
    available: bool = False
    sha256: str = ""
    size_bytes: int = 0
    message: str = ""
    error_message: str = ""
    result_summary: dict[str, object] = Field(default_factory=dict)


class OnlineMrReportRequestDTO(ApiModel):
    output_name: str = ""


class OnlineMrTimelineQueryDTO(ApiModel):
    limit: int = 500
    offset: int = 0


__all__ = [
    "OnlineMrReportRequestDTO",
    "OnlineMrTimelineQueryDTO",
    "RailTransitTaskDTO",
]
