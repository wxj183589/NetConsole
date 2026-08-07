from __future__ import annotations

import base64
import ipaddress
import json
import shutil
import uuid
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.models.api.ground_unattended import (
    GroundApIdentityDiagnosticsDTO,
    GroundActionResponseDTO,
    GroundArchiveDTO,
    GroundArchiveDetailDTO,
    GroundArchiveFileDTO,
    GroundArchivePageDTO,
    GroundArchiveValidationDTO,
    GroundDeepCollectionDTO,
    GroundDeepCollectorDTO,
    GroundDeepCollectionRecordDTO,
    GroundDeepCollectionRecordPageDTO,
    GroundDeepCollectionPageDTO,
    GroundPingSummaryPageDTO,
    GroundPingSampleDTO,
    GroundPingSamplePageDTO,
    GroundPingSeriesDTO,
    GroundPingTargetDTO,
    GroundRunDTO,
    GroundRunPageDTO,
    GroundRunDeleteRequestDTO,
    GroundAcPollerHealthDTO,
    GroundHealthDTO,
    GroundInventorySummaryDTO,
    GroundMrRuntimeStatusDTO,
    GroundMrRuntimeStatusPageDTO,
    GroundRawFileDTO,
    GroundRawFilePageDTO,
    GroundSyslogHostDTO,
    GroundSyslogRecordDTO,
    GroundSyslogRecordPageDTO,
    GroundSyslogDeleteAcceptedDTO,
    GroundSyslogDeletePreviewDTO,
    GroundSyslogDeletePreviewRequestDTO,
    GroundSyslogDeleteRequestDTO,
    GroundSyslogTransportStatusDTO,
    GroundTrainPolicyUpdateDTO,
    GroundTimelineEventDTO,
    GroundTimelinePageDTO,
    GroundOperationDTO,
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
from netconsole.services.ground_unattended.ap_resolver import (
    GroundApDisplayResolver,
)
from netconsole.services.ap_identity import ApIdentityQueryService
from netconsole.services.ground_unattended.inventory import TrainInventorySyncService
from netconsole.services.ground_unattended.identity import (
    GroundIdentityResolutionError,
)
from netconsole.services.ground_unattended.raw_query import (
    GroundRawQueryError,
    GroundRawStreamQueryService,
)
from netconsole.services.ground_unattended.raw_deletion import (
    GroundDeletionProcessPort,
    GroundRawDataDeletionApplicationService,
)
from netconsole.services.ground_unattended.raw_lifecycle import (
    GroundRawLifecycleError,
)
from netconsole.services.ground_unattended.schedule import schedule_window
from netconsole.services.ground_unattended.supervisor import GroundUnattendedSupervisor
from netconsole.services.ground_unattended.syslog_runtime import (
    WmeshRealtimeParser,
)
from netconsole.models.api.system_maintenance import DesktopActionDTO
from netconsole.models.api.system_network import SourceIpRecommendationRequestDTO
from netconsole.services.rail_transit.base_data_query_service import (
    RailTransitBaseDataQueryService,
)
from netconsole.services.rail_transit.train_identity import canonical_train_id_for
from netconsole.services.system_network_application_service import (
    SystemNetworkApplicationService,
    SystemNetworkError,
)
from netconsole.services.online_mr.errors import OnlineMrQueryError
from netconsole.services.online_mr.query_service import OnlineMrQueryService


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
        network_service: SystemNetworkApplicationService | None = None,
        process_adapter: GroundDeletionProcessPort | None = None,
        ap_identity_query_service: ApIdentityQueryService | None = None,
    ) -> None:
        self.paths = paths
        self.site_id = site_id
        self.repository = repository
        self.supervisor = supervisor
        self.base_query = base_query
        self.desktop_action_service = desktop_action_service
        self.network_service = network_service or SystemNetworkApplicationService()
        self.raw_query = GroundRawStreamQueryService(repository)
        self.raw_deletion = GroundRawDataDeletionApplicationService(
            repository,
            process_adapter=process_adapter,
            app_root=str(paths.app_root),
            data_root=str(paths.data_root),
        )
        shared_identity_query = getattr(
            supervisor,
            "ap_identity_query_service",
            None,
        )
        self.ap_identity_query_service = (
            ap_identity_query_service
            or shared_identity_query
            or ApIdentityQueryService(Database(paths.site_db_path(site_id)))
        )
        self._ap_display_cache = GroundApDisplayResolver(
            self.ap_identity_query_service
        )
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
        self._validate_network_profile(profile, require_syslog=profile.enabled)
        if (
            profile.syslog_server_ip
            and not self.network_service.is_local_ipv4(profile.syslog_server_ip)
            and profile.allow_external_syslog_address
            and not profile.external_syslog_address_confirmation
        ):
            raise GroundUnattendedError(
                "EXTERNAL_SYSLOG_CONFIRMATION_REQUIRED",
                "外部 NAT 日志回传地址需要再次确认",
                status_code=409,
            )
        previous = self.repository.get_profile()
        saved = self.repository.save_profile(
            GroundUnattendedProfileDTO.model_validate(profile.model_dump(mode="json"))
        )
        self.supervisor.profile_updated()
        self.repository.add_event(
            event_type="profile_updated",
            title="地面无人值守配置已保存",
            message="正在运行的任务在下一次调度周期读取新配置；当前采集任务不会被强制重启。",
        )
        if (
            saved.allow_external_syslog_address
            and saved.syslog_server_ip
            and not self.network_service.is_local_ipv4(saved.syslog_server_ip)
            and (
                not previous.allow_external_syslog_address
                or previous.syslog_server_ip != saved.syslog_server_ip
            )
        ):
            self.repository.add_event(
                event_type="external_syslog_address_override_enabled",
                severity="warning",
                title="已启用外部日志回传地址",
                message="用户已二次确认使用不属于本机的外部 NAT 地址。",
                details={"address_scope": "external_nat"},
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
        active_run = self.repository.get_active_run()
        latest_run = self.repository.latest_run()
        run = active_run or {}
        run_summary = run.get("summary")
        if not isinstance(run_summary, dict):
            run_summary = {}
        run_id = str(run.get("run_id") or "")
        trains = self.repository.list_train_runs(run_id) if run_id else []
        archives = self.repository.list_archives()
        inventory = self.repository.list_inventory(include_removed=False)
        syslog_health = self._syslog_health()
        radio_stats = self.repository.radio_runtime_statistics(
            run_id=run_id,
            day_start=now.replace(
                hour=0, minute=0, second=0, microsecond=0
            ).isoformat(timespec="seconds"),
        )
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
                if audit and audit.get("status") in {
                    "CONFIG_FAILED",
                    "CONFIG_VERIFY_FAILED",
                    "TARGET_PORT_CONFLICT",
                }:
                    config_abnormal += 1
        disk = shutil.disk_usage(self.paths.ground_unattended_root(site_id).parent)
        state = str(
            run.get("state") or ("WAITING_WINDOW" if profile.enabled else "DISABLED")
        ).strip().upper()
        if state not in {
            "DISABLED",
            "WAITING_WINDOW",
            "STARTING",
            "RUNNING",
            "PAUSED",
            "STOPPING",
            "FINALIZING",
            "ARCHIVING",
            "COMPLETED",
            "ERROR",
        }:
            state = "ERROR"
        if active_run is None:
            state = "WAITING_WINDOW" if profile.enabled else "DISABLED"
        active_operation = (
            self.repository.latest_operation(
                run_id=str(active_run["run_id"]), active_only=True
            )
            if active_run
            else None
        )
        latest_operation = self.repository.latest_terminal_operation()
        eligible_ping_endpoints = [
            (row, endpoint)
            for row in trains
            if row.get("ping_eligible")
            for endpoint in row.get("endpoints", [])
            if isinstance(endpoint, dict)
            and (
                bool(endpoint.get("ping_target_eligible"))
                or (
                    endpoint.get("online_status") == "ONLINE"
                    and bool(endpoint.get("management_ip"))
                )
            )
        ]
        return GroundUnattendedStatusDTO(
            site_id=site_id,
            enabled=profile.enabled,
            state=state,  # type: ignore[arg-type]
            service_state=state,  # type: ignore[arg-type]
            paused=bool(run.get("paused")),
            run_id=run_id,
            run_date=str(run.get("run_date") or ""),
            actual_started_at=str(run.get("actual_started_at") or ""),
            actual_ended_at=str(run.get("actual_ended_at") or ""),
            schedule_start_time=profile.schedule_start_time,
            schedule_end_time=profile.schedule_end_time,
            timezone=profile.timezone,
            running_mode=(
                "STANDARD"
                if profile.deep_collection_master_enabled
                else "LIGHTWEIGHT"
            ),
            next_start_at=window.next_start.isoformat(timespec="seconds"),
            next_end_at=window.next_end.isoformat(timespec="seconds"),
            ac_last_updated_at=str(run.get("ac_last_updated_at") or ""),
            ac_freshness_status=str(run.get("ac_freshness_status") or "NO_DATA"),
            mainline_train_count=sum(
                bool(row.get("mainline_eligible")) for row in trains
            ),
            mainline_ping_target_count=sum(
                bool(row.get("mainline_eligible"))
                for row, _endpoint in eligible_ping_endpoints
            ),
            depot_ping_target_count=sum(
                str(row.get("location_class") or "")
                in {"DEPOT", "PARKING_YARD", "STABLING"}
                for row, _endpoint in eligible_ping_endpoints
            ),
            ping_target_count=self.supervisor.fleet_ping.target_count
            or len(eligible_ping_endpoints),
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
            radio_down_mr_count=int(
                radio_stats.get("radio_down_mr_count") or 0
            ),
            radio_bounce_today_count=int(
                radio_stats.get("radio_bounce_today_count") or 0
            ),
            snmp_radio_control_today_count=int(
                radio_stats.get("snmp_radio_control_today_count") or 0
            ),
            snmp_unrecovered_count=int(
                radio_stats.get("snmp_unrecovered_count") or 0
            ),
            radio_flapping_mr_count=int(
                radio_stats.get("radio_flapping_mr_count") or 0
            ),
            last_snmp_radio_control_at=str(
                radio_stats.get("last_snmp_radio_control_at") or ""
            ),
            disk_used_bytes=int(run_summary.get("disk_used_bytes") or 0),
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
            active_run_id=str(active_run.get("run_id") or "")
            if active_run
            else "",
            active_run_state=str(active_run.get("state") or "")
            if active_run
            else "",
            active_run_date=str(active_run.get("run_date") or "")
            if active_run
            else "",
            active_run_started_at=str(active_run.get("actual_started_at") or "")
            if active_run
            else "",
            latest_run_id=str(latest_run.get("run_id") or "")
            if latest_run
            else "",
            latest_run_state=str(latest_run.get("state") or "")
            if latest_run
            else "",
            latest_run_date=str(latest_run.get("run_date") or "")
            if latest_run
            else "",
            latest_run_started_at=str(latest_run.get("actual_started_at") or "")
            if latest_run
            else "",
            latest_run_ended_at=str(latest_run.get("actual_ended_at") or "")
            if latest_run
            else "",
            active_operation_id=str(
                (active_operation or {}).get("operation_id") or ""
            ),
            active_operation_state=str(
                (active_operation or {}).get("operation_state") or ""
            ),
            latest_operation_id=str(
                (latest_operation or {}).get("operation_id") or ""
            ),
            latest_operation_state=str(
                (latest_operation or {}).get("operation_state") or ""
            ),
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
        self._validate_network_profile(profile, require_syslog=True)
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
        run_id = str(run["run_id"])
        existing = self.repository.latest_operation(
            run_id=run_id, active_only=True
        )
        if existing is not None:
            return GroundActionResponseDTO(
                state="STOPPING",
                run_id=run_id,
                operation_id=str(existing["operation_id"]),
                message=str(existing.get("message") or "停止请求正在处理"),
            )
        now = datetime.now().astimezone().isoformat(timespec="milliseconds")
        operation_id = f"groundop_{uuid.uuid4().hex}"
        self.repository.save_operation(
            {
                "operation_id": operation_id,
                "site_id": self.site_id,
                "run_id": run_id,
                "operation_type": "STOP_AND_ARCHIVE" if archive else "STOP",
                "operation_state": "PENDING",
                "operation_stage": "STOP_REQUESTED",
                "progress_percent": 0,
                "message": (
                    "停止并归档请求已提交"
                    if archive
                    else "正常停止请求已提交"
                ),
                "started_at": now,
                "updated_at": now,
            }
        )
        self.supervisor.request(
            "stop", archive=archive, operation_id=operation_id
        )
        return GroundActionResponseDTO(
            state="STOPPING",
            run_id=run_id,
            operation_id=operation_id,
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
        items = self._merge_base_candidate_endpoints(items)
        items = self._merge_inventory_policy(items)
        items = self._enrich_train_endpoints(items, run)
        return GroundUnattendedTrainPageDTO(items=items, total=len(items))

    def mr_runtime_status(
        self,
        site_id: str,
        *,
        mr_role: str = "",
        radio_state: str = "",
        snmp_state: str = "",
    ) -> GroundMrRuntimeStatusPageDTO:
        self._require_site(site_id)
        inventory = self.repository.list_inventory(include_removed=True)
        endpoint_by_id = {
            str(endpoint.get("device_uuid") or ""): endpoint
            for train in inventory
            for endpoint in train.get("endpoints", [])
        }
        items: list[GroundMrRuntimeStatusDTO] = []
        for row in self.repository.list_mr_runtime_states():
            if mr_role and str(row.get("mr_role") or "") != mr_role:
                continue
            if (
                radio_state
                and str(row.get("radio_overall_state") or "") != radio_state
            ):
                continue
            if (
                snmp_state
                and str(row.get("snmp_radio_control_state") or "")
                != snmp_state
            ):
                continue
            device_uuid = str(row.get("device_uuid") or "")
            endpoint = endpoint_by_id.get(device_uuid) or {}
            boot = self.repository.latest_boot_session(device_uuid) or {}
            audit = self.repository.latest_syslog_config_audit(device_uuid) or {}
            interfaces = [
                _radio_interface_projection(item)
                for item in self.repository.list_radio_interface_states(
                    device_uuid=device_uuid
                )
            ]
            items.append(
                GroundMrRuntimeStatusDTO(
                    device_uuid=device_uuid,
                    train_id=str(row.get("train_id") or ""),
                    mr_role=str(row.get("mr_role") or ""),
                    mr_name=str(endpoint.get("device_name") or ""),
                    radio_interfaces=interfaces,
                    radio_overall_state=str(
                        row.get("radio_overall_state") or "UNKNOWN"
                    ),  # type: ignore[arg-type]
                    snmp_radio_control_state=str(
                        row.get("snmp_radio_control_state") or "NONE"
                    ),  # type: ignore[arg-type]
                    last_radio_event_at=str(
                        row.get("last_radio_event_at") or ""
                    ),
                    last_cfg_event_at=str(row.get("last_cfg_event_at") or ""),
                    cfg_command_source=str(
                        row.get("last_command_source") or ""
                    ),
                    cfg_event_index=str(
                        row.get("last_cfg_event_index") or ""
                    ),
                    config_source=str(
                        row.get("last_config_source") or ""
                    ),
                    config_destination=str(
                        row.get("last_config_destination") or ""
                    ),
                    correlation_confidence=str(
                        row.get("last_correlation_confidence")
                        or "UNCONFIRMED"
                    ),  # type: ignore[arg-type]
                    managed_config_status=str(
                        boot.get("config_status") or "NOT_CHECKED"
                    ),
                    managed_config_checked_at=str(
                        boot.get("config_checked_at") or ""
                    ),
                    managed_profile_version=int(
                        audit.get("managed_profile_version") or 2
                    ),
                )
            )
        return GroundMrRuntimeStatusPageDTO(items=items, total=len(items))

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
        self,
        site_id: str,
        *,
        device_uuid: str = "",
        mode: str = "AUTO_REPAIR",
        allow_target_port_change: bool = False,
        explicit_confirmation: bool = False,
    ) -> GroundActionResponseDTO:
        run = self._active(site_id)
        profile = self.repository.get_profile()
        self._validate_network_profile(profile, require_syslog=True)
        if device_uuid and self.repository.get_inventory_endpoint(device_uuid) is None:
            raise GroundUnattendedError(
                "MR_NOT_FOUND", "MR 不在当前无人值守清单中", status_code=404
            )
        if allow_target_port_change and (
            not device_uuid or not explicit_confirmation
        ):
            raise GroundUnattendedError(
                "TARGET_PORT_CHANGE_CONFIRMATION_REQUIRED",
                "修改已有 MR 日志目标端口必须指定单台 MR 并明确确认",
                status_code=409,
            )
        if allow_target_port_change:
            self.repository.add_event(
                run_id=str(run["run_id"]),
                event_type="mr_loghost_port_change_authorized",
                severity="warning",
                mr_id=device_uuid,
                title="用户已确认高风险日志端口修改",
                message="已授权单台 MR 在检测到同 IP 端口冲突时修改 NetConsole 管理目标端口。",
                details={"risk_level": "high"},
            )
        self.supervisor.request_config_check(
            device_uuid,
            repair_enabled=(
                mode == "AUTO_REPAIR" and profile.syslog_auto_repair_enabled
            ),
            allow_target_port_change=allow_target_port_change,
        )
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
        run = self.repository.get_active_run()
        ac_pollers = self._ac_poller_health(
            site_id, str((run or {}).get("run_id") or "")
        )
        ac_unhealthy = any(
            item.status in {"DEGRADED", "STALE", "FAILED"}
            for item in ac_pollers
        )
        status = (
            "ERROR"
            if last_error or any(item.status == "FAILED" for item in ac_pollers)
            else "WARNING"
            if values.get("udp_dropped_count") or ac_unhealthy
            else "OK"
        )
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
            ac_pollers=ac_pollers,
            disk_free_bytes=disk.free,
            last_error=last_error,
            updated_at=datetime.now().astimezone().isoformat(timespec="milliseconds"),
        )

    def syslog_transport_status(
        self, site_id: str
    ) -> GroundSyslogTransportStatusDTO:
        self._require_site(site_id)
        profile = self.repository.get_profile()
        health = self._syslog_health()
        now = datetime.now().astimezone().isoformat(timespec="milliseconds")
        return_ip = str(profile.syslog_server_ip or "").strip()
        return_is_local = bool(
            return_ip and self.network_service.is_local_ipv4(return_ip)
        )
        if not return_ip:
            return_status = "EMPTY"
        else:
            try:
                parsed_return = ipaddress.ip_address(return_ip)
                valid_return = (
                    isinstance(parsed_return, ipaddress.IPv4Address)
                    and not parsed_return.is_unspecified
                    and not parsed_return.is_loopback
                    and not parsed_return.is_multicast
                    and str(parsed_return) != "255.255.255.255"
                )
            except ValueError:
                valid_return = False
            return_status = (
                "INVALID"
                if not valid_return
                else "LOCAL_ADDRESS"
                if return_is_local
                else "EXTERNAL_CONFIRMED"
                if profile.allow_external_syslog_address
                else "NOT_LOCAL"
            )

        listen_is_local = (
            profile.udp_listen_host == "0.0.0.0"
            or self.network_service.is_local_ipv4(profile.udp_listen_host)
        )
        receiver_running = bool(health.get("udp_running"))
        actual_listen = str(health.get("udp_listen_address") or "")
        receiver_state = (
            "ERROR"
            if str(health.get("last_error") or "")
            else "LISTENING"
            if receiver_running
            else "STARTING"
            if str((self.repository.get_active_run() or {}).get("state") or "")
            == "STARTING"
            else "STOPPED"
        )
        if not listen_is_local:
            port_state = "ADDRESS_NOT_LOCAL"
            port_message = "本机监听地址已不属于当前计算机"
        elif receiver_running and _listen_address_matches(
            actual_listen,
            profile.udp_listen_host,
            profile.udp_listen_port,
        ):
            port_state = "NETCONSOLE_LISTENING"
            port_message = "NetConsole 正在占用并监听该 UDP 端口"
        else:
            try:
                inspected = self.network_service.inspect_udp_port(
                    profile.udp_listen_host,
                    profile.udp_listen_port,
                )
                port_state = (
                    "AVAILABLE"
                    if inspected.available
                    else "OCCUPIED_BY_OTHER"
                )
                port_message = (
                    inspected.message
                    if inspected.available
                    else "UDP 端口已被其他进程占用"
                )
            except (SystemNetworkError, OSError, RuntimeError):
                port_state = "UNKNOWN"
                port_message = "UDP 端口状态检查失败，不影响运行概览加载"

        inventory = self.repository.list_inventory(include_removed=False)
        active_mr_count = 0
        target_ips: list[str] = []
        for train in inventory:
            for endpoint in train.get("endpoints", []):
                management_ip = str(endpoint.get("management_ip") or "").strip()
                if management_ip:
                    target_ips.append(management_ip)
                boot = self.repository.latest_boot_session(
                    str(endpoint.get("device_uuid") or "")
                )
                if boot and boot.get("last_syslog_received_at"):
                    active_mr_count += 1

        recommended_ip = ""
        recommended_adapter = ""
        try:
            recommendation = self.network_service.recommend_source_ip(
                SourceIpRecommendationRequestDTO(
                    target_ips=list(dict.fromkeys(target_ips)),
                    preferred_ip=return_ip,
                )
            )
            recommended_ip = recommendation.recommended_ip
            candidates = recommendation.candidates
            if not recommended_ip and candidates:
                recommended_ip = candidates[0].ipv4
            recommended_adapter = next(
                (
                    row.adapter_name
                    for row in candidates
                    if row.ipv4 == recommended_ip
                ),
                "",
            )
        except (SystemNetworkError, OSError, RuntimeError):
            pass

        ports_match: bool | None = (
            profile.syslog_server_port == profile.udp_listen_port
            if return_is_local
            else None
        )
        target_port_message = (
            "目标端口与本地监听一致"
            if ports_match is True
            else (
                f"目标端口 {profile.syslog_server_port} / "
                f"本地监听 {profile.udp_listen_port}，两者不一致"
            )
            if ports_match is False
            else "目标为外部/NAT 地址，本机监听端口状态不适用"
            if return_status in {"EXTERNAL_CONFIRMED", "NOT_LOCAL"}
            else "MR 日志回传地址尚未有效配置"
        )
        return GroundSyslogTransportStatusDTO(
            configured_return_ip=return_ip,
            configured_return_port=profile.syslog_server_port,
            return_address_status=return_status,  # type: ignore[arg-type]
            return_address_is_local=return_is_local,
            allow_external_address=profile.allow_external_syslog_address,
            listen_host=profile.udp_listen_host,
            listen_port=profile.udp_listen_port,
            receiver_running=receiver_running,
            receiver_state=receiver_state,  # type: ignore[arg-type]
            actual_listen_address=actual_listen,
            port_state=port_state,  # type: ignore[arg-type]
            port_message=port_message,
            ports_match=ports_match,
            target_port_message=target_port_message,
            last_received_at=str(health.get("udp_last_received_at") or ""),
            received_count=int(health.get("udp_received_count") or 0),
            active_mr_count=active_mr_count,
            unidentified_count=int(health.get("udp_unidentified_count") or 0),
            identity_conflict_count=int(
                health.get("udp_identity_conflict_count") or 0
            ),
            queue_length=int(health.get("udp_queue_length") or 0),
            queue_capacity=int(health.get("udp_queue_capacity") or 0),
            dropped_count=int(health.get("udp_dropped_count") or 0),
            recommended_local_ip=recommended_ip,
            recommended_adapter_name=recommended_adapter,
            checked_at=now,
        )

    def _ac_poller_health(
        self, site_id: str, run_id: str
    ) -> list[GroundAcPollerHealthDTO]:
        service = getattr(self.supervisor, "ac_resident_service", None)
        if service is None or not run_id:
            return []
        now = datetime.now().astimezone()
        profile = self.repository.get_profile()
        result: list[GroundAcPollerHealthDTO] = []
        for row in service.list_statuses(
            site_name=site_id, run_id=run_id
        ):
            heartbeat_age = self._age_seconds(row.get("heartbeat_at"), now)
            success_age = self._age_seconds(row.get("last_success_at"), now)
            connection_state = str(
                row.get("connection_state") or "UNKNOWN"
            ).upper()
            if connection_state == "FAILED":
                status = "FAILED"
            elif (
                success_age is not None
                and success_age > profile.ac_stale_grace_seconds
            ):
                status = "STALE"
            elif connection_state in {"RECONNECTING", "BACKOFF", "CONNECTING"}:
                status = "DEGRADED"
            elif heartbeat_age is None or heartbeat_age > max(
                5.0,
                float(row.get("poll_interval_seconds") or 0) + 2.0,
            ):
                status = "STALE"
            elif connection_state in {"CONNECTED", "POLLING", "WAITING"}:
                status = "HEALTHY"
            else:
                status = "DEGRADED"
            result.append(
                GroundAcPollerHealthDTO(
                    controller_id=str(row.get("controller_id") or ""),
                    controller_name=str(row.get("controller_name") or ""),
                    task_id=str(row.get("task_id") or ""),
                    run_id=str(row.get("run_id") or ""),
                    status=status,
                    connection_state=connection_state,
                    last_success_at=str(row.get("last_success_at") or ""),
                    latest_snapshot_id=self._optional_int(
                        row.get("latest_snapshot_id")
                    ),
                    next_poll_at=str(row.get("next_poll_at") or ""),
                    poll_interval_seconds=float(
                        row.get("poll_interval_seconds") or 0
                    ),
                    poll_count=int(row.get("poll_count") or 0),
                    success_count=int(row.get("success_count") or 0),
                    failure_count=int(row.get("failure_count") or 0),
                    reconnect_count=int(row.get("reconnect_count") or 0),
                    consecutive_failures=int(
                        row.get("consecutive_failures") or 0
                    ),
                    heartbeat_at=str(row.get("heartbeat_at") or ""),
                    heartbeat_age_seconds=heartbeat_age,
                    last_error=str(row.get("last_error_message") or ""),
                )
            )
        return result

    @staticmethod
    def _age_seconds(value: object, now: datetime) -> float | None:
        try:
            parsed = datetime.fromisoformat(
                str(value or "").replace("Z", "+00:00")
            )
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=now.tzinfo)
            return max(0.0, (now - parsed).total_seconds())
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _optional_int(value: object) -> int | None:
        try:
            return int(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

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

    def runs(
        self,
        site_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> GroundRunPageDTO:
        self._require_site(site_id)
        rows = self.repository.list_runs(limit=limit, offset=offset)
        return GroundRunPageDTO(
            items=[self._run_dto(row) for row in rows],
            total=self.repository.count_runs(),
            limit=max(1, min(int(limit), 500)),
            offset=max(0, int(offset)),
        )

    def delete_run_history(
        self,
        site_id: str,
        run_id: str,
        payload: GroundRunDeleteRequestDTO,
    ) -> GroundActionResponseDTO:
        self._require_site(site_id)
        if not payload.explicit_confirmation:
            raise GroundUnattendedError(
                "CONFIRMATION_REQUIRED", "删除运行历史需要明确确认", status_code=409
            )
        run = self.repository.get_run(run_id)
        if run is None:
            raise GroundUnattendedError(
                "RUN_NOT_FOUND", "指定的无人值守运行不存在", status_code=404
            )
        active = self.repository.get_active_run()
        if active and str(active.get("run_id") or "") == run_id:
            raise GroundUnattendedError(
                "RUN_IN_USE", "不能删除正在使用的无人值守运行", status_code=409
            )
        deleted = self.repository.delete_run_history(run_id)
        self.repository.add_event(
            event_type="run_history_deleted",
            title="运行历史已删除",
            message=f"{run.get('run_date') or run_id} 的运行历史已从索引移除",
            details={
                "run_id": run_id,
                "run_date": str(run.get("run_date") or ""),
                "deleted": deleted,
                "archive_preserved": bool(run.get("archive_id")),
            },
        )
        return GroundActionResponseDTO(
            state="WAITING_WINDOW",
            run_id=run_id,
            message="运行历史已删除",
        )

    def ping_summary(
        self, site_id: str, *, run_id: str = ""
    ) -> GroundPingSummaryPageDTO:
        self._require_site(site_id)
        run = self._resolve_run(run_id)
        active = self.repository.get_active_run()
        use_live = bool(
            run
            and active
            and str(run["run_id"]) == str(active["run_id"])
        )
        rows = (
            self.supervisor.fleet_ping.target_summaries()
            if use_live
            else []
        )
        if not rows and run:
            rows = self.repository.list_ping_summaries(str(run["run_id"]))
        availability, source = self._run_data_availability(run)
        raw_files = (
            [
                item
                for item in self.repository.list_raw_files_for_run(
                    str(run["run_id"])
                )
                if str(item.get("data_type") or "") == "ping"
            ]
            if run
            else []
        )
        raw_root = self.repository.db_path.parent.resolve()
        archive = (
            self.repository.get_archive_by_run(str(run["run_id"]))
            if run
            else None
        )
        archive_ready = (
            str((archive or {}).get("archive_status") or "") == "READY"
        )
        endpoint_names = {
            str(endpoint.get("device_uuid") or ""): str(
                endpoint.get("device_name") or ""
            )
            for train in self.repository.list_inventory(include_removed=True)
            for endpoint in train.get("endpoints", [])
        }
        train_states = {
            str(item.get("train_id") or ""): item
            for item in (
                self.repository.list_train_runs(str(run["run_id"]))
                if run
                else []
            )
        }
        for row in rows:
            train_state = train_states.get(str(row.get("train_id") or ""), {})
            identity_error = ""
            try:
                identity = self.raw_query.identity_resolver.resolve_ping(
                    run_id=str((run or {}).get("run_id") or ""),
                    train_id=str(row.get("train_id") or ""),
                    mr_id=str(row.get("mr_id") or ""),
                    target_ip=str(row.get("target_ip") or ""),
                )
                matching_files = [
                    item
                    for item in raw_files
                    if (
                        not identity.registered_train_ids
                        or str(item.get("train_id") or "")
                        in identity.registered_train_ids
                    )
                    and (
                        not identity.mr_roles
                        or str(item.get("mr_role") or "").upper()
                        in identity.mr_roles
                    )
                ]
            except GroundIdentityResolutionError as exc:
                identity = None
                identity_error = exc.code
                matching_files = []
            active_raw_count = sum(
                self._registered_raw_file_exists(raw_root, item)
                for item in matching_files
            )
            archived_raw_count = sum(
                archive_ready
                and str(item.get("archive_status") or "") == "ARCHIVED"
                for item in matching_files
            )
            target_source = (
                "MIXED"
                if active_raw_count and archived_raw_count
                else "ACTIVE"
                if active_raw_count
                else "ARCHIVE"
                if archived_raw_count
                else source
            )
            target_availability = (
                "MIXED"
                if target_source == "MIXED"
                else "ACTIVE_RAW"
                if target_source == "ACTIVE"
                else "ARCHIVED_RAW"
                if target_source == "ARCHIVE"
                else availability
            )
            row.setdefault("run_id", str((run or {}).get("run_id") or ""))
            row.setdefault("run_date", str((run or {}).get("run_date") or ""))
            row.setdefault(
                "location_class",
                str(train_state.get("location_class") or "UNKNOWN"),
            )
            row.setdefault(
                "ping_inclusion_reason",
                str(train_state.get("ping_inclusion_reason") or ""),
            )
            row.setdefault(
                "mainline_eligible",
                bool(train_state.get("mainline_eligible")),
            )
            row.setdefault(
                "deep_collection_eligible",
                bool(train_state.get("deep_collection_eligible")),
            )
            row.setdefault("data_availability", target_availability)
            row.setdefault("data_source", target_source)
            row.setdefault("active_raw_file_count", active_raw_count)
            row.setdefault("archived_raw_file_count", archived_raw_count)
            row.setdefault("raw_file_available", bool(active_raw_count))
            row.setdefault("archive_available", bool(archived_raw_count))
            row.setdefault("raw_file_count", len(matching_files))
            row.setdefault(
                "raw_record_count",
                sum(
                    max(0, int(item.get("record_count") or 0))
                    for item in matching_files
                ),
            )
            row.setdefault(
                "raw_file_ids",
                [
                    str(item.get("file_id") or "")
                    for item in matching_files
                    if str(item.get("file_id") or "")
                ],
            )
            row.setdefault("archive_id", str((archive or {}).get("archive_id") or ""))
            row.setdefault("source_kind", target_source)
            row.setdefault(
                "availability_reason",
                identity_error
                or (
                    ""
                    if target_availability
                    in {"ACTIVE_RAW", "ARCHIVED_RAW", "MIXED"}
                    else "RAW_FILE_MISSING"
                    if matching_files
                    else "SUMMARY_ONLY"
                ),
            )
            row.setdefault(
                "query_identity",
                identity.query_identity if identity is not None else "",
            )
            starts = [
                str(item.get("start_time") or "")
                for item in matching_files
                if item.get("start_time")
            ]
            ends = [
                str(item.get("end_time") or "")
                for item in matching_files
                if item.get("end_time")
            ]
            row.setdefault("first_sample_at", min(starts) if starts else "")
            row.setdefault("last_sample_at", max(ends) if ends else "")
            row.setdefault(
                "effective_sample_count", int(row.get("sent_count") or 0)
            )
            row.setdefault(
                "raw_sample_count",
                int(row.get("sent_count") or 0)
                + int(row.get("warmup_ignored_count") or 0),
            )
            if (
                int(row.get("raw_sample_count") or 0) == 0
                and int(row.get("sent_count") or 0) > 0
            ):
                row["raw_sample_count"] = int(row["sent_count"]) + int(
                    row.get("warmup_ignored_count") or 0
                )
            row.setdefault(
                "mr_name", endpoint_names.get(str(row.get("mr_id") or ""), "")
            )
        dto_fields = GroundPingTargetDTO.model_fields
        items = [
            GroundPingTargetDTO.model_validate(
                {key: value for key, value in row.items() if key in dto_fields}
            )
            for row in rows
        ]
        return GroundPingSummaryPageDTO(items=items, total=len(items))

    def ping_series(
        self,
        site_id: str,
        **filters: Any,
    ) -> GroundPingSeriesDTO:
        self._require_site(site_id)
        try:
            result = self.raw_query.ping_series(**filters)
            result["points"] = self._project_ping_samples(
                list(result.get("points") or [])
            )
            return GroundPingSeriesDTO.model_validate(result)
        except GroundRawQueryError as exc:
            raise GroundUnattendedError(
                exc.code,
                str(exc),
                status_code=(
                    409
                    if exc.code == "PING_TARGET_IDENTITY_CONFLICT"
                    else 422
                ),
            ) from exc

    def ping_series_incremental(
        self,
        site_id: str,
        **filters: Any,
    ) -> GroundPingSeriesDTO:
        self._require_site(site_id)
        try:
            result = self.raw_query.ping_series_incremental(**filters)
            result["points"] = self._project_ping_samples(
                list(result.get("points") or [])
            )
            return GroundPingSeriesDTO.model_validate(result)
        except GroundRawQueryError as exc:
            raise GroundUnattendedError(
                exc.code,
                str(exc),
                status_code=(
                    409
                    if exc.code == "PING_TARGET_IDENTITY_CONFLICT"
                    else 422
                ),
            ) from exc

    def ping_samples(
        self,
        site_id: str,
        **filters: Any,
    ) -> GroundPingSamplePageDTO:
        self._require_site(site_id)
        try:
            result = self.raw_query.ping_samples(**filters)
            result["items"] = self._project_ping_samples(
                list(result.get("items") or [])
            )
            return GroundPingSamplePageDTO.model_validate(result)
        except GroundRawQueryError as exc:
            raise GroundUnattendedError(
                exc.code,
                str(exc),
                status_code=(
                    409
                    if exc.code == "PING_TARGET_IDENTITY_CONFLICT"
                    else 422
                ),
            ) from exc

    @staticmethod
    def _project_ping_samples(
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        fields = GroundPingSampleDTO.model_fields
        return [
            GroundPingSampleDTO.model_validate(
                {key: value for key, value in row.items() if key in fields}
            ).model_dump(mode="json")
            for row in rows
        ]

    def syslog_records(
        self,
        site_id: str,
        **filters: Any,
    ) -> GroundSyslogRecordPageDTO:
        self._require_site(site_id)
        try:
            result = self.raw_query.syslog_records(**filters)
            resolver = self._ap_display_resolver()
            parser = WmeshRealtimeParser()
            parsed_items: list[tuple[dict[str, Any], dict[str, Any], bool]] = []
            for item in result.get("items", []):
                parsed = None
                display_enriched = bool(item.get("display_enriched"))
                if not item.get("event_type") and item.get("raw_text"):
                    receive_time = self._parse_datetime(item.get("receive_time"))
                    if receive_time is not None:
                        parsed = parser.parse(
                            str(item["raw_text"]), receive_time=receive_time
                        )
                        display_enriched = parsed is not None
                if parsed is None and item.get("event_type"):
                    parsed = {
                        "event_type": item.get("event_type"),
                        "peer_name": item.get("peer_name"),
                        "peer_mac": item.get("peer_mac"),
                        "previous_peer_name": item.get("previous_peer_name"),
                        "previous_peer_mac": item.get("previous_peer_mac"),
                        "details": item.get("parsed_details") or {},
                    }
                if parsed is None:
                    continue
                parsed_items.append((item, parsed, display_enriched))
            resolver.preload_parsed(parsed for _, parsed, _ in parsed_items)
            for item, parsed, display_enriched in parsed_items:
                enriched = resolver.enrich_parsed(parsed)
                details = dict(enriched.get("details") or {})
                item.update(
                    {
                        "display_enriched": display_enriched,
                        "event_type": str(enriched.get("event_type") or ""),
                        "peer_ap_id": str(details.get("peer_ap_id") or ""),
                        "peer_name": str(enriched.get("peer_name") or ""),
                        "peer_mac": str(enriched.get("peer_mac") or ""),
                        "previous_peer_ap_id": str(
                            details.get("previous_peer_ap_id") or ""
                        ),
                        "previous_peer_name": str(
                            enriched.get("previous_peer_name") or ""
                        ),
                        "previous_peer_mac": str(
                            enriched.get("previous_peer_mac") or ""
                        ),
                        "peer_radio_mac": str(
                            details.get("peer_radio_mac") or ""
                        ),
                        "previous_peer_radio_mac": str(
                            details.get("previous_peer_radio_mac") or ""
                        ),
                        "station": str(enriched.get("station") or ""),
                        "section": str(enriched.get("section") or ""),
                        "previous_station": str(
                            details.get("previous_station") or ""
                        ),
                        "previous_section": str(
                            details.get("previous_section") or ""
                        ),
                        "rssi": details.get("rssi", details.get("new_rssi")),
                        "previous_rssi": details.get("old_rssi"),
                        "reason_code": str(
                            details.get("reason_code")
                            or details.get("switch_reason_code")
                            or ""
                        ),
                        "reason_text": str(details.get("reason_raw") or ""),
                        "resolution_status": str(
                            details.get("resolution_status") or ""
                        ),
                        "parsed_details": details,
                    }
                )
            raw_file_ids = {
                str(item.get("raw_file_id") or "")
                for item in result.get("items", [])
                if item.get("raw_file_id")
            }
            structured_events = (
                self.repository.structured_syslog_events_by_raw_files(
                    raw_file_ids
                )
            )
            structured_by_position = {
                (
                    str(event.get("raw_file_id") or ""),
                    int(event.get("raw_line_number") or 0),
                ): event
                for event in structured_events
            }
            event_by_id = {
                int(event["id"]): event
                for event in structured_events
                if event.get("id") is not None
            }
            correlations = self.repository.list_radio_correlations(
                event_ids=event_by_id
            )
            correlations_by_event: dict[int, list[dict[str, Any]]] = {}
            correlations_by_cfg: dict[int, list[dict[str, Any]]] = {}
            for correlation in correlations:
                cfg_event_id = int(correlation["cfg_event_id"])
                ifnet_event_id = int(correlation["ifnet_event_id"])
                correlations_by_event.setdefault(cfg_event_id, []).append(
                    correlation
                )
                correlations_by_event.setdefault(ifnet_event_id, []).append(
                    correlation
                )
                correlations_by_cfg.setdefault(cfg_event_id, []).append(
                    correlation
                )
            composite_by_cfg = {
                cfg_event_id: _radio_composite_event_type(
                    grouped, event_by_id, self._parse_datetime
                )
                for cfg_event_id, grouped in correlations_by_cfg.items()
            }
            for item in result.get("items", []):
                structured = structured_by_position.get(
                    (
                        str(item.get("raw_file_id") or ""),
                        int(item.get("raw_line_number") or 0),
                    )
                )
                if structured is None:
                    continue
                structured_id = int(structured["id"])
                details = dict(item.get("parsed_details") or {})
                details.update(structured.get("details") or {})
                item.update(
                    {
                        "event_type": str(
                            structured.get("event_type")
                            or item.get("event_type")
                            or ""
                        ),
                        "event_family": str(
                            structured.get("event_family")
                            or item.get("event_family")
                            or ""
                        ),
                        "interface_name": str(
                            structured.get("interface_name") or ""
                        ),
                        "interface_type": str(
                            structured.get("interface_type") or ""
                        ),
                        "physical_state": str(
                            structured.get("physical_state") or ""
                        ),
                        "cfg_event_index": str(
                            structured.get("cfg_event_index") or ""
                        ),
                        "cfg_command_source": str(
                            structured.get("cfg_command_source") or ""
                        ),
                        "cfg_source": str(
                            structured.get("cfg_source") or ""
                        ),
                        "cfg_destination": str(
                            structured.get("cfg_destination") or ""
                        ),
                        "expected_internal_change": bool(
                            structured.get("expected_internal_change")
                        ),
                        "parsed_details": details,
                    }
                )
                related = correlations_by_event.get(structured_id, [])
                if not related:
                    continue
                confidence = (
                    "HIGH"
                    if any(
                        str(row.get("confidence") or "") == "HIGH"
                        for row in related
                    )
                    else "MEDIUM"
                )
                related_cfg_ids = {
                    int(row["cfg_event_id"]) for row in related
                }
                expanded = [
                    row
                    for cfg_event_id in related_cfg_ids
                    for row in correlations_by_cfg.get(cfg_event_id, [])
                ]
                correlated_event_ids = {
                    int(row["cfg_event_id"]) for row in expanded
                } | {
                    int(row["ifnet_event_id"]) for row in expanded
                }
                composite_types = {
                    composite_by_cfg.get(cfg_event_id, "")
                    for cfg_event_id in related_cfg_ids
                }
                item.update(
                    {
                        "correlation_status": "CORRELATED",
                        "correlation_confidence": confidence,
                        "correlation_delta_ms": min(
                            int(row.get("delta_ms") or 0)
                            for row in related
                        ),
                        "correlated_event_ids": sorted(
                            correlated_event_ids
                        ),
                        "composite_event_type": _preferred_composite_type(
                            composite_types
                        ),
                    }
                )
            dto_fields = GroundSyslogRecordDTO.model_fields
            result["items"] = [
                GroundSyslogRecordDTO.model_validate(
                    {key: value for key, value in item.items() if key in dto_fields}
                )
                for item in result.get("items", [])
            ]
            return GroundSyslogRecordPageDTO.model_validate(result)
        except GroundRawQueryError as exc:
            raise GroundUnattendedError(
                exc.code, str(exc), status_code=422
            ) from exc

    def preview_syslog_delete(
        self,
        site_id: str,
        request: GroundSyslogDeletePreviewRequestDTO,
    ) -> GroundSyslogDeletePreviewDTO:
        self._require_site(site_id)
        try:
            return self.raw_deletion.preview(request)
        except GroundRawLifecycleError as exc:
            raise GroundUnattendedError(
                exc.code,
                str(exc),
                status_code=409,
            ) from exc

    def submit_syslog_delete(
        self,
        site_id: str,
        request: GroundSyslogDeleteRequestDTO,
    ) -> GroundSyslogDeleteAcceptedDTO:
        self._require_site(site_id)
        try:
            return self.raw_deletion.submit(request)
        except GroundRawLifecycleError as exc:
            raise GroundUnattendedError(
                exc.code,
                str(exc),
                status_code=(
                    410
                    if exc.code == "DELETE_PREVIEW_EXPIRED"
                    else 503
                    if exc.code == "JOB_CENTER_UNAVAILABLE"
                    else 409
                ),
            ) from exc

    def deep_collections(
        self, site_id: str, *, run_id: str = ""
    ) -> GroundDeepCollectionPageDTO:
        run = self._resolve_run(run_id)
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
        query = self._deep_query_service()
        session_cache: dict[str, tuple[object | None, list[object], str]] = {}
        items = []
        for row in rows:
            train_id = str(row["train_id"])
            scheduling_priority, current_reason = scheduling.get(train_id, (0, ""))
            operations = row.get("operations") or {}
            sessions = row.get("sessions") or {}
            latest = latest_operations.get(train_id, {})
            endpoint_by_role = {
                str(endpoint.get("endpoint") or ""): endpoint
                for endpoint in row.get("endpoints", [])
            }
            collectors = [
                self._project_deep_collector(
                    run_id=str(run["run_id"]) if run else "",
                    train=row,
                    operation=operation,
                    endpoint=endpoint_by_role.get(role, {}),
                    query=query,
                    session_cache=session_cache,
                )
                for role, operation in latest.items()
            ]
            if not collectors:
                collectors = [
                    self._project_deep_collector(
                        run_id=str(run["run_id"]) if run else "",
                        train=row,
                        operation=None,
                        endpoint=endpoint,
                        query=query,
                        session_cache=session_cache,
                    )
                    for endpoint in endpoint_by_role.values()
                ]
            deep_state, deep_reason = self._collection_deep_state(
                row,
                collectors,
                queue_position=queue_positions.get(train_id),
            )
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
                    deep_state=deep_state,
                    deep_state_reason=deep_reason,
                    collectors=collectors,
                )
            )
        return GroundDeepCollectionPageDTO(items=items, total=len(items))

    def deep_collection_records(
        self,
        site_id: str,
        *,
        run_id: str = "",
        train_id: str = "",
        mr_id: str = "",
        mr_role: str = "",
        category: str = "ALL",
        keyword: str = "",
        cursor: str = "",
        limit: int = 200,
    ) -> GroundDeepCollectionRecordPageDTO:
        """Read a bounded increment of the existing Online MR raw logs."""

        self._require_site(site_id)
        collections = self.deep_collections(site_id, run_id=run_id).items
        selected = next(
            (
                collector
                for collection in collections
                if not train_id or collection.train_id == train_id
                for collector in collection.collectors
                if (not mr_id or collector.mr_id == mr_id)
                and (not mr_role or collector.mr_role.upper() == mr_role.upper())
            ),
            None,
        )
        if selected is None:
            raise GroundUnattendedError(
                "DEEP_COLLECTOR_NOT_FOUND", "未找到匹配的深度采集 MR", status_code=404
            )
        if not selected.collector_session_id:
            return GroundDeepCollectionRecordPageDTO(collector=selected)
        query = self._deep_query_service()
        if query is None:
            return GroundDeepCollectionRecordPageDTO(
                collector=selected.model_copy(
                    update={"state_reason": "Online MR 查询服务当前不可用"}
                )
            )
        category_key = str(category or "ALL").upper()
        sources = _DEEP_RECORD_SOURCES.get(category_key)
        if sources is None:
            raise GroundUnattendedError(
                "DEEP_RECORD_CATEGORY_INVALID", "不支持的深采记录分类", status_code=422
            )
        cursor_state = _decode_deep_cursor(cursor)
        if cursor_state.get("session_id") not in {None, "", selected.collector_session_id}:
            raise GroundUnattendedError(
                "DEEP_RECORD_CURSOR_INVALID", "深采记录游标与当前会话不匹配", status_code=409
            )
        offsets = {
            str(key): max(0, int(value))
            for key, value in dict(cursor_state.get("offsets") or {}).items()
        }
        per_source = max(1, min(500, int(limit)) // max(1, len(sources)))
        rows: list[GroundDeepCollectionRecordDTO] = []
        has_more = False
        needle = keyword.strip().casefold()
        for source in sources:
            try:
                chunk = query.read_log_chunk(
                    self.site_id,
                    selected.collector_session_id,
                    source,
                    cursor=offsets.get(source, 0),
                    limit=per_source,
                )
            except OnlineMrQueryError:
                continue
            offsets[source] = chunk.next_cursor
            has_more = has_more or chunk.has_more
            for line in chunk.lines:
                if needle and needle not in line.text.casefold():
                    continue
                rows.append(
                    GroundDeepCollectionRecordDTO(
                        sequence=line.sequence,
                        timestamp=line.timestamp or "",
                        category=_deep_record_category(source),
                        source=source,
                        text=line.text,
                    )
                )
        rows.sort(key=lambda item: (item.timestamp or "9999", item.source, item.sequence))
        return GroundDeepCollectionRecordPageDTO(
            collector=selected,
            records=rows[: max(1, min(500, int(limit)))],
            next_cursor=_encode_deep_cursor(
                {"session_id": selected.collector_session_id, "offsets": offsets}
            ),
            has_more=has_more,
        )

    def _deep_query_service(self) -> OnlineMrQueryService | None:
        scheduler = getattr(self.supervisor, "deep_scheduler", None)
        query = getattr(scheduler, "query_service", None)
        return (
            query
            if query is not None
            and all(
                callable(getattr(query, name, None))
                for name in ("get_session", "list_collectors", "read_log_chunk")
            )
            else None
        )

    def _project_deep_collector(
        self,
        *,
        run_id: str,
        train: Mapping[str, Any],
        operation: Mapping[str, Any] | None,
        endpoint: Mapping[str, Any],
        query: OnlineMrQueryService | None,
        session_cache: dict[str, tuple[object | None, list[object], str]],
    ) -> GroundDeepCollectorDTO:
        operation = operation or {}
        session_id = str(operation.get("session_id") or "")
        state, reason = _deep_operation_state(operation, train)
        bytes_written = 0
        last_record_at = ""
        session_error = ""
        if session_id and query is not None:
            cached = session_cache.get(session_id)
            if cached is None:
                try:
                    detail = query.get_session(self.site_id, session_id)
                    status_rows = query.list_collectors(self.site_id, session_id)
                    cached = (detail, status_rows, "")
                except OnlineMrQueryError as exc:
                    cached = (None, [], str(exc))
                session_cache[session_id] = cached
            detail, status_rows, session_error = cached
            for status in status_rows:
                bytes_written += int(getattr(status, "size_bytes", 0) or 0)
                updated_at = str(getattr(status, "updated_at", "") or "")
                if updated_at > last_record_at:
                    last_record_at = updated_at
            # Online MR may report an operation as RUNNING immediately after the
            # session is created.  The ground-unattended view must not present
            # that as a deep collector that is already producing evidence.
            if state == "RUNNING" and bytes_written <= 0:
                state, reason = "STARTING", "Online MR 会话已建立，等待 Collector 写入原始数据"
            elif bytes_written > 0 and state == "STARTING":
                state, reason = "RUNNING", "Collector 已写入原始数据"
            elif session_error and state in {"STARTING", "RUNNING"}:
                reason = f"{reason}；会话状态暂不可读"
            elif detail is not None:
                session_status = str(getattr(detail, "status", "") or "").upper()
                if session_status in {"FAILED", "ERROR"}:
                    state, reason = "FAILED", str(
                        getattr(detail, "error_message", "") or "Online MR 会话失败"
                    )
        return GroundDeepCollectorDTO(
            run_id=run_id,
            train_id=str(train.get("train_id") or ""),
            mr_id=str(operation.get("mr_id") or endpoint.get("mr_id") or ""),
            mr_role=str(operation.get("mr_position_code") or endpoint.get("endpoint") or ""),
            management_ip=str(endpoint.get("management_ip") or ""),
            operation_id=str(operation.get("operation_id") or ""),
            collector_session_id=session_id,
            state=state,
            state_reason=reason,
            started_at=str(operation.get("started_at") or ""),
            last_record_at=last_record_at,
            record_count=None,
            bytes_written=bytes_written,
            current_ap=str(train.get("current_ap_name") or ""),
            station=str(train.get("station") or ""),
            section=str(train.get("section") or ""),
            last_error=str(operation.get("error_summary") or session_error or ""),
            retry_count=max(0, int(train.get("attempt_count") or 0) - 1),
        )

    @staticmethod
    def _collection_deep_state(
        train: Mapping[str, Any],
        collectors: list[GroundDeepCollectorDTO],
        *,
        queue_position: int | None,
    ) -> tuple[str, str]:
        active_collectors = [item for item in collectors if item.operation_id]
        if active_collectors:
            priority = {
                "FAILED": 8,
                "RUNNING": 7,
                "STARTING": 6,
                "STOPPING": 5,
                "PAUSED": 4,
                "QUEUED": 3,
                "STOPPED": 2,
                "ELIGIBLE": 1,
                "INELIGIBLE": 0,
            }
            current = max(active_collectors, key=lambda item: priority[item.state])
            return current.state, current.state_reason
        if not train.get("deep_collection_eligible"):
            return "INELIGIBLE", str(train.get("deep_exclusion_reason") or "不具备深度采集资格")
        if queue_position is not None:
            return "QUEUED", "已进入深度采集调度队列"
        return "ELIGIBLE", "符合深度采集资格，等待调度"

    def timeline(
        self,
        site_id: str,
        *,
        train_id: str = "",
        event_type: str = "",
        query: str = "",
        run_id: str = "",
        page: int = 1,
        page_size: int = 100,
    ) -> GroundTimelinePageDTO:
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 500))
        offset = (page - 1) * page_size
        run = self._resolve_run(run_id)
        rows = (
            self.repository.list_events(
                str(run["run_id"]),
                train_id=train_id,
                event_type=event_type,
                query=query,
                limit=page_size,
                offset=offset,
            )
            if run
            else []
        )
        inventory = self.repository.list_inventory(include_removed=True)
        train_by_id = {str(row.get("train_id") or ""): row for row in inventory}
        endpoint_by_id = {
            str(endpoint.get("device_uuid") or ""): endpoint
            for train in inventory
            for endpoint in train.get("endpoints", [])
        }
        items = []
        resolver = self._ap_display_resolver()
        parsed_rows = [
            {
                "event_type": str(row.get("event_type") or "").upper(),
                "peer_name": (row.get("details") or {}).get("peer_ap_name")
                or "",
                "peer_mac": (row.get("details") or {}).get("new_peer_mac")
                or (row.get("details") or {}).get("peer_mac")
                or "",
                "previous_peer_name": (row.get("details") or {}).get(
                    "previous_peer_ap_name"
                )
                or "",
                "previous_peer_mac": (row.get("details") or {}).get(
                    "old_peer_mac"
                )
                or "",
                "details": dict(row.get("details") or {}),
            }
            for row in rows
        ]
        resolver.preload_parsed(parsed_rows)
        for row, parsed in zip(rows, parsed_rows, strict=True):
            details = dict(row.get("details") or {})
            mr_id = str(row.get("mr_id") or "")
            train_id_value = str(row.get("train_id") or "")
            train = train_by_id.get(train_id_value) or {}
            endpoint = endpoint_by_id.get(mr_id) or {}
            suffix = mr_id[-8:] if mr_id else ""
            ap_display = resolver.enrich_parsed(parsed)
            details = dict(ap_display.get("details") or details)
            current_name = str(ap_display.get("peer_name") or "")
            previous_name = str(
                ap_display.get("previous_peer_name") or ""
            )
            message = str(row.get("message") or "")
            event_kind = str(row.get("event_type") or "").casefold()
            current_mac = str(ap_display.get("peer_mac") or "")
            if event_kind == "mesh_activelink_switch":
                if details.get("old_active_link_missing"):
                    previous_name = "无主链路"
                message = (
                    f"{previous_name or '未知 AP'} → "
                    f"{current_name or '未知 AP'}"
                )
            elif event_kind in {"mesh_linkup", "mesh_linkdown"}:
                parts = [current_name or current_mac or "未知 AP"]
                if current_mac and current_mac.casefold() != current_name.casefold():
                    parts.append(current_mac)
                if details.get("rssi") is not None:
                    parts.append(f"RSSI {details['rssi']} dBm")
                if event_kind == "mesh_linkdown" and (
                    details.get("reason_label") or details.get("reason_raw")
                ):
                    parts.append(
                        f"原因：{details.get('reason_label') or details.get('reason_raw')}"
                    )
                message = " · ".join(parts)
            elif not message and current_name:
                message = current_name
            items.append(
                GroundTimelineEventDTO(
                    event_id=row["id"],
                    ts=row["ts"],
                    event_type=row["event_type"],
                    severity=row["severity"],
                    train_id=train_id_value,
                    train_no=str(
                        details.get("train_no") or train.get("train_no") or ""
                    ),
                    train_name=str(train.get("train_name") or ""),
                    mr_id=mr_id,
                    mr_name=str(
                        details.get("mr_name")
                        or endpoint.get("device_name")
                        or (f"未知 MR（{suffix}）" if suffix else "")
                    ),
                    mr_position_code=str(
                        details.get("mr_position_code")
                        or endpoint.get("mr_role")
                        or ""
                    ),
                    title=row["title"],
                    message=message,
                    peer_ap_id=str(details.get("peer_ap_id") or ""),
                    peer_ap_name=current_name,
                    peer_ap_mac=str(details.get("peer_ap_mac") or ""),
                    peer_radio_mac=str(
                        details.get("peer_radio_mac") or ""
                    ),
                    previous_peer_ap_id=str(
                        details.get("previous_peer_ap_id") or ""
                    ),
                    previous_peer_ap_name=previous_name,
                    previous_peer_ap_mac=str(
                        details.get("previous_peer_ap_mac") or ""
                    ),
                    previous_peer_radio_mac=str(
                        details.get("previous_peer_radio_mac") or ""
                    ),
                    station=str(ap_display.get("station") or ""),
                    section=str(ap_display.get("section") or ""),
                    previous_station=str(
                        details.get("previous_station") or ""
                    ),
                    previous_section=str(
                        details.get("previous_section") or ""
                    ),
                    rssi=details.get("rssi", details.get("new_rssi")),
                    previous_rssi=details.get("old_rssi"),
                    reason_code=str(
                        details.get("reason_code")
                        or details.get("switch_reason_code")
                        or ""
                    ),
                    reason_label=str(
                        details.get("reason_label")
                        or details.get("reason_raw")
                        or ""
                    ),
                    resolution_status=str(
                        details.get("resolution_status") or ""
                    ),
                    ap_display=current_name,
                    ap_transition_display=(
                        f"{previous_name or '未知 AP'} → "
                        f"{current_name or '未知 AP'}"
                        if str(row.get("event_type") or "").casefold()
                        == "mesh_activelink_switch"
                        else current_name
                    ),
                    resolved_ap_name=current_name,
                    previous_resolved_ap_name=previous_name,
                    details=details,
                )
            )
        return GroundTimelinePageDTO(
            items=items,
            total=self.repository.count_events(
                str(run["run_id"]),
                train_id=train_id,
                event_type=event_type,
                query=query,
            )
            if run
            else 0,
            page=page,
            page_size=page_size,
            total_exact=True,
        )

    def operation(
        self, site_id: str, operation_id: str
    ) -> GroundOperationDTO:
        self._require_site(site_id)
        row = self.repository.get_operation(operation_id)
        if row is None:
            raise GroundUnattendedError(
                "OPERATION_NOT_FOUND", "运行控制操作不存在", status_code=404
            )
        return GroundOperationDTO.model_validate(row)

    def latest_operation(self, site_id: str) -> GroundOperationDTO | None:
        self._require_site(site_id)
        row = self.repository.latest_terminal_operation()
        return GroundOperationDTO.model_validate(row) if row else None

    def active_operation(self, site_id: str) -> GroundOperationDTO | None:
        self._require_site(site_id)
        active_run = self.repository.get_active_run()
        if active_run is None:
            return None
        row = self.repository.latest_operation(
            run_id=str(active_run["run_id"]), active_only=True
        )
        return GroundOperationDTO.model_validate(row) if row else None

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

    def archive_detail(
        self,
        site_id: str,
        archive_id: str,
        *,
        verify: bool = False,
    ) -> GroundArchiveDetailDTO:
        self._require_site(site_id)
        try:
            inspection = self.raw_query.archive_reader.inspect_archive(
                archive_id, force=verify
            )
        except ValueError as exc:
            raise GroundUnattendedError(
                "ARCHIVE_INTEGRITY_FAILED", str(exc), status_code=409
            ) from exc
        archive = self._archive_dto(inspection.row).model_copy(
            update={
                "file_count": len(inspection.files),
                "integrity_status": "READY",
            }
        )
        return GroundArchiveDetailDTO(
            archive=archive,
            files=[
                GroundArchiveFileDTO.model_validate(item)
                for item in inspection.files
            ],
            validation=GroundArchiveValidationDTO(
                status="READY",
                checked_at=inspection.checked_at,
                archive_size_bytes=inspection.path.stat().st_size,
                archive_sha256=inspection.archive_sha256,
                manifest_sha256=inspection.manifest_sha256,
                file_count=len(inspection.files),
                legacy_manifest=inspection.legacy_manifest,
                message="归档路径、大小、SHA-256、ZIP CRC 与成员清单校验通过",
            ),
        )

    def archive_artifact(
        self, site_id: str, archive_id: str
    ) -> tuple[Path, str, int, str]:
        detail = self.archive_detail(site_id, archive_id)
        inspection = self.raw_query.archive_reader.inspect_archive(archive_id)
        return (
            inspection.path,
            f"{detail.archive.run_date}_ground_unattended.zip",
            inspection.path.stat().st_size,
            inspection.archive_sha256,
        )

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
            location_match_level=row.get("location_match_level", "UNMATCHED"),
            location_match_reason=row.get("location_match_reason", ""),
            resolved_ap_id=row.get("resolved_ap_id", ""),
            resolved_ap_name=row.get("resolved_ap_name", ""),
            raw_peer_ap_name=row.get("raw_peer_ap_name", ""),
            raw_peer_ap_mac=row.get("raw_peer_ap_mac", ""),
            canonical_station_name=row.get("canonical_station_name", ""),
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
            ap_identity_diagnostics=GroundApIdentityDiagnosticsDTO.model_validate(
                row.get("ap_identity_diagnostics") or {}
            ),
            updated_at=row.get("updated_at", ""),
        )

    def _validate_network_profile(
        self,
        profile: GroundUnattendedProfileDTO,
        *,
        require_syslog: bool,
    ) -> None:
        try:
            self.network_service.validate_profile_addresses(
                udp_listen_host=profile.udp_listen_host,
                syslog_server_ip=profile.syslog_server_ip,
                require_syslog=require_syslog,
                allow_external=profile.allow_external_syslog_address,
            )
        except SystemNetworkError as exc:
            raise GroundUnattendedError(
                exc.code, exc.message, status_code=exc.status_code
            ) from exc

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

    def _merge_base_candidate_endpoints(
        self, items: list[GroundUnattendedTrainDTO]
    ) -> list[GroundUnattendedTrainDTO]:
        base_by_train = {
            item.train_id: item for item in self._base_train_candidates()
        }
        if not items:
            return list(base_by_train.values())
        result = []
        seen: set[str] = set()
        for item in items:
            seen.add(item.train_id)
            base = base_by_train.get(item.train_id)
            if base is None:
                result.append(item)
                continue
            base_endpoints = {endpoint.endpoint: endpoint for endpoint in base.endpoints}
            endpoints = [
                endpoint
                if endpoint.mr_id
                else base_endpoints.get(endpoint.endpoint, endpoint)
                for endpoint in item.endpoints
            ]
            result.append(item.model_copy(update={"endpoints": endpoints}))
        result.extend(
            item for train_id, item in base_by_train.items() if train_id not in seen
        )
        return result

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
        profile = self.repository.get_profile()
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
                radio_runtime = (
                    self.repository.get_mr_runtime_state(endpoint.mr_id)
                    if endpoint.mr_id
                    else None
                )
                radio_interfaces = (
                    [
                        _radio_interface_projection(item)
                        for item in self.repository.list_radio_interface_states(
                            device_uuid=endpoint.mr_id
                        )
                    ]
                    if endpoint.mr_id
                    else []
                )
                config_audit = (
                    self.repository.latest_syslog_config_audit(endpoint.mr_id)
                    if endpoint.mr_id
                    else None
                )
                info_center = dict((boot or {}).get("info_center_metrics") or {})
                managed_ip = str(profile.syslog_server_ip or "")
                managed_port = int(profile.syslog_server_port)
                configured_hosts = [
                    GroundSyslogHostDTO(
                        ip=str(host.get("ip") or ""),
                        port=int(host.get("port") or 514),
                        facility=str(host.get("facility") or ""),
                        is_managed_target=(
                            str(host.get("ip") or "") == managed_ip
                            and int(host.get("port") or 514) == managed_port
                        ),
                        same_ip_different_port=(
                            str(host.get("ip") or "") == managed_ip
                            and int(host.get("port") or 514) != managed_port
                        ),
                        source=(
                            "NETCONSOLE_MANAGED"
                            if str(host.get("ip") or "") == managed_ip
                            and int(host.get("port") or 514) == managed_port
                            else "DEVICE_EXISTING"
                        ),
                    )
                    for host in info_center.get("log_hosts") or []
                    if isinstance(host, dict) and host.get("ip")
                ]
                managed_statuses: list[str] = []
                if managed_ip:
                    exact_target = any(
                        host.ip == managed_ip
                        and host.port == managed_port
                        for host in configured_hosts
                    )
                    same_ip_other_port = any(
                        host.ip == managed_ip
                        and host.port != managed_port
                        for host in configured_hosts
                    )
                    managed_statuses.append(
                        "TARGET_PRESENT"
                        if exact_target
                        else "TARGET_PORT_CONFLICT"
                        if same_ip_other_port
                        else "TARGET_MISSING"
                    )
                    if any(
                        host.ip != managed_ip for host in configured_hosts
                    ):
                        managed_statuses.append("OTHER_TARGETS_PRESENT")
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
                            "boot_time_uncertainty_seconds": int(
                                (boot or {}).get(
                                    "boot_time_uncertainty_seconds"
                                )
                                or 0
                            ),
                            "reboot_reason": str(
                                (boot or {}).get("reboot_reason") or ""
                            ),
                            "timezone_name": str(
                                (boot or {}).get("timezone_name") or ""
                            ),
                            "utc_offset_seconds": (boot or {}).get(
                                "utc_offset_seconds"
                            ),
                            "device_time_quality": str(
                                (boot or {}).get("time_quality") or ""
                            ),
                            "config_status": str(
                                (boot or {}).get("config_status") or "NOT_CHECKED"
                            ),
                            "config_checked_at": str(
                                (boot or {}).get("config_checked_at") or ""
                            ),
                            "managed_target_ip": managed_ip,
                            "managed_target_port": managed_port,
                            "managed_target_statuses": managed_statuses,
                            "configured_log_hosts": configured_hosts,
                            "managed_profile_version": int(
                                (config_audit or {}).get(
                                    "managed_profile_version"
                                )
                                or 2
                            ),
                            "radio_interfaces": radio_interfaces,
                            "radio_overall_state": str(
                                (radio_runtime or {}).get(
                                    "radio_overall_state"
                                )
                                or "UNKNOWN"
                            ),
                            "snmp_radio_control_state": str(
                                (radio_runtime or {}).get(
                                    "snmp_radio_control_state"
                                )
                                or "NONE"
                            ),
                            "last_radio_event_at": str(
                                (radio_runtime or {}).get(
                                    "last_radio_event_at"
                                )
                                or ""
                            ),
                            "last_cfg_event_at": str(
                                (radio_runtime or {}).get(
                                    "last_cfg_event_at"
                                )
                                or ""
                            ),
                            "cfg_command_source": str(
                                (radio_runtime or {}).get(
                                    "last_command_source"
                                )
                                or ""
                            ),
                            "cfg_event_index": str(
                                (radio_runtime or {}).get(
                                    "last_cfg_event_index"
                                )
                                or ""
                            ),
                            "correlation_confidence": str(
                                (radio_runtime or {}).get(
                                    "last_correlation_confidence"
                                )
                                or "UNCONFIRMED"
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
                "udp_identity_conflict_count": 0,
                "udp_last_received_at": "",
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

    def _ap_display_resolver(self) -> GroundApDisplayResolver:
        return self._ap_display_cache

    @staticmethod
    def _parse_datetime(value: object) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(
                str(value or "").replace("Z", "+00:00")
            )
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.astimezone()

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
            sha256=str(row.get("sha256") or ""),
            manifest_sha256=str(row.get("manifest_sha256") or ""),
            archive_status=row.get("archive_status", ""),
            retention_until=row.get("retention_until", ""),
            summary=summary,
            message=row.get("message", ""),
            created_at=row.get("created_at", ""),
            updated_at=row.get("updated_at", ""),
        )

    def _run_dto(self, row: dict[str, Any]) -> GroundRunDTO:
        availability, _source = self._run_data_availability(row)
        state = str(row.get("state") or "ERROR")
        return GroundRunDTO(
            run_id=str(row["run_id"]),
            site_id=str(row.get("site_id") or self.site_id),
            run_date=str(row.get("run_date") or ""),
            state=state,  # type: ignore[arg-type]
            paused=bool(row.get("paused")),
            scheduled_start_at=str(row.get("scheduled_start_at") or ""),
            scheduled_end_at=str(row.get("scheduled_end_at") or ""),
            actual_started_at=str(row.get("actual_started_at") or ""),
            actual_ended_at=str(row.get("actual_ended_at") or ""),
            ping_sample_count=int(row.get("ping_sample_count") or 0),
            archive_id=str(row.get("archive_id") or ""),
            archive_status=str(row.get("archive_status") or ""),
            data_availability=availability,  # type: ignore[arg-type]
            message=str(row.get("error_message") or ""),
            created_at=str(row.get("created_at") or ""),
            updated_at=str(row.get("updated_at") or ""),
        )

    def _resolve_run(self, run_id: str = "") -> dict[str, Any] | None:
        if not run_id:
            return self.repository.get_active_run() or self.repository.latest_run()
        run = self.repository.get_run(run_id)
        if run is None:
            raise GroundUnattendedError(
                "RUN_NOT_FOUND", "指定的无人值守运行不存在", status_code=404
            )
        return run

    def _run_data_availability(
        self, run: dict[str, Any] | None
    ) -> tuple[str, str]:
        if not run:
            return "MISSING", "NONE"
        raw_summary = run.get("summary")
        summary = raw_summary if isinstance(raw_summary, Mapping) else {}
        has_summary = bool(
            int(run.get("ping_sample_count") or 0)
            or any(
                int(summary.get(key) or 0)
                for key in (
                    "ping_sample_count",
                    "syslog_record_count",
                    "covered_train_count",
                )
            )
            or self.repository.list_ping_summaries(str(run["run_id"]))
        )
        rows = self.repository.list_raw_files_for_run(str(run["run_id"]))
        if not rows:
            return ("SUMMARY_ONLY" if has_summary else "MISSING"), "NONE"
        active_count = 0
        archived_count = 0
        root = self.repository.db_path.parent.resolve()
        archive = self.repository.get_archive_by_run(str(run["run_id"]))
        archive_status = str((archive or {}).get("archive_status") or "")
        if archive_status == "FAILED":
            return "CORRUPT", "NONE"
        for row in rows:
            if self._registered_raw_file_exists(root, row):
                active_count += 1
            elif (
                str(row.get("archive_status") or "") == "ARCHIVED"
                and archive_status == "READY"
            ):
                archived_count += 1
        source = (
            "MIXED"
            if active_count and archived_count
            else "ACTIVE"
            if active_count
            else "ARCHIVE"
            if archived_count
            else "NONE"
        )
        availability = (
            "MIXED"
            if source == "MIXED"
            else "ACTIVE_RAW"
            if source == "ACTIVE"
            else "ARCHIVED_RAW"
            if source == "ARCHIVE"
            else "SUMMARY_ONLY"
            if has_summary
            else "MISSING"
        )
        return availability, source

    @staticmethod
    def _registered_raw_file_exists(
        root: Path, row: dict[str, Any]
    ) -> bool:
        relative = Path(str(row.get("relative_path") or ""))
        if (
            not relative.parts
            or relative.is_absolute()
            or ".." in relative.parts
        ):
            return False
        candidate = root / relative
        try:
            return (
                candidate.is_file()
                and not candidate.is_symlink()
                and not bool(
                    getattr(candidate, "is_junction", lambda: False)()
                )
            )
        except OSError:
            return False

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


_DEEP_RECORD_SOURCES = {
    "ALL": (
        "collector_output",
        "mesh_link",
        "ap_radio_statistics",
        "wireless_status",
        "terminal_monitor",
    ),
    "WMESH": ("mesh_link", "switch_history"),
    "RSSI": ("ap_radio_statistics",),
    "RADIO": ("wireless_status", "interface_rate"),
    "STATUS": ("collector", "terminal_monitor"),
    "RAW_OUTPUT": ("collector_output",),
}


def _deep_operation_state(
    operation: Mapping[str, Any], train: Mapping[str, Any]
) -> tuple[str, str]:
    if not operation:
        if not train.get("deep_collection_eligible"):
            return "INELIGIBLE", str(
                train.get("deep_exclusion_reason") or "不具备深度采集资格"
            )
        return "ELIGIBLE", "符合深度采集资格，等待调度"
    state = str(operation.get("state") or "STARTING").upper()
    reason = str(operation.get("error_summary") or "")
    mapping = {
        "STARTING": ("STARTING", "正在建立 Online MR 会话"),
        "RUNNING": ("RUNNING", "Collector 正在运行，等待写入证据"),
        "FINALIZING": ("STOPPING", "正在停止并归集采集结果"),
        "COMPLETED": ("STOPPED", "深度采集已正常结束"),
        "PARTIAL": ("FAILED", "深度采集仅产生部分结果"),
        "FAILED": ("FAILED", "深度采集失败"),
    }
    resolved, default_reason = mapping.get(state, ("STARTING", "正在建立 Online MR 会话"))
    return resolved, reason or default_reason


def _deep_record_category(source: str) -> str:
    if source in {"mesh_link", "switch_history"}:
        return "WMESH"
    if source == "ap_radio_statistics":
        return "RSSI"
    if source in {"wireless_status", "interface_rate"}:
        return "RADIO"
    if source in {"collector", "terminal_monitor"}:
        return "STATUS"
    return "RAW_OUTPUT"


def _decode_deep_cursor(value: str) -> dict[str, Any]:
    if not value:
        return {}
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(decoded.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        raise GroundUnattendedError(
            "DEEP_RECORD_CURSOR_INVALID", "深采记录游标无效", status_code=409
        ) from None
    return payload if isinstance(payload, dict) else {}


def _encode_deep_cursor(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _listen_address_matches(actual: str, configured_host: str, configured_port: int) -> bool:
    try:
        actual_host, actual_port = actual.rsplit(":", 1)
        return int(actual_port) == int(configured_port) and (
            actual_host == configured_host
            or actual_host == "0.0.0.0"
            or configured_host == "0.0.0.0"
        )
    except (TypeError, ValueError):
        return False


def _radio_interface_projection(row: dict[str, Any]) -> dict[str, object]:
    return {
        "interface_name": str(row.get("interface_name") or ""),
        "current_state": str(row.get("current_state") or "UNKNOWN"),
        "previous_state": str(row.get("previous_state") or "UNKNOWN"),
        "last_changed_at": str(row.get("last_changed_at") or ""),
        "down_since": str(row.get("down_since") or ""),
        "last_up_at": str(row.get("last_up_at") or ""),
        "last_down_at": str(row.get("last_down_at") or ""),
        "latest_outage_duration_ms": row.get("latest_outage_duration_ms"),
        "transition_count_5m": int(row.get("transition_count_5m") or 0),
        "snmp_related_transition_count_5m": int(
            row.get("snmp_related_transition_count_5m") or 0
        ),
        "last_cfg_event_index": str(row.get("last_cfg_event_index") or ""),
        "last_command_source": str(row.get("last_command_source") or ""),
        "correlation_confidence": str(
            row.get("correlation_confidence") or "UNCONFIRMED"
        ),
        "last_event_id": row.get("last_event_id"),
    }


def _radio_composite_event_type(
    correlations: list[dict[str, Any]],
    event_by_id: dict[int, dict[str, Any]],
    parse_datetime: Any,
) -> str:
    ifnet_events = [
        event_by_id.get(int(row["ifnet_event_id"]))
        for row in correlations
    ]
    ifnet_events = [event for event in ifnet_events if event is not None]
    by_interface: dict[str, list[dict[str, Any]]] = {}
    for event in ifnet_events:
        by_interface.setdefault(
            str(event.get("interface_name") or ""), []
        ).append(event)
    for events in by_interface.values():
        ordered = sorted(
            events,
            key=lambda event: str(
                event.get("event_time") or event.get("receive_time") or ""
            ),
        )
        for index, down_event in enumerate(ordered):
            if str(down_event.get("physical_state") or "").upper() != "DOWN":
                continue
            down_time = parse_datetime(
                down_event.get("event_time")
                or down_event.get("receive_time")
            )
            if down_time is None:
                continue
            for up_event in ordered[index + 1 :]:
                if str(up_event.get("physical_state") or "").upper() != "UP":
                    continue
                up_time = parse_datetime(
                    up_event.get("event_time")
                    or up_event.get("receive_time")
                )
                if (
                    up_time is not None
                    and 0 <= (up_time - down_time).total_seconds() <= 5
                ):
                    return "RADIO_SNMP_BOUNCE"
    states = {
        str(event.get("physical_state") or "").upper()
        for event in ifnet_events
    }
    if "DOWN" in states:
        return "RADIO_SNMP_DOWN"
    if "UP" in states:
        return "RADIO_SNMP_UP"
    return ""


def _preferred_composite_type(values: set[str]) -> str:
    for event_type in (
        "RADIO_SNMP_BOUNCE",
        "RADIO_SNMP_DOWN",
        "RADIO_SNMP_UP",
    ):
        if event_type in values:
            return event_type
    return ""


__all__ = ["GroundUnattendedApplicationService", "GroundUnattendedError"]
