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
        } <= set(zipped.namelist())
        manifest = json.loads(zipped.read("manifest.json"))
        assert manifest["deep_session_packages_embedded"] is False


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
