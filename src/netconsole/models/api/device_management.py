from __future__ import annotations

from typing import Literal

from pydantic import Field, SecretStr

from netconsole.models.api.common import ApiModel


DeviceConnectionStatus = Literal[
    "UNKNOWN",
    "TESTING",
    "REACHABLE",
    "UNREACHABLE",
    "AUTH_FAILED",
    "ERROR",
]
DeviceConnectionProtocol = Literal["SSH", "TELNET", "SNMP"]
DeviceSecretField = Literal[
    "ssh_password",
    "telnet_password",
    "tunnel1_password",
    "tunnel2_password",
    "snmp_ro_community",
]


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
    primary_address: str = ""
    backup_address: str = ""
    updated_at: str = ""
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
    primary_address: str = Field(min_length=1, max_length=255)
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
    message: str = ""


class DeviceTaskBatchDTO(ApiModel):
    action: str
    tasks: list[DeviceTaskReferenceDTO] = Field(default_factory=list)


class DeviceBatchRefreshRequestDTO(ApiModel):
    device_uuids: list[str] = Field(min_length=1, max_length=200)


class DeviceBatchConnectionRequestDTO(ApiModel):
    device_uuids: list[str] = Field(min_length=1, max_length=200)


class DeviceImportPreviewRequestDTO(ApiModel):
    """CSV preview is multipart upload; browser paths are not accepted."""


class DeviceImportPreviewDTO(ApiModel):
    preview_token: str
    source_name: str
    source_sha256: str
    row_count: int
    columns: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    duplicate_rows: list[int] = Field(default_factory=list)
    persistence: Literal["preview_only"] = "preview_only"


class DeviceImportConfirmRequestDTO(ApiModel):
    preview_token: str = Field(min_length=16, max_length=256)
    duplicate_strategy: Literal["reject", "skip", "create_new"] = "reject"


class DeviceExportRequestDTO(ApiModel):
    device_uuids: list[str] = Field(default_factory=list, max_length=500)
    search: str = Field(default="", max_length=200)
    vendor: str = Field(default="", max_length=40)
    device_type: str = Field(default="", max_length=40)
    group_filter: int | Literal["__ungrouped__"] | None = None
    include_credentials: bool = False


class DeviceSecureCrtExportRequestDTO(DeviceExportRequestDTO):
    pass


class DeviceOmniPeekExportRequestDTO(DeviceExportRequestDTO):
    line_name: str = Field(min_length=1, max_length=200)
    include_device_mr: bool = True
    selected_item_keys: list[str] = Field(default_factory=list, max_length=5000)
    excluded_item_keys: list[str] = Field(default_factory=list, max_length=5000)
    force_export_keys: list[str] = Field(default_factory=list, max_length=5000)


class DeviceOmniPeekPreviewDTO(ApiModel):
    task_id: str
    task_status: str
    ready: bool = False
    items: list[dict[str, object | None]] = Field(default_factory=list)
    source_counts: dict[str, int] = Field(default_factory=dict)
    stats: dict[str, int] = Field(default_factory=dict)
    message: str = ""


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
