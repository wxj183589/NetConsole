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
    winscp: FileManagementCapabilityDTO = FileManagementCapabilityDTO(available=False, message="")


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
    file_ref: str = Field(default="", max_length=64, pattern=r"^(|fm1_[0-9a-f]{32})$")
    connection_id: str = Field(default="", max_length=80, pattern=r"^(|fc1_[0-9a-f]{32})$")
    remote_entry_id: str = Field(default="", max_length=80, pattern=r"^(|fe1_[0-9a-f]{32})$")


class DeviceFileConnectionRequestDTO(ApiModel):
    device_id: str = Field(min_length=1, max_length=120)


class FileRemoteDeviceDTO(ApiModel):
    device_id: str
    name: str
    address: str


class FileConnectionDTO(ApiModel):
    connection_id: str = Field(pattern=r"^fc1_[0-9a-f]{32}$")
    device_id: str
    device_name: str = ""
    status: str
    root_entry_id: str = Field(pattern=r"^fe1_[0-9a-f]{32}$")
    current_entry_id: str = Field(pattern=r"^fe1_[0-9a-f]{32}$")
    current_label: str = ""
    message: str = ""


class RemoteFileEntryDTO(ApiModel):
    entry_id: str = Field(pattern=r"^fe1_[0-9a-f]{32}$")
    name: str
    is_dir: bool = False
    size_bytes: int | None = Field(default=None, ge=0)
    modified_at: str | None = None
    category: str = ""
    file_type: str = "file"
    downloadable: bool = False


class RemoteFilePageDTO(ApiModel):
    connection_id: str = Field(pattern=r"^fc1_[0-9a-f]{32}$")
    current_entry_id: str = Field(pattern=r"^fe1_[0-9a-f]{32}$")
    parent_entry_id: str = Field(pattern=r"^fe1_[0-9a-f]{32}$")
    current_label: str = ""
    items: list[RemoteFileEntryDTO] = Field(default_factory=list)


class FileDesktopActionRequestDTO(ApiModel):
    device_id: str = Field(default="", max_length=120)
    artifact_id: str = Field(default="", max_length=80)


class FileDesktopActionDTO(ApiModel):
    action: str
    accepted: bool = False
    integration_required: bool = True
    message: str


class FileDownloadResultDTO(ApiModel):
    file_ref: str = Field(default="", pattern=r"^(|fm1_[0-9a-f]{32})$")
    name: str
    size_bytes: int = Field(ge=0)
    artifact_id: str = Field(default="", pattern=r"^(|fa1_[0-9a-f]{32})$")
    relative_path: str = ""
    sha256: str = Field(default="", pattern=r"^(|[0-9a-f]{64})$")
    device_id: str = ""
    remote_entry_id: str = Field(default="", pattern=r"^(|fe1_[0-9a-f]{32})$")


class FileDownloadTaskDTO(ApiModel):
    task_id: str
    site_id: str
    status: str
    progress: int = Field(ge=0, le=100)
    stage: str = ""
    message: str = ""
    result: FileDownloadResultDTO | None = None


__all__ = [
    "DeviceFileConnectionRequestDTO",
    "FileConnectionDTO",
    "FileDesktopActionDTO",
    "FileDesktopActionRequestDTO",
    "FileDownloadRequestDTO",
    "FileDownloadResultDTO",
    "FileDownloadTaskDTO",
    "FileManagementCapabilityDTO",
    "FileManagementStatusDTO",
    "FileRemoteDeviceDTO",
    "ManagedFileDTO",
    "ManagedFilePageDTO",
    "RemoteFileEntryDTO",
    "RemoteFilePageDTO",
]
