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


class LocalFileEntryDTO(ApiModel):
    entry_id: str = Field(pattern=r"^fl1_[0-9a-f]{32}$")
    name: str
    is_dir: bool = False
    size_bytes: int | None = Field(default=None, ge=0)
    modified_at: str | None = None
    file_type: str = "file"
    downloadable: bool = False


class LocalFilePageDTO(ApiModel):
    site_id: str
    root_entry_id: str = Field(pattern=r"^fl1_[0-9a-f]{32}$")
    current_entry_id: str = Field(pattern=r"^fl1_[0-9a-f]{32}$")
    parent_entry_id: str = Field(pattern=r"^fl1_[0-9a-f]{32}$")
    current_label: str = ""
    items: list[LocalFileEntryDTO] = Field(default_factory=list)
    total: int = 0
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=500, ge=1, le=500)
    has_more: bool = False


class LocalDirectoryCreateRequestDTO(ApiModel):
    directory_id: str = Field(default="", max_length=80, pattern=r"^(|fl1_[0-9a-f]{32})$")
    device_id: str = Field(default="", max_length=120)
    name: str = Field(min_length=1, max_length=120)


class FileDownloadRequestDTO(ApiModel):
    file_ref: str = Field(default="", max_length=64, pattern=r"^(|fm1_[0-9a-f]{32})$")
    connection_id: str = Field(default="", max_length=80, pattern=r"^(|fc1_[0-9a-f]{32})$")
    remote_entry_id: str = Field(default="", max_length=80, pattern=r"^(|fe1_[0-9a-f]{32})$")
    local_directory_id: str = Field(default="", max_length=80, pattern=r"^(|fl1_[0-9a-f]{32})$")


class FileDownloadBatchRequestDTO(ApiModel):
    connection_id: str = Field(max_length=80, pattern=r"^fc1_[0-9a-f]{32}$")
    remote_entry_ids: list[str] = Field(min_length=1, max_length=100)
    local_directory_id: str = Field(default="", max_length=80, pattern=r"^(|fl1_[0-9a-f]{32})$")


class DeviceFileConnectionRequestDTO(ApiModel):
    device_id: str = Field(min_length=1, max_length=120)
    allow_sftp_setup: bool = False


class HostKeyTrustRequestDTO(ApiModel):
    challenge_id: str = Field(min_length=36, max_length=80, pattern=r"^hk1_[0-9a-f]{32}$")
    allow_sftp_setup: bool = False


class FileRemoteDeviceDTO(ApiModel):
    device_id: str
    name: str
    address: str
    group_id: int | None = None
    group_name: str = ""
    device_type: str = ""
    station: str = ""


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
    total: int = 0
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=500, ge=1, le=500)
    has_more: bool = False


class FileDesktopActionRequestDTO(ApiModel):
    device_id: str = Field(default="", max_length=120)
    local_entry_id: str = Field(default="", max_length=80, pattern=r"^(|fl1_[0-9a-f]{32})$")
    task_id: str = Field(default="", max_length=160)


class FileDesktopActionDTO(ApiModel):
    action: str
    action_ref: str = Field(default="", pattern=r"^(|fda1_[0-9a-f]{32})$")
    expires_at: str = ""
    accepted: bool = False
    integration_required: bool = True
    message: str


class FileDesktopActionResultDTO(ApiModel):
    action: str
    success: bool
    message: str


class FileDownloadResultDTO(ApiModel):
    result_kind: str = "managed_file"
    file_ref: str = Field(default="", pattern=r"^(|fm1_[0-9a-f]{32})$")
    device_file_ref: str = Field(default="", pattern=r"^(|fd1_[0-9a-f]{32})$")
    name: str
    size_bytes: int = Field(ge=0)
    artifact_id: str = Field(default="", pattern=r"^(|fa1_[0-9a-f]{32})$")
    relative_path: str = ""
    sha256: str = Field(default="", pattern=r"^(|[0-9a-f]{64})$")
    device_id: str = ""
    remote_entry_id: str = Field(default="", pattern=r"^(|fe1_[0-9a-f]{32})$")
    target_kind: str = ""
    mesh_import_status: str = ""
    mesh_imported_count: int = Field(default=0, ge=0)
    mesh_duplicate_count: int = Field(default=0, ge=0)
    mesh_parsed_record_count: int = Field(default=0, ge=0)
    mesh_import_error: str = ""


class FileDownloadTaskDTO(ApiModel):
    task_id: str
    site_id: str
    status: str
    progress: int = Field(ge=0, le=100)
    stage: str = ""
    message: str = ""
    batch_id: str = ""
    source_kind: str = ""
    device_name: str = ""
    remote_name: str = ""
    downloaded_bytes: int = Field(default=0, ge=0)
    total_bytes: int = Field(default=0, ge=0)
    speed_bytes_per_second: float = Field(default=0, ge=0)
    created_at: str = ""
    updated_at: str = ""
    retryable: bool = False
    retry_reason: str = ""
    result: FileDownloadResultDTO | None = None


class FileDownloadBatchDTO(ApiModel):
    batch_id: str
    tasks: list[FileDownloadTaskDTO] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)


class FileDownloadClearRequestDTO(ApiModel):
    statuses: list[str] = Field(min_length=1, max_length=3)


class FileDownloadClearDTO(ApiModel):
    cleared_count: int = Field(ge=0)


__all__ = [
    "DeviceFileConnectionRequestDTO",
    "FileConnectionDTO",
    "FileDesktopActionDTO",
    "FileDesktopActionResultDTO",
    "FileDesktopActionRequestDTO",
    "FileDownloadRequestDTO",
    "FileDownloadBatchRequestDTO",
    "FileDownloadBatchDTO",
    "FileDownloadClearDTO",
    "FileDownloadClearRequestDTO",
    "FileDownloadResultDTO",
    "FileDownloadTaskDTO",
    "FileManagementCapabilityDTO",
    "FileManagementStatusDTO",
    "FileRemoteDeviceDTO",
    "HostKeyTrustRequestDTO",
    "LocalDirectoryCreateRequestDTO",
    "LocalFileEntryDTO",
    "LocalFilePageDTO",
    "ManagedFileDTO",
    "ManagedFilePageDTO",
    "RemoteFileEntryDTO",
    "RemoteFilePageDTO",
]
