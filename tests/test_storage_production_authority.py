from __future__ import annotations

import json
from pathlib import Path

import pytest

from netconsole.core.runtime_environment import write_data_environment
from netconsole.core.runtime_mode import DataEnvironmentInfo, DataEnvironmentMode
from netconsole.services.storage_production_authority import (
    DATA_ROOT_MIGRATION_AUTHORIZED,
    StorageAuthorityError,
    assert_safe_external_target,
    require_storage_operation,
    resolve_storage_root_authority,
)


def _production_root(root: Path) -> Path:
    write_data_environment(
        root,
        DataEnvironmentInfo(DataEnvironmentMode.PRODUCTION, readonly_warning=True),
    )
    config = root / "config"
    sites = root / "sites" / "line-1"
    config.mkdir(parents=True, exist_ok=True)
    sites.mkdir(parents=True, exist_ok=True)
    (config / "site_registry.json").write_text(
        json.dumps(
            {"schema_version": 1, "sites": [{"site_id": "line-1", "relative_path": "sites/line-1"}]}
        ),
        encoding="utf-8",
    )
    (config / "storage-manifest.json").write_text(
        json.dumps(
            {
                "format_version": 1,
                "data_root": str(root.resolve()),
                "installation_id": "installation-test",
            }
        ),
        encoding="utf-8",
    )
    return root


def test_relocated_production_root_requires_operation_specific_authority(tmp_path: Path) -> None:
    root = _production_root(tmp_path / "relocated-root")
    authority = resolve_storage_root_authority(root)

    assert authority.is_production
    assert authority.canonical_site_ids == ("line-1",)
    with pytest.raises(StorageAuthorityError, match="PRODUCTION_OPERATOR_INTENT_REQUIRED"):
        require_storage_operation(authority, "DATA_ROOT_MIGRATION")
    with pytest.raises(StorageAuthorityError, match="OPERATION_NOT_AUTHORIZED"):
        require_storage_operation(
            authority,
            "DATA_ROOT_MIGRATION",
            allow_production_write=True,
            authorization_token="WRONG",
        )
    require_storage_operation(
        authority,
        "DATA_ROOT_MIGRATION",
        allow_production_write=True,
        authorization_token=DATA_ROOT_MIGRATION_AUTHORIZED,
    )


def test_external_target_rejects_overlap_and_active_root(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    with pytest.raises(StorageAuthorityError, match="SOURCE_TARGET_OVERLAP"):
        assert_safe_external_target(source, source / "nested")

    active = tmp_path / "active"
    (active / "config").mkdir(parents=True)
    (active / "config" / "storage-manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(StorageAuthorityError, match="TARGET_ACTIVE_NETCONSOLE_ROOT"):
        assert_safe_external_target(source, active)
