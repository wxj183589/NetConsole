from __future__ import annotations

from types import SimpleNamespace
from datetime import datetime, timedelta

import pytest

from netconsole.backend.api.main import create_app
from netconsole.core.paths import PathResolver
from netconsole.repositories.ground_unattended_repository import GroundUnattendedRepository
from netconsole.services.ground_unattended.application_service import GroundUnattendedError
from netconsole.services.ground_unattended.syslog_runtime import RawStreamWriter


def _operation(repo, identity, *, run="run-a", state="RUNNING", session="", hour=8):
    repo.save_deep_operation({
        "operation_id": identity, "site_id": repo.site_id, "run_id": run,
        "train_id": "train-a", "mr_id": "mr-ct", "mr_position_code": "CT",
        "session_id": session, "state": state,
        "started_at": f"2026-11-07T{hour:02}:00:00+08:00", "updated_at": "",
        "finalization_complete": int(state == "COMPLETED"),
    })


def test_deep_paging_filters_keep_unfiltered_statistics_and_site_scope(tmp_path):
    repo = GroundUnattendedRepository(tmp_path / "ground.sqlite", site_id="site-a")
    repo.initialize()
    repo.upsert_train_state("run-a", "2026-11-07", {
        "train_id": "train-a", "train_no": "0017", "endpoints": [
            {"mr_id": "mr-ct", "endpoint": "CT", "management_ip": "127.0.0.7"},
            {"mr_id": "mr-cw", "endpoint": "CW", "management_ip": "127.0.0.8"},
        ],
    }, ap_identity="", same_ap_since="")
    _operation(repo, "old", state="COMPLETED")
    _operation(repo, "new", hour=9)
    _operation(repo, "other-run", run="run-b")
    result = repo.deep_task_page(run_id="run-a", query="127.0.0.7", page_size=1)
    assert result["total"] == 2
    assert result["items"][0]["operation_id"] == "new"
    assert result["statistics"] == {"task_count": 2, "running": 1, "completed": 1, "failed": 0, "partial": 0}
    assert repo.deep_task_page(run_id="run-a", query="127.0.0.8")["total"] == 0
    assert repo.deep_task_page(run_id="run-a", query="0017", state="COMPLETED")["total"] == 1
    assert repo.deep_task_page(run_id="run-a", ascending=True)["items"][0]["operation_id"] == "old"
    other = GroundUnattendedRepository(repo.db_path, site_id="site-b")
    assert other.deep_task_page(run_id="run-a")["total"] == 0
    assert other.get_deep_operation("old") is None


def test_syslog_cards_are_registered_scope_and_cross_midnight_is_unknown(tmp_path):
    repo = GroundUnattendedRepository(tmp_path / "ground.sqlite", site_id="site-a")
    repo.upsert_raw_file({"file_id": "today", "run_id": "a", "data_type": "syslog", "relative_path": "today.ndjson",
        "start_time": "2026-11-07T01:00:00+08:00", "end_time": "2026-11-07T02:00:00+08:00",
        "record_count": 7, "status": "CLOSED", "parse_status": "IGNORED"})
    window = {"day_start": "2026-11-07T00:00:00+08:00", "day_end": "2026-11-08T00:00:00+08:00"}
    result = repo.syslog_ui_statistics(run_id="a", **window)
    assert result["today_received"] == 7
    assert result["pending_files"] == 0
    assert result["scope"] == "RUN_REGISTERED_INDEX"
    repo.upsert_raw_file({"file_id": "crossing", "run_id": "a", "data_type": "syslog", "relative_path": "crossing.ndjson",
        "start_time": "2026-11-06T23:59:00+08:00", "end_time": "2026-11-07T00:01:00+08:00",
        "record_count": 9, "status": "MISSING", "parse_status": "FAILED"})
    result = repo.syslog_ui_statistics(run_id="a", **window)
    assert result["today_received"] is None
    assert result["raw_missing_files"] == result["parse_failed_files"] == 1
    assert result["data_status"] == "INCOMPLETE"
    assert repo.syslog_ui_statistics(run_id="unrelated", **window)["today_received"] == 0


def test_deep_projects_independent_children_and_exact_historical_operation(tmp_path, monkeypatch):
    app = create_app(paths=PathResolver(tmp_path / "app", tmp_path / "data"))
    service = app.state.ground_unattended_application_service
    repo = service.repository
    repo.create_or_get_run(run_id="run-a", run_date="2026-11-07", scheduled_start_at="", scheduled_end_at="")
    _operation(repo, "old", session="session-old", state="COMPLETED")
    _operation(repo, "new", session="session-new", hour=9)
    children = [SimpleNamespace(name="wmesh", label="WMESH", enabled=True, status="running", size_bytes=12),
                SimpleNamespace(name="rssi", label="RSSI", enabled=True, status="failed", size_bytes=4, last_error="timeout")]
    detail = SimpleNamespace(status="RUNNING", connection_summary={"host": "127.0.0.9"})
    query = SimpleNamespace(get_session=lambda *args: detail,
        list_collectors=lambda *args: children, read_log_chunk=lambda *args, **kwargs: SimpleNamespace(lines=[], next_cursor=0, has_more=False))
    monkeypatch.setattr(service, "_deep_query_service", lambda: query)
    page = service.deep_tasks(repo.site_id, run_id="run-a")
    assert len(page.items) == 2
    assert page.items[0].state == "RUNNING"
    assert page.items[0].management_ip == "127.0.0.9"
    assert [(item.name, item.status) for item in page.items[0].items] == [("wmesh", "running"), ("rssi", "failed")]
    assert page.items[0].items[1].error == "timeout"
    assert page.items[0].progress_kind == "CONTINUOUS"
    old = service.deep_collection_records(repo.site_id, run_id="run-a", operation_id="old")
    assert old.collector.collector_session_id == "session-old"
    assert old.collector.state == "STOPPED"
    with pytest.raises(GroundUnattendedError, match="未找到"):
        service.deep_collection_records(repo.site_id, run_id="run-a", operation_id="old", mr_id="wrong")
    with pytest.raises(GroundUnattendedError, match="开始时间"):
        service.deep_tasks(repo.site_id, run_id="run-a", start_at="2026-11-08", end_at="2026-11-07")
    detail.status = "FAILED"
    detail.error_message = "SSH initialization timeout"
    children.clear()
    failed = service.deep_tasks(repo.site_id, run_id="run-a").items[0]
    assert failed.state == "FAILED"
    assert failed.state_reason == "SSH initialization timeout"


def test_syslog_sort_paginates_actual_receive_time_without_altering_raw(tmp_path):
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    app = create_app(paths=paths)
    service = app.state.ground_unattended_application_service
    repo = service.repository
    repo.create_or_get_run(run_id="run-a", run_date="2026-11-07", scheduled_start_at="", scheduled_end_at="")
    writer = RawStreamWriter(root=paths.ground_unattended_active_dir(repo.site_id, "2026-11-07") / "realtime",
        repository=repo, site_id=repo.site_id, run_id="run-a", run_date="2026-11-07", data_type="syslog", directory_name="syslog")
    start = datetime.now().astimezone() - timedelta(minutes=2)
    try:
        # Arrival order intentionally differs from timestamps.
        for index in (2, 0, 1):
            stamp = start + timedelta(seconds=index)
            writer.write({"receive_time": stamp.isoformat(), "source_ip": "127.0.0.1", "raw_text": f"unaltered {index}"}, stamp)
    finally:
        writer.close()
        assert writer.flush_metadata(timeout=10)
    for order, expected in (("asc", ["unaltered 0", "unaltered 1", "unaltered 2"]), ("desc", ["unaltered 2", "unaltered 1", "unaltered 0"])):
        actual = [service.syslog_records(repo.site_id, run_id="run-a", sort_order=order,
            start_time=start.isoformat(), end_time=(start + timedelta(minutes=1)).isoformat(),
            page=number, page_size=1).items[0].raw_text for number in (1, 2, 3)]
        assert actual == expected
