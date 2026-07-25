from __future__ import annotations

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
        datetime.fromisoformat("2026-07-25T07:00:00+08:00"), "07:00", "23:00", "system"
    )
    assert active.active
    assert active.run_date == "2026-07-25"
    ended = schedule_window(
        datetime.fromisoformat("2026-07-25T23:00:00+08:00"), "07:00", "23:00", "system"
    )
    assert not ended.active
    assert ended.next_start.date().isoformat() == "2026-07-26"


def test_cross_midnight_schedule_uses_start_date() -> None:
    late = schedule_window(
        datetime.fromisoformat("2026-07-25T23:30:00+08:00"), "22:00", "06:00", "system"
    )
    early = schedule_window(
        datetime.fromisoformat("2026-07-26T05:59:00+08:00"), "22:00", "06:00", "system"
    )
    gap = schedule_window(
        datetime.fromisoformat("2026-07-26T12:00:00+08:00"), "22:00", "06:00", "system"
    )
    assert late.active and early.active
    assert late.run_date == early.run_date == "2026-07-25"
    assert not gap.active
    assert gap.next_start.isoformat().startswith("2026-07-26T22:00:00")


def test_profile_persists_updated_schedule(tmp_path) -> None:
    repo = GroundUnattendedRepository(tmp_path / "index.sqlite", site_id="site-a")
    profile = repo.get_profile().model_copy(
        update={
            "enabled": True,
            "schedule_start_time": "08:15",
            "schedule_end_time": "00:30",
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


def test_supervisor_auto_starts_and_finishes_at_window_boundary(tmp_path) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    paths.site_dir("site-a").mkdir(parents=True)
    repo = GroundUnattendedRepository(
        paths.ground_unattended_db_path("site-a"), site_id="site-a"
    )
    repo.save_profile(repo.get_profile().model_copy(update={"enabled": True}))
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
    repo.save_profile(repo.get_profile().model_copy(update={"enabled": True}))
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
