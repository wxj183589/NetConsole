from __future__ import annotations

import json
from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.core.runtime_environment import write_data_environment
from netconsole.core.runtime_mode import DataEnvironmentInfo, DataEnvironmentMode
from netconsole.services.production_rollback_authority import (
    BASE_DATA_ROLLBACK_AUTHORIZED,
    ProductionRollbackAuthorityError,
    require_rollback_authority,
)
from netconsole.services.production_database_maintenance import PRODUCTION_SITE_ALLOWLIST


def _production_paths(tmp_path: Path) -> PathResolver:
    root = tmp_path / "production"
    write_data_environment(
        root,
        DataEnvironmentInfo(
            DataEnvironmentMode.PRODUCTION,
            created_from="rollback-authority-test",
            readonly_warning=True,
        ),
    )
    site_root = root / "sites" / "relocated-sxl1"
    site_root.mkdir(parents=True)
    (root / "config").mkdir(parents=True)
    (root / "config" / "site_registry.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "sites": [
                    {
                        "site_id": "sxl1",
                        "display_name": PRODUCTION_SITE_ALLOWLIST["sxl1"],
                        "relative_path": "sites/relocated-sxl1",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return PathResolver(data_root=root)


def test_production_rollback_requires_operator_gate_and_operation_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _production_paths(tmp_path)
    monkeypatch.delenv("NETCONSOLE_ALLOW_PRODUCTION_WRITE", raising=False)
    with pytest.raises(ProductionRollbackAuthorityError, match="ROLLBACK_PRODUCTION_WRITE_NOT_ALLOWED"):
        require_rollback_authority(
            paths,
            site_ref="sxl1",
            operation="BASE_DATA_ROLLBACK",
            authorization_token=BASE_DATA_ROLLBACK_AUTHORIZED,
        )

    monkeypatch.setenv("NETCONSOLE_ALLOW_PRODUCTION_WRITE", "1")
    with pytest.raises(ProductionRollbackAuthorityError, match="ROLLBACK_OPERATION_AUTHORIZATION_REQUIRED"):
        require_rollback_authority(
            paths,
            site_ref="sxl1",
            operation="BASE_DATA_ROLLBACK",
            authorization_token="AC_EXTENSION_ROLLBACK_AUTHORIZED",
        )

    scope = require_rollback_authority(
        paths,
        site_ref="relocated-sxl1",
        operation="BASE_DATA_ROLLBACK",
        authorization_token=BASE_DATA_ROLLBACK_AUTHORIZED,
        audit_site_id="relocated-sxl1",
    )
    assert scope.canonical_site_id == "sxl1"
    assert scope.directory_name == "relocated-sxl1"
