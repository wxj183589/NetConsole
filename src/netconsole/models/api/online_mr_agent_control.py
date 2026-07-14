from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from netconsole.models.api.common import ApiModel
from netconsole.models.api.online_mr_control import (
    OnlineMrWebFpingDTO,
    OnlineMrWebIntervalsDTO,
    OnlineMrWebIperfDTO,
    OnlineMrWebItemsDTO,
    OnlineMrWebRadioDTO,
)


class OnlineMrAgentProfileDTO(ApiModel):
    profile_id: str
    name: str
    address_display: str
    enabled: bool
    status: str = "UNKNOWN"
    has_credential: bool = False


class OnlineMrAgentCapabilitiesDTO(ApiModel):
    agent_executor_enabled: bool
    site_id: str
    profiles: list[OnlineMrAgentProfileDTO] = Field(default_factory=list)


class OnlineMrAgentReadinessDTO(ApiModel):
    profile_id: str
    ready: bool
    reachable: bool
    authenticated: bool
    agent_id: str = ""
    version: str = ""
    mr_collector_ready: bool = False
    fping_ready: bool = False
    iperf3_ready: bool = False
    error_code: str = ""
    error_summary: str = ""


class OnlineMrAgentWebStartRequestDTO(ApiModel):
    site_id: str = Field(min_length=1, max_length=100)
    device_id: int | str
    mr_id: str = Field(min_length=1, max_length=200)
    agent_profile_id: str = Field(min_length=1, max_length=200)
    executor: Literal["AGENT"] = "AGENT"
    duration_minutes: int = Field(default=0, ge=0, le=1440)
    items: OnlineMrWebItemsDTO = Field(default_factory=OnlineMrWebItemsDTO)
    intervals: OnlineMrWebIntervalsDTO = Field(default_factory=OnlineMrWebIntervalsDTO)
    radio: OnlineMrWebRadioDTO = Field(default_factory=OnlineMrWebRadioDTO)
    fping: OnlineMrWebFpingDTO = Field(default_factory=OnlineMrWebFpingDTO)
    iperf: OnlineMrWebIperfDTO = Field(default_factory=OnlineMrWebIperfDTO)

    @field_validator("items")
    @classmethod
    def terminal_monitor_is_required(
        cls, value: OnlineMrWebItemsDTO
    ) -> OnlineMrWebItemsDTO:
        if not value.terminal_monitor:
            raise ValueError("terminal_monitor 是 Online MR 原始采集契约的必选项")
        return value


class OnlineMrAgentWebOperationDTO(ApiModel):
    operation_id: str
    controller_task_id: str
    session_id: str | None = None
    site_id: str
    device_id: int | str | None = None
    device_name: str = ""
    mr_id: str = ""
    mr_name: str = ""
    executor: Literal["AGENT"] = "AGENT"
    agent_id: str = ""
    agent_profile_id: str = ""
    agent_task_id: str = ""
    remote_session_id: str = ""
    remote_package_id: str = ""
    state: str
    phase: str
    remote_status: str = ""
    task_status: str | None = None
    mapping_status: str
    started_at: str | None = None
    updated_at: str
    deadline_at: str | None = None
    duration_minutes: float | None = None
    consecutive_status_failures: int = 0
    package_status: str = "pending"
    download_status: str = "pending"
    import_status: str = "pending"
    data_integrity: str = "unknown"
    error_code: str = ""
    error_summary: str = ""


class OnlineMrAgentWebStatusDTO(ApiModel):
    agent_executor_enabled: bool
    site_id: str
    operations: list[OnlineMrAgentWebOperationDTO] = Field(default_factory=list)


__all__ = [name for name in globals() if name.startswith("OnlineMrAgent")]
