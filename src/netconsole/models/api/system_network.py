from __future__ import annotations

from pydantic import Field

from netconsole.models.api.common import ApiModel


class LocalIpv4AddressDTO(ApiModel):
    adapter_id: str
    adapter_name: str
    description: str = ""
    interface_index: int = 0
    ipv4: str
    prefix_length: int = Field(ge=0, le=32)
    netmask: str = ""
    gateway: str = ""
    is_up: bool = False
    is_loopback: bool = False
    is_virtual: bool = False
    is_apipa: bool = False
    has_default_route: bool = False
    route_metric: int | None = None
    source: str = ""
    recommended: bool = False
    recommendation_reason: str = ""


class LocalIpv4AddressPageDTO(ApiModel):
    items: list[LocalIpv4AddressDTO] = Field(default_factory=list)
    total: int = 0
    generated_at: str = ""


class SourceIpRecommendationRequestDTO(ApiModel):
    target_ips: list[str] = Field(default_factory=list, max_length=200)
    preferred_ip: str = Field(default="", max_length=255)


class SourceIpRouteDTO(ApiModel):
    target_ip: str
    source_ip: str = ""
    reachable: bool = False
    reason: str = ""


class SourceIpRecommendationDTO(ApiModel):
    recommended_ip: str = ""
    recommendation_reason: str = ""
    routes: list[SourceIpRouteDTO] = Field(default_factory=list)
    candidates: list[LocalIpv4AddressDTO] = Field(default_factory=list)
    generated_at: str = ""


class UdpPortCheckRequestDTO(ApiModel):
    listen_host: str = Field(default="0.0.0.0", max_length=255)
    listen_port: int = Field(default=514, ge=1, le=65_535)


class UdpPortCheckDTO(ApiModel):
    listen_host: str
    listen_port: int
    available: bool
    status: str
    message: str = ""
    checked_at: str = ""


__all__ = [
    "LocalIpv4AddressDTO",
    "LocalIpv4AddressPageDTO",
    "SourceIpRecommendationDTO",
    "SourceIpRecommendationRequestDTO",
    "SourceIpRouteDTO",
    "UdpPortCheckDTO",
    "UdpPortCheckRequestDTO",
]
