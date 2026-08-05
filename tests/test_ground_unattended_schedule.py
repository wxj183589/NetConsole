from __future__ import annotations

import socket
from datetime import datetime
from types import SimpleNamespace

from netconsole.core.paths import PathResolver
from netconsole.models.api.ground_unattended import GroundUnattendedProfileDTO
from netconsole.models.api.rail_transit_base_data import RailTransitSummaryDTO
from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)
from netconsole.services.ground_unattended.schedule import schedule_window
from netconsole.services.ground_unattended.supervisor import GroundUnattendedSupervisor


def test_default_and_regular_schedule_window() -> None:
    profile = GroundUnattendedProfileDTO(site_id="site-a")
    assert profile.schedule_start_time == "07:00"
    assert profile.schedule_end_time == "23:00"
    active = schedule_window(
        datetime.fromisoformat("2026-07-25T07:00:00+08:00"), "07:00", "23:00", "Asia/Shanghai"
    )
    assert active.active
    assert active.run_date == "2026-07-25"
    ended = schedule_window(
        datetime.fromisoformat("2026-07-25T23:00:00+08:00"), "07:00", "23:00", "Asia/Shanghai"
    )
    assert not ended.active
    assert ended.next_start.date().isoformat() == "2026-07-26"


def test_cross_midnight_schedule_uses_start_date() -> None:
    late = schedule_window(
        datetime.fromisoformat("2026-07-25T23:30:00+08:00"), "22:00", "06:00", "Asia/Shanghai"
    )
    early = schedule_window(
        datetime.fromisoformat("2026-07-26T05:59:00+08:00"), "22:00", "06:00", "Asia/Shanghai"
    )
    gap = schedule_window(
        datetime.fromisoformat("2026-07-26T12:00:00+08:00"), "22:00", "06:00", "Asia/Shanghai"
    )
    assert late.active and early.active
    assert late.run_date == early.run_date == "2026-07-25"
    assert not gap.active
    assert gap.next_start.isoformat().startswith("2026-07-26T22:00:00")


def test_profile_persists_updated_schedule(tmp_path) -> None:
    repo = GroundUnattendedRepository(tmp_path / "index.sqlite", site_id="site-a")
    assert repo.get_profile().ping_depot_trains_enabled is False
    profile = repo.get_profile().model_copy(
        update={
            "enabled": True,
            "schedule_start_time": "08:15",
            "schedule_end_time": "00:30",
            "ping_depot_trains_enabled": True,
        }
    )
    repo.save_profile(profile)
    loaded = GroundUnattendedRepository(
        tmp_path / "index.sqlite", site_id="site-a"
    ).get_profile()
    assert (loaded.schedule_start_time, loaded.schedule_end_time, loaded.enabled) == (
        "08:15",
        "00:30",
        True,
    )
    assert loaded.ping_depot_trains_enabled is True


def test_train_run_schema_migration_backfills_historical_location_decisions(
    tmp_path,
) -> None:
    path = tmp_path / "index.sqlite"
    repo = GroundUnattendedRepository(path, site_id="site-a")
    repo.create_or_get_run(
        run_id="legacy",
        run_date="2026-07-30",
        scheduled_start_at="2026-07-30T07:00:00+08:00",
        scheduled_end_at="2026-07-30T23:00:00+08:00",
    )
    repo.upsert_train_state(
        "legacy",
        "2026-07-30",
        {
            "train_id": "train-mainline",
            "eligibility_status": "MAINLINE_STATIONARY",
        },
        ap_identity="",
        same_ap_since="",
    )
    repo.upsert_train_state(
        "legacy",
        "2026-07-30",
        {
            "train_id": "train-depot",
            "eligibility_status": "DEPOT",
        },
        ap_identity="",
        same_ap_since="",
    )

    GroundUnattendedRepository(path, site_id="site-a")
    rows = {
        row["train_id"]: row for row in repo.list_train_runs("legacy")
    }

    assert rows["train-mainline"]["location_class"] == "MAINLINE"
    assert rows["train-mainline"]["mainline_eligible"] is True
    assert rows["train-depot"]["location_class"] == "DEPOT"
    assert rows["train-depot"]["mainline_eligible"] is False


def test_running_profile_applies_depot_ping_switch_without_restarting_run() -> None:
    supervisor = object.__new__(GroundUnattendedSupervisor)
    supervisor._active_profile = GroundUnattendedProfileDTO(
        site_id="site-a",
        fleet_ping_interval_ms=1000,
        ping_depot_trains_enabled=False,
    )
    latest = GroundUnattendedProfileDTO(
        site_id="site-a",
        fleet_ping_interval_ms=2500,
        ping_depot_trains_enabled=True,
    )

    effective = supervisor._runtime_profile(latest)

    assert effective.ping_depot_trains_enabled is True
    assert effective.fleet_ping_interval_ms == 1000
    assert supervisor._active_profile.ping_depot_trains_enabled is False


def test_supervisor_auto_starts_and_finishes_at_window_boundary(tmp_path) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    paths.site_dir("site-a").mkdir(parents=True)
    repo = GroundUnattendedRepository(
        paths.ground_unattended_db_path("site-a"), site_id="site-a"
    )
    repo.save_profile(
        repo.get_profile().model_copy(
            update={
                "enabled": True,
                "udp_listen_port": _available_udp_port(),
                "syslog_server_ip": "192.0.2.100",
                "allow_external_syslog_address": True,
            }
        )
    )
    clock = [datetime.fromisoformat("2026-07-25T07:00:00+08:00")]
    supervisor = GroundUnattendedSupervisor(
        paths,
        site_id="site-a",
        repository=repo,
        base_query=_BaseQuery(),  # type: ignore[arg-type]
        mesh_query=_MeshQuery(),  # type: ignore[arg-type]
        vehicle_query=_VehicleQuery(),  # type: ignore[arg-type]
        now_provider=lambda: clock[0],
    )
    supervisor._tick()
    assert repo.get_active_run()["state"] == "RUNNING"  # type: ignore[index]
    clock[0] = datetime.fromisoformat("2026-07-25T23:00:00+08:00")
    supervisor._tick()
    supervisor._tick()
    assert repo.latest_run()["state"] == "COMPLETED"  # type: ignore[index]


def test_manual_stop_does_not_auto_restart_inside_the_same_window(tmp_path) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    paths.site_dir("site-a").mkdir(parents=True)
    repo = GroundUnattendedRepository(
        paths.ground_unattended_db_path("site-a"), site_id="site-a"
    )
    repo.save_profile(
        repo.get_profile().model_copy(
            update={
                "enabled": True,
                "udp_listen_port": _available_udp_port(),
                "syslog_server_ip": "192.0.2.100",
                "allow_external_syslog_address": True,
            }
        )
    )
    clock = [datetime.fromisoformat("2026-07-25T08:00:00+08:00")]
    supervisor = GroundUnattendedSupervisor(
        paths,
        site_id="site-a",
        repository=repo,
        base_query=_BaseQuery(),  # type: ignore[arg-type]
        mesh_query=_MeshQuery(),  # type: ignore[arg-type]
        vehicle_query=_VehicleQuery(),  # type: ignore[arg-type]
        now_provider=lambda: clock[0],
    )

    supervisor._tick()
    run_id = repo.get_active_run()["run_id"]  # type: ignore[index]
    supervisor.request("stop")
    supervisor._tick()
    assert repo.latest_run()["state"] == "COMPLETED"  # type: ignore[index]
    assert repo.latest_run()["requested_action"] == "stop"  # type: ignore[index]

    supervisor._tick()
    assert repo.get_active_run() is None
    assert repo.latest_run()["run_id"] == run_id  # type: ignore[index]

    supervisor.request("start")
    supervisor._tick()
    assert repo.get_active_run()["state"] == "RUNNING"  # type: ignore[index]
    assert repo.get_active_run()["requested_action"] == "manual_start"  # type: ignore[index]
    supervisor._shutdown_active_run()


def test_supervisor_does_not_reopen_ready_archived_run_date(tmp_path) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    paths.site_dir("site-a").mkdir(parents=True)
    repo = GroundUnattendedRepository(
        paths.ground_unattended_db_path("site-a"), site_id="site-a"
    )
    repo.save_profile(
        repo.get_profile().model_copy(
            update={
                "enabled": True,
                "udp_listen_port": _available_udp_port(),
                "syslog_server_ip": "192.0.2.100",
                "allow_external_syslog_address": True,
            }
        )
    )
    run = repo.create_or_get_run(
        run_id="run-archived",
        run_date="2026-07-25",
        scheduled_start_at="2026-07-25T07:00:00+08:00",
        scheduled_end_at="2026-07-25T23:00:00+08:00",
    )
    repo.update_run(
        run["run_id"],
        state="COMPLETED",
        requested_action="restart_after_window",
        actual_ended_at="2026-07-25T08:00:00+08:00",
    )
    repo.upsert_archive(
        {
            "archive_id": "archive-run-archived",
            "site_id": "site-a",
            "run_id": run["run_id"],
            "run_date": run["run_date"],
            "relative_path": "archives/2026-07-25_ground_unattended.zip",
            "archive_status": "READY",
            "archive_size_bytes": 1,
            "sha256": "a" * 64,
            "manifest_sha256": "b" * 64,
            "retention_until": "2026-08-24",
            "active_cleanup_pending": 0,
            "summary_json": "{}",
            "message": "归档完成",
            "created_at": "2026-07-25T08:00:00+08:00",
            "updated_at": "2026-07-25T08:00:00+08:00",
        }
    )
    clock = [datetime.fromisoformat("2026-07-25T09:00:00+08:00")]
    supervisor = GroundUnattendedSupervisor(
        paths,
        site_id="site-a",
        repository=repo,
        base_query=_BaseQuery(),  # type: ignore[arg-type]
        mesh_query=_MeshQuery(),  # type: ignore[arg-type]
        vehicle_query=_VehicleQuery(),  # type: ignore[arg-type]
        now_provider=lambda: clock[0],
    )

    supervisor._tick()
    assert repo.get_active_run() is None
    assert repo.latest_run()["run_id"] == run["run_id"]  # type: ignore[index]
    assert repo.latest_run()["state"] == "COMPLETED"  # type: ignore[index]

    supervisor.request("start")
    supervisor._tick()
    assert repo.get_active_run() is None
    assert repo.count_events(run["run_id"], event_type="start_rejected") == 1


def test_supervisor_reconciles_incomplete_operations_without_active_run(
    tmp_path,
) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    paths.site_dir("site-a").mkdir(parents=True)
    repo = GroundUnattendedRepository(
        paths.ground_unattended_db_path("site-a"), site_id="site-a"
    )
    run = repo.create_or_get_run(
        run_id="run-completed",
        run_date="2026-07-25",
        scheduled_start_at="2026-07-25T07:00:00+08:00",
        scheduled_end_at="2026-07-25T23:00:00+08:00",
    )
    repo.update_run(
        run["run_id"],
        state="COMPLETED",
        actual_ended_at="2026-07-25T08:00:00+08:00",
    )
    repo.save_operation(
        {
            "operation_id": "operation-completed",
            "run_id": run["run_id"],
            "operation_type": "STOP",
            "operation_state": "RUNNING",
            "operation_stage": "FINALIZING",
            "progress_percent": 60,
            "message": "正在保存运行汇总",
        }
    )
    repo.save_operation(
        {
            "operation_id": "operation-orphaned",
            "run_id": "missing-run",
            "operation_type": "STOP_AND_ARCHIVE",
            "operation_state": "PENDING",
            "operation_stage": "STOP_REQUESTED",
            "progress_percent": 5,
            "message": "等待停止",
        }
    )
    supervisor = GroundUnattendedSupervisor(
        paths,
        site_id="site-a",
        repository=repo,
        base_query=_BaseQuery(),  # type: ignore[arg-type]
        mesh_query=_MeshQuery(),  # type: ignore[arg-type]
        vehicle_query=_VehicleQuery(),  # type: ignore[arg-type]
        now_provider=lambda: datetime.fromisoformat("2026-07-25T09:00:00+08:00"),
    )

    supervisor._recover_on_start()

    completed = repo.get_operation("operation-completed")
    orphaned = repo.get_operation("operation-orphaned")
    assert completed is not None
    assert completed["operation_state"] == "COMPLETED"
    assert orphaned is not None
    assert orphaned["operation_state"] == "FAILED"
    assert orphaned["failure_code"] == "GROUND_OPERATION_RECOVERY_INCOMPLETE"


def test_classification_updates_daily_coverage_without_overwriting_results() -> None:
    waiting = SimpleNamespace(
        deep_collection_eligible=True, eligibility_status="MAINLINE"
    )
    excluded = SimpleNamespace(
        deep_collection_eligible=False, eligibility_status="DEPOT"
    )
    offline = SimpleNamespace(
        deep_collection_eligible=False, eligibility_status="OFFLINE"
    )
    assert (
        GroundUnattendedSupervisor._coverage_status_for_classification(None, waiting)
        == "WAITING"
    )
    assert (
        GroundUnattendedSupervisor._coverage_status_for_classification(
            {"coverage_status": "WAITING"}, excluded
        )
        == "EXCLUDED"
    )
    assert (
        GroundUnattendedSupervisor._coverage_status_for_classification(
            {"coverage_status": "EXCLUDED"}, offline
        )
        == "OFFLINE"
    )
    assert (
        GroundUnattendedSupervisor._coverage_status_for_classification(
            {"coverage_status": "COVERED"}, offline
        )
        == "COVERED"
    )


def _available_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class _BaseQuery:
    def get_summary(self, site_id):
        return RailTransitSummaryDTO(site_id=site_id, site_name=site_id)

    def list_mrs(self, *_args, **_kwargs):
        return SimpleNamespace(items=[], total=0)

    def list_stations(self, *_args, **_kwargs):
        return SimpleNamespace(items=[], total=0)

    def list_sections(self, *_args, **_kwargs):
        return SimpleNamespace(items=[], total=0)

    def list_ap_location_items(self, *_args, **_kwargs):
        return []


class _MeshQuery:
    def list_mrs(self, *_args, **_kwargs):
        return SimpleNamespace(items=[], total=0)

    def list_recent_snapshots(self, *_args, **_kwargs):
        return SimpleNamespace(items=[], total=0)


class _VehicleQuery:
    def list_controllers(self, *_args, **_kwargs):
        return []
