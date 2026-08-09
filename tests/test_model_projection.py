from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from netconsole.core.database import Database
from netconsole.core.model_projection import project_row_for_model


class _StrictRowModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: int
    name: str


def test_project_row_for_model_supports_mapping_and_sqlite_row(tmp_path) -> None:
    mapping = {"item_id": 7, "name": "known", "future_column": "ignored"}
    connection = Database(tmp_path / "projection.sqlite").connect()
    try:
        connection.execute(
            "CREATE TABLE sample (item_id INTEGER, name TEXT, future_column TEXT)"
        )
        connection.execute("INSERT INTO sample VALUES (7, 'known', 'ignored')")
        row = connection.execute("SELECT * FROM sample").fetchone()
        assert row is not None

        assert _StrictRowModel.model_validate(
            project_row_for_model(mapping, _StrictRowModel)
        ).name == "known"
        assert _StrictRowModel.model_validate(
            project_row_for_model(row, _StrictRowModel)
        ).name == "known"
    finally:
        connection.close()


def test_project_row_for_model_preserves_required_and_type_validation() -> None:
    with pytest.raises(ValidationError, match="item_id"):
        _StrictRowModel.model_validate(
            project_row_for_model({"name": "missing id", "future": 1}, _StrictRowModel)
        )
    with pytest.raises(ValidationError, match="item_id"):
        _StrictRowModel.model_validate(
            project_row_for_model(
                {"item_id": "not-an-integer", "name": "bad type", "future": 1},
                _StrictRowModel,
            )
        )
