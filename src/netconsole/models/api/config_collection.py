from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from netconsole.models.api.common import ApiModel


class ConfigDeviceGroupDTO(ApiModel):
    id: int
    name: str
    device_count: int = 0


class ConfigDeviceDTO(ApiModel):
    id: int
    device_uuid: str
    name: str
    system_name: str = ""
    device_type: str = ""
    station: str = ""
    group_id: int | None = None


class ConfigDevicePageDTO(ApiModel):
    items: list[ConfigDeviceDTO] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    total_pages: int = 1
    groups: list[ConfigDeviceGroupDTO] = Field(default_factory=list)


class ConfigSnapshotDTO(ApiModel):
    id: int
    device_id: int | None = None
    device_uuid: str
    timestamp: str
    type: str
    size_bytes: int = 0
    artifact_id: str
    filename: str
    created_at: str = ""
    error_message: str = ""


class ConfigTaskReferenceDTO(ApiModel):
    id: str
    type: str
    status: str
    progress: int = 0
    device_id: str = ""
    device_name: str = ""
    message: str = ""


class ConfigTaskStatusDTO(ConfigTaskReferenceDTO):
    stage: str = ""
    created_time: str = ""
    started_time: str = ""
    finished_time: str = ""
    error_message: str = ""
    result: dict[str, Any] = Field(default_factory=dict)


class ConfigActionRequest(ApiModel):
    action: Literal["fetch"] = "fetch"
    device_ids: list[int] = Field(min_length=1, max_length=50)


class ConfigSnapshotDiffRequest(ApiModel):
    left_snapshot_id: int = Field(ge=1)
    right_snapshot_id: int = Field(ge=1)


class ConfigDeviceDiffRequest(ApiModel):
    left_device_id: int = Field(ge=1)
    right_device_id: int = Field(ge=1)


__all__ = [
    "ConfigDeviceDTO",
    "ConfigActionRequest",
    "ConfigDeviceDiffRequest",
    "ConfigDeviceGroupDTO",
    "ConfigDevicePageDTO",
    "ConfigSnapshotDTO",
    "ConfigSnapshotDiffRequest",
    "ConfigTaskReferenceDTO",
    "ConfigTaskStatusDTO",
]
