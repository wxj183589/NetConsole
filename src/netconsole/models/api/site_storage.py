from __future__ import annotations

from typing import Literal

from pydantic import Field

from netconsole.models.api.common import ApiModel


class SiteCreateRequest(ApiModel):
    site_id: str = Field(min_length=1, max_length=63)
    display_name: str = Field(min_length=1, max_length=128)
    remark: str = Field(default="", max_length=500)
    activate: bool = False


class SiteActivateRequest(ApiModel):
    confirmed: bool = True


class SiteMigrateRequest(ApiModel):
    destination_root: str = Field(min_length=1, max_length=32_767)


class SiteExportRequest(ApiModel):
    destination_path: str = Field(default="", max_length=32_767)
    package_type: Literal["full_migration", "field_collection", "collection_return"] = "full_migration"


class SiteImportInspectRequest(ApiModel):
    package_path: str = Field(min_length=1, max_length=32_767)
    target_site_id: str = Field(default="", max_length=63)


class SiteConflictResolution(ApiModel):
    conflict_id: str = Field(min_length=1, max_length=128)
    choice: Literal["local", "returned", "manual"]
    manual_value: object | None = None


class SiteImportRequest(ApiModel):
    package_path: str = Field(min_length=1, max_length=32_767)
    site_id: str = Field(default="", max_length=63)
    display_name: str = Field(default="", max_length=128)
    replace_site_id: str = Field(default="", max_length=63)
    activate: bool = False
    raw_only: bool = False
    conflict_resolutions: list[SiteConflictResolution] = Field(default_factory=list, max_length=2_000)


class DataRootPathRequest(ApiModel):
    path: str = Field(min_length=1, max_length=32_767)


class SiteTaskResponse(ApiModel):
    task_id: str
    task_type: str


class SiteCleanupApplyRequest(ApiModel):
    cleanup_token: str = Field(min_length=16, max_length=128)
    confirmed: bool = False


class SiteCleanupRestoreRequest(ApiModel):
    confirmed: bool = False


class SiteDemoRebuildRequest(ApiModel):
    confirmed: bool = False
    allow_user_data: bool = False


class SiteAuditSummaryResponse(ApiModel):
    display_name: str
    site_id: str
    total_size: int
    file_count: int
    directory_count: int
    is_current: bool
    is_registered: bool
    is_referenced_by_bootstrap: bool
    is_demo: bool
    managed_demo: bool
    demo_seed_version: str
    migration_status: str
    raw_log_count: int
    parsed_database_count: int
    report_count: int
    artifact_count: int
    task_count: int
    online_mr_session_count: int
    mesh_source_count: int
    unique_business_data: bool
    duplicate_candidates: list[str]
    referenced_records: list[str]
    classification: str
    recommended_action: str
    can_delete: bool
    safe_to_replace: bool
    demo_pristine: bool = False
    legacy_demo_replaceable: bool = False
    unsafe_entry_count: int = 0
    unknown_file_count: int = 0


class SiteCleanupPlanResponse(ApiModel):
    cleanup_token: str
    site_id: str
    classification: str
    blocking_reasons: list[str]
    recoverable: bool
    can_delete: bool


__all__ = [
    "DataRootPathRequest", "SiteActivateRequest", "SiteCreateRequest", "SiteExportRequest",
    "SiteConflictResolution", "SiteImportInspectRequest", "SiteImportRequest", "SiteMigrateRequest", "SiteTaskResponse",
    "SiteCleanupApplyRequest", "SiteCleanupRestoreRequest", "SiteDemoRebuildRequest", "SiteAuditSummaryResponse", "SiteCleanupPlanResponse",
]
