from __future__ import annotations

from pathlib import Path

import pytest

from rail_transit_base_data_fixture import build_rail_transit_base_data_fixture, mark_base_data_copy
from netconsole.services.rail_transit.base_data_write_guard import BaseDataWriteGuard, BaseDataWriteGuardError


def test_write_guard_defaults_to_disabled_and_rejects_real_site(tmp_path: Path) -> None:
    paths, _database = build_rail_transit_base_data_fixture(tmp_path)
    disabled = BaseDataWriteGuard(paths, feature_enabled=True)
    with pytest.raises(BaseDataWriteGuardError) as error:
        disabled.authorize_apply("demo", explicit_confirmation=True)
    assert error.value.code == "BASE_DATA_WRITE_DISABLED"

    real = BaseDataWriteGuard(
        paths,
        feature_enabled=True,
        write_enabled=True,
        copy_write_enabled=True,
        real_write_enabled=False,
    )
    with pytest.raises(BaseDataWriteGuardError) as error:
        real.authorize_apply("demo", explicit_confirmation=True)
    assert error.value.code == "BASE_DATA_REAL_WRITE_NOT_AUTHORIZED"


def test_copy_scope_requires_marker_double_switch_and_confirmation(tmp_path: Path) -> None:
    paths, _database = build_rail_transit_base_data_fixture(tmp_path)
    mark_base_data_copy(paths)
    missing_switch = BaseDataWriteGuard(paths, feature_enabled=True, write_enabled=True)
    with pytest.raises(BaseDataWriteGuardError) as error:
        missing_switch.authorize_apply("demo", explicit_confirmation=True)
    assert error.value.code == "BASE_DATA_COPY_WRITE_NOT_AUTHORIZED"

    allowed = BaseDataWriteGuard(
        paths,
        feature_enabled=True,
        write_enabled=True,
        copy_write_enabled=True,
    )
    with pytest.raises(BaseDataWriteGuardError) as error:
        allowed.authorize_apply("demo", explicit_confirmation=False)
    assert error.value.code == "BASE_DATA_IMPORT_CONFLICT"
    assert allowed.authorize_apply("demo", explicit_confirmation=True).copy_write_authorized is True
