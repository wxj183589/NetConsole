from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from netconsole.models.api.common import ApiModel
from netconsole.models.api.task import TaskDTO
from netconsole.models.api.traffic import TrafficExecutionTargetRequest


class TcpPortTestStartRequest(ApiModel):
    execution_target: TrafficExecutionTargetRequest = Field(default_factory=TrafficExecutionTargetRequest)
    target: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    interval_ms: int = Field(default=1000, ge=1, le=60000)
    timeout_ms: int = Field(default=3000, ge=1, le=60000)
    count: int = Field(default=4, ge=1, le=1000000)


class ToolboxTextRequest(ApiModel):
    text: str = Field(min_length=1, max_length=200000)


class VlsmRequest(ApiModel):
    parent: str = Field(min_length=1, max_length=64)
    requests: str = Field(min_length=1, max_length=20000)


class SubnetSplitRequest(ApiModel):
    parent: str = Field(min_length=1, max_length=64)
    target_prefix: int = Field(ge=1, le=32)
    page: int = Field(default=1, ge=1, le=1000000)
    page_size: int = Field(default=50, ge=1, le=500)


class NetworkTaskStartRequest(ApiModel):
    kind: Literal["single_ping", "continuous_ping", "batch_ping", "subnet_ping", "tcp_ping"]
    target: str = Field(default="", max_length=255)
    targets: list[Annotated[str, Field(min_length=1, max_length=255)]] = Field(default_factory=list, max_length=4096)
    port: int = Field(default=443, ge=1, le=65535)
    interval_ms: int = Field(default=1000, ge=1, le=60000)
    timeout_ms: int = Field(default=1500, ge=1, le=60000)
    count: int = Field(default=4, ge=1, le=1000)
    packet_size: int = Field(default=32, ge=1, le=65500)
    concurrency: int = Field(default=100, ge=1, le=500)
    source_ip: str = Field(default="", max_length=128)


class NetworkExportRequest(ApiModel):
    format: Literal["csv", "xlsx"] = "xlsx"
    filename: str = Field(default="", max_length=100)


class WirelessScanStartRequest(ApiModel):
    adapter_name: str = Field(default="", max_length=256)
    adapter_guid: str = Field(default="", max_length=128)
    project_id: str = Field(default="", max_length=128)


class WirelessExportRequest(ApiModel):
    scan_id: str = Field(min_length=1, max_length=128)
    format: Literal["csv", "xlsx"] = "xlsx"
    filename: str = Field(default="", max_length=100)


class NetworkTaskResponse(ApiModel):
    task: TaskDTO


class NetworkTaskResultPageResponse(ApiModel):
    items: list[dict[str, object]] = Field(default_factory=list)
    offset: int = 0
    limit: int = 100
    total: int = 0


class NetworkToolArtifactResponse(ApiModel):
    artifact_id: str
    filename: str
    format: Literal["csv", "xlsx"]
    sha256: str
    size: int
    download_url: str


class WirelessProjectRequest(ApiModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)


__all__ = [
    "NetworkExportRequest",
    "NetworkTaskResponse",
    "NetworkTaskResultPageResponse",
    "NetworkTaskStartRequest",
    "NetworkToolArtifactResponse",
    "SubnetSplitRequest",
    "TcpPortTestStartRequest",
    "ToolboxTextRequest",
    "VlsmRequest",
    "WirelessExportRequest",
    "WirelessProjectRequest",
    "WirelessScanStartRequest",
]
