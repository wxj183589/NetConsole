from __future__ import annotations

from collections.abc import Callable

from fastapi import HTTPException, status
from starlette.requests import HTTPConnection

from netconsole.core.feature_flags import FeatureGate


def require_feature(feature_id: str) -> Callable[[HTTPConnection], None]:
    def dependency(connection: HTTPConnection) -> None:
        gate = getattr(connection.app.state, "feature_gate", None)
        if not isinstance(gate, FeatureGate) or not gate.is_enabled(feature_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="功能未启用")

    return dependency


__all__ = ["require_feature"]
