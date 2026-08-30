from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from netconsole.application.rail_transit.web_application_service import (
    RailTransitWebApplicationService,
)
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.backend.api.trackside_ap_business_router import _raise_snapshot_error
from netconsole.models.ap_identity_index import ApIdentityBatchResult, ApIdentityMatch
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.repositories.history_store import HistoryStore
from netconsole.services.job_center.task_application_service import TaskApplicationService
from netconsole.services.rail_transit.effective_trackside_ap_scope import (
    TracksideApScopeContext,
)
from netconsole.services.rail_transit.trackside_ap_business_snapshot import (
    TracksideApBusinessSnapshotError,
    content_sha256,
    cleanup_export_snapshot,
    read_export_snapshot,
    read_trackside_ap_source_revisions,
    write_export_snapshot,
)
from netconsole.services.rail_transit.trackside_ap_business_query_service import (
    TracksideApBusinessQueryService,
)
from netconsole.services import trackside_ap_export_service as export_service
from netconsole.services.trackside_ap_export_service import (
    TracksideApBusinessLoadResult,
    build_trackside_ap_business_export_snapshot,
    export_trackside_ap_business_from_snapshot,
    load_trackside_ap_business_snapshot,
    select_trackside_ap_business_rows,
)
from tests.support.job_process_test_support import FakeExportProcessAdapter, FakeLocalProcessAdapter


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "site.db")
    database.initialize()
    return database


def _empty_export_payload() -> dict[str, object]:
    empty_rows_sha256 = content_sha256([])
    return {
        "snapshot_id": "snapshot-1",
        "site_id": "demo",
        "business_revision": "b" * 64,
        "export_revision": "e" * 64,
        "identity_revision": 7,
        "created_at": "2026-08-06T01:00:00+08:00",
        "content_sha256": empty_rows_sha256,
        "export_content_sha256": empty_rows_sha256,
        "row_count": 0,
        "abnormal_count": 0,
        "unresolved_count": 0,
        "ambiguous_count": 0,
        "identity_distinct_count": 0,
        "source_revisions": {"base_data_revision": "1"},
        "export_kind": "trackside_ap_business",
        "snapshot_build_ms": 12,
        "snapshot_retry_count": 0,
        "scope_context": {"display_name": "测试局点"},
        "business_rows": [],
        "workbook": {
            "rows": [],
            "overview_rows": [],
            "new_online_ap_rows": [],
            "optical_treatment_rows": [],
            "offline_stats": {},
            "offline_ledger_rows": [],
            "unmatched_online_rows": [],
        },
    }


def _one_row_export_payload() -> dict[str, object]:
    payload = _empty_export_payload()
    row = {
        "site": "普通测试站",
        "device_name": "SW-ORDINARY",
        "interface_name": "XGE1/0/1",
        "ap_name": "AP-ORDINARY",
        "ap_mac": "0011-2233-4455",
    }
    payload["business_rows"] = [row]
    workbook = dict(payload["workbook"])
    workbook["rows"] = [row]
    payload["workbook"] = workbook
    payload["row_count"] = 1
    payload["content_sha256"] = content_sha256([row])
    payload["export_content_sha256"] = content_sha256([row])
    return payload


def test_source_revisions_track_runtime_content_but_ignore_unrelated_metadata(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    initial = read_trackside_ap_source_revisions(database)
    with database.connect() as connection:
        connection.execute(
            "UPDATE schema_metadata SET updated_at = updated_at WHERE key = 'schema_version'"
        )
        connection.commit()
    assert read_trackside_ap_source_revisions(database) == initial

    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO ac_fit_ap_optical (
                ac_device_uuid, ap_uuid, ap_name, rx_power, collected_at, updated_at
            ) VALUES ('ac-1', 'ap-1', 'AP-1', '-10.00', 't1', 't1')
            """
        )
        connection.commit()
    changed = read_trackside_ap_source_revisions(database)
    assert changed["optical_data_revision"] != initial["optical_data_revision"]

    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO device_facts (
                device_uuid, sysname, collected_at, updated_at
            ) VALUES ('sw-1', 'HZDT-SC', 't1', 't1')
            """
        )
        connection.commit()
    facts_changed = read_trackside_ap_source_revisions(database)
    assert (
        facts_changed["switch_facts_revision"]
        != changed["switch_facts_revision"]
    )

    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO device_lldp_neighbors (
                device_uuid, local_interface, neighbor_mac, collected_at, updated_at
            ) VALUES ('sw-1', 'XGE1/0/1', '0011-2233-4455', 't1', 't1')
            """
        )
        connection.commit()
    lldp_changed = read_trackside_ap_source_revisions(database)
    assert lldp_changed["lldp_revision"] != facts_changed["lldp_revision"]

    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO ac_fit_ap_resources (
                ac_device_uuid, ap_uuid, ap_name, ap_mac, collected_at, updated_at
            ) VALUES ('ac-1', 'ap-1', 'AP-1', '0011-2233-4455', 't1', 't1')
            """
        )
        connection.commit()
    fit_ap_changed = read_trackside_ap_source_revisions(database)
    assert (
        fit_ap_changed["fit_ap_resource_revision"]
        != lldp_changed["fit_ap_resource_revision"]
    )

    with database.connect() as connection:
        connection.execute(
            """
            UPDATE schema_metadata
            SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT)
            WHERE key = 'base_data_revision'
            """
        )
        connection.commit()
    base_changed = read_trackside_ap_source_revisions(database)
    assert base_changed["base_data_revision"] != fit_ap_changed["base_data_revision"]

    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO ac_fit_ap_unauthenticated_history (
                ac_device_uuid, ap_name, collected_at, created_at
            ) VALUES ('ac-1', 'AP-1', 't2', 't2')
            """
        )
        connection.commit()
    unauthenticated_changed = read_trackside_ap_source_revisions(database)
    # Trackside Current revisions intentionally exclude the retired
    # unauthenticated/history timelines.
    assert unauthenticated_changed == base_changed

    before_export_history = read_trackside_ap_source_revisions(
        database,
        include_export_history=True,
    )
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO device_optical_modules_history (
                device_uuid, interface_name, collected_at, created_at
            ) VALUES ('sw-1', 'XGE1/0/1', 't2', 't2')
            """
        )
        connection.commit()
    assert (
        read_trackside_ap_source_revisions(database)
        == unauthenticated_changed
    )
    assert (
        read_trackside_ap_source_revisions(
            database,
            include_export_history=True,
        )["export_history_revision"]
        != before_export_history["export_history_revision"]
    )


def test_source_revisions_include_history_outbox_without_opening_history_shards(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    before = read_trackside_ap_source_revisions(database)
    history_root = database.path.parent / "history"
    history_root.mkdir()
    (history_root / "catalog.db").write_bytes(
        b"must not be opened by current-db revision"
    )

    with database.connect() as connection:
        assert HistoryStore(database.path).record_event(
            connection,
            kind="fit_ap_lldp",
            entity_key="ap-1",
            payload={"ap_uuid": "ap-1", "neighbor_interface": "GE1/0/1"},
            collected_at="2026-08-13T10:00:00",
            meaningful_fields=("ap_uuid", "neighbor_interface"),
        )
        connection.commit()

    after = read_trackside_ap_source_revisions(database)
    assert after == before
    assert (history_root / "catalog.db").read_bytes() == (
        b"must not be opened by current-db revision"
    )


def test_source_revision_uses_metadata_counters_without_row_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _database(tmp_path)
    with database.connect() as connection:
        connection.execute(
            "UPDATE schema_metadata SET value='41' WHERE key='trackside_ap_business_revision'"
        )
        connection.execute(
            "UPDATE schema_metadata SET value='7' WHERE key='trackside_ap_optical_revision'"
        )
        connection.commit()

    def fail_scan(*_args, **_kwargs):
        raise AssertionError("revision fallback must not scan current tables")

    monkeypatch.setattr(
        "netconsole.services.rail_transit.trackside_ap_business_snapshot._tables_revision",
        fail_scan,
    )
    revisions = read_trackside_ap_source_revisions(database)
    assert revisions["optical_data_revision"] == "7"
    assert "ap_history_revision" not in revisions


def test_stable_snapshot_retries_once_and_is_deterministic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = DeviceRepository(_database(tmp_path))
    revisions = iter(({"r": "1"}, {"r": "2"}, {"r": "2"}, {"r": "2"}))
    monkeypatch.setattr(
        export_service,
        "read_trackside_ap_source_revisions",
        lambda *_args, **_kwargs: next(revisions),
    )
    monkeypatch.setattr(
        export_service,
        "_load_trackside_ap_business_snapshot_once",
        lambda *_args, **_kwargs: TracksideApBusinessLoadResult(0, "demo", [], 0, 0, 0),
    )

    snapshot = load_trackside_ap_business_snapshot(repository, "demo", 0)

    assert snapshot.snapshot_retry_count == 1
    assert snapshot.business_revision
    assert snapshot.content_sha256


def test_complete_snapshot_survives_continuous_revision_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = DeviceRepository(_database(tmp_path))
    counter = 0

    def changing(*_args, **_kwargs):
        nonlocal counter
        counter += 1
        return {"r": str(counter)}

    monkeypatch.setattr(export_service, "read_trackside_ap_source_revisions", changing)
    monkeypatch.setattr(
        export_service,
        "_load_trackside_ap_business_snapshot_once",
        lambda *_args, **_kwargs: TracksideApBusinessLoadResult(0, "demo", [], 0, 0, 0),
    )

    snapshot = load_trackside_ap_business_snapshot(repository, "demo", 0)

    assert snapshot.snapshot_id
    assert snapshot.business_revision
    assert snapshot.content_sha256
    assert counter == 6


def test_business_revision_and_content_hash_are_idempotent(tmp_path: Path) -> None:
    repository = DeviceRepository(_database(tmp_path))
    first = load_trackside_ap_business_snapshot(repository, "demo", 0)
    second = load_trackside_ap_business_snapshot(repository, "demo", 0)

    assert first.snapshot_id != second.snapshot_id
    assert first.business_revision == second.business_revision
    assert first.content_sha256 == second.content_sha256

    with pytest.raises(TypeError):
        first.source_revisions["base_data_revision"] = "changed"  # type: ignore[index]


def test_trackside_text_query_reuses_base_snapshot_identity_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = PathResolver(tmp_path)
    paths.ensure_site_dirs("demo")
    SiteManager(paths).save_site_metadata("demo", {"display_name": "测试局点"})
    captured: list[tuple[object, ...]] = []
    snapshot = TracksideApBusinessLoadResult(
        0,
        "demo",
        [],
        0,
        0,
        0,
        snapshot_id="snapshot-1",
        business_revision="revision-1",
    )

    def load(*_args, **kwargs):
        captured.append(tuple(kwargs.get("identity_query_macs") or ()))
        return snapshot

    monkeypatch.setattr(
        "netconsole.services.rail_transit.trackside_ap_business_query_service.load_trackside_ap_business_snapshot",
        load,
    )
    service = TracksideApBusinessQueryService(paths)

    service.list_rows("demo", query="车站A")
    service.list_rows("demo", query="0011-2233-4455")

    assert captured == [(), ("0011-2233-4455",)]


def test_same_revision_snapshot_build_is_single_flight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _database(tmp_path)
    calls = 0
    original = export_service._load_trackside_ap_business_snapshot_once

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(
        export_service,
        "_load_trackside_ap_business_snapshot_once",
        counted,
    )

    def load() -> TracksideApBusinessLoadResult:
        return load_trackside_ap_business_snapshot(
            DeviceRepository(database),
            "single-flight",
            0,
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        snapshots = list(executor.map(lambda _index: load(), range(4)))

    assert calls == 1
    assert len({item.business_revision for item in snapshots}) == 1
    assert len({item.snapshot_id for item in snapshots}) == 4


def test_stable_snapshot_rows_and_identity_queries_are_immutable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = DeviceRepository(_database(tmp_path))
    monkeypatch.setattr(
        export_service,
        "read_trackside_ap_source_revisions",
        lambda *_args, **_kwargs: {"base_data_revision": "1"},
    )
    monkeypatch.setattr(
        export_service,
        "_load_trackside_ap_business_snapshot_once",
        lambda *_args, **_kwargs: TracksideApBusinessLoadResult(
            0,
            "demo",
            [{"site": "站点A", "business_row_id": "row-1"}],
            0,
            0,
            0,
            identity_query_entities={"001122334455": "entity-1"},
        ),
    )

    snapshot = load_trackside_ap_business_snapshot(repository, "demo", 0)

    assert isinstance(snapshot.rows, tuple)
    with pytest.raises(TypeError):
        snapshot.rows[0]["site"] = "changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        snapshot.identity_query_entities["001122334455"] = "changed"  # type: ignore[index]


def test_identity_is_resolved_once_for_distinct_macs_and_keeps_ambiguous(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[object], str | None]] = []

    class Query:
        def __init__(self, _database: Database) -> None:
            pass

        def resolve_ap_macs(self, macs, *, ap_role=None):
            calls.append((list(macs), ap_role))
            return ApIdentityBatchResult(
                revision=9,
                index_status="ready",
                requested_count=len(macs),
                normalized_count=len(macs),
                distinct_count=2,
                matched_count=1,
                unresolved_count=0,
                ambiguous_count=1,
                invalid_count=0,
                matches={
                    "001122334477": ApIdentityMatch(
                        status="matched",
                        identity_revision=9,
                        query_mac="001122334477",
                        matched_entity_id="entity-1",
                        match_rule="exact_alias",
                    ),
                    "001122334455": ApIdentityMatch(
                        status="matched",
                        identity_revision=9,
                        query_mac="001122334455",
                        matched_entity_id="entity-1",
                        match_rule="exact_alias",
                    ),
                    "001122334466": ApIdentityMatch(
                        status="ambiguous",
                        identity_revision=9,
                        query_mac="001122334466",
                        candidates=({"entity_id": "entity-2"}, {"entity_id": "entity-3"}),
                    ),
                },
            )

    monkeypatch.setattr(export_service, "ApIdentityQueryService", Query)
    rows, revision, counts, _queries = export_service._apply_batch_identity(
        [
            {
                "device_uuid": "sw-1",
                "interface_name": "XGE1/0/1",
                "ap_mac": "0011-2233-4455",
                "lldp_observed_neighbor_mac": "0011-2233-4477",
            },
            {"device_uuid": "sw-1", "interface_name": "XGE1/0/2", "ap_mac": "0011-2233-4455"},
            {"device_uuid": "sw-1", "interface_name": "XGE1/0/3", "ap_mac": "0011-2233-4466"},
        ],
        _database(tmp_path),
    )

    assert len(calls) == 1
    assert calls[0][1] == "trackside"
    assert calls[0][0] == [
        "001122334477",
        "001122334455",
        "001122334466",
    ]
    assert len(calls[0][0]) == len(set(calls[0][0]))
    assert revision == 9
    assert counts == {"distinct": 3, "unresolved": 0, "ambiguous": 1}
    assert rows[0]["ap_identity_entity_id"] == "entity-1"
    assert rows[2]["identity_match_status"] == "ambiguous"
    assert rows[2]["ap_identity_entity_id"] == ""


def test_export_snapshot_rejects_stale_selection(tmp_path: Path) -> None:
    repository = DeviceRepository(_database(tmp_path))

    with pytest.raises(TracksideApBusinessSnapshotError) as error:
        build_trackside_ap_business_export_snapshot(
            repository,
            "demo",
            selected_row_ids=["removed-row"],
        )

    assert error.value.code == "TRACKSIDE_AP_EXPORT_SELECTION_STALE"


def test_export_snapshot_ignores_deprecated_optical_anomaly_filter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = DeviceRepository(_database(tmp_path))
    calls: list[bool] = []
    source_rows = [
        {
            "business_row_id": "row-normal",
            "site": "站点A",
            "device_name": "SW-A",
            "interface_name": "XGE1/0/1",
            "optical_severity": "normal",
        },
        {
            "business_row_id": "row-abnormal",
            "site": "站点A",
            "device_name": "SW-A",
            "interface_name": "XGE1/0/2",
            "optical_severity": "warning",
        },
    ]

    monkeypatch.setattr(
        export_service,
        "read_trackside_ap_source_revisions",
        lambda *_args, **_kwargs: {"base_data_revision": "1"},
    )

    def build_once(*_args, optical_anomaly_only: bool, **_kwargs):
        calls.append(optical_anomaly_only)
        business_rows = select_trackside_ap_business_rows(
            source_rows,
            optical_anomaly_only=optical_anomaly_only,
        )
        return {
            "business_revision": "revision-1",
            "snapshot_retry_count": 0,
            "content_sha256": content_sha256(business_rows),
            "filters": {"station": "", "query": ""},
            "business_rows": business_rows,
        }

    monkeypatch.setattr(
        export_service,
        "_build_trackside_ap_business_export_snapshot_once",
        build_once,
    )

    unfiltered = build_trackside_ap_business_export_snapshot(
        repository,
        "demo",
        optical_anomaly_only=False,
    )
    deprecated_true = build_trackside_ap_business_export_snapshot(
        repository,
        "demo",
        optical_anomaly_only=True,
    )

    assert calls == [False, False]
    assert deprecated_true["business_rows"] == unfiltered["business_rows"]
    assert deprecated_true["content_sha256"] == unfiltered["content_sha256"]
    assert deprecated_true["filters"] == {"station": "", "query": ""}


def test_shared_selection_hash_matches_filtered_page_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    paths.ensure_site_dirs("demo")
    SiteManager(paths).save_site_metadata("demo", {"display_name": "测试局点"})
    rows = [
        {
            "business_row_id": "row-a",
            "site": "站点A",
            "device_name": "SW-A",
            "interface_name": "XGE1/0/1",
            "ap_name": "AP-A",
            "ap_mac": "0011-2233-4455",
            "identity_match_status": "matched",
        },
        {
            "business_row_id": "row-b",
            "site": "站点B",
            "device_name": "SW-B",
            "interface_name": "XGE1/0/2",
            "ap_name": "AP-B",
            "ap_mac": "0011-2233-4466",
            "identity_match_status": "unresolved",
        },
    ]
    snapshot = TracksideApBusinessLoadResult(
        0,
        "demo",
        rows,
        0,
        0,
        0,
        snapshot_id="snapshot-1",
        business_revision="revision-1",
        source_revisions={"base_data_revision": "1"},
        created_at="2026-08-06T01:00:00+08:00",
        row_count=2,
        business_row_count=2,
    )
    monkeypatch.setattr(
        "netconsole.services.rail_transit.trackside_ap_business_query_service.load_trackside_ap_business_snapshot",
        lambda *_args, **_kwargs: snapshot,
    )

    page = TracksideApBusinessQueryService(paths).list_rows(
        "demo",
        station="站点A",
    )
    selected = select_trackside_ap_business_rows(rows, station="站点A")

    assert page.row_count == 1
    assert page.total == 1
    assert page.content_sha256 == content_sha256(selected)
    assert page.abnormal_count == 0
    assert page.unresolved_count == 0


def test_worker_renders_only_from_frozen_snapshot(tmp_path: Path) -> None:
    path, digest = write_export_snapshot(
        tmp_path / "staging",
        site_id="demo",
        task_id="task-1",
        payload=_empty_export_payload(),
    )
    output = tmp_path / "result.xlsx"
    result = export_trackside_ap_business_from_snapshot(
        snapshot_path=path,
        snapshot_sha256=digest,
        output_path=output,
        tmp_path=tmp_path / "result.tmp",
    )

    assert output.is_file()
    assert result["business_revision"] == "b" * 64
    assert result["row_count"] == 0
    assert result["source_revisions"] == {"base_data_revision": "1"}
    assert result["export_kind"] == "trackside_ap_business"


def test_snapshot_hash_and_missing_file_errors_are_structured(tmp_path: Path) -> None:
    path, digest = write_export_snapshot(
        tmp_path / "staging",
        site_id="demo",
        task_id="task-1",
        payload=_empty_export_payload(),
    )
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(TracksideApBusinessSnapshotError) as invalid:
        read_export_snapshot(path, expected_sha256=digest)
    assert invalid.value.code == "TRACKSIDE_AP_SNAPSHOT_INVALID"

    path.unlink()
    with pytest.raises(TracksideApBusinessSnapshotError) as missing:
        read_export_snapshot(path, expected_sha256=digest)
    assert missing.value.code == "TRACKSIDE_AP_SNAPSHOT_NOT_FOUND"


def test_snapshot_write_failure_removes_pending_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_replace(_source: Path, _target: Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(
        "netconsole.services.rail_transit.trackside_ap_business_snapshot.os.replace",
        fail_replace,
    )
    with pytest.raises(OSError, match="replace failed"):
        write_export_snapshot(
            tmp_path / "staging",
            site_id="demo",
            task_id="task-1",
            payload=_empty_export_payload(),
        )
    task_dir = tmp_path / "staging" / "trackside_ap_business" / "demo" / "task-1"
    assert not (task_dir / "snapshot.json.tmp").exists()
    assert not (task_dir / "snapshot.json").exists()


def test_snapshot_supports_unicode_site_id_and_cleans_snapshot(tmp_path: Path) -> None:
    payload = _empty_export_payload()
    site_id = "宁波地铁12号线"
    task_id = "rail-export-unicode"
    path, digest = write_export_snapshot(
        tmp_path / "staging",
        site_id=site_id,
        task_id=task_id,
        payload=payload,
    )

    assert path.is_file()
    assert path.parent.name == task_id
    assert path.parent.parent.name == site_id
    assert read_export_snapshot(path, expected_sha256=digest) == payload
    assert cleanup_export_snapshot(
        tmp_path / "staging",
        site_id=site_id,
        task_id=task_id,
    )
    assert not path.exists()


def test_worker_prepares_unicode_snapshot_and_cleans_staging(tmp_path: Path) -> None:
    database = _database(tmp_path)
    output = tmp_path / "result.xlsx"
    result = export_service.export_trackside_ap_business_prepare_and_render(
        database_path=database.path,
        site_name="绍兴1号线",
        task_id="rail-export-worker",
        snapshot_staging_root=tmp_path / "staging",
        output_path=output,
        tmp_path=tmp_path / "result.xlsx.task.tmp",
    )

    assert output.is_file()
    assert result["export_kind"] == "trackside_ap_business"
    assert not list((tmp_path / "staging").rglob("snapshot.json"))


def test_recovery_cleans_terminal_trackside_snapshot(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    paths.ensure_site_dirs("demo")
    task_id = "rail-export-task-1"
    snapshot_path, _digest = write_export_snapshot(
        paths.staging_dir,
        site_id="demo",
        task_id=task_id,
        payload=_empty_export_payload(),
    )
    pending = snapshot_path.with_suffix(".json.tmp")
    pending.write_text("pending", encoding="utf-8")
    tasks = TaskApplicationService(paths=paths, site_name="demo")
    service = RailTransitWebApplicationService(
        paths,
        tasks,
        process_adapter=FakeLocalProcessAdapter(tasks),  # type: ignore[arg-type]
        export_adapter=FakeExportProcessAdapter(tasks),  # type: ignore[arg-type]
    )

    assert service._cleanup_recovered_task(
        "demo",
        SimpleNamespace(
            task_type="web_export_trackside_ap_business",
            task_id=task_id,
        ),
    )
    assert not snapshot_path.exists()
    assert not pending.exists()


def test_stale_expected_revision_creates_task_before_worker_validation(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    paths.ensure_site_dirs("demo")
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    SiteManager(paths).save_site_metadata("demo", {"display_name": "测试局点"})
    repository = DeviceRepository(database)
    current = load_trackside_ap_business_snapshot(
        repository,
        "demo",
        0,
        scope_context=TracksideApScopeContext.from_metadata(
            "demo",
            SiteManager(paths).load_site_metadata("demo"),
        ),
    )
    with database.connect() as connection:
        connection.execute(
            """
            UPDATE schema_metadata
            SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT)
            WHERE key = 'base_data_revision'
            """
        )
        connection.commit()
    tasks = TaskApplicationService(paths=paths, site_name="demo")
    export = FakeExportProcessAdapter(tasks)
    service = RailTransitWebApplicationService(
        paths,
        tasks,
        process_adapter=FakeLocalProcessAdapter(tasks),  # type: ignore[arg-type]
        export_adapter=export,  # type: ignore[arg-type]
    )

    started = service.start_trackside_ap_business_export(
        "demo",
        expected_revision=current.business_revision,
    )

    task = tasks.repository("demo").get(started.task_id)
    assert task is not None
    assert task.task_type == "web_export_trackside_ap_business"
    assert export.jobs[started.task_id].params["expected_revision"] == current.business_revision
    assert not list((paths.staging_dir / "trackside_ap_business").rglob("snapshot.json"))

    with pytest.raises(TracksideApBusinessSnapshotError) as error:
        export_service.export_trackside_ap_business_prepare_and_render(
            database_path=database.path,
            site_name="demo",
            task_id=started.task_id,
            snapshot_staging_root=paths.staging_dir,
            output_path=paths.staging_dir / "stale.xlsx",
            tmp_path=paths.staging_dir / "stale.xlsx.tmp",
            expected_revision=current.business_revision,
            scope_context=export.jobs[started.task_id].params["scope_context"],
        )

    assert error.value.code == "TRACKSIDE_AP_SNAPSHOT_STALE"
    assert not (paths.staging_dir / "stale.xlsx").exists()


def test_page_expected_revision_rejects_mixed_pagination(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    paths.ensure_site_dirs("demo")
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    first = TracksideApBusinessQueryService(paths).list_rows("demo")
    with database.connect() as connection:
        connection.execute(
            """
            UPDATE schema_metadata
            SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT)
            WHERE key = 'base_data_revision'
            """
        )
        connection.commit()

    with pytest.raises(TracksideApBusinessSnapshotError) as error:
        TracksideApBusinessQueryService(paths).list_rows(
            "demo",
            page=2,
            expected_revision=first.business_revision,
        )

    assert error.value.code == "TRACKSIDE_AP_SNAPSHOT_STALE"


@pytest.mark.parametrize(
    ("code", "expected_status"),
    [
        ("TRACKSIDE_AP_SNAPSHOT_STALE", 409),
        ("TRACKSIDE_AP_EXPORT_SELECTION_STALE", 409),
        ("TRACKSIDE_AP_SNAPSHOT_UNSTABLE", 503),
    ],
)
def test_snapshot_errors_have_structured_http_contract(
    code: str,
    expected_status: int,
) -> None:
    with pytest.raises(HTTPException) as raised:
        _raise_snapshot_error(TracksideApBusinessSnapshotError(code, "snapshot error"))

    assert raised.value.status_code == expected_status
    assert raised.value.detail == {"code": code, "message": "snapshot error"}


def test_export_freezes_complete_payload_when_live_revision_keeps_moving(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = DeviceRepository(_database(tmp_path))
    revision_counter = 0

    def changing_revisions(*_args, **_kwargs):
        nonlocal revision_counter
        revision_counter += 1
        return {"base_data_revision": str(revision_counter)}

    monkeypatch.setattr(
        export_service,
        "read_trackside_ap_source_revisions",
        changing_revisions,
    )
    monkeypatch.setattr(
        export_service,
        "_build_trackside_ap_business_export_snapshot_once",
        lambda *_args, **_kwargs: _one_row_export_payload(),
    )

    payload = build_trackside_ap_business_export_snapshot(repository, "ordinary-site")
    snapshot_path, snapshot_sha256 = write_export_snapshot(
        tmp_path / "staging",
        site_id="ordinary-site",
        task_id="moving-revision",
        payload=payload,
    )
    output = tmp_path / "moving-revision.xlsx"
    result = export_trackside_ap_business_from_snapshot(
        snapshot_path=snapshot_path,
        snapshot_sha256=snapshot_sha256,
        output_path=output,
        tmp_path=tmp_path / "moving-revision.xlsx.tmp",
    )

    assert output.is_file()
    assert result["business_revision"] == payload["business_revision"]
    assert result["content_sha256"] == payload["content_sha256"]
    assert result["row_count"] == 1
    assert revision_counter >= 6


def test_wps_workbook_uses_already_frozen_payload_without_live_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = PathResolver(tmp_path)
    paths.ensure_site_dirs("ordinary-site")
    payload = _one_row_export_payload()
    from netconsole.models.wps_sync import TRACKSIDE_AP_WPS_BUSINESS_KEY
    from netconsole.services.wps_trackside_ap_sync import TracksideApWpsSyncService

    service = TracksideApWpsSyncService(paths)
    monkeypatch.setattr(service, "_build_snapshot", lambda _site_id: payload)
    frozen = service._build_snapshot("ordinary-site")
    assert frozen is payload
    workbook, snapshot_sha256, _payload_size, _manifest = service._build_workbook_dto(
        "ordinary-site",
        "frozen-wps",
        frozen,
    )

    expected_sha256 = content_sha256(
        {
            "site_id": "ordinary-site",
            "business_key": TRACKSIDE_AP_WPS_BUSINESS_KEY,
            "snapshot_revision": payload["business_revision"],
            "content_sha256": payload["content_sha256"],
            "workbook": workbook.to_dict(),
        }
    )
    assert snapshot_sha256 == expected_sha256
    snapshot_path, snapshot_file_sha256 = write_export_snapshot(
        tmp_path / "staging",
        site_id="ordinary-site",
        task_id="wps-and-excel",
        payload=payload,
    )
    excel_result = export_trackside_ap_business_from_snapshot(
        snapshot_path=snapshot_path,
        snapshot_sha256=snapshot_file_sha256,
        output_path=tmp_path / "wps-and-excel.xlsx",
        tmp_path=tmp_path / "wps-and-excel.xlsx.tmp",
    )
    assert excel_result["business_revision"] == payload["business_revision"]
    assert excel_result["content_sha256"] == payload["content_sha256"]
    assert excel_result["row_count"] == 1


def test_snapshot_read_failure_is_not_converted_to_unstable_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = DeviceRepository(_database(tmp_path))

    def fail_read(*_args, **_kwargs):
        raise sqlite3.OperationalError("database is malformed")

    monkeypatch.setattr(
        export_service,
        "_load_trackside_ap_business_snapshot_once",
        fail_read,
    )
    with pytest.raises(sqlite3.OperationalError, match="malformed"):
        load_trackside_ap_business_snapshot(repository, "ordinary-site", 0)
