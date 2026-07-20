from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.maintenance.check_desktop_bootstrap import inspect_bootstrap, repair_bootstrap


def _site(root: Path, name: str) -> None:
    database = root / "data" / "sites" / name / "db" / "devices.db"
    database.parent.mkdir(parents=True, exist_ok=True)
    database.write_bytes(b"sqlite")


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def test_inspection_rejects_codex_temp_root(tmp_path: Path) -> None:
    temporary = tmp_path / "temp"
    root = temporary / "NetConsole-Codex-bad" / "data"
    _site(root, "demo")
    bootstrap = tmp_path / "user-data" / "bootstrap.json"
    _write(bootstrap, {"schema_version": 1, "data_root": str(root), "active_site_id": "demo"})

    result = inspect_bootstrap(bootstrap, temp_root=temporary)

    assert not result.valid
    assert result.data_root_kind == "temporary"


def test_repair_uses_app_current_site_and_preserves_original_bytes(tmp_path: Path) -> None:
    temporary = tmp_path / "temp"
    persistent = tmp_path / "persistent"
    _site(persistent, "line-a")
    _site(persistent, "line-b")
    _write(persistent / "data" / "config" / "app.json", {"current_site": "line-b"})
    bootstrap = tmp_path / "user-data" / "bootstrap.json"
    original = json.dumps({"schema_version": 1, "data_root": str(temporary / "NetConsole-Codex-gone"), "active_site_id": "demo"}).encode()
    bootstrap.parent.mkdir(parents=True)
    bootstrap.write_bytes(original)
    inspection = inspect_bootstrap(bootstrap, temp_root=temporary)

    target, active, backup = repair_bootstrap(inspection, candidate_roots=[persistent])

    assert target == persistent.resolve()
    assert active == "line-b"
    assert backup is not None and backup.read_bytes() == original
    assert json.loads(bootstrap.read_text(encoding="utf-8"))["active_site_id"] == "line-b"


def test_repair_refuses_ambiguous_sites_without_explicit_site(tmp_path: Path) -> None:
    persistent = tmp_path / "persistent"
    _site(persistent, "line-a")
    _site(persistent, "line-b")
    bootstrap = tmp_path / "bootstrap.json"
    _write(bootstrap, {"data_root": str(tmp_path / "missing"), "active_site_id": "missing"})
    inspection = inspect_bootstrap(bootstrap, temp_root=tmp_path / "temp")

    with pytest.raises(RuntimeError, match="--site-id"):
        repair_bootstrap(inspection, candidate_roots=[persistent])


def test_dry_run_does_not_change_bootstrap(tmp_path: Path) -> None:
    persistent = tmp_path / "persistent"
    _site(persistent, "only")
    bootstrap = tmp_path / "bootstrap.json"
    _write(bootstrap, {"data_root": str(tmp_path / "missing"), "active_site_id": "missing"})
    original = bootstrap.read_bytes()

    _target, active, backup = repair_bootstrap(
        inspect_bootstrap(bootstrap, temp_root=tmp_path / "temp"),
        candidate_roots=[persistent],
        dry_run=True,
    )

    assert active == "only"
    assert backup is not None and not backup.exists()
    assert bootstrap.read_bytes() == original


def test_single_legacy_directory_resolves_to_stable_registry_id(tmp_path: Path) -> None:
    persistent = tmp_path / "persistent"
    _site(persistent, "中文局点")
    _write(
        persistent / "data" / "config" / "site_registry.json",
        {
            "sites": [
                {
                    "site_id": "legacy-stable",
                    "display_name": "中文局点",
                    "relative_path": "data/sites/中文局点",
                }
            ]
        },
    )
    bootstrap = tmp_path / "bootstrap.json"
    _write(bootstrap, {"data_root": str(tmp_path / "missing")})

    _target, active, _backup = repair_bootstrap(
        inspect_bootstrap(bootstrap, temp_root=tmp_path / "temp"),
        candidate_roots=[persistent],
        dry_run=True,
    )

    assert active == "legacy-stable"
