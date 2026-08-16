from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event

import pytest

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.online_mr_models import (
    TASK_AP_RADIO_STATISTICS,
    TASK_CHANNEL_BUSY,
    TASK_INTERFACE_RATE,
    TASK_MESH_LINK,
    TASK_SWITCH_HISTORY,
    TASK_WIRELESS_STATUS,
    OnlineMrConnectionConfig,
)
from netconsole.models.task_snapshot import TaskEvent, TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.parsers.mesh_log_parser import sha256_file
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)
from netconsole.repositories.mesh_mr_repository import MeshMrRepository
from netconsole.repositories.task_repository import TaskRepository
from netconsole.services.job_center.task_result_rollout import (
    TaskResultRolloutService,
)
from netconsole.services.ground_unattended.syslog_runtime import RawStreamWriter
from netconsole.services.mesh_import_service import MeshImportService
from netconsole.services.mesh_source_rebuild_service import MeshSourceRebuildService
from netconsole.services.mesh_storage_service import MeshStorageService
from netconsole.services.online_mr_collector import (
    NetmikoShellConnection,
    OnlineMrCollector,
)
from netconsole.services.online_mr.offline.replay_engine import replay_session
from netconsole.services.online_mr_session_store import (
    COLLECTOR_OUTPUT_RAW_FILE,
    DEVICE_TERMINAL_MONITOR_RAW_FILE,
    OnlineMrSessionStore,
)
from netconsole.services.site_storage import SiteApplicationService, SitePackageService
from scripts.maintenance.task_result_maintenance import (
    TaskResultMaintenanceService,
)


MESH_LINE = (
    "[1] Active 30f5-277a-5a2f 2025/12/03 10:12:30 0d 00h 00m 03s 1 "
    "36/43 2%/4% 45%/47% 3/1 15/27 60/72060 88/105 0/5000 2/297 "
    "314/0 0/93 0/0 0/0 0/0"
)


class _OnlineMrConnection:
    def __init__(self) -> None:
        self.closed = False

    def send_command(self, command: str, timeout: int) -> str:
        del timeout
        return MESH_LINE if command == "display wlan mesh-link" else f"{command}\nOK"

    def close(self) -> None:
        self.closed = True


class _OnlineMrRawAuthorityConnection(_OnlineMrConnection):
    AP_STATISTICS = "\n".join(
        f"Radio statistic counter {index}: {index * 17}" for index in range(128)
    )
    CHANNEL_BUSY = (
        "Date/Month/Year: 16/08/2026\n"
        "Ctl Channel: 149 Channel Band: 80M\n"
        "Record Interval(s): 9\n"
        "Time(h/m/s): CtlBusy(%) TxBusy(%) RxBusy(%) ExtBusy(%)\n"
        "01 14:30:00 7 5 1 -"
    )
    INTERFACE_INBOUND = (
        "Inbound interface\n"
        "WLAN-Radio1/0/1 12.5 100 10 20"
    )
    INTERFACE_OUTBOUND = (
        "Outbound interface\n"
        "WLAN-Radio1/0/1 8.5 80 8 16"
    )
    SWITCH_HISTORY = "switch history latest fact"

    def send_command(self, command: str, timeout: int) -> str:
        del timeout
        if command == "display wlan mesh-link":
            return MESH_LINE
        if command.endswith(" channelbusy"):
            return self.CHANNEL_BUSY
        if command.endswith(" statistics"):
            return self.AP_STATISTICS
        if command == "dis counters rate inbound interface":
            return self.INTERFACE_INBOUND
        if command == "dis counters rate outbound interface":
            return self.INTERFACE_OUTBOUND
        if "switch-history" in command:
            return self.SWITCH_HISTORY
        return f"{command}\nOK"


def test_terminal_result_replay_keeps_one_canonical_full_payload(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    paths = PathResolver(app_root=tmp_path, data_root=data_root)
    database = paths.site_tasks_db_path("line-12")
    repository = TaskRepository(database)
    TaskResultRolloutService(database).enable_dual_write(
        expected_revision=1,
        reason="No-Reinflation result fixture",
        updated_by="pytest",
    )
    TaskResultMaintenanceService(
        paths,
        site_id="line-12",
        tasks_database=database,
        development_root=tmp_path,
    ).enable_ref_authority(
        expected_revision=2,
        reason="No-Reinflation result reference authority",
        updated_by="pytest",
        apply=True,
        allow_development_root_only=True,
    )
    result = {
        "status": "COMPLETED",
        "rows": 100,
        "nested": {"source_id": "source-1", "artifact_ref": "artifact-1"},
    }
    snapshot = TaskSnapshot(
        task_id="terminal-replay",
        task_type="mesh_analysis",
        task_name="Terminal Replay",
        status=TaskState.COMPLETED,
        progress=100,
        result=result,
        created_time="2026-08-16T00:00:00Z",
        updated_time="2026-08-16T00:01:00Z",
        finished_time="2026-08-16T00:01:00Z",
    )
    for index in range(100):
        event = TaskEvent(
            event_id=f"terminal-replay-{index}",
            task_id=snapshot.task_id,
            type="finished",
            time=f"2026-08-16T00:01:{index % 60:02d}Z",
            source="worker",
            payload={"message": "done", "result": result},
        )
        assert repository.record(snapshot, event)

    with sqlite3.connect(database) as connection:
        result_rows = connection.execute(
            "SELECT canonical_json, byte_size FROM task_results"
        ).fetchall()
        snapshot_result = connection.execute(
            "SELECT result_json FROM task_snapshots WHERE task_id=?",
            (snapshot.task_id,),
        ).fetchone()
        event_payloads = [
            json.loads(str(row[0]))
            for row in connection.execute(
                "SELECT payload_json FROM task_events WHERE task_id=? ORDER BY sequence",
                (snapshot.task_id,),
            ).fetchall()
        ]
    assert len(result_rows) == 1
    assert result_rows[0][1] == len(str(result_rows[0][0]).encode("utf-8"))
    assert snapshot_result == ("{}",)
    assert len(event_payloads) == 100
    assert all("result" not in payload and payload["result_id"] for payload in event_payloads)
    restored = TaskRepository(database).get(snapshot.task_id)
    assert restored is not None and restored.result == result


@pytest.mark.parametrize("replay_count", [100, 1_000, 10_000])
def test_ground_current_state_replay_is_cardinality_bounded(
    tmp_path: Path,
    replay_count: int,
) -> None:
    database = tmp_path / f"ground-{replay_count}.db"
    repository = GroundUnattendedRepository(database, site_id="line-12")
    train_state = {
        "train_id": "train-01",
        "train_no": "01",
        "train_name": "Train 01",
        "coverage_status": "COVERED",
        "current_ap_name": "AP-01",
        "current_ap_mac": "4873-97cc-e9af",
        "station": "station-01",
        "section": "section-01",
        "rssi": -55,
        "same_ap_duration_seconds": 30,
    }
    radio_state = {
        "device_uuid": "mr-01",
        "train_id": "train-01",
        "mr_role": "CT",
        "interface_name": "WLAN-Radio1/0/1",
        "current_state": "UP",
        "stable_state": "UP",
        "previous_state": "UP",
        "transition_count_5m": 0,
    }
    for _ in range(replay_count):
        repository.upsert_train_state(
            "run-20260816",
            "2026-08-16",
            train_state,
            ap_identity="ap-identity-01",
            same_ap_since="2026-08-16T00:00:00Z",
        )
        repository.upsert_radio_interface_state(radio_state)

    current = repository.get_train_run("run-20260816", "train-01")
    radio = repository.get_radio_interface_state(
        "mr-01", "WLAN-Radio1/0/1"
    )
    assert current is not None and current["current_ap_identity"] == "ap-identity-01"
    assert radio is not None and radio["current_state"] == "UP"
    with sqlite3.connect(database) as connection:
        counts = {
            table: int(
                connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            )
            for table in (
                "ground_unattended_train_runs",
                "ground_unattended_radio_interface_states",
                "ground_unattended_events",
                "ground_unattended_ac_snapshots",
            )
        }
    assert counts == {
        "ground_unattended_train_runs": 1,
        "ground_unattended_radio_interface_states": 1,
        "ground_unattended_events": 0,
        "ground_unattended_ac_snapshots": 0,
    }


def test_online_mr_long_replay_keeps_one_raw_payload_authority(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path / "data")
    profile = MeshStorageService("line-12", paths).create_mr_profile("Train 01 MR CT")
    config = OnlineMrConnectionConfig(
        site="line-12",
        mr_id=profile.mr_id,
        mr_name=profile.display_name,
        safe_mr_name=profile.safe_folder_name,
        device_id=1,
        device_name="MR-CT-01",
        host="192.0.2.10",
        username="test-user",
        password="test-password",
        reconnect_interval=0,
    )
    connection = _OnlineMrConnection()
    collector = OnlineMrCollector(
        config,
        OnlineMrSessionStore(paths),
        connection_factory=lambda _config: connection,
        sleeper=lambda _seconds: None,
    )
    collector.start()
    assert collector.run_once(TASK_MESH_LINK) == 1
    for expected_sample_id in range(2, 1_001):
        assert collector.run_once(TASK_MESH_LINK) == expected_sample_id
    session = collector.session
    assert session is not None
    collector.stop()

    mesh_raw = session.session_dir / "raw" / "mesh_link_raw.log"
    collector_raw = session.session_dir / "raw" / COLLECTOR_OUTPUT_RAW_FILE
    terminal_raw = session.session_dir / "raw" / DEVICE_TERMINAL_MONITOR_RAW_FILE
    mesh_text = mesh_raw.read_text(encoding="utf-8")
    assert mesh_text.count(MESH_LINE) == 1_000
    assert MESH_LINE not in collector_raw.read_text(encoding="utf-8")
    assert MESH_LINE not in terminal_raw.read_text(encoding="utf-8")
    with sqlite3.connect(session.db_path) as database:
        samples = database.execute(
            "SELECT raw_file, raw_offset_start, raw_offset_end, "
            "raw_content_sha256, raw_source_id "
            "FROM live_samples ORDER BY id"
        ).fetchall()
        assert int(
            database.execute("SELECT COUNT(*) FROM live_mesh_links").fetchone()[0]
        ) == 1_000
        assert database.execute(
            "SELECT COUNT(*) FROM live_channel_busy"
        ).fetchone() == (0,)
        assert database.execute(
            "SELECT COUNT(*) FROM live_radio_statistics_raw_index"
        ).fetchone() == (0,)
    assert len(samples) == 1_000
    assert {str(row[0]) for row in samples} == {"raw/mesh_link_raw.log"}
    assert int(samples[0][1]) == 0
    assert all(
        int(current[1]) == int(previous[2])
        for previous, current in zip(samples, samples[1:])
    )
    assert int(samples[-1][2]) == mesh_raw.stat().st_size
    with mesh_raw.open("rb") as raw_file:
        for raw_file_name, start, end, content_sha256, source_id in samples:
            assert raw_file_name == "raw/mesh_link_raw.log"
            raw_file.seek(int(start))
            payload = raw_file.read(int(end) - int(start))
            assert hashlib.sha256(payload).hexdigest() == content_sha256
            assert str(source_id).startswith("online-mr:")
    assert connection.closed is True


def test_online_mr_offline_replay_is_source_idempotent(tmp_path: Path) -> None:
    session_dir = tmp_path / "offline-session"
    raw_dir = session_dir / "raw"
    raw_dir.mkdir(parents=True)
    (session_dir / "parsed").mkdir()
    (raw_dir / "fping_v5_samples.jsonl").write_text(
        '{"ts":"2026-08-16T10:00:00.123","target":"192.0.2.1",'
        '"seq":1,"ok":true,"rtt_ms":1.25,"timeout_ms":100,'
        '"raw":{"resp":{"host":"192.0.2.1","seq":1,"rtt":1.25}}}\n',
        encoding="utf-8",
    )
    (raw_dir / "iperf3.json").write_text(
        json.dumps(
            {"end": {"sum_received": {"bits_per_second": 80_000_000}}},
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    first = replay_session(session_dir, session_id="offline-1", device_id=7)
    database_path = session_dir / "parsed" / "online_diagnosis.sqlite"
    first_size = database_path.stat().st_size
    for _ in range(99):
        current = replay_session(session_dir, session_id="offline-1", device_id=7)
        assert current.events == first.events

    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            "SELECT raw, raw_file, raw_sha256, source_identity "
            "FROM event_stream ORDER BY id"
        ).fetchall()
    assert first.events == 2
    assert len(rows) == 2
    assert {str(row[1]) for row in rows} == {
        "fping_v5_samples.jsonl",
        "iperf3.json",
    }
    assert all(row[0] is None for row in rows)
    assert all(len(str(row[2])) == 64 and len(str(row[3])) == 64 for row in rows)
    assert database_path.stat().st_size == first_size


def test_online_mr_slow_collectors_keep_raw_authority_and_bounded_current_state(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path / "data")
    profile = MeshStorageService("line-12", paths).create_mr_profile("Train 01 MR CT")
    config = OnlineMrConnectionConfig(
        site="line-12",
        mr_id=profile.mr_id,
        mr_name=profile.display_name,
        safe_mr_name=profile.safe_folder_name,
        device_id=1,
        device_name="MR-CT-01",
        host="192.0.2.10",
        username="test-user",
        password="test-password",
        reconnect_interval=0,
    )
    collector = OnlineMrCollector(
        config,
        OnlineMrSessionStore(paths),
        connection_factory=lambda _config: _OnlineMrRawAuthorityConnection(),
        sleeper=lambda _seconds: None,
    )
    collector.start()
    replay_count = 100
    append_only_tasks = (
        TASK_CHANNEL_BUSY,
        TASK_AP_RADIO_STATISTICS,
        TASK_INTERFACE_RATE,
        TASK_WIRELESS_STATUS,
    )
    for _ in range(replay_count):
        for task_type in (*append_only_tasks, TASK_SWITCH_HISTORY):
            assert collector.run_once(task_type) > 0
    session = collector.session
    assert session is not None
    collector.stop()

    with sqlite3.connect(session.db_path) as database:
        database.row_factory = sqlite3.Row
        samples = database.execute(
            "SELECT task_type, raw_file, raw_offset_start, raw_offset_end, "
            "raw_content_sha256, raw_source_id FROM live_samples ORDER BY id"
        ).fetchall()
        sample_counts = {
            str(row[0]): int(row[1])
            for row in database.execute(
                "SELECT task_type, COUNT(*) FROM live_samples GROUP BY task_type"
            ).fetchall()
        }
        assert sample_counts == {
            TASK_AP_RADIO_STATISTICS: replay_count,
            TASK_CHANNEL_BUSY: replay_count,
            TASK_INTERFACE_RATE: replay_count,
            TASK_SWITCH_HISTORY: 1,
            TASK_WIRELESS_STATUS: replay_count,
        }
        assert int(
            database.execute(
                "SELECT COUNT(*) FROM live_radio_statistics_raw_index"
            ).fetchone()[0]
        ) == 0
        assert tuple(
            database.execute(
                "SELECT COUNT(*), COUNT(raw_text) FROM live_channel_busy"
            ).fetchone()
        ) == (replay_count, 0)
        assert tuple(
            database.execute(
                "SELECT COUNT(*), COUNT(raw_line), COUNT(raw_text) "
                "FROM live_interface_rates"
            ).fetchone()
        ) == (replay_count * 2, 0, 0)
        assert int(
            database.execute(
                "SELECT COUNT(*) FROM live_switch_history_latest"
            ).fetchone()[0]
        ) == 1

    assert len({str(row["raw_source_id"]) for row in samples}) == len(samples)
    for row in samples:
        raw_path = session.session_dir / str(row["raw_file"])
        start = int(row["raw_offset_start"])
        end = int(row["raw_offset_end"])
        with raw_path.open("rb") as raw_file:
            raw_file.seek(start)
            payload = raw_file.read(end - start)
        assert payload
        assert hashlib.sha256(payload).hexdigest() == row["raw_content_sha256"]
        assert str(row["raw_source_id"]).startswith("online-mr:")

    assert _OnlineMrRawAuthorityConnection.AP_STATISTICS in (
        session.session_dir / "raw" / "ap_radio_statistics_raw.log"
    ).read_text(encoding="utf-8")
    assert _OnlineMrRawAuthorityConnection.AP_STATISTICS not in session.db_path.read_bytes().decode(
        "utf-8",
        errors="ignore",
    )
    switch_latest = session.session_dir / "raw" / "switch_history_latest.log"
    switch_text = switch_latest.read_text(encoding="utf-8")
    assert switch_text.rstrip().endswith(_OnlineMrRawAuthorityConnection.SWITCH_HISTORY)
    assert switch_text.count(_OnlineMrRawAuthorityConnection.SWITCH_HISTORY) == 1


def test_online_mr_authority_schema_upgrade_preserves_legacy_raw_columns(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path / "data")
    profile = MeshStorageService("line-12", paths).create_mr_profile("Train 01 MR CT")
    config = OnlineMrConnectionConfig(
        site="line-12",
        mr_id=profile.mr_id,
        mr_name=profile.display_name,
        safe_mr_name=profile.safe_folder_name,
        device_id=1,
        device_name="MR-CT-01",
        host="192.0.2.10",
        username="test-user",
        password="test-password",
    )
    session = OnlineMrSessionStore(paths).create_session(config)
    with sqlite3.connect(session.db_path) as database:
        database.execute("DROP TABLE live_samples")
        database.execute(
            """
            CREATE TABLE live_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                task_type TEXT NOT NULL,
                collected_at TEXT NOT NULL,
                device_clock TEXT,
                command_group TEXT NOT NULL,
                raw_file TEXT NOT NULL,
                raw_offset_start INTEGER NOT NULL,
                raw_offset_end INTEGER NOT NULL,
                parse_status TEXT NOT NULL,
                error_message TEXT DEFAULT ''
            )
            """
        )
        database.execute(
            "INSERT INTO live_samples (session_id, task_type, collected_at, "
            "command_group, raw_file, raw_offset_start, raw_offset_end, parse_status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session.meta.session_id,
                TASK_AP_RADIO_STATISTICS,
                "2026-08-16 14:30:00.123",
                "display ar5drv 1 statistics",
                "raw/ap_radio_statistics_raw.log",
                0,
                0,
                "OK",
            ),
        )
        database.execute(
            "INSERT INTO live_radio_statistics_raw_index (sample_id, raw_text) "
            "VALUES (1, 'legacy AP raw')"
        )
        database.execute(
            "INSERT INTO live_channel_busy (sample_id, raw_text) "
            "VALUES (1, 'legacy channel summary')"
        )
        database.execute(
            "INSERT INTO live_interface_rates (sample_id, raw_line, raw_text) "
            "VALUES (1, 'legacy interface row', 'legacy interface row')"
        )

    session.initialize_database()

    with sqlite3.connect(session.db_path) as database:
        columns = {
            str(row[1])
            for row in database.execute("PRAGMA table_info(live_samples)").fetchall()
        }
        assert {"raw_content_sha256", "raw_source_id"}.issubset(columns)
        assert database.execute(
            "SELECT raw_content_sha256, raw_source_id FROM live_samples WHERE id=1"
        ).fetchone() == ("", "")
        assert database.execute(
            "SELECT raw_text FROM live_radio_statistics_raw_index WHERE sample_id=1"
        ).fetchone() == ("legacy AP raw",)
        assert database.execute(
            "SELECT raw_text FROM live_channel_busy WHERE sample_id=1"
        ).fetchone() == ("legacy channel summary",)
        assert database.execute(
            "SELECT raw_line, raw_text FROM live_interface_rates WHERE sample_id=1"
        ).fetchone() == ("legacy interface row", "legacy interface row")


def test_online_mr_repeat_stream_publishes_durable_raw_range_before_database_fact(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path / "data")
    profile = MeshStorageService("line-12", paths).create_mr_profile("Train 01 MR CT")
    config = OnlineMrConnectionConfig(
        site="line-12",
        mr_id=profile.mr_id,
        mr_name=profile.display_name,
        safe_mr_name=profile.safe_folder_name,
        device_id=1,
        device_name="MR-CT-01",
        host="192.0.2.10",
        username="test-user",
        password="test-password",
    )
    store = OnlineMrSessionStore(paths)
    collector = OnlineMrCollector(
        config,
        store,
        connection_factory=lambda _config: _OnlineMrConnection(),
        sleeper=lambda _seconds: None,
    )
    collector.session = store.create_session(config)
    stop_event = Event()

    class _InteractiveConnection:
        def __init__(self) -> None:
            self.read_count = 0

        def write_channel(self, _text: str) -> None:
            return None

        def read_channel(self) -> str:
            self.read_count += 1
            if self.read_count == 1:
                return f"{MESH_LINE}\n"
            stop_event.set()
            return ""

        def disconnect(self) -> None:
            return None

    shell = object.__new__(NetmikoShellConnection)
    shell.connection = _InteractiveConnection()
    shell._tunnel_session = None
    raw_path = collector.session.session_dir / "raw" / "mesh_link_raw.log"
    shell.run_repeat_stream(
        ("display wlan mesh-link",),
        raw_path,
        stop_event,
        timeout=1,
        persisted_line_callback=lambda stamp, line, start, end: collector._persist_stream_line(
            TASK_MESH_LINK,
            stamp,
            line,
            "raw/mesh_link_raw.log",
            start,
            end,
        ),
    )

    with sqlite3.connect(collector.session.db_path) as database:
        sample = database.execute(
            "SELECT raw_offset_start, raw_offset_end, raw_content_sha256, "
            "raw_source_id FROM live_samples"
        ).fetchone()
        assert sample is not None
        assert database.execute(
            "SELECT COUNT(*) FROM live_mesh_links"
        ).fetchone() == (1,)
    start, end, content_sha256, source_id = sample
    with raw_path.open("rb") as raw_file:
        raw_file.seek(int(start))
        payload = raw_file.read(int(end) - int(start))
    assert MESH_LINE.encode("utf-8") in payload
    assert hashlib.sha256(payload).hexdigest() == content_sha256
    assert str(source_id).startswith("online-mr:")


def test_ground_ping_syslog_growth_preserves_raw_facts_and_bounds_projections(
    tmp_path: Path,
) -> None:
    root = tmp_path / "ground"
    repository = GroundUnattendedRepository(root / "index.sqlite", site_id="line-12")
    active = root / "active" / "2026-08-16"
    ping_writer = RawStreamWriter(
        root=active,
        repository=repository,
        site_id="line-12",
        run_id="run-20260816",
        run_date="2026-08-16",
        data_type="ping",
        directory_name="fleet_ping",
        flush_records=100,
    )
    syslog_writer = RawStreamWriter(
        root=active,
        repository=repository,
        site_id="line-12",
        run_id="run-20260816",
        run_date="2026-08-16",
        data_type="syslog",
        directory_name="syslog",
        flush_records=100,
    )
    started = datetime(2026, 8, 16, tzinfo=UTC)
    raw_syslog = (
        "%Aug 16 00:00:00:000 2026 MR-CT-01 IFNET/3/PHY_UPDOWN: "
        "Physical state on WLAN-Radio1/0/1 changed to up."
    )
    for index in range(1_000):
        observed_at = started + timedelta(milliseconds=index)
        ping_writer.write(
            {
                "sample_id": f"ping-{index}",
                "train_id": "train-01",
                "mr_role": "CT",
                "seq": index,
                "rtt_ms": 10.123 + index / 10_000,
                "ok": True,
            },
            observed_at,
        )
        raw_file_id, raw_line_number = syslog_writer.write(
            {
                "train_id": "train-01",
                "mr_role": "CT",
                "global_receive_sequence": index + 1,
                "source_receive_sequence": index + 1,
                "raw_text": raw_syslog,
            },
            observed_at,
        )
        saved, inserted = repository.record_control_syslog_event(
            {
                "run_id": "run-20260816",
                "device_uuid": "mr-ct-01",
                "train_id": "train-01",
                "mr_role": "CT",
                "event_type": "IFNET_PHY_UP",
                "event_family": "IFNET",
                "device_time": "2026-08-16T00:00:00+00:00",
                "receive_time": observed_at.isoformat(timespec="milliseconds"),
                "event_time": "2026-08-16T00:00:00+00:00",
                "event_time_source": "DEVICE_CLOCK",
                "raw_file_id": raw_file_id,
                "raw_line_number": raw_line_number,
                "dedup_key": "stable-syslog-event",
                "interface_name": "WLAN-Radio1/0/1",
                "interface_type": "RADIO",
                "physical_state": "UP",
                "details": {"source": "syslog"},
            }
        )
        assert inserted is (index == 0)
        assert int(saved["duplicate_count"]) == index
    assert ping_writer.close() == 1
    assert syslog_writer.close() == 1

    repository.upsert_ping_summary(
        {
            "site_id": "line-12",
            "run_id": "run-20260816",
            "bucket_kind": "daily",
            "bucket_start": "2026-08-16T00:00:00+00:00",
            "bucket_end": "2026-08-17T00:00:00+00:00",
            "target_ip": "192.0.2.10",
            "train_id": "train-01",
            "mr_id": "mr-ct-01",
            "ap_identity": "ap-01",
            "raw_sample_count": 1_000,
            "sent_count": 1_000,
            "success_count": 1_000,
            "created_at": "2026-08-16T00:00:00+00:00",
        }
    )
    summaries = repository.list_ping_summaries("run-20260816")
    assert len(summaries) == 1
    assert summaries[0]["raw_sample_count"] == summaries[0]["success_count"] == 1_000
    raw_files = repository.list_raw_files_for_run("run-20260816")
    assert len(raw_files) == 2
    assert {row["data_type"]: row["record_count"] for row in raw_files} == {
        "ping": 1_000,
        "syslog": 1_000,
    }
    payloads_by_type: dict[str, list[dict[str, object]]] = {}
    for row in raw_files:
        path = repository.db_path.parent / str(row["relative_path"])
        payloads_by_type[str(row["data_type"])] = [
            json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
        ]
    assert len(payloads_by_type["ping"]) == 1_000
    assert payloads_by_type["ping"][0]["rtt_ms"] == 10.123
    assert payloads_by_type["ping"][-1]["rtt_ms"] == pytest.approx(10.2229)
    assert len({row["sample_id"] for row in payloads_by_type["ping"]}) == 1_000
    assert len(payloads_by_type["syslog"]) == 1_000
    assert all(row["raw_text"] == raw_syslog for row in payloads_by_type["syslog"])
    structured = repository.list_control_events(
        device_uuid="mr-ct-01", run_id="run-20260816"
    )
    assert len(structured) == 1 and structured[0]["duplicate_count"] == 999


@pytest.mark.parametrize("replay_count", [100, 1_000, 10_000])
def test_device_lldp_ap_association_replay_records_only_semantic_change(
    tmp_path: Path,
    replay_count: int,
) -> None:
    database = Database(tmp_path / f"devices-{replay_count}.db")
    database.initialize()
    repository = DeviceFactRepository(database)
    unchanged = {
        "local_interface": "GigabitEthernet1/0/1",
        "neighbor_sysname": "AP-01",
        "neighbor_mac": "4873-97cc-e9af",
        "neighbor_interface": "WLAN-Radio1/0/1",
        "neighbor_device_uuid": "ap-01",
        "collected_at": "2026-08-16T00:00:00+00:00",
    }
    for _ in range(replay_count):
        repository.replace_lldp_neighbors(
            "switch-01",
            [unchanged],
            preserve_existing=False,
        )

    current = repository.list_lldp_neighbors("switch-01")
    history = repository.list_lldp_history(
        "switch-01", "GigabitEthernet1/0/1"
    )
    with database.connect() as connection:
        before_counts = {
            "current": int(
                connection.execute(
                    "SELECT COUNT(*) FROM device_lldp_neighbors WHERE device_uuid=?",
                    ("switch-01",),
                ).fetchone()[0]
            ),
            "pending_history": int(
                connection.execute(
                    "SELECT COUNT(*) FROM history_outbox "
                    "WHERE kind='device_lldp' AND entity_key=?",
                    ("switch-01:GigabitEthernet1/0/1",),
                ).fetchone()[0]
            ),
            "state": int(
                connection.execute(
                    "SELECT COUNT(*) FROM history_state "
                    "WHERE kind='device_lldp' AND entity_key=?",
                    ("switch-01:GigabitEthernet1/0/1",),
                ).fetchone()[0]
            ),
        }
    assert before_counts == {"current": 1, "pending_history": 1, "state": 1}
    assert len(current) == len(history) == 1
    assert current[0]["neighbor_device_uuid"] == history[0]["neighbor_device_uuid"] == (
        "ap-01"
    )

    changed = {
        **unchanged,
        "neighbor_sysname": "AP-02",
        "neighbor_mac": "4873-97cc-e9bf",
        "neighbor_device_uuid": "ap-02",
        "collected_at": "2026-08-16T00:01:00+00:00",
    }
    repository.replace_lldp_neighbors(
        "switch-01",
        [changed],
        preserve_existing=False,
    )
    current_after = repository.list_lldp_neighbors("switch-01")
    history_after = repository.list_lldp_history(
        "switch-01", "GigabitEthernet1/0/1"
    )
    assert len(current_after) == 1 and current_after[0]["neighbor_device_uuid"] == "ap-02"
    assert [row["neighbor_device_uuid"] for row in history_after] == ["ap-02", "ap-01"]
    with database.connect() as connection:
        assert int(
            connection.execute(
                "SELECT COUNT(*) FROM history_outbox "
                "WHERE kind='device_lldp' AND entity_key=?",
                ("switch-01:GigabitEthernet1/0/1",),
            ).fetchone()[0]
        ) == 2


def test_mesh_repeat_import_and_reparse_keep_one_source_authority(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path / "data")
    storage = MeshStorageService("line-12", paths)
    profile = storage.create_mr_profile("Train 01 MR CT")
    source = tmp_path / "meshlog.log"
    source.write_text(
        f"[1] 2025/12/03 10:12:30.579 (3)\n{MESH_LINE}\n",
        encoding="utf-8",
    )
    importer = MeshImportService("line-12", paths)

    imports = [importer.import_files(profile, [source]) for _ in range(10)]
    repository = MeshMrRepository(
        paths.mesh_mr_db_path("line-12", profile.safe_folder_name)
    )
    source_rows = repository.list_source_files()
    assert (imports[0].imported_count, imports[0].duplicate_count) == (1, 0)
    assert all(
        (result.imported_count, result.duplicate_count) == (0, 1)
        for result in imports[1:]
    )
    assert len(source_rows) == 1

    source_row = source_rows[0]
    raw = Path(str(source_row["archived_path"]))
    detail = Path(str(source_row["parsed_db_path"]))
    raw_hash = sha256_file(raw)
    initial_summary = MeshMrRepository(detail).summary()
    session_id = f"{profile.mr_id}:{source_row['id']}"
    for _ in range(10):
        rebuilt = MeshSourceRebuildService(paths).rebuild_source(
            "line-12",
            session_id,
            force_reparse=True,
        )
        assert rebuilt["recovery_source"] == "raw_reparse"

    refreshed = repository.list_source_files()
    assert len(refreshed) == 1
    assert sha256_file(raw) == raw_hash
    assert Path(str(refreshed[0]["parsed_db_path"])) == detail
    assert MeshMrRepository(detail).summary()["link_record_count"] == (
        initial_summary["link_record_count"]
    )
    raw_files = [path for path in raw.parent.parent.parent.rglob("*") if path.is_file()]
    parsed_files = [
        path
        for path in detail.parent.iterdir()
        if path.is_file() and path.suffix in {".db", ".sqlite", ".sqlite3"}
    ]
    assert len(raw_files) == 1
    assert parsed_files == [detail]


def test_site_package_cancel_cleans_staging_and_preserves_source(
    tmp_path: Path,
) -> None:
    app_root = tmp_path / "app"
    app_root.mkdir()
    paths = PathResolver(app_root=app_root, data_root=tmp_path / "data")
    sites = SiteApplicationService(paths)
    sites.create_site("line-12", "Line 12")
    source_database = paths.site_db_path("line-12")
    source_size = source_database.stat().st_size
    destination = tmp_path / "cancelled.ncsite"
    cancel_checks = 0

    def cancel_export() -> None:
        nonlocal cancel_checks
        cancel_checks += 1
        raise RuntimeError("simulated package cancellation")

    with pytest.raises(RuntimeError, match="cancellation"):
        SitePackageService(paths, sites).export_site(
            "line-12",
            destination,
            check_cancel=cancel_export,
        )

    assert cancel_checks == 1
    assert source_database.is_file() and source_database.stat().st_size == source_size
    with sqlite3.connect(source_database) as connection:
        assert connection.execute("PRAGMA quick_check").fetchone() == ("ok",)
    assert not destination.exists()
    assert not list(destination.parent.glob(f".{destination.name}.*.tmp"))
    assert paths.temp_dir.is_dir()
    assert not list(paths.temp_dir.glob("netconsole-site-export-*"))
