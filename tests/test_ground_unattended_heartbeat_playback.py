import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from netconsole.core.paths import PathResolver
from netconsole.repositories.ground_unattended_repository import GroundUnattendedRepository
from netconsole.services.ground_unattended.application_service import GroundUnattendedApplicationService
from netconsole.services.ground_unattended.raw_query import GroundRawStreamQueryService


START = "2026-11-20T15:11:00+08:00"
END = "2026-11-20T16:08:24+08:00"
MR_UUID = "mr-35-ct"


def _register_ping_file(
    repository: GroundUnattendedRepository,
    path: Path,
    *,
    run_id: str,
    rows: list[dict[str, object]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    repository.upsert_raw_file(
        {
            "file_id": f"{run_id}-{path.stem}",
            "run_id": run_id,
            "train_id": "train:35",
            "device_uuid": MR_UUID,
            "mr_role": "CT",
            "data_type": "ping",
            "relative_path": path.relative_to(repository.db_path.parent).as_posix(),
            "start_time": str(rows[0]["ts"]),
            "end_time": str(rows[-1]["ts"]),
            "record_count": len(rows),
            "size_bytes": path.stat().st_size,
            "status": "CLOSED",
            "archive_status": "PENDING",
        }
    )


def _sample(ts: str, target_ip: str, *, ok: bool) -> dict[str, object]:
    return {
        "sample_id": f"{target_ip}-{ts}",
        "ts": ts,
        "target_ip": target_ip,
        "train_id": "train:35",
        "train_no": "35",
        "mr_id": MR_UUID,
        "device_uuid": MR_UUID,
        "mr_position_code": "CT",
        "ok": ok,
        "rtt_ms": 2.0 if ok else None,
        "warmup_ignored": False,
    }


def test_historical_playback_uses_resident_heartbeat_stream_for_both_addresses(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    repository = GroundUnattendedRepository(paths.ground_unattended_db_path("site-a"), site_id="site-a")
    repository.create_or_get_run(
        run_id="archive-run",
        run_date="2026-11-20",
        scheduled_start_at=START,
        scheduled_end_at=END,
    )
    repository.update_run("archive-run", state="COMPLETED", actual_started_at=START, actual_ended_at=END)
    resident = paths.ground_unattended_active_dir("site-a", "2026-11-20") / "heartbeat" / "ct.ndjson"
    _register_ping_file(
        repository,
        resident,
        run_id="heartbeat-resident",
        rows=[
            _sample("2026-11-20T15:11:01+08:00", "10.82.24.235", ok=True),
            _sample("2026-11-20T15:11:02+08:00", "192.168.35.249", ok=False),
            _sample("2026-11-20T16:08:23+08:00", "10.82.24.235", ok=False),
        ],
    )

    service = GroundUnattendedApplicationService(
        paths,
        site_id="site-a",
        repository=repository,
        supervisor=SimpleNamespace(),
    )
    source_run_id = service._heartbeat_history_source_run_id(
        run_id="archive-run",
        mr_uuid=MR_UUID,
        start=datetime.fromisoformat(START),
        end=datetime.fromisoformat(END),
    )
    assert source_run_id == "heartbeat-resident"

    series = GroundRawStreamQueryService(repository).ping_series(
        run_id=source_run_id,
        mr_id=MR_UUID,
        start_time=START,
        end_time=END,
        max_points=100,
    )
    assert series["raw_sample_count"] == 3
    assert series["success_count"] == 1
    assert series["loss_count"] == 2
    assert {row["target_ip"] for row in series["points"]} == {
        "10.82.24.235",
        "192.168.35.249",
    }
    assert series["diagnostics"]["resolved_mr_ids"] == [MR_UUID]


def test_historical_playback_keeps_full_resident_heartbeat_series_budget(tmp_path: Path, monkeypatch) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    repository = GroundUnattendedRepository(paths.ground_unattended_db_path("site-a"), site_id="site-a")
    repository.create_or_get_run(
        run_id="archive-run",
        run_date="2026-11-20",
        scheduled_start_at=START,
        scheduled_end_at=END,
    )
    repository.update_run("archive-run", state="COMPLETED", actual_started_at=START, actual_ended_at=END)
    repository.upsert_heartbeat_snapshot(
        "archive-run",
        {
            "mr_uuid": MR_UUID,
            "train_id": "train:35",
            "train_no": "35",
            "role": "CT",
            "status": "ONLINE",
            "management_ip": "10.82.24.235",
            "backup_management_ip": "192.168.35.249",
            "ip_states": [],
        },
        entity_type="MR",
        entity_id=MR_UUID,
    )
    resident = paths.ground_unattended_active_dir("site-a", "2026-11-20") / "heartbeat" / "ct.ndjson"
    _register_ping_file(
        repository,
        resident,
        run_id="heartbeat-resident",
        rows=[
            _sample("2026-11-20T15:11:01+08:00", "10.82.24.235", ok=True),
            _sample("2026-11-20T15:11:02+08:00", "192.168.35.249", ok=False),
            _sample("2026-11-20T16:08:23+08:00", "10.82.24.235", ok=False),
        ],
    )
    service = GroundUnattendedApplicationService(
        paths,
        site_id="site-a",
        repository=repository,
        supervisor=SimpleNamespace(),
    )
    captured: dict[str, object] = {}
    original_ping_series = service.ping_series

    def capture_ping_series(site_id: str, **filters: object):
        captured.update(filters)
        return original_ping_series(site_id, **filters)

    monkeypatch.setattr(service, "ping_series", capture_ping_series)
    result = service.mr_monitoring(
        "site-a",
        mr_uuid=MR_UUID,
        run_id="archive-run",
        start_time=START,
        end_time=END,
    )

    assert captured["max_points"] == 10_000
    assert result.series.raw_sample_count == 3
    assert result.series.success_count == 1
    assert result.series.loss_count == 2


def test_historical_playback_does_not_use_resident_samples_outside_window(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    repository = GroundUnattendedRepository(paths.ground_unattended_db_path("site-a"), site_id="site-a")
    resident = paths.ground_unattended_active_dir("site-a", "2026-11-19") / "heartbeat" / "ct.ndjson"
    _register_ping_file(
        repository,
        resident,
        run_id="heartbeat-resident",
        rows=[_sample("2026-11-19T15:11:01+08:00", "10.82.24.235", ok=True)],
    )
    service = GroundUnattendedApplicationService(
        paths,
        site_id="site-a",
        repository=repository,
        supervisor=SimpleNamespace(),
    )
    assert service._heartbeat_history_source_run_id(
        run_id="archive-run",
        mr_uuid=MR_UUID,
        start=datetime.fromisoformat(START),
        end=datetime.fromisoformat(END),
    ) == "archive-run"
