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
