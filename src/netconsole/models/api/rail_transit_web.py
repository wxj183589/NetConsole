from __future__ import annotations

from netconsole.models.api.common import ApiModel


class RailTransitTaskDTO(ApiModel):
    task_id: str
    status: str = "PENDING"
    action: str
    artifact_id: str = ""
    available: bool = False
    sha256: str = ""
    size_bytes: int = 0


class OnlineMrReportRequestDTO(ApiModel):
    output_name: str = ""


class RailTransitTaskRequestDTO(ApiModel):
    train_id: str = ""


class OnlineMrTimelineQueryDTO(ApiModel):
    limit: int = 500
    offset: int = 0


__all__ = [
    "OnlineMrReportRequestDTO",
    "OnlineMrTimelineQueryDTO",
    "RailTransitTaskDTO",
    "RailTransitTaskRequestDTO",
]
