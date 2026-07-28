from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from netconsole.models.api.common import ApiModel


class DeviceDetailSourceDTO(ApiModel):
    available: bool = True
    source: str
    collected_at: str | None = None
    task_id: str | None = None
    reason: str | None = None


class DevicePlatformFactsDTO(ApiModel):
    vendor: str
    role: str
    platform: str
    software_version: str | None = None
    software_major: str | None = None
    source: str
    confidence: Literal["high", "medium", "low", "unknown"]
    collected_at: str | None = None


class DeviceDetailCapabilityDTO(ApiModel):
    capability_id: str
    available: bool
    executable: bool = False
    source: str
    reason: str | None = None
    profile_id: str | None = None
    profile_version: int | None = None
    compatibility: str | None = None
    risk: str | None = None
    real_device_status: str | None = None


class DeviceOverviewCountsDTO(ApiModel):
    interfaces: int | None = None
    transceivers: int | None = None
    lldp_neighbors: int | None = None
    recent_tasks: int | None = None
    config_snapshots: int | None = None


class DeviceOverviewTaskFactDTO(ApiModel):
    task_id: str
    task_type: str
    status: str
    updated_at: str
    finished_at: str | None = None
    message: str | None = None


class DeviceOverviewTaskFactsDTO(ApiModel):
    recent_task_count: int | None = None
    active_task_count: int | None = None
    latest_running_task: DeviceOverviewTaskFactDTO | None = None
    latest_successful_task: DeviceOverviewTaskFactDTO | None = None
    latest_failed_task: DeviceOverviewTaskFactDTO | None = None
    latest_error: str | None = None
    truncated: bool = False


class DeviceOverviewDTO(ApiModel):
    device_uuid: str
    name: str
    system_name: str | None = None
    device_type: str | None = None
    station: str | None = None
    location: str | None = None
    primary_address: str | None = None
    backup_address: str | None = None
    protocol: str | None = None
    port: int | None = None
    group_id: int | None = None
    group_name: str | None = None
    cpu_usage: float | None = None
    memory_usage: float | None = None
    model: str | None = None
    serial_number: str | None = None
    mac_address: str | None = None
    bootrom_version: str | None = None
    uptime: str | None = None
    connection_status: str = "UNKNOWN"
    platform_facts: DevicePlatformFactsDTO
    capabilities: list[DeviceDetailCapabilityDTO] = Field(default_factory=list)
    command_profile: DeviceDetailCapabilityDTO
    visible_sections: list[
        Literal[
            "overview",
            "interfaces",
            "optical",
            "lldp",
            "configuration",
            "tasks",
            "business",
        ]
    ]
    task_facts: DeviceOverviewTaskFactsDTO
    counts: DeviceOverviewCountsDTO = Field(default_factory=DeviceOverviewCountsDTO)
    snapshot: DeviceDetailSourceDTO


class DeviceInterfaceDTO(ApiModel):
    name: str
    normalized_name: str
    category: str
    link_status: str | None = None
    admin_status: str | None = None
    physical_status: str | None = None
    protocol_status: str | None = None
    media_attribute: str | None = None
    media_type: str | None = None
    speed: str | None = None
    duplex: str | None = None
    interface_type: str | None = None
    port_status: str | None = None
    port_mode: str | None = None
    pvid: str | None = None
    native_vlan: str | None = None
    tagged_vlans: list[str] = Field(default_factory=list)
    untagged_vlans: list[str] = Field(default_factory=list)
    pvid_source: str | None = None
    pvid_verified: bool | None = None
    vlan_config_status: str | None = None
    vlan_config_collected_at: str | None = None
    vlan_warnings: list[dict[str, object]] = Field(default_factory=list)
    description: str | None = None
    ip_address: str | None = None
    mac_address: str | None = None
    vlan: str | None = None
    optical_status: str | None = None
    lldp_summary: str | None = None
    collected_at: str | None = None


class DeviceInterfacePageDTO(ApiModel):
    items: list[DeviceInterfaceDTO] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    total_pages: int = 1
    source: DeviceDetailSourceDTO


class DeviceTransceiverDTO(ApiModel):
    interface_name: str
    normalized_interface_name: str
    rx_power: float | None = None
    tx_power: float | None = None
    temperature: float | None = None
    voltage: float | None = None
    bias_current: float | None = None
    module_model: str | None = None
    module_serial_number: str | None = None
    module_vendor: str | None = None
    wavelength: str | None = None
    transmission_distance: str | None = None
    connector_type: str | None = None
    device_vendor: str | None = Field(default=None, exclude_if=lambda value: value is None)
    device_reported_status: str | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    threshold_source: str | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    transceiver_mode: str | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    vendor_part_number: str | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    vendor_revision: str | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    vendor_serial_number: str | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    rx_low_alarm: float | None = None
    rx_high_alarm: float | None = None
    rx_low_warning: float | None = None
    rx_high_warning: float | None = None
    tx_low_alarm: float | None = None
    tx_high_alarm: float | None = None
    tx_low_warning: float | None = None
    tx_high_warning: float | None = None
    severity: str
    severity_reason: str | None = None
    collected_at: str | None = None


class DeviceTransceiverPageDTO(ApiModel):
    items: list[DeviceTransceiverDTO] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    total_pages: int = 1
    truncated: bool = False
    source: DeviceDetailSourceDTO


class DeviceLldpNeighborDTO(ApiModel):
    local_interface: str
    normalized_local_interface: str
    scope: str | None = None
    chassis_type: str | None = None
    chassis_id: str | None = None
    neighbor_system_name: str | None = None
    neighbor_mac: str | None = None
    port_id_type: str | None = None
    neighbor_interface: str | None = None
    neighbor_ip: str | None = None
    holdtime: int | None = None
    ttl: int | None = None
    port_description: str | None = None
    system_description: str | None = None
    system_capabilities: str | None = None
    pvid: int | None = None
    operational_mau: str | None = None
    max_frame_size: int | None = None
    neighbor_device_uuid: str | None = None
    association_status: Literal["matched", "unresolved"] = "unresolved"
    collected_at: str | None = None


class DeviceLldpPageDTO(ApiModel):
    items: list[DeviceLldpNeighborDTO] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    total_pages: int = 1
    source: DeviceDetailSourceDTO


class DeviceInterfaceDetailDTO(ApiModel):
    interface: DeviceInterfaceDTO
    transceiver: DeviceTransceiverDTO | None = None
    lldp_neighbors: list[DeviceLldpNeighborDTO] = Field(default_factory=list)
    lldp_truncated: bool = False
    source: DeviceDetailSourceDTO


class DeviceConfigSnapshotDTO(ApiModel):
    snapshot_id: int
    snapshot_type: str
    timestamp: str
    size_bytes: int | None = None
    artifact_id: str | None = None
    filename: str | None = None
    sha256: str | None = None
    created_at: str | None = None
    error_summary: str | None = None


class DeviceConfigSnapshotPageDTO(ApiModel):
    items: list[DeviceConfigSnapshotDTO] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    total_pages: int = 1
    source: DeviceDetailSourceDTO


class DeviceDetailTaskDTO(ApiModel):
    task_id: str
    task_type: str
    task_name: str
    status: str
    progress: int = 0
    stage: str | None = None
    message: str | None = None
    error_summary: str | None = None
    created_at: str
    updated_at: str
    started_at: str | None = None
    finished_at: str | None = None


class DeviceDetailTaskPageDTO(ApiModel):
    items: list[DeviceDetailTaskDTO] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    total_pages: int = 1
    truncated: bool = False
    source: DeviceDetailSourceDTO


class DeviceTracksideApAssociationFactsDTO(ApiModel):
    link_status: str | None = None
    switch_rx_power: float | None = None
    ap_rx_power: float | None = None


class DeviceAcApAssociationFactsDTO(ApiModel):
    mac_address: str | None = None
    radio1_status: str | None = None
    radio1_channel: str | None = None
    radio1_power: str | None = None
    radio2_status: str | None = None
    radio2_channel: str | None = None
    radio2_power: str | None = None
    lldp_status: str | None = None
    optical_status: str | None = None
    optical_rx_power: float | None = None


class DeviceMrSessionAssociationFactsDTO(ApiModel):
    site_id: str
    started_at: str | None = None
    stopped_at: str | None = None
    executor_kind: str | None = None
    has_raw_data: bool = False
    has_parsed_data: bool = False
    has_package: bool = False
    mesh_available: bool = False
    rssi_available: bool = False
    fping_available: bool = False
    iperf_available: bool = False


class DeviceBusinessAssociationDTO(ApiModel):
    association_type: Literal["trackside_ap", "fit_ap", "online_mr_session"]
    association_id: str
    name: str | None = None
    status: str | None = None
    local_interface: str | None = None
    peer_address: str | None = None
    trackside_ap: DeviceTracksideApAssociationFactsDTO | None = None
    fit_ap: DeviceAcApAssociationFactsDTO | None = None
    online_mr_session: DeviceMrSessionAssociationFactsDTO | None = None
    updated_at: str | None = None


class DeviceBusinessAssociationPageDTO(ApiModel):
    items: list[DeviceBusinessAssociationDTO] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    total_pages: int = 1
    truncated: bool = False
    source: DeviceDetailSourceDTO


class DeviceHistoryRecordDTO(ApiModel):
    kind: Literal["interface", "optical", "lldp"]
    object_name: str
    collected_at: str | None = None
    values: dict[str, Any] = Field(default_factory=dict)


class DeviceHistoryPageDTO(ApiModel):
    items: list[DeviceHistoryRecordDTO] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    total_pages: int = 1
    source: DeviceDetailSourceDTO


class DeviceRefreshRequestDTO(ApiModel):
    operation_id: Literal["device.inventory.collect"] = "device.inventory.collect"
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)


class DeviceRefreshTaskDTO(ApiModel):
    task_id: str
    operation_id: str
    status: str
    reused: bool = False
    message: str | None = None
    profile_id: str | None = None
    profile_version: int | None = None


__all__ = [name for name in globals() if name.endswith("DTO")]
