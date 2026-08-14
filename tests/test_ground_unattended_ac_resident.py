from __future__ import annotations

from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from netconsole.core.paths import PathResolver
from netconsole.models.api.rail_transit_base_data import RailTransitSummaryDTO
from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)
from netconsole.services.ground_unattended.application_service import (
    GroundUnattendedApplicationService,
    GroundUnattendedError,
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
    def __init__(
        self,
        *,
        active: bool,
        active_ids: list[str] | None = None,
        force_completes: bool = True,
    ) -> None:
        self.active = active
        self.active_ids = active_ids or (["deep-1"] if active else [])
        self.force_completes = force_completes
        self.stop_calls = 0
        self.force_stop_calls: list[str] = []
        self.recover_calls: list[str] = []

    def recover(self, run_id: str) -> None:
        self.recover_calls.append(run_id)

    def stop_all(self, *_args, **_kwargs) -> None:
        self.stop_calls += 1

    def tick(self, *_args, **_kwargs) -> None:
        return None

    def has_active_automated(self) -> bool:
        return self.active

    def active_automated_operation_ids(self) -> list[str]:
        return list(self.active_ids)

    def force_stop_all(self, run_id: str, *, reason: str) -> list[str]:
        self.force_stop_calls.append(reason)
        operation_ids = list(self.active_ids)
        if self.force_completes:
            self.active = False
            self.active_ids = []
        return operation_ids


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


class _FleetPingRecorder:
    def __init__(self) -> None:
        self.started = False
        self.target_updates: list[list[object]] = []

    def start(self, **_values) -> None:
        self.started = True

    def update_targets(self, targets) -> None:
        self.target_updates.append(list(targets))


def test_application_shutdown_quiesces_process_without_stopping_business_run(
    tmp_path: Path,
) -> None:
    supervisor, repository, _mesh = _supervisor(tmp_path)
    resident = _ResidentService()
    deep = _DeepScheduler(active=True)
    supervisor.ac_resident_service = resident  # type: ignore[assignment]
    supervisor.deep_scheduler = deep  # type: ignore[assignment]

    supervisor._shutdown_active_run()

    assert deep.stop_calls == 0
    assert resident.stop_calls == []
    run = repository.get_run("run-1")
    assert run is not None
    assert run["state"] == "RUNNING"
    operation = repository.latest_operation(run_id="run-1")
    assert operation is None
    events = repository.list_events("run-1", event_type="backend_shutdown_quiesced")
    assert len(events) == 1
    assert events[0]["details"]["stop_trigger"] == "BACKEND_SHUTDOWN"


def test_user_stop_intent_is_persisted_before_supervisor_command_runs(
    tmp_path: Path,
) -> None:
    supervisor, repository, _mesh = _supervisor(tmp_path)
    service = GroundUnattendedApplicationService(
        supervisor.paths,
        site_id="site-a",
        repository=repository,
        supervisor=supervisor,
        base_query=_BaseQuery(),  # type: ignore[arg-type]
    )

    response = service.stop("site-a", archive=True)

    run = repository.get_run("run-1")
    operation = repository.get_operation(response.operation_id)
    assert run is not None and run["state"] == "STOPPING"
    assert run["requested_action"] == "stop_and_archive"
    assert operation is not None and operation["operation_state"] == "PENDING"
    assert operation["stop_trigger"] == "USER_STOP_AND_ARCHIVE"

    supervisor._handle_commands()
    operation = repository.get_operation(response.operation_id)
    assert operation is not None and operation["previous_state"] == "RUNNING"


def test_concurrent_stop_requests_share_one_durable_operation(tmp_path: Path) -> None:
    supervisor, repository, _mesh = _supervisor(tmp_path)
    service = GroundUnattendedApplicationService(
        supervisor.paths,
        site_id="site-a",
        repository=repository,
        supervisor=supervisor,
        base_query=_BaseQuery(),  # type: ignore[arg-type]
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(lambda archive: service.stop("site-a", archive=archive), [False, True])
        )

    active = repository.list_operations(run_id="run-1", active_only=True)
    assert len(active) == 1
    assert {response.operation_id for response in responses} == {active[0]["operation_id"]}
    assert len(supervisor._commands) == 1


def test_stop_intent_is_not_overwritten_by_pause_or_resume(tmp_path: Path) -> None:
    supervisor, repository, _mesh = _supervisor(tmp_path)
    service = GroundUnattendedApplicationService(
        supervisor.paths,
        site_id="site-a",
        repository=repository,
        supervisor=supervisor,
        base_query=_BaseQuery(),  # type: ignore[arg-type]
    )

    response = service.stop("site-a", archive=True)

    with pytest.raises(GroundUnattendedError, match="仅运行中的") as pause_error:
        service.pause("site-a")
    assert pause_error.value.code == "RUN_NOT_PAUSABLE"
    with pytest.raises(GroundUnattendedError, match="仅已暂停的") as resume_error:
        service.resume("site-a")
    assert resume_error.value.code == "RUN_NOT_RESUMABLE"

    # 模拟在 stop 已持久化后仍滞留于队列中的旧命令，消费端必须再次校验状态。
    supervisor.request("pause")
    supervisor.request("resume")
    supervisor._handle_commands()

    run = repository.get_run("run-1")
    operation = repository.get_operation(response.operation_id)
    assert run is not None and run["state"] == "STOPPING"
    assert run["requested_action"] == "stop_and_archive"
    assert operation is not None and operation["operation_state"] == "RUNNING"


def test_pause_and_resume_only_allow_exact_state_transitions(tmp_path: Path) -> None:
    supervisor, repository, _mesh = _supervisor(tmp_path)
    service = GroundUnattendedApplicationService(
        supervisor.paths,
        site_id="site-a",
        repository=repository,
        supervisor=supervisor,
        base_query=_BaseQuery(),  # type: ignore[arg-type]
    )

    with pytest.raises(GroundUnattendedError) as resume_error:
        service.resume("site-a")
    assert resume_error.value.code == "RUN_NOT_RESUMABLE"

    service.pause("site-a")
    supervisor._handle_commands()
    assert repository.get_run("run-1")["state"] == "PAUSED"

    with pytest.raises(GroundUnattendedError) as pause_error:
        service.pause("site-a")
    assert pause_error.value.code == "RUN_NOT_PAUSABLE"

    service.resume("site-a")
    supervisor._handle_commands()
    assert repository.get_run("run-1")["state"] == "RUNNING"


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


def test_restart_recovers_legacy_application_shutdown_inside_frozen_window(
    tmp_path: Path,
) -> None:
    supervisor, repository, _mesh = _supervisor(tmp_path)
    repository.save_profile(repository.get_profile().model_copy(update={"enabled": True}))
    repository.update_run(
        "run-1", state="FINALIZING", requested_action="application_shutdown"
    )
    deep = _DeepScheduler(active=False)
    supervisor.deep_scheduler = deep  # type: ignore[assignment]
    supervisor.now_provider = lambda: datetime.fromisoformat(
        "2026-07-29T11:46:00+08:00"
    )
    supervisor._network_profile_error = lambda _profile: None  # type: ignore[method-assign]
    supervisor.inventory_sync = SimpleNamespace(synchronize=lambda: None)  # type: ignore[assignment]
    supervisor._start_fleet_ping = lambda *_args: None  # type: ignore[method-assign]
    supervisor._start_syslog = lambda *_args: None  # type: ignore[method-assign]
    supervisor._ensure_ac_resident_pollers = lambda *_args: None  # type: ignore[method-assign]

    supervisor._recover_on_start()

    run = repository.get_run("run-1")
    assert run is not None and run["state"] == "RUNNING"
    assert run["requested_action"] == "recovered_after_shutdown"
    assert deep.recover_calls == ["run-1"]


def test_restart_keeps_persisted_user_archive_intent_over_shutdown_marker(
    tmp_path: Path,
) -> None:
    supervisor, repository, _mesh = _supervisor(tmp_path)
    repository.save_profile(repository.get_profile().model_copy(update={"enabled": True}))
    repository.update_run(
        "run-1", state="FINALIZING", requested_action="application_shutdown"
    )
    repository.save_operation(
        {
            "operation_id": "user-archive",
            "site_id": "site-a",
            "run_id": "run-1",
            "operation_type": "STOP_AND_ARCHIVE",
            "operation_state": "PENDING",
            "operation_stage": "STOP_REQUESTED",
            "progress_percent": 0,
            "message": "停止并归档请求已提交",
            "stop_trigger": "USER_STOP_AND_ARCHIVE",
            "requested_by": "local_user",
            "started_at": "2026-07-29T11:45:00+08:00",
            "updated_at": "2026-07-29T11:45:00+08:00",
        }
    )
    deep = _DeepScheduler(active=False)
    supervisor.deep_scheduler = deep  # type: ignore[assignment]
    supervisor.now_provider = lambda: datetime.fromisoformat(
        "2026-07-29T11:46:00+08:00"
    )

    supervisor._recover_on_start()

    run = repository.get_run("run-1")
    operation = repository.get_operation("user-archive")
    assert run is not None and run["state"] == "STOPPING"
    assert run["requested_action"] == "stop_and_archive"
    assert operation is not None and operation["operation_state"] == "PENDING"
    assert operation["stop_trigger"] == "USER_STOP_AND_ARCHIVE"
    assert deep.recover_calls == ["run-1"]


def test_legacy_backend_shutdown_operation_keeps_backend_reason_and_continues(
    tmp_path: Path,
) -> None:
    supervisor, repository, _mesh = _supervisor(tmp_path)
    repository.update_run(
        "run-1", state="FINALIZING", requested_action="application_shutdown"
    )
    repository.save_operation(
        {
            "operation_id": "legacy-backend-stop",
            "site_id": "site-a",
            "run_id": "run-1",
            "operation_type": "STOP",
            "operation_state": "RUNNING",
            "operation_stage": "STOPPING_AC_POLLER",
            "progress_percent": 22,
            "message": "正在停止 AC 常驻轮询",
            "started_at": "2026-07-29T11:45:00+08:00",
            "updated_at": "2026-07-29T11:45:00+08:00",
        }
    )
    deep = _DeepScheduler(active=False)
    supervisor.deep_scheduler = deep  # type: ignore[assignment]

    supervisor._recover_on_start()

    run = repository.get_run("run-1")
    operation = repository.get_operation("legacy-backend-stop")
    assert run is not None and run["state"] == "FINALIZING"
    assert operation is not None
    assert operation["stop_trigger"] == "BACKEND_SHUTDOWN"
    assert "旧版本 Backend 退出" in operation["stop_reason"]
    assert deep.recover_calls == ["run-1"]


def test_restart_backfills_missing_frozen_window_before_next_tick(
    tmp_path: Path,
) -> None:
    supervisor, repository, _mesh = _supervisor(tmp_path)
    repository.save_profile(repository.get_profile().model_copy(update={"enabled": True}))
    repository.update_run("run-1", scheduled_start_at="", scheduled_end_at="")
    supervisor.now_provider = lambda: datetime.fromisoformat(
        "2026-07-29T11:46:00+08:00"
    )
    supervisor._network_profile_error = lambda _profile: None  # type: ignore[method-assign]
    supervisor.inventory_sync = SimpleNamespace(synchronize=lambda: None)  # type: ignore[assignment]
    supervisor._start_fleet_ping = lambda *_args: None  # type: ignore[method-assign]
    supervisor._start_syslog = lambda *_args: None  # type: ignore[method-assign]
    supervisor._ensure_ac_resident_pollers = lambda *_args: None  # type: ignore[method-assign]
    supervisor._poll_if_due = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

    supervisor._recover_on_start()
    supervisor._tick()

    run = repository.get_run("run-1")
    assert run is not None and run["state"] == "RUNNING"
    assert run["scheduled_start_at"].startswith("2026-07-29T07:00:00")
    assert run["scheduled_end_at"].startswith("2026-07-29T23:00:00")
    assert repository.latest_operation(run_id="run-1") is None


def test_restart_restores_persisted_ping_targets_without_new_ac_snapshot(
    tmp_path: Path,
) -> None:
    supervisor, repository, _mesh = _supervisor(tmp_path)
    repository.save_profile(
        repository.get_profile().model_copy(
            update={"enabled": True, "ac_stale_grace_seconds": 180}
        )
    )
    repository.update_run(
        "run-1",
        summary_json={"ac_last_processed_snapshot_ids": {"ac-1": 11, "ac-2": 21}},
    )
    repository.upsert_train_state(
        "run-1",
        "2026-07-29",
        {
            "train_id": "train-02",
            "train_no": "02",
            "train_name": "列车02",
            "ping_eligible": True,
            "current_ap_name": "AP0808",
            "current_ap_mac": "0011-2233-4455",
            "station": "泽民",
            "section": "泽民-大卿桥-下行",
            "rssi": -61,
            "ac_snapshot_id": 21,
            "ac_received_at": "2026-07-29T11:45:00+08:00",
            "endpoints": [
                {
                    "endpoint": "CW",
                    "mr_id": "mr-cw-02",
                    "mr_name": "列车02-MR-CW",
                    "device_id": 22,
                    "management_ip": "192.168.100.232",
                    "ping_target_eligible": True,
                }
            ],
            "ap_identity_diagnostics": {"identity_revision": 8743},
        },
        ap_identity="ap-identity-0808",
        same_ap_since="2026-07-29T11:40:00+08:00",
    )
    repository.insert_wmesh_events(
        [
            {
                "run_id": "run-1",
                "device_uuid": "mr-cw-02",
                "train_id": "train-02",
                "mr_role": "CW",
                "event_type": "MESH_LINKUP",
                "event_family": "WMESH",
                "receive_time": "2026-07-29T11:45:30+08:00",
            }
        ]
    )
    ping = _FleetPingRecorder()
    supervisor.fleet_ping = ping  # type: ignore[assignment]
    clock = [datetime.fromisoformat("2026-07-29T11:46:00+08:00")]
    supervisor.now_provider = lambda: clock[0]
    supervisor._network_profile_error = lambda _profile: None  # type: ignore[method-assign]
    supervisor.inventory_sync = SimpleNamespace(synchronize=lambda: None)  # type: ignore[assignment]
    supervisor._start_syslog = lambda *_args: None  # type: ignore[method-assign]
    supervisor._ensure_ac_resident_pollers = lambda *_args: None  # type: ignore[method-assign]

    supervisor._recover_on_start()

    assert ping.started is True
    assert len(ping.target_updates[-1]) == 1
    recovered = ping.target_updates[-1][0]
    assert recovered.target_ip == "192.168.100.232"
    assert recovered.current_ap_name == "AP0808"
    assert recovered.station == "泽民"
    assert recovered.section == "泽民-大卿桥-下行"
    run = repository.get_run("run-1")
    assert run is not None
    assert run["summary"]["recovered_from_restart"] is True
    assert run["summary"]["ping_recovered_target_count"] == 1
    assert run["summary"]["main_link_recovered"] is True
    assert run["summary"]["main_link_state"] == "MESH_LINKUP"
    assert run["summary"]["main_link_last_event_at"] == (
        "2026-07-29T11:45:30+08:00"
    )
    assert run["summary"]["ap_identity_revision"] == 8743

    clock[0] = datetime.fromisoformat("2026-07-29T11:49:01+08:00")
    supervisor._poll_ac_and_classify(
        repository.get_run("run-1"),
        repository.get_profile(),
        clock[0],
        scheduling_paused=False,
    )

    assert ping.target_updates[-1] == []


def test_restart_marks_persisted_main_link_stale_after_existing_grace(
    tmp_path: Path,
) -> None:
    supervisor, repository, _mesh = _supervisor(tmp_path)
    repository.save_profile(
        repository.get_profile().model_copy(
            update={"enabled": True, "ac_stale_grace_seconds": 120}
        )
    )
    repository.insert_wmesh_events(
        [
            {
                "run_id": "run-1",
                "device_uuid": "mr-cw-02",
                "event_type": "MESH_LINKUP",
                "event_family": "WMESH",
                "receive_time": "2026-07-29T11:40:00+08:00",
                "peer_name": "AP0808",
            }
        ]
    )
    supervisor.now_provider = lambda: datetime.fromisoformat(
        "2026-07-29T11:46:00+08:00"
    )
    supervisor._network_profile_error = lambda _profile: None  # type: ignore[method-assign]
    supervisor.inventory_sync = SimpleNamespace(synchronize=lambda: None)  # type: ignore[assignment]
    supervisor.fleet_ping = _FleetPingRecorder()  # type: ignore[assignment]
    supervisor._start_syslog = lambda *_args: None  # type: ignore[method-assign]
    supervisor._ensure_ac_resident_pollers = lambda *_args: None  # type: ignore[method-assign]
    supervisor.deep_scheduler = None

    supervisor._recover_on_start()

    run = repository.get_run("run-1")
    assert run is not None
    assert run["summary"]["main_link_state"] == "STALE"
    assert run["summary"]["main_link_recovered"] is False


def test_endpoint_snapshot_scopes_persisted_wmesh_to_current_run(
    tmp_path: Path,
) -> None:
    _supervisor_instance, repository, _mesh = _supervisor(tmp_path)
    repository.insert_wmesh_events(
        [
            {
                "run_id": "run-1",
                "device_uuid": "mr-cw-02",
                "event_type": "MESH_LINKUP",
                "event_family": "WMESH",
                "receive_time": "2026-07-29T11:45:00+08:00",
                "peer_name": "AP-CURRENT-RUN",
            },
            {
                "run_id": "run-other",
                "device_uuid": "mr-cw-02",
                "event_type": "MESH_LINKUP",
                "event_family": "WMESH",
                "receive_time": "2026-07-29T11:46:00+08:00",
                "peer_name": "AP-OTHER-RUN",
            },
        ]
    )

    snapshot = repository.train_endpoint_snapshot(
        ["mr-cw-02"], run_id="run-1"
    )

    assert snapshot["wmesh_by_device"]["mr-cw-02"]["peer_name"] == (
        "AP-CURRENT-RUN"
    )


def test_restart_inside_frozen_window_records_profile_disabled_reason(
    tmp_path: Path,
) -> None:
    supervisor, repository, _mesh = _supervisor(tmp_path)
    supervisor.now_provider = lambda: datetime.fromisoformat(
        "2026-07-29T11:46:00+08:00"
    )

    supervisor._recover_on_start()

    run = repository.get_run("run-1")
    operation = repository.latest_operation(run_id="run-1")
    assert run is not None and run["state"] == "STOPPING"
    assert run["requested_action"] == "disabled"
    assert operation is not None
    assert operation["stop_trigger"] == "PROFILE_DISABLED"
    assert operation["operation_type"] == "STOP"


def test_restart_retries_legacy_error_with_failed_stop_operation(
    tmp_path: Path,
) -> None:
    supervisor, repository, _mesh = _supervisor(tmp_path)
    repository.update_run("run-1", state="ERROR", requested_action="fatal_error")
    repository.save_operation(
        {
            "operation_id": "legacy-failed-stop",
            "site_id": "site-a",
            "run_id": "run-1",
            "operation_type": "STOP",
            "operation_state": "FAILED",
            "operation_stage": "FAILED",
            "progress_percent": 100,
            "message": "旧版本停止失败",
            "failure_code": "DEEP_COLLECTION_STOP_TIMEOUT",
            "started_at": "2026-07-29T11:40:00+08:00",
            "updated_at": "2026-07-29T11:43:00+08:00",
        }
    )
    deep = _DeepScheduler(active=False)
    supervisor.deep_scheduler = deep  # type: ignore[assignment]
    supervisor.ac_resident_service = _ResidentService()  # type: ignore[assignment]

    supervisor._recover_on_start()
    recovered = repository.latest_operation(run_id="run-1", active_only=True)
    assert recovered is not None
    assert recovered["operation_id"] != "legacy-failed-stop"
    assert recovered["stop_trigger"] == "RECOVERY"
    assert repository.get_run("run-1")["state"] == "STOPPING"

    supervisor._tick()

    run = repository.get_run("run-1")
    operation = repository.get_operation(str(recovered["operation_id"]))
    assert run is not None and run["state"] == "COMPLETED"
    assert operation is not None and operation["operation_state"] == "COMPLETED"


def test_deep_collection_stop_deadline_continues_other_component_cleanup(
    tmp_path: Path,
) -> None:
    supervisor, repository, _mesh = _supervisor(tmp_path)
    deep = _DeepScheduler(active=True)
    resident = _ResidentService()
    supervisor.deep_scheduler = deep  # type: ignore[assignment]
    supervisor.ac_resident_service = resident  # type: ignore[assignment]
    repository.update_run("run-1", state="STOPPING", requested_action="stop")
    repository.save_operation(
        {
            "operation_id": "stop-timeout",
            "site_id": "site-a",
            "run_id": "run-1",
            "operation_type": "STOP",
            "operation_state": "RUNNING",
            "operation_stage": "STOP_REQUESTED",
            "progress_percent": 5,
            "message": "停止",
            "stop_trigger": "USER_NORMAL_STOP",
            "stop_reason": "用户请求正常停止",
            "triggered_at": "2026-07-29T11:40:00+08:00",
            "started_at": "2026-07-29T11:40:00+08:00",
            "updated_at": "2026-07-29T11:40:00+08:00",
        }
    )
    supervisor.now_provider = lambda: datetime.fromisoformat(
        "2026-07-29T11:43:00+08:00"
    )
    run = repository.get_active_run()
    assert run is not None

    supervisor._finalize_run(run, archive=False)

    operation = repository.get_operation("stop-timeout")
    assert operation is not None
    assert operation["operation_state"] == "FAILED"
    assert operation["failure_code"] == "DEEP_COLLECTION_STOP_TIMEOUT"
    assert operation["result_summary"]["stop_failures"][0]["component"] == "deep_collection"
    assert operation["result_summary"]["deep_collection_stop_state"] == "TIMED_OUT"
    assert resident.stop_calls
    run = repository.get_run("run-1")
    assert run is not None and run["state"] == "COMPLETED"


def test_deep_collection_deadline_accounts_for_bounded_finalizing_waves(
    tmp_path: Path,
) -> None:
    supervisor, repository, _mesh = _supervisor(tmp_path)
    deep = _DeepScheduler(
        active=True,
        active_ids=["deep-1", "deep-2", "deep-3", "deep-4"],
    )
    resident = _ResidentService()
    supervisor.deep_scheduler = deep  # type: ignore[assignment]
    supervisor.ac_resident_service = resident  # type: ignore[assignment]
    repository.save_profile(
        repository.get_profile().model_copy(update={"max_finalizing_mrs": 2})
    )
    repository.update_run("run-1", state="STOPPING", requested_action="stop")
    repository.save_operation(
        {
            "operation_id": "stop-waves",
            "site_id": "site-a",
            "run_id": "run-1",
            "operation_type": "STOP",
            "operation_state": "RUNNING",
            "operation_stage": "STOP_REQUESTED",
            "progress_percent": 5,
            "message": "停止",
            "stop_trigger": "USER_NORMAL_STOP",
            "triggered_at": "2026-07-29T11:40:00+08:00",
            "started_at": "2026-07-29T11:40:00+08:00",
            "updated_at": "2026-07-29T11:40:00+08:00",
        }
    )
    clock = [datetime.fromisoformat("2026-07-29T11:42:30+08:00")]
    supervisor.now_provider = lambda: clock[0]

    supervisor._finalize_run(repository.get_active_run(), archive=False)

    waiting = repository.get_operation("stop-waves")
    assert waiting is not None and waiting["operation_state"] == "RUNNING"
    assert waiting["result_summary"]["deep_collection_stop_timeout_seconds"] == 160.0
    assert resident.stop_calls == []

    clock[0] = datetime.fromisoformat("2026-07-29T11:42:41+08:00")
    supervisor._finalize_run(repository.get_active_run(), archive=False)
    completed = repository.get_operation("stop-waves")
    assert completed is not None and completed["operation_state"] == "FAILED"
    assert resident.stop_calls


def test_deep_collection_force_stop_keeps_run_owned_until_mapping_terminal(
    tmp_path: Path,
) -> None:
    supervisor, repository, _mesh = _supervisor(tmp_path)
    deep = _DeepScheduler(active=True, force_completes=False)
    supervisor.deep_scheduler = deep  # type: ignore[assignment]
    supervisor.ac_resident_service = _ResidentService()  # type: ignore[assignment]
    repository.update_run("run-1", state="STOPPING", requested_action="stop")
    repository.save_operation(
        {
            "operation_id": "stop-force-wait",
            "site_id": "site-a",
            "run_id": "run-1",
            "operation_type": "STOP",
            "operation_state": "RUNNING",
            "operation_stage": "STOP_REQUESTED",
            "progress_percent": 5,
            "message": "停止",
            "stop_trigger": "USER_NORMAL_STOP",
            "triggered_at": "2026-07-29T11:40:00+08:00",
            "started_at": "2026-07-29T11:40:00+08:00",
            "updated_at": "2026-07-29T11:40:00+08:00",
        }
    )
    supervisor.now_provider = lambda: datetime.fromisoformat(
        "2026-07-29T11:43:00+08:00"
    )

    supervisor._finalize_run(repository.get_active_run(), archive=False)

    run = repository.get_run("run-1")
    operation = repository.get_operation("stop-force-wait")
    assert run is not None and run["state"] == "FINALIZING"
    assert operation is not None and operation["operation_state"] == "RUNNING"
    assert operation["operation_stage"] == "WAITING_DEEP_COLLECTION_TERMINAL"
    assert deep.force_stop_calls == ["normal_stop_deadline_exceeded"]


def test_restart_from_deep_wait_preserves_persisted_ping_count(
    tmp_path: Path,
) -> None:
    supervisor, repository, _mesh = _supervisor(tmp_path)
    repository.update_run(
        "run-1",
        state="FINALIZING",
        requested_action="stop",
        ping_sample_count=47,
    )
    repository.save_operation(
        {
            "operation_id": "stop-restart-count",
            "site_id": "site-a",
            "run_id": "run-1",
            "operation_type": "STOP",
            "operation_state": "RUNNING",
            "operation_stage": "WAITING_DEEP_COLLECTION_TERMINAL",
            "progress_percent": 90,
            "message": "等待深度采集映射进入终态",
            "stop_trigger": "USER_NORMAL_STOP",
            "stop_reason": "用户请求正常停止",
            "triggered_at": "2026-07-29T11:40:00+08:00",
            "started_at": "2026-07-29T11:40:00+08:00",
            "updated_at": "2026-07-29T11:43:00+08:00",
            "result_summary": {
                "ping_sample_count": 47,
                "deep_collection_stop_state": "FORCE_STOPPING",
                "stop_failures": [
                    {
                        "component": "deep_collection",
                        "code": "DEEP_COLLECTION_STOP_TIMEOUT",
                        "message": "深度采集任务未在停止预算内终结",
                        "state": "TIMED_OUT",
                    }
                ],
            },
        }
    )
    deep = _DeepScheduler(active=False)
    supervisor.deep_scheduler = deep  # type: ignore[assignment]
    supervisor.ac_resident_service = _ResidentService()  # type: ignore[assignment]

    supervisor._recover_on_start()
    supervisor._tick()

    run = repository.get_run("run-1")
    operation = repository.get_operation("stop-restart-count")
    assert run is not None and run["state"] == "COMPLETED"
    assert run["ping_sample_count"] == 47
    assert operation is not None and operation["operation_state"] == "FAILED"
    assert operation["result_summary"]["ping_sample_count"] == 47
    assert deep.recover_calls == ["run-1"]


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
