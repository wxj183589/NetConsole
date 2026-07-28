from __future__ import annotations

from typing import Literal

from pydantic import Field

from netconsole.models.api.common import ApiModel


class JobCenterArtifactDTO(ApiModel):
    artifact_id: str
    display_name: str
    size_bytes: int
    sha256: str = ""
    media_type: str
    api_path: str
    query: dict[str, str] = Field(default_factory=dict)


class JobCenterTaskDTO(ApiModel):
    id: str
    type: str
    name: str
    status: str
    progress: int = 0
    phase: str = ""
    stage: str = ""
    message: str = ""
    site_name: str = ""
    owner: str = ""
    executor: str = "LOCAL"
    source: str = "local"
    device_id: str = ""
    device_name: str = ""
    agent: str = ""
    mr_name: str = ""
    session_id: str = ""
    mapping_state: str = ""
    created_time: str = ""
    started_time: str = ""
    finished_time: str = ""
    expires_at: str = ""
    acknowledged_at: str = ""
    dismissed_at: str = ""
    updated_time: str = ""
    duration_seconds: float = 0.0
    error_code: str = ""
    error_summary: str = ""
    has_warning: bool = False
    text_integrity: str = "ok"
    text_integrity_reason: str = ""
    text_integrity_updated_at: str = ""
    text_schema_version: int = 1
    producer_kind: str = "legacy"
    producer_version: str = "unknown"
    producer_commit: str = "unknown"
    snapshot_id: int | None = None
    records_count: int | None = None
    parser_version: str = ""
    module: str = ""
    cancellable: bool = False
    cancel_reason: str = ""
    retryable: bool = False
    retry_reason: str = "当前任务 owner 未提供统一重试能力"
    artifact_download: JobCenterArtifactDTO | None = None
    artifact_reason: str = "当前任务 owner 未提供可下载 Artifact"
    details: dict[str, object] = Field(default_factory=dict)


class JobCenterSummaryDTO(ApiModel):
    total: int = 0
    active: int = 0
    completed: int = 0
    failed: int = 0
    warning: int = 0
    unacknowledged_failed: int = 0
    unacknowledged_warning: int = 0


JobCenterCleanupType = Literal[
    "completed",
    "cancelled",
    "expired",
    "completed_and_expired",
    "resolved_alerts",
    "all_history",
]


class JobCenterCleanupRequest(ApiModel):
    cleanup_type: JobCenterCleanupType
    site_id: str = ""
    include_states: list[str] = Field(default_factory=list)
    exclude_states: list[str] = Field(default_factory=list)
    delete_artifacts: bool = False
    dry_run: bool = False


class JobCenterCleanupCountsDTO(ApiModel):
    completed: int = 0
    cancelled: int = 0
    expired: int = 0
    alerts: int = 0


class JobCenterCleanupResultDTO(ApiModel):
    matched: int = 0
    dismissed: int = 0
    skipped_active: int = 0
    skipped_unacknowledged: int = 0
    artifacts_deleted: int = 0
    task_ids: list[str] = Field(default_factory=list)
    counts: JobCenterCleanupCountsDTO = Field(default_factory=JobCenterCleanupCountsDTO)


class JobCenterAcknowledgeRequest(ApiModel):
    task_ids: list[str] = Field(default_factory=list)
    all_alerts: bool = False


class JobCenterAcknowledgeResultDTO(ApiModel):
    acknowledged: int = 0
    task_ids: list[str] = Field(default_factory=list)
    acknowledged_at: str = ""


class JobCenterLogLineDTO(ApiModel):
    sequence: int
    time: str
    level: str = "INFO"
    type: str
    source: str = "service"
    message: str
    details: dict[str, object] = Field(default_factory=dict)


class JobCenterLogTailDTO(ApiModel):
    task_id: str
    lines: list[JobCenterLogLineDTO] = Field(default_factory=list)
    message: str = ""


__all__ = [
    "JobCenterLogLineDTO",
    "JobCenterArtifactDTO",
    "JobCenterLogTailDTO",
    "JobCenterCleanupCountsDTO",
    "JobCenterCleanupRequest",
    "JobCenterCleanupResultDTO",
    "JobCenterAcknowledgeRequest",
    "JobCenterAcknowledgeResultDTO",
    "JobCenterSummaryDTO",
    "JobCenterTaskDTO",
]
