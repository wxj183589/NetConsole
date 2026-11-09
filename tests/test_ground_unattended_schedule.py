from __future__ import annotations

import socket
import threading
from concurrent.futures import Future
from datetime import datetime
from types import SimpleNamespace

import pytest

from netconsole.core.paths import PathResolver
from netconsole.models.api.ground_unattended import GroundUnattendedProfileDTO
from netconsole.models.api.rail_transit_base_data import RailTransitSummaryDTO
from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)
from netconsole.services.ground_unattended.schedule import schedule_window
from netconsole.services.ground_unattended.supervisor import GroundUnattendedSupervisor
from netconsole.services.ground_unattended.fleet_ping import FleetPingTarget


def test_default_and_regular_schedule_window() -> None:
    profile = GroundUnattendedProfileDTO(site_id="site-a")
    assert profile.schedule_start_time == "07:00"
    assert profile.schedule_end_time == "23:00"
    assert profile.ac_poll_interval_seconds == 60
    assert profile.ac_mesh_link_poll_interval_seconds == 300
    assert profile.syslog_receiver_auto_start_enabled is False
    assert profile.boot_check_auto_start_enabled is False
    assert profile.syslog_auto_repair_enabled is False
    assert profile.ac_mesh_link_auto_collection_enabled is False
    active = schedule_window(
        datetime.fromisoformat("2026-07-25T07:00:00+08:00"), "07:00", "23:00", "Asia/Shanghai"
    )
    assert active.active
    assert active.run_date == "2026-07-25"


def test_profile_rejects_invalid_timezone_before_runtime() -> None:
    with pytest.raises(ValueError, match="IANA"):
        GroundUnattendedProfileDTO(site_id="site-a", timezone="Shanghai/local")
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
    assert repo.get_profile().deep_fping.enabled is True
    assert repo.get_profile().deep_fping.interval_ms == 10
    profile = repo.get_profile().model_copy(
        update={
            "enabled": True,
            "schedule_start_time": "08:15",
            "schedule_end_time": "00:30",
            "ping_depot_trains_enabled": True,
            "deep_fping": repo.get_profile().deep_fping.model_copy(
                update={
                    "enabled": False,
                    "preset_key": "",
                    "preset_name": "自定义",
                    "packet_size": 256,
                    "interval_ms": 30,
                    "timeout_ms": 250,
                    "loss_warn_percent": 2.5,
                    "latency_warn_ms": 150,
                }
            ),
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
    assert loaded.deep_fping.enabled is True
    assert loaded.deep_fping.target == ""
    assert loaded.deep_fping.packet_size == 256
    assert loaded.deep_fping.interval_ms == 30
    assert loaded.deep_fping.timeout_ms == 250


def test_supervisor_repeated_ticks_tolerate_future_profile_columns(tmp_path) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    paths.site_dir("site-a").mkdir(parents=True)
    repo = GroundUnattendedRepository(
        paths.ground_unattended_db_path("site-a"), site_id="site-a"
    )
    repo.get_profile()
    with repo._connection() as connection:
        connection.execute(
            "ALTER TABLE ground_unattended_profiles "
            "ADD COLUMN future_schema_test_column TEXT"
        )
        connection.execute(
            "UPDATE ground_unattended_profiles "
            "SET future_schema_test_column='newer-runtime'"
        )
    supervisor = GroundUnattendedSupervisor(
        paths,
        site_id="site-a",
        repository=repo,
        base_query=_BaseQuery(),  # type: ignore[arg-type]
        mesh_query=_MeshQuery(),  # type: ignore[arg-type]
        vehicle_query=_VehicleQuery(),  # type: ignore[arg-type]
        now_provider=lambda: datetime.fromisoformat("2026-07-25T06:00:00+08:00"),
    )

    for _index in range(3):
        supervisor._tick()

    assert supervisor._tick_error_fingerprint == ""


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


def test_running_profile_hot_updates_ac_and_background_switches() -> None:
    supervisor = object.__new__(GroundUnattendedSupervisor)
    supervisor._active_profile = GroundUnattendedProfileDTO(
        site_id="site-a",
        ac_poll_interval_seconds=60,
        ac_mesh_link_poll_interval_seconds=300,
        syslog_receiver_auto_start_enabled=False,
        boot_check_auto_start_enabled=False,
        syslog_auto_repair_enabled=False,
        ac_mesh_link_auto_collection_enabled=False,
    )
    latest = supervisor._active_profile.model_copy(
        update={
            "ac_poll_interval_seconds": 90,
            "ac_mesh_link_poll_interval_seconds": 600,
            "syslog_receiver_auto_start_enabled": True,
            "boot_check_auto_start_enabled": True,
            "syslog_auto_repair_enabled": True,
            "ac_mesh_link_auto_collection_enabled": True,
        }
    )

    effective = supervisor._runtime_profile(latest)

    assert effective.ac_poll_interval_seconds == 90
    assert effective.ac_mesh_link_poll_interval_seconds == 600
    assert effective.syslog_receiver_auto_start_enabled is True
    assert effective.boot_check_auto_start_enabled is True
    assert effective.syslog_auto_repair_enabled is True
    assert effective.ac_mesh_link_auto_collection_enabled is True
    assert supervisor._active_profile.ac_poll_interval_seconds == 60


def test_manual_config_check_uses_inventory_when_ac_targets_are_missing() -> None:
    supervisor = object.__new__(GroundUnattendedSupervisor)
    target = FleetPingTarget(
        target_ip="192.0.2.10",
        train_id="train-1",
        train_no="01",
        mr_id="mr-1",
        mr_position_code="CT",
    )
    submitted: list[dict[str, object]] = []

    class _Repository:
        def list_inventory(self, *, include_removed: bool):
            return [{"train_id": "train-1", "priority": False, "scheduling_priority": 0}]

        def latest_syslog_config_audit(self, _device_uuid):
            return None

    class _FleetPing:
        def target_summaries(self):
            return []

    class _Executor:
        def submit(self, _function, **kwargs):
            submitted.append(kwargs)
            return object()

    class _ConfigService:
        def check(self, **_kwargs):
            return None

    supervisor.repository = _Repository()
    supervisor.fleet_ping = _FleetPing()
    supervisor.heartbeat = SimpleNamespace(_heartbeat_fleet_targets=lambda: {target.target_ip: target})
    supervisor._manual_config_checks = {"mr-1": (False, True)}
    supervisor._config_futures = {}
    supervisor._config_executor = _Executor()
    supervisor.config_service = _ConfigService()
    supervisor._now = lambda: datetime.fromisoformat("2026-07-25T08:00:00+08:00")

    profile = GroundUnattendedProfileDTO(
        site_id="site-a",
        syslog_server_ip="192.0.2.100",
        syslog_server_port=514,
    )
    supervisor._schedule_config_checks(
        {"run_id": "run-1", "run_date": "2026-07-25"}, profile, {}
    )

    assert len(submitted) == 1
    assert submitted[0]["device_uuid"] == "mr-1"
    assert submitted[0]["repair_enabled"] is True


def test_syslog_task_cancel_discards_queued_devices_and_finishes_task() -> None:
    supervisor = object.__new__(GroundUnattendedSupervisor)
    supervisor._lock = threading.RLock()
    supervisor._manual_config_checks = {"mr-1": (False, True)}
    supervisor._manual_config_task_ids = {"mr-1": "task-1"}
    supervisor._manual_syslog_exits = set()
    supervisor._manual_syslog_exit_task_ids = {}
    supervisor._config_future_meta = {}
    supervisor._config_futures = {}
    supervisor._syslog_task_progress = {
        "task-1": {
            "current": 0,
            "total": 1,
            "success": 0,
            "failed": 0,
            "results": [],
        }
    }
    supervisor._cancelled_syslog_tasks = set()
    supervisor._wake_event = threading.Event()
    recorded: list[tuple[str, dict[str, object]]] = []
    supervisor._record_syslog_task_event = (
        lambda task_id, event_type, payload: recorded.append((event_type, payload))
    )

    assert supervisor.cancel_syslog_task("task-1") is True

    assert supervisor._manual_config_checks == {}
    assert supervisor._manual_config_task_ids == {}
    assert supervisor._syslog_task_progress == {}
    assert recorded == [
        (
            "finished",
            {
                "terminal_state": "CANCELLED",
                "message": "Syslog 批次任务已取消",
                "result": {
                    "success_count": 0,
                    "failed_count": 0,
                    "business_status": "CANCELLED",
                },
            },
        )
    ]


def test_repeated_syslog_requests_keep_independent_fifo_entries() -> None:
    supervisor = object.__new__(GroundUnattendedSupervisor)
    supervisor._lock = threading.RLock()
    supervisor._wake_event = threading.Event()
    supervisor._manual_syslog_queue = []
    supervisor._manual_config_checks = {}
    supervisor._manual_config_task_ids = {}
    supervisor._manual_syslog_exits = set()
    supervisor._manual_syslog_exit_task_ids = {}

    supervisor.request_config_check("mr-1", task_id="task-1")
    supervisor.request_config_check("mr-1", task_id="task-2")
    supervisor.request_syslog_exit("mr-1", task_id="task-3")

    assert [
        (item["task_id"], item["device_uuid"], item["op"])
        for item in supervisor._manual_syslog_queue
    ] == [
        ("task-1", "mr-1", "JOIN"),
        ("task-2", "mr-1", "JOIN"),
        ("task-3", "mr-1", "EXIT"),
    ]


def test_syslog_cancel_only_removes_its_batch_and_records_device_result() -> None:
    supervisor = object.__new__(GroundUnattendedSupervisor)
    supervisor._lock = threading.RLock()
    supervisor._wake_event = threading.Event()
    supervisor._manual_syslog_queue = [
        {"task_id": "task-1", "device_uuid": "mr-1", "op": "JOIN"},
        {"task_id": "task-2", "device_uuid": "mr-1", "op": "JOIN"},
    ]
    supervisor._manual_config_checks = {"mr-1": (False, True)}
    supervisor._manual_config_task_ids = {"mr-1": "task-1"}
    supervisor._manual_syslog_exits = set()
    supervisor._manual_syslog_exit_task_ids = {}
    supervisor._config_future_meta = {}
    supervisor._config_futures = {}
    supervisor._syslog_task_progress = {
        task_id: {"current": 0, "total": 1, "success": 0, "failed": 0, "results": []}
        for task_id in ("task-1", "task-2")
    }
    supervisor._syslog_task_devices = {"task-1": {"mr-1"}, "task-2": {"mr-1"}}
    supervisor._cancelled_syslog_tasks = set()
    events: list[tuple[str, str, dict[str, object]]] = []
    supervisor._record_syslog_task_event = (
        lambda task_id, event_type, payload: events.append((task_id, event_type, payload))
    )

    assert supervisor.cancel_syslog_task("task-1") is True

    assert [item["task_id"] for item in supervisor._manual_syslog_queue] == ["task-2"]
    assert supervisor._syslog_task_progress["task-2"]["current"] == 0
    finished = [payload for task_id, kind, payload in events if task_id == "task-1" and kind == "finished"]
    assert finished[0]["result"]["devices"] == [
        {"device_uuid": "mr-1", "status": "CANCELLED", "audit_id": ""}
    ]


def test_syslog_batch_results_map_service_status_per_task() -> None:
    supervisor = object.__new__(GroundUnattendedSupervisor)
    first = Future()
    first.set_result(SimpleNamespace(config_status="CONFIG_SENT", audit_id="audit-1"))
    second = Future()
    second.set_result(SimpleNamespace(config_status="CONFIG_PRESENT", audit_id="audit-2"))
    supervisor._config_futures = {"mr-1": first, "mr-2": second}
    supervisor._config_future_meta = {
        "mr-1": {"task_id": "task-1", "operation": "JOIN"},
        "mr-2": {"task_id": "task-2", "operation": "JOIN"},
    }
    supervisor._syslog_task_progress = {
        task_id: {"current": 0, "total": 1, "success": 0, "failed": 0, "results": [], "in_flight": 1}
        for task_id in ("task-1", "task-2")
    }
    supervisor._cancelled_syslog_tasks = set()
    events: list[tuple[str, str, dict[str, object]]] = []
    supervisor._record_syslog_task_event = (
        lambda task_id, event_type, payload: events.append((task_id, event_type, payload))
    )

    supervisor._collect_config_checks()

    results = {
        task_id: payload["device_result"]
        for task_id, kind, payload in events
        if kind == "progress"
    }
    assert results == {
        "task-1": {
            "device_uuid": "mr-1", "operation": "JOIN", "status": "CONFIGURED",
            "audit_id": "audit-1", "error": "",
        },
        "task-2": {
            "device_uuid": "mr-2", "operation": "JOIN", "status": "ALREADY_CONFIGURED",
            "audit_id": "audit-2", "error": "",
        },
    }


def test_running_syslog_batches_recover_independently_after_restart() -> None:
    class _TaskService:
        def list_tasks(self, *, statuses, limit, site_name):
            assert site_name == "site-a"
            return [
                SimpleNamespace(
                    task_id="task-1",
                    task_type="ground_unattended_syslog_control",
                    created_time="2026-07-26T01:00:00Z",
                    total=1,
                ),
                SimpleNamespace(
                    task_id="task-2",
                    task_type="ground_unattended_syslog_control",
                    created_time="2026-07-26T01:01:00Z",
                    total=1,
                ),
            ]

        def list_events(self, task_id, *, limit, site_name):
            assert site_name == "site-a"
            assert limit == 2000
            if task_id == "task-1":
                return [
                    {
                        "payload": {
                            "event": "BATCH_DEVICES",
                            "device_uuids": ["mr-1", "mr-2"],
                            "operation": "JOIN",
                        }
                    },
                    {
                        "payload": {
                            "event": "DEVICE_QUEUED",
                            "device_uuid": "mr-1",
                            "operation": "JOIN",
                        }
                    }
                ]
            return [
                {
                    "payload": {
                        "event": "DEVICE_QUEUED",
                        "device_uuid": "mr-1",
                        "operation": "JOIN",
                    }
                },
                {
                    "payload": {
                        "device_result": {
                            "device_uuid": "mr-1",
                            "status": "ALREADY_CONFIGURED",
                            "audit_id": "audit-2",
                        }
                    }
                },
            ]

    supervisor = object.__new__(GroundUnattendedSupervisor)
    supervisor.site_id = "site-a"
    supervisor.task_service = _TaskService()
    supervisor._manual_syslog_queue = []
    supervisor._syslog_task_progress = {}
    supervisor._syslog_task_devices = {}
    finished: dict[str, dict[str, object]] = {}

    def _finish(task_id: str, **kwargs: object) -> None:
        finished[task_id] = dict(supervisor._syslog_task_progress[task_id])

    supervisor._finish_syslog_task = _finish

    supervisor._recover_syslog_batch_tasks()

    assert supervisor._manual_syslog_queue == [
        {"op": "JOIN", "device_uuid": "mr-1", "task_id": "task-1"},
        {"op": "JOIN", "device_uuid": "mr-2", "task_id": "task-1"},
    ]
    assert supervisor._syslog_task_devices == {"task-1": {"mr-1", "mr-2"}}
    assert supervisor._syslog_task_progress["task-1"]["current"] == 0
    assert finished["task-2"]["results"] == [
        {"device_uuid": "mr-1", "status": "ALREADY_CONFIGURED", "audit_id": "audit-2"}
    ]


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
    operation = repo.latest_operation(run_id=str(repo.latest_run()["run_id"]))  # type: ignore[index]
    assert operation is not None
    assert operation["stop_trigger"] == "SCHEDULE_END"
    assert operation["previous_state"] == "RUNNING"
    assert operation["next_state"] == "STOPPING"


def test_running_run_uses_frozen_end_when_profile_changes_at_midday(tmp_path) -> None:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    paths.site_dir("site-a").mkdir(parents=True)
    repo = GroundUnattendedRepository(
        paths.ground_unattended_db_path("site-a"), site_id="site-a"
    )
    repo.save_profile(
        repo.get_profile().model_copy(
            update={
                "enabled": True,
                "schedule_start_time": "07:00",
                "schedule_end_time": "23:00",
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
    supervisor._start_fleet_ping = lambda *_args: None  # type: ignore[method-assign]
    supervisor._start_syslog = lambda *_args: None  # type: ignore[method-assign]
    supervisor._ensure_ac_resident_pollers = lambda *_args: None  # type: ignore[method-assign]
    supervisor._poll_if_due = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
    supervisor._tick()
    run = repo.get_active_run()
    assert run is not None
    assert run["scheduled_end_at"].startswith("2026-07-25T23:00:00")

    repo.save_profile(
        repo.get_profile().model_copy(update={"schedule_end_time": "08:00"})
    )
    for value in ("11:00:00", "11:46:00", "15:00:00"):
        clock[0] = datetime.fromisoformat(f"2026-07-25T{value}+08:00")
        supervisor._tick()
        assert repo.get_active_run()["state"] == "RUNNING"  # type: ignore[index]
        assert repo.latest_operation(run_id=str(run["run_id"])) is None


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
    operation = repo.latest_operation(run_id=str(run_id))
    assert operation is not None
    assert operation["stop_trigger"] == "USER_NORMAL_STOP"
    assert operation["stop_reason"] == "用户请求正常停止"
    assert operation["request_id"].startswith("groundreq_")

    supervisor._tick()
    assert repo.get_active_run() is None
    assert repo.latest_run()["run_id"] == run_id  # type: ignore[index]

    supervisor.request("start")
    supervisor._tick()
    assert repo.get_active_run()["state"] == "RUNNING"  # type: ignore[index]
    assert repo.get_active_run()["requested_action"] == "manual_start"  # type: ignore[index]
    supervisor.close()


def test_supervisor_allows_explicit_same_day_restart_after_ready_archive(tmp_path) -> None:
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
    assert repo.get_active_run() is not None
    supervisor.close()
    assert len(repo.list_run_sessions(run["run_id"])) == 1


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
