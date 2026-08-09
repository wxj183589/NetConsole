from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.models.online_mr_models import OnlineMrConnectionConfig
from netconsole.repositories.online_mr_diagnosis_repository import OnlineMrDiagnosisRepository
from netconsole.services.mesh_storage_service import MeshStorageService
from netconsole.services.online_mr.parsed_database_contract import (
    ONLINE_MR_REQUIRED_CAPABILITIES,
    PARSER_SCHEMA_VERSION,
    inspect_parsed_database,
)
from netconsole.services.online_mr.parsed_database_upgrade import (
    OnlineMrParsedDatabaseUpgradeError,
    OnlineMrParsedDatabaseUpgradeService,
    OnlineMrRawDataMissingError,
    UPGRADE_FAILED,
    UPGRADE_RAW_DATA_MISSING,
)
from netconsole.services.online_mr_session_store import OnlineMrSessionStore
from netconsole.services.rail_transit.online_mr_diagnosis_parser import OnlineMrDiagnosisParser


MESH_LINE = "[1] Active 30f5-277a-5a2f 2025/12/03 10:12:30 0d 00h 00m 03s 1 36/43 2%/4% 45%/47% 3/1 15/27 60/72060 88/105 0/5000 2/297 314/0 0/93 0/0 0/0 0/0"


def _session(tmp_path: Path, *, with_raw: bool = True):
    paths = PathResolver(tmp_path)
    profile = MeshStorageService("demo", paths).create_mr_profile("MR-Upgrade")
    config = OnlineMrConnectionConfig(
        site="demo",
        mr_id=profile.mr_id,
        mr_name=profile.display_name,
        safe_mr_name=profile.safe_folder_name,
        device_id=1,
        device_name="MR-Upgrade",
        host="192.0.2.20",
        username="admin",
        password="secret",
    )
    session = OnlineMrSessionStore(paths).create_session(config)
    if with_raw:
        (session.session_dir / "raw" / "mesh_link_raw.log").write_text(
            f"2026-08-09 23:12:31 >>> display clock ; display wlan mesh-link\n{MESH_LINE}\n",
            encoding="utf-8",
        )
    return session


def _legacy_database(path: Path, marker: str = "legacy") -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE legacy_keep(value TEXT NOT NULL)")
        connection.execute("INSERT INTO legacy_keep(value) VALUES (?)", (marker,))
        connection.commit()
    return path.read_bytes()


def test_capability_contract_requires_declared_metadata_and_real_tables(tmp_path: Path) -> None:
    path = tmp_path / "online.sqlite"
    repository = OnlineMrDiagnosisRepository(path)
    repository.initialize()

    current = inspect_parsed_database(path)
    assert current.schema_version == PARSER_SCHEMA_VERSION
    assert current.missing_capabilities == frozenset()
    assert current.current is True

    with closing(sqlite3.connect(path)) as connection:
        connection.execute("DROP TABLE channel_busy_records")
        connection.commit()

    incomplete = inspect_parsed_database(path)
    assert incomplete.current is False
    assert "channel_busy" in incomplete.missing_capabilities


def test_upgrade_rebuilds_candidate_then_atomically_publishes_and_retains_one_rollback(tmp_path: Path) -> None:
    session = _session(tmp_path)
    upgrade = OnlineMrParsedDatabaseUpgradeService(session.session_dir)
    legacy_bytes = _legacy_database(upgrade.database_path)

    result = upgrade.rebuild(force=False)

    inspected = inspect_parsed_database(upgrade.database_path)
    assert inspected.current is True
    assert inspected.missing_capabilities == frozenset()
    assert result["schema_version"] == PARSER_SCHEMA_VERSION
    assert upgrade.candidate_path.exists() is False
    assert list(upgrade.parsed_dir.rglob("*.pending*")) == []
    assert upgrade.rollback_path.read_bytes() == legacy_bytes
    with closing(sqlite3.connect(upgrade.rollback_path)) as connection:
        assert connection.execute("SELECT value FROM legacy_keep").fetchone()[0] == "legacy"


def test_upgrade_accepts_historical_session_meta_extension_fields(tmp_path: Path) -> None:
    session = _session(tmp_path)
    meta_path = session.session_dir / "session_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["items"] = {"mesh_link": True, "channel_busy": True}
    meta["collectors"] = {"mesh_link": {"status": "stopped"}}
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    upgrade = OnlineMrParsedDatabaseUpgradeService(session.session_dir)
    _legacy_database(upgrade.database_path)

    result = upgrade.rebuild(force=False)

    assert result["upgrade_status"] == "CURRENT"
    assert inspect_parsed_database(upgrade.database_path).current is True


def test_current_database_is_a_noop_across_repeated_ensure_calls(tmp_path: Path) -> None:
    session = _session(tmp_path)
    upgrade = OnlineMrParsedDatabaseUpgradeService(session.session_dir)
    upgrade.rebuild(force=False)
    original = upgrade.database_revision()

    results = [upgrade.rebuild(force=False) for _ in range(10)]

    assert all(result["cache_used"] is True for result in results)
    assert upgrade.database_revision() == original
    assert upgrade.candidate_path.exists() is False


def test_failed_candidate_validation_keeps_legacy_database_readable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session(tmp_path)
    upgrade = OnlineMrParsedDatabaseUpgradeService(session.session_dir)
    legacy_bytes = _legacy_database(upgrade.database_path, "keep-after-failure")

    def reject(*_args, **_kwargs):
        raise OnlineMrParsedDatabaseUpgradeError("capability post-validation failed")

    monkeypatch.setattr(upgrade, "_validate_candidate", reject)

    with pytest.raises(OnlineMrParsedDatabaseUpgradeError):
        upgrade.rebuild(force=False)

    assert upgrade.database_path.read_bytes() == legacy_bytes
    with closing(sqlite3.connect(upgrade.database_path)) as connection:
        assert connection.execute("SELECT value FROM legacy_keep").fetchone()[0] == "keep-after-failure"
    assert upgrade.candidate_path.exists() is False
    assert upgrade.read_state()["status"] == UPGRADE_FAILED


def test_missing_raw_data_is_persisted_and_suppresses_same_input_retry(tmp_path: Path) -> None:
    session = _session(tmp_path, with_raw=False)
    upgrade = OnlineMrParsedDatabaseUpgradeService(session.session_dir)
    _legacy_database(upgrade.database_path)

    with pytest.raises(OnlineMrRawDataMissingError):
        upgrade.rebuild(force=False)

    assert upgrade.read_state()["status"] == UPGRADE_RAW_DATA_MISSING
    assert upgrade.retry_suppressed() is True
    assert inspect_parsed_database(upgrade.database_path).exists is True


@pytest.mark.parametrize(
    "filename",
    ["Fping.txt", "fping.txt", "iperf3.json", "iperf_client_raw.json"],
)
def test_historical_raw_source_names_are_eligible_for_automatic_upgrade(
    tmp_path: Path,
    filename: str,
) -> None:
    session = _session(tmp_path, with_raw=False)
    upgrade = OnlineMrParsedDatabaseUpgradeService(session.session_dir)
    (upgrade.raw_dir / filename).write_text("historical raw data\n", encoding="utf-8")

    assert upgrade.raw_sources_available() == (True, "")


def test_completed_upgrading_database_is_recovered_after_interruption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session(tmp_path)
    upgrade = OnlineMrParsedDatabaseUpgradeService(session.session_dir)
    _legacy_database(upgrade.database_path)
    OnlineMrDiagnosisParser(session.session_dir, db_path=upgrade.candidate_path).parse(force=True)

    def unexpected_parse(*_args, **_kwargs):
        raise AssertionError("valid residual candidate must be recovered without reparsing")

    monkeypatch.setattr(OnlineMrDiagnosisParser, "parse", unexpected_parse)

    result = upgrade.rebuild(force=False)

    assert result["cache_used"] is True
    assert inspect_parsed_database(upgrade.database_path).current is True
    assert upgrade.candidate_path.exists() is False
    assert set(result["capabilities"]) == set(ONLINE_MR_REQUIRED_CAPABILITIES)
