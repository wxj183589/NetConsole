from __future__ import annotations

import json
import zipfile
from datetime import datetime

from netconsole.core.paths import PathResolver
from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)
from netconsole.services.ground_unattended.archive_service import (
    GroundUnattendedArchiveService,
)


def test_archive_verifies_zip_before_removing_active_data(tmp_path) -> None:
    paths, repo, service, run_id = _setup(tmp_path)
    active = paths.ground_unattended_active_dir("site-a", "2026-07-25")
    (active / "fleet_ping").mkdir(parents=True)
    (active / "fleet_ping" / "ping.jsonl").write_text('{"ok":true}\n', encoding="utf-8")
    repo.upsert_ping_summary(
        {
            "site_id": "site-a",
            "run_id": run_id,
            "bucket_kind": "daily",
            "bucket_start": "2026-07-25T00:00:00+08:00",
            "bucket_end": "2026-07-26T00:00:00+08:00",
            "target_ip": "192.0.2.10",
            "train_id": "train-1",
            "train_no": "01",
            "mr_id": "mr-ct",
            "mr_position_code": "CT",
            "ac_snapshot_id": 1,
            "ap_identity": "",
            "sent_count": 10,
            "success_count": 9,
            "loss_count": 1,
            "loss_rate_percent": 10.0,
            "min_rtt_ms": 1.0,
            "avg_rtt_ms": 2.0,
            "max_rtt_ms": 3.0,
            "continuous_loss_max_count": 1,
            "continuous_loss_max_seconds": 1.0,
            "created_at": "2026-07-25T23:00:00+08:00",
        }
    )
    result = service.archive_run(run_id, repo.get_profile())
    assert result.success
    archive = repo.get_archive(result.archive_id)
    assert archive and archive["archive_status"] == "READY"
    assert not active.exists()
    archive_path = paths.ground_unattended_root("site-a") / archive["relative_path"]
    with zipfile.ZipFile(archive_path) as zipped:
        assert {
            "manifest.json",
            "daily_summary.json",
            "coverage_summary.csv",
            "deep_collection_manifest.json",
            "fleet_ping/",
            "ac_snapshots/",
            "timeline/",
            "ping_summaries/daily_by_mr.json",
            "ping_summaries/daily_by_train.json",
        } <= set(zipped.namelist())
        manifest = json.loads(zipped.read("manifest.json"))
        assert manifest["deep_session_packages_embedded"] is False
        daily_train = json.loads(zipped.read("ping_summaries/daily_by_train.json"))
        assert daily_train["items"][0]["sent_count"] == 10

    first_sha = archive["sha256"]
    repeated = service.archive_run(run_id, repo.get_profile())
    assert repeated.success
    assert repo.get_archive(result.archive_id)["sha256"] == first_sha  # type: ignore[index]


def test_archive_failure_keeps_active_raw_data(tmp_path, monkeypatch) -> None:
    paths, repo, service, run_id = _setup(tmp_path)
    active = paths.ground_unattended_active_dir("site-a", "2026-07-25")
    active.mkdir(parents=True)
    raw = active / "fleet_ping.jsonl"
    raw.write_text("raw\n", encoding="utf-8")
    monkeypatch.setattr(
        service,
        "_write_zip",
        lambda *_args: (_ for _ in ()).throw(OSError("disk full")),
    )
    result = service.archive_run(run_id, repo.get_profile())
    assert not result.success
    assert raw.read_text(encoding="utf-8") == "raw\n"
    assert repo.get_archive(result.archive_id)["message"] == "归档失败，原始数据仍保留"  # type: ignore[index]


def test_corrupted_ready_archive_without_active_data_is_not_overwritten(
    tmp_path,
) -> None:
    paths, repo, service, run_id = _setup(tmp_path)
    first = service.archive_run(run_id, repo.get_profile())
    assert first.success
    archive = repo.get_archive(first.archive_id)
    assert archive is not None
    archive_path = paths.ground_unattended_root("site-a") / archive["relative_path"]
    archive_path.write_bytes(b"corrupted-ready-archive")

    repeated = service.archive_run(run_id, repo.get_profile())

    assert repeated.success is False
    assert archive_path.read_bytes() == b"corrupted-ready-archive"
    failed = repo.get_archive(first.archive_id)
    assert failed is not None
    assert failed["archive_status"] == "FAILED"
    assert failed["message"] == "正式归档校验失败且原始数据不存在，已保留现有文件"


def _setup(tmp_path):
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    repo = GroundUnattendedRepository(
        paths.ground_unattended_db_path("site-a"), site_id="site-a"
    )
    run = repo.create_or_get_run(
        run_id="run-1",
        run_date="2026-07-25",
        scheduled_start_at="2026-07-25T07:00:00+08:00",
        scheduled_end_at="2026-07-25T23:00:00+08:00",
    )
    repo.update_run(
        "run-1",
        state="ARCHIVING",
        actual_ended_at=datetime.now().astimezone().isoformat(),
    )
    return (
        paths,
        repo,
        GroundUnattendedArchiveService(paths, site_id="site-a", repository=repo),
        run["run_id"],
    )
