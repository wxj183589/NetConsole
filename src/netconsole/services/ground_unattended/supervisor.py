from __future__ import annotations

import logging
import json
import shutil
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from netconsole.core.paths import PathResolver
from netconsole.models.api.ground_unattended import GroundUnattendedProfileDTO
from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)
from netconsole.services.ac.mesh_link_query_service import AcMeshLinkQueryService
from netconsole.services.ac.mesh_link_refresh_service import (
    AcMeshLinkRefreshApplicationService,
)
from netconsole.services.ac.mesh_link_resident_polling_service import (
    AcMeshLinkResidentPollingApplicationService,
)
from netconsole.services.ground_unattended.eligibility import (
    GroundUnattendedEligibilityClassifier,
    StationaryTracker,
)
from netconsole.services.ground_unattended.fleet_ping import (
    FleetPingSupervisor,
    FleetPingTarget,
)
from netconsole.services.ground_unattended.deep_scheduler import (
    DeepMrCollectionScheduler,
)
from netconsole.services.ground_unattended.archive_service import (
    GroundUnattendedArchiveService,
)
from netconsole.services.online_mr.application_service import OnlineMrApplicationService
from netconsole.services.online_mr.query_service import OnlineMrQueryService
from netconsole.services.ground_unattended.schedule import (
    resolve_timezone,
    schedule_window,
)
from netconsole.services.ground_unattended.boot_config import MrSyslogConfigService
from netconsole.services.ground_unattended.inventory import TrainInventorySyncService
from netconsole.services.ground_unattended.syslog_runtime import (
    SyslogUdpReceiver,
    recover_raw_files,
)
from netconsole.services.rail_transit.base_data_query_service import (
    RailTransitBaseDataQueryService,
)
from netconsole.services.rail_transit.train_identity import canonical_train_id_for
from netconsole.services.rail_transit.vehicle_mr_online_query_service import (
    VehicleMrOnlineQueryService,
)
from netconsole.services.system_network_application_service import (
    SystemNetworkApplicationService,
    SystemNetworkError,
)


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SupervisorCommand:
    action: str
    archive: bool = False
    operation_id: str = ""


class GroundUnattendedSupervisor:
    """由 FastAPI lifespan 持有的无人值守后台状态机。"""

    def __init__(
        self,
        paths: PathResolver,
        *,
        site_id: str,
        repository: GroundUnattendedRepository,
        base_query: RailTransitBaseDataQueryService,
        mesh_query: AcMeshLinkQueryService,
        vehicle_query: VehicleMrOnlineQueryService,
        ac_refresh_service: AcMeshLinkRefreshApplicationService | None = None,
        ac_resident_service: AcMeshLinkResidentPollingApplicationService
        | None = None,
        online_mr_application_service: OnlineMrApplicationService | None = None,
        online_mr_query_service: OnlineMrQueryService | None = None,
        network_service: SystemNetworkApplicationService | None = None,
        now_provider: Callable[[], datetime] | None = None,
        tick_seconds: float = 1.0,
    ) -> None:
        self.paths = paths
        self.site_id = site_id
        self.repository = repository
        self.base_query = base_query
        self.mesh_query = mesh_query
        self.vehicle_query = vehicle_query
        self.network_service = network_service or SystemNetworkApplicationService()
        self.ac_refresh_service = ac_refresh_service
        self.ac_resident_service = ac_resident_service
        self.now_provider = now_provider or (lambda: datetime.now().astimezone())
        self.tick_seconds = max(0.05, float(tick_seconds))
        self.classifier = GroundUnattendedEligibilityClassifier()
        self.fleet_ping = FleetPingSupervisor(repository=repository, site_id=site_id)
        self.deep_scheduler = (
            DeepMrCollectionScheduler(
                paths,
                site_id=site_id,
                repository=repository,
                application_service=online_mr_application_service,
                query_service=online_mr_query_service,
                base_query=base_query,
                fleet_ping=self.fleet_ping,
            )
            if online_mr_application_service is not None
            and online_mr_query_service is not None
            else None
        )
        self.archive_service = GroundUnattendedArchiveService(
            paths,
            site_id=site_id,
            repository=repository,
        )
        self.inventory_sync = TrainInventorySyncService(
            paths,
            site_id=site_id,
            repository=repository,
            base_query=base_query,
        )
        self.syslog_receiver = SyslogUdpReceiver(
            repository=repository,
            site_id=site_id,
        )
        self.config_service = MrSyslogConfigService(
            paths,
            site_id=site_id,
            repository=repository,
        )
        self._config_executor = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="ground-syslog-config",
        )
        self._config_futures: dict[str, Future] = {}
        self._manual_config_checks: dict[str, bool] = {}
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._commands: list[SupervisorCommand] = []
        self._active_profile: GroundUnattendedProfileDTO | None = None
        self._last_ac_poll_monotonic = 0.0
        self._last_disk_check_monotonic = 0.0
        self._manual_start = False
        self._last_valid_ping_targets: dict[str, tuple[FleetPingTarget, datetime]] = {}
        self._archive_delete_requests: list[str] = []
        self._last_profile_network_error = ""
        self._last_processed_snapshot_id_by_controller: dict[str, int] = {}

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name=f"ground-unattended-{self.site_id}",
                daemon=True,
            )
            self._thread.start()

    def close(self, timeout_seconds: float = 30.0) -> None:
        self._stop_event.set()
        self._wake_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=max(0.1, float(timeout_seconds)))
            if thread.is_alive():
                LOGGER.error(
                    "地面无人值守 Supervisor 未在退出预算内结束：site=%s", self.site_id
                )
        self._thread = None
        self.fleet_ping.stop()
        self.syslog_receiver.stop()
        if self.deep_scheduler is not None:
            self.deep_scheduler.close()
        self._config_executor.shutdown(wait=True, cancel_futures=True)

    def request(
        self,
        action: str,
        *,
        archive: bool = False,
        operation_id: str = "",
    ) -> None:
        if action not in {"start", "pause", "resume", "stop"}:
            raise ValueError("unsupported ground unattended action")
        with self._lock:
            self._commands.append(
                SupervisorCommand(action, archive, operation_id)
            )
        self._wake_event.set()

    def profile_updated(self) -> None:
        self._wake_event.set()

    def request_archive_delete(self, archive_id: str) -> None:
        with self._lock:
            self._archive_delete_requests.append(str(archive_id))
        self._wake_event.set()

    def request_config_check(
        self,
        device_uuid: str = "",
        *,
        allow_target_port_change: bool = False,
    ) -> None:
        with self._lock:
            key = str(device_uuid or "*")
            self._manual_config_checks[key] = bool(allow_target_port_change)
        self._wake_event.set()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _run(self) -> None:
        try:
            self._recover_on_start()
            while not self._stop_event.is_set():
                try:
                    self._tick()
                except Exception as exc:
                    LOGGER.exception("地面无人值守调度周期失败：site=%s", self.site_id)
                    run = self.repository.get_active_run()
                    self.repository.add_event(
                        run_id=str((run or {}).get("run_id") or ""),
                        event_type="supervisor_error",
                        severity="error",
                        title="无人值守调度周期失败",
                        message=f"{exc.__class__.__name__}: {exc}",
                    )
                    if run:
                        self.repository.update_run(
                            str(run["run_id"]),
                            state="ERROR",
                            error_code="GROUND_UNATTENDED_TICK_FAILED",
                            error_message=str(exc),
                        )
                self._wake_event.wait(self.tick_seconds)
                self._wake_event.clear()
        finally:
            self._shutdown_active_run()

    def _recover_on_start(self) -> None:
        run = self.repository.get_active_run()
        if run is None:
            for archive in self.repository.list_archives():
                if archive.get("archive_status") not in {"BUILDING", "FAILED"}:
                    continue
                candidate = self.repository.get_run(str(archive["run_id"]))
                if (
                    candidate
                    and self.paths.ground_unattended_active_dir(
                        self.site_id, str(candidate["run_date"])
                    ).is_dir()
                ):
                    self.archive_service.archive_run(
                        str(candidate["run_id"]), self.repository.get_profile()
                    )
            return
        profile = self.repository.get_profile()
        if str(run.get("state") or "") in {
            "STOPPING",
            "FINALIZING",
            "ARCHIVING",
            "ERROR",
        }:
            self._active_profile = profile
            operation = self.repository.latest_operation(
                run_id=str(run["run_id"]), active_only=True
            )
            if operation is not None:
                self.repository.add_event(
                    run_id=str(run["run_id"]),
                    event_type="operation_recovered",
                    title="已恢复停止或归档操作",
                    details={
                        "operation_id": str(operation["operation_id"]),
                        "operation_stage": str(
                            operation.get("operation_stage") or ""
                        ),
                    },
                )
            return
        window = schedule_window(
            self._now(),
            profile.schedule_start_time,
            profile.schedule_end_time,
            profile.timezone,
        )
        manual_run_active = self._manual_run_is_active(run, self._now())
        if profile.enabled and (
            (window.active and run["run_date"] == window.run_date) or manual_run_active
        ):
            error = self._network_profile_error(profile)
            if error is not None:
                self.repository.update_run(
                    str(run["run_id"]),
                    state="ERROR",
                    requested_action="profile_invalid",
                    error_code=error.code,
                    error_message=error.message,
                )
                self.repository.add_event(
                    run_id=str(run["run_id"]),
                    event_type="run_recovery_rejected",
                    severity="error",
                    title="重启恢复被网络配置阻止",
                    message=error.message,
                )
                return
            self._active_profile = profile
            self._restore_processed_snapshot_ids(run)
            self.inventory_sync.synchronize()
            self._start_fleet_ping(run, profile)
            self._start_syslog(run, profile)
            self._ensure_ac_resident_pollers(run, profile)
            self.repository.update_run(
                str(run["run_id"]), state="RUNNING", error_code="", error_message=""
            )
            self.repository.add_event(
                run_id=str(run["run_id"]),
                event_type="run_recovered",
                title="软件重启后恢复无人值守运行",
                message="当前仍在配置运行窗口内，长 Ping 与深度调度将从持久化状态恢复。",
            )
            self._last_ac_poll_monotonic = 0.0
            if self.deep_scheduler is not None:
                self.deep_scheduler.recover(str(run["run_id"]))
        else:
            self.repository.update_run(
                str(run["run_id"]),
                state="FINALIZING",
                requested_action="restart_after_window",
            )

    def _tick(self) -> None:
        self._collect_config_checks()
        self._handle_archive_deletes()
        self._handle_commands()
        profile = self.repository.get_profile()
        now = self._now()
        window = schedule_window(
            now,
            profile.schedule_start_time,
            profile.schedule_end_time,
            profile.timezone,
        )
        run = self.repository.get_active_run()

        if run is not None and run["state"] in {
            "FINALIZING",
            "ARCHIVING",
            "STOPPING",
            "ERROR",
        }:
            self._finalize_run(
                run,
                archive=run.get("requested_action")
                in {"stop_and_archive", "window_end", "restart_after_window"},
            )
            return

        if not profile.enabled and not self._manual_start:
            if run is not None:
                self.repository.update_run(
                    str(run["run_id"]), state="STOPPING", requested_action="disabled"
                )
            return

        if run is None and window.active and not self._manual_start:
            latest = self.repository.latest_run()
            if (
                latest
                and latest.get("run_date") == window.run_date
                and latest.get("state") == "COMPLETED"
                and latest.get("requested_action") in {"stop", "stop_and_archive"}
            ):
                return

        if run is None and (window.active or self._manual_start):
            error = self._network_profile_error(profile)
            if error is not None:
                self._manual_start = False
                if self._last_profile_network_error != error.code:
                    self.repository.add_event(
                        event_type="start_rejected",
                        severity="warning",
                        title="无人值守启动被网络配置阻止",
                        message=error.message,
                        details={"code": error.code},
                    )
                    self._last_profile_network_error = error.code
                return
            self._last_profile_network_error = ""
            latest = self.repository.latest_run()
            if latest and str(latest.get("run_date") or "") == window.run_date:
                archive = self.repository.get_archive_by_run(str(latest["run_id"]))
                if archive and archive.get("archive_status") == "READY":
                    manual_start = self._manual_start
                    self._manual_start = False
                    if manual_start:
                        self.repository.add_event(
                            run_id=str(latest["run_id"]),
                            event_type="start_rejected",
                            severity="warning",
                            title="立即开始被拒绝",
                            message="当前运行日已完成正式归档，不能再次启动并写入当日数据。",
                        )
                    return
            run = self._start_run(profile, now, window)
        elif (
            run is not None
            and not window.active
            and not self._manual_run_is_active(run, now)
        ):
            self.repository.update_run(
                str(run["run_id"]), state="STOPPING", requested_action="window_end"
            )
            return

        if run is None:
            return
        if run["state"] == "PAUSED" or run.get("paused"):
            self._poll_if_due(
                run, self._active_profile or profile, now, scheduling_paused=True
            )
            return
        self._poll_if_due(
            run, self._active_profile or profile, now, scheduling_paused=False
        )

    def _network_profile_error(
        self, profile: GroundUnattendedProfileDTO
    ) -> SystemNetworkError | None:
        try:
            self.network_service.validate_profile_addresses(
                udp_listen_host=profile.udp_listen_host,
                syslog_server_ip=profile.syslog_server_ip,
                require_syslog=True,
                allow_external=profile.allow_external_syslog_address,
            )
        except SystemNetworkError as exc:
            return exc
        return None

    def _handle_commands(self) -> None:
        with self._lock:
            commands, self._commands = self._commands, []
        for command in commands:
            run = self.repository.get_active_run()
            if command.action == "start":
                profile = self.repository.get_profile()
                if not profile.enabled:
                    self.repository.add_event(
                        event_type="start_rejected",
                        severity="warning",
                        title="立即开始被拒绝",
                        message="请先启用当前局点的地面无人值守配置。",
                    )
                    continue
                self._manual_start = True
            elif command.action == "pause" and run is not None:
                self.repository.update_run(
                    str(run["run_id"]), state="PAUSED", paused=True
                )
                self.repository.add_event(
                    run_id=str(run["run_id"]),
                    event_type="scheduling_paused",
                    title="深度采集调度已暂停",
                    message="全车长 Ping 与 AC 轮询继续运行。",
                )
            elif command.action == "resume" and run is not None:
                self.repository.update_run(
                    str(run["run_id"]), state="RUNNING", paused=False
                )
                self.repository.add_event(
                    run_id=str(run["run_id"]),
                    event_type="scheduling_resumed",
                    title="深度采集调度已继续",
                )
            elif command.action == "stop" and run is not None:
                self._manual_start = False
                if command.operation_id:
                    self.repository.update_operation(
                        command.operation_id,
                        operation_state="RUNNING",
                        operation_stage="STOP_REQUESTED",
                        progress_percent=5,
                        message="已提交停止请求",
                    )
                self.repository.update_run(
                    str(run["run_id"]),
                    state="STOPPING",
                    requested_action="stop_and_archive" if command.archive else "stop",
                )

    def _start_run(self, profile, now, window):
        manual_start = self._manual_start
        scheduled_start = now if manual_start else window.current_start or now
        scheduled_end = window.current_end or window.next_end
        run_id = f"ground_{window.run_date.replace('-', '')}_{uuid.uuid4().hex[:12]}"
        run = self.repository.create_or_get_run(
            run_id=run_id,
            run_date=window.run_date,
            scheduled_start_at=scheduled_start.isoformat(timespec="seconds"),
            scheduled_end_at=scheduled_end.isoformat(timespec="seconds"),
        )
        self.repository.update_run(
            str(run["run_id"]),
            state="STARTING",
            paused=False,
            requested_action="manual_start" if manual_start else "",
            scheduled_start_at=scheduled_start.isoformat(timespec="seconds"),
            scheduled_end_at=scheduled_end.isoformat(timespec="seconds"),
            actual_started_at=now.isoformat(timespec="milliseconds"),
            actual_ended_at="",
            error_code="",
            error_message="",
        )
        run = self.repository.get_run(str(run["run_id"])) or run
        self._manual_start = False
        self._active_profile = profile
        self._last_processed_snapshot_id_by_controller = {}
        inventory_summary = self.inventory_sync.synchronize()
        self._start_fleet_ping(run, profile)
        self._start_syslog(run, profile)
        self._ensure_ac_resident_pollers(run, profile)
        self._last_ac_poll_monotonic = 0.0
        self.repository.update_run(str(run["run_id"]), state="RUNNING")
        self.repository.add_event(
            run_id=str(run["run_id"]),
            event_type="run_started",
            title="地面无人值守运行已开始",
            message=f"运行窗口 {profile.schedule_start_time} - {profile.schedule_end_time}",
            details=inventory_summary.model_dump(mode="json"),
        )
        return self.repository.get_run(str(run["run_id"])) or run

    @staticmethod
    def _manual_run_is_active(run, now: datetime) -> bool:
        if str(run.get("requested_action") or "") != "manual_start":
            return False
        try:
            scheduled_end = datetime.fromisoformat(str(run["scheduled_end_at"]))
        except (KeyError, TypeError, ValueError):
            return False
        if scheduled_end.tzinfo is None:
            scheduled_end = scheduled_end.replace(tzinfo=now.tzinfo)
        return now < scheduled_end

    def _poll_if_due(self, run, profile, now, *, scheduling_paused: bool) -> None:
        import time

        self._ensure_ac_resident_pollers(run, profile)
        current = time.monotonic()
        if current - self._last_ac_poll_monotonic < min(
            1.0, max(0.1, self.tick_seconds)
        ):
            return
        self._last_ac_poll_monotonic = current
        self._poll_ac_and_classify(
            run, profile, now, scheduling_paused=scheduling_paused
        )

    def _poll_ac_and_classify(
        self, run, profile, now, *, scheduling_paused: bool
    ) -> None:
        snapshots = self._latest_controller_snapshots()
        if not snapshots:
            self.repository.update_run(
                str(run["run_id"]),
                state="PAUSED" if scheduling_paused else "RUNNING",
                ac_freshness_status="NO_DATA",
            )
            return
        new_snapshots = [
            snapshot
            for snapshot in snapshots
            if int(snapshot.id)
            > int(
                self._last_processed_snapshot_id_by_controller.get(
                    str(snapshot.controller_id), 0
                )
            )
        ]
        received_at = max(
            (
                str(snapshot.collected_at)
                for snapshot in snapshots
                if snapshot.collected_at
            ),
            default=now.isoformat(timespec="milliseconds"),
        )
        if not new_snapshots:
            fresh = any(
                str(snapshot.data_status) == "fresh"
                for snapshot in snapshots
            )
            self.repository.update_run(
                str(run["run_id"]),
                state="PAUSED" if scheduling_paused else "RUNNING",
                ac_last_updated_at=received_at,
                ac_freshness_status="FRESH" if fresh else "STALE",
            )
            return

        mesh_rows = self._mesh_rows_for_snapshots(snapshots)
        ac_rows = [item for item, _snapshot in mesh_rows]
        snapshot_batch_id = f"ac_{uuid.uuid4().hex}"
        new_snapshot_keys = {
            (str(snapshot.controller_id), int(snapshot.id))
            for snapshot in new_snapshots
        }
        base_mrs = self._all_base_mrs()
        base_by_train = {
            canonical_train_id_for(item.train_no or item.train_id): item.train_id
            for item in base_mrs
            if canonical_train_id_for(item.train_no or item.train_id)
        }
        persisted_rows = []
        for item, source_snapshot in mesh_rows:
            key = canonical_train_id_for(item.train_no)
            train_id = base_by_train.get(key, f"mesh:{key}" if key else "")
            persisted_rows.append(
                {
                    "snapshot_id": snapshot_batch_id,
                    "site_id": self.site_id,
                    "run_id": str(run["run_id"]),
                    "ac_device_id": source_snapshot.controller_id,
                    "source_snapshot_id": source_snapshot.id,
                    "device_time": source_snapshot.ac_time,
                    "received_at": str(
                        source_snapshot.collected_at or received_at
                    ),
                    "train_id": train_id,
                    "train_no": item.train_no,
                    "mr_id": item.mr_device_id or item.mr_id,
                    "mr_position_code": "CT"
                    if item.car_end.upper() == "CT"
                    else "CW"
                    if item.car_end.upper() in {"CW", "TC"}
                    else "",
                    "mr_online_status": item.online_status,
                    "peer_ap_name": item.peer_ap_name,
                    "peer_ap_mac": item.peer_ap_mac,
                    "station": item.station,
                    "section": item.section,
                    "mileage": item.mileage,
                    "rssi": item.rssi,
                    "freshness_status": item.data_status,
                    "raw_source_reference": source_snapshot.source_reference,
                }
            )
        new_persisted_rows = [
            row
            for row in persisted_rows
            if (
                str(row["ac_device_id"]),
                int(row["source_snapshot_id"]),
            )
            in new_snapshot_keys
        ]
        ac_ids = (
            self.repository.insert_ac_rows(new_persisted_rows)
            if new_persisted_rows
            else {}
        )
        if new_persisted_rows:
            self._append_ac_snapshot_file(
                str(run["run_date"]), new_persisted_rows, now
            )
        policies = {
            str(row["train_id"]): row
            for row in self.repository.list_inventory(include_removed=False)
        }
        priorities = {
            train_id for train_id, policy in policies.items() if policy.get("priority")
        }
        previous_rows = {
            row["train_id"]: row
            for row in self.repository.list_train_runs(str(run["run_id"]))
        }
        trackers = {
            train_id: StationaryTracker(
                str(row.get("current_ap_identity") or ""),
                str(row.get("same_ap_since") or ""),
            )
            for train_id, row in previous_rows.items()
        }
        results = self.classifier.classify_all(
            summary=self.base_query.get_summary(self.site_id),
            stations=self._all_stations(),
            sections=self._all_sections(),
            aps=self.base_query.list_ap_location_items(self.site_id),
            mrs=base_mrs,
            ac_rows=ac_rows,
            trackers=trackers,
            stationary_exclusion_minutes=profile.stationary_exclusion_minutes,
            now=now,
        )
        fresh = False
        valid_ping_targets: dict[str, FleetPingTarget] = {}
        for result in results:
            train = result.train
            policy = policies.get(train.train_id) or {}
            train.priority = train.train_id in priorities
            train.enabled = bool(policy.get("enabled", True))
            train.scheduling_priority = int(policy.get("scheduling_priority") or 0)
            train.deep_collection_enabled = bool(
                policy.get("deep_collection_enabled", True)
            )
            train.monitor_only = bool(policy.get("monitor_only", False))
            train.remark = str(policy.get("remark") or "")
            train.inventory_status = str(policy.get("inventory_status") or "ACTIVE")
            if not train.enabled:
                train.ping_eligible = False
                train.deep_collection_eligible = False
                train.exclusion_reason = "列车已在无人值守策略中停用"
            elif train.monitor_only or not train.deep_collection_enabled:
                train.deep_collection_eligible = False
                train.exclusion_reason = (
                    train.exclusion_reason
                    or "当前策略仅执行基础监测，不进入深度采集"
                )
            train.coverage_status = self._coverage_status_for_classification(
                previous_rows.get(train.train_id), train
            )
            endpoint_ids = [item.mr_id for item in train.endpoints if item.mr_id]
            train.ac_snapshot_id = next(
                (
                    ac_ids[(train.train_id, mr_id)]
                    for mr_id in endpoint_ids
                    if (train.train_id, mr_id) in ac_ids
                ),
                (previous_rows.get(train.train_id) or {}).get(
                    "ac_snapshot_id"
                )
                or None,
            )
            previous = previous_rows.get(train.train_id)
            if (
                previous
                and previous.get("current_ap_identity")
                and previous.get("current_ap_identity") != result.tracker.ap_identity
            ):
                self.repository.add_event(
                    run_id=str(run["run_id"]),
                    event_type="ap_transition",
                    train_id=train.train_id,
                    title="列车当前 AP 已变化",
                    message=f"{previous.get('current_ap_name') or '未知'} -> {train.current_ap_name or '未知'}",
                    details={
                        "before_ap": previous.get("current_ap_name") or "",
                        "after_ap": train.current_ap_name,
                        "received_at": received_at,
                    },
                )
            self.repository.upsert_train_state(
                str(run["run_id"]),
                str(run["run_date"]),
                train.model_dump(mode="json"),
                ap_identity=result.tracker.ap_identity,
                same_ap_since=result.tracker.since,
            )
            if train.ping_eligible:
                for endpoint in train.endpoints:
                    if endpoint.online_status != "ONLINE" or not endpoint.management_ip:
                        continue
                    target = FleetPingTarget(
                        target_ip=endpoint.management_ip,
                        train_id=train.train_id,
                        train_no=train.train_no,
                        mr_id=endpoint.mr_id,
                        mr_name=endpoint.mr_name,
                        mr_position_code=endpoint.endpoint,
                        device_id=endpoint.device_id,
                        ac_snapshot_id=train.ac_snapshot_id,
                        ac_received_at=received_at,
                        current_ap_identity=result.tracker.ap_identity,
                        current_ap_name=train.current_ap_name,
                        current_ap_mac=train.current_ap_mac,
                        station=train.station,
                        section=train.section,
                        mileage=train.mileage,
                        rssi=train.rssi,
                        same_ap_since=result.tracker.since,
                    )
                    valid_ping_targets[target.target_ip] = target
                    self._last_valid_ping_targets[target.target_ip] = (target, now)
            fresh = fresh or train.eligibility_status in {
                "MAINLINE",
                "MAINLINE_STATIONARY",
                "OFFLINE",
            }
        grace_statuses = {"AC_STALE", "AC_UNKNOWN", "AP_UNMATCHED"}
        abnormal_trains = {
            result.train.train_id
            for result in results
            if result.train.eligibility_status in grace_statuses
        }
        for address, (target, last_valid_at) in tuple(
            self._last_valid_ping_targets.items()
        ):
            elapsed = (now - last_valid_at).total_seconds()
            train_missing = not any(
                result.train.train_id == target.train_id for result in results
            )
            if address not in valid_ping_targets and (
                target.train_id in abnormal_trains or train_missing
            ):
                if elapsed <= profile.ac_stale_grace_seconds:
                    valid_ping_targets[address] = target
                else:
                    self._last_valid_ping_targets.pop(address, None)
                    self.repository.add_event(
                        run_id=str(run["run_id"]),
                        event_type="ping_target_grace_expired",
                        severity="warning",
                        train_id=target.train_id,
                        mr_id=target.mr_id,
                        title="AC 异常宽限期已结束，停止对应长 Ping",
                        details={
                            "target_ip": address,
                            "grace_seconds": profile.ac_stale_grace_seconds,
                        },
                    )
            elif address not in valid_ping_targets:
                self._last_valid_ping_targets.pop(address, None)
        self.fleet_ping.update_targets(list(valid_ping_targets.values()))
        self.fleet_ping.flush_summaries()
        self.syslog_receiver.refresh_inventory()
        self.syslog_receiver.update_ap_locations(
            self.base_query.list_ap_location_items(self.site_id)
        )
        self._schedule_config_checks(run, profile, valid_ping_targets)
        current_trains = self.repository.list_train_runs(str(run["run_id"]))
        disk_free = shutil.disk_usage(
            self.paths.ground_unattended_root(self.site_id).parent
        ).free
        disk_warning = disk_free < profile.storage_warning_free_gb * 1024**3
        disk_critical = disk_free < profile.storage_critical_free_gb * 1024**3
        import time

        if (
            time.monotonic() - self._last_disk_check_monotonic >= 60
            or self._last_disk_check_monotonic == 0
        ):
            current_run = self.repository.get_run(str(run["run_id"])) or run
            summary = dict(current_run.get("summary") or {})
            summary["disk_used_bytes"] = self._managed_directory_size(
                self.paths.ground_unattended_active_dir(
                    self.site_id, str(run["run_date"])
                )
            )
            self.repository.update_run(str(run["run_id"]), summary_json=summary)
            self._last_disk_check_monotonic = time.monotonic()
        if self.deep_scheduler is not None:
            if disk_critical:
                self.deep_scheduler.stop_all(
                    str(run["run_id"]),
                    reason="critical_disk_space",
                    max_finalizing_mrs=profile.max_finalizing_mrs,
                )
            self.deep_scheduler.tick(
                str(run["run_id"]),
                profile,
                current_trains,
                paused=(
                    scheduling_paused
                    or disk_warning
                    or not profile.deep_collection_master_enabled
                ),
            )
        self.repository.update_run(
            str(run["run_id"]),
            state="PAUSED" if scheduling_paused else "RUNNING",
            ac_last_updated_at=received_at,
            ac_freshness_status="FRESH" if fresh else "STALE" if ac_rows else "NO_DATA",
            ping_sample_count=self.fleet_ping.sample_count,
        )
        for snapshot in new_snapshots:
            self._last_processed_snapshot_id_by_controller[
                str(snapshot.controller_id)
            ] = int(snapshot.id)
        current_run = self.repository.get_run(str(run["run_id"])) or run
        summary = dict(current_run.get("summary") or {})
        summary["ac_last_processed_snapshot_ids"] = dict(
            self._last_processed_snapshot_id_by_controller
        )
        self.repository.update_run(
            str(run["run_id"]), summary_json=summary
        )

    @staticmethod
    def _coverage_status_for_classification(previous, train) -> str:
        previous_status = str((previous or {}).get("coverage_status") or "")
        if previous_status in {"COLLECTING", "PARTIAL", "COVERED", "FAILED"}:
            return previous_status
        if train.deep_collection_eligible:
            return "WAITING"
        if train.eligibility_status == "OFFLINE":
            return "OFFLINE"
        if train.eligibility_status in {
            "DEPOT",
            "PARKING_LOT",
            "STORAGE_TRACK",
            "NON_MAIN_PATH",
            "DEPOT_CONNECTION",
            "MAINLINE_STATIONARY",
        }:
            return "EXCLUDED"
        return "NOT_SEEN"

    def _ensure_ac_resident_pollers(self, run, profile) -> None:
        if self.ac_resident_service is None:
            return
        for controller in self.vehicle_query.list_controllers(self.site_id):
            if not controller.connection_ready:
                continue
            try:
                result = self.ac_resident_service.ensure_poller(
                    site_name=self.site_id,
                    run_id=str(run["run_id"]),
                    controller_id=controller.controller_id,
                    controller_name=controller.name,
                    poll_interval_seconds=profile.ac_poll_interval_seconds,
                    include_switch_history=False,
                )
                if result.already_running:
                    continue
                self.repository.add_event(
                    run_id=str(run["run_id"]),
                    event_type=(
                        "ac_poller_recovered"
                        if result.recovered
                        else "ac_poller_started"
                    ),
                    title=(
                        "已恢复 AC Mesh-Link 常驻轮询"
                        if result.recovered
                        else "AC Mesh-Link 常驻轮询已启动"
                    ),
                    details={
                        "task_id": result.task.task_id,
                        "controller_id": controller.controller_id,
                        "poll_session_id": result.poll_session_id,
                    },
                )
            except Exception as exc:
                self.repository.add_event(
                    run_id=str(run["run_id"]),
                    event_type="ac_poller_start_failed",
                    severity="warning",
                    title="AC 常驻轮询启动失败",
                    message=f"{exc.__class__.__name__}: {exc}",
                    details={"controller_id": controller.controller_id},
                )

    def _latest_controller_snapshots(self) -> list[object]:
        provider = getattr(
            self.mesh_query, "list_latest_snapshots_by_controller", None
        )
        if callable(provider):
            return list(provider(self.site_id))
        page = self.mesh_query.list_recent_snapshots(
            self.site_id, page=1, page_size=100
        )
        latest: dict[str, object] = {}
        for snapshot in page.items:
            controller_id = str(snapshot.controller_id or "")
            latest.setdefault(controller_id, snapshot)
        return list(latest.values())

    def _mesh_rows_for_snapshots(
        self, snapshots: list[object]
    ) -> list[tuple[object, object]]:
        provider = getattr(self.mesh_query, "list_mrs_for_snapshot", None)
        selected: dict[str, tuple[object, object]] = {}
        for index, snapshot in enumerate(snapshots):
            rows = (
                list(provider(self.site_id, int(snapshot.id)))
                if callable(provider)
                else self._all_mesh_mrs()
                if index == 0
                else []
            )
            for item in rows:
                key = (
                    str(item.mr_device_id or item.mr_id or "")
                    or f"{item.train_no}:{item.car_end}"
                )
                previous = selected.get(key)
                if previous is None or (
                    not str(previous[0].peer_ap_name or "")
                    and str(item.peer_ap_name or "")
                ):
                    selected[key] = (item, snapshot)
        return list(selected.values())

    def _restore_processed_snapshot_ids(self, run) -> None:
        values = dict(run.get("summary") or {}).get(
            "ac_last_processed_snapshot_ids"
        )
        self._last_processed_snapshot_id_by_controller = {}
        if not isinstance(values, dict):
            return
        for controller_id, snapshot_id in values.items():
            try:
                self._last_processed_snapshot_id_by_controller[
                    str(controller_id)
                ] = int(snapshot_id)
            except (TypeError, ValueError):
                continue

    def _finalize_run(self, run, *, archive: bool) -> None:
        run_id = str(run["run_id"])
        operation = self.repository.latest_operation(
            run_id=run_id, active_only=True
        )
        latest_operation = self.repository.latest_operation(run_id=run_id)
        if (
            operation is None
            and latest_operation is not None
            and latest_operation.get("operation_state") == "FAILED"
            and str(run.get("requested_action") or "")
            in {"stop", "stop_and_archive"}
        ):
            return
        if operation is None:
            now = self._now().isoformat(timespec="milliseconds")
            operation = self.repository.save_operation(
                {
                    "operation_id": f"groundop_{uuid.uuid4().hex}",
                    "site_id": self.site_id,
                    "run_id": run_id,
                    "operation_type": "STOP_AND_ARCHIVE" if archive else "STOP",
                    "operation_state": "RUNNING",
                    "operation_stage": "STOP_REQUESTED",
                    "progress_percent": 5,
                    "message": "正在执行无人值守运行收尾",
                    "started_at": now,
                    "updated_at": now,
                }
            )
        operation_id = str(operation["operation_id"])
        self._operation_progress(
            operation_id,
            stage="FINALIZING",
            percent=15,
            message="正在安全结束深度采集任务",
        )
        self.repository.update_run(run_id, state="FINALIZING")
        if self.deep_scheduler is not None:
            active_profile = self._active_profile or self.repository.get_profile()
            self.deep_scheduler.stop_all(
                run_id,
                reason="run_window_ended",
                max_finalizing_mrs=active_profile.max_finalizing_mrs,
            )
            self.deep_scheduler.tick(
                run_id,
                active_profile,
                self.repository.list_train_runs(run_id),
                paused=True,
            )
        self._operation_progress(
            operation_id,
            stage="STOPPING_AC_POLLER",
            percent=22,
            message="正在停止 AC 常驻轮询",
        )
        if self.ac_resident_service is not None:
            ac_stop = self.ac_resident_service.request_stop_run(
                site_name=self.site_id,
                run_id=run_id,
                timeout_seconds=25.0,
            )
            if not ac_stop.success:
                self._fail_operation(
                    operation_id,
                    run_id,
                    code="AC_POLLER_STOP_TIMEOUT",
                    message="AC 常驻轮询未在停止预算内退出",
                    result={"ac_pollers": list(ac_stop.pollers)},
                )
                return
        if self.deep_scheduler is not None:
            if self.deep_scheduler.has_active_automated():
                return
            for train in self.repository.list_train_runs(run_id):
                if train.get("coverage_status") not in {"COLLECTING", "WAITING"}:
                    continue
                self.repository.update_train_run(
                    run_id,
                    str(train["train_id"]),
                    coverage_status="PARTIAL",
                    failure_reason=str(train.get("failure_reason") or "")
                    or "运行停止时本轮深度采集未覆盖全部可用 MR",
                    operations_json={},
                )
        self._operation_progress(
            operation_id,
            stage="STOPPING_PING",
            percent=25,
            message="正在停止长 Ping",
        )
        ping_result = self.fleet_ping.stop()
        if not bool(ping_result.get("success")):
            self._fail_operation(
                operation_id,
                run_id,
                code="FPING_STOP_TIMEOUT",
                message="长 Ping worker 未在停止预算内退出",
                result={"ping": ping_result},
            )
            return
        self._operation_progress(
            operation_id,
            stage="STOPPING_SYSLOG",
            percent=40,
            message="正在停止 Syslog UDP 接收",
            result={"ping": ping_result},
        )
        syslog_result = self.syslog_receiver.stop()
        if not bool(syslog_result.get("success")):
            self._fail_operation(
                operation_id,
                run_id,
                code="SYSLOG_STOP_TIMEOUT",
                message="Syslog 接收线程或队列未能安全停止",
                result={"ping": ping_result, "syslog": syslog_result},
            )
            return
        self._operation_progress(
            operation_id,
            stage="FLUSHING_QUEUE",
            percent=50,
            message="Syslog 接收队列已清空",
            result={"ping": ping_result, "syslog": syslog_result},
        )
        self._operation_progress(
            operation_id,
            stage="CLOSING_FILES",
            percent=55,
            message="正在核对原始文件关闭状态",
        )
        recovered_file_count = recover_raw_files(
            active_dir=self.paths.ground_unattended_active_dir(
                self.site_id, str(run["run_date"])
            ),
            repository=self.repository,
            run_id=run_id,
        )
        open_files = self.repository.list_open_raw_files(run_id)
        if open_files:
            self._fail_operation(
                operation_id,
                run_id,
                code="RAW_FILES_STILL_OPEN",
                message="仍有原始文件处于 OPEN 状态，停止流程未完成",
                result={
                    "ping": ping_result,
                    "syslog": syslog_result,
                    "open_file_ids": [
                        str(row.get("file_id") or "") for row in open_files
                    ],
                },
            )
            return
        ended_at = self._now().isoformat(timespec="milliseconds")
        result_summary: dict[str, Any] = {
            "run_id": run_id,
            "ping_sample_count": int(ping_result.get("sample_count") or 0),
            "syslog_record_count": int(
                syslog_result.get("received_count") or 0
            ),
            "closed_file_count": int(
                syslog_result.get("closed_file_count") or 0
            )
            + int(ping_result.get("closed_file_count") or 0)
            + recovered_file_count,
            "queue_dropped_count": int(
                syslog_result.get("dropped_count") or 0
            ),
            "unarchived_file_count": self.repository.count_unarchived_raw_files(
                run_id
            ),
            "udp_port_released": bool(
                syslog_result.get("udp_port_released")
            ),
            "fping_processes_exited": bool(
                ping_result.get("fping_processes_exited")
            ),
        }
        self._operation_progress(
            operation_id,
            stage="FINALIZING",
            percent=60,
            message="正在保存运行汇总",
            result=result_summary,
        )
        self.repository.update_run(
            run_id,
            state="ARCHIVING" if archive else "COMPLETED",
            actual_ended_at=ended_at,
            ping_sample_count=int(ping_result.get("sample_count") or 0),
        )
        archive_result = None
        if archive:
            archive_result = self.archive_service.archive_run(
                run_id,
                self._active_profile or self.repository.get_profile(),
                progress_callback=lambda stage, percent, message, details: (
                    self._operation_progress(
                        operation_id,
                        stage=stage,
                        percent=percent,
                        message=message,
                        result=details,
                    )
                ),
            )
            self.repository.update_run(
                run_id,
                state="COMPLETED",
                error_code=""
                if archive_result.success
                else "GROUND_UNATTENDED_ARCHIVE_FAILED",
                error_message="" if archive_result.success else archive_result.message,
            )
            archive_row = self.repository.get_archive(archive_result.archive_id) or {}
            result_summary.update(
                {
                    "archive_id": archive_result.archive_id,
                    "archive_status": str(
                        archive_row.get("archive_status") or ""
                    ),
                    "archive_relative_path": str(
                        archive_row.get("relative_path") or ""
                    ),
                    "archive_size_bytes": int(
                        archive_row.get("archive_size_bytes") or 0
                    ),
                    "archive_sha256": str(archive_row.get("sha256") or ""),
                    "active_cleanup_pending": bool(
                        archive_result.active_cleanup_pending
                    ),
                }
            )
            operation_completed_at = self._now().isoformat(
                timespec="milliseconds"
            )
            if not archive_result.success:
                self.repository.update_operation(
                    operation_id,
                    operation_state="FAILED",
                    operation_stage="FAILED",
                    progress_percent=100,
                    message=archive_result.message,
                    completed_at=operation_completed_at,
                    failure_code="GROUND_UNATTENDED_ARCHIVE_FAILED",
                    failure_reason=archive_result.message,
                    result_summary=result_summary,
                )
            else:
                self.repository.update_operation(
                    operation_id,
                    operation_state="COMPLETED",
                    operation_stage="COMPLETED",
                    progress_percent=100,
                    message="停止并归档完成",
                    completed_at=operation_completed_at,
                    failure_code="",
                    failure_reason="",
                    result_summary=result_summary,
                )
        else:
            self.repository.update_operation(
                operation_id,
                operation_state="COMPLETED",
                operation_stage="COMPLETED",
                progress_percent=100,
                message="正常停止完成。本次运行未执行归档。",
                completed_at=ended_at,
                failure_code="",
                failure_reason="",
                result_summary=result_summary,
            )
        self.repository.add_event(
            run_id=run_id,
            event_type="run_completed",
            severity=(
                "warning"
                if archive_result is not None and not archive_result.success
                else "info"
            ),
            title="地面无人值守运行已停止",
            message=archive_result.message if archive_result else "",
        )
        self._active_profile = None
        self._manual_start = False
        self._last_valid_ping_targets = {}
        self._last_processed_snapshot_id_by_controller = {}

    def _operation_progress(
        self,
        operation_id: str,
        *,
        stage: str,
        percent: int,
        message: str,
        result: dict[str, Any] | None = None,
    ) -> None:
        current = self.repository.get_operation(operation_id) or {}
        summary = dict(current.get("result_summary") or {})
        summary.update(result or {})
        self.repository.update_operation(
            operation_id,
            operation_state="RUNNING",
            operation_stage=stage,
            progress_percent=percent,
            message=message,
            result_summary=summary,
        )

    def _fail_operation(
        self,
        operation_id: str,
        run_id: str,
        *,
        code: str,
        message: str,
        result: dict[str, Any],
    ) -> None:
        completed_at = self._now().isoformat(timespec="milliseconds")
        self.repository.update_operation(
            operation_id,
            operation_state="FAILED",
            operation_stage="FAILED",
            progress_percent=100,
            message=message,
            completed_at=completed_at,
            failure_code=code,
            failure_reason=message,
            result_summary=result,
        )
        self.repository.update_run(
            run_id,
            state="ERROR",
            error_code=code,
            error_message=message,
        )
        self.repository.add_event(
            run_id=run_id,
            event_type="stop_failed",
            severity="error",
            title="无人值守停止流程失败",
            message=message,
            details={"operation_id": operation_id, "code": code, **result},
        )

    def _shutdown_active_run(self) -> None:
        run = self.repository.get_active_run()
        if run is None:
            return
        self.repository.update_run(
            str(run["run_id"]),
            state="FINALIZING",
            requested_action="application_shutdown",
        )
        self._finalize_run(run, archive=False)

    def _start_fleet_ping(
        self, run: dict[str, Any], profile: GroundUnattendedProfileDTO
    ) -> None:
        self.fleet_ping.start(
            run_id=str(run["run_id"]),
            run_date=str(run["run_date"]),
            active_dir=self.paths.ground_unattended_active_dir(
                self.site_id, str(run["run_date"])
            ),
            period_ms=profile.fleet_ping_interval_ms,
            timeout_ms=profile.fleet_ping_timeout_ms,
            packet_size=profile.fleet_ping_packet_size,
            shard_size=profile.fleet_ping_shard_size,
            warmup_seconds=profile.fleet_ping_warmup_seconds,
            correlation_tolerance_seconds=profile.ac_ping_correlation_tolerance_seconds,
            switch_before_seconds=profile.ap_switch_before_seconds,
            switch_after_seconds=profile.ap_switch_after_seconds,
        )

    def _start_syslog(
        self, run: dict[str, Any], profile: GroundUnattendedProfileDTO
    ) -> None:
        try:
            self.syslog_receiver.start(
                run_id=str(run["run_id"]),
                run_date=str(run["run_date"]),
                active_dir=self.paths.ground_unattended_active_dir(
                    self.site_id, str(run["run_date"])
                ),
                listen_host=profile.udp_listen_host,
                listen_port=profile.udp_listen_port,
                queue_capacity=profile.udp_queue_capacity,
                flush_records=profile.raw_flush_record_count,
                flush_interval_seconds=profile.raw_flush_interval_seconds,
                event_batch_size=profile.event_batch_size,
                event_batch_interval_seconds=profile.event_batch_interval_seconds,
            )
            self.syslog_receiver.update_ap_locations(
                self.base_query.list_ap_location_items(self.site_id)
            )
        except Exception as exc:
            self.repository.add_health_event(
                run_id=str(run["run_id"]),
                component="udp_receiver",
                severity="error",
                code="UDP_LISTEN_START_FAILED",
                message=f"{exc.__class__.__name__}: {exc}",
                details={
                    "listen_host": profile.udp_listen_host,
                    "listen_port": profile.udp_listen_port,
                },
            )
            raise

    def _schedule_config_checks(
        self,
        run: dict[str, Any],
        profile: GroundUnattendedProfileDTO,
        targets: dict[str, FleetPingTarget],
    ) -> None:
        target_ip = str(profile.syslog_server_ip or "").strip()
        if not target_ip:
            return
        live = {
            str(row.get("mr_id") or ""): row
            for row in self.fleet_ping.target_summaries()
        }
        with self._lock:
            manual = dict(self._manual_config_checks)
            self._manual_config_checks.clear()
        policies = {
            str(row["train_id"]): row
            for row in self.repository.list_inventory(include_removed=False)
        }
        endpoints = {
            target.mr_id: target for target in targets.values() if target.mr_id
        }
        if "*" in manual:
            for device_uuid in endpoints:
                manual.setdefault(device_uuid, False)
        now = self._now()
        ordered = sorted(
            endpoints.items(),
            key=lambda item: (
                0 if policies.get(item[1].train_id, {}).get("priority") else 1,
                -int(
                    policies.get(item[1].train_id, {}).get("scheduling_priority")
                    or 0
                ),
                item[1].train_no,
                item[0],
            ),
        )
        for device_uuid, target in ordered:
            if device_uuid in self._config_futures:
                continue
            if (
                device_uuid not in manual
                and int((live.get(device_uuid) or {}).get("success_count") or 0) <= 0
            ):
                continue
            latest = self.repository.latest_syslog_config_audit(device_uuid)
            if device_uuid not in manual and latest:
                checked_at = self._parse_datetime(str(latest.get("checked_at") or ""))
                if (
                    checked_at
                    and (now - checked_at).total_seconds()
                    < profile.config_check_cooldown_seconds
                ):
                    continue
            self._config_futures[device_uuid] = self._config_executor.submit(
                self.config_service.check,
                run_id=str(run["run_id"]),
                run_date=str(run["run_date"]),
                device_uuid=device_uuid,
                target_ip=target_ip,
                target_port=profile.syslog_server_port,
                boot_tolerance_seconds=profile.boot_time_tolerance_seconds,
                allow_target_port_change=bool(manual.get(device_uuid, False)),
            )

    def _collect_config_checks(self) -> None:
        for device_uuid, future in tuple(self._config_futures.items()):
            if not future.done():
                continue
            self._config_futures.pop(device_uuid, None)
            try:
                future.result()
            except Exception:
                # Service 已持久化结构化失败审计，Supervisor 继续调度其他 MR。
                pass

    @staticmethod
    def _parse_datetime(value: str) -> datetime | None:
        try:
            result = datetime.fromisoformat(value)
            return result if result.tzinfo else result.astimezone()
        except (TypeError, ValueError):
            return None

    def _handle_archive_deletes(self) -> None:
        with self._lock:
            requests, self._archive_delete_requests = self._archive_delete_requests, []
        for archive_id in requests:
            try:
                self.archive_service.delete_archive(archive_id)
                self.repository.add_event(
                    event_type="archive_deleted",
                    title="历史无人值守归档已删除",
                    details={"archive_id": archive_id},
                )
            except Exception as exc:
                self.repository.add_event(
                    event_type="archive_delete_failed",
                    severity="error",
                    title="历史无人值守归档删除失败",
                    message=f"{exc.__class__.__name__}: {exc}",
                    details={"archive_id": archive_id},
                )

    def _append_ac_snapshot_file(
        self,
        run_date: str,
        rows: list[dict[str, Any]],
        now: datetime,
    ) -> None:
        root = (
            self.paths.ground_unattended_active_dir(self.site_id, run_date)
            / "ac_snapshots"
        )
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"ac_{now.strftime('%Y%m%d_%H')}.jsonl"
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()

    @staticmethod
    def _managed_directory_size(root) -> int:
        total = 0
        if not root.is_dir() or root.is_symlink():
            return 0
        for path in root.rglob("*"):
            if path.is_file() and not path.is_symlink():
                try:
                    total += path.stat().st_size
                except OSError:
                    continue
        return total

    def _all_mesh_mrs(self):
        first = self.mesh_query.list_mrs(self.site_id, page=1, page_size=200)
        rows = list(first.items)
        page = 2
        while len(rows) < first.total:
            current = self.mesh_query.list_mrs(self.site_id, page=page, page_size=200)
            if not current.items:
                break
            rows.extend(current.items)
            page += 1
        return rows

    def _all_base_mrs(self):
        first = self.base_query.list_mrs(self.site_id, page=1, page_size=200)
        rows = list(first.items)
        page = 2
        while len(rows) < first.total:
            current = self.base_query.list_mrs(self.site_id, page=page, page_size=200)
            if not current.items:
                break
            rows.extend(current.items)
            page += 1
        return rows

    def _all_stations(self):
        first = self.base_query.list_stations(self.site_id, page=1, page_size=200)
        rows = list(first.items)
        page = 2
        while len(rows) < first.total:
            current = self.base_query.list_stations(
                self.site_id, page=page, page_size=200
            )
            if not current.items:
                break
            rows.extend(current.items)
            page += 1
        return rows

    def _all_sections(self):
        first = self.base_query.list_sections(self.site_id, page=1, page_size=200)
        rows = list(first.items)
        page = 2
        while len(rows) < first.total:
            current = self.base_query.list_sections(
                self.site_id, page=page, page_size=200
            )
            if not current.items:
                break
            rows.extend(current.items)
            page += 1
        return rows

    def _now(self) -> datetime:
        value = self.now_provider()
        if value.tzinfo is None:
            value = value.replace(
                tzinfo=resolve_timezone(self.repository.get_profile().timezone)
            )
        return value


__all__ = ["GroundUnattendedSupervisor"]
