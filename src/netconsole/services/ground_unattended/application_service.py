from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.models.api.ground_unattended import (
    GroundActionResponseDTO,
    GroundArchiveDTO,
    GroundArchivePageDTO,
    GroundDeepCollectionDTO,
    GroundDeepCollectionPageDTO,
    GroundPingSummaryPageDTO,
    GroundPingTargetDTO,
    GroundHealthDTO,
    GroundInventorySummaryDTO,
    GroundRawFileDTO,
    GroundRawFilePageDTO,
    GroundTrainPolicyUpdateDTO,
    GroundTimelineEventDTO,
    GroundTimelinePageDTO,
    GroundUnattendedEndpointDTO,
    GroundUnattendedProfileDTO,
    GroundUnattendedProfileUpdateDTO,
    GroundUnattendedStatusDTO,
    GroundUnattendedTrainDTO,
    GroundUnattendedTrainPageDTO,
)
from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)
from netconsole.services.ground_unattended.deep_scheduler import (
    DeepMrCollectionScheduler,
)
from netconsole.services.ground_unattended.inventory import TrainInventorySyncService
from netconsole.services.ground_unattended.schedule import schedule_window
from netconsole.services.ground_unattended.supervisor import GroundUnattendedSupervisor
from netconsole.models.api.system_maintenance import DesktopActionDTO
from netconsole.services.rail_transit.base_data_query_service import (
    RailTransitBaseDataQueryService,
)
from netconsole.services.rail_transit.train_identity import canonical_train_id_for


class DesktopActionResultPort(Protocol):
    success: bool
    code: str
    message: str


class DesktopActionPort(Protocol):
    def open_controlled_path(
        self,
        path: Path,
        *,
        expect_directory: bool,
    ) -> DesktopActionResultPort: ...


class GroundUnattendedError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class GroundUnattendedApplicationService:
    def __init__(
        self,
        paths: PathResolver,
        *,
        site_id: str,
        repository: GroundUnattendedRepository,
        supervisor: GroundUnattendedSupervisor,
        base_query: RailTransitBaseDataQueryService | None = None,
        desktop_action_service: DesktopActionPort | None = None,
    ) -> None:
        self.paths = paths
        self.site_id = site_id
        self.repository = repository
        self.supervisor = supervisor
        self.base_query = base_query
        self.desktop_action_service = desktop_action_service
        self.inventory_sync = (
            TrainInventorySyncService(
                paths,
                site_id=site_id,
                repository=repository,
                base_query=base_query,
            )
            if base_query is not None
            else None
        )

    def current_site_id(self) -> str:
        """返回组合根创建本服务时绑定且已校验的局点。"""

        try:
            return SiteManager(self.paths).validate_site_name(self.site_id)
        except ValueError as exc:
            raise GroundUnattendedError(
                "SITE_INVALID", "当前局点标识无效", status_code=422
            ) from exc

    def get_profile(self, site_id: str) -> GroundUnattendedProfileDTO:
        self._require_site(site_id)
        return self.repository.get_profile()

    def update_profile(
        self,
        site_id: str,
        profile: GroundUnattendedProfileUpdateDTO,
    ) -> GroundUnattendedProfileDTO:
        self._require_site(site_id)
        if profile.site_id != site_id:
            raise GroundUnattendedError("SITE_MISMATCH", "配置局点必须与当前局点一致")
        saved = self.repository.save_profile(
            GroundUnattendedProfileDTO.model_validate(profile.model_dump(mode="json"))
        )
        self.supervisor.profile_updated()
        self.repository.add_event(
            event_type="profile_updated",
            title="地面无人值守配置已保存",
            message="正在运行的任务在下一次调度周期读取新配置；当前采集任务不会被强制重启。",
        )
        return saved

    def status(self, site_id: str) -> GroundUnattendedStatusDTO:
        self._require_site(site_id)
        profile = self.repository.get_profile()
        now = datetime.now().astimezone()
        window = schedule_window(
            now,
            profile.schedule_start_time,
            profile.schedule_end_time,
            profile.timezone,
        )
        run = self.repository.get_active_run() or self.repository.latest_run() or {}
        run_id = str(run.get("run_id") or "")
        trains = self.repository.list_train_runs(run_id) if run_id else []
        archives = self.repository.list_archives()
        inventory = self.repository.list_inventory(include_removed=False)
        syslog_health = self._syslog_health()
        config_abnormal = 0
        syslog_active = 0
        for train in inventory:
            for endpoint in train.get("endpoints", []):
                boot = self.repository.latest_boot_session(
                    str(endpoint.get("device_uuid") or "")
                )
                if boot and boot.get("last_syslog_received_at"):
                    syslog_active += 1
                audit = self.repository.latest_syslog_config_audit(
                    str(endpoint.get("device_uuid") or "")
                )
                if audit and audit.get("status") == "CONFIG_FAILED":
                    config_abnormal += 1
        disk = shutil.disk_usage(self.paths.ground_unattended_root(site_id).parent)
        state = str(
            run.get("state") or ("WAITING_WINDOW" if profile.enabled else "DISABLED")
        )
        if state == "COMPLETED" and profile.enabled and not window.active:
            state = "WAITING_WINDOW"
        return GroundUnattendedStatusDTO(
            site_id=site_id,
            enabled=profile.enabled,
            state=state,  # type: ignore[arg-type]
            paused=bool(run.get("paused")),
            run_id=run_id,
            run_date=str(run.get("run_date") or ""),
            actual_started_at=str(run.get("actual_started_at") or ""),
            actual_ended_at=str(run.get("actual_ended_at") or ""),
            schedule_start_time=profile.schedule_start_time,
            schedule_end_time=profile.schedule_end_time,
            timezone=profile.timezone,
            next_start_at=window.next_start.isoformat(timespec="seconds"),
            next_end_at=window.next_end.isoformat(timespec="seconds"),
            ac_last_updated_at=str(run.get("ac_last_updated_at") or ""),
            ac_freshness_status=str(run.get("ac_freshness_status") or "NO_DATA"),
            mainline_train_count=sum(
                row.get("eligibility_status") in {"MAINLINE", "MAINLINE_STATIONARY"}
                for row in trains
            ),
            ping_target_count=self.supervisor.fleet_ping.target_count
            or sum(
                bool(endpoint.get("management_ip"))
                and endpoint.get("online_status") == "ONLINE"
                for row in trains
                if row.get("ping_eligible")
                for endpoint in row.get("endpoints", [])
            ),
            active_deep_train_count=sum(
                row.get("coverage_status") == "COLLECTING" for row in trains
            ),
            covered_train_count=sum(
                row.get("coverage_status") == "COVERED" for row in trains
            ),
            incomplete_train_count=sum(
                row.get("coverage_status") not in {"COVERED", "EXCLUDED"}
                for row in trains
            ),
            inventory_train_count=len(inventory),
            syslog_active_mr_count=syslog_active,
            config_abnormal_count=config_abnormal,
            data_quality_warning_count=int(
                syslog_health.get("udp_unidentified_count") or 0
            )
            + int(syslog_health.get("udp_dropped_count") or 0),
            disk_used_bytes=int((run.get("summary") or {}).get("disk_used_bytes") or 0),
            disk_free_bytes=disk.free,
            disk_status=(
                "CRITICAL"
                if disk.free < profile.storage_critical_free_gb * 1024**3
                else "WARNING"
                if disk.free < profile.storage_warning_free_gb * 1024**3
                else "OK"
            ),
            latest_archive_status=str(archives[0].get("archive_status") or "")
            if archives
            else "",
            latest_archive_message=str(archives[0].get("message") or "")
            if archives
            else "",
            message=str(run.get("error_message") or ""),
            updated_at=datetime.now().astimezone().isoformat(timespec="milliseconds"),
        )

    def start_now(self, site_id: str) -> GroundActionResponseDTO:
        self._require_site(site_id)
        profile = self.repository.get_profile()
        if not profile.enabled:
            raise GroundUnattendedError(
                "PROFILE_DISABLED",
                "请先启用当前局点的地面无人值守配置",
                status_code=409,
            )
        active = self.repository.get_active_run()
        if active is not None:
            return GroundActionResponseDTO(
                state=str(active["state"]),
                run_id=str(active["run_id"]),
                message="当前无人值守运行已存在，无需重复启动",
            )
        window = schedule_window(
            datetime.now().astimezone(),
            profile.schedule_start_time,
            profile.schedule_end_time,
            profile.timezone,
        )
        latest = self.repository.latest_run()
        if latest and str(latest.get("run_date") or "") == window.run_date:
            archive = self.repository.get_archive_by_run(str(latest["run_id"]))
            if archive and archive.get("archive_status") == "READY":
                raise GroundUnattendedError(
                    "DAILY_RUN_ARCHIVED",
                    "当前运行日已完成正式归档，不能再次启动并覆盖当日归档",
                    status_code=409,
                )
        self.supervisor.request("start")
        return GroundActionResponseDTO(state="STARTING", message="立即开始请求已提交")

    def pause(self, site_id: str) -> GroundActionResponseDTO:
        run = self._active(site_id)
        self.supervisor.request("pause")
        return GroundActionResponseDTO(
            state="PAUSED",
            run_id=str(run["run_id"]),
            message="深度采集调度将暂停，长 Ping 继续",
        )

    def resume(self, site_id: str) -> GroundActionResponseDTO:
        run = self._active(site_id)
        self.supervisor.request("resume")
        return GroundActionResponseDTO(
            state="RUNNING", run_id=str(run["run_id"]), message="深度采集调度将继续"
        )

    def stop(self, site_id: str, *, archive: bool) -> GroundActionResponseDTO:
        run = self._active(site_id)
        self.supervisor.request("stop", archive=archive)
        return GroundActionResponseDTO(
            state="STOPPING",
            run_id=str(run["run_id"]),
            message="停止并归档请求已提交" if archive else "正常停止请求已提交",
        )

    def list_trains(self, site_id: str) -> GroundUnattendedTrainPageDTO:
        self._require_site(site_id)
        if self.inventory_sync is not None and not self.repository.list_inventory():
            self.inventory_sync.synchronize()
        run = self._latest_run(site_id)
        rows = self.repository.list_train_runs(str(run["run_id"])) if run else []
        items = [self._train_dto(row) for row in rows]
        if not items:
            items = self._inventory_train_candidates()
        items = self._merge_inventory_policy(items)
        items = self._enrich_train_endpoints(items, run)
        return GroundUnattendedTrainPageDTO(items=items, total=len(items))

    def sync_inventory(self, site_id: str) -> GroundInventorySummaryDTO:
        self._require_site(site_id)
        if self.inventory_sync is None:
            raise GroundUnattendedError(
                "INVENTORY_SYNC_UNAVAILABLE", "设备清单同步服务不可用", status_code=503
            )
        result = self.inventory_sync.synchronize()
        receiver = getattr(self.supervisor, "syslog_receiver", None)
        if receiver is not None:
            receiver.refresh_inventory()
        self.repository.add_event(
            event_type="inventory_synchronized",
            title="无人值守设备清单已同步",
            message=f"发现 {result.discovered_train_count} 辆列车",
            details=result.model_dump(mode="json"),
        )
        return result

    def get_train(self, site_id: str, train_id: str) -> GroundUnattendedTrainDTO:
        candidate = next(
            (
                item
                for item in self.list_trains(site_id).items
                if item.train_id == train_id
            ),
            None,
        )
        if candidate is None:
            raise GroundUnattendedError(
                "TRAIN_NOT_FOUND", "无人值守列车状态不存在", status_code=404
            )
        return candidate

    def set_priority(
        self, site_id: str, train_id: str, priority: bool
    ) -> GroundUnattendedTrainDTO:
        self._require_site(site_id)
        self.repository.set_priority(train_id, priority)
        run = self.repository.get_active_run()
        if run:
            self.repository.update_train_run(
                str(run["run_id"]), train_id, priority=priority
            )
        return self.get_train(site_id, train_id)

    def update_train_policy(
        self,
        site_id: str,
        train_id: str,
        policy: GroundTrainPolicyUpdateDTO,
    ) -> GroundUnattendedTrainDTO:
        self._require_site(site_id)
        if not any(
            str(row.get("train_id") or "") == train_id
            for row in self.repository.list_inventory()
        ):
            raise GroundUnattendedError(
                "TRAIN_NOT_FOUND", "无人值守列车不存在", status_code=404
            )
        values = policy.model_dump(mode="json")
        self.repository.save_train_policy(train_id, values)
        self.repository.set_priority(train_id, policy.priority)
        run = self.repository.get_active_run()
        if run:
            self.repository.update_train_run(
                str(run["run_id"]), train_id, priority=policy.priority
            )
        self.supervisor.profile_updated()
        return self.get_train(site_id, train_id)

    def request_config_check(
        self, site_id: str, *, device_uuid: str = ""
    ) -> GroundActionResponseDTO:
        run = self._active(site_id)
        profile = self.repository.get_profile()
        if not profile.syslog_server_ip:
            raise GroundUnattendedError(
                "SYSLOG_TARGET_REQUIRED",
                "请先设置 Syslog 服务器 IP，再执行配置检查",
                status_code=409,
            )
        if device_uuid and self.repository.get_inventory_endpoint(device_uuid) is None:
            raise GroundUnattendedError(
                "MR_NOT_FOUND", "MR 不在当前无人值守清单中", status_code=404
            )
        self.supervisor.request_config_check(device_uuid)
        return GroundActionResponseDTO(
            state=str(run["state"]),
            run_id=str(run["run_id"]),
            message="MR 配置检查请求已提交",
        )

    def health(self, site_id: str) -> GroundHealthDTO:
        self._require_site(site_id)
        values = self._syslog_health()
        latest = self.repository.latest_health_event() or {}
        disk = shutil.disk_usage(self.paths.ground_unattended_root(site_id).parent)
        deep_queue = sum(
            item.status in {"NOT_SEEN", "WAITING", "PARTIAL"}
            for item in self.deep_collections(site_id).items
        )
        archives = self.repository.list_archives()
        last_error = str(values.pop("last_error", "") or latest.get("message") or "")
        status = "ERROR" if last_error else "WARNING" if values.get("udp_dropped_count") else "OK"
        return GroundHealthDTO(
            site_id=site_id,
            status=status,
            **values,
            ping_target_count=int(getattr(self.supervisor.fleet_ping, "target_count", 0)),
            ping_process_count=int(getattr(self.supervisor.fleet_ping, "process_count", 0)),
            deep_queue_length=deep_queue,
            archive_pending_count=sum(
                row.get("archive_status") in {"PENDING", "BUILDING", "FAILED"}
                for row in archives
            ),
            disk_free_bytes=disk.free,
            last_error=last_error,
            updated_at=datetime.now().astimezone().isoformat(timespec="milliseconds"),
        )

    def raw_files(
        self,
        site_id: str,
        *,
        data_type: str = "",
        status: str = "",
        limit: int = 200,
        offset: int = 0,
    ) -> GroundRawFilePageDTO:
        self._require_site(site_id)
        rows = self.repository.list_raw_files(
            data_type=data_type, status=status, limit=limit, offset=offset
        )
        return GroundRawFilePageDTO(
            items=[GroundRawFileDTO.model_validate(row) for row in rows],
            total=self.repository.count_raw_files(data_type=data_type, status=status),
        )

    def ping_summary(self, site_id: str) -> GroundPingSummaryPageDTO:
        run = self._latest_run(site_id)
        rows = self.supervisor.fleet_ping.target_summaries()
        if not rows and run:
            rows = self.repository.list_ping_summaries(str(run["run_id"]))
        items = [GroundPingTargetDTO.model_validate(row) for row in rows]
        return GroundPingSummaryPageDTO(items=items, total=len(items))

    def deep_collections(self, site_id: str) -> GroundDeepCollectionPageDTO:
        run = self._latest_run(site_id)
        rows = self.repository.list_train_runs(str(run["run_id"])) if run else []
        queue_order: list[str] = []
        scheduling: dict[str, tuple[int, str]] = {}
        if run:
            queue = self.repository.get_daily_queue(str(run["run_id"])) or {}
            queue_order = [str(value) for value in queue.get("queue_order", [])]
            ping_loss_by_train: dict[str, float] = {}
            for summary in self.repository.list_ping_summaries(str(run["run_id"])):
                train_id = str(summary.get("train_id") or "")
                ping_loss_by_train[train_id] = max(
                    ping_loss_by_train.get(train_id, 0.0),
                    float(summary.get("loss_rate_percent") or 0.0),
                )
            candidates = DeepMrCollectionScheduler.ordered_candidates(
                rows,
                queue_order=queue_order,
                ping_loss_by_train=ping_loss_by_train,
            )
            scheduling = {
                candidate.train_id: (index, candidate.reason)
                for index, candidate in enumerate(candidates, start=1)
            }
        queue_positions = {
            train_id: index for index, train_id in enumerate(queue_order, start=1)
        }
        latest_operations: dict[str, dict[str, dict[str, Any]]] = {}
        if run:
            for operation in self.repository.list_deep_operations(str(run["run_id"])):
                latest_operations.setdefault(str(operation["train_id"]), {})[
                    str(operation["mr_position_code"])
                ] = operation
        items = []
        for row in rows:
            train_id = str(row["train_id"])
            scheduling_priority, current_reason = scheduling.get(train_id, (0, ""))
            operations = row.get("operations") or {}
            sessions = row.get("sessions") or {}
            latest = latest_operations.get(train_id, {})
            items.append(
                GroundDeepCollectionDTO(
                    train_id=train_id,
                    train_no=row.get("train_no", ""),
                    status=row.get("coverage_status", "NOT_SEEN"),
                    queue_position=queue_positions.get(train_id),
                    scheduling_priority=scheduling_priority,
                    selection_reason=row.get("selection_reason") or current_reason,
                    started_at=row.get("collection_started_at", ""),
                    valid_duration_minutes=float(
                        row.get("valid_duration_minutes") or 0
                    ),
                    ct_operation_id=str(
                        operations.get("CT")
                        or (latest.get("CT") or {}).get("operation_id")
                        or ""
                    ),
                    cw_operation_id=str(
                        operations.get("CW")
                        or (latest.get("CW") or {}).get("operation_id")
                        or ""
                    ),
                    ct_session_id=str(
                        sessions.get("CT")
                        or (latest.get("CT") or {}).get("session_id")
                        or ""
                    ),
                    cw_session_id=str(
                        sessions.get("CW")
                        or (latest.get("CW") or {}).get("session_id")
                        or ""
                    ),
                    attempt_count=int(row.get("attempt_count") or 0),
                    covered_rounds=int(row.get("covered_rounds") or 0),
                    failure_reason=row.get("failure_reason", ""),
                    updated_at=row.get("updated_at", ""),
                )
            )
        return GroundDeepCollectionPageDTO(items=items, total=len(items))

    def timeline(
        self,
        site_id: str,
        *,
        train_id: str = "",
        event_type: str = "",
        limit: int = 200,
        offset: int = 0,
    ) -> GroundTimelinePageDTO:
        run = self._latest_run(site_id)
        rows = (
            self.repository.list_events(
                str(run["run_id"]),
                train_id=train_id,
                event_type=event_type,
                limit=limit,
                offset=offset,
            )
            if run
            else []
        )
        items = [
            GroundTimelineEventDTO(
                event_id=row["id"],
                ts=row["ts"],
                event_type=row["event_type"],
                severity=row["severity"],
                train_id=row["train_id"],
                mr_id=row["mr_id"],
                title=row["title"],
                message=row["message"],
                details=row.get("details") or {},
            )
            for row in rows
        ]
        return GroundTimelinePageDTO(
            items=items,
            total=self.repository.count_events(
                str(run["run_id"]), train_id=train_id, event_type=event_type
            )
            if run
            else 0,
        )

    def archives(self, site_id: str) -> GroundArchivePageDTO:
        self._require_site(site_id)
        items = [self._archive_dto(row) for row in self.repository.list_archives()]
        return GroundArchivePageDTO(items=items, total=len(items))

    def archive(self, site_id: str, archive_id: str) -> GroundArchiveDTO:
        self._require_site(site_id)
        row = self.repository.get_archive(archive_id)
        if row is None:
            raise GroundUnattendedError(
                "ARCHIVE_NOT_FOUND", "无人值守归档不存在", status_code=404
            )
        return self._archive_dto(row)

    def open_archive_directory(self, site_id: str) -> DesktopActionDTO:
        self._require_site(site_id)
        if self.desktop_action_service is None:
            raise GroundUnattendedError(
                "DESKTOP_ACTION_UNAVAILABLE",
                "当前宿主不支持打开本机目录",
                status_code=409,
            )
        path = self.paths.ground_unattended_archives_dir(site_id)
        path.mkdir(parents=True, exist_ok=True)
        result = self.desktop_action_service.open_controlled_path(
            path,
            expect_directory=True,
        )
        return DesktopActionDTO(
            success=result.success,
            code=result.code,
            message=result.message,
        )

    def request_delete_archive(
        self, site_id: str, archive_id: str, *, confirmed: bool
    ) -> GroundActionResponseDTO:
        self._require_site(site_id)
        if not confirmed:
            raise GroundUnattendedError(
                "CONFIRMATION_REQUIRED", "删除归档需要明确确认", status_code=409
            )
        row = self.repository.get_archive(archive_id)
        if row is None:
            raise GroundUnattendedError(
                "ARCHIVE_NOT_FOUND", "无人值守归档不存在", status_code=404
            )
        active = self.repository.get_active_run()
        if active and active["run_id"] == row["run_id"]:
            raise GroundUnattendedError(
                "ARCHIVE_IN_USE", "不能删除正在使用的当日数据", status_code=409
            )
        self.supervisor.request_archive_delete(archive_id)
        self.repository.add_event(
            run_id=str(row["run_id"]),
            event_type="archive_delete_requested",
            title="归档删除请求已登记",
            details={"archive_id": archive_id},
        )
        return GroundActionResponseDTO(
            state="WAITING_WINDOW",
            run_id=str(row["run_id"]),
            message="归档删除请求已提交",
        )

    def _train_dto(self, row: dict[str, Any]) -> GroundUnattendedTrainDTO:
        return GroundUnattendedTrainDTO(
            train_id=row["train_id"],
            train_no=row.get("train_no", ""),
            train_name=row.get("train_name", ""),
            ping_eligible=bool(row.get("ping_eligible")),
            deep_collection_eligible=bool(row.get("deep_collection_eligible")),
            eligibility_status=row.get("eligibility_status", "AC_UNKNOWN"),
            exclusion_reason=row.get("exclusion_reason", ""),
            current_ap_name=row.get("current_ap_name", ""),
            current_ap_mac=row.get("current_ap_mac", ""),
            station=row.get("station", ""),
            section=row.get("section", ""),
            mileage=row.get("mileage", ""),
            rssi=row.get("rssi"),
            same_ap_duration_seconds=int(row.get("same_ap_duration_seconds") or 0),
            ac_snapshot_id=row.get("ac_snapshot_id"),
            ac_received_at=row.get("ac_received_at", ""),
            coverage_status=row.get("coverage_status", "NOT_SEEN"),
            priority=bool(row.get("priority")),
            attempt_count=int(row.get("attempt_count") or 0),
            covered_rounds=int(row.get("covered_rounds") or 0),
            selection_reason=row.get("selection_reason", ""),
            failure_reason=row.get("failure_reason", ""),
            endpoints=[
                GroundUnattendedEndpointDTO.model_validate(item)
                for item in row.get("endpoints", [])
            ],
            updated_at=row.get("updated_at", ""),
        )

    def _inventory_train_candidates(self) -> list[GroundUnattendedTrainDTO]:
        result: list[GroundUnattendedTrainDTO] = []
        for row in self.repository.list_inventory(include_removed=True):
            endpoints_by_role = {
                str(item.get("mr_role") or ""): item
                for item in row.get("endpoints", [])
                if item.get("binding_status") == "ACTIVE"
            }
            endpoints = []
            for role in ("CT", "CW"):
                endpoint = endpoints_by_role.get(role) or {}
                endpoints.append(
                    GroundUnattendedEndpointDTO(
                        endpoint=role,  # type: ignore[arg-type]
                        mr_id=str(endpoint.get("device_uuid") or ""),
                        mr_name=str(endpoint.get("device_name") or ""),
                        device_id=endpoint.get("device_id"),
                        management_ip=str(endpoint.get("management_ip") or ""),
                        online_status="UNKNOWN" if endpoint else "MISSING",
                    )
                )
            result.append(
                GroundUnattendedTrainDTO(
                    train_id=str(row["train_id"]),
                    train_no=str(row.get("train_no") or ""),
                    train_name=str(row.get("train_name") or row["train_id"]),
                    eligibility_status="AC_UNKNOWN",
                    exclusion_reason="设备已移除"
                    if row.get("inventory_status") == "REMOVED"
                    else "尚未开始无人值守运行，等待实时状态",
                    coverage_status="EXCLUDED"
                    if row.get("inventory_status") == "REMOVED"
                    else "NOT_SEEN",
                    priority=bool(row.get("priority")),
                    enabled=bool(row.get("enabled", True)),
                    scheduling_priority=int(row.get("scheduling_priority") or 0),
                    deep_collection_enabled=bool(
                        row.get("deep_collection_enabled", True)
                    ),
                    monitor_only=bool(row.get("monitor_only", False)),
                    remark=str(row.get("remark") or ""),
                    inventory_status=str(row.get("inventory_status") or "ACTIVE"),
                    endpoints=endpoints,
                    updated_at=str(row.get("updated_at") or ""),
                )
            )
        return result

    def _merge_inventory_policy(
        self, items: list[GroundUnattendedTrainDTO]
    ) -> list[GroundUnattendedTrainDTO]:
        inventory = {
            str(row["train_id"]): row for row in self.repository.list_inventory()
        }
        result = []
        for item in items:
            row = inventory.get(item.train_id) or {}
            result.append(
                item.model_copy(
                    update={
                        "priority": bool(row.get("priority", item.priority)),
                        "enabled": bool(row.get("enabled", item.enabled)),
                        "scheduling_priority": int(
                            row.get("scheduling_priority", item.scheduling_priority)
                            or 0
                        ),
                        "deep_collection_enabled": bool(
                            row.get(
                                "deep_collection_enabled",
                                item.deep_collection_enabled,
                            )
                        ),
                        "monitor_only": bool(
                            row.get("monitor_only", item.monitor_only)
                        ),
                        "remark": str(row.get("remark", item.remark) or ""),
                        "inventory_status": str(
                            row.get("inventory_status", item.inventory_status)
                            or "ACTIVE"
                        ),
                    }
                )
            )
        return sorted(
            result,
            key=lambda item: (
                not item.priority,
                -item.scheduling_priority,
                item.train_no,
                item.train_id,
            ),
        )

    def _base_train_candidates(self) -> list[GroundUnattendedTrainDTO]:
        if self.base_query is None:
            return []
        page = self.base_query.list_mrs(self.site_id, page=1, page_size=200)
        rows = list(page.items)
        current_page = 2
        while len(rows) < page.total:
            batch = self.base_query.list_mrs(
                self.site_id, page=current_page, page_size=200
            )
            if not batch.items:
                break
            rows.extend(batch.items)
            current_page += 1
        grouped: dict[str, list[Any]] = {}
        for row in rows:
            key = canonical_train_id_for(row.train_no or row.train_id)
            if key:
                grouped.setdefault(key, []).append(row)
        priorities = self.repository.list_priority_train_ids()
        result: list[GroundUnattendedTrainDTO] = []
        for key, mrs in grouped.items():
            first = mrs[0]
            train_id = first.train_id or f"base:{key}"
            endpoints = []
            for position in ("CT", "CW"):
                mr = next(
                    (item for item in mrs if item.mr_position_code == position), None
                )
                endpoints.append(
                    GroundUnattendedEndpointDTO(
                        endpoint=position,  # type: ignore[arg-type]
                        mr_id=mr.id if mr else "",
                        mr_name=mr.name if mr else "",
                        device_id=mr.device_id if mr else None,
                        management_ip=mr.management_ip if mr else "",
                        online_status="UNKNOWN",
                    )
                )
            result.append(
                GroundUnattendedTrainDTO(
                    train_id=train_id,
                    train_no=first.train_no,
                    train_name=train_id,
                    eligibility_status="AC_UNKNOWN",
                    exclusion_reason="尚未开始无人值守运行，等待 AC 在线状态",
                    coverage_status="NOT_SEEN",
                    priority=train_id in priorities,
                    endpoints=endpoints,
                )
            )
        return sorted(result, key=lambda item: (item.train_no, item.train_id))

    def _enrich_train_endpoints(
        self,
        trains: list[GroundUnattendedTrainDTO],
        run: dict[str, Any] | None,
    ) -> list[GroundUnattendedTrainDTO]:
        if not run:
            return trains
        run_id = str(run["run_id"])
        persisted = self.repository.list_ping_summaries(run_id)
        live = self.supervisor.fleet_ping.target_summaries()
        summaries: dict[tuple[str, str], dict[str, Any]] = {}
        for row in (*persisted, *live):
            train_id = str(row.get("train_id") or "")
            if row.get("mr_id"):
                summaries[(train_id, f"mr:{row['mr_id']}")] = row
            if row.get("mr_position_code"):
                summaries[(train_id, f"end:{row['mr_position_code']}")] = row
        live_keys = {
            (str(row.get("train_id") or ""), f"mr:{row.get('mr_id') or ''}")
            for row in live
            if row.get("mr_id")
        } | {
            (
                str(row.get("train_id") or ""),
                f"end:{row.get('mr_position_code') or ''}",
            )
            for row in live
            if row.get("mr_position_code")
        }
        operations: dict[tuple[str, str], dict[str, Any]] = {}
        for row in self.repository.list_deep_operations(run_id):
            operations[(str(row["train_id"]), str(row["mr_position_code"]))] = row
        result = []
        for train in trains:
            endpoints = []
            for endpoint in train.endpoints:
                mr_key = (train.train_id, f"mr:{endpoint.mr_id}")
                end_key = (train.train_id, f"end:{endpoint.endpoint}")
                summary = summaries.get(mr_key) or summaries.get(end_key) or {}
                operation = operations.get((train.train_id, endpoint.endpoint)) or {}
                boot = self.repository.latest_boot_session(endpoint.mr_id) if endpoint.mr_id else None
                wmesh = self.repository.latest_wmesh_event(endpoint.mr_id) if endpoint.mr_id else None
                endpoints.append(
                    endpoint.model_copy(
                        update={
                            "ping_active": mr_key in live_keys or end_key in live_keys,
                            "ping_sent_count": int(summary.get("sent_count") or 0),
                            "ping_success_count": int(
                                summary.get("success_count") or 0
                            ),
                            "ping_loss_rate_percent": summary.get("loss_rate_percent"),
                            "ping_avg_rtt_ms": summary.get("avg_rtt_ms"),
                            "active_operation_id": str(
                                operation.get("operation_id") or ""
                            )
                            if operation.get("state")
                            not in {"COMPLETED", "PARTIAL", "FAILED"}
                            else "",
                            "latest_session_id": str(operation.get("session_id") or ""),
                            "syslog_status": "ACTIVE"
                            if (boot or {}).get("last_syslog_received_at")
                            else "WAITING",
                            "last_syslog_received_at": str(
                                (boot or {}).get("last_syslog_received_at") or ""
                            ),
                            "current_active_peer": str(
                                (wmesh or {}).get("peer_name") or ""
                            ),
                            "last_link_switch_at": str(
                                (wmesh or {}).get("receive_time") or ""
                            )
                            if (wmesh or {}).get("event_type")
                            == "MESH_ACTIVELINK_SWITCH"
                            else "",
                            "boot_session_id": str(
                                (boot or {}).get("boot_session_id") or ""
                            ),
                            "estimated_boot_time": str(
                                (boot or {}).get("estimated_boot_time") or ""
                            ),
                            "uptime_seconds": (boot or {}).get(
                                "last_uptime_seconds"
                            ),
                            "config_status": str(
                                (boot or {}).get("config_status") or "NOT_CHECKED"
                            ),
                            "config_checked_at": str(
                                (boot or {}).get("config_checked_at") or ""
                            ),
                        }
                    )
                )
            result.append(train.model_copy(update={"endpoints": endpoints}))
        return result

    def _syslog_health(self) -> dict[str, Any]:
        receiver = getattr(self.supervisor, "syslog_receiver", None)
        if receiver is None:
            return {
                "udp_running": False,
                "udp_listen_address": "",
                "udp_receive_rate_per_second": 0.0,
                "udp_received_count": 0,
                "udp_unidentified_count": 0,
                "udp_queue_length": 0,
                "udp_queue_capacity": 0,
                "udp_dropped_count": 0,
                "raw_records_written": 0,
                "raw_bytes_written": 0,
                "raw_last_write_duration_ms": 0.0,
                "database_pending_count": 0,
                "database_last_batch_duration_ms": 0.0,
                "open_file_count": 0,
                "last_error": "",
            }
        return dict(receiver.health_snapshot())

    @staticmethod
    def _archive_dto(row: dict[str, Any]) -> GroundArchiveDTO:
        summary = row.get("summary") or {}
        return GroundArchiveDTO(
            archive_id=row["archive_id"],
            site_id=row["site_id"],
            run_id=row["run_id"],
            run_date=row["run_date"],
            actual_started_at=row.get("actual_started_at", ""),
            actual_ended_at=row.get("actual_ended_at", ""),
            mainline_train_count=int(summary.get("mainline_train_count") or 0),
            ping_target_count=int(summary.get("ping_target_count") or 0),
            ping_sample_count=int(summary.get("ping_sample_count") or 0),
            covered_train_count=int(summary.get("covered_train_count") or 0),
            complete_session_count=int(summary.get("complete_session_count") or 0),
            partial_session_count=int(summary.get("partial_session_count") or 0),
            archive_size_bytes=int(row.get("archive_size_bytes") or 0),
            archive_status=row.get("archive_status", ""),
            retention_until=row.get("retention_until", ""),
            summary=summary,
            message=row.get("message", ""),
            created_at=row.get("created_at", ""),
            updated_at=row.get("updated_at", ""),
        )

    def _active(self, site_id: str) -> dict[str, Any]:
        self._require_site(site_id)
        run = self.repository.get_active_run()
        if run is None:
            raise GroundUnattendedError(
                "RUN_NOT_ACTIVE", "当前没有运行中的无人值守任务", status_code=409
            )
        return run

    def _latest_run(self, site_id: str) -> dict[str, Any] | None:
        self._require_site(site_id)
        return self.repository.get_active_run() or self.repository.latest_run()

    def _require_site(self, site_id: str) -> None:
        if site_id != self.site_id:
            raise GroundUnattendedError(
                "SITE_MISMATCH", "请求局点必须与当前局点一致", status_code=409
            )


__all__ = ["GroundUnattendedApplicationService", "GroundUnattendedError"]
