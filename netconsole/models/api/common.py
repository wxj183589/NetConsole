from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApiResponse(ApiModel):
    ok: bool = True
    data: Any = None


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
