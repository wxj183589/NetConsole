from __future__ import annotations

import hashlib
import os
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)
from netconsole.services.ground_unattended.raw_query import (
    GroundRawStreamQueryService,
)


RUN_ID = "run-scale"
RUN_DATE = "2026-07-25"
START = f"{RUN_DATE}T07:00:00+08:00"
END = f"{RUN_DATE}T23:00:00+08:00"
SAMPLE_TIME = f"{RUN_DATE}T08:00:00+08:00"
RUN_LARGE_SCALE_TESTS = os.environ.get("NETCONSOLE_RUN_SCALE_TESTS") == "1"


def test_ready_archive_streams_50000_ping_samples_with_bounded_output(
    tmp_path: Path,
) -> None:
    paths, repository = _setup(tmp_path)
    source = tmp_path / "scale-ping.ndjson"
    _write_ping_records(source, 50_000)
    repository.upsert_raw_file(
        _raw_file_row(
            file_id="raw-ping-archive",
            relative_path=f"active/{RUN_DATE}/fleet_ping/scale-ping.ndjson",
            data_type="ping",
            record_count=50_000,
            size_bytes=source.stat().st_size,
        )
    )
    archive_path = paths.ground_unattended_archives_dir("site-a") / "scale.zip"
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        archive_path,
        "w",
        compression=zipfile.ZIP_STORED,
    ) as archive:
        archive.write(source, "fleet_ping/scale-ping.ndjson")
    _register_archive(repository, archive_path)

    result = GroundRawStreamQueryService(repository).ping_series(
        run_id=RUN_ID,
        train_id="train-01",
        mr_id="mr-01-ct",
        target_ip="192.0.2.10",
        max_points=3000,
    )

    assert result["raw_sample_count"] == 50_000
    assert len(result["points"]) <= 3000
    assert sum(not point["ok"] for point in result["points"]) == 51
    assert result["diagnostics"]["records_scanned"] == 50_000
    assert result["diagnostics"]["source_kind"] == "ARCHIVE"
    assert result["diagnostics"]["truncated"] is False


@pytest.mark.skipif(
    not RUN_LARGE_SCALE_TESTS,
    reason="set NETCONSOLE_RUN_SCALE_TESTS=1 to run the 500k stream gate",
)
def test_active_query_streams_500000_ping_samples_within_query_budget(
    tmp_path: Path,
) -> None:
    paths, repository = _setup(tmp_path)
    path = (
        paths.ground_unattended_active_dir("site-a", RUN_DATE)
        / "fleet_ping"
        / "scale-ping-500k.ndjson"
    )
    _write_ping_records(path, 500_000)
    repository.upsert_raw_file(
        _raw_file_row(
            file_id="raw-ping-500k",
            relative_path=path.relative_to(repository.db_path.parent).as_posix(),
            data_type="ping",
            record_count=500_000,
            size_bytes=path.stat().st_size,
        )
    )

    result = GroundRawStreamQueryService(repository).ping_series(
        run_id=RUN_ID,
        train_id="train-01",
        mr_id="mr-01-ct",
        target_ip="192.0.2.10",
        max_points=3000,
    )

    assert result["raw_sample_count"] == 500_000
    assert result["diagnostics"]["records_scanned"] == 500_000
    assert result["diagnostics"]["bytes_scanned"] == path.stat().st_size
    assert result["diagnostics"]["truncated"] is False
    assert len(result["points"]) <= 3000
    assert any(not point["ok"] for point in result["points"])


def test_syslog_query_pages_100000_records_without_materializing_all_rows(
    tmp_path: Path,
) -> None:
    paths, repository = _setup(tmp_path)
    path = (
        paths.ground_unattended_active_dir("site-a", RUN_DATE)
        / "realtime"
        / "syslog"
        / "scale-syslog.ndjson"
    )
    _write_syslog_records(path, 100_000)
    repository.upsert_raw_file(
        _raw_file_row(
            file_id="raw-syslog-100k",
            relative_path=path.relative_to(repository.db_path.parent).as_posix(),
            data_type="syslog",
            record_count=100_000,
            size_bytes=path.stat().st_size,
        )
    )

    result = GroundRawStreamQueryService(repository).syslog_records(
        run_id=RUN_ID,
        train_id="train-01",
        mr_id="mr-01-ct",
        mr_role="CT",
        event_type="mesh_linkup",
        page=1,
        page_size=100,
    )

    assert result["total"] == 100_000, (
        result["diagnostics"]["records_scanned"],
        result["diagnostics"]["malformed_record_count"],
        result["diagnostics"]["duplicate_record_count"],
        result["diagnostics"]["no_data_reason"],
    )
    assert len(result["items"]) == 100
    assert result["diagnostics"]["records_scanned"] == 100_000
    assert result["diagnostics"]["truncated"] is False


def test_registry_prefilters_36_mrs_across_30_days_before_limit(
    tmp_path: Path,
) -> None:
    _paths, repository = _setup(tmp_path)
    first_day = date(2026, 6, 1)
    for day_offset in range(30):
        current = first_day + timedelta(days=day_offset)
        timestamp = f"{current.isoformat()}T08:00:00+08:00"
        for mr_index in range(36):
            repository.upsert_raw_file(
                {
                    **_raw_file_row(
                        file_id=f"raw-{day_offset:02}-{mr_index:02}",
                        relative_path=(
                            f"active/{current.isoformat()}/fleet_ping/"
                            f"mr-{mr_index:02}.ndjson"
                        ),
                        data_type="ping",
                        record_count=1,
                        size_bytes=100,
                    ),
                    "run_id": f"run-{day_offset:02}",
                    "device_uuid": f"mr-{mr_index:02}",
                    "start_time": timestamp,
                    "end_time": timestamp,
                }
            )

    target_day = first_day + timedelta(days=29)
    rows = repository.list_raw_files_for_query(
        data_type="ping",
        start_time=f"{target_day.isoformat()}T00:00:00+08:00",
        end_time=f"{target_day.isoformat()}T23:59:59+08:00",
        device_uuid="mr-17",
        limit=2,
    )

    assert len(rows) == 1
    assert rows[0]["run_id"] == "run-29"
    assert rows[0]["device_uuid"] == "mr-17"


def _setup(
    tmp_path: Path,
) -> tuple[PathResolver, GroundUnattendedRepository]:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    repository = GroundUnattendedRepository(
        paths.ground_unattended_db_path("site-a"),
        site_id="site-a",
    )
    repository.create_or_get_run(
        run_id=RUN_ID,
        run_date=RUN_DATE,
        scheduled_start_at=START,
        scheduled_end_at=END,
    )
    repository.update_run(
        RUN_ID,
        state="COMPLETED",
        actual_started_at=START,
        actual_ended_at=END,
    )
    return paths, repository


def _raw_file_row(
    *,
    file_id: str,
    relative_path: str,
    data_type: str,
    record_count: int,
    size_bytes: int,
) -> dict[str, object]:
    return {
        "file_id": file_id,
        "run_id": RUN_ID,
        "train_id": "train-01",
        "device_uuid": "mr-01-ct",
        "mr_role": "CT",
        "data_type": data_type,
        "relative_path": relative_path,
        "start_time": SAMPLE_TIME,
        "end_time": SAMPLE_TIME,
        "record_count": record_count,
        "size_bytes": size_bytes,
        "status": "CLOSED",
        "archive_status": "ARCHIVED" if data_type == "ping" else "PENDING",
    }


def _write_ping_records(path: Path, count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        for sequence in range(count):
            ok = "false" if sequence % 997 == 0 else "true"
            handle.write(
                (
                    f'{{"sample_id":"sample-{sequence}","ts":"{SAMPLE_TIME}",'
                    f'"target_ip":"192.0.2.10","train_id":"train-01",'
                    f'"mr_id":"mr-01-ct","seq":{sequence},"ok":{ok},'
                    '"rtt_ms":2.5}\n'
                ).encode("ascii")
            )


def _write_syslog_records(path: Path, count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        for sequence in range(count):
            handle.write(
                (
                    f'{{"global_receive_sequence":{sequence},'
                    f'"receive_time":"{SAMPLE_TIME}","train_id":"train-01",'
                    '"device_uuid":"mr-01-ct","mr_name":"Train 01 MR CT",'
                    '"mr_role":"CT","source_ip":"192.0.2.20",'
                    '"event_type":"mesh_linkup","raw_text":"WMESH LINKUP"}\n'
                ).encode("ascii")
            )


def _register_archive(
    repository: GroundUnattendedRepository,
    archive_path: Path,
) -> None:
    repository.upsert_archive(
        {
            "archive_id": "archive-scale",
            "site_id": repository.site_id,
            "run_id": RUN_ID,
            "run_date": RUN_DATE,
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
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
