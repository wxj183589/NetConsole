from __future__ import annotations

from fastapi import APIRouter, Request

from netconsole.core.feature_registry import list_features
from netconsole.models.api.features import WebFeatureStateDTO, WebFeatureStateListDTO


router = APIRouter(prefix="/features", tags=["features"])


@router.get("", response_model=WebFeatureStateListDTO)
def web_feature_states(request: Request) -> WebFeatureStateListDTO:
    gate = request.app.state.feature_gate
    return WebFeatureStateListDTO(
        items=[
            WebFeatureStateDTO(
                feature_id=item.feature_id,
                visible=gate.is_visible(item.feature_id),
                enabled=gate.is_enabled(item.feature_id),
            )
            for item in list_features()
            if item.feature_id.startswith("web.") or item.feature_id == "network_tools.traffic"
        ]
    )


__all__ = ["router"]
