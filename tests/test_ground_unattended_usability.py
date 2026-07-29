from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from netconsole.core.paths import PathResolver
from netconsole.core.ping.fping_v5_models import BACKEND, FpingV5Sample
from netconsole.models.api.ground_unattended import GroundUnattendedProfileDTO
from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)
from netconsole.services.ground_unattended.application_service import (
    GroundUnattendedApplicationService,
)
from netconsole.services.ground_unattended.fleet_ping import (
    FleetPingSupervisor,
    FleetPingTarget,
)
from netconsole.services.ground_unattended.raw_query import (
    GroundRawQueryError,
    GroundRawStreamQueryService,
)
from netconsole.services.ground_unattended.supervisor import (
    GroundUnattendedSupervisor,
)
from netconsole.services.ground_unattended.syslog_runtime import RawStreamWriter


def test_profile_migrates_legacy_timezone_and_persists_lightweight_mode(
    tmp_path,
) -> None:
    db_path = tmp_path / "ground" / "index.sqlite"
    repository = GroundUnattendedRepository(db_path, site_id="site-a")
    repository.save_profile(
        GroundUnattendedProfileDTO(
            site_id="site-a",
            timezone="system",
            deep_collection_master_enabled=False,
            fleet_ping_warmup_seconds=17,
        )
    )

    migrated = GroundUnattendedRepository(
        db_path, site_id="site-a"
    ).get_profile()

    assert migrated.timezone == "Asia/Shanghai"
    assert migrated.deep_collection_master_enabled is False
    assert migrated.fleet_ping_warmup_seconds == 17


def test_fleet_ping_warmup_is_per_target_persisted_and_restarts_after_readd(
    tmp_path,
) -> None:
    repository = GroundUnattendedRepository(
        tmp_path / "ground" / "index.sqlite", site_id="site-a"
    )
    active = tmp_path / "ground" / "active" / "2026-07-28"
    fleet = FleetPingSupervisor(
        repository=repository, site_id="site-a", runner=_idle_runner
    )
    fleet.start(
        run_id="run-warmup",
        run_date="2026-07-28",
        active_dir=active,
        period_ms=1000,
        timeout_ms=4000,
        packet_size=64,
        shard_size=12,
        correlation_tolerance_seconds=15,
        switch_before_seconds=5,
        switch_after_seconds=5,
        warmup_seconds=10,
    )
    target = _target()
    fleet.update_targets([target])
    activated_at = fleet.target_summaries()[0]["started_at"]
    activated = datetime.fromisoformat(activated_at)
    fleet._record_sample(_sample(activated + timedelta(seconds=9.999), 1), "shard-test")
    fleet._record_sample(_sample(activated + timedelta(seconds=10), 2), "shard-test")

    summary = fleet.target_summaries()[0]
    assert summary["raw_sample_count"] == 2
    assert summary["effective_sample_count"] == 1
    assert summary["warmup_ignored_count"] == 1
    assert summary["sent_count"] == 1
    assert fleet.stop()["success"] is True

    raw_file = repository.list_raw_files(data_type="ping", limit=10)[0]
    rows = [
        json.loads(line)
        for line in (
            repository.db_path.parent / raw_file["relative_path"]
        ).read_text(encoding="utf-8").splitlines()
    ]
    assert [row["warmup_ignored"] for row in rows] == [True, False]

    recovered = FleetPingSupervisor(
        repository=repository, site_id="site-a", runner=_idle_runner
    )
    recovered.start(
        run_id="run-warmup",
        run_date="2026-07-28",
        active_dir=active,
        period_ms=1000,
        timeout_ms=4000,
        packet_size=64,
        shard_size=12,
        correlation_tolerance_seconds=15,
        switch_before_seconds=5,
        switch_after_seconds=5,
        warmup_seconds=10,
    )
    recovered.update_targets([target])
    assert recovered.target_summaries()[0]["started_at"] == activated_at
    recovered.update_targets([])
    time.sleep(0.01)
    recovered.update_targets([target])
    assert recovered.target_summaries()[0]["started_at"] != activated_at
    assert recovered.stop()["success"] is True


def test_raw_queries_preserve_loss_points_page_syslog_and_reject_path_escape(
    tmp_path,
) -> None:
    repository = GroundUnattendedRepository(
        tmp_path / "ground" / "index.sqlite", site_id="site-a"
    )
    root = repository.db_path.parent / "active" / "2026-07-28"
    now = datetime.now().astimezone()
    ping_writer = RawStreamWriter(
        root=root,
        repository=repository,
        site_id="site-a",
        run_id="run-query",
        run_date="2026-07-28",
        data_type="ping",
        directory_name="fleet_ping",
        flush_records=1,
    )
    for index in range(50):
        ping_writer.write(
            {
                "sample_id": f"sample-{index}",
                "ts": (now + timedelta(seconds=index)).isoformat(
                    timespec="milliseconds"
                ),
                "target_ip": "192.0.2.10",
                "train_id": "train-1",
                "train_no": "04",
                "mr_id": "mr-ct",
                "mr_name": "NBL12-LC04-MR-CT",
                "mr_position_code": "CT",
                "mr_role": "CT",
                "seq": index,
                "ok": index != 23,
                "rtt_ms": None if index == 23 else float(index),
                "timeout_ms": 4000,
                "packet_size": 64,
                "current_ap_name": "AP-01",
                "station": "站点 A",
                "section": "A-B",
                "position_quality": "MATCHED",
                "warmup_ignored": index < 2,
            },
            now + timedelta(seconds=index),
        )
    ping_writer.close()

    syslog_writer = RawStreamWriter(
        root=root / "realtime",
        repository=repository,
        site_id="site-a",
        run_id="run-query",
        run_date="2026-07-28",
        data_type="syslog",
        flush_records=1,
    )
    for index in range(3):
        syslog_writer.write(
            {
                "receive_time": (now + timedelta(seconds=index)).isoformat(
                    timespec="milliseconds"
                ),
                "device_time": (now + timedelta(seconds=index - 1)).isoformat(
                    timespec="milliseconds"
                ),
                "source_ip": "192.0.2.20",
                "source_port": 514,
                "hostname": "MR-CT",
                "system_name": "MR-CT",
                "facility": "local7",
                "severity": "info",
                "train_id": "train-1",
                "train_no": "04",
                "device_uuid": "mr-ct",
                "mr_name": "NBL12-LC04-MR-CT",
                "mr_role": "CT",
                "identity_status": "VERIFIED",
                "parse_status": "PARSED",
                "data_quality": "COMPLETE",
                "raw_text": f"WMESH event {index}",
            },
            now + timedelta(seconds=index),
        )

    query = GroundRawStreamQueryService(repository)
    series = query.ping_series(
        run_id="run-query",
        target_ip="192.0.2.10",
        start_time=(now - timedelta(seconds=1)).isoformat(),
        end_time=(now + timedelta(minutes=1)).isoformat(),
        max_points=10,
    )
    assert series["raw_sample_count"] == 50
    assert series["effective_sample_count"] == 48
    assert series["ignored_sample_count"] == 2
    assert any(not row["ok"] for row in series["points"])
    assert series["loss_windows"][0]["loss_count"] == 1

    active_page = query.syslog_records(
        run_id="run-query",
        start_time=(now - timedelta(seconds=1)).isoformat(),
        end_time=(now + timedelta(minutes=1)).isoformat(),
        page=1,
        page_size=2,
    )
    assert active_page["total"] == 3
    assert len(active_page["items"]) == 2
    assert all(row["raw_file_status"] == "OPEN" for row in active_page["items"])
    syslog_writer.close()
    closed_page = query.syslog_records(
        run_id="run-query",
        start_time=(now - timedelta(seconds=1)).isoformat(),
        end_time=(now + timedelta(minutes=1)).isoformat(),
        page=2,
        page_size=2,
    )
    assert closed_page["items"][0]["mr_name"] == "NBL12-LC04-MR-CT"
    assert closed_page["items"][0]["raw_file_status"] == "CLOSED"

    repository.upsert_raw_file(
        {
            "file_id": "unsafe",
            "run_id": "run-query",
            "data_type": "ping",
            "relative_path": "../outside.ndjson",
            "status": "CLOSED",
        }
    )
    try:
        query.ping_series(run_id="run-query")
    except GroundRawQueryError as exc:
        assert "数据根之外" in str(exc)
    else:
        raise AssertionError("path escape must be rejected")


def test_raw_query_rejects_registered_symbolic_link(tmp_path) -> None:
    repository = GroundUnattendedRepository(
        tmp_path / "ground" / "index.sqlite", site_id="site-a"
    )
    outside = tmp_path / "outside.ndjson"
    outside.write_text(
        json.dumps(
            {
                "ts": datetime.now().astimezone().isoformat(),
                "target_ip": "192.0.2.10",
                "ok": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    link = repository.db_path.parent / "linked.ndjson"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"当前 Windows 环境不能创建测试符号链接：{exc}")
    repository.upsert_raw_file(
        {
            "file_id": "linked",
            "run_id": "run-query",
            "data_type": "ping",
            "relative_path": link.relative_to(repository.db_path.parent).as_posix(),
            "status": "CLOSED",
        }
    )

    with pytest.raises(GroundRawQueryError, match="符号链接"):
        GroundRawStreamQueryService(repository).ping_series(run_id="run-query")


def test_timeline_resolves_device_name_and_stop_operation_is_idempotent(
    tmp_path,
) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    repository = GroundUnattendedRepository(
        paths.ground_unattended_db_path("site-a"), site_id="site-a"
    )
    repository.sync_inventory(
        trains=[
            {"train_id": "train-1", "train_no": "04", "train_name": "列车 04"}
        ],
        endpoints=[
            {
                "device_uuid": "b15363cc-ec3b-4028-a90d-1234567890ab",
                "device_id": 4,
                "train_id": "train-1",
                "mr_role": "CW",
                "device_name": "NBL12-LC04-MR-CW",
                "management_ip": "192.0.2.44",
            }
        ],
    )
    run = repository.create_or_get_run(
        run_id="run-stop",
        run_date="2026-07-28",
        scheduled_start_at=now_text(),
        scheduled_end_at=now_text(),
    )
    repository.update_run(
        str(run["run_id"]), state="RUNNING", actual_started_at=now_text()
    )
    repository.add_event(
        run_id="run-stop",
        event_type="mesh_linkup",
        train_id="train-1",
        mr_id="b15363cc-ec3b-4028-a90d-1234567890ab",
        title="WMESH 链路建立",
    )
    request_log: list[tuple[str, bool, str]] = []
    application = GroundUnattendedApplicationService(
        paths,
        site_id="site-a",
        repository=repository,
        supervisor=SimpleNamespace(
            fleet_ping=SimpleNamespace(target_summaries=lambda: []),
            request=lambda action, archive=False, operation_id="": request_log.append(
                (action, archive, operation_id)
            ),
        ),
    )

    timeline = application.timeline("site-a")
    assert timeline.items[0].mr_name == "NBL12-LC04-MR-CW"
    assert timeline.items[0].mr_position_code == "CW"

    repository.save_operation(
        {
            "operation_id": "groundop_previous",
            "run_id": "run-previous",
            "operation_type": "STOP",
            "operation_state": "COMPLETED",
            "operation_stage": "COMPLETED",
            "progress_percent": 100,
            "message": "旧运行已停止",
        }
    )
    assert (
        application.latest_operation("site-a").operation_id
        == "groundop_previous"
    )

    first = application.stop("site-a", archive=False)
    second = application.stop("site-a", archive=False)
    assert first.operation_id == second.operation_id
    assert len(request_log) == 1
    assert application.active_operation("site-a").operation_id == first.operation_id
    assert (
        application.latest_operation("site-a").operation_id
        == "groundop_previous"
    )

    supervisor = object.__new__(GroundUnattendedSupervisor)
    supervisor.repository = repository
    supervisor.paths = paths
    supervisor.site_id = "site-a"
    supervisor.deep_scheduler = None
    supervisor.fleet_ping = SimpleNamespace(
        stop=lambda: {
            "success": True,
            "sample_count": 12,
            "fping_processes_exited": True,
        }
    )
    supervisor.syslog_receiver = SimpleNamespace(
        stop=lambda: {
            "success": True,
            "received_count": 9,
            "closed_file_count": 2,
            "dropped_count": 0,
            "udp_port_released": True,
        }
    )
    supervisor.archive_service = SimpleNamespace()
    supervisor._active_profile = None
    supervisor._manual_start = False
    supervisor._last_valid_ping_targets = {}
    supervisor.now_provider = lambda: datetime.now().astimezone()
    GroundUnattendedSupervisor._finalize_run(
        supervisor, repository.get_run("run-stop"), archive=False
    )

    operation = repository.get_operation(first.operation_id)
    assert operation is not None
    assert operation["operation_state"] == "COMPLETED"
    assert operation["operation_stage"] == "COMPLETED"
    assert operation["result_summary"]["udp_port_released"] is True
    assert repository.get_run("run-stop")["state"] == "COMPLETED"


def _idle_runner(*, stop_event, **_kwargs):
    while not stop_event.wait(0.01):
        if False:
            yield None


def _target() -> FleetPingTarget:
    return FleetPingTarget(
        target_ip="192.0.2.10",
        train_id="train-1",
        train_no="04",
        mr_id="mr-ct",
        mr_name="NBL12-LC04-MR-CT",
        mr_position_code="CT",
        current_ap_identity="ap:1",
        current_ap_name="AP-01",
        station="站点 A",
        section="A-B",
    )


def _sample(ts: datetime, seq: int) -> FpingV5Sample:
    return FpingV5Sample(
        ts=ts.isoformat(timespec="milliseconds"),
        target="192.0.2.10",
        seq=seq,
        ok=True,
        rtt_ms=3.2,
        timeout_ms=4000,
        size=64,
        error="",
        backend=BACKEND,
        raw_type="response",
        raw={},
    )


def now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")
