from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta
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
            CREATE TABLE radio_statistics_samples (
                id INTEGER PRIMARY KEY, collector_time TEXT, device_clock TEXT, radio INTEGER,
                metric_name TEXT, metric_value REAL, metric_unit TEXT,
                raw_file TEXT, raw_line_start INTEGER, raw_line_end INTEGER
            );
            CREATE TABLE switch_history_events (
                id INTEGER PRIMARY KEY, event_time_local TEXT, event_time_device TEXT,
                snapshot_collector_time TEXT, radio INTEGER, old_peer_name TEXT, old_peer_mac TEXT,
                old_rssi REAL, new_peer_name TEXT, new_peer_mac TEXT, new_rssi REAL,
                switch_reason_text TEXT, raw_file TEXT, raw_line_start INTEGER, raw_line_end INTEGER
            );
            CREATE TABLE switch_realtime_events (
                id INTEGER PRIMARY KEY, device_time TEXT,
                old_peer_name TEXT, old_peer_mac TEXT, old_rssi REAL,
                new_peer_name TEXT, new_peer_mac TEXT, new_rssi REAL,
                switch_reason_text TEXT, raw_file TEXT, raw_line_start INTEGER, raw_line_end INTEGER
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
            "INSERT INTO radio_statistics_samples VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (1, "2026-07-13 10:00:00", "10:00:00", 1, "TxFrameAllCnt", 120, "frame", "raw/ap_radio_statistics_raw.log", 10, 20),
                (2, "2026-07-13 10:00:01", "10:00:01", 1, "TxRetryFrmCnt", None, "frame", "raw/ap_radio_statistics_raw.log", 21, 30),
            ],
        )
        conn.execute(
            "INSERT INTO switch_history_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, "2026-07-13 10:01:00", "2026-07-13 10:01:00", None, 1, "AP-OLD-H", "aa", -81, "AP-NEW-H", "bb", -55, "history", "raw/switch_history_latest.log", 31, 32),
        )
        conn.execute(
            "INSERT INTO switch_realtime_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, "2026-07-13 10:02:00", "AP-OLD-R", "cc", -77, "AP-NEW-R", "dd", -49, "realtime", "raw/terminal_monitor_raw.log", 41, 42),
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
    assert detail.database_summary.status == "missing"
    assert detail.database_summary.action == "parse_session"
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


def test_current_session_uses_explicit_active_operation_session(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _session(service, "older-active", started_at="2026-07-13 09:00:00", status="COLLECTING")
    _session(service, "selected-active", started_at="2026-07-13 10:00:00", status="COLLECTING")

    assert service.get_current_session("site-a", session_id=None) is None
    current = service.get_current_session("site-a", session_id="older-active")

    assert current is not None and current.session_id == "older-active"


def test_current_session_falls_back_to_active_task_mapping(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _session(service, "mapping-active", started_at="2026-07-13 10:00:00", status="COLLECTING")
    tasks_db = service.paths.site_tasks_db_path("site-a")
    tasks_db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(tasks_db) as conn:
        conn.execute(
            "CREATE TABLE online_mr_task_sessions ("
            "controller_task_id TEXT PRIMARY KEY, session_id TEXT, site_id TEXT, mapping_state TEXT, "
            "updated_at TEXT, created_at TEXT)"
        )
        conn.execute(
            "INSERT INTO online_mr_task_sessions VALUES (?, ?, ?, ?, ?, ?)",
            ("task-1", "mapping-active", "site-a", "LINKED", "2026-07-13 10:05:00", "2026-07-13 10:00:00"),
        )

    current = service.get_current_session("site-a")

    assert current is not None
    assert current.session_id == "mapping-active"


def test_collectors_report_fresh_stale_and_interrupted_from_fact_timestamps(tmp_path: Path) -> None:
    service = _service(tmp_path)
    session = _session(service, "freshness", status="COLLECTING")
    raw = session / "raw" / "mesh_link_raw.log"
    raw.write_text("sample", encoding="utf-8")

    os.utime(raw, ((datetime.now() - timedelta(seconds=10)).timestamp(),) * 2)
    fresh = next(row for row in service.list_collectors("site-a", "freshness") if row.name == "mesh_link")
    os.utime(raw, ((datetime.now() - timedelta(seconds=60)).timestamp(),) * 2)
    stale = next(row for row in service.list_collectors("site-a", "freshness") if row.name == "mesh_link")
    os.utime(raw, ((datetime.now() - timedelta(seconds=180)).timestamp(),) * 2)
    interrupted = next(row for row in service.list_collectors("site-a", "freshness") if row.name == "mesh_link")

    assert fresh.health_status == "normal"
    assert stale.health_status == "stale"
    assert interrupted.health_status == "interrupted"
    assert interrupted.stale_seconds is not None and interrupted.stale_seconds >= 179


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


def test_preview_rssi_prefers_signal_dbm_and_normalizes_positive_h3c_magnitude() -> None:
    assert OnlineMrQueryService._preview_rssi_dbm(-52, 36) == -52
    assert OnlineMrQueryService._preview_rssi_dbm(None, 52) == -52
    assert OnlineMrQueryService._preview_rssi_dbm(None, -51) == -51
    assert OnlineMrQueryService._preview_rssi_dbm(None, None) is None


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


def test_metric_page_returns_real_radio_statistics_units_without_raw_evidence(tmp_path: Path) -> None:
    service = _service(tmp_path)
    session = _session(service, "radio-statistics")
    _metric_database(session / "parsed" / "online_diagnosis.sqlite")

    first = service.query_metric_page(
        "site-a",
        "radio-statistics",
        [OnlineMrMetricType.RADIO_STATISTICS],
        limit=1,
    )
    second = service.query_metric_page(
        "site-a",
        "radio-statistics",
        [OnlineMrMetricType.RADIO_STATISTICS],
        limit=1,
        offset=1,
    )

    assert first.has_more is True
    assert first.returned_points == 1
    assert first.series[0].unit == "frame"
    assert first.series[0].points[0].value == 120
    assert "raw_file" not in first.series[0].points[0].dimensions
    assert "raw_line_start" not in first.series[0].points[0].dimensions
    assert second.has_more is False
    assert second.series[0].points[0].value is None
    assert second.series[0].points[0].dimensions["metric_name"] == "TxRetryFrmCnt"


def test_business_tables_use_new_keys_active_rows_and_strip_source_fields(tmp_path: Path) -> None:
    service = _service(tmp_path)
    session = _session(service, "business-table")
    db = session / "parsed" / "online_diagnosis.sqlite"
    with sqlite3.connect(db) as conn:
        conn.executescript(
            """
            CREATE TABLE main_link_samples (
                id INTEGER PRIMARY KEY,
                collector_time TEXT,
                device_time TEXT,
                device_clock TEXT,
                radio INTEGER,
                link_state TEXT,
                peer_name TEXT,
                peer_mac TEXT,
                peer_mac_normalized TEXT,
                resolved_peer_name TEXT,
                mr_rssi REAL,
                bssid TEXT,
                mesh_interface TEXT,
                belong_station TEXT,
                belong_section TEXT,
                online_time TEXT,
                raw_file TEXT,
                raw_line_start INTEGER,
                raw_line_end INTEGER
            );
            """
        )
        conn.executemany(
            """
            INSERT INTO main_link_samples VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            [
                (
                    1,
                    "2026-07-13 10:00:00.100",
                    "2026-07-13 10:00:00",
                    "",
                    1,
                    "ACTIVE",
                    "AP-A",
                    "aa-aa-aa-aa-aa-aa",
                    "aaaaaaaaaaaa",
                    "轨旁AP-A",
                    -61,
                    "bb-bb-bb-bb-bb-bb",
                    "WLAN-MeshLink1",
                    "站点A",
                    "区间A",
                    "00h 01m 00s",
                    "raw/mesh_link_raw.log",
                    10,
                    11,
                ),
                (
                    2,
                    "2026-07-13 10:00:00.100",
                    "2026-07-13 10:00:00",
                    "",
                    1,
                    "STANDBY",
                    "AP-B",
                    "cc-cc-cc-cc-cc-cc",
                    "cccccccccccc",
                    "轨旁AP-B",
                    -72,
                    "dd-dd-dd-dd-dd-dd",
                    "WLAN-MeshLink2",
                    "站点B",
                    "区间B",
                    "00h 00m 30s",
                    "raw/mesh_link_raw.log",
                    12,
                    13,
                ),
            ],
        )

    main = service.query_business_table("site-a", "business-table", "main_link")
    alias = service.query_business_table("site-a", "business-table", "mesh_link")
    detail = service.query_business_table("site-a", "business-table", "link_detail")

    assert main.table == "main_link"
    assert alias.table == "main_link"
    assert len(main.rows) == 1
    assert main.rows[0] == {
        "device_time": "2026-07-13 10:00:00",
        "radio": 1,
        "link_state": "ACTIVE",
        "peer_name": "未关联",
        "peer_mac": "aa-aa-aa-aa-aa-aa",
        "canonical_ap_mac": "",
        "identity_status": "unresolved",
        "identity_source": "",
        "identity_reason": "缺少明确 AP MAC 映射",
        "mr_rssi": -61,
        "bssid": "bb-bb-bb-bb-bb-bb",
        "belong_station": "站点A",
        "belong_section": "区间A",
        "online_time": "00h 01m 00s",
    }
    assert [row["link_state"] for row in detail.rows] == ["ACTIVE", "STANDBY"]
    assert all("raw_file" not in row and "raw_line_start" not in row for row in [*main.rows, *detail.rows])
    with pytest.raises(OnlineMrQueryError) as error:
        service.query_business_table("site-a", "business-table", "radio_statistics")
    assert error.value.code == OnlineMrQueryErrorCode.METRIC_UNSUPPORTED


def test_business_projection_uses_matched_mac_like_ap_names_and_switch_endpoints(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    session = _session(service, "identity-business")
    db = session / "parsed" / "online_diagnosis.sqlite"
    with sqlite3.connect(db) as conn:
        conn.executescript(
            """
            CREATE TABLE main_link_samples (
                id INTEGER PRIMARY KEY, device_time TEXT, radio INTEGER,
                link_state TEXT, peer_name TEXT, peer_mac TEXT,
                resolved_peer_name TEXT, canonical_ap_mac TEXT, peer_ap_mac TEXT,
                identity_status TEXT, mr_rssi REAL, belong_station TEXT,
                belong_section TEXT
            );
            CREATE TABLE switch_realtime_events (
                id INTEGER PRIMARY KEY, device_time TEXT, radio INTEGER,
                old_peer_name TEXT, old_peer_mac TEXT, old_rssi REAL,
                old_matched_ap_name TEXT, old_matched_ap_mac TEXT,
                old_belong_station TEXT, old_belong_section TEXT,
                new_peer_name TEXT, new_peer_mac TEXT, new_rssi REAL,
                new_matched_ap_name TEXT, new_matched_ap_mac TEXT,
                new_belong_station TEXT, new_belong_section TEXT,
                switch_reason_text TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO main_link_samples VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                1,
                "2026-07-21 16:00:00",
                1,
                "ACTIVE",
                "bc5a-3457-61e0",
                "bc5a-3457-61ff",
                "bc5a-3457-61e0",
                "bc5a345761e0",
                "bc5a345761e0",
                "matched",
                -45,
                "横溪站",
                None,
            ),
        )
        conn.execute(
            "INSERT INTO switch_realtime_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                1,
                "2026-07-21 16:00:01",
                1,
                "bc5a-3457-61e0",
                "bc5a-3457-61ff",
                -55,
                "bc5a-3457-61e0",
                "bc5a345761e0",
                "横溪站",
                None,
                "bc5a-3457-7080",
                "bc5a-3457-709f",
                -43,
                "bc5a-3457-7080",
                "bc5a34577080",
                "横溪站",
                None,
                "Better RSSI",
            ),
        )

    summary = service.get_business_summary("site-a", "identity-business")
    main = service.query_business_table("site-a", "identity-business", "main_link")
    switches = service.query_business_table(
        "site-a", "identity-business", "switch_realtime"
    )
    windows = service.query_switch_rssi_windows(
        "site-a", "identity-business", "realtime"
    )

    assert summary.current_peer_name == "bc5a-3457-61e0"
    assert main.rows[0]["peer_name"] == "bc5a-3457-61e0"
    assert switches.rows[0]["from_peer_name"] == "bc5a-3457-61e0"
    assert switches.rows[0]["from_peer_mac"] == "bc5a345761e0"
    assert switches.rows[0]["from_peer_radio_mac"] == "bc5a-3457-61ff"
    assert switches.rows[0]["to_station"] == "横溪站"
    assert windows.items[0].old_peer_name == "bc5a-3457-61e0"
    assert windows.items[0].old_peer_mac == "bc5a-3457-61ff"
    assert windows.items[0].old_ap_mac == "bc5a345761e0"
    assert windows.items[0].new_station == "横溪站"


def test_channel_busy_business_and_metrics_keep_every_block_sample(tmp_path: Path) -> None:
    service = _service(tmp_path)
    session = _session(service, "channel-busy-block")
    db = session / "parsed" / "online_diagnosis.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            CREATE TABLE channel_busy_records (
                id INTEGER PRIMARY KEY, device_time TEXT, radio INTEGER,
                ctl_channel INTEGER, bandwidth REAL, channel_band_raw TEXT,
                bandwidth_mhz REAL, record_interval INTEGER, row_index INTEGER,
                ctl_busy REAL, tx_busy REAL, rx_busy REAL
            )
            """
        )
        conn.executemany(
            "INSERT INTO channel_busy_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (1, "2026-07-21 15:58:19", 1, 149, 80, "80M", 80, 9, 1, 7, 5, 1),
                (2, "2026-07-21 15:58:10", 1, 149, 80, "80M", 80, 9, 2, 8, 6, 2),
                (3, "2026-07-21 15:58:01", 1, 149, 80, "80M", 80, 9, 3, 9, 7, 3),
            ],
        )

    page = service.query_business_table(
        "site-a", "channel-busy-block", "channel_busy"
    )
    metrics = service.query_metrics(
        "site-a", "channel-busy-block", [OnlineMrMetricType.CTL_BUSY]
    )

    assert len(page.rows) == 3
    assert {row["channel_band_raw"] for row in page.rows} == {"80M"}
    assert {row["bandwidth_mhz"] for row in page.rows} == {80.0}
    assert sum(len(series.points) for series in metrics) == 3


def test_fping_business_rows_use_natural_second_buckets_and_loss_status(tmp_path: Path) -> None:
    service = _service(tmp_path)
    session = _session(service, "fping-business")
    db = session / "parsed" / "online_diagnosis.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            CREATE TABLE fping_1s_summary (
                id INTEGER PRIMARY KEY,
                bucket_time TEXT,
                local_bucket_time TEXT,
                device_bucket_time TEXT,
                target_ip TEXT,
                sent INTEGER,
                received INTEGER,
                lost INTEGER,
                loss_percent REAL,
                avg_latency_ms REAL,
                min_latency_ms REAL,
                max_latency_ms REAL,
                jitter_ms REAL,
                status TEXT
            )
            """
        )
        conn.executemany(
            "INSERT INTO fping_1s_summary VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (1, "2026-07-13 15:51:02", "2026-07-13 15:51:02", "2026-07-13 15:51:03", "10.0.0.1", 2, 1, 1, 50.0, 2.5, 2.5, 2.5, 0.0, "LOSS"),
                (2, "2026-07-13 15:51:03", "2026-07-13 15:51:03", "2026-07-13 15:51:04", "10.0.0.1", 1, 0, 1, 100.0, None, None, None, None, "LOSS"),
                (3, "2026-07-13 15:51:02", "2026-07-13 15:51:02", "2026-07-13 15:51:03", "10.0.0.2", 1, 1, 0, 0.0, 5.0, 5.0, 5.0, 0.0, "OK"),
            ],
        )

    page = service.query_business_table("site-a", "fping-business", "fping_1s")

    assert [(row["time"], row["target_ip"]) for row in page.rows] == [
        ("2026-07-13 15:51:02", "10.0.0.1"),
        ("2026-07-13 15:51:02", "10.0.0.2"),
        ("2026-07-13 15:51:03", "10.0.0.1"),
    ]
    assert page.rows[0]["device_time"] == "2026-07-13 15:51:03"
    assert page.rows[0]["status"] == "部分丢包"
    assert page.rows[1]["status"] == "正常"
    assert page.rows[2]["status"] == "全部丢包"
    assert page.rows[2]["avg_rtt"] is None
    assert page.rows[2]["min_rtt"] is None
    assert page.rows[2]["max_rtt"] is None


def test_multi_metric_page_caps_total_points_and_advances_shared_offset(tmp_path: Path) -> None:
    service = _service(tmp_path)
    session = _session(service, "multi-metric-page")
    _metric_database(session / "parsed" / "online_diagnosis.sqlite")

    page = service.query_metric_page(
        "site-a",
        "multi-metric-page",
        [OnlineMrMetricType.RSSI, OnlineMrMetricType.CTL_BUSY],
        limit=3,
    )

    assert page.page_size_per_metric == 1
    assert page.next_offset == 1
    assert page.returned_points <= page.limit
    assert page.has_more is True
    legacy = service.query_metrics(
        "site-a",
        "multi-metric-page",
        [OnlineMrMetricType.RSSI, OnlineMrMetricType.CTL_BUSY],
        limit=2,
    )
    assert sum(len(row.points) for row in legacy if row.metric_type == OnlineMrMetricType.RSSI) == 2
    assert sum(len(row.points) for row in legacy if row.metric_type == OnlineMrMetricType.CTL_BUSY) == 2
    with pytest.raises(OnlineMrQueryError, match="不能小于指标数量"):
        service.query_metric_page(
            "site-a",
            "multi-metric-page",
            [OnlineMrMetricType.RSSI, OnlineMrMetricType.CTL_BUSY],
            limit=1,
        )


def test_switch_rssi_windows_are_source_specific_without_raw_evidence(tmp_path: Path) -> None:
    service = _service(tmp_path)
    session = _session(service, "switch-rssi")
    _metric_database(session / "parsed" / "online_diagnosis.sqlite")

    history = service.query_switch_rssi_windows("site-a", "switch-rssi", "history")
    realtime = service.query_switch_rssi_windows("site-a", "switch-rssi", "realtime")

    assert [(row.old_rssi_dbm, row.new_rssi_dbm) for row in history.items] == [(-81, -55)]
    assert [(row.old_rssi_dbm, row.new_rssi_dbm) for row in realtime.items] == [(-77, -49)]
    assert realtime.items[0].radio is None
    assert "raw_file" not in history.items[0].model_dump()
    assert "raw_line_start" not in realtime.items[0].model_dump()
    assert {-60, -70}.isdisjoint({history.items[0].old_rssi_dbm, history.items[0].new_rssi_dbm})
    timeline = service.query_timeline("site-a", "switch-rssi")
    assert {row.source for row in timeline} == {
        "switch_history",
        "switch_realtime",
    }
    assert next(row for row in timeline if row.source == "switch_realtime").payload["radio"] is None


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


def test_summary_and_rssi_metrics_use_mr_device_time_and_trackside_keeps_both_roles(tmp_path: Path) -> None:
    service = _service(tmp_path)
    session = _session(service, "rssi-timeline")
    db = session / "parsed" / "online_diagnosis.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            CREATE TABLE main_link_samples (
                id INTEGER PRIMARY KEY, device_time TEXT, collector_time TEXT, radio INTEGER,
                link_state TEXT, mr_rssi REAL, resolved_peer_name TEXT, peer_mac TEXT,
                canonical_ap_mac TEXT, peer_radio_mac TEXT
            )
            """
        )
        conn.executemany(
            "INSERT INTO main_link_samples VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (1, "2026-07-21 12:00:00", "2026-07-21 12:10:00", 1, "ACTIVE", -61, "AP-A", "0011-2233-4455", "001122334400", "001122334455"),
                (2, "2026-07-21 12:00:01", "2026-07-21 12:10:01", 1, "STANDBY", -72, "AP-A", "0011-2233-4455", "001122334400", "001122334455"),
            ],
        )

    summary = service.get_business_summary("site-a", "rssi-timeline")
    main, trackside = service.query_metrics(
        "site-a",
        "rssi-timeline",
        [OnlineMrMetricType.RSSI, OnlineMrMetricType.TRACKSIDE_RSSI],
    )

    assert summary.first_sample_time == "2026-07-21 12:00:00"
    assert summary.last_sample_time == "2026-07-21 12:00:01"
    assert [point.dimensions["link_state"] for point in main.points] == ["ACTIVE"]
    assert {point.dimensions["link_state"] for point in trackside.points} == {"ACTIVE", "STANDBY"}
    assert {point.raw_timestamp for point in trackside.points} == {
        "2026-07-21 12:00:00",
        "2026-07-21 12:00:01",
    }


def test_external_metrics_realign_old_derived_times_at_query_time_and_keep_raw_timestamp(tmp_path: Path) -> None:
    service = _service(tmp_path)
    session = _session(service, "query-time-alignment")
    db = session / "parsed" / "online_diagnosis.sqlite"
    with sqlite3.connect(db) as conn:
        conn.executescript(
            """
            CREATE TABLE time_sync_samples (
                id INTEGER PRIMARY KEY, collector_time TEXT, device_time TEXT, source TEXT
            );
            CREATE TABLE fping_1s_summary (
                id INTEGER PRIMARY KEY, bucket_time TEXT, local_bucket_time TEXT,
                device_bucket_time TEXT, target_ip TEXT, sent INTEGER, received INTEGER,
                lost INTEGER, loss_percent REAL
            );
            CREATE TABLE iperf_intervals (
                id INTEGER PRIMARY KEY, run_id TEXT, collector_time TEXT,
                interval_center_time TEXT, device_aligned_time TEXT,
                direction TEXT, protocol TEXT, bitrate_mbps REAL
            );
            """
        )
        anchors = []
        collector_start = datetime(2026, 7, 21, 12, 0, 4, 250_000)
        for index in range(20):
            collector = collector_start + timedelta(seconds=index)
            device = collector - timedelta(milliseconds=4_250)
            anchors.append((index + 1, collector.isoformat(sep=" ", timespec="milliseconds"), device.isoformat(sep=" ", timespec="milliseconds"), "mesh_link_display_clock"))
        conn.executemany("INSERT INTO time_sync_samples VALUES (?, ?, ?, ?)", anchors)
        conn.execute(
            "INSERT INTO fping_1s_summary VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, "2026-07-21 12:00:10.250", "2026-07-21 12:00:10.250", "2026-07-21 12:00:50.000", "10.0.0.1", 1, 0, 1, 100.0),
        )
        conn.execute(
            "INSERT INTO iperf_intervals VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (1, "run-1", "2026-07-21 12:00:10.250", "2026-07-21 12:00:10.250", "2026-07-21 12:00:50.000", "downlink", "tcp", 286.0),
        )

    rows = service.query_metrics(
        "site-a",
        "query-time-alignment",
        [OnlineMrMetricType.PING_LOSS, OnlineMrMetricType.IPERF_BITRATE],
        start_time="2026-07-21 12:00:05.500",
        end_time="2026-07-21 12:00:06.500",
    )

    assert {series.metric_type for series in rows} == {
        OnlineMrMetricType.PING_LOSS,
        OnlineMrMetricType.IPERF_BITRATE,
    }
    for series in rows:
        point = series.points[0]
        assert point.timestamp == "2026-07-21 12:00:06.000"
        assert point.normalized_timestamp == "2026-07-21 12:00:06.000"
        assert point.raw_timestamp == "2026-07-21 12:00:10.250"
        assert point.correction_method == "fixed-offset"
        assert point.correction_confidence == "high"


def test_external_metric_without_time_anchor_is_explicitly_low_confidence(tmp_path: Path) -> None:
    service = _service(tmp_path)
    session = _session(service, "missing-alignment")
    db = session / "parsed" / "online_diagnosis.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE fping_samples (id INTEGER PRIMARY KEY, collector_time TEXT, target_ip TEXT, success INTEGER, latency_ms REAL)"
        )
        conn.execute(
            "INSERT INTO fping_samples VALUES (1, '2026-07-21 12:00:10.250', '10.0.0.1', 1, 12.0)"
        )

    rows = service.query_metrics("site-a", "missing-alignment", [OnlineMrMetricType.PING_RTT])
    point = rows[0].points[0]

    assert point.timestamp == "2026-07-21 12:00:10.250"
    assert point.raw_timestamp == "2026-07-21 12:00:10.250"
    assert point.correction_method == "none"
    assert point.correction_confidence == "low"


def test_database_missing_corrupt_and_busy_are_controlled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(tmp_path)
    session = _session(service, "database")
    missing = service.get_database_summary("site-a", "database")
    assert missing.status == "missing"
    assert missing.error_code == OnlineMrQueryErrorCode.DATABASE_NOT_FOUND
    db = session / "parsed" / "online_diagnosis.sqlite"
    db.write_bytes(b"not sqlite")
    corrupt = service.get_database_summary("site-a", "database")
    assert corrupt.status == "unreadable"
    assert corrupt.error_code == OnlineMrQueryErrorCode.DATABASE_CORRUPT
    assert str(tmp_path) not in corrupt.model_dump_json()

    def locked(*args: object, **kwargs: object) -> sqlite3.Connection:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr("netconsole.services.online_mr.query_service.sqlite3.connect", locked)
    with pytest.raises(OnlineMrQueryError) as error:
        service.query_metrics("site-a", "database", [OnlineMrMetricType.RSSI])
    assert error.value.code == OnlineMrQueryErrorCode.DATABASE_BUSY


def test_session_detail_keeps_metadata_when_parsed_database_is_corrupt(tmp_path: Path) -> None:
    service = _service(tmp_path)
    session = _session(service, "corrupt-detail", status="ABORTED")
    (session / "raw" / "mesh_link_raw.log").write_text("partial raw", encoding="utf-8")
    (session / "parsed" / "online_diagnosis.sqlite").write_bytes(b"broken sqlite")

    detail = service.get_session("site-a", "corrupt-detail")

    assert detail.status == "ABORTED"
    assert detail.has_raw_data is True
    assert detail.database_summary.status == "unreadable"
    assert detail.database_summary.action == "force_reparse"
    assert detail.latest_metric_time is None


def test_old_parsed_database_reports_compatible_capabilities_without_writing(tmp_path: Path) -> None:
    service = _service(tmp_path)
    session = _session(service, "legacy-detail")
    db = session / "parsed" / "online_diagnosis.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE main_link_samples (device_time TEXT, mr_rssi REAL)")
    before = {path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*")}

    summary = service.get_database_summary("site-a", "legacy-detail")

    assert summary.status == "legacy"
    assert summary.compatible is True
    assert summary.available_capabilities == ["link_detail", "main_link"]
    assert "channel_busy" in summary.missing_capabilities
    assert {path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*")} == before


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


def test_timeline_pagination_bounds_each_database_source(tmp_path: Path) -> None:
    service = _service(tmp_path)
    session = _session(service, "timeline-page")
    db = session / "parsed" / "online_diagnosis.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE analysis_events (id INTEGER PRIMARY KEY, collector_time TEXT, event_type TEXT, severity TEXT, summary_text TEXT, details_json TEXT)"
        )
        conn.executemany(
            "INSERT INTO analysis_events VALUES (?, ?, 'diagnosis', 'info', ?, '{}')",
            [(index, f"2026-07-13 10:00:{index:02d}", f"event-{index}") for index in range(1, 6)],
        )

    assert [row.title for row in service.query_timeline("site-a", "timeline-page", limit=2, offset=2)] == [
        "event-3",
        "event-4",
    ]


def test_query_service_has_no_qt_dependency() -> None:
    source = Path("src/netconsole/services/online_mr/query_service.py").read_text(encoding="utf-8")
    assert "PySide6" not in source
    assert "QObject" not in source
