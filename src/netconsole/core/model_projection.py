from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from pydantic import BaseModel


ModelT = TypeVar("ModelT", bound=BaseModel)


def project_row_for_model(
    row: Mapping[str, Any] | object,
    model: type[ModelT],
) -> dict[str, Any]:
    """Project SQLite/Mapping rows without weakening strict model validation."""

    if isinstance(row, Mapping):
        payload = dict(row)
    else:
        keys = getattr(row, "keys", None)
        if not callable(keys) or not hasattr(row, "__getitem__"):
            raise TypeError("row must be a Mapping or sqlite3.Row-compatible object")
        payload = {str(key): row[key] for key in keys()}
    return {
        field: payload[field]
        for field in model.model_fields
        if field in payload
    }
