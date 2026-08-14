from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from netconsole.backend.api.main import create_app
from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.api.ground_unattended import GroundPingSeriesDTO
from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)
from netconsole.repositories.ac_repository import AcRepository
from netconsole.services.ap_identity import ApIdentityQueryService
from netconsole.services.ground_unattended.archive_reader import (
    GroundArchiveReadError,
    GroundArchiveReader,
)
from netconsole.services.ground_unattended.archive_service import (
    GroundUnattendedArchiveService,
)
from netconsole.services.ground_unattended.application_service import (
    GroundUnattendedApplicationService,
)
from netconsole.services.ground_unattended.identity import (
    encode_ping_query_identity,
)
from netconsole.services.ground_unattended.raw_query import (
    GroundRawQueryError,
    GroundRawStreamQueryService,
)


START = "2026-07-25T07:00:00+08:00"
END = "2026-07-25T23:00:00+08:00"


def test_ready_archive_is_queryable_and_mixed_sources_are_deduplicated(
    tmp_path: Path,
) -> None:
    paths, repository, run_id = _setup_run(tmp_path)
    active = paths.ground_unattended_active_dir("site-a", "2026-07-25")
    first = active / "fleet_ping" / "ping-a.jsonl"
    second = active / "fleet_ping" / "ping-b.jsonl"
    _register_ping_file(
        repository,
        first,
        file_id="raw-a",
        run_id=run_id,
        sample_id="sample-a",
        ts="2026-07-25T08:00:00+08:00",
    )
    _register_ping_file(
        repository,
        second,
        file_id="raw-b",
        run_id=run_id,
        sample_id="sample-b",
        ts="2026-07-25T08:01:00+08:00",
    )
    query = GroundRawStreamQueryService(repository)
    active_result = query.ping_series(run_id=run_id)
    assert active_result["raw_sample_count"] == 2
    assert active_result["diagnostics"]["source_kind"] == "ACTIVE"

    archive_result = GroundUnattendedArchiveService(
        paths, site_id="site-a", repository=repository
    ).archive_run(run_id, repository.get_profile())
    assert archive_result.success
    assert not active.exists()

    archived_result = query.ping_series(run_id=run_id)
    assert archived_result["raw_sample_count"] == 2
    assert archived_result["diagnostics"]["source_kind"] == "ARCHIVE"
    assert (
        archived_result["diagnostics"]["data_availability"]
        == "ARCHIVED_RAW"
    )
    assert all(
        item["data_source"] == "ARCHIVE"
        for item in archived_result["points"]
    )

    inspection = query.archive_reader.inspect_archive(archive_result.archive_id)
    with zipfile.ZipFile(inspection.path) as archive:
        first.parent.mkdir(parents=True, exist_ok=True)
        first.write_bytes(archive.read("fleet_ping/ping-a.jsonl"))
    mixed_result = query.ping_series(run_id=run_id)
    assert mixed_result["raw_sample_count"] == 2
    assert mixed_result["diagnostics"]["source_kind"] == "MIXED"
    assert {item["sample_id"] for item in mixed_result["points"]} == {
        "sample-a",
        "sample-b",
    }


def test_ping_transition_marker_projects_wmesh_event_and_real_rssi_evidence(
    tmp_path: Path,
) -> None:
    paths, repository, run_id = _setup_run(tmp_path)
    raw_path = paths.ground_unattended_active_dir("site-a", "2026-07-25") / "fleet_ping" / "ping.jsonl"
    _register_ping_file(
        repository,
        raw_path,
        file_id="raw-ping",
        run_id=run_id,
        sample_id="sample-ping",
        ts="2026-07-25T08:00:00+08:00",
    )
    repository.record_control_syslog_event(
        {
            "run_id": run_id,
            "device_uuid": "mr-ct",
            "train_id": "train-1",
            "mr_role": "CT",
            "event_type": "MESH_ACTIVELINK_SWITCH",
            "event_family": "WMESH",
            "receive_time": "2026-07-25T08:00:00.500+08:00",
            "event_time": "2026-07-25T08:00:00.500+08:00",
            "peer_mac": "bc5a-3457-a0cf",
            "previous_peer_mac": "bc5a.3457.655f",
            "station": "大徐站",
            "section": "大徐-下一站",
            "raw_file_id": "syslog-raw",
            "raw_line_number": 18,
            "dedup_key": "switch-evidence",
            "details": {
                "old_peer_mac": "bc5a.3457.655f",
                "new_peer_mac": "bc5a-3457-a0cf",
                "old_rssi": -67,
                "new_rssi": -72,
                "previous_peer_ap_id": "old-ap",
                "previous_peer_ap_name": "AP-OLD",
                "previous_peer_ap_mac": "bc:5a:34:57:65:50",
                "previous_station": "大徐站",
                "peer_ap_id": "new-ap",
                "peer_ap_name": "AP-NEW",
                "peer_ap_mac": "bc:5a:34:57:a0:c0",
                "identity_status": "matched",
                "identity_source": "base_data",
                "identity_revision": 7,
                "source_receive_sequence": 42,
            },
        }
    )

    result = GroundRawStreamQueryService(repository).ping_series(run_id=run_id)

    assert len(result["ap_transitions"]) == 1
    marker = result["ap_transitions"][0]
    assert marker["event_type"] == "MESH_ACTIVELINK_SWITCH"
    assert marker["old_ap_name"] == "AP-OLD"
    assert marker["new_ap_name"] == "AP-NEW"
    assert marker["old_ap_raw"] == "bc5a.3457.655f"
    assert marker["new_ap_mac"] == "bc:5a:34:57:a0:c0"
    assert marker["rssi_before"] == -67
    assert marker["rssi_before_delta_ms"] == 0
    assert marker["rssi_after"] == -72
    assert marker["raw_file_id"] == "syslog-raw"
    assert marker["source_sequence"] == 42


def test_ping_transition_marker_pushes_identity_before_20k_limit(
    tmp_path: Path,
) -> None:
    paths, repository, run_id = _setup_run(tmp_path)
    raw_path = (
        paths.ground_unattended_active_dir("site-a", "2026-07-25")
        / "fleet_ping"
        / "ping-scale.jsonl"
    )
    _register_ping_file(
        repository,
        raw_path,
        file_id="raw-ping-scale",
        run_id=run_id,
        sample_id="sample-scale",
        ts="2026-07-25T08:00:00+08:00",
    )
    base = datetime.fromisoformat("2026-07-25T08:00:00+08:00")
    insert_sql = """
        INSERT INTO ground_unattended_wmesh_events(
            site_id, run_id, device_uuid, train_id, mr_role, event_type,
            receive_time, event_family, event_time, dedup_key, details_json,
            created_at
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    rows = [
        (
            "site-a",
            run_id,
            "mr-ct",
            "train-1",
            "CT",
            "MESH_ACTIVELINK_SWITCH",
            base.isoformat(timespec="milliseconds"),
            "WMESH",
            base.isoformat(timespec="milliseconds"),
            "target-switch",
            json.dumps({"peer_ap_name": "AP-TARGET"}),
            base.isoformat(timespec="milliseconds"),
        )
    ]
    rows.extend(
        (
            "site-a",
            run_id,
            "mr-ct",
            "train-1",
            "CT",
            "MESH_LINKUP",
            (base + timedelta(milliseconds=index + 1)).isoformat(
                timespec="milliseconds"
            ),
            "WMESH",
            (base + timedelta(milliseconds=index + 1)).isoformat(
                timespec="milliseconds"
            ),
            f"other-{index}",
            "{}",
            base.isoformat(timespec="milliseconds"),
        )
        for index in range(20_000)
    )
    with repository._transaction() as conn:
        conn.executemany(insert_sql, rows)

    result = GroundRawStreamQueryService(repository).ping_series(
        run_id=run_id,
        mr_id="mr-ct",
        target_ip="192.0.2.10",
        start_time="2026-07-25T08:00:00+08:00",
        end_time="2026-07-25T08:00:30+08:00",
    )

    assert len(result["ap_transitions"]) == 1
    assert result["ap_transitions"][0]["new_ap_name"] == "AP-TARGET"


def test_ping_transition_marker_receive_prefilter_keeps_complete_clock_skew(
    tmp_path: Path,
) -> None:
    paths, repository, run_id = _setup_run(tmp_path)
    raw_path = (
        paths.ground_unattended_active_dir("site-a", "2026-07-25")
        / "fleet_ping"
        / "ping-clock-boundary.jsonl"
    )
    _register_ping_file(
        repository,
        raw_path,
        file_id="raw-ping-clock-boundary",
        run_id=run_id,
        sample_id="sample-clock-boundary",
        ts="2026-07-25T08:00:00+08:00",
    )
    repository.record_control_syslog_event(
        {
            "run_id": run_id,
            "device_uuid": "mr-ct",
            "train_id": "train-1",
            "mr_role": "CT",
            "event_type": "MESH_ACTIVELINK_SWITCH",
            "event_family": "WMESH",
            "receive_time": "2026-07-25T07:59:50.200+08:00",
            "event_time": "2026-07-25T07:59:55.100+08:00",
            "event_time_source": "DEVICE_TIME",
            "data_quality": "COMPLETE",
            "dedup_key": "clock-boundary-switch",
            "details": {"peer_ap_name": "AP-CLOCK-BOUNDARY"},
        }
    )

    result = GroundRawStreamQueryService(repository).ping_series(
        run_id=run_id,
        mr_id="mr-ct",
        target_ip="192.0.2.10",
        start_time="2026-07-25T08:00:00+08:00",
        end_time="2026-07-25T08:00:01+08:00",
    )

    assert len(result["ap_transitions"]) == 1
    assert result["ap_transitions"][0]["new_ap_name"] == "AP-CLOCK-BOUNDARY"


def test_ping_sample_position_context_does_not_emit_switch_marker(
    tmp_path: Path,
) -> None:
    paths, repository, run_id = _setup_run(tmp_path)
    raw_path = (
        paths.ground_unattended_active_dir("site-a", "2026-07-25")
        / "fleet_ping"
        / "ping-context.jsonl"
    )
    _register_ping_file(
        repository,
        raw_path,
        file_id="raw-context",
        run_id=run_id,
        sample_id="sample-context",
        ts="2026-07-25T08:00:00+08:00",
        ap_transition_context="same_ap",
    )

    result = GroundRawStreamQueryService(repository).ping_series(run_id=run_id)

    assert result["ap_transitions"] == []


def test_switch_provenance_dedup_keeps_real_flap_and_fills_mr_identity(
    tmp_path: Path,
) -> None:
    paths, repository, run_id = _setup_run(tmp_path)
    raw_path = (
        paths.ground_unattended_active_dir("site-a", "2026-07-25")
        / "fleet_ping"
        / "ping-flap.jsonl"
    )
    _register_ping_file(
        repository,
        raw_path,
        file_id="raw-flap-ping",
        run_id=run_id,
        sample_id="sample-flap",
        ts="2026-07-25T08:00:00+08:00",
    )
    repository.sync_inventory(
        trains=[{"train_id": "train-1", "train_no": "01"}],
        endpoints=[
            {
                "device_uuid": "mr-ct",
                "train_id": "train-1",
                "mr_role": "CT",
                "management_ip": "192.0.2.10",
            }
        ],
    )

    def event(
        *,
        at: str,
        old: str,
        new: str,
        line: int,
        device_uuid: str = "mr-ct",
    ) -> dict[str, object]:
        return {
            "run_id": run_id,
            "device_uuid": device_uuid,
            "train_id": "train-1",
            "mr_role": "CT",
            "event_type": "MESH_ACTIVELINK_SWITCH",
            "event_family": "WMESH",
            "receive_time": at,
            "event_time": at,
            "source_ip": "192.0.2.10",
            "previous_peer_mac": old,
            "peer_mac": new,
            "raw_file_id": "syslog-flap",
            "raw_line_number": line,
            "details": {"old_peer_mac": old, "new_peer_mac": new},
        }

    inserted = repository.insert_wmesh_events(
        [
            event(
                at="2026-07-25T08:00:00.100+08:00",
                old="0000-0000-000a",
                new="0000-0000-000b",
                line=10,
                device_uuid="",
            ),
            event(
                at="2026-07-25T08:00:00.100+08:00",
                old="0000-0000-000a",
                new="0000-0000-000b",
                line=10,
                device_uuid="",
            ),
            event(
                at="2026-07-25T08:00:00.200+08:00",
                old="0000-0000-000b",
                new="0000-0000-000a",
                line=11,
            ),
            event(
                at="2026-07-25T08:00:00.300+08:00",
                old="0000-0000-000a",
                new="0000-0000-000b",
                line=12,
            ),
        ]
    )

    result = GroundRawStreamQueryService(repository).ping_series(
        run_id=run_id,
        target_ip="192.0.2.10",
    )

    assert inserted == 3
    assert len(result["ap_transitions"]) == 3
    assert [
        (row["old_ap_raw"], row["new_ap_raw"])
        for row in result["ap_transitions"]
    ] == [
        ("0000-0000-000a", "0000-0000-000b"),
        ("0000-0000-000b", "0000-0000-000a"),
        ("0000-0000-000a", "0000-0000-000b"),
    ]
    assert result["ap_transitions"][0]["mr_id"] == "mr-ct"
    assert result["ap_transitions"][0]["management_ip"] == "192.0.2.10"


def test_ping_query_normalizes_registry_train_id_and_incrementally_reads_appends(
    tmp_path: Path,
) -> None:
    paths, repository, run_id = _setup_run(tmp_path)
    repository.update_run(run_id, state="RUNNING", actual_ended_at="")
    raw_path = (
        paths.ground_unattended_active_dir("site-a", "2026-07-25")
        / "fleet_ping"
        / "_07"
        / "CT"
        / "2026-07-25"
        / "08_live.ndjson"
    )
    raw_path.parent.mkdir(parents=True, exist_ok=True)

    def sample(sample_id: str, ts: str, seq: int) -> dict[str, object]:
        return {
            "sample_id": sample_id,
            "ts": ts,
            "target_ip": "10.122.7.249",
            "train_id": "_07",
            "train_no": "07",
            "mr_id": "mr-ct",
            "mr_name": "列车07-MR-CT",
            "mr_position_code": "CT",
            "seq": seq,
            "ok": True,
            "rtt_ms": float(seq),
            "position_quality": "MATCHED",
        }

    initial_rows = [
        sample("sample-1", "2026-07-25T08:00:01+08:00", 1),
        sample("sample-2", "2026-07-25T08:00:02+08:00", 2),
    ]
    raw_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in initial_rows),
        encoding="utf-8",
    )
    repository.upsert_raw_file(
        {
            "file_id": "raw-live-07",
            "run_id": run_id,
            "train_id": "_07",
            "device_uuid": "mr-ct",
            "mr_role": "CT",
            "data_type": "ping",
            "relative_path": raw_path.relative_to(
                repository.db_path.parent
            ).as_posix(),
            "start_time": "2026-07-25T08:00:01+08:00",
            "end_time": "",
            "record_count": 0,
            "size_bytes": 0,
            "status": "OPEN",
            "archive_status": "PENDING",
        }
    )
    query = GroundRawStreamQueryService(repository)

    initial = query.ping_series(
        run_id=run_id,
        train_id="列车07",
        mr_id="mr-ct",
        target_ip="10.122.7.249",
        end_time="2026-07-25T08:00:05+08:00",
    )

    assert initial["raw_sample_count"] == 2
    assert initial["success_count"] == 2
    assert initial["loss_count"] == 0
    assert initial["rtt_sample_count"] == 2
    assert initial["rtt_sum_ms"] == 3.0
    assert initial["current_rtt_ms"] == 2.0
    assert initial["average_rtt_ms"] == 1.5
    assert initial["max_rtt_ms"] == 2.0
    assert initial["diagnostics"]["data_availability"] == "ACTIVE_RAW"
    assert initial["next_cursor"]

    appended = [
        sample("sample-late", "2026-07-25T08:00:01.500+08:00", 3),
        sample("sample-3", "2026-07-25T08:00:03+08:00", 4),
    ]
    with raw_path.open("a", encoding="utf-8", newline="\n") as handle:
        for row in appended:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    incremental = query.ping_series_incremental(
        run_id=run_id,
        train_id="列车07",
        mr_id="mr-ct",
        target_ip="10.122.7.249",
        cursor=initial["next_cursor"],
    )

    assert [row["sample_id"] for row in incremental["points"]] == [
        "sample-late",
        "sample-3",
    ]
    assert incremental["success_count"] == 2
    assert incremental["loss_count"] == 0
    assert incremental["rtt_sample_count"] == 2
    assert incremental["rtt_sum_ms"] == 7.0
    assert incremental["current_rtt_ms"] == 4.0
    assert incremental["average_rtt_ms"] == 3.5
    assert incremental["max_rtt_ms"] == 4.0
    assert incremental["latest_sequence"] == 4
    assert incremental["diagnostics"]["records_scanned"] == len(appended)
    assert incremental["diagnostics"]["bytes_scanned"] == sum(
        len((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))
        for row in appended
    )
    repeated = query.ping_series_incremental(
        run_id=run_id,
        train_id="列车07",
        mr_id="mr-ct",
        target_ip="10.122.7.249",
        cursor=incremental["next_cursor"],
    )
    assert repeated["points"] == []
    assert repeated["diagnostics"]["no_data_reason"] == "NEW_SAMPLES_PENDING"


def test_run_without_actual_times_uses_registered_raw_file_range(
    tmp_path: Path,
) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    repository = GroundUnattendedRepository(
        paths.ground_unattended_db_path("site-a"), site_id="site-a"
    )
    run = repository.create_or_get_run(
        run_id="run-no-actual-times",
        run_date="2026-07-25",
        scheduled_start_at="2026-07-25T09:00:00+08:00",
        scheduled_end_at="2026-07-25T10:00:00+08:00",
    )
    repository.update_run(
        str(run["run_id"]),
        state="COMPLETED",
        actual_started_at="",
        actual_ended_at="",
    )
    raw_path = (
        paths.ground_unattended_active_dir("site-a", "2026-07-25")
        / "fleet_ping"
        / "early.jsonl"
    )
    raw_time = "2026-07-25T08:00:00+08:00"
    _register_ping_file(
        repository,
        raw_path,
        file_id="raw-before-schedule",
        run_id=str(run["run_id"]),
        sample_id="sample-before-schedule",
        ts=raw_time,
    )

    result = GroundRawStreamQueryService(repository).ping_series(
        run_id=str(run["run_id"])
    )

    assert result["raw_sample_count"] == 1
    assert result["points"][0]["sample_id"] == "sample-before-schedule"
    expected_range_time = "2026-07-25T08:00:00.000+08:00"
    assert result["diagnostics"]["resolved_start_time"] == expected_range_time
    assert result["diagnostics"]["resolved_end_time"] == expected_range_time


def test_archive_reader_rejects_zip_slip_and_reports_corruption(
    tmp_path: Path,
) -> None:
    paths, repository, run_id = _setup_run(tmp_path)
    archive_path = (
        paths.ground_unattended_archives_dir("site-a") / "unsafe.zip"
    )
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../escape.ndjson", "{}\n")
    _register_archive(repository, archive_path, run_id=run_id)

    with pytest.raises(GroundArchiveReadError, match="路径不安全"):
        GroundArchiveReader(repository).inspect_archive("archive-test")

    repository.upsert_raw_file(
        {
            "file_id": "raw-history",
            "run_id": run_id,
            "data_type": "ping",
            "relative_path": "active/2026-07-25/fleet_ping/history.jsonl",
            "start_time": "2026-07-25T08:00:00+08:00",
            "end_time": "2026-07-25T08:00:00+08:00",
            "status": "CLOSED",
            "archive_status": "ARCHIVED",
            "compressed_path": "archives/unsafe.zip",
        }
    )
    with pytest.raises(GroundRawQueryError, match="完整性校验失败"):
        GroundRawStreamQueryService(repository).ping_series(run_id=run_id)


def test_archive_reader_rejects_abnormal_compression_ratio(
    tmp_path: Path,
) -> None:
    paths, repository, run_id = _setup_run(tmp_path)
    archive_path = (
        paths.ground_unattended_archives_dir("site-a") / "zip-bomb.zip"
    )
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        archive_path, "w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        archive.writestr("fleet_ping/bomb.jsonl", b"0" * (2 * 1024 * 1024))
    _register_archive(repository, archive_path, run_id=run_id)

    with pytest.raises(GroundArchiveReadError, match="压缩比异常"):
        GroundArchiveReader(repository).inspect_archive("archive-test")


def test_archive_reader_rejects_member_crc_failure(tmp_path: Path) -> None:
    paths, repository, run_id = _setup_run(tmp_path)
    archive_path = (
        paths.ground_unattended_archives_dir("site-a") / "bad-crc.zip"
    )
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    payload = b'{"sample_id":"crc"}\n'
    with zipfile.ZipFile(
        archive_path, "w", compression=zipfile.ZIP_STORED
    ) as archive:
        archive.writestr("fleet_ping/crc.jsonl", payload)
    raw_zip = bytearray(archive_path.read_bytes())
    payload_offset = raw_zip.find(payload)
    assert payload_offset >= 0
    raw_zip[payload_offset] ^= 0x01
    archive_path.write_bytes(raw_zip)
    _register_archive(repository, archive_path, run_id=run_id)

    with pytest.raises(GroundArchiveReadError, match="CRC 校验失败"):
        GroundArchiveReader(repository).inspect_archive("archive-test")


def test_legacy_ready_archive_only_reads_known_registered_prefix(
    tmp_path: Path,
) -> None:
    paths, repository, run_id = _setup_run(tmp_path)
    archive_path = (
        paths.ground_unattended_archives_dir("site-a") / "legacy.zip"
    )
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "sample_id": "legacy-sample",
        "ts": "2026-07-25T08:00:00+08:00",
        "target_ip": "192.0.2.20",
        "ok": True,
    }
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "fleet_ping/legacy.jsonl",
            json.dumps(record).encode("utf-8") + b"\n",
        )
    _register_archive(repository, archive_path, run_id=run_id)
    repository.upsert_raw_file(
        {
            "file_id": "raw-legacy",
            "run_id": run_id,
            "data_type": "ping",
            "relative_path": "active/2026-07-25/fleet_ping/legacy.jsonl",
            "start_time": record["ts"],
            "end_time": record["ts"],
            "record_count": 1,
            "status": "CLOSED",
            "archive_status": "ARCHIVED",
            "compressed_path": "archives/legacy.zip",
        }
    )

    result = GroundRawStreamQueryService(repository).ping_series(run_id=run_id)
    assert result["raw_sample_count"] == 1
    assert result["diagnostics"]["legacy_archive"] is True
    assert result["diagnostics"]["source_kind"] == "ARCHIVE"


def test_status_separates_service_active_and_latest_run_and_downloads_artifact(
    tmp_path: Path,
) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    app = create_app(paths=paths)
    repository = app.state.ground_unattended_repository
    run = repository.create_or_get_run(
        run_id="run-completed",
        run_date="2026-07-25",
        scheduled_start_at=START,
        scheduled_end_at=END,
    )
    repository.update_run(
        str(run["run_id"]),
        state="COMPLETED",
        actual_started_at=START,
        actual_ended_at=END,
    )
    repository.save_operation(
        {
            "operation_id": "groundop-completed",
            "run_id": "run-completed",
            "operation_type": "STOP",
            "operation_state": "COMPLETED",
            "operation_stage": "COMPLETED",
            "progress_percent": 100,
            "message": "正常停止完成",
        }
    )
    archive_path = (
        paths.ground_unattended_archives_dir("demo") / "download.zip"
    )
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("daily_summary.json", b"{}\n")
    repository.upsert_archive(
        {
            "archive_id": "archive-download",
            "site_id": "demo",
            "run_id": "run-completed",
            "run_date": "2026-07-25",
            "relative_path": archive_path.relative_to(
                repository.db_path.parent
            ).as_posix(),
            "archive_status": "READY",
            "archive_size_bytes": archive_path.stat().st_size,
            "sha256": _sha256(archive_path),
            "manifest_sha256": "",
            "retention_until": "2099-01-01",
            "active_cleanup_pending": 0,
            "summary_json": json.dumps({"run_id": "run-completed"}),
            "message": "ready",
            "created_at": START,
            "updated_at": END,
        }
    )

    with TestClient(app) as client:
        status_response = client.get(
            "/api/rail-transit/ground-unattended/status"
        )
        runs_response = client.get(
            "/api/rail-transit/ground-unattended/runs"
        )
        detail_response = client.get(
            "/api/rail-transit/ground-unattended/archives/"
            "archive-download/detail"
        )
        artifact_response = client.get(
            "/api/rail-transit/ground-unattended/artifacts/"
            "archive-download/download"
        )
        latest_operation_response = client.get(
            "/api/rail-transit/ground-unattended/operations/latest"
        )

    status_body = status_response.json()
    assert status_body["state"] == "DISABLED"
    assert status_body["active_run_id"] == ""
    assert status_body["latest_run_id"] == "run-completed"
    assert status_body["latest_run_state"] == "COMPLETED"
    assert status_body["active_operation_id"] == ""
    assert status_body["latest_operation_id"] == "groundop-completed"
    assert latest_operation_response.json()["operation_id"] == "groundop-completed"
    assert runs_response.json()["items"][0]["run_id"] == "run-completed"
    assert detail_response.json()["validation"]["status"] == "READY"
    assert detail_response.json()["validation"]["legacy_manifest"] is True
    assert artifact_response.content == archive_path.read_bytes()
    assert artifact_response.headers["x-content-sha256"] == _sha256(
        archive_path
    )


def test_archive_detail_api_returns_registered_file_metadata(
    tmp_path: Path,
) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    app = create_app(paths=paths)
    repository = app.state.ground_unattended_repository
    run = repository.create_or_get_run(
        run_id="run-detail",
        run_date="2026-07-25",
        scheduled_start_at=START,
        scheduled_end_at=END,
    )
    repository.update_run(
        str(run["run_id"]),
        state="COMPLETED",
        actual_started_at=START,
        actual_ended_at=END,
    )
    active = paths.ground_unattended_active_dir("demo", "2026-07-25")
    raw_path = active / "fleet_ping" / "ping-detail.jsonl"
    _register_ping_file(
        repository,
        raw_path,
        file_id="raw-detail",
        run_id="run-detail",
        sample_id="sample-detail",
        ts="2026-07-25T08:00:00+08:00",
    )
    archived = GroundUnattendedArchiveService(
        paths, site_id="demo", repository=repository
    ).archive_run("run-detail", repository.get_profile())
    assert archived.success

    with TestClient(app) as client:
        response = client.get(
            "/api/rail-transit/ground-unattended/archives/"
            f"{archived.archive_id}/detail"
        )

    assert response.status_code == 200
    body = response.json()
    assert body["validation"]["legacy_manifest"] is False
    assert body["validation"]["file_count"] == len(body["files"])
    raw_file = next(
        item
        for item in body["files"]
        if item["path"] == "fleet_ping/ping-detail.jsonl"
    )
    assert raw_file == {
        "path": "fleet_ping/ping-detail.jsonl",
        "data_type": "ping",
        "train_id": "train-1",
        "mr_id": "mr-ct",
        "mr_role": "CT",
        "hour": "08",
        "record_count": 1,
        "size_bytes": raw_file["size_bytes"],
        "compressed_size_bytes": raw_file["compressed_size_bytes"],
        "sha256": raw_file["sha256"],
        "parse_status": "PENDING",
    }
    assert raw_file["size_bytes"] > 0
    assert raw_file["compressed_size_bytes"] > 0
    assert len(raw_file["sha256"]) == 64


def test_legacy_syslog_is_enriched_at_read_time_without_modifying_ndjson(
    tmp_path: Path,
) -> None:
    paths, repository, run_id = _setup_run(tmp_path)
    raw_path = (
        paths.ground_unattended_active_dir("site-a", "2026-07-25")
        / "realtime"
        / "syslog"
        / "legacy.ndjson"
    )
    raw_text = (
        "<189>Jul 25 08:00:00 2026 TEST-MR-CT "
        "%%10WMESH/5/MESH_LINKUP: Mesh Link on the interface "
        "WLAN-MeshLink841 is up: peer MAC = 0200-0000-0001, "
        "peer radio mode = 3, RSSI = 25"
    )
    record = {
        "receive_time": "2026-07-25T08:00:00+08:00",
        "source_ip": "192.0.2.10",
        "raw_text": raw_text,
        "raw_bytes_base64": "c2Vuc2l0aXZlLWludGVybmFsLWJ5dGVz",
        "site_id": "internal-site-id",
        "device_id": 42,
        "train_id": "train-1",
        "device_uuid": "mr-ct",
        "mr_role": "CT",
        "identity_status": "VERIFIED",
    }
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    original = (
        json.dumps(record, ensure_ascii=False).encode("utf-8") + b"\n"
    )
    raw_path.write_bytes(original)
    repository.upsert_raw_file(
        {
            "file_id": "raw-syslog-legacy",
            "run_id": run_id,
            "train_id": "train-1",
            "device_uuid": "mr-ct",
            "mr_role": "CT",
            "data_type": "syslog",
            "relative_path": raw_path.relative_to(
                repository.db_path.parent
            ).as_posix(),
            "start_time": record["receive_time"],
            "end_time": record["receive_time"],
            "record_count": 1,
            "size_bytes": len(original),
            "sha256": _sha256(raw_path),
            "status": "CLOSED",
            "archive_status": "PENDING",
        }
    )
    identity_database = Database(paths.site_db_path("site-a"))
    identity_database.initialize()
    AcRepository(identity_database).replace_fit_ap_resources(
        "ac-1",
        [
            {
                "ap_uuid": "ap-1",
                "ap_name": "站点A-AP01",
                "ap_mac": "0100-0000-0001",
                "site": "站点A",
                "rid1_bbssid": "0200-0000-0001",
            }
        ],
    )
    ApIdentityQueryService(identity_database).rebuild_index("test_ac_refresh")
    service = GroundUnattendedApplicationService(
        paths,
        site_id="site-a",
        repository=repository,
        supervisor=SimpleNamespace(),
    )

    result = service.syslog_records("site-a", run_id=run_id)

    assert result.total == 1
    item = result.items[0]
    assert item.display_enriched is True
    assert item.event_type == "MESH_LINKUP"
    assert item.peer_name == "站点A-AP01"
    assert item.peer_mac == "02:00:00:00:00:01"
    assert item.resolution_status == "RADIO_BSSID"
    assert item.parsed_details["identity_entity_id"]
    assert item.parsed_details["identity_revision"] == 1
    assert item.raw_file_id == "raw-syslog-legacy"
    assert item.raw_line_number == 1
    assert item.data_source == "ACTIVE"
    assert {
        "raw_bytes_base64",
        "site_id",
        "device_id",
    }.isdisjoint(item.model_dump())
    assert result.diagnostics.source_kind == "ACTIVE"
    assert result.diagnostics.data_availability == "ACTIVE_RAW"
    assert raw_path.read_bytes() == original


def test_regular_archive_query_skips_full_archive_hash(
    tmp_path: Path, monkeypatch
) -> None:
    paths, repository, run_id = _setup_run(tmp_path)
    raw_path = (
        paths.ground_unattended_active_dir("site-a", "2026-07-25")
        / "realtime"
        / "syslog"
        / "archived.ndjson"
    )
    record = {
        "global_receive_sequence": 1,
        "receive_time": "2026-07-25T08:00:00+08:00",
        "event_type": "MESH_LINKUP",
        "raw_text": "WMESH LINKUP",
    }
    payload = json.dumps(record).encode("utf-8") + b"\n"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(payload)
    repository.upsert_raw_file(
        {
            "file_id": "raw-archive-lightweight",
            "run_id": run_id,
            "data_type": "syslog",
            "relative_path": raw_path.relative_to(
                repository.db_path.parent
            ).as_posix(),
            "start_time": record["receive_time"],
            "end_time": record["receive_time"],
            "record_count": 1,
            "size_bytes": len(payload),
            "status": "CLOSED",
            "archive_status": "ARCHIVED",
        }
    )
    archive_path = (
        paths.ground_unattended_archives_dir("site-a") / "lightweight.zip"
    )
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("realtime/syslog/archived.ndjson", payload)
    raw_path.unlink()
    _register_archive(repository, archive_path, run_id=run_id)

    def reject_full_hash(_path: Path) -> str:
        raise AssertionError("regular query must not hash the whole archive")

    monkeypatch.setattr(
        "netconsole.services.ground_unattended.archive_reader._sha256",
        reject_full_hash,
    )

    result = GroundRawStreamQueryService(repository).syslog_records(run_id=run_id)

    assert result["total"] == 1
    assert result["items"][0]["data_source"] == "ARCHIVE"


def test_ping_target_ip_survives_inventory_mr_uuid_drift(
    tmp_path: Path,
) -> None:
    paths, repository, run_id = _setup_run(tmp_path)
    repository.sync_inventory(
        trains=[
            {
                "train_id": "inventory-train-03",
                "train_no": "03",
                "train_name": "列车03",
            }
        ],
        endpoints=[
            {
                "device_uuid": "current-mr-uuid",
                "device_id": 3,
                "train_id": "inventory-train-03",
                "mr_role": "CW",
                "device_name": "列车03-MR-CW",
                "management_ip": "10.122.3.250",
                "source_hostname": "列车03-MR-CW",
            }
        ],
    )
    raw_path = (
        paths.ground_unattended_active_dir("site-a", "2026-07-25")
        / "fleet_ping"
        / "drifted.ndjson"
    )
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "sample_id": "sample-drifted",
        "ts": "2026-07-25T08:00:00+08:00",
        "target_ip": "10.122.3.250",
        "train_id": "列车03",
        "train_no": "03",
        "mr_id": "historical-mr-uuid",
        "device_uuid": "historical-mr-uuid",
        "mr_name": "列车03-MR-CW",
        "mr_position_code": "CW",
        "ok": True,
        "rtt_ms": 43.0,
        "site_id": "site-a",
        "automation_run_id": run_id,
        "raw_file_id": "raw-drifted",
        "raw_line_number": 1,
    }
    raw_path.write_text(
        json.dumps(record, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    repository.upsert_raw_file(
        {
            "file_id": "raw-drifted",
            "run_id": run_id,
            "train_id": "_03",
            "device_uuid": "historical-mr-uuid",
            "mr_role": "CW",
            "data_type": "ping",
            "relative_path": raw_path.relative_to(
                repository.db_path.parent
            ).as_posix(),
            "start_time": record["ts"],
            "end_time": record["ts"],
            "record_count": 1,
            "size_bytes": raw_path.stat().st_size,
            "status": "CLOSED",
            "archive_status": "PENDING",
        }
    )

    raw_result = GroundRawStreamQueryService(repository).ping_series(
        run_id=run_id,
        train_id="inventory-train-03",
        mr_id="current-mr-uuid",
        target_ip="10.122.3.250",
    )
    raw_result["points"] = (
        GroundUnattendedApplicationService._project_ping_samples(
            raw_result["points"]
        )
    )

    dto = GroundPingSeriesDTO.model_validate(raw_result)
    assert dto.raw_sample_count == 1
    assert dto.points[0].sample_id == "sample-drifted"
    assert dto.diagnostics.raw_file_registry_hit_count == 1
    assert dto.diagnostics.matched_count == 1
    assert dto.query_identity == encode_ping_query_identity(
        run_id, "10.122.3.250"
    )


def test_ping_target_ip_accepts_historical_records_with_missing_alias_fields(
    tmp_path: Path,
) -> None:
    paths, repository, run_id = _setup_run(tmp_path)
    repository.sync_inventory(
        trains=[
            {
                "train_id": "inventory-train-03",
                "train_no": "03",
                "train_name": "列车03",
            }
        ],
        endpoints=[
            {
                "device_uuid": "current-mr-uuid",
                "device_id": 3,
                "train_id": "inventory-train-03",
                "mr_role": "CW",
                "device_name": "列车03-MR-CW",
                "management_ip": "10.122.3.250",
                "source_hostname": "列车03-MR-CW",
            }
        ],
    )
    raw_path = (
        paths.ground_unattended_active_dir("site-a", "2026-07-25")
        / "fleet_ping"
        / "missing-alias-fields.ndjson"
    )
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "sample_id": "sample-missing-aliases",
        "ts": "2026-07-25T08:00:00+08:00",
        "target_ip": "10.122.3.250",
        "ok": True,
        "rtt_ms": 42.0,
    }
    raw_path.write_text(
        json.dumps(record, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    repository.upsert_raw_file(
        {
            "file_id": "raw-missing-aliases",
            "run_id": run_id,
            "train_id": "_03",
            "device_uuid": "historical-mr-uuid",
            "mr_role": "CW",
            "data_type": "ping",
            "relative_path": raw_path.relative_to(
                repository.db_path.parent
            ).as_posix(),
            "start_time": record["ts"],
            "end_time": record["ts"],
            "record_count": 1,
            "size_bytes": raw_path.stat().st_size,
            "status": "CLOSED",
            "archive_status": "PENDING",
        }
    )

    result = GroundRawStreamQueryService(repository).ping_series(
        run_id=run_id,
        train_id="inventory-train-03",
        mr_id="current-mr-uuid",
        target_ip="10.122.3.250",
    )

    assert result["raw_sample_count"] == 1
    assert result["points"][0]["sample_id"] == "sample-missing-aliases"


def test_ping_query_identity_rejects_mismatch_and_duplicate_target_ip(
    tmp_path: Path,
) -> None:
    paths, repository, run_id = _setup_run(tmp_path)
    for index, (train_id, role) in enumerate(
        (("_03", "CW"), ("_07", "CT")),
        start=1,
    ):
        path = (
            paths.ground_unattended_active_dir("site-a", "2026-07-25")
            / "fleet_ping"
            / f"conflict-{index}.ndjson"
        )
        record = {
            "sample_id": f"conflict-{index}",
            "ts": f"2026-07-25T08:0{index}:00+08:00",
            "target_ip": "10.122.99.250",
            "train_id": train_id,
            "mr_position_code": role,
            "ok": True,
            "rtt_ms": 2.0,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(record, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        repository.upsert_raw_file(
            {
                "file_id": f"raw-conflict-{index}",
                "run_id": run_id,
                "train_id": train_id,
                "device_uuid": f"mr-{index}",
                "mr_role": role,
                "data_type": "ping",
                "relative_path": path.relative_to(
                    repository.db_path.parent
                ).as_posix(),
                "start_time": record["ts"],
                "end_time": record["ts"],
                "record_count": 1,
                "size_bytes": path.stat().st_size,
                "status": "CLOSED",
                "archive_status": "PENDING",
            }
        )
    query = GroundRawStreamQueryService(repository)

    with pytest.raises(
        GroundRawQueryError,
        match="多个列车或 MR 端位",
    ) as conflict:
        query.ping_series(
            run_id=run_id,
            target_ip="10.122.99.250",
        )
    assert conflict.value.code == "PING_TARGET_IDENTITY_CONFLICT"

    with pytest.raises(GroundRawQueryError) as mismatch:
        query.ping_series(
            run_id=run_id,
            target_ip="10.122.99.250",
            query_identity=encode_ping_query_identity(
                run_id, "10.122.99.251"
            ),
        )
    assert mismatch.value.code == "PING_IDENTITY_MISMATCH"


def test_ping_series_api_projects_raw_fields_and_returns_request_id(
    tmp_path: Path,
) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    app = create_app(paths=paths)
    repository = app.state.ground_unattended_repository
    run = repository.create_or_get_run(
        run_id="run-api-ping",
        run_date="2026-07-25",
        scheduled_start_at=START,
        scheduled_end_at=END,
    )
    repository.update_run(
        str(run["run_id"]),
        state="COMPLETED",
        actual_started_at=START,
        actual_ended_at=END,
    )
    raw_path = (
        paths.ground_unattended_active_dir(
            repository.site_id, "2026-07-25"
        )
        / "fleet_ping"
        / "api-extra.ndjson"
    )
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "sample_id": "api-sample",
        "ts": "2026-07-25T08:00:00+08:00",
        "target_ip": "192.0.2.80",
        "train_id": "_80",
        "mr_id": "mr-api",
        "mr_position_code": "CT",
        "ok": True,
        "rtt_ms": 8.0,
        "site_id": repository.site_id,
        "automation_run_id": "run-api-ping",
        "device_uuid": "mr-api",
        "backend": "fping",
        "error": "",
        "shard_id": "shard-api",
        "raw_file_id": "raw-api-extra",
        "raw_line_number": 1,
        "raw_file_status": "CLOSED",
    }
    raw_path.write_text(
        json.dumps(record, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    repository.upsert_raw_file(
        {
            "file_id": "raw-api-extra",
            "run_id": "run-api-ping",
            "train_id": "_80",
            "device_uuid": "mr-api",
            "mr_role": "CT",
            "data_type": "ping",
            "relative_path": raw_path.relative_to(
                repository.db_path.parent
            ).as_posix(),
            "start_time": record["ts"],
            "end_time": record["ts"],
            "record_count": 1,
            "size_bytes": raw_path.stat().st_size,
            "status": "CLOSED",
            "archive_status": "PENDING",
        }
    )

    with TestClient(app) as client:
        response = client.get(
            "/api/rail-transit/ground-unattended/ping-series",
            params={
                "run_id": "run-api-ping",
                "target_ip": "192.0.2.80",
            },
        )

    assert response.status_code == 200
    assert response.json()["raw_sample_count"] == 1
    assert response.json()["points"][0]["sample_id"] == "api-sample"
    assert "site_id" not in response.json()["points"][0]
    request_id = response.json()["diagnostics"]["request_id"]
    assert request_id
    assert response.headers["x-request-id"] == request_id


def test_ping_series_unknown_error_returns_stable_500(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    app = create_app(paths=paths)
    service = app.state.ground_unattended_application_service

    def fail_ping(*_args, **_kwargs):
        raise RuntimeError("sensitive physical path must stay in logs")

    monkeypatch.setattr(service, "ping_series", fail_ping)
    with TestClient(app) as client:
        response = client.get(
            "/api/rail-transit/ground-unattended/ping-series",
            params={
                "run_id": "run-failure",
                "target_ip": "192.0.2.99",
            },
        )
        status_response = client.get(
            "/api/rail-transit/ground-unattended/status"
        )

    assert response.status_code == 500
    detail = response.json()["detail"]
    assert detail["code"] == "GROUND_PING_QUERY_FAILED"
    assert detail["details"]["request_id"]
    assert response.headers["x-request-id"] == detail["details"]["request_id"]
    assert "sensitive" not in response.text
    assert status_response.status_code == 200


def _setup_run(
    tmp_path: Path,
) -> tuple[PathResolver, GroundUnattendedRepository, str]:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    repository = GroundUnattendedRepository(
        paths.ground_unattended_db_path("site-a"), site_id="site-a"
    )
    run = repository.create_or_get_run(
        run_id="run-history",
        run_date="2026-07-25",
        scheduled_start_at=START,
        scheduled_end_at=END,
    )
    repository.update_run(
        str(run["run_id"]),
        state="COMPLETED",
        actual_started_at=START,
        actual_ended_at=END,
    )
    return paths, repository, str(run["run_id"])


def _register_ping_file(
    repository: GroundUnattendedRepository,
    path: Path,
    *,
    file_id: str,
    run_id: str,
    sample_id: str,
    ts: str,
    ap_transition_context: str = "",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "sample_id": sample_id,
        "ts": ts,
        "target_ip": "192.0.2.10",
        "train_id": "train-1",
        "mr_id": "mr-ct",
        "ok": True,
        "rtt_ms": 2.0,
        "ap_transition_context": ap_transition_context,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    repository.upsert_raw_file(
        {
            "file_id": file_id,
            "run_id": run_id,
            "train_id": "train-1",
            "device_uuid": "mr-ct",
            "mr_role": "CT",
            "data_type": "ping",
            "relative_path": path.relative_to(
                repository.db_path.parent
            ).as_posix(),
            "start_time": ts,
            "end_time": ts,
            "record_count": 1,
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
            "status": "CLOSED",
            "archive_status": "PENDING",
        }
    )


def _register_archive(
    repository: GroundUnattendedRepository,
    archive_path: Path,
    *,
    run_id: str,
) -> None:
    repository.upsert_archive(
        {
            "archive_id": "archive-test",
            "site_id": repository.site_id,
            "run_id": run_id,
            "run_date": "2026-07-25",
            "relative_path": archive_path.relative_to(
                repository.db_path.parent
            ).as_posix(),
            "archive_status": "READY",
            "archive_size_bytes": archive_path.stat().st_size,
            "sha256": _sha256(archive_path),
            "manifest_sha256": "",
            "retention_until": "2099-01-01",
            "active_cleanup_pending": 0,
            "summary_json": "{}",
            "message": "ready",
            "created_at": START,
            "updated_at": END,
        }
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
