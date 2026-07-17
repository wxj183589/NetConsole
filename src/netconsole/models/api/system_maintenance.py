from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from netconsole.models.api.common import ApiModel


class LogEntryDTO(ApiModel):
    time: str
    level: str
    display_level: str
    display_event: str
    display_detail: str
    raw_event: str
    raw_detail: str


class LogPageDTO(ApiModel):
    items: list[LogEntryDTO] = Field(default_factory=list)
    page: int
    page_size: int
    total: int
    total_pages: int


class CleanupItemDTO(ApiModel):
    item_id: str
    title: str
    description: str
    retention_policy: str
    status: str
    file_count: int
    total_bytes: int


class OpenSourceComponentDTO(ApiModel):
    name: str
    version: str
    license: str
    purpose: str
    homepage: str
    note: str


class MaintenanceTaskDTO(ApiModel):
    task_id: str
    status: str
    action: str
    progress: int = 0
    stage: str = ""
    message: str = ""
    error_message: str = ""
    artifact_id: str = ""
    artifact_kind: str = ""
    artifact_name: str = ""
    available: bool = False
    sha256: str = ""
    size_bytes: int = 0
    cleanup_items: list[CleanupItemDTO] = Field(default_factory=list)
    processed_files: int = 0
    deleted_files: int = 0
    failed_count: int = 0
    freed_bytes: int = 0
    components: list[OpenSourceComponentDTO] = Field(default_factory=list)


class CleanupStartRequest(ApiModel):
    mode: Literal["scan", "clean"] = "scan"
    retention_days: int = Field(default=3, ge=1, le=365)
    selected_item_ids: list[Literal["runtime_logs", "runtime_cache", "temporary_files"]] = Field(
        default_factory=list,
        max_length=3,
    )
    confirmed: bool = False

    @model_validator(mode="after")
    def validate_cleanup_contract(self) -> "CleanupStartRequest":
        if len(self.selected_item_ids) != len(set(self.selected_item_ids)):
            raise ValueError("清理项目不能重复")
        if self.mode == "scan":
            if self.selected_item_ids or self.confirmed:
                raise ValueError("扫描请求只能包含保留天数")
            return self
        if not self.selected_item_ids:
            raise ValueError("正式清理至少选择一个项目")
        if not self.confirmed:
            raise ValueError("正式清理必须明确确认")
        return self


class LogExportRequest(ApiModel):
    scope: Literal["current", "all"]
    keyword: str = Field(default="", max_length=200)
    level: Literal["", "INFO", "WARNING", "ERROR", "DEBUG", "CRITICAL"] = ""
    page: int = Field(default=1, ge=1, le=1_000_000)
    page_size: Literal[50, 100, 200, 500] = 200


class OpenSourceExportRequest(ApiModel):
    format: Literal["txt", "xlsx"]


class ChangelogDTO(ApiModel):
    title: str
    version: str
    content: str


class AboutLinkDTO(ApiModel):
    link_id: str
    label: str


class AboutDTO(ApiModel):
    title: str
    version: str
    author: str
    external_tool_notice: str
    repositories: list[AboutLinkDTO]


class DesktopActionDTO(ApiModel):
    success: bool
    code: str
    message: str = ""


class ExternalLinkDTO(ApiModel):
    url: str


__all__ = [
    "AboutDTO",
    "AboutLinkDTO",
    "ChangelogDTO",
    "CleanupItemDTO",
    "CleanupStartRequest",
    "DesktopActionDTO",
    "ExternalLinkDTO",
    "LogEntryDTO",
    "LogExportRequest",
    "LogPageDTO",
    "MaintenanceTaskDTO",
    "OpenSourceComponentDTO",
    "OpenSourceExportRequest",
]
