from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from netconsole.models.api.common import ApiModel


IssueSeverity = Literal["error", "warning", "info"]
MergeResult = Literal[
    "CREATE",
    "UPDATE",
    "UNCHANGED",
    "SKIP",
    "CONFLICT",
    "INVALID",
    "NEEDS_CONFIRMATION",
]
BaseDataEntityType = Literal[
    "site_metadata",
    "station",
    "device_station_binding",
    "section",
    "trackside_ap",
    "vehicle_mr",
    "trackside_ap_plan",
]
BaseDataChangeAction = Literal["create", "update", "delete", "replace"]
BaseDataEditScope = Literal[
    "all",
    "overview",
    "stations",
    "trackside_ap",
    "trackside_ap_planning",
    "vehicles",
]
StationNodeType = Literal["station", "parking_lot", "depot", "connection_point", "other", "unknown"]
StationStructureType = Literal["underground", "elevated", "at_grade", "cutting", "mixed", "unknown"]
StationPlatformLayout = Literal["island", "side", "mixed", "stacked_island", "stacked_side", "separated", "unknown"]
StationTurnbackType = Literal["none", "crossover", "pocket_track", "tail_track", "loop", "depot_connection", "other", "unknown"]
StationTurnbackDirection = Literal["none", "both", "increasing_to_decreasing", "decreasing_to_increasing", "unknown"]
StationTrackFacility = Literal[
    "turnback_track",
    "crossover",
    "storage_track",
    "depot_connection",
    "tail_track",
    "loop",
    "siding",
    "other",
]
StationSourceKind = Literal["device_station_field", "template", "manual", "legacy_ap_derived"]
StationSourceSyncStatus = Literal["matched", "stale", "conflict", "manual", "legacy", "unavailable"]
StationSourceMatchStatus = Literal[
    "exact_source_key",
    "canonical_name",
    "canonical_name_and_type",
    "alias",
    "create",
    "conflict",
    "manual_review",
]
StationSourceProcessingStrategy = Literal[
    "auto_match",
    "overwrite_existing",
    "create",
    "ignore",
    "manual_target",
    "merge_duplicates",
]
StationDeletePreflightStatus = Literal["SAFE_DELETE", "REQUIRES_MERGE", "BLOCKED"]
SectionKind = Literal["between_stations", "terminal_extension", "depot_connection", "manual", "legacy"]
SectionDirectionRole = Literal["increasing", "decreasing", "none", "unknown"]
SectionNodeType = Literal["station", "terminal_endpoint", "legacy", "unknown"]
SectionSourceKind = Literal["generated", "manual", "template", "legacy_ap_derived"]
SectionMileageSource = Literal["generated", "manual", "unavailable"]
SectionGenerationResult = Literal["CREATE", "UPDATE", "UNCHANGED", "CONFLICT", "STALE"]
LineSideSource = Literal["section_direction", "manual", "import", "legacy", "unavailable"]
MrPositionCode = Literal["CT", "CW", "unknown"]
MrPhysicalEnd = Literal["car_1_end", "car_6_end", "unknown"]
IncreasingDirectionLeadingEnd = MrPhysicalEnd


class BaseDataEditSessionDTO(ApiModel):
    site_id: str
    base_revision: str
    loaded_at: str
    can_write: bool = False
    write_scope: str = "real"
    storage_mode: Literal["persistent", "isolated_test"] = "persistent"
    write_denial_code: str = ""
    write_denial_reason: str = ""


class DeviceStationBindingDTO(ApiModel):
    device_id: str
    station_id: str
    source: Literal["station_source_preview", "manual", "migration"] = "migration"


class BaseDataChangeDTO(ApiModel):
    entity_type: BaseDataEntityType
    action: BaseDataChangeAction
    entity_id: str = ""
    values: dict[str, Any] = Field(default_factory=dict)


class BaseDataValidationIssueDTO(ApiModel):
    change_index: int
    code: str
    message: str
    field_name: str = ""
    blocking: bool = True


class BaseDataValidateRequestDTO(ApiModel):
    site_id: str
    base_revision: str
    scope: BaseDataEditScope = "all"
    changes: list[BaseDataChangeDTO] = Field(default_factory=list, max_length=2000)


class BaseDataValidationResultDTO(ApiModel):
    valid: bool
    issues: list[BaseDataValidationIssueDTO] = Field(default_factory=list)


class BaseDataSaveRequestDTO(BaseDataValidateRequestDTO):
    explicit_confirmation: bool = False


class BaseDataSaveResultDTO(ApiModel):
    revision: str
    created_count: int = 0
    updated_count: int = 0
    deleted_count: int = 0
    device_binding_count: int = 0
    planning_row_count: int = 0
    station_id_repaired_count: int = 0
    ap_identity_refreshed: bool = False
    warnings: list[str] = Field(default_factory=list)
    validation_issues: list[BaseDataValidationIssueDTO] = Field(default_factory=list)


class BaseDataClearPreviewDTO(ApiModel):
    site_id: str
    base_revision: str
    station_count: int = 0
    section_count: int = 0
    affected_trackside_ap_count: int = 0


class BaseDataClearRequestDTO(ApiModel):
    site_id: str
    base_revision: str
    explicit_confirmation: bool = False


class BaseDataClearResultDTO(ApiModel):
    revision: str
    deleted_station_count: int = 0
    deleted_section_count: int = 0
    unlinked_trackside_ap_count: int = 0
    deleted_trackside_ap_plan_count: int = 0


class MileageDTO(ApiModel):
    raw: str = ""
    normalized: str = ""
    meters: float | None = None
    line_type: str = ""
    valid: bool = False
    error: str = ""


class RelatedRuntimeStatusDTO(ApiModel):
    fit_ap_id: str = ""
    fit_ap_ac_id: str = ""
    fit_ap_name: str = ""
    fit_ap_match_status: str = "unmatched"
    fit_ap_status: str = "unknown"
    optical_status: str = "no_data"
    mesh_status: str = "unknown"
    mesh_related_name: str = ""
    latest_session_id: str = ""
    latest_session_status: str = ""
    updated_at: str = ""


class DataQualityIssueDTO(ApiModel):
    severity: IssueSeverity
    code: str
    entity_type: str
    entity_id: str = ""
    entity_name: str = ""
    row_number: int | None = None
    field_name: str = ""
    original_value: str = ""
    message: str
    suggested_action: str = ""
    blocking: bool = False


class DataQualityEntityGroupDTO(ApiModel):
    entity_type: str
    entity_id: str
    display_name: str = ""
    issue_count: int = 0
    error_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    blocking: bool = False
    needs_confirmation: bool = False
    issues: list[DataQualityIssueDTO] = Field(default_factory=list)
    suggested_action: str = ""


class DataQualityEntityGroupPageDTO(ApiModel):
    items: list[DataQualityEntityGroupDTO] = Field(default_factory=list)
    total: int = 0
    issue_total: int = 0
    blocking_total: int = 0
    warning_total: int = 0
    info_total: int = 0
    code_counts: dict[str, int] = Field(default_factory=dict)
    page: int = 1
    page_size: int = 50


class RailTransitSummaryDTO(ApiModel):
    site_id: str
    site_name: str
    line_name: str = ""
    project_type: str = ""
    network_type: str = ""
    main_path_code: str = "MAIN"
    increasing_direction_name: str = "上行"
    decreasing_direction_name: str = "下行"
    increasing_direction_line_side: str = "右线"
    decreasing_direction_line_side: str = "左线"
    increasing_direction_leading_end: IncreasingDirectionLeadingEnd = "unknown"
    station_source_group_name: str = "车站"
    station_source_field: str = "station"
    remark: str = ""
    created_at: str = ""
    updated_at: str = ""
    station_count: int = 0
    normal_station_count: int = 0
    special_node_count: int = 0
    source_pending_count: int = 0
    source_conflict_count: int = 0
    source_stale_count: int = 0
    section_count: int = 0
    ap_count: int = 0
    train_count: int = 0
    mr_count: int = 0
    missing_location_ap_count: int = 0
    invalid_mileage_count: int = 0
    duplicate_ap_mac_count: int = 0
    duplicate_static_ip_count: int = 0
    unbound_mr_count: int = 0
    issue_count: int = 0
    message: str = ""


class StationDTO(ApiModel):
    id: str
    node_uid: str = ""
    name: str
    code: str = ""
    line_name: str = ""
    sort_order: int | None = None
    ap_count: int = 0
    section_count: int = 0
    mileage_min: float | None = None
    mileage_max: float | None = None
    remark: str = ""
    source_station_value: str = ""
    source_station_key: str = ""
    source_order_text: str = ""
    source_order: int | None = None
    canonical_station_name: str = ""
    node_type: StationNodeType = "station"
    path_code: str = "MAIN"
    participates_in_direction: bool = True
    structure_type: StationStructureType = "unknown"
    platform_layout: StationPlatformLayout = "unknown"
    center_mileage_text: str = ""
    center_mileage_m: float | None = None
    is_line_terminal: bool = False
    is_service_terminal: bool = False
    turnback_capable: bool = False
    turnback_type: StationTurnbackType = "none"
    track_facilities: list[StationTrackFacility] = Field(default_factory=list)
    turnback_direction: StationTurnbackDirection = "none"
    terminal_extension_enabled: bool = False
    terminal_endpoint_label: str = "端点"
    terminal_extension_distance_m: float | None = None
    terminal_endpoint_mileage_text: str = ""
    enabled: bool = True
    source_kind: StationSourceKind = "legacy_ap_derived"
    source_device_count: int = 0
    source_sync_status: StationSourceSyncStatus = "legacy"
    source_last_seen_at: str = ""


class StationSourceIssueDTO(ApiModel):
    severity: IssueSeverity
    code: str
    message: str
    field_name: str = ""
    blocking: bool = False
    entity_id: str = ""


class StationSourceCandidateDTO(ApiModel):
    candidate_id: str
    source_device_ids: list[str] = Field(default_factory=list)
    source_station_value: str
    source_station_key: str
    source_order_text: str = ""
    source_order: int | None = None
    code: str = ""
    name: str
    canonical_name: str = ""
    order_parse_method: str = "none"
    parse_confidence: str = "manual_review"
    parse_warning: str = ""
    canonical_station_name: str = ""
    node_type: StationNodeType = "station"
    path_code: str = "MAIN"
    sort_order: int | None = None
    participates_in_direction: bool = True
    source_device_count: int = 0
    match_status: StationSourceMatchStatus = "create"
    matched_station_id: str = ""
    matched_station_name: str = ""
    matched_station_ids: list[str] = Field(default_factory=list)
    matched_station_names: list[str] = Field(default_factory=list)
    match_basis: str = ""
    suggested_action: str = ""
    processing_strategy: StationSourceProcessingStrategy = "create"
    processing_options: list[StationSourceProcessingStrategy] = Field(default_factory=list)
    cleanup_name_prefix_recommended: bool = False
    proposed_station: StationDTO
    issues: list[StationSourceIssueDTO] = Field(default_factory=list)


class StationSourcePreviewDTO(ApiModel):
    site_id: str
    source_group_name: str = "车站"
    source_field: str = "station"
    group_found: bool = False
    scanned_device_count: int = 0
    empty_station_device_count: int = 0
    unique_station_value_count: int = 0
    normal_station_count: int = 0
    special_node_count: int = 0
    create_count: int = 0
    match_count: int = 0
    conflict_count: int = 0
    manual_review_count: int = 0
    canonical_match_count: int = 0
    recommended_overwrite_count: int = 0
    recommended_create_count: int = 0
    recommended_merge_count: int = 0
    remaining_manual_count: int = 0
    warning_count: int = 0
    candidates: list[StationSourceCandidateDTO] = Field(default_factory=list)
    issues: list[StationSourceIssueDTO] = Field(default_factory=list)


class StationReferenceSummaryDTO(ApiModel):
    section_start_count: int = 0
    section_end_count: int = 0
    ap_count: int = 0
    device_count: int = 0
    relation_count: int = 0
    endpoint_extension_count: int = 0
    plan_count: int = 0
    total_count: int = 0


class StationDeletePreflightRequestDTO(ApiModel):
    site_id: str
    base_revision: str
    station_ids: list[str] = Field(default_factory=list, min_length=1, max_length=200)


class StationDeletePreflightItemDTO(ApiModel):
    station_id: str
    station_name: str
    code: str = ""
    sort_order: int | None = None
    source_kind: StationSourceKind = "legacy_ap_derived"
    status: StationDeletePreflightStatus
    reason: str = ""
    is_manual: bool = False
    is_line_terminal: bool = False
    references: StationReferenceSummaryDTO = Field(default_factory=StationReferenceSummaryDTO)


class StationDeletePreflightDTO(ApiModel):
    site_id: str
    base_revision: str
    items: list[StationDeletePreflightItemDTO] = Field(default_factory=list)
    safe_delete_count: int = 0
    requires_merge_count: int = 0
    blocked_count: int = 0


class StationConflictMemberDTO(ApiModel):
    station_id: str
    station_name: str
    code: str = ""
    node_uid: str = ""
    node_type: StationNodeType = "station"
    path_code: str = "MAIN"
    sort_order: int | None = None
    source_kind: StationSourceKind = "legacy_ap_derived"


class StationConflictGroupDTO(ApiModel):
    group_id: str
    path_code: str
    sort_order: int
    stations: list[StationConflictMemberDTO] = Field(default_factory=list)
    suggested_action: Literal["OVERWRITE", "MERGE", "MANUAL"] = "MANUAL"
    reason: str = ""


class StationConflictPreviewDTO(ApiModel):
    site_id: str
    base_revision: str
    groups: list[StationConflictGroupDTO] = Field(default_factory=list)
    conflict_group_count: int = 0
    conflict_station_count: int = 0
    recommended_overwrite_count: int = 0
    recommended_merge_count: int = 0
    remaining_manual_count: int = 0


class StationTemplatePreviewRowDTO(ApiModel):
    row_number: int
    source_station_value: str = ""
    source_station_key: str = ""
    code: str = ""
    name: str = ""
    node_type: StationNodeType = "station"
    path_code: str = "MAIN"
    sort_order: int | None = None
    participates_in_direction: bool = True
    proposed_station: StationDTO | None = None
    action: Literal["create", "update", "unchanged", "conflict"] = "create"
    valid: bool = True
    issues: list[StationSourceIssueDTO] = Field(default_factory=list)


class StationTemplateSectionPreviewRowDTO(ApiModel):
    row_number: int
    section_code: str = ""
    name: str = ""
    section_kind: SectionKind = "manual"
    path_code: str = "MAIN"
    direction_role: SectionDirectionRole = "none"
    line_direction: str = ""
    start_node_type: SectionNodeType = "unknown"
    start_station: str = ""
    end_node_type: SectionNodeType = "unknown"
    end_station: str = ""
    proposed_section: SectionDTO | None = None
    action: Literal["create", "update", "unchanged", "conflict"] = "create"
    valid: bool = True
    issues: list[StationSourceIssueDTO] = Field(default_factory=list)


class StationTemplatePreviewDTO(ApiModel):
    valid: bool = True
    line_metadata: dict[str, Any] = Field(default_factory=dict)
    rows: list[StationTemplatePreviewRowDTO] = Field(default_factory=list)
    section_rows: list[StationTemplateSectionPreviewRowDTO] = Field(default_factory=list)
    section_sheet_present: bool = True
    create_count: int = 0
    update_count: int = 0
    unchanged_count: int = 0
    conflict_count: int = 0
    blocking_count: int = 0
    issues: list[StationSourceIssueDTO] = Field(default_factory=list)


class SectionDTO(ApiModel):
    id: str
    name: str
    section_code: str = ""
    section_kind: SectionKind = "legacy"
    path_code: str = "MAIN"
    direction_role: SectionDirectionRole = "unknown"
    line_direction: str = ""
    start_node_type: SectionNodeType = "legacy"
    start_node_uid: str = ""
    start_station: str = ""
    end_node_type: SectionNodeType = "legacy"
    end_node_uid: str = ""
    end_station: str = ""
    line_side: str = ""
    auto_generated: bool = False
    generation_key: str = ""
    manual_override_fields: list[str] = Field(default_factory=list)
    section_mileage_start_m: float | None = None
    section_mileage_end_m: float | None = None
    section_mileage_open_end: bool = False
    section_mileage_source: SectionMileageSource = "unavailable"
    enabled: bool = True
    source_kind: SectionSourceKind = "legacy_ap_derived"
    ap_count: int = 0
    mileage_min: float | None = None
    mileage_max: float | None = None
    remark: str = ""


class SectionGenerationLineMetadataDTO(ApiModel):
    main_path_code: str = "MAIN"
    increasing_direction_name: str = "上行"
    decreasing_direction_name: str = "下行"
    increasing_direction_line_side: str = "右线"
    decreasing_direction_line_side: str = "左线"


class SectionGenerationPreviewRequestDTO(ApiModel):
    site_id: str
    base_revision: str
    line_metadata: SectionGenerationLineMetadataDTO
    stations: list[StationDTO] = Field(default_factory=list, max_length=2000)
    current_sections: list[SectionDTO] = Field(default_factory=list, max_length=4000)


class SectionGenerationPreviewItemDTO(ApiModel):
    item_id: str
    result: SectionGenerationResult
    proposed_section: SectionDTO | None = None
    current_section: SectionDTO | None = None
    selected_by_default: bool = False
    selectable: bool = True
    issues: list[StationSourceIssueDTO] = Field(default_factory=list)


class SectionGenerationPreviewDTO(ApiModel):
    site_id: str
    base_revision: str
    generated_sections: list[SectionGenerationPreviewItemDTO] = Field(default_factory=list)
    create_count: int = 0
    update_count: int = 0
    unchanged_count: int = 0
    conflict_count: int = 0
    stale_count: int = 0
    blocking_count: int = 0
    issues: list[StationSourceIssueDTO] = Field(default_factory=list)


class MeshRadioDTO(ApiModel):
    radio_id: int
    channel: str = ""
    bandwidth: str = ""
    power: str = ""
    bssid: str = ""


class TracksideApDTO(ApiModel):
    id: str
    site_id: str
    line_name: str = ""
    name: str
    point_code: str = ""
    vendor: str = ""
    mac: str = ""
    management_ip: str = ""
    model: str = ""
    station_id: str = ""
    station: str = ""
    section_id: str = ""
    section: str = ""
    station_relation_status: Literal["resolved", "missing", "ambiguous", "stale"] = "missing"
    section_relation_status: Literal["resolved", "missing", "ambiguous", "stale"] = "missing"
    candidate_station_ids: list[str] = Field(default_factory=list)
    candidate_section_ids: list[str] = Field(default_factory=list)
    identity_entity_id: str = ""
    identity_match_status: str = "unresolved"
    identity_match_source: str = ""
    lldp_suggestion_status: Literal["none", "suggested", "ambiguous"] = "none"
    lldp_suggested_station_id: str = ""
    lldp_suggested_station_name: str = ""
    lldp_suggestion_switch_device_id: str = ""
    lldp_suggestion_switch_name: str = ""
    lldp_suggestion_interface: str = ""
    lldp_observed_neighbor_mac: str = ""
    lldp_observed_at: str = ""
    section_start_station: str = ""
    section_end_station: str = ""
    mileage: MileageDTO
    line_side: str = ""
    line_side_source: LineSideSource = "unavailable"
    line_side_derivation_issue_code: str = ""
    line_side_derivation_issue_message: str = ""
    direction: str = ""
    location_class: Literal[
        "MAINLINE",
        "DEPOT",
        "PARKING_YARD",
        "STABLING",
        "DEPOT_CONNECTION",
        "TEST_TRACK",
        "NON_MAINLINE",
        "UNKNOWN",
    ] = "MAINLINE"
    participates_in_mainline: bool = True
    location_class_source: str = "DEFAULT_MAINLINE"
    location_class_conflict: bool = False
    radios: list[MeshRadioDTO] = Field(default_factory=list)
    remark: str = ""
    source_file: str = ""
    source_sheet: str = ""
    source_row: int | None = None
    updated_at: str = ""
    runtime: RelatedRuntimeStatusDTO = Field(default_factory=RelatedRuntimeStatusDTO)
    issue_count: int = 0
    highest_issue_severity: str = ""
    record_kind: str = "ap"
    base_metadata: dict[str, Any] = Field(default_factory=dict)


class TracksideApDetailDTO(ApiModel):
    ap: TracksideApDTO
    issues: list[DataQualityIssueDTO] = Field(default_factory=list)


class VehicleMrDTO(ApiModel):
    id: str
    device_id: int | None = None
    name: str
    train_id: str = ""
    train_no: str = ""
    role: str = Field(default="", json_schema_extra={"deprecated": True})
    mr_position_code: MrPositionCode = "unknown"
    physical_end: MrPhysicalEnd = "unknown"
    car_number: int | None = None
    management_ip: str = ""
    station: str = ""
    mac: str = ""
    protocol: str = ""
    port: int | None = None
    remark: str = ""
    runtime: RelatedRuntimeStatusDTO = Field(default_factory=RelatedRuntimeStatusDTO)
    issue_count: int = 0
    highest_issue_severity: str = ""


class BaseDataTracksideApPlanRowDTO(ApiModel):
    station_id: str = ""
    sequence_no: int = 0
    station_name: str = ""
    planned_ap_count: int = Field(default=0, ge=0)
    management_vlan: int | None = Field(default=None, ge=1, le=4094)
    remark: str = ""
    relation_status: Literal["resolved", "missing", "ambiguous", "stale"] = "missing"
    candidate_station_ids: list[str] = Field(default_factory=list)


class BaseDataEditSnapshotDTO(BaseDataEditSessionDTO):
    scope: BaseDataEditScope = "all"
    metadata: RailTransitSummaryDTO
    stations: list[StationDTO] = Field(default_factory=list)
    sections: list[SectionDTO] = Field(default_factory=list)
    trackside_aps: list[TracksideApDTO] = Field(default_factory=list)
    trackside_ap_plans: list[BaseDataTracksideApPlanRowDTO] = Field(default_factory=list)
    device_station_bindings: list[DeviceStationBindingDTO] = Field(default_factory=list)
    vehicle_mrs: list[VehicleMrDTO] = Field(default_factory=list)


class VehicleMrDetailDTO(ApiModel):
    mr: VehicleMrDTO
    issues: list[DataQualityIssueDTO] = Field(default_factory=list)


class TrainDTO(ApiModel):
    id: str
    train_no: str
    name: str
    mr_count: int = 0
    roles: list[str] = Field(default_factory=list, json_schema_extra={"deprecated": True})
    mr_position_codes: list[MrPositionCode] = Field(default_factory=list)
    latest_mesh_status: str = "unknown"
    latest_session_id: str = ""
    issue_count: int = 0
    highest_issue_severity: str = ""


class TrainDetailDTO(ApiModel):
    train: TrainDTO
    mrs: list[VehicleMrDTO] = Field(default_factory=list)
    issues: list[DataQualityIssueDTO] = Field(default_factory=list)


class StationPageDTO(ApiModel):
    items: list[StationDTO] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50


class SectionPageDTO(ApiModel):
    items: list[SectionDTO] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50


class TracksideApPageDTO(ApiModel):
    items: list[TracksideApDTO] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50


class TrainPageDTO(ApiModel):
    items: list[TrainDTO] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50


class VehicleMrPageDTO(ApiModel):
    items: list[VehicleMrDTO] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50


class DataQualityIssuePageDTO(ApiModel):
    items: list[DataQualityIssueDTO] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50


class RailTransitRelationDTO(ApiModel):
    mr_id: str = ""
    mr_name: str = ""
    train_no: str = ""
    ap_id: str = ""
    ap_name: str = ""
    station: str = ""
    section: str = ""
    status: str = "unknown"
    updated_at: str = ""


class RailTransitRelationPageDTO(ApiModel):
    items: list[RailTransitRelationDTO] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50


class ImportPreviewRowDTO(ApiModel):
    row_number: int
    entity_type: str = "ap"
    values: dict[str, Any] = Field(default_factory=dict)
    issues: list[DataQualityIssueDTO] = Field(default_factory=list)


class FieldProvenanceDTO(ApiModel):
    field_name: str
    value: Any = None
    source_type: str
    source_reference: str = ""
    source_row: int | None = None
    imported_at: str = ""
    confirmed: bool = False
    priority: int = 0
    warning: str = ""


class MergeFieldDiffDTO(ApiModel):
    field_name: str
    current_value: Any = None
    proposed_value: Any = None
    source: FieldProvenanceDTO
    action: Literal["keep_existing", "use_imported", "fill_missing", "manual_review"]
    warning: str = ""


class MergePlanItemDTO(ApiModel):
    row_number: int
    entity_type: str = "ap"
    source_identity: dict[str, Any] = Field(default_factory=dict)
    matched_entity_id: str = ""
    matched_entity_name: str = ""
    match_method: str = ""
    result: MergeResult
    conflict_summary: str = ""
    field_diffs: list[MergeFieldDiffDTO] = Field(default_factory=list)
    source_values: dict[str, Any] = Field(default_factory=dict)
    blocking: bool = False
    issues: list[DataQualityIssueDTO] = Field(default_factory=list)


class MergePlanSummaryDTO(ApiModel):
    total_rows: int = 0
    importable_count: int = 0
    create_count: int = 0
    update_count: int = 0
    unchanged_count: int = 0
    skip_count: int = 0
    conflict_count: int = 0
    invalid_count: int = 0
    warning_count: int = 0
    unmatched_fit_ap_count: int = 0
    needs_confirmation_count: int = 0
    blocking_count: int = 0


class MergePlanDTO(ApiModel):
    plan_id: str
    site_id: str
    source_file_name: str
    source_file_sha256: str
    source_type: str
    database_hash: str
    created_at: str
    preview_expires_at: str
    write_enabled: bool = False
    items: list[MergePlanItemDTO] = Field(default_factory=list)
    summary: MergePlanSummaryDTO = Field(default_factory=MergePlanSummaryDTO)


class ImportPolicyDTO(ApiModel):
    entity_type: str
    field_name: str
    priority: list[str] = Field(default_factory=list)
    runtime_only: bool = False
    note: str = ""


class ImportPolicyResponseDTO(ApiModel):
    feature_enabled: bool = False
    write_enabled: bool = False
    copy_write_authorized: bool = False
    real_write_authorized: bool = False
    rollback_enabled: bool = False
    write_scope: str = "real"
    identity_boundaries: dict[str, str] = Field(default_factory=dict)
    items: list[ImportPolicyDTO] = Field(default_factory=list)


class ImportPreviewResultDTO(ApiModel):
    preview_id: str = ""
    file_name: str
    file_size: int
    template_type: str = ""
    confidence_score: int = 0
    total_rows: int = 0
    valid_rows: int = 0
    error_count: int = 0
    warning_count: int = 0
    sheet_names: list[str] = Field(default_factory=list)
    statistics: dict[str, int] = Field(default_factory=dict)
    rows: list[ImportPreviewRowDTO] = Field(default_factory=list)
    merge_plan: MergePlanDTO | None = None
    database_hash: str = ""
    preview_expires_at: str = ""
    write_enabled: bool = False
    message: str = "当前仅支持校验和合并预览。正式写入功能默认关闭。"


class MergeFieldDecisionDTO(ApiModel):
    row_number: int = Field(ge=1)
    field_name: str = ""
    action: Literal["keep_existing", "use_imported", "fill_missing", "skip_entity"]


class ImportApplyRequestDTO(ApiModel):
    preview_id: str
    site_id: str
    explicit_confirmation: bool = False
    decisions: list[MergeFieldDecisionDTO] = Field(default_factory=list)
    expected_database_sha256: str


class ImportApplyResultDTO(ApiModel):
    operation_id: str
    status: str
    total_rows: int = 0
    imported_rows: int = 0
    created_rows: int = 0
    updated_rows: int = 0
    unchanged_rows: int = 0
    warning_rows: int = 0
    skipped_conflict_rows: int = 0
    skipped_invalid_rows: int = 0
    unmatched_fit_ap_rows: int = 0
    issues: list[DataQualityIssueDTO] = Field(default_factory=list)
    created_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    warning_count: int = 0
    backup_id: str
    database_sha256_before: str
    database_sha256_after: str
    audit_id: str


class ImportOperationDTO(ApiModel):
    operation_id: str
    preview_id: str
    site_id: str
    source_file_name: str
    source_file_sha256: str
    owner: str = ""
    started_at: str
    ended_at: str = ""
    status: str
    created_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    warning_count: int = 0
    backup_reference: str = ""
    database_hash_before: str = ""
    database_hash_after: str = ""
    error_code: str = ""
    error_summary: str = ""
    rolled_back_at: str = ""


class ImportOperationPageDTO(ApiModel):
    items: list[ImportOperationDTO] = Field(default_factory=list)
    total: int = 0


class ImportChangeDTO(ApiModel):
    operation_id: str
    entity_type: str = "ap"
    entity_id: str
    action: str
    field_name: str
    old_value: Any = None
    new_value: Any = None
    source_type: str = ""
    source_reference: str = ""
    confirmation_method: str = "policy"


class ImportChangePageDTO(ApiModel):
    items: list[ImportChangeDTO] = Field(default_factory=list)
    total: int = 0


class ImportRollbackRequestDTO(ApiModel):
    explicit_confirmation: bool = False


class ImportRollbackResultDTO(ApiModel):
    operation_id: str
    status: str
    rolled_back_at: str = ""
    database_sha256: str = ""


__all__ = [name for name in globals() if name.endswith("DTO")]
