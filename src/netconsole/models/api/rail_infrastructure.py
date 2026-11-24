"""Read-only infrastructure workbench contracts."""

from typing import Literal

from pydantic import Field

from netconsole.models.api.common import ApiModel
from netconsole.models.api.rail_transit_base_data import SectionDTO, StationDTO


class InfrastructureDeviceDTO(ApiModel):
    device_uuid: str
    name: str
    vendor: str = ""
    platform: str = ""
    device_type: str
    device_role: str = ''
    role: str = ""
    service_stations: list[str] = Field(default_factory=list)
    section_uid: str | None = None
    source: Literal["engineering", "legacy_station"]


class InfrastructureNameDTO(ApiModel):
    name: str
    name_type: str
    source: str
    valid_from: str | None = None
    valid_to: str | None = None


class InfrastructureProjectDTO(ApiModel):
    project_id: str
    name: str
    stage: str


class InfrastructureNodeDTO(ApiModel):
    uid: str
    kind: Literal["station", "depot", "parking_yard", "cocc", "bocc", "train", "section"]
    code: str = ""
    name: str
    source: Literal["engineering", "legacy_station", "legacy_train"]
    station: StationDTO | None = None
    aliases: list[InfrastructureNameDTO] = Field(default_factory=list)
    projects: list[InfrastructureProjectDTO] = Field(default_factory=list)
    devices: list[InfrastructureDeviceDTO] = Field(default_factory=list)
    sections: list[SectionDTO] = Field(default_factory=list)
    ac_service_stations: list[str] = Field(default_factory=list)
    parent_uid: str = ""
    sort_order: int = 0
    custom: bool = False


class InfrastructureDTO(ApiModel):
    site_id: str
    site_name: str
    line_name: str
    schema_available: bool = False
    organization_initialized: bool = False
    organization_writable: bool = False
    device_count: int
    unassociated_device_count: int
    unresolved_binding_count: int
    nodes: list[InfrastructureNodeDTO] = Field(default_factory=list)
    unassociated_devices: list[InfrastructureDeviceDTO] = Field(default_factory=list)


class OrganizationAssetDTO(ApiModel):
    device_uuid: str
    name: str
    address: str = ""
    mac: str = ""
    serial: str = ""
    device_type: str = ""
    group_name: str = ""
    node_uids: list[str] = Field(default_factory=list)
    project_ids: list[str] = Field(default_factory=list)
    collection: Literal["included", "excluded"]


class OrganizationCatalogDTO(ApiModel):
    revision: str
    devices: list[OrganizationAssetDTO]
    projects: list[InfrastructureProjectDTO]


class OrganizationBatchRequest(ApiModel):
    revision: str = Field(min_length=1, max_length=40)
    device_uuids: list[str] = Field(min_length=1, max_length=500)
    node_uid: str = Field(default="", max_length=160)
    collection: Literal["included", "excluded"] | None = None
    add_projects: list[str] = Field(default_factory=list, max_length=50)
    remove_projects: list[str] = Field(default_factory=list, max_length=50)
    explicit_confirmation: bool = False


class OrganizationAssetChangeDTO(ApiModel):
    before: OrganizationAssetDTO
    after: OrganizationAssetDTO


class OrganizationBatchResultDTO(ApiModel):
    revision: str
    changes: list[OrganizationAssetChangeDTO]


class OrganizationNodeRequest(ApiModel):
    revision: str = Field(min_length=1, max_length=40)
    node_uid: str = Field(default="", max_length=160)
    parent_uid: str = Field(default="", max_length=160)
    kind: Literal["station", "depot", "parking_yard", "cocc", "bocc"]
    name: str = Field(min_length=1, max_length=120)
    code: str = Field(default="", max_length=50)
    sort_order: int = Field(default=0, ge=-10000, le=10000)
    explicit_confirmation: bool = False


class InfrastructureSwitchApDTO(ApiModel):
    row_id: str
    ap_uuid: str
    ap_name: str
    interface_name: str
    link_status: str


class InfrastructureSwitchApsDTO(ApiModel):
    items: list[InfrastructureSwitchApDTO] = Field(default_factory=list)
    total: int
    page: int
    page_size: int


class InfrastructureSwitchApContextDTO(InfrastructureSwitchApDTO):
    identity_match_status: str = "unresolved"
    recognition_status: str = "unidentified"
    primary_reason_label: str = ""
    section_ids: list[str] = Field(default_factory=list)


class InfrastructureSwitchApContextPageDTO(ApiModel):
    items: list[InfrastructureSwitchApContextDTO] = Field(default_factory=list)
    total: int
    page: int
    page_size: int
    partial_data: bool = False
    unavailable_sources: list[str] = Field(default_factory=list)
