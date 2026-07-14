from __future__ import annotations

from pydantic import Field

from netconsole.models.api.common import ApiModel


class WebFeatureStateDTO(ApiModel):
    feature_id: str
    visible: bool
    enabled: bool


class WebFeatureStateListDTO(ApiModel):
    items: list[WebFeatureStateDTO] = Field(default_factory=list)


__all__ = ["WebFeatureStateDTO", "WebFeatureStateListDTO"]
