from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from netconsole.core.paths import PathResolver
from netconsole.models.api.rail_transit_base_data import RailTransitSummaryDTO
from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)
from netconsole.services.ground_unattended.application_service import (
    GroundUnattendedApplicationService,
)
from netconsole.services.ground_unattended.supervisor import (
    GroundUnattendedSupervisor,
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
    def __init__(self) -> None:
        self.snapshots = [
            self._snapshot(11, "ac-1"),
            self._snapshot(21, "ac-2"),
        ]
        self.snapshot_row_calls: list[int] = []

    @staticmethod
    def _snapshot(snapshot_id: int, controller_id: str):
        return SimpleNamespace(
            id=snapshot_id,
            controller_id=controller_id,
            controller_name=controller_id,
            collected_at=f"2026-07-29T08:00:{snapshot_id % 60:02d}+08:00",
            ac_time="2026-07-29T08:00:00+08:00",
            data_status="fresh",
            source_reference=f"snapshot:{snapshot_id}",
        )

    def list_latest_snapshots_by_controller(self, _site_id):
        return list(self.snapshots)

    def list_mrs_for_snapshot(self, _site_id, snapshot_id):
        self.snapshot_row_calls.append(snapshot_id)
        return [
            SimpleNamespace(
                train_no=f"train-{snapshot_id}",
                mr_device_id=f"mr-{snapshot_id}",
                mr_id=f"mr-{snapshot_id}",
                mr_name=f"MR {snapshot_id}",
                car_end="CT",
                management_ip="",
                online_status="online",
                peer_ap_id="",
                peer_ap_name=f"ap-{snapshot_id}",
                peer_ap_mac=f"00:00:00:00:00:{snapshot_id % 100:02d}",
                station="",
                section="",
                mileage="",
                rssi=-60,
                data_status="fresh",
                last_seen_at=f"2026-07-29T08:00:{snapshot_id % 60:02d}+08:00",
            )
        ]


class _VehicleQuery:
    def list_controllers(self, *_args, **_kwargs):
        return []


def _supervisor(
    tmp_path: Path,
) -> tuple[GroundUnattendedSupervisor, GroundUnattendedRepository, _MeshQuery]:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    paths.site_dir("site-a").mkdir(parents=True)
    repository = GroundUnattendedRepository(
        paths.ground_unattended_db_path("site-a"),
        site_id="site-a",
    )
    run = repository.create_or_get_run(
        run_id="run-1",
        run_date="2026-07-29",
        scheduled_start_at="2026-07-29T07:00:00+08:00",
        scheduled_end_at="2026-07-29T23:00:00+08:00",
    )
    repository.update_run(str(run["run_id"]), state="RUNNING")
    mesh = _MeshQuery()
    supervisor = GroundUnattendedSupervisor(
        paths,
        site_id="site-a",
        repository=repository,
        base_query=_BaseQuery(),  # type: ignore[arg-type]
        mesh_query=mesh,  # type: ignore[arg-type]
        vehicle_query=_VehicleQuery(),  # type: ignore[arg-type]
    )
    return supervisor, repository, mesh


def test_supervisor_processes_each_controller_snapshot_only_once(
    tmp_path: Path,
) -> None:
    supervisor, repository, mesh = _supervisor(tmp_path)
    run = repository.get_active_run()
    assert run is not None
    profile = repository.get_profile()
    now = datetime.fromisoformat("2026-07-29T08:01:00+08:00")

    supervisor._poll_ac_and_classify(
        run, profile, now, scheduling_paused=False
    )
    supervisor._poll_ac_and_classify(
        run, profile, now, scheduling_paused=True
    )

    assert mesh.snapshot_row_calls == [11, 21]
    assert supervisor._last_processed_snapshot_id_by_controller == {
        "ac-1": 11,
        "ac-2": 21,
    }
    saved = repository.get_run("run-1")
    assert saved is not None
    assert saved["summary"]["ac_last_processed_snapshot_ids"] == {
        "ac-1": 11,
        "ac-2": 21,
    }
    assert saved["state"] == "PAUSED"
    first_ac_2_row = repository.latest_ac_snapshot(
        "run-1", "mesh:train:21", "mr-21"
    )
    assert first_ac_2_row is not None

    mesh.snapshots[0] = mesh._snapshot(12, "ac-1")
    supervisor._poll_ac_and_classify(
        saved, profile, now, scheduling_paused=False
    )
    assert mesh.snapshot_row_calls == [11, 21, 12, 21]
    assert supervisor._last_processed_snapshot_id_by_controller == {
        "ac-1": 12,
        "ac-2": 21,
    }
    second_ac_2_row = repository.latest_ac_snapshot(
        "run-1", "mesh:train:21", "mr-21"
    )
    assert second_ac_2_row is not None
    assert second_ac_2_row["id"] == first_ac_2_row["id"]


class _DeepScheduler:
    def __init__(self, *, active: bool) -> None:
        self.active = active
        self.stop_calls = 0

    def stop_all(self, *_args, **_kwargs) -> None:
        self.stop_calls += 1

    def tick(self, *_args, **_kwargs) -> None:
        return None

    def has_active_automated(self) -> bool:
        return self.active


class _ResidentService:
    def __init__(
        self,
        *,
        stop_success: bool = True,
        statuses: list[dict[str, object]] | None = None,
    ) -> None:
        self.stop_success = stop_success
        self.statuses = statuses or []
        self.stop_calls: list[dict[str, object]] = []

    def request_stop_run(self, **values):
        self.stop_calls.append(values)
        return SimpleNamespace(
            success=self.stop_success,
            pollers=(
                {
                    "controller_id": "ac-1",
                    "task_id": "resident-1",
                    "connection_state": "BACKOFF",
                    "stopped": self.stop_success,
                    "forced": not self.stop_success,
                },
            ),
        )

    def list_statuses(self, **_values):
        return list(self.statuses)


def test_application_shutdown_requests_normal_ac_stop_before_deep_jobs_finish(
    tmp_path: Path,
) -> None:
    supervisor, repository, _mesh = _supervisor(tmp_path)
    resident = _ResidentService()
    deep = _DeepScheduler(active=True)
    supervisor.ac_resident_service = resident  # type: ignore[assignment]
    supervisor.deep_scheduler = deep  # type: ignore[assignment]

    supervisor._shutdown_active_run()

    assert deep.stop_calls == 1
    assert resident.stop_calls == [
        {
            "site_name": "site-a",
            "run_id": "run-1",
            "timeout_seconds": 25.0,
        }
    ]
    run = repository.get_run("run-1")
    assert run is not None
    assert run["state"] == "FINALIZING"
    operation = repository.latest_operation(run_id="run-1")
    assert operation is not None
    assert operation["operation_stage"] == "STOPPING_AC_POLLER"


def test_ac_poller_stop_timeout_keeps_controller_diagnostics(
    tmp_path: Path,
) -> None:
    supervisor, repository, _mesh = _supervisor(tmp_path)
    supervisor.ac_resident_service = _ResidentService(  # type: ignore[assignment]
        stop_success=False
    )
    run = repository.get_active_run()
    assert run is not None

    supervisor._finalize_run(run, archive=False)

    operation = repository.latest_operation(run_id="run-1")
    assert operation is not None
    assert operation["operation_state"] == "FAILED"
    assert operation["failure_code"] == "AC_POLLER_STOP_TIMEOUT"
    assert operation["result_summary"]["ac_pollers"][0] == {
        "controller_id": "ac-1",
        "task_id": "resident-1",
        "connection_state": "BACKOFF",
        "stopped": False,
        "forced": True,
    }


def test_ac_health_marks_backoff_degraded_and_keeps_failed_poller(
    tmp_path: Path,
) -> None:
    supervisor, repository, _mesh = _supervisor(tmp_path)
    now = datetime.now().astimezone()
    resident = _ResidentService(
        statuses=[
            {
                "controller_id": "ac-1",
                "controller_name": "AC 1",
                "task_id": "resident-1",
                "run_id": "run-1",
                "connection_state": "BACKOFF",
                "heartbeat_at": now.isoformat(timespec="milliseconds"),
                "last_success_at": (now - timedelta(seconds=1)).isoformat(
                    timespec="milliseconds"
                ),
                "poll_interval_seconds": 10,
            },
            {
                "controller_id": "ac-2",
                "controller_name": "AC 2",
                "task_id": "resident-2",
                "run_id": "run-1",
                "connection_state": "FAILED",
                "heartbeat_at": now.isoformat(timespec="milliseconds"),
                "last_error_message": "凭据不可用",
            },
        ]
    )
    supervisor.ac_resident_service = resident  # type: ignore[assignment]
    service = GroundUnattendedApplicationService(
        supervisor.paths,
        site_id="site-a",
        repository=repository,
        supervisor=supervisor,
    )

    health = service.health("site-a")

    assert [(item.controller_id, item.status) for item in health.ac_pollers] == [
        ("ac-1", "DEGRADED"),
        ("ac-2", "FAILED"),
    ]
    assert health.status == "ERROR"
    assert health.ac_pollers[1].last_error == "凭据不可用"
