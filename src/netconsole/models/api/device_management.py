from __future__ import annotations

from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator

from netconsole.models.api.common import ApiModel
from netconsole.models.device import (
    ProjectPhase,
    WorkScopeStatus,
    normalize_device_vendor,
    normalize_project_phase,
    normalize_work_scope_status,
    validate_device_vendor_type,
)


DeviceConnectionStatus = Literal[
    "UNKNOWN",
    "TESTING",
    "REACHABLE",
    "UNREACHABLE",
    "AUTH_FAILED",
    "ERROR",
]
DeviceConnectionProtocol = Literal["SSH", "TELNET", "SNMP"]
DeviceBatchRefreshStatus = Literal[
    "ACCEPTED",
    "REUSED",
    "REJECTED",
    "RUNNING",
    "COMPLETED",
    "PARTIAL_SUCCESS",
    "FAILED",
    "CANCELLED",
]
DeviceImportMatchStrategy = Literal[
    "LEGACY_APPEND", "DEVICE_ID", "SITE_PRIMARY_IP", "DEVICE_NAME"
]
DeviceImportWriteMode = Literal["CREATE_ONLY", "UPDATE_ONLY", "UPSERT"]
DeviceSecretField = Literal[
    "ssh_password",
    "telnet_password",
    "tunnel1_password",
    "tunnel2_password",
    "snmp_ro_community",
]
ProjectPhaseValue = Literal[
    "phase_1", "phase_2", "phase_3", "other", "unspecified"
]
WorkScopeStatusValue = Literal["included", "excluded"]


class DeviceCapabilityDTO(ApiModel):
    ssh: bool = False
    ssh_port: int | None = None
    telnet: bool = False
    telnet_port: int | None = None
    snmp: bool = False
    snmp_versions: list[str] = Field(default_factory=list)
    snmp_port: int | None = None


class DeviceGroupOptionDTO(ApiModel):
    id: int
    name: str


class DeviceListItemDTO(ApiModel):
    id: int
    device_uuid: str
    name: str
    system_name: str = ""
    station: str = ""
    group_id: int | None = None
    group_name: str = "未分组"
    device_vendor: str = ""
    device_type: str = ""
    project_phase: ProjectPhaseValue = "unspecified"
    work_scope_status: WorkScopeStatusValue = "included"
    work_scope_reason: str = ""
    work_scope_updated_at: str = ""
    primary_address: str = ""
    backup_address: str = ""
    updated_at: str = ""
    metadata_updated_at: str = ""
    last_collected_at: str = ""
    last_collect_status: str = ""
    last_collect_task_id: str = ""
    capabilities: DeviceCapabilityDTO
    connection_status: DeviceConnectionStatus = "UNKNOWN"
    last_test_task_id: str = ""
    last_test_time: str = ""
    credential_status: str = "missing"
    credential_source: str = "none"
    credential_error_code: str = "CREDENTIAL_MISSING"
    credential_message: str = ""


class DevicePageDTO(ApiModel):
    items: list[DeviceListItemDTO] = Field(default_factory=list)
    groups: list[DeviceGroupOptionDTO] = Field(default_factory=list)
    site_name: str = ""
    total: int = 0
    page: int = 1
    page_size: int = 50
    total_pages: int = 1


class DeviceFactDTO(ApiModel):
    system_name: str = ""
    model: str = ""
    serial_number: str = ""
    mac_address: str = ""
    software_version: str = ""
    bootrom_version: str = ""
    vendor: str = ""
    uptime: str = ""
    collected_at: str = ""


class DeviceTaskSummaryDTO(ApiModel):
    task_id: str
    task_type: str
    task_name: str
    status: str
    stage: str = ""
    message: str = ""
    created_time: str = ""
    updated_time: str = ""
    error_summary: str = ""


class DeviceCollectionSummaryDTO(ApiModel):
    collect_run_uuid: str
    collect_type: str
    status: str
    started_at: str
    ended_at: str = ""
    error_summary: str = ""


class DeviceErrorSummaryDTO(ApiModel):
    source: Literal["task", "collection"]
    time: str
    message: str


class DeviceConnectionCommandDTO(ApiModel):
    protocol: Literal["SSH", "TELNET"]
    command: str


class DeviceDetailItemDTO(DeviceListItemDTO):
    location: str = ""
    mac_address: str = ""
    https_port: int | None = None
    web_url: str = ""
    ssh_username: str = ""
    telnet_username: str = ""
    tunnel_enabled: bool = False
    tunnel1_enabled: bool = False
    tunnel1_host: str = ""
    tunnel1_port: int | None = None
    tunnel1_username: str = ""
    tunnel2_enabled: bool = False
    tunnel2_host: str = ""
    tunnel2_port: int | None = None
    tunnel2_username: str = ""
    snmp_v1_enabled: bool = False
    snmp_v2c_enabled: bool = False
    snmp_timeout_ms: int = 2000
    snmp_retries: int = 1
    ssh_secret_configured: bool = False
    telnet_secret_configured: bool = False
    tunnel1_secret_configured: bool = False
    tunnel2_secret_configured: bool = False
    snmp_ro_secret_configured: bool = False
    remark: str = ""
    created_at: str = ""


class DeviceEditProfileDTO(DeviceDetailItemDTO):
    """设备编辑所需的非敏感事实；秘密只返回是否已配置。"""

    protocol: str | None = None
    port: int | None = None
    ssh_enabled: bool = False
    ssh_port: int = 22
    telnet_enabled: bool = False
    telnet_port: int = 23
    snmp_enabled: bool = False
    snmp_port: int = 161


class DeviceCredentialRevealDTO(ApiModel):
    """仅供受保护的本机桌面会话按用户动作读取。"""

    device_uuid: str
    credential_field: DeviceSecretField
    value: str = ""


class DeviceDetailDTO(ApiModel):
    device: DeviceDetailItemDTO
    fact: DeviceFactDTO | None = None
    recent_tasks: list[DeviceTaskSummaryDTO] = Field(default_factory=list)
    recent_collection: DeviceCollectionSummaryDTO | None = None
    recent_errors: list[DeviceErrorSummaryDTO] = Field(default_factory=list)
    connection_commands: list[DeviceConnectionCommandDTO] = Field(default_factory=list)
    interfaces: list[dict[str, object | None]] = Field(default_factory=list)
    optical_modules: list[dict[str, object | None]] = Field(default_factory=list)
    lldp_neighbors: list[dict[str, object | None]] = Field(default_factory=list)
    trackside_ap_business: list[dict[str, object | None]] = Field(default_factory=list)


class DeviceWriteRequestDTO(ApiModel):
    """设备写入字段；普通详情不读秘密，清除必须显式声明。"""

    name: str = Field(min_length=1, max_length=120)
    system_name: str = Field(default="", max_length=120)
    station: str = Field(default="", max_length=120)
    location: str = Field(default="", max_length=200)
    group_id: int | None = Field(default=None, ge=1)
    device_vendor: str = Field(default="H3C", max_length=40)
    device_type: str = Field(default="SW", max_length=40)
    project_phase: ProjectPhaseValue = ProjectPhase.UNSPECIFIED.value
    work_scope_status: WorkScopeStatusValue = WorkScopeStatus.INCLUDED.value
    work_scope_reason: str = Field(default="", max_length=1000)
    primary_address: str = Field(default="", max_length=255)
    backup_address: str = Field(default="", max_length=255)
    ssh_enabled: bool = True
    ssh_port: int = Field(default=22, ge=1, le=65535)
    telnet_enabled: bool = False
    telnet_port: int = Field(default=23, ge=1, le=65535)
    snmp_enabled: bool = True
    snmp_v1_enabled: bool = False
    snmp_v2c_enabled: bool = True
    snmp_port: int = Field(default=161, ge=1, le=65535)
    https_port: int | None = Field(default=None, ge=1, le=65535)
    remark: str = Field(default="", max_length=1000)
    ssh_username: str = Field(default="", max_length=255)
    ssh_password: SecretStr | None = Field(default=None, repr=False)
    telnet_username: str = Field(default="", max_length=255)
    telnet_password: SecretStr | None = Field(default=None, repr=False)
    tunnel_enabled: bool = False
    tunnel1_enabled: bool = False
    tunnel1_host: str = Field(default="", max_length=255)
    tunnel1_port: int | None = Field(default=22, ge=1, le=65535)
    tunnel1_username: str = Field(default="", max_length=255)
    tunnel1_password: SecretStr | None = Field(default=None, repr=False)
    tunnel2_enabled: bool = False
    tunnel2_host: str = Field(default="", max_length=255)
    tunnel2_port: int | None = Field(default=22, ge=1, le=65535)
    tunnel2_username: str = Field(default="", max_length=255)
    tunnel2_password: SecretStr | None = Field(default=None, repr=False)
    snmp_ro_community: SecretStr | None = Field(default=None, repr=False)
    snmp_timeout_ms: int = Field(default=2000, ge=100, le=60000)
    snmp_retries: int = Field(default=1, ge=0, le=10)
    clear_secret_fields: list[DeviceSecretField] = Field(
        default_factory=list, max_length=5
    )

    @field_validator("device_vendor", mode="before")
    @classmethod
    def normalize_vendor(cls, value: object) -> str:
        return normalize_device_vendor(value)

    @field_validator("project_phase", mode="before")
    @classmethod
    def normalize_phase(cls, value: object) -> str:
        return normalize_project_phase(value)

    @field_validator("work_scope_status", mode="before")
    @classmethod
    def normalize_status(cls, value: object) -> str:
        return normalize_work_scope_status(value)

    @model_validator(mode="after")
    def validate_supported_vendor_type(self) -> "DeviceWriteRequestDTO":
        self.device_vendor, self.device_type = validate_device_vendor_type(
            self.device_vendor, self.device_type
        )
        return self


class DeviceFormConnectionTestRequestDTO(DeviceWriteRequestDTO):
    protocol: DeviceConnectionProtocol
    device_uuid: str = Field(default="", max_length=64)


class DeviceWriteDTO(ApiModel):
    action: Literal["created", "updated", "duplicated"]
    device: DeviceDetailItemDTO


class DeviceGroupDTO(DeviceGroupOptionDTO):
    device_count: int = 0


class DeviceGroupRequestDTO(ApiModel):
    name: str = Field(min_length=1, max_length=64)


class DeviceGroupAssignmentRequestDTO(ApiModel):
    device_uuids: list[str] = Field(min_length=1, max_length=500)
    group_id: int | None = Field(default=None, ge=1)


class DeviceGroupAssignmentDTO(ApiModel):
    success: int
    failed: int
    group_id: int | None = None


class DeviceClassificationUpdateRequestDTO(ApiModel):
    device_uuids: list[str] = Field(min_length=1, max_length=500)
    project_phase: ProjectPhaseValue | None = None
    work_scope_status: WorkScopeStatusValue | None = None
    reason: str = Field(default="", max_length=1000)

    @field_validator("project_phase", mode="before")
    @classmethod
    def normalize_phase(cls, value: object) -> str | None:
        return None if value is None else normalize_project_phase(value)

    @field_validator("work_scope_status", mode="before")
    @classmethod
    def normalize_status(cls, value: object) -> str | None:
        return None if value is None else normalize_work_scope_status(value)

    @model_validator(mode="after")
    def validate_change(self) -> "DeviceClassificationUpdateRequestDTO":
        if self.project_phase is None and self.work_scope_status is None:
            raise ValueError("至少提供建设阶段或当前工作状态")
        return self


class DeviceClassificationUpdateDTO(ApiModel):
    updated: int


class DeviceGroupDeleteDTO(ApiModel):
    deleted: bool = True


class DeviceDeletionTokenRequestDTO(ApiModel):
    device_uuids: list[str] = Field(min_length=1, max_length=500)


class DeviceDeletionTokenDTO(ApiModel):
    confirmation_token: str
    device_uuids: list[str]
    expires_at: str


class DeviceDeleteRequestDTO(DeviceDeletionTokenRequestDTO):
    confirmation_token: str = Field(min_length=16, max_length=256)


class DeviceDeleteDTO(ApiModel):
    deleted: int
    device_uuids: list[str]


class DeviceTaskReferenceDTO(ApiModel):
    task_id: str
    task_status: str
    action: str
    artifact_id: str = ""
    available: bool = False
    sha256: str = ""
    size_bytes: int = 0
    row_count: int = 0
    message: str = ""


class DeviceBatchRefreshItemDTO(ApiModel):
    device_uuid: str
    device_name: str = ""
    primary_address: str = ""
    vendor: str = ""
    device_type: str = ""
    profile_id: str = ""
    profile_version: int | None = None
    submission_status: Literal["ACCEPTED", "REUSED", "REJECTED"]
    status: DeviceBatchRefreshStatus
    task_id: str = ""
    task_status: str = ""
    collect_run_uuid: str = ""
    facts_updated: bool = False
    interfaces_updated: int = 0
    optical_modules_updated: int = 0
    lldp_neighbors_updated: int = 0
    started_at: str = ""
    finished_at: str = ""
    last_collected_at: str = ""
    error_message: str = ""


class DeviceBatchRefreshSummaryDTO(ApiModel):
    total: int = 0
    accepted: int = 0
    reused: int = 0
    rejected: int = 0
    running: int = 0
    completed: int = 0
    partial_success: int = 0
    failed: int = 0
    cancelled: int = 0


class DeviceTaskBatchDTO(ApiModel):
    action: str
    tasks: list[DeviceTaskReferenceDTO] = Field(default_factory=list)
    batch_id: str = ""
    created_at: str = ""
    finished_at: str = ""
    terminal: bool = False
    summary: DeviceBatchRefreshSummaryDTO = Field(
        default_factory=DeviceBatchRefreshSummaryDTO
    )
    items: list[DeviceBatchRefreshItemDTO] = Field(default_factory=list)


class DeviceBatchRefreshRequestDTO(ApiModel):
    device_uuids: list[str] = Field(min_length=1, max_length=200)


class DeviceBatchConnectionRequestDTO(ApiModel):
    device_uuids: list[str] = Field(min_length=1, max_length=200)


class DeviceImportPreviewRequestDTO(ApiModel):
    """CSV preview is multipart upload; browser paths are not accepted."""


class DeviceImportErrorDTO(ApiModel):
    line: int = 0
    device_name: str = ""
    field: str = ""
    raw_value: str = ""
    message: str
    code: str = ""


class DeviceImportRowResultDTO(ApiModel):
    line: int
    action: Literal[
        "CREATE", "UPDATE", "UNCHANGED", "NOT_FOUND", "CONFLICT", "INVALID"
    ]
    match_strategy: DeviceImportMatchStrategy
    match_basis: str = ""
    device_id: int | None = None
    device_name: str = ""
    original_primary_address: str = ""
    new_primary_address: str = ""
    message: str = ""
    error_code: str = ""
    warnings: list[str] = Field(default_factory=list)


class DeviceImportPreviewDTO(ApiModel):
    preview_token: str
    source_name: str
    source_sha256: str
    row_count: int
    total_rows: int = 0
    valid_rows: int = 0
    invalid_rows: int = 0
    vendor_summary: dict[str, int] = Field(default_factory=dict)
    device_type_summary: dict[str, int] = Field(default_factory=dict)
    create_count: int = 0
    update_count: int = 0
    conflict_count: int = 0
    unchanged_count: int = 0
    not_found_count: int = 0
    detected_encoding: str = ""
    match_strategy: DeviceImportMatchStrategy = "LEGACY_APPEND"
    write_mode: DeviceImportWriteMode = "CREATE_ONLY"
    columns: list[str] = Field(default_factory=list)
    errors: list[DeviceImportErrorDTO] = Field(default_factory=list)
    rows: list[DeviceImportRowResultDTO] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    duplicate_rows: list[int] = Field(default_factory=list)
    has_hard_errors: bool = False
    persistence: Literal["preview_only"] = "preview_only"


class DeviceImportConfirmRequestDTO(ApiModel):
    preview_token: str = Field(min_length=16, max_length=256)
    duplicate_strategy: Literal["reject", "skip", "create_new"] = "reject"


class DeviceExportRequestDTO(ApiModel):
    device_uuids: list[str] = Field(default_factory=list, max_length=500)
    export_scope: Literal["selected", "filtered_all"] | None = None
    search: str = Field(default="", max_length=200)
    vendor: str = Field(default="", max_length=40)
    device_type: str = Field(default="", max_length=40)
    group_filter: int | Literal["__ungrouped__"] | None = None
    project_phase: Literal[
        "all", "phase_1", "phase_2", "phase_3", "other", "unspecified"
    ] = "all"
    work_scope_status: Literal["all", "included", "excluded"] = "included"
    include_credentials: bool = False


class DeviceSecureCrtExportRequestDTO(DeviceExportRequestDTO):
    pass


class DeviceExternalTerminalRequestDTO(ApiModel):
    terminal_type: Literal["securecrt", "putty", "xshell"] = "securecrt"


class DeviceExternalTerminalActionDTO(ApiModel):
    native_action: Literal["launchTerminal"] = "launchTerminal"
    device_uuid: str
    terminal_type: Literal["securecrt", "putty", "xshell"]
    success: Literal[True] = True
    code: str
    message: str = ""


class DeviceExternalTerminalBatchRequestDTO(ApiModel):
    device_uuids: list[str] = Field(min_length=1, max_length=200)
    terminal_type: Literal["securecrt", "putty", "xshell"] = "securecrt"
    confirmation_token: str = Field(default="", max_length=256)


class DeviceExternalTerminalConfirmationRequestDTO(ApiModel):
    device_uuids: list[str] = Field(min_length=21, max_length=200)
    terminal_type: Literal["securecrt", "putty", "xshell"] = "securecrt"


class DeviceExternalTerminalConfirmationDTO(ApiModel):
    confirmation_token: str
    device_uuids: list[str]
    terminal_type: Literal["securecrt", "putty", "xshell"]
    expires_at: str


class DeviceExternalTerminalBatchDTO(ApiModel):
    terminal_type: Literal["securecrt", "putty", "xshell"]
    success: int = 0
    failed: int = 0
    failures: list[str] = Field(default_factory=list)


class DeviceExternalTerminalPreflightRequestDTO(ApiModel):
    device_uuids: list[str] = Field(min_length=1, max_length=200)
    terminal_type: Literal["securecrt", "putty", "xshell"] = "securecrt"


class DeviceExternalTerminalPreflightItemDTO(ApiModel):
    device_uuid: str
    available: bool = False
    reason: str = ""


class DeviceExternalTerminalPreflightDTO(ApiModel):
    terminal_type: Literal["securecrt", "putty", "xshell"]
    launchable_devices: list[str] = Field(default_factory=list)
    skipped_devices: list[DeviceExternalTerminalPreflightItemDTO] = Field(default_factory=list)


class DeviceExternalTerminalSettingsDTO(ApiModel):
    terminal_type: Literal["securecrt", "putty", "xshell"] = "securecrt"
    securecrt_path: str = ""
    xshell_path: str = ""
    putty_path: str = ""
    pass_password: bool = False


class DeviceExternalTerminalSettingsUpdateDTO(DeviceExternalTerminalSettingsDTO):
    securecrt_path: str = Field(default="", max_length=1024)
    xshell_path: str = Field(default="", max_length=1024)
    putty_path: str = Field(default="", max_length=1024)


class DeviceConnectionTestRequestDTO(ApiModel):
    protocol: DeviceConnectionProtocol


class DeviceConnectionTestDTO(ApiModel):
    task_id: str
    task_status: str
    device_uuid: str
    protocol: DeviceConnectionProtocol | None = None
    success: bool | None = None
    result_status: str = ""
    failure_category: str = ""
    error_code: str = ""
    summary: str = ""
    retryable: bool = False
    suggested_action: str = ""
    message: str = ""
    safe_message: str = ""
    method: str = ""
    host: str = ""
    port: int | None = None
    latency_ms: int | None = None
    elapsed_ms: int | None = None
    tested_at: str = ""
    system_name: str = ""
    model: str = ""
    os_family: str = ""
    interface_count: int | None = None
    error_type: str = ""
    suggestion: str = ""
    created_time: str = ""
    updated_time: str = ""


__all__ = [name for name in globals() if name.endswith("DTO")]
