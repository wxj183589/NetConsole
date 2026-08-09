from __future__ import annotations

from typing import Any

from pydantic import Field

from netconsole.models.api.common import ApiModel


class WpsSyncTargetDTO(ApiModel):
    target_id: str
    site_id: str
    business_key: str
    target_code: str
    target_type: str
    target_name: str
    document_open_url: str
    webhook_url: str
    expected_document_id: str
    expected_script_version: str = ""
    expected_deployment_id: str = ""
    expected_script_id: str = ""
    runtime_capability: str = "RUNTIME_UNVERIFIED"
    last_runtime_probe_at: str = ""
    runtime_probe_document_id: str = ""
    runtime_probe_script_id: str = ""
    runtime_probe_script_version: str = ""
    runtime_probe_deployment_id: str = ""
    binding_status: str = "UNKNOWN"
    binding_id: str = ""
    remote_binding_id: str = ""
    remote_site_id: str = ""
    remote_site_name: str = ""
    remote_business_key: str = ""
    connection_diagnostic: dict[str, Any] = Field(default_factory=dict)
    runtime_probe_diagnostic: dict[str, Any] = Field(default_factory=dict)
    sync_test_diagnostic: dict[str, Any] = Field(default_factory=dict)
    sheet_tab_color_probe_diagnostic: dict[str, Any] = Field(default_factory=dict)
    column_width_probe_diagnostic: dict[str, Any] = Field(default_factory=dict)
    remote_script_version: str = ""
    remote_deployment_id: str = ""
    remote_script_id: str = ""
    remote_identity_verified_at: str = ""
    enabled: bool
    protocol_version: int
    timeout_seconds: int
    token_configured: bool
    token_suffix: str = ""
    last_test_at: str = ""
    last_test_status: str = ""
    last_test_message: str = ""
    last_sync_at: str = ""
    last_sync_status: str = ""
    last_sync_revision: str = ""


class WpsSyncTargetUpdateDTO(ApiModel):
    token: str | None = Field(default=None, min_length=1, max_length=4096)
    document_open_url: str | None = Field(default=None, min_length=1, max_length=2048)
    webhook_url: str | None = Field(default=None, min_length=1, max_length=2048)
    enabled: bool | None = None
    timeout_seconds: int | None = Field(default=None, ge=5, le=120)


class WpsSyncRequestDTO(ApiModel):
    target_codes: list[str] = Field(default_factory=list, max_length=1)
    expected_revision: str = Field(default="", max_length=128)
    initialize_binding: bool = False


class WpsSyncConnectionTestDTO(ApiModel):
    target_code: str
    result: dict[str, Any] = Field(default_factory=dict)


class WpsSyncResponseDTO(ApiModel):
    batch_id: str
    site_id: str
    business_key: str
    snapshot_revision: str
    snapshot_sha256: str
    snapshot_generated_at: str
    payload_bytes: int
    sheet_count: int
    status: str
    targets: list[dict[str, Any]] = Field(default_factory=list)


class WpsSyncRecentBatchesDTO(ApiModel):
    items: list[dict[str, Any]] = Field(default_factory=list)


__all__ = [
    "WpsSyncConnectionTestDTO",
    "WpsSyncRecentBatchesDTO",
    "WpsSyncRequestDTO",
    "WpsSyncResponseDTO",
    "WpsSyncTargetDTO",
    "WpsSyncTargetUpdateDTO",
]
