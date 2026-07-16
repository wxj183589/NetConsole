from __future__ import annotations

from typing import Any

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


__all__ = [name for name in globals() if name.startswith("TracksideAp")]
