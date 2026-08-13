from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


T = TypeVar("T")


class ApiResponse(ApiModel, Generic[T]):
    ok: bool = True
    data: T


class ErrorDetail(ApiModel):
    code: str = "internal_error"
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(ApiModel):
    ok: bool = False
    error: ErrorDetail


class HealthResponse(ApiModel):
    status: str = "ok"
    version: str
    build_id: str
    data_root: str
    active_site_id: str
    storage_schema_version: int
    runtime_services_status: str = "ready"
    runtime_services_ready: bool = True
    runtime_services_error: str = ""
    performance_mode: str = "standard"
    unattended_status: str = "disabled"
    unattended_ready: bool = False
    unattended_error: str = ""
    history_status: str = "idle"
    history_pending: int = 0
    history_error: str = ""
    history_oldest_pending_age_seconds: int = 0
    history_pressure: str = "normal"
    history_last_drain_elapsed_ms: int = 0
    history_last_drain_written: int = 0
    history_budget_overrun: bool = False
