from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from netconsole.models.api.common import ApiModel
from netconsole.models.api.rail_transit_base_data import TracksideApDTO


class TracksideApBusinessRowDTO(ApiModel):
    site: str = ""
    device_name: str = ""
    switch_vendor: str = ""
    interface_name: str = ""
    link_status: str = ""
    port_type: str = ""
    description: str = ""
    pvid: Any = None
    vlan: Any = None
    switch_rx_power: Any = None
    switch_tx_power: Any = None
    switch_rx_low_alarm: Any = None
    switch_rx_high_alarm: Any = None
    switch_tx_low_alarm: Any = None
    switch_tx_high_alarm: Any = None
    switch_optical_status: str = ""
    ap_uuid: str = ""
    ap_mac: str = ""
    ap_name: str = ""
    ap_rx_power: Any = None
    ap_tx_power: Any = None
    ap_optical_status: str = ""
    ap_match_source: str = ""
    ap_match_confidence: int = 0
    lldp_match_status: str = ""
    local_rx_power_dbm: Any = None
    local_tx_power_dbm: Any = None
    remote_rx_power_dbm: Any = None
    remote_tx_power_dbm: Any = None
    forward_loss_db: Any = None
    reverse_loss_db: Any = None
    calculation_status: str = ""
    calculation_reason: str = ""
    local_sample_time: str = ""
    remote_sample_time: str = ""
    sample_time_delta_seconds: int | None = None
    updated_at: str = ""
    optical_severity: str = "normal"


class TracksideApBusinessPageDTO(ApiModel):
    items: list[TracksideApBusinessRowDTO] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    site_id: str
    station_options: list[str] = Field(default_factory=list)
    device_count: int = 0
    candidate_interface_count: int = 0
    optical_abnormal_count: int = 0
    fit_ap_resource_count: int = 0
    query_ms: int = 0
    build_ms: int = 0
    empty_reason: str = ""
    identity_shadow: dict[str, object] = Field(default_factory=dict)


class TracksideApUpdateRequestDTO(ApiModel):
    station: str = ""
    ap_uuid: str = ""
    ap_mac: str = ""
    ap_name: str = ""


class TracksideSwitchCommandProfileDTO(ApiModel):
    profile_id: str
    vendor: str
    platform: str
    product_family: str
    reference_version: str
    privilege_required: bool = False
    enable_command: str = ""
    enable_level: int = 0
    enable_secret_configured: bool = False
    device_version: list[str] = Field(default_factory=list)
    interface_brief: list[str] = Field(default_factory=list)
    interface_detail: list[str] = Field(default_factory=list)
    optical_brief: list[str] = Field(default_factory=list)
    optical_detail: list[str] = Field(default_factory=list)
    lldp_global_candidates: list[str] = Field(default_factory=list)
    lldp_interface_candidates: list[str] = Field(default_factory=list)
    lldp_config_candidates: list[str] = Field(default_factory=list)


class TracksideSwitchCapabilityDTO(ApiModel):
    key: str
    label: str
    status: str
    message: str


class TracksideSwitchAdapterDTO(ApiModel):
    vendor: str
    vendor_label: str
    platform: str
    product_family: str
    adaptation_status: str
    verification_status: str
    profile: TracksideSwitchCommandProfileDTO
    capabilities: list[TracksideSwitchCapabilityDTO] = Field(default_factory=list)
    pending_items: list[str] = Field(default_factory=list)


class TracksideSwitchDeviceDTO(ApiModel):
    device_uuid: str
    device_name: str
    station: str = ""
    primary_address: str = ""
    adapter: TracksideSwitchAdapterDTO


class TracksideSwitchAdapterCatalogDTO(ApiModel):
    items: list[TracksideSwitchDeviceDTO] = Field(default_factory=list)
    total: int = 0


class TracksideSwitchSampleRequestDTO(ApiModel):
    device_uuid: str = Field(min_length=1, max_length=80)
    vendor: str = Field(min_length=1, max_length=40)
    command_profile: str = Field(min_length=1, max_length=100)
    selected_interface: str = Field(default="", max_length=80)
    requested_commands: list[str] = Field(default_factory=list, max_length=20)


class TracksideApPlanRowDTO(ApiModel):
    station_name: str = ""
    ap_count: int = 0
    ap_start_address: str = ""
    mask_length: int | None = None
    ap_gateway: str = ""
    ap_management_vlans: str = ""
    remark: str = ""
    sort_order: int = 0


class TracksideApPlanDTO(ApiModel):
    items: list[TracksideApPlanRowDTO] = Field(default_factory=list)
    total: int = 0


class TracksideApPlanWriteRequestDTO(ApiModel):
    rows: list[TracksideApPlanRowDTO] = Field(default_factory=list)
    explicit_confirmation: bool = False
    audit: dict[str, str] = Field(default_factory=dict)


class TracksideApPlanPreviewRowDTO(ApiModel):
    row_number: int
    status: Literal["valid", "duplicate", "error"]
    key: str = ""
    message: str = ""
    row: TracksideApPlanRowDTO | None = None


class TracksideApPlanPreviewDTO(ApiModel):
    file_name: str
    file_sha256: str
    duplicate_strategy: Literal["replace", "skip", "error"]
    can_apply: bool
    total_count: int
    valid_count: int
    duplicate_count: int
    error_count: int
    rows: list[TracksideApPlanPreviewRowDTO] = Field(default_factory=list)
    result_rows: list[TracksideApPlanRowDTO] = Field(default_factory=list)


class TracksideApPlanExportRequestDTO(ApiModel):
    template: bool = False
    rows: list[TracksideApPlanRowDTO] | None = Field(default=None, max_length=2000)


class TracksideApBaseExportRequestDTO(ApiModel):
    template: bool = False
    rows: list[TracksideApDTO] | None = Field(default=None, max_length=2000)


class TracksideApRenameCommandExportRequestDTO(ApiModel):
    rows: list[TracksideApDTO] | None = Field(default=None, max_length=2000)


__all__ = [name for name in globals() if name.startswith("TracksideAp")]
