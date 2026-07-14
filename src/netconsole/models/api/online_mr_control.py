from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from netconsole.models.api.common import ApiModel
from netconsole.models.api.online_mr import OnlineMrCollectorStatusDTO


class OnlineMrWebItemsDTO(ApiModel):
    terminal_monitor: bool = True
    mesh_link: bool = True
    channel_busy: bool = True
    ap_radio_statistics: bool = True
    switch_history: bool = True
    interface_rate: bool = True
    wireless_status: bool = True


class OnlineMrWebIntervalsDTO(ApiModel):
    mesh_link: int = Field(default=1, ge=1, le=3600)
    channel_busy: int = Field(default=9, ge=1, le=3600)
    ap_radio_statistics: int = Field(default=10, ge=1, le=3600)
    switch_history: int = Field(default=300, ge=10, le=86400)
    interface_rate: int = Field(default=2, ge=1, le=3600)
    wireless_status: int = Field(default=3, ge=1, le=3600)


class OnlineMrWebRadioDTO(ApiModel):
    channel_busy_radio: int = Field(default=1, ge=1, le=3)
    ap_radio_statistics_radio: int = Field(default=1, ge=1, le=3)
    wireless_status_radio: int = Field(default=1, ge=1, le=3)


class OnlineMrWebFpingDTO(ApiModel):
    enabled: bool = False
    target: str = Field(default="", max_length=64)
    packet_size: int = Field(default=64, ge=1, le=65535)
    interval_ms: int = Field(default=1000, ge=10, le=60000)
    timeout_ms: int = Field(default=4000, ge=1, le=60000)
    loss_warn_percent: float = Field(default=10.0, ge=0, le=100)
    latency_warn_ms: int = Field(default=4000, ge=1, le=60000)


class OnlineMrWebIperfDTO(ApiModel):
    enabled: bool = False
    server_ip: str = Field(default="", max_length=64)
    port: int = Field(default=5201, ge=1, le=65535)
    protocol: Literal["TCP", "UDP"] = "TCP"
    parallel: int = Field(default=1, ge=1, le=32)
    interval_seconds: int = Field(default=1, ge=1, le=60)
    udp_bitrate_mbps: float | None = Field(default=None, gt=0)
    tcp_report_threshold_mbps: float | None = Field(default=None, ge=0)
    reverse: bool = False


class OnlineMrWebStartRequestDTO(ApiModel):
    site_id: str = Field(min_length=1, max_length=100)
    device_id: int | str
    mr_id: str = Field(min_length=1, max_length=200)
    executor: Literal["LOCAL"] = "LOCAL"
    duration_minutes: int = Field(default=0, ge=0, le=1440)
    items: OnlineMrWebItemsDTO = Field(default_factory=OnlineMrWebItemsDTO)
    intervals: OnlineMrWebIntervalsDTO = Field(default_factory=OnlineMrWebIntervalsDTO)
    radio: OnlineMrWebRadioDTO = Field(default_factory=OnlineMrWebRadioDTO)
    fping: OnlineMrWebFpingDTO = Field(default_factory=OnlineMrWebFpingDTO)
    iperf: OnlineMrWebIperfDTO = Field(default_factory=OnlineMrWebIperfDTO)

    @field_validator("items")
    @classmethod
    def terminal_monitor_is_required(cls, value: OnlineMrWebItemsDTO) -> OnlineMrWebItemsDTO:
        if not value.terminal_monitor:
            raise ValueError("terminal_monitor 是 Online MR 原始采集契约的必选项")
        return value


class OnlineMrWebOperationDTO(ApiModel):
    operation_id: str
    task_id: str
    session_id: str | None = None
    site_id: str
    device_id: int | str | None = None
    device_name: str = ""
    mr_id: str = ""
    mr_name: str = ""
    owner: str = ""
    executor: Literal["LOCAL"] = "LOCAL"
    state: str
    phase: str
    task_status: str | None = None
    session_status: str | None = None
    mapping_status: str
    started_at: str | None = None
    updated_at: str
    duration_minutes: float | None = None
    duration_limit: int | None = None
    collectors: list[OnlineMrCollectorStatusDTO] = Field(default_factory=list)
    fping_status: str = "disabled"
    iperf_status: str = "disabled"
    package_status: str = "pending"
    package_path_reference: str | None = None
    error_code: str = ""
    error_summary: str = ""
    data_integrity: str = "unknown"


class OnlineMrWebControlStatusDTO(ApiModel):
    enabled: bool
    local_only: bool = True
    site_id: str
    operations: list[OnlineMrWebOperationDTO] = Field(default_factory=list)


__all__ = [name for name in globals() if name.startswith("OnlineMrWeb")]
