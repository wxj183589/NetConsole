from __future__ import annotations

import hashlib
from types import SimpleNamespace
from pathlib import Path

import pytest

from netconsole.services.mesh_parsed_rebuild_service import MeshParsedRebuildService
from netconsole.services.database_upgrade.coordinator import DatabaseUpgradeCoordinator
from netconsole.services.file_contract import ImportValidationError
from tests.support.mesh_analysis_test_support import create_mesh_analysis_fixture


def _fingerprint(path: Path) -> tuple[int, str]:
    return path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest()


def test_failed_mesh_rebuild_restores_index_parsed_and_raw_files(tmp_path: Path) -> None:
    paths, _session_id, detail, raw, _report = create_mesh_analysis_fixture(tmp_path)
    index = paths.mesh_mr_db_path("demo", "列车01-MR-CT")
    before = {"index": _fingerprint(index), "detail": _fingerprint(detail), "raw": _fingerprint(raw)}

    with pytest.raises(ImportValidationError, match="未识别到 MESH 记录"):
        MeshParsedRebuildService(paths).rebuild("demo", "12345678-1234-1234-1234-123456789abc")

    assert _fingerprint(index) == before["index"]
    assert _fingerprint(detail) == before["detail"]
    assert _fingerprint(raw) == before["raw"]
    assert not list(index.parent.glob("*.schema_archive_*"))


def test_cancelled_mesh_rebuild_does_not_touch_derived_files(tmp_path: Path) -> None:
    paths, _session_id, detail, raw, _report = create_mesh_analysis_fixture(tmp_path)
    index = paths.mesh_mr_db_path("demo", "列车01-MR-CT")
    before = (_fingerprint(index), _fingerprint(detail), _fingerprint(raw))

    with pytest.raises(RuntimeError, match="已取消"):
        MeshParsedRebuildService(paths).rebuild(
            "demo",
            "12345678-1234-1234-1234-123456789abc",
            should_cancel=lambda: True,
        )

    assert (_fingerprint(index), _fingerprint(detail), _fingerprint(raw)) == before


@pytest.mark.parametrize(
    ("allow_legacy_startup_recovery", "expected"),
    [(False, None), (True, "LEGACY_MESH_REBUILD_ADAPTER")],
)
def test_legacy_mesh_recovery_adapter_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    allow_legacy_startup_recovery: bool,
    expected: str | None,
) -> None:
    paths, _session_id, _detail, _raw, _report = create_mesh_analysis_fixture(tmp_path)
    metadata: dict[str, object] = {}

    def capture_descriptor(_self, descriptor, **_kwargs):
        metadata.update(descriptor.metadata)
        return SimpleNamespace(
            diagnostics={"build": {}},
            backup_id="",
            backup_path="",
            backup_validation={},
            checkpoint_status="",
            new_validation={},
            rollback_available=False,
            rollback_performed=False,
            retained_backup_count=0,
        )

    monkeypatch.setattr(DatabaseUpgradeCoordinator, "upgrade", capture_descriptor)

    MeshParsedRebuildService(paths).rebuild(
        "demo",
        "12345678-1234-1234-1234-123456789abc",
        allow_legacy_startup_recovery=allow_legacy_startup_recovery,
    )

    assert metadata.get("startup_recovery_legacy_adapter") == expected
