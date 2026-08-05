from __future__ import annotations

from typing import Any, Literal

from pydantic import AliasChoices, Field

from netconsole.models.api.common import ApiModel
from netconsole.models.api.rail_transit_base_data import TracksideApDTO


class TracksideApBusinessRowDTO(ApiModel):
    station_id: str = ""
    switch_station_id: str = ""
    ap_station_id: str = ""
    planning_station_id: str = ""
    effective_station_id: str = ""
    station_consistency_status: str = "unresolved"
    station_consistency_reason: str = ""
    site: str = ""
    device_name: str = ""
    switch_device_uuid: str = ""
    switch_terminal_available: bool = False
    switch_terminal_unavailable_reason: str = ""
    switch_vendor: str = ""
    interface_name: str = ""
    link_status: str = ""
    port_type: str = ""
    description: str = ""
    pvid: Any = None
    vlan: Any = None
    planned_management_vlan: int | None = None
    vlan_group_id: str = ""
    vlan_group_code: str = ""
    vlan_group_name: str = ""
    pvid_plan_status: Literal["matched", "mismatched", "unresolved"] = "unresolved"
    switch_rx_power: Any = None
    switch_tx_power: Any = None
    switch_rx_low_alarm: Any = None
    switch_rx_high_alarm: Any = None
    switch_tx_low_alarm: Any = None
    switch_tx_high_alarm: Any = None
    switch_optical_status: str = ""
    switch_interface_updated_at: str = ""
    switch_optical_updated_at: str = ""
    switch_interface_data_status: Literal["current", "stale", "missing", "unknown"] = "unknown"
    switch_optical_data_status: Literal["current", "stale", "missing", "unknown"] = "unknown"
    ap_uuid: str = ""
    ap_mac: str = ""
    ap_name: str = ""
    ap_terminal_device_uuid: str = ""
    ap_terminal_available: bool = False
    ap_terminal_unavailable_reason: str = ""
    ap_rx_power: Any = None
    ap_tx_power: Any = None
    ap_device_optical_status: str = ""
    ap_business_optical_status: str = "unknown"
    ap_business_threshold_dbm: float = -13.90
    ap_business_reason: str = ""
    ap_optical_status: str = ""
    ap_match_source: str = ""
    ap_match_confidence: int = 0
    ap_identity_entity_id: str = ""
    identity_match_status: str = "unresolved"
    identity_match_rule: str = ""
    lldp_observed_neighbor_mac: str = ""
    lldp_match_status: str = ""
    lldp_history_status: str = "no_current_evidence"
    runtime_snapshot_status: str = "unavailable"
    fit_ap_snapshot_collected_at: str = ""
    lldp_snapshot_collected_at: str = ""
    lldp_snapshot_generation: str = ""
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


class TracksideApScopeExcludedDTO(ApiModel):
    source: str = ""
    item_id: str = ""
    device_name: str = ""
    station_name: str = ""
    operation_status: str = ""
    project_phase: str = ""
    reason: str = ""
    mac: str = ""


class TracksideApUnmatchedOnlineDTO(ApiModel):
    source: str = ""
    item_id: str = ""
    ap_name: str = ""
    mac: str = ""
    ac_status: str = ""
    runtime_station_text: str = ""
    reason: str = ""
    suggested_action: str = ""
    association_status: str = "unknown"
    reason_code: str = ""
    fit_ap_collected_at: str = ""
    lldp_collected_at: str = ""
    lldp_candidate_count: int = 0


class TracksideApScopeExcludedPageDTO(ApiModel):
    items: list[TracksideApScopeExcludedDTO] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)
    revision: str = ""


class TracksideApUnmatchedOnlinePageDTO(ApiModel):
    items: list[TracksideApUnmatchedOnlineDTO] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)
    revision: str = ""


class TracksideApDataSourceIssueDTO(ApiModel):
    source: str
    label: str
    code: str
    message: str
    device_id: str = ""


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
    fit_ap_resource_total_count: int = 0
    fit_ap_matched_count: int = 0
    fit_ap_matched_online_count: int = 0
    fit_ap_online_total_count: int = 0
    fit_ap_offline_total_count: int = 0
    fit_ap_unknown_total_count: int = 0
    fit_ap_unmatched_online_count: int = 0
    fit_ap_lldp_snapshot_stale_count: int = 0
    fit_ap_lldp_exact_match_pending_count: int = 0
    fit_ap_current_conflict_count: int = 0
    fit_ap_planning_missing_count: int = 0
    fit_ap_ambiguous_online_count: int = 0
    fit_ap_station_master_missing_count: int = 0
    fit_ap_unknown_association_count: int = 0
    runtime_snapshot: dict[str, object] = Field(default_factory=dict)
    business_row_count: int = 0
    query_ms: int = 0
    build_ms: int = 0
    empty_reason: str = ""
    identity_shadow: dict[str, object] = Field(default_factory=dict)
    scope_description: str = "当前项目 · 当前工作范围轨旁 AP"
    scope_station_count: int = Field(default=0, ge=0)
    scope_device_count: int = Field(default=0, ge=0)
    scope_ap_reference_count: int = Field(default=0, ge=0)
    excluded_device_count: int = Field(default=0, ge=0)
    excluded_items: list[TracksideApScopeExcludedDTO] = Field(default_factory=list)
    unmatched_online_items: list[TracksideApUnmatchedOnlineDTO] = Field(default_factory=list)
    partial_data: bool = False
    source_statuses: dict[
        str,
        Literal["loaded", "partial", "failed"],
    ] = Field(default_factory=dict)
    unavailable_sources: list[TracksideApDataSourceIssueDTO] = Field(
        default_factory=list
    )


class TracksideApUpdateRequestDTO(ApiModel):
    station: str = ""
    ap_uuid: str = ""
    ap_mac: str = ""
    ap_name: str = ""


class TracksideApBusinessExportProposalDTO(ApiModel):
    site_id: str
    site_display_name: str
    generated_at: str
    suggested_name: str


class TracksideApBusinessExportRequestDTO(ApiModel):
    generated_at: str = ""
    suggested_name: str = Field(default="", max_length=180)


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
    station_id: str = ""
    sequence_no: int = 0
    station_name: str = ""
    planned_ap_count: int = Field(
        default=0,
        ge=0,
        validation_alias=AliasChoices("planned_ap_count", "ap_count"),
    )
    management_vlan: int | None = Field(default=None, ge=1, le=4094)
    remark: str = ""
    relation_status: Literal["resolved", "missing", "ambiguous", "stale"] = "missing"
    candidate_station_ids: list[str] = Field(default_factory=list)


class TracksideApOnlineStatusRowDTO(ApiModel):
    station_id: str = ""
    station_name: str
    planned_ap_count: int = Field(default=0, ge=0)
    actual_online_count: int = Field(default=0, ge=0)
    offline_count: int = Field(default=0, ge=0)
    online_rate: float | None = None
    remark: str = ""
    planning_missing: bool = False
    count_anomaly: bool = False
    status: Literal[
        "normal",
        "planning_missing",
        "unplanned_online",
        "over_planned",
    ] = "normal"
    warning: str = ""


class TracksideApUnassignedDTO(ApiModel):
    ap_id: str
    ap_name: str = ""
    point_code: str = ""
    mac: str = ""
    station_name: str = ""


class TracksideApOnlineStatusDTO(ApiModel):
    items: list[TracksideApOnlineStatusRowDTO] = Field(default_factory=list)
    planned_ap_count: int = Field(default=0, ge=0)
    actual_online_count: int = Field(default=0, ge=0)
    offline_count: int = Field(default=0, ge=0)
    online_rate: float | None = None
    unassigned_count: int = 0
    unassigned_items: list[TracksideApUnassignedDTO] = Field(default_factory=list)
    updated_at: str = ""
    warning: str = ""
    count_anomaly: bool = False
    status: Literal["normal", "anomaly"] = "normal"
    scope_description: str = "当前项目 · 当前工作范围轨旁 AP"
    scope_station_count: int = Field(default=0, ge=0)
    scope_device_count: int = Field(default=0, ge=0)
    scope_ap_reference_count: int = Field(default=0, ge=0)
    excluded_device_count: int = Field(default=0, ge=0)
    excluded_items: list[TracksideApScopeExcludedDTO] = Field(default_factory=list)
    fit_ap_resource_total_count: int = Field(default=0, ge=0)
    fit_ap_matched_count: int = Field(default=0, ge=0)
    fit_ap_matched_online_count: int = Field(default=0, ge=0)
    fit_ap_online_total_count: int = Field(default=0, ge=0)
    fit_ap_offline_total_count: int = Field(default=0, ge=0)
    fit_ap_unknown_total_count: int = Field(default=0, ge=0)
    fit_ap_unmatched_online_count: int = Field(default=0, ge=0)
    fit_ap_lldp_snapshot_stale_count: int = Field(default=0, ge=0)
    fit_ap_lldp_exact_match_pending_count: int = Field(default=0, ge=0)
    fit_ap_current_conflict_count: int = Field(default=0, ge=0)
    fit_ap_planning_missing_count: int = Field(default=0, ge=0)
    fit_ap_ambiguous_online_count: int = Field(default=0, ge=0)
    fit_ap_station_master_missing_count: int = Field(default=0, ge=0)
    fit_ap_unknown_association_count: int = Field(default=0, ge=0)
    fit_ap_unresolved_online_count: int = Field(default=0, ge=0)
    fit_ap_ambiguous_online_count: int = Field(default=0, ge=0)
    unmatched_online_items: list[TracksideApUnmatchedOnlineDTO] = Field(default_factory=list)
    generated_at: str = ""
    revision: str = ""
    source_revision: dict[str, object] = Field(default_factory=dict)
    cache_hit: bool = False
    snapshot_status: str = "unavailable"
    snapshot_age_seconds: int | None = None
    snapshot_warnings: list[str] = Field(default_factory=list)
    fit_ap_collected_at: str = ""
    switch_lldp_collected_at: str = ""


class ApManagementVlanPlanningDTO(ApiModel):
    line_id: str = "current"
    planning_mode: Literal["line_single", "station_independent", "station_grouped"] = (
        "station_independent"
    )
    auto_group_station_count: int = Field(default=1, ge=1, le=4)
    address_allocation_strategy: str = "station_then_point"
    revision: int = Field(default=0, ge=0)
    created_at: str = ""
    updated_at: str = ""


class ApManagementVlanGroupMemberDTO(ApiModel):
    station_id: str
    station_name: str
    station_sequence: int = 0
    ap_count: int = Field(default=0, ge=0)


class ApManagementVlanIssueDTO(ApiModel):
    code: str
    severity: Literal["error", "warning", "info"] = "error"
    message: str
    blocking: bool = True
    field_name: str = ""
    group_id: str = ""
    station_id: str = ""
    ap_id: str = ""


class ApManagementVlanGroupDTO(ApiModel):
    group_id: str
    line_id: str = "current"
    group_code: str
    group_name: str
    sequence: int = 0
    management_vlan: int | None = Field(default=None, ge=1, le=4094)
    legacy_management_vlans: str = ""
    network_address: str | None = None
    prefix_length: int | str | None = None
    subnet_mask: str | None = None
    default_gateway: str | None = None
    ap_start_ip: str | None = None
    ap_end_ip: str | None = None
    address_allocation_strategy: str = "station_then_point"
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    members: list[ApManagementVlanGroupMemberDTO] = Field(default_factory=list)
    start_station_name: str = ""
    end_station_name: str = ""
    station_count: int = 0
    ap_count: int = 0
    address_capacity: int = 0
    used_address_count: int = 0
    validation_status: Literal["valid", "warning", "error"] = "valid"
    issues: list[ApManagementVlanIssueDTO] = Field(default_factory=list)


class ApManagementVlanAssignmentDTO(ApiModel):
    assignment_id: str
    assignment_type: Literal["section_default", "interval_default", "ap_override"] = (
        "ap_override"
    )
    target_id: str
    group_id: str
    source: str = "ap_override"
    created_at: str = ""
    updated_at: str = ""


class ApManagementVlanAllocationDTO(ApiModel):
    ap_id: str
    ap_name: str = ""
    point_code: str = ""
    station_id: str = ""
    station_name: str = ""
    section_name: str = ""
    group_id: str
    planned_ip: str = ""
    allocation_order: int = 0
    is_manual: bool = False
    is_locked: bool = False
    source: str = "generated"
    group_source: str = ""
    created_at: str = ""
    updated_at: str = ""


class ApManagementVlanStationDetailDTO(ApiModel):
    station_id: str
    station_name: str
    station_sequence: int = 0
    ap_count: int = 0
    group_id: str = ""
    group_code: str = ""
    group_name: str = ""
    ap_start_ip: str = ""
    ap_end_ip: str = ""
    management_vlan: int | None = None
    network_address: str = ""
    prefix_length: int | None = None
    subnet_mask: str = ""
    default_gateway: str = ""
    source: str = "unassigned"
    notes: str = ""


class TracksideApPlanDraftDTO(ApiModel):
    planning: ApManagementVlanPlanningDTO = Field(
        default_factory=ApManagementVlanPlanningDTO
    )
    groups: list[ApManagementVlanGroupDTO] = Field(
        default_factory=list,
        max_length=2000,
    )
    assignments: list[ApManagementVlanAssignmentDTO] = Field(
        default_factory=list,
        max_length=10000,
    )
    allocations: list[ApManagementVlanAllocationDTO] = Field(
        default_factory=list,
        max_length=10000,
    )


class ApManagementVlanImpactDTO(ApiModel):
    old_group_count: int = 0
    new_group_count: int = 0
    affected_station_count: int = 0
    affected_ap_count: int = 0
    vlan_change_count: int = 0
    ip_change_count: int = 0
    gateway_change_count: int = 0
    manual_address_override_count: int = 0
    conflict_count: int = 0
    warning_count: int = 0
    issues: list[ApManagementVlanIssueDTO] = Field(default_factory=list)


class TracksideApPlanDTO(ApiModel):
    items: list[TracksideApPlanRowDTO] = Field(default_factory=list)
    total: int = 0
    planning: ApManagementVlanPlanningDTO = Field(
        default_factory=ApManagementVlanPlanningDTO
    )
    groups: list[ApManagementVlanGroupDTO] = Field(default_factory=list)
    assignments: list[ApManagementVlanAssignmentDTO] = Field(default_factory=list)
    allocations: list[ApManagementVlanAllocationDTO] = Field(default_factory=list)
    station_details: list[ApManagementVlanStationDetailDTO] = Field(
        default_factory=list
    )
    issues: list[ApManagementVlanIssueDTO] = Field(default_factory=list)
    valid: bool = True
    unassigned_station_count: int = 0


class TracksideApPlanWriteRequestDTO(ApiModel):
    rows: list[TracksideApPlanRowDTO] = Field(default_factory=list)
    draft: TracksideApPlanDraftDTO | None = None
    expected_revision: int = Field(default=0, ge=0)
    reallocation_policy: Literal["only_unlocked", "all"] = "only_unlocked"
    explicit_confirmation: bool = False
    audit: dict[str, str] = Field(default_factory=dict)


class TracksideApPlanPreviewRowDTO(ApiModel):
    row_number: int
    status: Literal["valid", "duplicate", "error"]
    key: str = ""
    message: str = ""
    row: dict[str, Any] | None = None


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
    result_plan: TracksideApPlanDTO | None = None
    legacy_schema: bool = False
    message: str = ""


class TracksideApPlanExportRequestDTO(ApiModel):
    template: bool = False


class ApManagementVlanAutoGroupRequestDTO(ApiModel):
    planning_mode: Literal["line_single", "station_independent", "station_grouped"]
    auto_group_station_count: int = Field(default=1, ge=1, le=4)
    current: TracksideApPlanDraftDTO | None = None
    reallocation_policy: Literal["only_unlocked", "all"] = "only_unlocked"


class ApManagementVlanPreviewRequestDTO(ApiModel):
    proposed: TracksideApPlanDraftDTO
    reallocation_policy: Literal["only_unlocked", "all"] = "only_unlocked"


class ApManagementVlanPreviewDTO(ApiModel):
    plan: TracksideApPlanDTO
    impact: ApManagementVlanImpactDTO


class EffectiveManagementNetworkDTO(ApiModel):
    vlan_group_id: str
    vlan_group_code: str = ""
    vlan_group_name: str = ""
    management_vlan: int | None = None
    network_address: str = ""
    prefix_length: int | None = None
    subnet_mask: str = ""
    default_gateway: str = ""
    ap_start_ip: str = ""
    ap_end_ip: str = ""
    address_allocation_strategy: str = "station_then_point"
    source: str = ""


class TracksideApPointTableRowDTO(ApiModel):
    ap_id: str
    station: str = ""
    section: str = ""
    ap_name: str = ""
    point_code: str = ""
    ap_ip: str = ""
    management_vlan: int | None = None
    subnet_mask: str = ""
    prefix_length: int | None = None
    default_gateway: str = ""
    vlan_group_id: str = ""
    vlan_group_code: str = ""
    vlan_group_name: str = ""
    allocation_source: str = ""
    is_locked: bool = False


class TracksideApPointTablePreviewDTO(ApiModel):
    items: list[TracksideApPointTableRowDTO] = Field(default_factory=list)
    total: int = 0
    impact: ApManagementVlanImpactDTO = Field(default_factory=ApManagementVlanImpactDTO)


class TracksideApBaseExportRequestDTO(ApiModel):
    template: bool = False
    rows: list[TracksideApDTO] | None = Field(default=None, max_length=2000)
    issues: list["TracksideApImportIssueExportRowDTO"] | None = Field(
        default=None,
        max_length=50000,
    )


class TracksideApImportIssueExportRowDTO(ApiModel):
    row_number: int = Field(ge=1)
    result: str
    severity: str
    code: str
    field_name: str = ""
    original_value: str = ""
    message: str
    suggested_action: str = ""
    ap_name: str = ""
    point_code: str = ""
    ap_mac: str = ""


class TracksideApRenameCommandExportRequestDTO(ApiModel):
    rows: list[TracksideApDTO] | None = Field(default=None, max_length=2000)


__all__ = [name for name in globals() if name.startswith("TracksideAp")]
