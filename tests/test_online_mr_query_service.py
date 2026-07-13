from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.models.api.online_mr import OnlineMrDownsampleMode, OnlineMrMetricType
from netconsole.services.online_mr.errors import OnlineMrQueryError, OnlineMrQueryErrorCode
from netconsole.services.online_mr.query_service import OnlineMrQueryService


def _service(tmp_path: Path) -> OnlineMrQueryService:
    return OnlineMrQueryService(PathResolver(app_root=tmp_path, data_root=tmp_path))


def _session(
    service: OnlineMrQueryService,
    session_id: str,
    *,
    site: str = "site-a",
    mr: str = "MR-01",
    started_at: str = "2026-07-13 10:00:00",
    status: str = "COMPLETED",
) -> Path:
    path = service.paths.online_mr_session_dir(site, mr, session_id)
    for name in ("raw", "parsed", "view", "logs", "outputs"):
        (path / name).mkdir(parents=True, exist_ok=True)
    (path / "session_meta.json").write_text(
        json.dumps(
            {
                "session_id": session_id,
                "site": site,
                "mr_name": mr,
                "device_id": 7,
                "device_name": "列车07 MR",
                "status": status,
                "started_at": started_at,
                "ended_at": "2026-07-13 10:10:00",
                "host": "192.0.2.1",
                "protocol": "SSH",
                "port": 22,
                "intervals": {"mesh_link": 1},
                "fping": {"enabled": True},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def _metric_database(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE main_link_samples (
                id INTEGER PRIMARY KEY, device_time TEXT, collector_time TEXT, radio INTEGER,
                mr_rssi REAL, resolved_peer_name TEXT, peer_name TEXT, peer_mac TEXT
            );
            CREATE TABLE channel_busy_records (
                id INTEGER PRIMARY KEY, device_time TEXT, radio INTEGER, ctl_busy REAL, tx_busy REAL, rx_busy REAL
            );
            CREATE TABLE interface_rate_samples (
                id INTEGER PRIMARY KEY, device_time TEXT, interface_name TEXT, direction TEXT, total_pps REAL
            );
            CREATE TABLE fping_samples (
                id INTEGER PRIMARY KEY, collector_time TEXT, target_ip TEXT, success INTEGER, latency_ms REAL
            );
            CREATE TABLE fping_1s_summary (
                id INTEGER PRIMARY KEY, bucket_time TEXT, target_ip TEXT, loss_percent REAL
            );
            CREATE TABLE iperf_intervals (
                id INTEGER PRIMARY KEY, run_id TEXT, collector_time TEXT, bitrate_mbps REAL
            );
            CREATE TABLE analysis_events (
                id INTEGER PRIMARY KEY, collector_time TEXT, event_type TEXT, severity TEXT,
                summary_text TEXT, details_json TEXT
            );
            """
        )
        conn.executemany(
            "INSERT INTO main_link_samples VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (1, "2026-07-13 10:00:00", None, 1, -60, "AP-1", "", "aa"),
                (2, "2026-07-13 10:00:01", None, 2, -70, "AP-2", "", "bb"),
            ],
        )
        conn.executemany(
            "INSERT INTO channel_busy_records VALUES (?, ?, ?, ?, ?, ?)",
            [
                (1, "2026-07-13 10:00:00", 1, 20, 10, 5),
                (2, "2026-07-13 10:00:00", 2, 80, 30, 10),
            ],
        )
        conn.executemany(
            "INSERT INTO fping_samples VALUES (?, ?, ?, ?, ?)",
            [
                (1, "2026-07-13 10:00:00", "10.0.0.1", 1, 2.5),
                (2, "2026-07-13 10:00:01", "10.0.0.1", 0, None),
                (3, "2026-07-13 10:00:00", "10.0.0.2", 1, 8.0),
            ],
        )


def test_list_sessions_is_stable_filtered_and_site_isolated(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _session(service, "older", started_at="2026-07-13 09:00:00")
    latest = _session(service, "latest", started_at="2026-07-13 11:00:00", status="FAILED")
    (latest / "outputs" / "latest.zip").write_bytes(b"zip")
    _session(service, "other", site="site-b")
    broken = service.paths.online_mr_session_dir("site-a", "MR-01", "broken")
    broken.mkdir(parents=True)
    (broken / "session_meta.json").write_text("{", encoding="utf-8")

    assert [row.session_id for row in service.list_sessions("site-a")] == ["latest", "older"]
    rows = service.list_sessions("site-a", status="FAILED", has_package=True, limit=1)
    assert [row.session_id for row in rows] == ["latest"]
    assert service.list_sessions("site-a", created_after="2026-07-13 10:00:00")[0].session_id == "latest"


def test_get_session_handles_old_metadata_raw_only_and_safe_reference(tmp_path: Path) -> None:
    service = _service(tmp_path)
    session = _session(service, "raw-only")
    (session / "raw" / "terminal_monitor_raw.log").write_text("raw", encoding="utf-8")

    detail = service.get_session("site-a", "raw-only")

    assert detail.has_raw_data is True
    assert detail.has_parsed_data is False
    assert detail.finalization_complete is None
    assert detail.data_integrity == "unknown"
    assert detail.session_path_reference == "MR-01/sessions/raw-only"
    assert str(tmp_path) not in detail.model_dump_json()


def test_get_session_prefers_finalized_traffic_summary(tmp_path: Path) -> None:
    service = _service(tmp_path)
    session = _session(service, "traffic-summary")
    meta_path = session / "session_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["traffic_summary"] = {
        "fping": {"status": "stopped", "sent_count": 10},
        "iperf": {"status": "stopped_by_collection"},
        "flush_complete": True,
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    detail = service.get_session("site-a", "traffic-summary")

    assert detail.traffic_summary["flush_complete"] is True
    assert detail.traffic_summary["fping"]["sent_count"] == 10


def test_missing_and_invalid_metadata_have_domain_errors(tmp_path: Path) -> None:
    service = _service(tmp_path)
    missing = service.paths.online_mr_session_dir("site-a", "MR-01", "missing")
    missing.mkdir(parents=True)
    invalid = service.paths.online_mr_session_dir("site-a", "MR-01", "invalid")
    invalid.mkdir(parents=True)
    (invalid / "session_meta.json").write_text("[]", encoding="utf-8")

    with pytest.raises(OnlineMrQueryError, match="缺少 metadata") as missing_error:
        service.get_session("site-a", "missing")
    assert missing_error.value.code == OnlineMrQueryErrorCode.SESSION_INCOMPLETE
    with pytest.raises(OnlineMrQueryError, match="metadata 无效") as invalid_error:
        service.get_session("site-a", "invalid")
    assert invalid_error.value.code == OnlineMrQueryErrorCode.METADATA_INVALID


@pytest.mark.parametrize("site,session_id", [("../site-a", "x"), ("site-a", "../x"), ("site-a", "C:\\x")])
def test_session_lookup_rejects_path_traversal(tmp_path: Path, site: str, session_id: str) -> None:
    service = _service(tmp_path)
    with pytest.raises(OnlineMrQueryError) as error:
        service.get_session(site, session_id)
    assert error.value.code == OnlineMrQueryErrorCode.SESSION_NOT_FOUND


def test_artifacts_are_whitelisted_and_temporary_files_are_excluded(tmp_path: Path) -> None:
    service = _service(tmp_path)
    session = _session(service, "artifacts")
    (session / "raw" / "mesh_link_raw.log").write_text("fact", encoding="utf-8")
    (session / "parsed" / "online_diagnosis.sqlite").write_bytes(b"derived")
    (session / "outputs" / "artifacts.zip").write_bytes(b"zip")
    (session / "outputs" / "artifacts.zip.tmp").write_bytes(b"partial")
    (session / "view" / "hidden.txt").write_text("hidden", encoding="utf-8")

    rows = service.list_artifacts("site-a", "artifacts")
    names = {row.relative_name for row in rows}

    assert "raw/mesh_link_raw.log" in names
    assert "parsed/online_diagnosis.sqlite" in names
    assert "outputs/artifacts.zip" in names
    assert "outputs/artifacts.zip.tmp" not in names
    assert "view/hidden.txt" not in names
    assert next(row for row in rows if row.kind == "raw").is_fact_source is True
    assert next(row for row in rows if row.kind == "parsed").is_rebuildable is True
    assert all(not Path(row.relative_name).is_absolute() and ".." not in Path(row.relative_name).parts for row in rows)


def test_artifacts_exclude_symlinks(tmp_path: Path) -> None:
    service = _service(tmp_path)
    session = _session(service, "symlink")
    outside = tmp_path / "outside.log"
    outside.write_text("secret", encoding="utf-8")
    link = session / "raw" / "outside.log"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("当前 Windows 环境不允许创建符号链接")
    assert "raw/outside.log" not in {row.relative_name for row in service.list_artifacts("site-a", "symlink")}


def test_log_chunks_use_byte_cursor_tail_and_utf8_replacement(tmp_path: Path) -> None:
    service = _service(tmp_path)
    session = _session(service, "logs")
    path = session / "logs" / "collector.log"
    path.write_bytes(b"2026-07-13 10:00:00 [INFO] one\ninvalid:\xff\nlast")

    first = service.read_log_chunk("site-a", "logs", "collector", limit=2)
    assert len(first.lines) == 2
    assert first.lines[0].timestamp == "2026-07-13 10:00:00"
    assert "�" in first.lines[1].text
    assert first.has_more is True
    with path.open("ab") as handle:
        handle.write(b"-continued\nnew\n")
    second = service.read_log_chunk("site-a", "logs", "collector", cursor=first.next_cursor, limit=2)
    assert second.lines[0].text == "last-continued"
    tail = service.read_log_chunk("site-a", "logs", "collector", limit=1, tail=True)
    assert [line.text for line in tail.lines] == ["new"]


def test_log_errors_are_controlled(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _session(service, "logs")
    with pytest.raises(OnlineMrQueryError) as invalid:
        service.read_log_chunk("site-a", "logs", "unknown")
    assert invalid.value.code == OnlineMrQueryErrorCode.LOG_SOURCE_INVALID
    with pytest.raises(OnlineMrQueryError) as missing:
        service.read_log_chunk("site-a", "logs", "collector")
    assert missing.value.code == OnlineMrQueryErrorCode.ARTIFACT_NOT_FOUND


def test_metrics_preserve_ping_targets_radios_and_timeout_semantics(tmp_path: Path) -> None:
    service = _service(tmp_path)
    session = _session(service, "metrics")
    _metric_database(session / "parsed" / "online_diagnosis.sqlite")

    rows = service.query_metrics(
        "site-a",
        "metrics",
        [OnlineMrMetricType.PING_RTT, OnlineMrMetricType.CTL_BUSY, OnlineMrMetricType.RSSI],
    )

    ping = [row for row in rows if row.metric_type == OnlineMrMetricType.PING_RTT]
    busy = [row for row in rows if row.metric_type == OnlineMrMetricType.CTL_BUSY]
    rssi = [row for row in rows if row.metric_type == OnlineMrMetricType.RSSI]
    assert len(ping) == 2
    assert sorted(point.value for row in ping for point in row.points) == [2.5, 8.0]
    assert len(busy) == 2
    assert len(rssi) == 2
    assert all(point.value != 0 for row in rows for point in row.points if point.value is not None)


def test_metrics_support_old_missing_schema_and_deterministic_downsample(tmp_path: Path) -> None:
    service = _service(tmp_path)
    session = _session(service, "old-db")
    db = session / "parsed" / "online_diagnosis.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE main_link_samples (device_time TEXT, radio INTEGER, mr_rssi REAL, peer_name TEXT)")
        conn.executemany(
            "INSERT INTO main_link_samples VALUES (?, ?, ?, ?)",
            [
                ("2026-07-13 10:00:00.100", 1, -60, "AP-1"),
                ("2026-07-13 10:00:00.900", 1, -70, "AP-1"),
            ],
        )
    rows = service.query_metrics(
        "site-a",
        "old-db",
        [OnlineMrMetricType.RSSI, OnlineMrMetricType.PING_LOSS],
        downsample=OnlineMrDownsampleMode.BUCKET_AVG,
    )
    assert len(rows) == 1
    assert rows[0].points[0].value == -65


def test_database_missing_corrupt_and_busy_are_controlled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(tmp_path)
    session = _session(service, "database")
    assert service.get_database_summary("site-a", "database").error_code == OnlineMrQueryErrorCode.DATABASE_NOT_FOUND
    db = session / "parsed" / "online_diagnosis.sqlite"
    db.write_bytes(b"not sqlite")
    assert service.get_database_summary("site-a", "database").error_code == OnlineMrQueryErrorCode.DATABASE_INCOMPATIBLE

    def locked(*args: object, **kwargs: object) -> sqlite3.Connection:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr("netconsole.services.online_mr.query_service.sqlite3.connect", locked)
    with pytest.raises(OnlineMrQueryError) as error:
        service.query_metrics("site-a", "database", [OnlineMrMetricType.RSSI])
    assert error.value.code == OnlineMrQueryErrorCode.DATABASE_BUSY


def test_notes_and_timeline_keep_missing_device_time_as_none(tmp_path: Path) -> None:
    service = _service(tmp_path)
    session = _session(service, "notes")
    (session / "manual_notes.jsonl").write_text(
        '{"session_id":"notes","local_time":"2026-07-13 10:01:00","device_aligned_time":null,"note":"现场备注"}\ninvalid\n',
        encoding="utf-8",
    )
    notes = service.list_notes("site-a", "notes")
    timeline = service.query_timeline("site-a", "notes")
    assert len(notes) == 1
    assert notes[0].device_time is None
    assert timeline[0].title == "现场备注"


def test_query_service_has_no_qt_dependency() -> None:
    source = Path("src/netconsole/services/online_mr/query_service.py").read_text(encoding="utf-8")
    assert "PySide6" not in source
    assert "QObject" not in source
