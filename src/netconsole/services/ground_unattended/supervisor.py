from __future__ import annotations

import logging
import json
import shutil
import threading
import uuid
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
from netconsole.services.rail_transit.base_data_query_service import (
    RailTransitBaseDataQueryService,
)
from netconsole.services.rail_transit.train_identity import canonical_train_id_for
from netconsole.services.rail_transit.vehicle_mr_online_query_service import (
    VehicleMrOnlineQueryService,
)


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SupervisorCommand:
    action: str
    archive: bool = False


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
        online_mr_application_service: OnlineMrApplicationService | None = None,
        online_mr_query_service: OnlineMrQueryService | None = None,
        now_provider: Callable[[], datetime] | None = None,
        tick_seconds: float = 1.0,
    ) -> None:
        self.paths = paths
        self.site_id = site_id
        self.repository = repository
        self.base_query = base_query
        self.mesh_query = mesh_query
        self.vehicle_query = vehicle_query
        self.ac_refresh_service = ac_refresh_service
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
        if self.deep_scheduler is not None:
            self.deep_scheduler.close()

    def request(self, action: str, *, archive: bool = False) -> None:
        if action not in {"start", "pause", "resume", "stop"}:
            raise ValueError("unsupported ground unattended action")
        with self._lock:
            self._commands.append(SupervisorCommand(action, archive))
        self._wake_event.set()

    def profile_updated(self) -> None:
        self._wake_event.set()

    def request_archive_delete(self, archive_id: str) -> None:
        with self._lock:
            self._archive_delete_requests.append(str(archive_id))
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
            self._active_profile = profile
            self._start_fleet_ping(run, profile)
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
        self._start_fleet_ping(run, profile)
        self._last_ac_poll_monotonic = 0.0
        self.repository.update_run(str(run["run_id"]), state="RUNNING")
        self.repository.add_event(
            run_id=str(run["run_id"]),
            event_type="run_started",
            title="地面无人值守运行已开始",
            message=f"运行窗口 {profile.schedule_start_time} - {profile.schedule_end_time}",
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

        current = time.monotonic()
        if current - self._last_ac_poll_monotonic < profile.ac_poll_interval_seconds:
            return
        self._last_ac_poll_monotonic = current
        self._poll_ac_and_classify(
            run, profile, now, scheduling_paused=scheduling_paused
        )
        self.repository.update_run(
            str(run["run_id"]),
            state="PAUSED" if scheduling_paused else "RUNNING",
            ac_last_updated_at=now.isoformat(timespec="milliseconds"),
        )

    def _poll_ac_and_classify(
        self, run, profile, now, *, scheduling_paused: bool
    ) -> None:
        self._request_ac_refreshes(run)
        ac_rows = self._all_mesh_mrs()
        latest_snapshot_page = self.mesh_query.list_recent_snapshots(
            self.site_id,
            page=1,
            page_size=30,
        )
        latest_snapshot = (
            latest_snapshot_page.items[0] if latest_snapshot_page.items else None
        )
        snapshot_batch_id = f"ac_{uuid.uuid4().hex}"
        received_at = (
            str(latest_snapshot.collected_at)
            if latest_snapshot and latest_snapshot.collected_at
            else now.isoformat(timespec="milliseconds")
        )
        base_mrs = self._all_base_mrs()
        base_by_train = {
            canonical_train_id_for(item.train_no or item.train_id): item.train_id
            for item in base_mrs
            if canonical_train_id_for(item.train_no or item.train_id)
        }
        persisted_rows = []
        for item in ac_rows:
            key = canonical_train_id_for(item.train_no)
            train_id = base_by_train.get(key, f"mesh:{key}" if key else "")
            persisted_rows.append(
                {
                    "snapshot_id": snapshot_batch_id,
                    "site_id": self.site_id,
                    "run_id": str(run["run_id"]),
                    "ac_device_id": latest_snapshot.controller_id
                    if latest_snapshot
                    else "",
                    "source_snapshot_id": latest_snapshot.id
                    if latest_snapshot
                    else None,
                    "device_time": latest_snapshot.ac_time if latest_snapshot else "",
                    "received_at": received_at,
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
                    "raw_source_reference": latest_snapshot.source_reference
                    if latest_snapshot
                    else "",
                }
            )
        ac_ids = (
            self.repository.insert_ac_rows(persisted_rows) if persisted_rows else {}
        )
        if persisted_rows:
            self._append_ac_snapshot_file(str(run["run_date"]), persisted_rows, now)
        priorities = self.repository.list_priority_train_ids()
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
            train.priority = train.train_id in priorities
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
                None,
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
                        mr_position_code=endpoint.endpoint,
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
                paused=scheduling_paused or disk_warning,
            )
        self.repository.update_run(
            str(run["run_id"]),
            ac_last_updated_at=received_at,
            ac_freshness_status="FRESH" if fresh else "STALE" if ac_rows else "NO_DATA",
            ping_sample_count=self.fleet_ping.sample_count,
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

    def _request_ac_refreshes(self, run) -> None:
        if self.ac_refresh_service is None:
            return
        for controller in self.vehicle_query.list_controllers(self.site_id):
            if not controller.connection_ready:
                continue
            try:
                result = self.ac_refresh_service.start_refresh(
                    site_name=self.site_id,
                    controller_id=controller.controller_id,
                    include_switch_history=False,
                )
                if not result.already_running:
                    self.repository.add_event(
                        run_id=str(run["run_id"]),
                        event_type="ac_poll_started",
                        title="AC Mesh-Link 轮询任务已创建",
                        details={
                            "task_id": result.task.task_id,
                            "controller_id": controller.controller_id,
                        },
                    )
            except Exception as exc:
                self.repository.add_event(
                    run_id=str(run["run_id"]),
                    event_type="ac_poll_failed",
                    severity="warning",
                    title="AC 轮询启动失败",
                    message=f"{exc.__class__.__name__}: {exc}",
                    details={"controller_id": controller.controller_id},
                )

    def _finalize_run(self, run, *, archive: bool) -> None:
        run_id = str(run["run_id"])
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
        self.fleet_ping.stop()
        ended_at = self._now().isoformat(timespec="milliseconds")
        self.repository.update_run(
            run_id,
            state="ARCHIVING" if archive else "COMPLETED",
            actual_ended_at=ended_at,
            ping_sample_count=self.fleet_ping.sample_count,
        )
        archive_result = None
        if archive:
            archive_result = self.archive_service.archive_run(
                run_id,
                self._active_profile or self.repository.get_profile(),
            )
            self.repository.update_run(
                run_id,
                state="COMPLETED",
                error_code=""
                if archive_result.success
                else "GROUND_UNATTENDED_ARCHIVE_FAILED",
                error_message="" if archive_result.success else archive_result.message,
            )
        self.repository.add_event(
            run_id=run_id,
            event_type="run_completed",
            title="地面无人值守运行已正常停止",
            message=archive_result.message if archive_result else "",
        )
        self._active_profile = None
        self._manual_start = False
        self._last_valid_ping_targets = {}

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
            correlation_tolerance_seconds=profile.ac_ping_correlation_tolerance_seconds,
            switch_before_seconds=profile.ap_switch_before_seconds,
            switch_after_seconds=profile.ap_switch_after_seconds,
        )

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
