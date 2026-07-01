from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CloudSyncProfile:
    site_id: str
    provider: str = "wps"
    profile_name: str = "trackside_ap_business"
    enabled: bool = False
    auto_sync_after_export: bool = False
    sync_mode: str = "manual"
    auth_type: str = "bearer"
    access_token: str = ""
    refresh_token: str = ""
    token_expires_at: str = ""
    app_id: str = ""
    tenant_id: str = ""
    target_type: str = "ksheet"
    target_name: str = ""
    file_token: str = ""
    remote_url: str = ""
    permission_mode: str = "readonly_members"
    readonly_members: list[dict[str, str]] = field(default_factory=list)
    readonly_link_enabled: bool = False
    readonly_link_url: str = ""
    last_sync_at: str = ""
    last_sync_status: str = ""
    last_error_message: str = ""
    id: int | None = None


@dataclass(frozen=True)
class CloudSyncRun:
    site_id: str
    provider: str
    report_type: str
    profile_name: str
    action: str
    status: str
    file_token: str = ""
    rows_total: int = 0
    sheets_total: int = 0
    started_at: str = ""
    ended_at: str = ""
    elapsed_ms: int = 0
    error_message: str = ""
    local_export_path: str = ""
    remote_url: str = ""
    id: int | None = None


@dataclass(frozen=True)
class WpsReadonlyMember:
    account: str
    display_name: str = ""
    permission: str = "read"


@dataclass(frozen=True)
class WpsKSheetDocument:
    file_token: str
    name: str
    url: str = ""


@dataclass(frozen=True)
class WpsKSheetSheet:
    sheet_id: str | int
    name: str


@dataclass(frozen=True)
class WpsApiResult:
    ok: bool
    message: str = ""
    payload: dict | None = None


@dataclass(frozen=True)
class WpsShareLink:
    url: str
    permission: str = "read"


@dataclass(frozen=True)
class WpsSheetPayload:
    name: str
    headers: list[str]
    rows: list[list[object]]


@dataclass(frozen=True)
class WpsSyncResult:
    status: str
    message: str
    file_token: str = ""
    remote_url: str = ""
    rows_total: int = 0
    sheets_total: int = 0
    permission_status: str = "skipped"
    skipped_unchanged: bool = False
    error_message: str = ""

