from __future__ import annotations

from pathlib import Path

import pytest

from netconsole.core.database import Database
from netconsole.services.ap_identity import ApIdentityQueryService
from scripts.build.smoke_production_ap_identity_startup import (
    DATABASE_RELATIVE_PATH,
    prepare_fixture,
    verify_fixture,
)


@pytest.mark.parametrize("scenario", ("missing", "stale"))
def test_production_ap_identity_fixture_prepares_and_verifies_after_safe_rebuild(
    tmp_path: Path,
    scenario: str,
) -> None:
    fixture_root = tmp_path / scenario
    prepared = prepare_fixture(fixture_root, scenario)

    assert prepared["scenario"] == scenario
    assert prepared["state"] == scenario

    database = Database(fixture_root / DATABASE_RELATIVE_PATH)
    assert ApIdentityQueryService(database).ensure_index(
        "backend_startup",
        automatic_safe_only=True,
    ) is not None

    verified = verify_fixture(fixture_root)
    assert verified["status"] == "ready"
    assert verified["source_rows"] > 0
