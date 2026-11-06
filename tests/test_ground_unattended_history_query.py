from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from netconsole.repositories.ground_unattended_repository import GroundUnattendedRepository
from netconsole.services.ground_unattended.history_query import (
    HISTORY_DATA_TYPES,
    GroundHistoryQueryError,
    GroundHistoryQueryService,
)

STAMP = "2026-11-07T10:00:00+08:00"


def insert(conn: sqlite3.Connection, table: str, **values: object) -> None:
    """Use the real schema, filling only required fixture columns."""
    table = "ground_unattended_" + table
    for _, name, kind, required, default, primary in conn.execute(f"PRAGMA table_info({table})"):
        if name in values or default is not None or not required or (primary and kind == "INTEGER"):
            continue
        values[name] = 0 if kind in {"INTEGER", "REAL"} else STAMP if name.endswith("_at") else "fixture"
    conn.execute(f"INSERT INTO {table} ({','.join(values)}) VALUES ({','.join('?' for _ in values)})", tuple(values.values()))


@pytest.fixture
def indexed(tmp_path: Path):
    path = tmp_path / "ground.sqlite"
    GroundUnattendedRepository(path, site_id="demo")
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        common = {"site_id": "demo", "run_id": "run-1"}
        identity = {"train_id": "train-1", "mr_id": "mr-1", "mr_position_code": "CT"}
        insert(conn, "runs", **common, run_date="2026-11-07", state="STOPPED", actual_started_at=STAMP)
        insert(conn, "train_runs", **common, train_id="train-1", endpoints_json=json.dumps([
            {"mr_id": "mr-1", "endpoint": "CT"}, {"mr_id": "mr-2", "endpoint": "CW"},
        ]))
        insert(conn, "ping_summaries", **common, **identity, bucket_kind="minute", bucket_start=STAMP, bucket_end=STAMP, target_ip="192.0.2.1")
        insert(conn, "heartbeat_states", **common, entity_type="MR", entity_id="mr-1", snapshot_json=json.dumps({"train_id": "train-1", "mr_uuid": "mr-1", "role": "CT"}))
        insert(conn, "quick_ping_runs", site_id="demo", run_id="quick-1", run_date="2026-11-07", state="COMPLETED", started_at=STAMP, targets_json=json.dumps([
            {"train_id": "train-1", "mr_id": "mr-1", "mr_role": "CT"},
            {"train_id": "train-1", "mr_id": "mr-2", "mr_role": "CW"},
        ]))
        insert(conn, "raw_files", **common, file_id="raw-1", train_id="train-1", device_uuid="mr-1", mr_role="CT", data_type="syslog", relative_path="syslog/a.ndjson", start_time=STAMP, record_count=87, sha256="a" * 64, revision=3)
        insert(conn, "wmesh_events", **common, train_id="train-1", device_uuid="mr-1", mr_role="CT", event_type="RADIO_DOWN", receive_time=STAMP)
        insert(conn, "ac_snapshots", **common, **identity, snapshot_id="ac-1", received_at=STAMP)
        insert(conn, "deep_operations", **common, **identity, operation_id="deep-1", started_at=STAMP)
        insert(conn, "events", **common, train_id="train-1", mr_id="mr-1", ts=STAMP, event_type="RADIO_DOWN", details_json=json.dumps({"mr_role": "CT"}))
        insert(conn, "events", site_id="other", run_id="other", ts=STAMP, event_type="RADIO_DOWN")
    return path, GroundHistoryQueryService(path, site_id="demo")


def test_all_durable_sources_identity_and_raw_integrity(indexed):
    _, service = indexed
    page = service.query()
    assert page["total"] == 10
    assert set(row["data_type"] for row in page["items"]) == set(HISTORY_DATA_TYPES)
    assert set(page["sources"].values()) == {"AVAILABLE"}
    assert service.query(train_id="train-1", mr_id="mr-1", mr_role="CT")["total"] == 10
    assert service.query(train_id="train-1", mr_id="mr-1", mr_role="CW")["total"] == 0
    raw = service.query(data_type="syslog_raw")["items"][0]
    assert raw["details"]["record_count"] == 87
    assert raw["details"]["sha256"] == "a" * 64
    assert raw["details"]["revision"] == 3
    assert service.query(event_type="RADIO_DOWN")["total"] == 2


def test_pagination_timezone_and_export_consistent_snapshot(indexed):
    path, service = indexed
    with sqlite3.connect(path) as conn:
        for number in range(620):
            insert(conn, "events", site_id="demo", run_id="run-1", ts=STAMP, event_type=f"event-{number}")
    filters = {"data_type": "timeline", "start_at": "2026-11-07T01:59:59Z", "end_at": "2026-11-07T02:00:01Z"}
    pages = [service.query(**filters, page=p, page_size=100) for p in range(1, 8)]
    assert {page["total"] for page in pages} == {621}
    assert len({row["record_id"] for page in pages for row in page["items"]}) == 621
    rows = service.iter_export_rows(**filters)
    first = next(rows)
    with sqlite3.connect(path) as conn:
        insert(conn, "events", site_id="demo", run_id="run-1", ts=STAMP, event_type="late")
    assert len([first, *rows]) == 621
    assert service.query(**filters)["total"] == 622


def test_missing_index_has_no_write_side_effects(tmp_path):
    path = tmp_path / "missing" / "ground.sqlite"
    service = GroundHistoryQueryService(path, site_id="demo")
    assert service.query()["total"] == 0
    assert list(service.iter_export_rows()) == []
    assert not path.parent.exists()


def test_history_gateway_snapshot_rejects_database_writes(indexed):
    _, service = indexed
    before = service.query()["total"]
    with service._read_snapshot() as connection:
        assert connection is not None
        assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("DELETE FROM ground_unattended_events")
    assert service.query()["total"] == before


@pytest.mark.parametrize("filters", [
    {"sort_order": "desc; DROP TABLE events"}, {"data_type": "arbitrary"}, {"mr_role": "mr1"}, {"start_at": "2026-11-07T10:00:00"},
    {"start_at": "2026-11-08T00:00:00Z", "end_at": "2026-11-07T00:00:00Z"},
])
def test_invalid_filters_fail_before_read(tmp_path, filters):
    with pytest.raises(GroundHistoryQueryError):
        GroundHistoryQueryService.validate_filters(**filters)
    with pytest.raises(GroundHistoryQueryError):
        GroundHistoryQueryService(tmp_path / "missing.sqlite", site_id="demo").query(**filters)


def test_history_sort_is_global_before_pagination_and_matches_export(indexed):
    path, service = indexed
    with sqlite3.connect(path) as conn:
        for number, stamp in enumerate(("2026-11-07T01:00:00Z", "2026-11-07T11:00:00+08:00", "2026-11-07T02:00:00Z")):
            insert(conn, "events", site_id="demo", run_id="run-1", ts=stamp, event_type=f"sort-{number}")
    for direction in ("asc", "desc"):
        expected = list(service.iter_export_rows(data_type="timeline", sort_order=direction))
        actual = [service.query(data_type="timeline", sort_order=direction, page=page, page_size=1)["items"][0] for page in range(1, 5)]
        assert [row["record_id"] for row in actual] == [row["record_id"] for row in expected]
        assert actual[0]["event_type"] == ("sort-0" if direction == "asc" else "sort-1")
