from __future__ import annotations

from pydantic import Field

from netconsole.models.api.common import ApiModel


class FileManagementCapabilityDTO(ApiModel):
    available: bool
    message: str = ""


class FileManagementStatusDTO(ApiModel):
    site_id: str
    local_files: FileManagementCapabilityDTO
    device_files: FileManagementCapabilityDTO


class ManagedFileDTO(ApiModel):
    file_ref: str = Field(pattern=r"^fm1_[0-9a-f]{32}$")
    site_id: str
    category: str
    name: str
    relative_path: str
    size_bytes: int = Field(ge=0)
    modified_at: str | None = None
    downloadable: bool = True


class ManagedFilePageDTO(ApiModel):
    site_id: str
    category: str = ""
    items: list[ManagedFileDTO] = Field(default_factory=list)
    total: int = 0


class FileDownloadRequestDTO(ApiModel):
    file_ref: str = Field(min_length=1, max_length=64, pattern=r"^fm1_[0-9a-f]{32}$")


class FileDownloadResultDTO(ApiModel):
    file_ref: str = Field(pattern=r"^fm1_[0-9a-f]{32}$")
    name: str
    size_bytes: int = Field(ge=0)


class FileDownloadTaskDTO(ApiModel):
    task_id: str
    site_id: str
    status: str
    progress: int = Field(ge=0, le=100)
    stage: str = ""
    message: str = ""
    result: FileDownloadResultDTO | None = None


__all__ = [
    "FileDownloadRequestDTO",
    "FileDownloadResultDTO",
    "FileDownloadTaskDTO",
    "FileManagementCapabilityDTO",
    "FileManagementStatusDTO",
    "ManagedFileDTO",
    "ManagedFilePageDTO",
]
