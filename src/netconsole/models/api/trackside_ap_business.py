from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from netconsole.models.api.common import ApiModel


class TracksideApBusinessRowDTO(ApiModel):
    site: str = ""
    device_name: str = ""
    interface_name: str = ""
    link_status: str = ""
    port_type: str = ""
    description: str = ""
    pvid: Any = None
    vlan: Any = None
    switch_rx_power: Any = None
    switch_optical_status: str = ""
    ap_uuid: str = ""
    ap_mac: str = ""
    ap_name: str = ""
    ap_rx_power: Any = None
    ap_optical_status: str = ""
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


__all__ = [name for name in globals() if name.startswith("TracksideAp")]
