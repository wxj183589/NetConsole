from __future__ import annotations

from fastapi import APIRouter, Request

from netconsole.backend.api.edition_access import ensure_edition_gate
from netconsole.core.feature_registry import list_features
from netconsole.models.api.features import RendererFeatureStateDTO, RendererFeatureStateListDTO


router = APIRouter(prefix="/features", tags=["features"])


@router.get("", response_model=RendererFeatureStateListDTO)
def renderer_feature_states(request: Request) -> RendererFeatureStateListDTO:
    gate = ensure_edition_gate(request.app)
    return RendererFeatureStateListDTO(
        items=[
            RendererFeatureStateDTO(
                feature_id=item.feature_id,
                visible=gate.is_visible(item.feature_id),
                enabled=gate.is_enabled(item.feature_id),
            )
            for item in list_features()
            if not item.internal_only or gate.is_feature_configuration_available()
        ]
    )


__all__ = ["router"]
