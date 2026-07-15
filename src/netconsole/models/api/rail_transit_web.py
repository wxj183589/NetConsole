from __future__ import annotations

from typing import Any

from pydantic import Field

from netconsole.models.api.common import ApiModel


class RailTransitTaskDTO(ApiModel):
    task_id: str
    task_type: str
    status: str = "PENDING"
    message: str = ""
    artifact_path: str = ""


class OnlineMrReportRequestDTO(ApiModel):
    site_id: str = ""
    output_name: str = ""


class RailTransitTaskRequestDTO(ApiModel):
    site_id: str = ""
    ac_id: str = ""
    train_id: str = ""


class OnlineMrTimelineQueryDTO(ApiModel):
    limit: int = 500
    offset: int = 0


class RailTransitExportDTO(ApiModel):
    task_id: str
    artifact_path: str = ""
    sha256: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "OnlineMrReportRequestDTO",
    "OnlineMrTimelineQueryDTO",
    "RailTransitExportDTO",
    "RailTransitTaskDTO",
    "RailTransitTaskRequestDTO",
]
