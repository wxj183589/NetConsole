from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from netconsole.models.api.common import ApiModel


class CommunicationWarningDTO(ApiModel):
    code: str
    message: str
    source: str
    severity: str = "warning"


class CommunicationDataSourceDTO(ApiModel):
    source: str
    status: str = "no_data"
    updated_at: str | None = None
    age_seconds: int | None = None
    reference: str = ""


class CommunicationMetricDTO(ApiModel):
    status: str = "no_data"
    target: str | None = None
    protocol: str | None = None
    direction: str | None = None
    sent: int | None = None
    received: int | None = None
    loss_percent: float | None = None
    latest_value: float | None = None
    average_value: float | None = None
    maximum_value: float | None = None
    threshold_value: float | None = None
    updated_at: str | None = None


class CommunicationRawSourceDTO(ApiModel):
    name: str
    label: str
    session_id: str
    exists: bool = False
    size_bytes: int = 0
    modified_at: str | None = None
    message: str = ""


class CommunicationPackageDTO(ApiModel):
    session_id: str
    package_name: str
    package_reference: str
    executor: str = ""
    agent_id: str | None = None
    import_status: str = "not_applicable"
    data_integrity: str = "unknown"
    collected_at: str | None = None


class CommunicationTaskDTO(ApiModel):
    id: str
    type: str
    name: str
    status: str
    progress: int = 0
    executor: str = "LOCAL"
    source: str = "local"
    started_at: str = ""
    ended_at: str = ""
    updated_at: str = ""
    error_summary: str = ""


class MrCommunicationStatusDTO(ApiModel):
    train_id: str
    train_name: str
    mr_id: str
    mr_name: str
    mr_role: str = ""
    device_id: int | str | None = None
    management_ip: str = ""
    mac: str = ""
    executor: str | None = None
    agent_id: str | None = None
    collection_status: str = "no_data"
    session_id: str | None = None
    task_id: str | None = None
    mesh_link_status: str = "unknown"
    peer_ap_id: str = ""
    peer_ap_name: str = ""
    peer_ap_mac: str = ""
    mesh_radio: str = ""
    rssi: float | None = None
    station: str = ""
    section: str = ""
    mileage: str = ""
    line_side: str = ""
    ap_online_status: str = "unknown"
    optical_status: str = "no_data"
    fping_status: str = "no_data"
    fping_latest_rtt_ms: float | None = None
    fping_avg_rtt_ms: float | None = None
    fping_loss_percent: float | None = None
    iperf_status: str = "no_data"
    iperf_latest_mbps: float | None = None
    iperf_avg_mbps: float | None = None
    iperf_threshold_mbps: float | None = None
    data_integrity: str = "unknown"
    collected_at: str | None = None
    data_age_seconds: int | None = None
    communication_status: str = "unknown"
    is_active: bool = False
    warnings: list[CommunicationWarningDTO] = Field(default_factory=list)
    data_sources: list[CommunicationDataSourceDTO] = Field(default_factory=list)
    fping: CommunicationMetricDTO = Field(default_factory=CommunicationMetricDTO)
    iperf: CommunicationMetricDTO = Field(default_factory=CommunicationMetricDTO)


class TrainCommunicationRowDTO(ApiModel):
    train_id: str
    train_no: str
    train_name: str
    communication_status: str = "unknown"
    mrs: list[MrCommunicationStatusDTO] = Field(default_factory=list)
    current_mesh_links: int = 0
    active_sessions: int = 0
    warning_count: int = 0
    last_updated_at: str | None = None


class TrainCommunicationDetailDTO(ApiModel):
    train: TrainCommunicationRowDTO
    site_id: str
    sources: list[CommunicationDataSourceDTO] = Field(default_factory=list)
    warnings: list[CommunicationWarningDTO] = Field(default_factory=list)


class TrainCommunicationPageDTO(ApiModel):
    items: list[TrainCommunicationRowDTO] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50


class TrainCommunicationSummaryDTO(ApiModel):
    site_id: str
    registered_trains: int = 0
    registered_mrs: int = 0
    normal_trains: int = 0
    warning_trains: int = 0
    critical_trains: int = 0
    stale_trains: int = 0
    unknown_trains: int = 0
    current_mesh_links: int = 0
    active_online_mr_sessions: int = 0
    agent_imported_sessions: int = 0
    latest_updated_at: str | None = None


TopologyStatus = Literal["normal", "abnormal", "not_detected", "not_configured", "checking", "stale"]


class TrainCommunicationTopologyNodeDTO(ApiModel):
    node_id: str
    side: Literal["TC1", "TC2"]
    role: Literal["MR", "SWITCH", "SERVER"]
    name: str = ""
    device_id: str | None = None
    ip_address: str | None = None
    status: TopologyStatus = "not_configured"
    message: str = ""
    updated_at: str | None = None


class TrainCommunicationTopologyLinkDTO(ApiModel):
    link_id: str
    source: str
    target: str
    label: str
    status: TopologyStatus = "not_detected"
    message: str = ""


class TrainCommunicationVrrpDTO(ApiModel):
    status: TopologyStatus = "not_detected"
    master_side: Literal["TC1", "TC2"] | None = None
    virtual_ip: str | None = None
    master_device: str | None = None
    backup_device: str | None = None
    message: str = ""
    updated_at: str | None = None


class TrainCommunicationCrossEndDTO(ApiModel):
    status: TopologyStatus = "not_detected"
    message: str = ""
    updated_at: str | None = None


class TrainCommunicationTopologyDTO(ApiModel):
    train_id: str
    train_name: str
    train_status: TopologyStatus = "not_detected"
    checked_at: str | None = None
    tc1_nodes: list[TrainCommunicationTopologyNodeDTO] = Field(default_factory=list)
    tc2_nodes: list[TrainCommunicationTopologyNodeDTO] = Field(default_factory=list)
    links: list[TrainCommunicationTopologyLinkDTO] = Field(default_factory=list)
    vrrp: TrainCommunicationVrrpDTO = Field(default_factory=TrainCommunicationVrrpDTO)
    cross_end: TrainCommunicationCrossEndDTO = Field(default_factory=TrainCommunicationCrossEndDTO)


class MrCommunicationDetailDTO(ApiModel):
    mr: MrCommunicationStatusDTO
    collectors: list[dict[str, Any]] = Field(default_factory=list)
    raw_sources: list[CommunicationRawSourceDTO] = Field(default_factory=list)
    tasks: list[CommunicationTaskDTO] = Field(default_factory=list)
    packages: list[CommunicationPackageDTO] = Field(default_factory=list)


__all__ = [
    "CommunicationDataSourceDTO",
    "CommunicationMetricDTO",
    "CommunicationPackageDTO",
    "CommunicationRawSourceDTO",
    "CommunicationTaskDTO",
    "CommunicationWarningDTO",
    "MrCommunicationDetailDTO",
    "MrCommunicationStatusDTO",
    "TrainCommunicationDetailDTO",
    "TrainCommunicationPageDTO",
    "TrainCommunicationRowDTO",
    "TrainCommunicationSummaryDTO",
    "TrainCommunicationTopologyDTO",
    "TrainCommunicationTopologyLinkDTO",
    "TrainCommunicationTopologyNodeDTO",
    "TrainCommunicationVrrpDTO",
    "TrainCommunicationCrossEndDTO",
]
