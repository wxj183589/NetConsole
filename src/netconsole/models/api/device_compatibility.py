from __future__ import annotations

from pydantic import BaseModel, Field


class DeviceCompatibilityProfileDTO(BaseModel):
    profile_id: str
    vendor: str
    device_role: str
    platform: str
    validation_level: str
    capabilities: dict[str, str] = Field(default_factory=dict)


class DeviceCompatibilitySummaryDTO(BaseModel):
    generated_at: str
    profile_count: int
    platforms: list[str]
    roles: list[str]
    validation_levels: list[str]
    statement: str
    disclaimer: str
    profiles: list[DeviceCompatibilityProfileDTO]
