from __future__ import annotations

from pydantic import Field

from netconsole.models.api.common import ApiModel


class RendererFeatureStateDTO(ApiModel):
    feature_id: str
    visible: bool
    enabled: bool


class RendererFeatureStateListDTO(ApiModel):
    items: list[RendererFeatureStateDTO] = Field(default_factory=list)


__all__ = ["RendererFeatureStateDTO", "RendererFeatureStateListDTO"]
