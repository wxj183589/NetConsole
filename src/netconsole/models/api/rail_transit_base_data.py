from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from netconsole.models.api.common import ApiModel


IssueSeverity = Literal["error", "warning", "info"]
MergeResult = Literal["CREATE", "UPDATE", "UNCHANGED", "SKIP", "CONFLICT", "NEEDS_CONFIRMATION"]


class MileageDTO(ApiModel):
    raw: str = ""
    normalized: str = ""
    meters: float | None = None
    line_type: str = ""
    valid: bool = False
    error: str = ""


class RelatedRuntimeStatusDTO(ApiModel):
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
    remark: str = ""
    created_at: str = ""
    updated_at: str = ""
    station_count: int = 0
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
    name: str
    code: str = ""
    line_name: str = ""
    sort_order: int = 0
    ap_count: int = 0
    section_count: int = 0
    mileage_min: float | None = None
    mileage_max: float | None = None
    remark: str = ""


class SectionDTO(ApiModel):
    id: str
    name: str
    start_station: str = ""
    end_station: str = ""
    line_side: str = ""
    ap_count: int = 0
    mileage_min: float | None = None
    mileage_max: float | None = None
    remark: str = ""


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
    mac: str = ""
    management_ip: str = ""
    model: str = ""
    station: str = ""
    section: str = ""
    section_start_station: str = ""
    section_end_station: str = ""
    mileage: MileageDTO
    line_side: str = ""
    direction: str = ""
    radios: list[MeshRadioDTO] = Field(default_factory=list)
    remark: str = ""
    source_file: str = ""
    source_sheet: str = ""
    source_row: int | None = None
    updated_at: str = ""
    runtime: RelatedRuntimeStatusDTO = Field(default_factory=RelatedRuntimeStatusDTO)
    issue_count: int = 0
    highest_issue_severity: str = ""


class TracksideApDetailDTO(ApiModel):
    ap: TracksideApDTO
    issues: list[DataQualityIssueDTO] = Field(default_factory=list)


class VehicleMrDTO(ApiModel):
    id: str
    device_id: int | None = None
    name: str
    train_id: str = ""
    train_no: str = ""
    role: str = ""
    management_ip: str = ""
    mac: str = ""
    protocol: str = ""
    port: int | None = None
    remark: str = ""
    runtime: RelatedRuntimeStatusDTO = Field(default_factory=RelatedRuntimeStatusDTO)
    issue_count: int = 0
    highest_issue_severity: str = ""


class VehicleMrDetailDTO(ApiModel):
    mr: VehicleMrDTO
    issues: list[DataQualityIssueDTO] = Field(default_factory=list)


class TrainDTO(ApiModel):
    id: str
    train_no: str
    name: str
    mr_count: int = 0
    roles: list[str] = Field(default_factory=list)
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
    create_count: int = 0
    update_count: int = 0
    unchanged_count: int = 0
    skip_count: int = 0
    conflict_count: int = 0
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
    write_enabled: bool = False
    identity_boundaries: dict[str, str] = Field(default_factory=dict)
    items: list[ImportPolicyDTO] = Field(default_factory=list)


class ImportPreviewResultDTO(ApiModel):
    file_name: str
    file_size: int
    template_type: str = ""
    confidence_score: int = 0
    total_rows: int = 0
    valid_rows: int = 0
    error_count: int = 0
    warning_count: int = 0
    rows: list[ImportPreviewRowDTO] = Field(default_factory=list)
    merge_plan: MergePlanDTO | None = None
    database_hash: str = ""
    preview_expires_at: str = ""
    write_enabled: bool = False
    message: str = "当前仅支持校验和合并预览。正式写入功能默认关闭。"


__all__ = [name for name in globals() if name.endswith("DTO")]
