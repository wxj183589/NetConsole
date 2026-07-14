from __future__ import annotations

from pydantic import Field

from netconsole.models.api.common import ApiModel
from netconsole.models.api.traffic import TrafficExecutionTargetRequest


class TcpPortTestStartRequest(ApiModel):
    execution_target: TrafficExecutionTargetRequest = Field(default_factory=TrafficExecutionTargetRequest)
    target: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    interval_ms: int = Field(default=1000, ge=1, le=60000)
    timeout_ms: int = Field(default=3000, ge=1, le=60000)
    count: int = Field(default=4, ge=1, le=1000000)


__all__ = ["TcpPortTestStartRequest"]
