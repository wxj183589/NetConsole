from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
from contextlib import contextmanager
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


def test_cursor_pages_can_skip_exact_total(indexed):
    _, service = indexed
    expected = service.query(page_size=1)
    first = service.query(page_size=1, include_total=False)
    second = service.query(page_size=1, cursor=first["next_cursor"], include_total=False)
    assert first["items"] == expected["items"]
    assert first["next_cursor"] == expected["next_cursor"]
    assert first["total"] == second["total"] == 0
    assert not first["total_exact"]
    assert second["items"] == service.query(page=2, page_size=1)["items"]


def test_cursor_page_bounds_each_source_before_merging(indexed):
    path, service = indexed
    statements: list[str] = []

    @contextmanager
    def traced_snapshot():
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        connection.set_trace_callback(statements.append)
        try:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            yield connection
        finally:
            connection.rollback()
            connection.close()

    service._read_snapshot = traced_snapshot  # type: ignore[method-assign]
    page = service.query(run_id="run-1", page_size=2, include_total=False)
    source_queries = [sql for sql in statements if "cursor_julian_day" in sql]
    assert len(source_queries) == 10
    assert all("UNION ALL" not in sql for sql in source_queries)
    assert all("LIMIT 3" in sql for sql in source_queries)
    assert not any("COUNT(*) AS item_count" in sql for sql in statements)
    assert page["has_more"]


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
    expected_ids = [
        row["record_id"]
        for row in service.iter_export_rows(**filters)
    ]
    actual_ids = []
    cursor = ""
    while True:
        page = service.query(
            **filters, page_size=100, cursor=cursor,
            include_total=False,
        )
        actual_ids.extend(row["record_id"] for row in page["items"])
        if not page["has_more"]:
            break
        cursor = page["next_cursor"]
    assert actual_ids == expected_ids


def test_history_page_batches_detail_reads_and_keeps_site_filter(indexed):
    path, service = indexed
    with sqlite3.connect(path) as conn:
        for number in range(8):
            insert(
                conn,
                "events",
                site_id="demo",
                run_id="run-1",
                ts=STAMP,
                event_type=f"batch-{number}",
                details_json=json.dumps({"number": number}),
            )
        insert(
            conn,
            "events",
            site_id="other",
            run_id="other",
            ts=STAMP,
            event_type="other-site",
        )

    traces: list[str] = []

    @contextmanager
    def traced_snapshot():
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        connection.set_trace_callback(traces.append)
        try:
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            yield connection
        finally:
            connection.rollback()
            connection.close()

    service._read_snapshot = traced_snapshot  # type: ignore[method-assign]
    page = service.query(data_type="timeline", page_size=20)

    assert page["total"] == 9
    assert len(page["items"]) == 9
    detail_queries = [trace for trace in traces if "AS _source_rowid" in trace]
    assert len(detail_queries) == 1
    assert "rowid IN (" in detail_queries[0]
    assert "s.site_id='demo'" in detail_queries[0]
    ranking_query, = [trace for trace in traces if " AS cursor_ts_is_null" in trace]
    assert "details_json" not in ranking_query
    assert "_history_summary" in detail_queries[0]
    assert not any("WHERE rowid=?" in trace for trace in traces)
    assert sum("COUNT(*) AS item_count" in trace for trace in traces) == 1
    assert all(item["details"].get("site_id") == "demo" for item in page["items"])


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


@pytest.mark.parametrize("sort_order", ["asc", "desc"])
def test_cursor_pagination_matches_global_export_for_mixed_sources(indexed, sort_order):
    _path, service = indexed
    expected = list(service.iter_export_rows(sort_order=sort_order))
    actual = []
    cursor = ""
    while True:
        page = service.query(sort_order=sort_order, page_size=2, cursor=cursor)
        actual.extend(page["items"])
        if not page["has_more"]:
            break
        assert page["next_cursor"]
        cursor = page["next_cursor"]
    assert [row["record_id"] for row in actual] == [row["record_id"] for row in expected]
    assert len(actual) == len({row["record_id"] for row in actual})


def test_cursor_is_bound_to_site_and_filters(indexed):
    path, service = indexed
    first = service.query(page_size=1)
    cursor = first["next_cursor"]
    assert cursor

    with pytest.raises(GroundHistoryQueryError) as wrong_filter:
        service.query(data_type="run", page_size=1, cursor=cursor)
    assert wrong_filter.value.code == "GROUND_HISTORY_CURSOR_INVALID"

    other_site = GroundHistoryQueryService(path, site_id="other")
    with pytest.raises(GroundHistoryQueryError) as wrong_site:
        other_site.query(data_type="timeline", page_size=1, cursor=cursor)
    assert wrong_site.value.code == "GROUND_HISTORY_CURSOR_INVALID"

    with pytest.raises(GroundHistoryQueryError) as malformed:
        service.query(page_size=1, cursor="not-a-cursor")
    assert malformed.value.code == "GROUND_HISTORY_CURSOR_INVALID"


def test_cursor_anchor_survives_delete_and_excludes_newer_insert(indexed):
    path, service = indexed
    with sqlite3.connect(path) as conn:
        insert(conn, "events", site_id="demo", run_id="run-1", ts="2026-11-07T11:00:00+08:00", event_type="anchor-newer")
        insert(conn, "events", site_id="demo", run_id="run-1", ts="2026-11-07T09:00:00+08:00", event_type="anchor-older")
    first = service.query(data_type="timeline", page_size=1, sort_order="desc")
    cursor = first["next_cursor"]
    anchor_id = first["items"][0]["record_id"]
    anchor_rowid = int(anchor_id.rsplit(":", 1)[-1])
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM ground_unattended_events WHERE rowid=?", (anchor_rowid,))
        insert(conn, "events", site_id="demo", run_id="run-1", ts="2026-11-07T12:00:00+08:00", event_type="newer")
        insert(conn, "events", site_id="demo", run_id="run-1", ts="2026-11-07T09:00:00+08:00", event_type="older")
    pages = []
    while True:
        page = service.query(data_type="timeline", page_size=1, sort_order="desc", cursor=cursor)
        pages.extend(page["items"])
        if not page["has_more"]:
            break
        cursor = page["next_cursor"]
    ids = [row["record_id"] for row in pages]
    assert anchor_id not in ids
    assert any(row["details"].get("event_type") == "older" for row in pages)
    assert all(row["details"].get("event_type") != "newer" for row in pages)


@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_cursor_empty_timestamp_matches_export_without_duplicates(indexed, direction):
    path, service = indexed
    with sqlite3.connect(path) as conn:
        for number in range(2):
            insert(
                conn, "raw_files", site_id="demo", run_id="run-1",
                file_id=f"raw-empty-{number}", data_type="syslog",
                relative_path=f"syslog/empty-{number}.ndjson", start_time="",
            )
        insert(
            conn, "events", site_id="demo", run_id="run-1",
            ts="2026-11-07T09:00:00+08:00", event_type="earlier-event",
        )
        insert(
            conn, "events", site_id="other", run_id="other",
            ts="", event_type="other-site-empty",
        )

    expected = list(service.iter_export_rows(sort_order=direction))
    expected_ids = [row["record_id"] for row in expected]
    assert len(expected_ids) == 13
    assert len({row["ts"] for row in expected}) >= 3
    empty_ids = {f"ground_unattended_raw_files:raw-empty-{number}" for number in range(2)}
    assert empty_ids.issubset(expected_ids)

    actual_ids: list[str] = []
    cursor = ""
    last_page = None
    for _ in range(len(expected_ids) + 1):
        page = service.query(sort_order=direction, page_size=1, cursor=cursor)
        assert len(page["items"]) == 1
        actual_ids.append(page["items"][0]["record_id"])
        last_page = page
        if not page["has_more"]:
            break
        assert page["next_cursor"] and page["next_cursor"] != cursor
        cursor = page["next_cursor"]

    assert last_page is not None and last_page["has_more"] is False
    assert last_page["next_cursor"] == ""
    assert len(actual_ids) == len(expected_ids)
    assert len(set(actual_ids)) == len(actual_ids)
    assert actual_ids == expected_ids
    assert empty_ids.issubset(actual_ids)


def test_previous_cursor_version_is_rejected(indexed):
    _path, service = indexed
    current = service.query(page_size=1)["next_cursor"]
    _version, encoded, _digest = current.split(".")
    payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    payload["v"] = 1
    payload["anchor"].pop("ts_is_null", None)
    old_raw = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")
    old_cursor = (
        "v1." + base64.urlsafe_b64encode(old_raw).decode("ascii").rstrip("=")
        + "." + hashlib.sha256(old_raw).hexdigest()[:16]
    )
    with pytest.raises(GroundHistoryQueryError) as rejected:
        service.query(page_size=1, cursor=old_cursor)
    assert rejected.value.code == "GROUND_HISTORY_CURSOR_INVALID"
