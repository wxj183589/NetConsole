from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import scripts.maintenance.cleanup_retired_tasks as cleanup_module
import netconsole.services.production_database_maintenance as maintenance_module
from netconsole.core.paths import PathResolver
from netconsole.services.production_database_maintenance import (
    PRODUCTION_SITE_ALLOWLIST,
    ProductionMaintenanceError,
)


def _write_production_registry(root: Path, *, include_fake: bool = False) -> Path:
    sites = [
        {
            "site_id": site_id,
            "display_name": display_name,
            "relative_path": f"sites/{site_id}",
        }
        for site_id, display_name in PRODUCTION_SITE_ALLOWLIST.items()
    ]
    if include_fake:
        sites.append(
            {
                "site_id": "fake-site",
                "display_name": "Fake Site",
                "relative_path": "sites/fake-site",
            }
        )
    config = root / "config"
    config.mkdir(parents=True, exist_ok=True)
    registry = config / "site_registry.json"
    registry.write_text(
        json.dumps({"schema_version": 2, "sites": sites}, ensure_ascii=False),
        encoding="utf-8",
    )
    return registry


def _production_fixture(tmp_path: Path, *, include_fake: bool = False) -> tuple[PathResolver, Path]:
    root = tmp_path / "production-fixture"
    _write_production_registry(root, include_fake=include_fake)
    for site_id in PRODUCTION_SITE_ALLOWLIST:
        (root / "sites" / site_id / "db").mkdir(parents=True, exist_ok=True)
    fake_database = root / "sites" / "fake-site" / "db" / "tasks.db"
    if include_fake:
        fake_database.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(fake_database) as connection:
            connection.execute("CREATE TABLE sentinel(value TEXT NOT NULL)")
            connection.execute("INSERT INTO sentinel(value) VALUES ('keep')")
            connection.commit()
    return PathResolver(app_root=tmp_path, data_root=root), fake_database


def _production_main_args(paths: PathResolver, *extra: str) -> list[str]:
    return [
        "--data-root",
        str(paths.data_root),
        "--site",
        "sxl1",
        *extra,
    ]


def test_all_allowlisted_production_sites_resolve_from_canonical_registry(
    tmp_path: Path,
) -> None:
    paths, _fake_database = _production_fixture(tmp_path)

    targets = cleanup_module._production_site_databases(paths, None, True)

    assert [site_id for site_id, _database in targets] == sorted(PRODUCTION_SITE_ALLOWLIST)


def test_unlisted_production_apply_rejects_before_database_side_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, fake_database = _production_fixture(tmp_path, include_fake=True)
    monkeypatch.setattr(cleanup_module, "_is_production_scope", lambda _paths: True)
    before_bytes = fake_database.read_bytes()
    before_rows = 1

    with pytest.raises(SystemExit, match="PRODUCTION_SITE_NOT_ALLOWLISTED"):
        cleanup_module.main(
            [
                "--data-root",
                str(paths.data_root),
                "--site",
                "fake-site",
                "--allow-production",
                "--apply",
            ]
        )

    assert fake_database.read_bytes() == before_bytes
    with sqlite3.connect(fake_database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM sentinel").fetchone()[0] == before_rows


def test_production_apply_without_allow_production_still_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, _fake_database = _production_fixture(tmp_path)
    monkeypatch.setattr(cleanup_module, "_is_production_scope", lambda _paths: True)

    with pytest.raises(SystemExit, match="allow-production"):
        cleanup_module.main(_production_main_args(paths, "--apply"))


@pytest.mark.parametrize(
    "site_ref",
    [
        "../xxx",
        r"..\xxx",
        r"C:\outside\site",
        r"\\server\share\site",
        "%2e%2e%5cxxx",
        "valid-site/../other",
        "宁波地铁10号线",
    ],
)
def test_production_site_path_or_alias_inputs_are_rejected_before_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    site_ref: str,
) -> None:
    paths, _fake_database = _production_fixture(tmp_path)
    monkeypatch.setattr(cleanup_module, "_is_production_scope", lambda _paths: True)

    with pytest.raises(SystemExit, match="PRODUCTION_SITE_NOT_ALLOWLISTED"):
        cleanup_module.main(
            [
                "--data-root",
                str(paths.data_root),
                "--site",
                site_ref,
                "--allow-production",
                "--apply",
            ]
        )


def test_production_site_id_normalization_uses_canonical_registry_id(
    tmp_path: Path,
) -> None:
    paths, _fake_database = _production_fixture(tmp_path)

    targets = cleanup_module._production_site_databases(paths, "  SXL1  ", False)

    assert targets[0][0] == "sxl1"
    assert targets[0][1] == paths.data_root / "sites" / "sxl1" / "db" / "tasks.db"


def test_production_allowlist_provider_failure_is_fail_closed(
    tmp_path: Path,
) -> None:
    paths, _fake_database = _production_fixture(tmp_path)
    (paths.config_dir / "site_registry.json").write_text("{broken", encoding="utf-8")

    with pytest.raises(ProductionMaintenanceError, match="PRODUCTION_SITE_REGISTRY_UNAVAILABLE"):
        cleanup_module._production_site_databases(paths, "sxl1", False)


def test_development_site_preview_resolution_remains_unchanged(tmp_path: Path) -> None:
    data_root = tmp_path / "development"
    legacy_directory_name = "宁波地铁12号线"

    targets = cleanup_module._site_databases(data_root, legacy_directory_name, False)

    assert targets == [
        (
            legacy_directory_name,
            data_root / "sites" / legacy_directory_name / "db" / "tasks.db",
        )
    ]


def test_production_sites_link_or_reparse_guard_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, _fake_database = _production_fixture(tmp_path)
    monkeypatch.setattr(
        maintenance_module,
        "_is_link_or_reparse_point",
        lambda path: path == paths.sites_dir,
    )

    with pytest.raises(
        ProductionMaintenanceError,
        match="PRODUCTION_SITE_REGISTRY_IDENTITY_MISMATCH",
    ):
        cleanup_module._production_site_databases(paths, "sxl1", False)
