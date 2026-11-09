from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import re
import shutil
import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from netconsole.core.database import Database
from netconsole.core.model_projection import project_row_for_model
from netconsole.core.paths import PathResolver
from netconsole.services.site_manager import SiteManager
from netconsole.models.api.ground_unattended import (
    GroundApIdentityDiagnosticsDTO,
    GroundActionResponseDTO,
    GroundArchiveDTO,
    GroundArchiveDetailDTO,
    GroundArchiveFileDTO,
    GroundArchivePageDTO,
    GroundArchiveValidationDTO,
    GroundArchiveBatchDeleteRequestDTO,
    GroundArchiveBatchDeleteResponseDTO,
    GroundArchiveBatchDeleteItemDTO,
    GroundDeepCollectionDTO,
    GroundDeepCollectorDTO,
    GroundDeepTaskPageDTO,
    GroundDeepCollectionRecordDTO,
    GroundDeepCollectionRecordPageDTO,
    GroundDeepCollectionPageDTO,
    GroundPingSummaryPageDTO,
    GroundPingSampleDTO,
    GroundPingSamplePageDTO,
    GroundPingSeriesDTO,
    GroundPingTargetDTO,
    GroundQuickPingPageDTO,
    GroundQuickPingRunDTO,
    GroundQuickPingSamplePageDTO,
    GroundHistoryPageDTO,
    GroundQuickPingStartRequestDTO,
    GroundRunDTO,
    GroundRunPageDTO,
    GroundRunDeleteRequestDTO,
    GroundAcPollerHealthDTO,
    GroundHealthDTO,
    GroundHeartbeatMrDTO,
    GroundSyslogControlRequestDTO,
    GroundHeartbeatIpDTO,
    GroundHeartbeatApDTO,
    GroundHeartbeatInventoryApplyDTO,
    GroundHeartbeatInventoryPreviewDTO,
    GroundHeartbeatPageDTO,
    GroundHeartbeatStatisticsDTO,
    GroundMrMonitoringDTO,
    GroundHeartbeatTrainDTO,
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
from netconsole.services.ground_unattended.quick_ping import (
    QuickPingConfig,
    QuickPingError,
    QuickPingService,
    QuickPingTarget,
)
from netconsole.services.ground_unattended.history_query import GroundHistoryQueryError, GroundHistoryQueryService
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
from netconsole.services.job_center.task_application_service import TaskApplicationService


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
        quick_ping_service: QuickPingService | None = None,
        task_service: TaskApplicationService | None = None,
    ) -> None:
        self.paths = paths
        self.site_id = site_id
        self.repository = repository
        self.supervisor = supervisor
        self.task_service = task_service
        self.quick_ping = quick_ping_service or QuickPingService(
            site_id=site_id,
            output_root=paths.ground_unattended_root(site_id),
            repository=repository,
        )
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

    def quick_ping_start(
        self,
        site_id: str,
        payload: GroundQuickPingStartRequestDTO,
    ) -> GroundQuickPingRunDTO:
        self._require_site(site_id)
        if self.base_query is None:
            raise GroundUnattendedError(
                "QUICK_PING_INVENTORY_UNAVAILABLE",
                "当前局点的 MR 基础资料查询服务不可用",
                status_code=503,
            )
        base_mrs: dict[str, Any] = {}
        page = self.base_query.list_mrs(site_id, page=1, page_size=200)
        base_mrs.update((str(item.id), item) for item in page.items)
        current_page = 2
        while len(base_mrs) < page.total:
            batch = self.base_query.list_mrs(
                site_id, page=current_page, page_size=200
            )
            if not batch.items:
                break
            base_mrs.update((str(item.id), item) for item in batch.items)
            current_page += 1
        validated_targets: list[QuickPingTarget] = []
        for item in payload.targets:
            mr = base_mrs.get(item.mr_id)
            if mr is None:
                raise GroundUnattendedError(
                    "QUICK_PING_MR_NOT_FOUND",
                    f"MR {item.mr_id} 不存在于当前局点基础资料",
                    status_code=409,
                )
            expected_ip = (
                str(mr.management_ip or "").strip()
                if item.address_role == "PRIMARY"
                else str(mr.backup_management_ip or "").strip()
            )
            try:
                expected_ip = str(ipaddress.ip_address(expected_ip))
                requested_ip = str(ipaddress.ip_address(item.target_ip.strip()))
            except ValueError as exc:
                raise GroundUnattendedError(
                    "QUICK_PING_ADDRESS_NOT_IN_INVENTORY",
                    f"MR {item.mr_id} 的所选管理地址无效或未配置",
                    status_code=409,
                ) from exc
            if expected_ip != requested_ip:
                raise GroundUnattendedError(
                    "QUICK_PING_ADDRESS_NOT_IN_INVENTORY",
                    f"目标地址与 MR {item.mr_id} 的基础资料不匹配",
                    status_code=409,
                )
            validated_targets.append(
                QuickPingTarget(
                    target_ip=expected_ip,
                    train_id=str(mr.train_id or ""),
                    train_no=str(mr.train_no or ""),
                    mr_id=str(mr.id),
                    mr_name=str(mr.name or ""),
                    mr_role=str(mr.mr_position_code or ""),
                    address_role=item.address_role,
                    current_ap_name=str(getattr(mr, "current_ap_name", "") or ""),
                    station=str(getattr(mr, "station", "") or ""),
                    section=str(getattr(mr, "section", "") or ""),
                )
            )
        try:
            run_id = self.quick_ping.start(
                targets=validated_targets,
                config=QuickPingConfig(
                    interval_ms=payload.interval_ms,
                    timeout_ms=payload.timeout_ms,
                    packet_size=payload.packet_size,
                    duration_seconds=payload.duration_seconds,
                    max_in_flight=payload.max_in_flight,
                ),
            )
        except QuickPingError as exc:
            raise GroundUnattendedError(exc.code, exc.message, status_code=exc.status_code) from exc
        return self._quick_ping_dto(run_id)

    def quick_ping_status(self, site_id: str, run_id: str) -> GroundQuickPingRunDTO:
        self._require_site(site_id)
        return self._quick_ping_dto(run_id)

    def quick_ping_list(
        self, site_id: str, *, limit: int = 100, offset: int = 0,
        start_time: str = "", end_time: str = "", query: str = "", state: str = "",
        train_id: str = "", mr_id: str = "", mr_role: str = "",
    ) -> GroundQuickPingPageDTO:
        self._require_site(site_id)
        try:
            values, total = self.quick_ping.query_runs(
                limit=limit, offset=offset, start_time=start_time, end_time=end_time,
                query=query, state=state, train_id=train_id, mr_id=mr_id, mr_role=mr_role,
            )
        except QuickPingError as exc:
            raise GroundUnattendedError(exc.code, exc.message, status_code=exc.status_code) from exc
        return GroundQuickPingPageDTO(
            items=[self._quick_ping_run_dto_with_events(value) for value in values],
            active_ips=self.quick_ping.active_ips(),
            total=total, offset=offset, limit=limit,
        )

    def quick_ping_samples(
        self, site_id: str, run_id: str, *, target_ip: str = "", start_time: str = "",
        end_time: str = "", limit: int = 1000, cursor: str = "",
    ) -> GroundQuickPingSamplePageDTO:
        self._require_site(site_id)
        try:
            return GroundQuickPingSamplePageDTO.model_validate(self.quick_ping.query_samples(
                run_id, target_ip=target_ip, start_time=start_time, end_time=end_time,
                limit=limit, cursor=cursor,
            ))
        except QuickPingError as exc:
            raise GroundUnattendedError(exc.code, exc.message, status_code=exc.status_code) from exc

    def quick_ping_stop(self, site_id: str, run_id: str) -> GroundQuickPingRunDTO:
        self._require_site(site_id)
        try:
            self.quick_ping.stop(run_id)
        except QuickPingError as exc:
            raise GroundUnattendedError(exc.code, exc.message, status_code=exc.status_code) from exc
        return self._quick_ping_dto(run_id)

    def quick_ping_stop_target(self, site_id: str, run_id: str, target_ip: str) -> GroundQuickPingRunDTO:
        self._require_site(site_id)
        try:
            self.quick_ping.stop_target(run_id, target_ip)
        except QuickPingError as exc:
            raise GroundUnattendedError(exc.code, exc.message, status_code=exc.status_code) from exc
        return self._quick_ping_dto(run_id)

    def history(
        self, site_id: str, *, data_type: str = "", run_id: str = "", train_id: str = "",
        mr_id: str = "", mr_role: str = "", event_type: str = "", start_at: str = "", end_at: str = "",
        page: int = 1, page_size: int = 100, sort_order: str = "desc",
    ) -> GroundHistoryPageDTO:
        self._require_site(site_id)
        try:
            result = GroundHistoryQueryService(self.repository.db_path, site_id=site_id).query(
                data_type=data_type, run_id=run_id, train_id=train_id, mr_id=mr_id,
                mr_role=mr_role, event_type=event_type, start_at=start_at, end_at=end_at,
                page=page, page_size=page_size, sort_order=sort_order,
            )
        except GroundHistoryQueryError as exc:
            raise GroundUnattendedError(exc.code, exc.message, status_code=exc.status_code) from exc
        return GroundHistoryPageDTO.model_validate(result)

    def close(self) -> None:
        """Stop site-scoped diagnostic workers owned by this application service."""
        self.quick_ping.close()

    @staticmethod
    def _heartbeat_ap_projection(identity: Any) -> tuple[list[GroundHeartbeatApDTO], list[str]]:
        """Project only explicit AC Mesh MR->peer AP observations for heartbeat UI."""
        if identity is None:
            return [], []
        projected: list[GroundHeartbeatApDTO] = []
        seen: set[tuple[str, str, str, str]] = set()
        for peer in getattr(identity, "peer_aps", ()) or ():
            name = str(getattr(peer, "peer_ap_name", "") or "").strip()
            bssid = str(getattr(peer, "bssid", "") or "").strip()
            mac = str(getattr(peer, "peer_ap_mac", "") or "").strip()
            station = str(getattr(peer, "station", "") or "").strip()
            section = str(getattr(peer, "section", "") or "").strip()
            key = (name, bssid, mac, station)
            if not any(key) or key in seen:
                continue
            seen.add(key)
            projected.append(GroundHeartbeatApDTO(
                name=name,
                bssid=bssid,
                mac=mac,
                rssi=getattr(peer, "rssi", None),
                connection_status=("ONLINE" if str(getattr(peer, "mr_online_status", "")).lower() == "online"
                                   else str(getattr(peer, "data_status", "") or "UNKNOWN").upper()),
                last_seen_at=str(getattr(peer, "last_seen_at", "") or ""),
                station=station,
                section=section,
            ))
        stations = sorted({ap.station for ap in projected if ap.station})
        return projected, stations

    def _quick_ping_dto(self, run_id: str) -> GroundQuickPingRunDTO:
        run = self.quick_ping.status(run_id)
        if run is None:
            raise GroundUnattendedError("QUICK_PING_NOT_FOUND", "快速 Ping 任务不存在", status_code=404)
        return self._quick_ping_run_dto_with_events(run.as_dict())

    def _quick_ping_run_dto_with_events(self, value: dict[str, Any]) -> GroundQuickPingRunDTO:
        dto = self._quick_ping_run_dto(value)
        dto.loss_events = self.repository.list_ping_loss_intervals(dto.run_id, limit=500)
        return dto

    @staticmethod
    def _quick_ping_run_dto(value: dict[str, Any]) -> GroundQuickPingRunDTO:
        return GroundQuickPingRunDTO.model_validate(value)

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

    def heartbeat(self, site_id: str, *, run_id: str = "", query: str = "", status: str = "", station: str = "", abnormal_only: bool = False, page: int = 1, page_size: int = 50, mr_uuid: str = "", role: str = "") -> GroundHeartbeatPageDTO:
        """Read durable heartbeat facts without deriving reachability from AC data."""
        self._require_site(site_id)
        state = self.repository.heartbeat_inventory_state()
        source_conflicts: list[str] = []
        active_run = self.repository.get_active_run()
        # A page refresh reconciles the device projection once per source change;
        # it never starts probes. Explicit clearing suppresses regeneration.
        # During an active run the supervisor has already synchronized the
        # inventory, and re-running the full source preview for every heartbeat
        # read can occupy the backend thread pool. Explicit inventory sync
        # remains available for changes while monitoring is active.
        supervisor_running = bool(getattr(self.supervisor, "running", False))
        if (
            not run_id
            and (not active_run or not supervisor_running)
            and state["enabled"]
            and self.inventory_sync is not None
        ):
            preview = self.inventory_sync.preview()
            source_conflicts = preview["conflicts"]
            if not source_conflicts and any(preview[key] for key in (
                "added_count", "updated_count", "disabled_count",
            )):
                self.sync_inventory(site_id)
        run = self._resolve_run(run_id)
        resolved_id = str(run["run_id"]) if run else ""
        is_current = not run_id or bool(
            active_run and str(active_run["run_id"]) == resolved_id
        )
        inventory = self.repository.list_inventory(include_removed=not is_current)
        snapshot_rows = (
            self.repository.list_heartbeat_snapshots(resolved_id)
            if resolved_id
            else []
        )
        # A selected historical run can legitimately have no heartbeat facts
        # (for example, a run created before the first probe). Keep that run
        # context in the response, but project the current active inventory so
        # the page does not turn a known 21/42 inventory into an unsupported 0.
        inventory_projection = bool(
            state["enabled"] and resolved_id and not snapshot_rows
        )
        if inventory_projection:
            inventory = self.repository.list_inventory(include_removed=False)
        trains_by_id = {str(row["train_id"]): row for row in inventory}
        endpoints = {
            str(endpoint.get("device_uuid") or ""): endpoint
            for row in inventory for endpoint in row.get("endpoints", [])
        }
        syslog_audits = self.repository.latest_syslog_config_audits(endpoints)

        def apply_syslog_projection(payload: dict[str, Any], endpoint: dict[str, Any]) -> dict[str, Any]:
            audit = syslog_audits.get(str(payload.get("mr_uuid") or ""), {})
            audit_status = str(audit.get("status") or "").upper()
            payload["management_ip"] = str(endpoint.get("management_ip") or "")
            payload["backup_management_ip"] = str(endpoint.get("backup_management_ip") or "")
            payload["syslog_status"] = {
                "CONFIGURING": "CONFIGURING",
                "VERIFYING": "VERIFYING",
                "EXITING": "EXITING",
                "EXITED": "EXITED",
                "CONFIG_SENT": "CONFIGURED",
                "CONFIG_REPAIRED": "CONFIGURED",
                "CONFIG_PRESENT": "CONFIGURED",
                "CONFIG_VERIFY_FAILED": "FAILED",
                "EXIT_VERIFY_FAILED": "FAILED",
                "CONFIG_FAILED": "FAILED",
                "EXIT_FAILED": "FAILED",
                "TARGET_PORT_CONFLICT": "FAILED",
            }.get(audit_status, "NOT_CONFIGURED" if audit_status in {"", "AUTO_REPAIR_DISABLED"} else "UNKNOWN")
            payload["syslog_last_error"] = str(audit.get("error_message") or "")
            return payload
        # Reuse the AC view's exact physical MR identity contract; its peer AP is
        # deliberately not the MR body identity or location.
        from netconsole.services.ac.mesh_link_query_service import AcMeshLinkQueryService
        ac_query = AcMeshLinkQueryService(self.paths)
        identity_rows: dict[str, Any] = {}
        ac_page = 1
        while True:
            result = ac_query.list_mrs(site_id, page=ac_page, page_size=200)
            for item in result.items:
                identity_rows[str(item.mr_device_id)] = item
            if ac_page * 200 >= result.total:
                break
            ac_page += 1
        recent_rtts = self.supervisor.fleet_ping.latest_mr_rtts(resolved_id) if is_current else {}
        mrs: list[GroundHeartbeatMrDTO] = []
        trains: list[GroundHeartbeatTrainDTO] = []
        for row in snapshot_rows:
            if state["data_cleared_at"] and str(row.get("updated_at") or "") <= state["data_cleared_at"]:
                continue
            payload = dict(row["snapshot"])
            train_id = str(payload.get("train_id") or "")
            if (is_current or inventory_projection) and train_id not in trains_by_id:
                continue
            train = trains_by_id.get(train_id, {})
            payload.update(
                train_no=str(train.get("train_no") or ""),
                updated_at=str(row.get("updated_at") or ""),
            )
            if row["entity_type"] == "MR":
                endpoint = endpoints.get(str(payload.get("mr_uuid") or ""), {})
                if (is_current or inventory_projection) and (
                    not endpoint
                    or str(endpoint.get("train_id") or "") != train_id
                    or str(endpoint.get("mr_role") or "").upper() != str(payload.get("role") or "").upper()
                ):
                    continue
                if is_current or inventory_projection:
                    expected_ips = {str(endpoint.get("management_ip") or "")}
                    if endpoint.get("backup_monitoring_strategy") == "MONITOR":
                        expected_ips.add(str(endpoint.get("backup_management_ip") or ""))
                    expected_ips.discard("")
                    if {str(ip.get("ip") or "") for ip in payload.get("ip_states", [])} != expected_ips:
                        continue
                payload["mr_name"] = str(endpoint.get("device_name") or "")
                apply_syslog_projection(payload, endpoint)
                identity = identity_rows.get(str(payload.get("mr_uuid") or ""))
                if identity is not None:
                    associated_aps, associated_stations = self._heartbeat_ap_projection(identity)
                    payload.update(resolved_ap_name=identity.resolved_ap, identity_status=identity.identity_status,
                                   ac_data_status=identity.data_status, station=identity.resolved_ap_station,
                                   section=identity.resolved_ap_section,
                                   associated_aps=associated_aps,
                                   associated_stations=associated_stations)
                payload["current_rtt_ms"] = recent_rtts.get(str(payload.get("mr_uuid") or ""))
                mrs.append(GroundHeartbeatMrDTO.model_validate(
                    project_row_for_model(payload, GroundHeartbeatMrDTO)
                ))
            elif row["entity_type"] == "TRAIN":
                trains.append(GroundHeartbeatTrainDTO.model_validate(payload))
        # Inventory objects exist before the first run/sample. Unknown means
        # no evidence, never "offline" or an AC-derived reachability result.
        if is_current or inventory_projection:
            present = {mr.mr_uuid for mr in mrs}
            for mr_id, endpoint in endpoints.items():
                if mr_id in present:
                    continue
                train = trains_by_id.get(str(endpoint.get("train_id") or ""), {})
                identity = identity_rows.get(mr_id)
                associated_aps, associated_stations = self._heartbeat_ap_projection(identity)
                ips = [str(endpoint.get("management_ip") or "")]
                if endpoint.get("backup_monitoring_strategy") == "MONITOR":
                    ips.append(str(endpoint.get("backup_management_ip") or ""))
                projected = apply_syslog_projection({"mr_uuid": mr_id}, endpoint)
                mrs.append(GroundHeartbeatMrDTO(
                    mr_uuid=mr_id, train_id=str(endpoint.get("train_id") or ""),
                    train_no=str(train.get("train_no") or ""),
                    mr_name=str(endpoint.get("device_name") or ""),
                    role=str(endpoint.get("mr_role") or ""),
                    management_ip=str(endpoint.get("management_ip") or ""),
                    backup_management_ip=str(endpoint.get("backup_management_ip") or ""),
                    syslog_status=str(projected.get("syslog_status") or "NOT_CONFIGURED"),  # type: ignore[arg-type]
                    syslog_last_error=str(projected.get("syslog_last_error") or ""),
                    resolved_ap_name=identity.resolved_ap if identity else "",
                    station=identity.resolved_ap_station if identity else "",
                    section=identity.resolved_ap_section if identity else "",
                    associated_aps=associated_aps,
                    associated_stations=associated_stations,
                    ip_states=[GroundHeartbeatIpDTO(ip=ip) for ip in dict.fromkeys(ips) if ip],
                ))
        if is_current or inventory_projection:
            # An IP/group/role edit invalidates an MR snapshot above. A train
            # aggregate from before that edit must not continue to advertise
            # BOTH_ONLINE alongside a newly UNKNOWN endpoint.
            current_members: dict[str, dict[str, str]] = {}
            for mr in mrs:
                current_members.setdefault(mr.train_id, {})[mr.role] = mr.status
            trains = [
                train for train in trains
                if train.mr_states == current_members.get(train.train_id, {})
            ]
        # Older runs can contain durable MR facts without a train aggregate.
        # Retain those facts in an explicitly UNKNOWN row, never infer online.
        snapshotted_train_ids = {row.train_id for row in trains}
        for mr in mrs:
            if mr.train_id not in snapshotted_train_ids:
                members = {row.role: row.status for row in mrs if row.train_id == mr.train_id}
                trains.append(GroundHeartbeatTrainDTO(train_id=mr.train_id, train_no=mr.train_no,
                                                       status="UNKNOWN", mr_states=members))
                snapshotted_train_ids.add(mr.train_id)
        mr_counts: dict[str, int] = dict.fromkeys(
            ("ONLINE", "OFFLINE", "OFFLINE_PENDING", "RECOVERING", "UNKNOWN"), 0
        )
        train_counts: dict[str, int] = {}
        for mr in mrs:
            mr_counts[mr.status] = mr_counts.get(mr.status, 0) + 1
        for train in trains:
            train_counts[train.status] = train_counts.get(train.status, 0) + 1
        sent_count = success_count = lost_count = 0
        weighted_rtt = 0.0
        latest_sample_at = ""
        loss_events_by_mr = (
            self.repository.list_ping_loss_intervals_by_mr(
                resolved_id, (mr.mr_uuid for mr in mrs), limit_per_mr=200,
                started_after=str(state["data_cleared_at"]),
            )
            if resolved_id
            else {}
        )
        for mr in mrs:
            if resolved_id:
                mr.loss_events = loss_events_by_mr.get(mr.mr_uuid, [])
            for ip in mr.ip_states:
                sent_count += int(ip.sent_count or 0)
                success_count += int(ip.received_count or 0)
                lost_count += int(ip.lost_count or 0)
                if ip.avg_rtt_ms is not None:
                    weighted_rtt += float(ip.avg_rtt_ms) * int(ip.received_count or 0)
                if ip.sent_count or ip.received_count or ip.lost_count:
                    candidate = ip.last_probe_at or ip.last_success_at
                    if candidate > latest_sample_at:
                        latest_sample_at = candidate
        has_samples = sent_count > 0 or success_count > 0 or lost_count > 0
        run_state = str((run or {}).get("state") or "").upper()
        if not inventory:
            data_state = "DISABLED" if not state["enabled"] else "NO_INVENTORY"
            data_state_message = "已停用心跳监测对象" if not state["enabled"] else "当前局点没有已登记的心跳监测对象"
        elif not state["enabled"]:
            data_state, data_state_message = "DISABLED", "心跳监测已停止，设备清单保留"
        elif run_state in {"COMPLETED", "FINALIZING", "ARCHIVING"}:
            data_state, data_state_message = "STOPPED", "心跳监测已停止，保留设备清单和最近有效采样"
        elif not has_samples:
            data_state = (
                "INITIALIZING" if run_state == "STARTING"
                else "PAUSED" if run_state == "PAUSED"
                else "ERROR" if run_state == "ERROR"
                else "WAITING_FOR_SAMPLES" if resolved_id else "NOT_STARTED"
            )
            data_state_message = (
                "心跳任务报告错误，尚未产生有效采样" if data_state == "ERROR"
                else "已生成监测对象，等待首个 Ping 采样" if resolved_id
                else "监测任务尚未启动，设备状态待检测"
            )
        elif run_state == "ERROR":
            data_state, data_state_message = "ERROR", "心跳任务报告错误，保留最近有效采样"
        elif run_state == "PAUSED":
            data_state, data_state_message = "PAUSED", "心跳任务已暂停，状态保留在最近有效采样"
        elif latest_sample_at:
            try:
                age = (datetime.now().astimezone() - datetime.fromisoformat(latest_sample_at.replace("Z", "+00:00"))).total_seconds()
            except ValueError:
                age = 0
            if age > max(30, self.repository.get_profile().fleet_ping_timeout_ms / 1000 * 5):
                data_state, data_state_message = "STALE", "最近心跳采样已超过刷新阈值"
            else:
                data_state, data_state_message = "RUNNING", "正在接收实时心跳采样"
        else:
            data_state, data_state_message = "RUNNING", "正在接收实时心跳采样"
        total_mrs = len(mrs)
        stations = sorted({station_name for mr in mrs for station_name in (
            list(mr.associated_stations) + ([mr.station] if mr.station else [])
        ) if station_name})
        needle = query.strip().casefold()
        selected_ids = {
            mr.train_id for mr in mrs
            if (not needle or needle in " ".join((
                mr.train_no, mr.mr_name, mr.mr_uuid, mr.resolved_ap_name,
                *(ap.name for ap in mr.associated_aps),
                *(ap.bssid for ap in mr.associated_aps),
                *(ap.mac for ap in mr.associated_aps),
                *(ip.ip for ip in mr.ip_states),
            )).casefold())
            and (not station or station in set(mr.associated_stations) | ({mr.station} if mr.station else set()))
            and (not mr_uuid or mr.mr_uuid == mr_uuid)
            and (not role or mr.role == role.upper())
        }
        trains = [row for row in trains if row.train_id in selected_ids
                  and (not status or row.status == status)
                  and (not abnormal_only or row.status not in {"BOTH_ONLINE", "SINGLE_ONLINE"})]
        trains.sort(key=lambda row: [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", row.train_no or row.train_id)])
        total = len(trains)
        page, page_size = max(1, page), max(1, min(200, page_size))
        trains = trains[(page - 1) * page_size:page * page_size]
        selected_ids = {row.train_id for row in trains}
        mrs = [row for row in mrs if row.train_id in selected_ids]
        return GroundHeartbeatPageDTO(
            monitoring_enabled=bool(state["enabled"]), source_conflicts=source_conflicts,
            data_cleared_at=str(state["data_cleared_at"]),
            run_id=resolved_id, run_state=run_state,
            mrs=mrs, trains=trains, mr_counts=mr_counts, train_counts=train_counts,
            total=total, total_mrs=total_mrs, page=page, page_size=page_size, stations=stations,
            data_state=data_state, data_state_message=data_state_message,
            inventory_train_count=len(inventory),
            inventory_mr_count=sum(len(row.get("endpoints", [])) for row in inventory),
            heartbeat_statistics=GroundHeartbeatStatisticsDTO(
                sent_count=sent_count,
                success_count=success_count,
                lost_count=lost_count,
                average_rtt_ms=(weighted_rtt / success_count) if success_count else None,
                loss_rate_percent=(lost_count / sent_count * 100) if sent_count else None,
                latest_sample_at=latest_sample_at,
            ),
        )

    def mr_monitoring(self, site_id: str, *, mr_uuid: str, run_id: str = "", start_time: str = "", end_time: str = "") -> GroundMrMonitoringDTO:
        from netconsole.services.ground_unattended.monitoring import monitoring_range, mesh_evidence, indexed_evidence, ac_peer_intervals
        try:
            start, end = monitoring_range(start_time, end_time)
        except ValueError as exc:
            raise GroundUnattendedError("GROUND_MONITOR_RANGE_INVALID", str(exc)) from exc
        heartbeat = self.heartbeat(site_id, run_id=run_id, mr_uuid=mr_uuid)
        mr = next((row for row in heartbeat.mrs if row.mr_uuid == mr_uuid), None)
        if mr is None:
            raise GroundUnattendedError("GROUND_MR_NOT_FOUND", "当前运行中没有该 MR 的心跳快照")
        cleared_at = self.repository.heartbeat_inventory_state()["data_cleared_at"]
        if cleared_at:
            start = max(start, datetime.fromisoformat(cleared_at))
        if not heartbeat.run_id or start >= end:
            return GroundMrMonitoringDTO(mr=mr, series=GroundPingSeriesDTO(),
                                         queried_start=start.isoformat(), queried_end=end.isoformat())
        series = self.ping_series(site_id, run_id=heartbeat.run_id, mr_id=mr_uuid,
                                  start_time=start.isoformat(), end_time=end.isoformat(), max_points=2400)
        rows, ac_rows, truncated = indexed_evidence(self.repository.db_path, site_id=site_id, run_id=heartbeat.run_id,
                                                   mr_uuid=mr_uuid, start=start, end=end)
        resolver = self._ap_display_resolver()
        resolver.preload_parsed(rows)
        events, intervals = mesh_evidence([resolver.enrich_parsed(row) for row in rows], start, end)
        intervals.extend(ac_peer_intervals(ac_rows, intervals))
        intervals.sort(key=lambda row: row["start"])
        return GroundMrMonitoringDTO(mr=mr, series=series, mesh_events=events, peer_intervals=intervals,
                                     run_sent_count=sum(ip.sent_count for ip in mr.ip_states),
                                     run_lost_count=sum(ip.lost_count for ip in mr.ip_states),
                                     loss_events=self.repository.list_ping_loss_intervals(
                                         heartbeat.run_id, mr_id=mr_uuid, limit=500,
                                         started_after=str(cleared_at),
                                     ),
                                     queried_start=start.isoformat(), queried_end=end.isoformat(), events_truncated=truncated)

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
        endpoint_ids = [
            str(endpoint.get("device_uuid") or "")
            for train in inventory
            for endpoint in train.get("endpoints", [])
            if str(endpoint.get("device_uuid") or "")
        ]
        endpoint_runtime = self.repository.train_endpoint_snapshot(endpoint_ids)
        boot_by_device = endpoint_runtime["boot_by_device"]
        audit_by_device = endpoint_runtime["audit_by_device"]
        for train in inventory:
            for endpoint in train.get("endpoints", []):
                device_uuid = str(endpoint.get("device_uuid") or "")
                boot = boot_by_device.get(device_uuid)
                if boot and boot.get("last_syslog_received_at"):
                    syslog_active += 1
                audit = audit_by_device.get(device_uuid)
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
        if str(run.get("state") or "").upper() != "RUNNING":
            raise GroundUnattendedError(
                "RUN_NOT_PAUSABLE",
                "仅运行中的无人值守任务可以暂停",
                status_code=409,
            )
        self.supervisor.request("pause")
        return GroundActionResponseDTO(
            state="PAUSED",
            run_id=str(run["run_id"]),
            message="深度采集调度将暂停，心跳检测继续",
        )

    def resume(self, site_id: str) -> GroundActionResponseDTO:
        run = self._active(site_id)
        if str(run.get("state") or "").upper() != "PAUSED":
            raise GroundUnattendedError(
                "RUN_NOT_RESUMABLE",
                "仅已暂停的无人值守任务可以继续",
                status_code=409,
            )
        self.supervisor.request("resume")
        return GroundActionResponseDTO(
            state="RUNNING", run_id=str(run["run_id"]), message="深度采集调度将继续"
        )

    def stop(self, site_id: str, *, archive: bool) -> GroundActionResponseDTO:
        run = self._active(site_id)
        run_id = str(run["run_id"])
        now = datetime.now().astimezone().isoformat(timespec="milliseconds")
        operation_id = f"groundop_{uuid.uuid4().hex}"
        request_id = f"groundreq_{uuid.uuid4().hex}"
        stop_trigger = (
            "USER_STOP_AND_ARCHIVE" if archive else "USER_NORMAL_STOP"
        )
        stop_reason = "用户请求停止并归档" if archive else "用户请求正常停止"
        operation, created = self.repository.create_active_operation_if_absent(
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
                "stop_trigger": stop_trigger,
                "stop_reason": stop_reason,
                "requested_by": "local_user",
                "request_id": request_id,
                "previous_state": str(run.get("state") or ""),
                "next_state": "STOPPING",
                "triggered_at": now,
                "started_at": now,
                "updated_at": now,
            },
            run_state="STOPPING",
            requested_action="stop_and_archive" if archive else "stop",
        )
        if not created:
            return GroundActionResponseDTO(
                state="STOPPING",
                run_id=run_id,
                operation_id=str(operation["operation_id"]),
                message=str(operation.get("message") or "停止请求正在处理"),
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

    def heartbeat_inventory_preview(self, site_id: str, *, action: str = "SYNC") -> GroundHeartbeatInventoryPreviewDTO:
        self._require_site(site_id)
        if action not in {"SYNC", "CLEAR_DEVICES", "CLEAR_DATA"}:
            raise GroundUnattendedError("HEARTBEAT_ACTION_INVALID", "无效的心跳管理操作")
        state = self.repository.heartbeat_inventory_state()
        history_counts = self.repository.heartbeat_history_counts()
        history_count = sum(history_counts.values())
        affected_history_count = (history_counts["ground_unattended_heartbeat_states"]
                                  + history_counts["heartbeat_events"]) if action == "CLEAR_DATA" else 0
        if action == "SYNC":
            if self.inventory_sync is None:
                raise GroundUnattendedError("INVENTORY_SYNC_UNAVAILABLE", "设备清单同步服务不可用", status_code=503)
            preview = self.inventory_sync.preview()
        else:
            inventory = self.repository.list_inventory(include_removed=False) if state["enabled"] else []
            device_count = sum(len(train.get("endpoints", [])) for train in inventory)
            preview = {
                "revision": hashlib.sha256(json.dumps(
                    {"state": state, "inventory": inventory, "history": history_counts},
                    sort_keys=True, ensure_ascii=False, default=str,
                ).encode("utf-8")).hexdigest(),
                "added_count": 0, "updated_count": 0,
                "disabled_count": device_count if action == "CLEAR_DEVICES" else 0,
                "device_count": device_count, "train_count": len(inventory),
                "conflict_count": 0, "conflicts": [],
            }
        # Bind confirmation to its exact operation, not merely the source
        # snapshot, so a SYNC preview cannot authorize a destructive action.
        preview["revision"] = hashlib.sha256(
            f"{action}:{preview['revision']}".encode("utf-8")
        ).hexdigest()
        return GroundHeartbeatInventoryPreviewDTO(
            site_id=site_id, action=action, **preview,
            monitoring_enabled=bool(state["enabled"]),
            retained_history_count=history_count - affected_history_count,
            affected_history_count=affected_history_count,
        )

    def heartbeat_inventory_apply(self, site_id: str, payload: GroundHeartbeatInventoryApplyDTO) -> GroundHeartbeatInventoryPreviewDTO:
        self._require_site(site_id)
        if not payload.confirm:
            raise GroundUnattendedError("HEARTBEAT_CONFIRM_REQUIRED", "请明确确认操作范围", status_code=409)
        state = self.repository.heartbeat_inventory_state()
        preview = self.heartbeat_inventory_preview(site_id, action=payload.action)
        if preview.revision != payload.revision:
            raise GroundUnattendedError("HEARTBEAT_PREVIEW_STALE", "设备或监测数据已变化，请重新预览", status_code=409)
        if payload.action == "SYNC" and preview.conflict_count:
            raise GroundUnattendedError("HEARTBEAT_INVENTORY_CONFLICT", "设备身份或端别存在冲突，请先修复设备资料", status_code=409)
        try:
            if payload.action == "SYNC":
                self.sync_inventory(site_id, heartbeat_revision=int(state["revision"]),
                                    heartbeat_preview_revision=payload.revision)
            else:
                self.repository.apply_heartbeat_inventory_action(payload.action, expected_revision=int(state["revision"]))
        except ValueError as exc:
            raise GroundUnattendedError(str(exc).split(":")[0], "监测运行中或预览已过期，请停止监测后重新预览", status_code=409) from exc
        self.repository.add_event(
            event_type="heartbeat_inventory_managed", title="心跳监测管理操作",
            message=payload.action, details=preview.model_dump(mode="json"),
        )
        return preview.model_copy(update={"applied": True, "monitoring_enabled": bool(self.repository.heartbeat_inventory_state()["enabled"])})

    def sync_inventory(self, site_id: str, *, heartbeat_revision: int | None = None,
                       heartbeat_preview_revision: str = "") -> GroundInventorySummaryDTO:
        self._require_site(site_id)
        if self.inventory_sync is None:
            raise GroundUnattendedError(
                "INVENTORY_SYNC_UNAVAILABLE", "设备清单同步服务不可用", status_code=503
            )
        try:
            result = (self.inventory_sync.synchronize(heartbeat_revision=heartbeat_revision,
                                                      preview_revision=heartbeat_preview_revision)
                      if heartbeat_revision is not None else self.inventory_sync.synchronize())
        except ValueError as exc:
            code = str(exc).split(":")[0]
            raise GroundUnattendedError(code, str(exc), status_code=409) from exc
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
            # This endpoint is an explicit operator action.  The profile flag
            # gates only unattended boot checks; a manual repair request keeps
            # its existing meaning and is still recorded by the audit service.
            repair_enabled=mode == "AUTO_REPAIR",
            allow_target_port_change=allow_target_port_change,
        )
        return GroundActionResponseDTO(
            state=str(run["state"]),
            run_id=str(run["run_id"]),
            message="MR 配置检查请求已提交",
        )

    def request_syslog_control(
        self,
        site_id: str,
        payload: GroundSyslogControlRequestDTO,
    ) -> GroundActionResponseDTO:
        run = self._active(site_id)
        profile = self.repository.get_profile()
        self._validate_network_profile(profile, require_syslog=True)
        requested = list(dict.fromkeys(str(item).strip() for item in payload.device_uuids if str(item).strip()))
        if not requested:
            raise GroundUnattendedError("MR_REQUIRED", "至少选择一台 MR", status_code=422)
        inventory = {str(row.get("device_uuid") or ""): row for row in self.repository.list_inventory() for row in row.get("endpoints", [])}
        selected: list[str] = []
        address_owners: dict[str, str] = {}
        for endpoint in inventory.values():
            owner = str(endpoint.get("device_uuid") or "")
            for field in ("management_ip", "backup_management_ip"):
                raw_ip = str(endpoint.get(field) or "").strip()
                if not raw_ip:
                    continue
                try:
                    normalized_ip = str(ipaddress.ip_address(raw_ip))
                except ValueError:
                    continue
                previous_owner = address_owners.setdefault(normalized_ip, owner)
                if previous_owner != owner:
                    address_owners[normalized_ip] = "<conflict>"
        for device_uuid in requested:
            endpoint = inventory.get(device_uuid)
            if endpoint is None:
                raise GroundUnattendedError("MR_NOT_FOUND", f"MR 不在当前无人值守清单中: {device_uuid}", status_code=404)
            if payload.mode == "JOIN":
                live = next((row for row in self.supervisor.fleet_ping.target_summaries() if str(row.get("mr_id") or "") == device_uuid), None)
                if not live or str(live.get("status") or "").upper() != "ONLINE":
                    raise GroundUnattendedError("MR_NOT_ONLINE", f"MR 当前不在线，不能加入 Syslog: {device_uuid}", status_code=409)
                if not str(endpoint.get("management_ip") or "").strip():
                    raise GroundUnattendedError("MR_MANAGEMENT_IP_MISSING", f"MR 没有有效管理地址: {device_uuid}", status_code=409)
                for field in ("management_ip", "backup_management_ip"):
                    raw_ip = str(endpoint.get(field) or "").strip()
                    if not raw_ip:
                        continue
                    try:
                        normalized_ip = str(ipaddress.ip_address(raw_ip))
                    except ValueError as exc:
                        raise GroundUnattendedError("MR_MANAGEMENT_IP_INVALID", f"MR 管理地址无效: {device_uuid}", status_code=409) from exc
                    if address_owners.get(normalized_ip) == "<conflict>":
                        raise GroundUnattendedError("MR_MANAGEMENT_IP_CONFLICT", f"MR 主备地址与其他 MR 冲突: {device_uuid}", status_code=409)
            selected.append(device_uuid)
        task_id = f"ground-syslog-{uuid.uuid4().hex}"
        if self.task_service is not None:
            self.task_service.create_external_task(
                task_id=task_id,
                task_type="ground_unattended_syslog_control",
                task_name=f"MR Syslog {'加入' if payload.mode == 'JOIN' else '退出'}",
                source="local",
                site_name=site_id,
                owner="ground_unattended",
                device=str(len(selected)),
            )
            self.task_service.record_external_event(
                task_id,
                "state",
                {
                    "state": "RUNNING",
                    "current": 0,
                    "total": len(selected),
                    "stage": f"SYSLOG_{payload.mode}",
                    "message": "Syslog 批次任务已开始",
                },
                site_name=site_id,
                source="ground_unattended",
            )
            self.task_service.record_external_event(
                task_id,
                "progress",
                {
                    "event": "BATCH_DEVICES",
                    "operation": payload.mode,
                    "device_uuids": list(selected),
                },
                site_name=site_id,
                source="ground_unattended",
            )
        register_task = getattr(self.supervisor, "register_syslog_task", None)
        if callable(register_task):
            register_for_devices = getattr(
                self.supervisor, "register_syslog_task_for_devices", None
            )
            if callable(register_for_devices):
                register_for_devices(task_id, len(selected), selected)
            else:
                register_task(task_id, len(selected))
        if payload.mode == "JOIN":
            for device_uuid in selected:
                if self.task_service is not None:
                    self.task_service.record_external_event(
                        task_id,
                        "progress",
                        {
                            "event": "DEVICE_QUEUED",
                            "device_uuid": device_uuid,
                            "operation": "JOIN",
                            "status": "QUEUED",
                        },
                        site_name=site_id,
                        source="ground_unattended",
                    )
                try:
                    self.supervisor.request_config_check(
                        device_uuid, repair_enabled=True, task_id=task_id
                    )
                except TypeError as exc:
                    if "task_id" not in str(exc):
                        raise
                    self.supervisor.request_config_check(device_uuid, repair_enabled=True)
            message = f"已提交 {len(selected)} 台 MR 加入 Syslog 上报"
        else:
            for device_uuid in selected:
                if self.task_service is not None:
                    self.task_service.record_external_event(
                        task_id,
                        "progress",
                        {
                            "event": "DEVICE_QUEUED",
                            "device_uuid": device_uuid,
                            "operation": "EXIT",
                            "status": "QUEUED",
                        },
                        site_name=site_id,
                        source="ground_unattended",
                    )
                try:
                    self.supervisor.request_syslog_exit(device_uuid, task_id=task_id)
                except TypeError as exc:
                    if "task_id" not in str(exc):
                        raise
                    self.supervisor.request_syslog_exit(device_uuid)
            message = f"已提交 {len(selected)} 台 MR 退出 Syslog 上报"
        return GroundActionResponseDTO(
            state=str(run["state"]), run_id=str(run["run_id"]), task_id=task_id,
            message=message,
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
        current_error = str(values.pop("last_error", "") or "") or str(
            getattr(self.supervisor, "_heartbeat_event_error", "") or ""
        )
        last_error = current_error or (
            str(latest.get("message") or "")
            if str(latest.get("severity") or "").lower() in {"error", "critical"}
            else ""
        )
        values.pop("disk_free_bytes", None)
        run = self.repository.get_active_run()
        ac_pollers = self._ac_poller_health(
            site_id, str((run or {}).get("run_id") or "")
        )
        now = datetime.now().astimezone()
        fleet = self.supervisor.fleet_ping
        supervisor_running = getattr(self.supervisor, "running", None)
        run_state = str((run or {}).get("state") or "")
        run_age = self._age_seconds((run or {}).get("actual_started_at"), now)
        target_count = int(getattr(fleet, "target_count", 0))
        process_count = int(getattr(fleet, "process_count", 0))
        worker_warnings = list(getattr(fleet, "worker_warnings", []))
        scheduler = getattr(self.supervisor, "task_scheduler", None)
        scheduler_values = scheduler.snapshot() if scheduler is not None else {}
        archive_failed = sum(row.get("archive_status") == "FAILED" for row in archives)
        startup_grace = max(
            10.0, self.repository.get_profile().fleet_ping_timeout_ms / 1000.0 * 2.0
        )
        core_stopped = run_state == "RUNNING" and (
            supervisor_running is False
            or (
                run_age is not None
                and run_age > startup_grace
                and (
                    (target_count > 0 and process_count == 0)
                    or not values.get("udp_running")
                )
            )
        )
        pipeline_stopped = values.get("udp_running") and any(
            values.get(name) is False
            for name in ("receiver_alive", "writer_alive", "parser_alive")
        )
        critical = (
            core_stopped
            or pipeline_stopped
            or run_state == "ERROR"
            or values.get("raw_write_failed_count")
            or values.get("udp_dropped_count")
            or values.get("dropped")
            or values.get("spool_guard_state") in {"CRITICAL", "EMERGENCY"}
        )
        degraded = (
            current_error
            or worker_warnings
            or archive_failed
            or values.get("compression_failed_count")
            or values.get("compression_skipped_count")
            or values.get("spool_guard_state") == "WARNING"
            or float(values.get("udp_queue_pressure") or 0) >= 0.8
            or any(item.status in {"DEGRADED", "CRITICAL"} for item in ac_pollers)
            or getattr(self.supervisor, "_tick_consecutive_failure_count", 0)
        )
        observed = (
            supervisor_running is True
            or values.get("udp_running")
            or process_count > 0
            or any(item.status == "HEALTHY" for item in ac_pollers)
        )
        status = (
            "CRITICAL" if critical else "DEGRADED" if degraded
            else "HEALTHY" if observed else "UNKNOWN"
        )
        return GroundHealthDTO(
            site_id=site_id,
            status=status,
            **values,
            supervisor_running=supervisor_running,
            run_state=run_state,
            run_elapsed_seconds=run_age,
            ping_target_count=target_count,
            ping_process_count=process_count,
            ping_sample_rate_per_second=getattr(fleet, "sample_rate_per_second", None),
            ping_last_sample_at=str(getattr(fleet, "last_sample_at", "")),
            ping_sample_write_duration_ms=getattr(fleet, "last_sample_write_duration_ms", None),
            ping_worker_warnings=worker_warnings,
            deep_queue_length=deep_queue,
            archive_pending_count=sum(
                row.get("archive_status") in {"PENDING", "BUILDING"}
                for row in archives
            ),
            ac_pollers=ac_pollers,
            archive_failed_count=archive_failed,
            disk_free_bytes=int(disk.free),
            disk_total_bytes=int(disk.total),
            raw_file_count=self.repository.count_raw_files(),
            last_error=last_error,
            updated_at=datetime.now().astimezone().isoformat(timespec="milliseconds"),
            task_queue_lengths=dict(scheduler_values.get("queue_lengths") or {}),
            active_task_count=int(scheduler_values.get("active_tasks") or 0),
            completed_task_count=int(scheduler_values.get("completed_tasks") or 0),
            failed_task_count=int(scheduler_values.get("failed_tasks") or 0),
            cancelled_task_count=int(scheduler_values.get("cancelled_tasks") or 0),
            scheduler_worker_count=int(scheduler_values.get("worker_count") or 0),
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
                status = "CRITICAL"
            elif (
                success_age is not None
                and success_age > profile.ac_stale_grace_seconds
            ):
                status = "DEGRADED"
            elif connection_state in {"RECONNECTING", "BACKOFF", "CONNECTING"}:
                status = "DEGRADED"
            elif heartbeat_age is None or heartbeat_age > max(
                5.0,
                float(row.get("poll_interval_seconds") or 0) + 2.0,
            ):
                status = "DEGRADED"
            elif connection_state in {"CONNECTED", "POLLING", "WAITING"}:
                status = "HEALTHY"
            else:
                status = "UNKNOWN"
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
                    last_success_age_seconds=success_age,
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
            items=[
                GroundRawFileDTO.model_validate(
                    project_row_for_model(row, GroundRawFileDTO)
                )
                for row in rows
            ],
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
            result["ap_transitions"] = self._project_ping_transitions(
                list(result.get("ap_transitions") or [])
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
            result["ap_transitions"] = self._project_ping_transitions(
                list(result.get("ap_transitions") or [])
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

    def _project_ping_transitions(
        self,
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not rows:
            return []
        parsed_rows = [
            {
                "event_type": "MESH_ACTIVELINK_SWITCH",
                "peer_name": row.get("new_ap_name") or "",
                "peer_mac": row.get("new_ap_raw") or "",
                "previous_peer_name": row.get("old_ap_name") or "",
                "previous_peer_mac": row.get("old_ap_raw") or "",
                "details": {
                    "new_peer_mac": row.get("new_ap_raw") or "",
                    "new_peer_radio_mac": row.get("new_ap_radio_mac") or "",
                    "old_peer_mac": row.get("old_ap_raw") or "",
                    "old_peer_radio_mac": row.get("old_ap_radio_mac") or "",
                },
            }
            for row in rows
        ]
        # Bind every old/new peer in this chart query to one Identity batch.
        # A request-scoped resolver avoids a second lookup if the shared
        # realtime cache happens to cross a revision boundary.
        resolver = GroundApDisplayResolver(self.ap_identity_query_service)
        resolver.preload_parsed(parsed_rows)
        return [
            resolver.project_switch(parsed, base=row)
            for row, parsed in zip(rows, parsed_rows, strict=True)
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
            day_start = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
            result["statistics"] = self.repository.syslog_ui_statistics(
                run_id=str(filters.get("run_id") or ""),
                day_start=day_start.isoformat(),
                day_end=(day_start + timedelta(days=1)).isoformat(),
            )
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

    def deep_tasks(self, site_id: str, *, run_id: str = "", **filters: Any) -> GroundDeepTaskPageDTO:
        self._require_site(site_id)
        for field in ("start_at", "end_at"):
            value = str(filters.get(field) or "")
            if value:
                parsed = self._parse_datetime(value)
                if parsed is None:
                    raise GroundUnattendedError("INVALID_TIME_RANGE", "时间范围必须为有效 ISO 时间")
                filters[field] = parsed.isoformat()
        if filters.get("start_at") and filters.get("end_at") and datetime.fromisoformat(filters["start_at"]).timestamp() > datetime.fromisoformat(filters["end_at"]).timestamp():
            raise GroundUnattendedError("INVALID_TIME_RANGE", "开始时间不能晚于结束时间")
        run = self._resolve_run(run_id)
        if not run:
            return GroundDeepTaskPageDTO()
        resolved_run_id = str(run["run_id"])
        result = self.repository.deep_task_page(run_id=resolved_run_id, **filters)
        trains = {str(row["train_id"]): row for row in self.repository.list_train_runs(resolved_run_id)}
        query = self._deep_query_service()
        cache: dict[str, tuple[object | None, list[object], dict[str, Any], str]] = {}
        items = []
        for operation in result["items"]:
            train = trains.get(str(operation["train_id"]), {"train_id": operation["train_id"]})
            endpoint = next((item for item in train.get("endpoints", []) if str(item.get("mr_id") or "") == str(operation["mr_id"])), None)
            if endpoint is None:
                endpoint = next((item for item in train.get("endpoints", []) if item.get("endpoint") == operation["mr_position_code"]), {})
            items.append(self._project_deep_collector(run_id=resolved_run_id, train=train, operation=operation, endpoint=endpoint, query=query, session_cache=cache))
        result["statistics"]["scope"] = "SELECTED_RUN_ALL_TASKS"
        return GroundDeepTaskPageDTO(items=items, total=result["total"], page=filters.get("page", 1), page_size=filters.get("page_size", 50), statistics=result["statistics"])

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
        session_cache: dict[
            str, tuple[object | None, list[object], dict[str, Any], str]
        ] = {}
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
        operation_id: str = "",
        category: str = "ALL",
        keyword: str = "",
        cursor: str = "",
        limit: int = 200,
    ) -> GroundDeepCollectionRecordPageDTO:
        """Read a bounded increment of the existing Online MR raw logs."""

        self._require_site(site_id)
        collections = self.deep_collections(site_id, run_id=run_id).items if not operation_id else []
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
        if operation_id:
            operation = self.repository.get_deep_operation(operation_id)
            run = self._resolve_run(run_id)
            if operation and run and str(operation["run_id"]) == str(run["run_id"]) and (not train_id or operation["train_id"] == train_id) and (not mr_id or operation["mr_id"] == mr_id) and (not mr_role or operation["mr_position_code"].upper() == mr_role.upper()):
                train = next((row for row in self.repository.list_train_runs(str(run["run_id"])) if row["train_id"] == operation["train_id"]), {"train_id": operation["train_id"]})
                endpoint = next((row for row in train.get("endpoints", []) if row.get("endpoint") == operation["mr_position_code"]), {})
                selected = self._project_deep_collector(run_id=str(run["run_id"]), train=train, operation=operation, endpoint=endpoint, query=self._deep_query_service(), session_cache={})
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
        normalized_keyword = keyword.strip().casefold()
        if cursor and (
            cursor_state.get("category") != category_key
            or cursor_state.get("keyword") != normalized_keyword
        ):
            raise GroundUnattendedError(
                "DEEP_RECORD_CURSOR_FILTER_MISMATCH",
                "深采记录游标与当前筛选条件不匹配",
                status_code=409,
            )
        offsets = {
            str(key): max(0, int(value))
            for key, value in dict(cursor_state.get("offsets") or {}).items()
        }
        page_limit = max(1, min(500, int(limit)))
        chunk_limit = max(50, min(500, page_limit * 2))
        candidates: list[
            tuple[str, GroundDeepCollectionRecordDTO, int]
        ] = []
        candidates_by_source: dict[
            str, list[tuple[str, GroundDeepCollectionRecordDTO, int]]
        ] = {}
        scan_end_by_source: dict[str, int] = {}
        source_has_more: dict[str, bool] = {}
        for source in sources:
            source_candidates: list[
                tuple[str, GroundDeepCollectionRecordDTO, int]
            ] = []
            next_offset = offsets.get(source, 0)
            scanned = 0
            try:
                while len(source_candidates) < page_limit:
                    chunk = query.read_log_chunk(
                        self.site_id,
                        selected.collector_session_id,
                        source,
                        cursor=next_offset,
                        limit=chunk_limit,
                    )
                    next_offset = chunk.next_cursor
                    scanned += len(chunk.lines)
                    for index, line in enumerate(chunk.lines):
                        categories = _deep_record_categories(source, line.text)
                        included = (
                            category_key in {"ALL", "RAW_OUTPUT"}
                            or category_key in categories
                        )
                        if not included or (
                            normalized_keyword
                            and normalized_keyword not in line.text.casefold()
                        ):
                            continue
                        after_cursor = (
                            int(chunk.lines[index + 1].sequence)
                            if index + 1 < len(chunk.lines)
                            else int(chunk.next_cursor)
                        )
                        primary_category = (
                            category_key
                            if category_key not in {"ALL", "RAW_OUTPUT"}
                            else _deep_primary_category(categories)
                            if category_key == "ALL"
                            else "RAW_OUTPUT"
                        )
                        source_candidates.append(
                            (
                                source,
                                GroundDeepCollectionRecordDTO(
                                    sequence=line.sequence,
                                    timestamp=line.timestamp or "",
                                    category=primary_category,
                                    source=source,
                                    text=line.text,
                                ),
                                after_cursor,
                            )
                        )
                    if not chunk.has_more or not chunk.lines or scanned >= 50_000:
                        break
            except OnlineMrQueryError:
                continue
            candidates.extend(source_candidates)
            candidates_by_source[source] = source_candidates
            scan_end_by_source[source] = next_offset
            source_has_more[source] = bool(chunk.has_more) or scanned >= 50_000
        candidates.sort(
            key=lambda item: (
                item[1].timestamp or "9999",
                item[0],
                item[1].sequence,
            )
        )
        returned = candidates[:page_limit]
        returned_keys = {
            (source, row.sequence) for source, row, _after_cursor in returned
        }
        has_more = False
        for source in sources:
            pending = [
                item
                for item in candidates_by_source.get(source, [])
                if (item[0], item[1].sequence) not in returned_keys
            ]
            if pending:
                offsets[source] = pending[0][1].sequence
                has_more = True
            elif source in scan_end_by_source:
                offsets[source] = scan_end_by_source[source]
                has_more = has_more or source_has_more.get(source, False)
        return GroundDeepCollectionRecordPageDTO(
            collector=selected,
            records=[row for _source, row, _after_cursor in returned],
            next_cursor=_encode_deep_cursor(
                {
                    "v": 2,
                    "session_id": selected.collector_session_id,
                    "category": category_key,
                    "keyword": normalized_keyword,
                    "offsets": offsets,
                }
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
        session_cache: dict[
            str, tuple[object | None, list[object], dict[str, Any], str]
        ],
    ) -> GroundDeepCollectorDTO:
        operation = operation or {}
        session_id = str(operation.get("session_id") or "")
        state, reason = _deep_operation_state(operation, train)
        bytes_written = 0
        last_record_at = ""
        session_error = ""
        fping_view: dict[str, Any] = {}
        fping_row = None
        collector_items: list[dict[str, Any]] = []
        session_host = ""
        if session_id and query is not None:
            cached = session_cache.get(session_id)
            if cached is None:
                try:
                    detail = query.get_session(self.site_id, session_id)
                    status_rows = query.list_collectors(self.site_id, session_id)
                    preview_getter = getattr(query, "get_realtime_preview", None)
                    preview = (
                        preview_getter(self.site_id, session_id)
                        if callable(preview_getter)
                        else None
                    )
                    fping_view = dict(getattr(preview, "fping", {}) or {})
                    if not fping_view:
                        fping_view = dict(
                            (getattr(detail, "traffic_summary", {}) or {}).get(
                                "fping"
                            )
                            or {}
                        )
                    cached = (detail, status_rows, fping_view, "")
                except OnlineMrQueryError as exc:
                    cached = (None, [], {}, str(exc))
                session_cache[session_id] = cached
            detail, status_rows, fping_view, session_error = cached
            session_host = str((getattr(detail, "connection_summary", {}) or {}).get("host") or "")
            for status in status_rows:
                if getattr(status, "enabled", False):
                    collector_items.append({
                        "name": str(getattr(status, "name", "") or ""),
                        "label": str(getattr(status, "label", "") or ""),
                        "status": str(getattr(status, "status", "") or "unknown"),
                        "size_bytes": int(getattr(status, "size_bytes", 0) or 0),
                        "started_at": str(getattr(status, "started_at", "") or ""),
                        "ended_at": str(getattr(status, "ended_at", "") or ""),
                        "updated_at": str(getattr(status, "updated_at", "") or ""),
                        "error": str(getattr(status, "last_error", "") or getattr(status, "error", "") or ""),
                        "raw_file": str(getattr(status, "raw_file", "") or ""),
                        "exists": bool(getattr(status, "exists", False)),
                    })
                bytes_written += int(getattr(status, "size_bytes", 0) or 0)
                updated_at = str(getattr(status, "updated_at", "") or "")
                if updated_at > last_record_at:
                    last_record_at = updated_at
                if getattr(status, "name", "") == "fping_v5":
                    fping_row = status
            # Online MR may report an operation as RUNNING immediately after the
            # session is created.  The ground-unattended view must not present
            # that as a deep collector that is already producing evidence.
            if state == "RUNNING" and bytes_written <= 0:
                state, reason = "STARTING", "Online MR 会话已建立，等待 Collector 写入原始数据"
            elif bytes_written > 0 and state == "STARTING":
                state, reason = "RUNNING", "Collector 已写入原始数据"
            elif session_error and state in {"STARTING", "RUNNING"}:
                reason = f"{reason}；会话状态暂不可读"
            if detail is not None:
                session_status = str(getattr(detail, "status", "") or "").upper()
                if session_status in {"FAILED", "ERROR"}:
                    state, reason = "FAILED", str(
                        getattr(detail, "error_message", "") or "Online MR 会话失败"
                    )
        fping_summary = dict(fping_view.get("summary") or {})
        fping_config = dict(fping_view.get("config") or {})
        fping_latest = dict(fping_view.get("latest") or {})
        fping_status = str(
            fping_view.get("status")
            or getattr(fping_row, "status", "")
            or "missing"
        ).lower()
        fping_samples = int(fping_summary.get("sent_count") or 0)
        fping_error = str(
            fping_view.get("error")
            or getattr(fping_row, "last_error", "")
            or getattr(fping_row, "error", "")
            or ""
        )
        if fping_status in {"failed", "error", "missing"}:
            integrity_status = "INCOMPLETE"
        elif fping_samples > 0:
            integrity_status = "COMPLETE"
        else:
            integrity_status = "UNKNOWN"
        if state == "RUNNING" and integrity_status == "INCOMPLETE":
            reason = f"{reason}；fping {fping_status}，Ping 数据完整性不完整"
        return GroundDeepCollectorDTO(
            run_id=run_id,
            train_id=str(train.get("train_id") or ""),
            mr_id=str(operation.get("mr_id") or endpoint.get("mr_id") or ""),
            mr_role=str(operation.get("mr_position_code") or endpoint.get("endpoint") or ""),
            management_ip=session_host or str(endpoint.get("management_ip") or ""),
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
            fping_status=fping_status,
            fping_target_ip=str(
                fping_view.get("target")
                or fping_config.get("target")
                or endpoint.get("management_ip")
                or ""
            ),
            fping_started_at=str(getattr(fping_row, "started_at", "") or ""),
            fping_last_data_at=str(
                fping_latest.get("ts")
                or getattr(fping_row, "last_data_at", "")
                or fping_view.get("updated_at")
                or ""
            ),
            fping_sample_count=fping_samples,
            fping_interval_ms=int(fping_config.get("interval_ms") or 0),
            fping_timeout_ms=int(
                fping_config.get("timeout_ms")
                or fping_config.get("loss_threshold_ms")
                or 0
            ),
            fping_packet_size=int(fping_config.get("packet_size") or 0),
            fping_loss_percent=fping_summary.get("loss_rate_percent"),
            fping_avg_latency_ms=fping_summary.get("avg_rtt_ms"),
            fping_latest_latency_ms=fping_latest.get("rtt_ms"),
            fping_error=fping_error,
            data_integrity_status=integrity_status,
            items=collector_items,
            source_state=str(operation.get("state") or ""),
            train_no=str(train.get("train_no") or ""),
            ended_at=str(operation.get("ended_at") or ""),
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
        mr_id: str = "",
        mr_role: str = "",
        start_at: str = "",
        end_at: str = "",
        run_id: str = "",
        page: int = 1,
        page_size: int = 100,
    ) -> GroundTimelinePageDTO:
        self._require_site(site_id)
        filter_mr_id = mr_id
        parsed_start = self._parse_datetime(start_at) if start_at else None
        parsed_end = self._parse_datetime(end_at) if end_at else None
        if (start_at and parsed_start is None) or (end_at and parsed_end is None):
            raise GroundUnattendedError("INVALID_TIME_RANGE", "时间范围必须为有效 ISO 时间")
        if parsed_start and parsed_end and parsed_start.timestamp() > parsed_end.timestamp():
            raise GroundUnattendedError("INVALID_TIME_RANGE", "开始时间不能晚于结束时间")
        start_at = parsed_start.isoformat() if parsed_start else ""
        end_at = parsed_end.isoformat() if parsed_end else ""
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
                mr_id=filter_mr_id,
                mr_role=mr_role,
                start_at=start_at,
                end_at=end_at,
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
        # A page query uses one resolver so every old/new endpoint is loaded
        # in one batch and projected against one Identity revision.
        resolver = GroundApDisplayResolver(self.ap_identity_query_service)
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
            message = str(row.get("message") or "")
            event_kind = str(row.get("event_type") or "").casefold()
            if event_kind == "mesh_activelink_switch":
                switch = resolver.project_switch(parsed)
                details = dict(switch.get("details") or details)
                current_name = str(switch.get("new_ap_name") or "")
                previous_name = str(switch.get("old_ap_name") or "")
                current_mac = str(switch.get("new_ap_raw") or "")
                current_station = str(switch.get("new_station") or "")
                current_section = str(switch.get("new_section") or "")
                previous_station = str(switch.get("old_station") or "")
                previous_section = str(switch.get("old_section") or "")
                previous_display = (
                    previous_name
                    or str(switch.get("old_ap_raw") or "")
                    or str(switch.get("old_ap_radio_mac") or "")
                    or "未知 AP"
                )
                current_display = (
                    current_name
                    or current_mac
                    or str(switch.get("new_ap_radio_mac") or "")
                    or "未知 AP"
                )
                raw_previous = (
                    str(switch.get("old_ap_raw") or "")
                    or str(switch.get("old_ap_radio_mac") or "")
                    or previous_display
                )
                raw_current = (
                    current_mac
                    or str(switch.get("new_ap_radio_mac") or "")
                    or current_display
                )
                raw_transition = f"{raw_previous} → {raw_current}"
                resolved_transition = f"{previous_display} → {current_display}"
                message_parts = [raw_transition]
                if resolved_transition != raw_transition:
                    message_parts.append(resolved_transition)
                if previous_station or current_station:
                    message_parts.append(
                        f"{previous_station or '站点未知'} → "
                        f"{current_station or '站点未知'}"
                    )
                message = " · ".join(message_parts)
            else:
                switch = {}
                ap_display = resolver.enrich_parsed(parsed)
                details = dict(ap_display.get("details") or details)
                current_name = str(ap_display.get("peer_name") or "")
                previous_name = str(ap_display.get("previous_peer_name") or "")
                current_mac = str(ap_display.get("peer_mac") or "")
                current_station = str(ap_display.get("station") or "")
                current_section = str(ap_display.get("section") or "")
                previous_station = str(details.get("previous_station") or "")
                previous_section = str(details.get("previous_section") or "")
                previous_display = previous_name or "未知 AP"
                current_display = current_name or "未知 AP"
            if event_kind in {"mesh_linkup", "mesh_linkdown"}:
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
            elif (
                event_kind != "mesh_activelink_switch"
                and not message
                and current_name
            ):
                message = current_name
            items.append(
                GroundTimelineEventDTO(
                    event_id=row["id"],
                    ts=row["ts"],
                    event_at=row["ts"],
                    run_date=str(run.get("run_date") or ""),
                    source=str(details.get("source") or details.get("event_source") or ""),
                    device_time=str(details.get("device_time") or ""),
                    received_at=str(details.get("received_at") or details.get("receive_time") or ""),
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
                        or details.get("mr_role")
                        or endpoint.get("mr_role")
                        or ""
                    ),
                    title=row["title"],
                    message=message,
                    peer_ap_id=str(
                        switch.get("new_ap_id") or details.get("peer_ap_id") or ""
                    ),
                    peer_ap_name=current_name,
                    peer_ap_mac=str(
                        switch.get("new_ap_mac")
                        or details.get("peer_ap_mac")
                        or ""
                    ),
                    peer_radio_mac=str(
                        switch.get("new_ap_radio_mac")
                        or details.get("peer_radio_mac")
                        or ""
                    ),
                    previous_peer_ap_id=str(
                        switch.get("old_ap_id")
                        or details.get("previous_peer_ap_id")
                        or ""
                    ),
                    previous_peer_ap_name=previous_name,
                    previous_peer_ap_mac=str(
                        switch.get("old_ap_mac")
                        or details.get("previous_peer_ap_mac")
                        or ""
                    ),
                    previous_peer_radio_mac=str(
                        switch.get("old_ap_radio_mac")
                        or details.get("previous_peer_radio_mac")
                        or ""
                    ),
                    station=current_station,
                    section=current_section,
                    previous_station=previous_station,
                    previous_section=previous_section,
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
                        switch.get("identity_status")
                        or details.get("resolution_status")
                        or ""
                    ),
                    ap_display=current_name,
                    ap_transition_display=(
                        f"{previous_display} → {current_display}"
                        if str(row.get("event_type") or "").casefold()
                        == "mesh_activelink_switch"
                        else current_name
                    ),
                    resolved_ap_name=current_name,
                    previous_resolved_ap_name=previous_name,
                    old_ap_raw=str(switch.get("old_ap_raw") or ""),
                    new_ap_raw=str(switch.get("new_ap_raw") or ""),
                    old_ap_identity_status=str(
                        switch.get("old_ap_identity_status") or ""
                    ),
                    new_ap_identity_status=str(
                        switch.get("new_ap_identity_status") or ""
                    ),
                    old_match_source=str(switch.get("old_match_source") or ""),
                    new_match_source=str(switch.get("new_match_source") or ""),
                    old_match_rule=str(switch.get("old_match_rule") or ""),
                    new_match_rule=str(switch.get("new_match_rule") or ""),
                    old_identity_reason=str(
                        switch.get("old_identity_reason") or ""
                    ),
                    new_identity_reason=str(
                        switch.get("new_identity_reason") or ""
                    ),
                    identity_status=str(switch.get("identity_status") or ""),
                    identity_source=str(switch.get("identity_source") or ""),
                    identity_revision=int(
                        switch.get("identity_revision") or 0
                    ),
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
                mr_id=filter_mr_id,
                mr_role=mr_role,
                start_at=start_at,
                end_at=end_at,
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
        return GroundOperationDTO.model_validate(
            project_row_for_model(row, GroundOperationDTO)
        )

    def latest_operation(self, site_id: str) -> GroundOperationDTO | None:
        self._require_site(site_id)
        row = self.repository.latest_terminal_operation()
        return (
            GroundOperationDTO.model_validate(
                project_row_for_model(row, GroundOperationDTO)
            )
            if row
            else None
        )

    def active_operation(self, site_id: str) -> GroundOperationDTO | None:
        self._require_site(site_id)
        active_run = self.repository.get_active_run()
        if active_run is None:
            return None
        row = self.repository.latest_operation(
            run_id=str(active_run["run_id"]), active_only=True
        )
        return (
            GroundOperationDTO.model_validate(
                project_row_for_model(row, GroundOperationDTO)
            )
            if row
            else None
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

    def request_delete_archives(
        self, site_id: str, payload: GroundArchiveBatchDeleteRequestDTO
    ) -> GroundArchiveBatchDeleteResponseDTO:
        self._require_site(site_id)
        if not payload.explicit_confirmation:
            raise GroundUnattendedError(
                "CONFIRMATION_REQUIRED", "批量删除归档需要明确确认", status_code=409
            )
        results: list[GroundArchiveBatchDeleteItemDTO] = []
        for archive_id in dict.fromkeys(str(value).strip() for value in payload.archive_ids if str(value).strip()):
            try:
                result = self.request_delete_archive(site_id, archive_id, confirmed=True)
                results.append(GroundArchiveBatchDeleteItemDTO(
                    archive_id=archive_id, accepted=result.accepted,
                    state=result.state, run_id=result.run_id,
                    operation_id=result.operation_id, message=result.message,
                ))
            except GroundUnattendedError as exc:
                results.append(GroundArchiveBatchDeleteItemDTO(
                    archive_id=archive_id, accepted=False,
                    state="FAILED", message=exc.message,
                ))
        accepted = sum(1 for item in results if item.accepted)
        return GroundArchiveBatchDeleteResponseDTO(
            accepted_count=accepted,
            failed_count=len(results) - accepted,
            results=results,
        )

    def _train_dto(self, row: dict[str, Any]) -> GroundUnattendedTrainDTO:
        return GroundUnattendedTrainDTO(
            train_id=row["train_id"],
            train_no=row.get("train_no", ""),
            train_name=row.get("train_name", ""),
            location_class=row.get("location_class", "UNKNOWN"),
            location_class_source=row.get(
                "location_class_source", "UNDETERMINED"
            ),
            participates_in_mainline=bool(
                row.get("participates_in_mainline")
            ),
            mainline_eligible=bool(row.get("mainline_eligible")),
            mainline_reason_code=row.get(
                "mainline_reason_code", "NOT_EVALUATED"
            ),
            mainline_reason_text=row.get(
                "mainline_reason_text", "未评估"
            ),
            ping_eligible=bool(row.get("ping_eligible")),
            ping_reason_code=row.get("ping_reason_code", "NOT_EVALUATED"),
            ping_reason_text=row.get("ping_reason_text", "未评估"),
            deep_collection_eligible=bool(row.get("deep_collection_eligible")),
            deep_collection_reason_code=row.get(
                "deep_collection_reason_code", "NOT_EVALUATED"
            ),
            deep_collection_reason_text=row.get(
                "deep_collection_reason_text", "未评估"
            ),
            decision_revision=int(row.get("decision_revision") or 0),
            decision_source=row.get("decision_source", "NOT_EVALUATED"),
            ping_inclusion_reason=row.get("ping_inclusion_reason", ""),
            ping_exclusion_reason=row.get("ping_exclusion_reason", ""),
            deep_exclusion_reason=row.get("deep_exclusion_reason", ""),
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
        endpoint_snapshot = self.repository.train_endpoint_snapshot(
            (
                endpoint.mr_id
                for train in trains
                for endpoint in train.endpoints
                if endpoint.mr_id
            ),
            run_id=run_id,
        )
        boot_by_device = dict(endpoint_snapshot["boot_by_device"])
        wmesh_by_device = dict(endpoint_snapshot["wmesh_by_device"])
        runtime_by_device = dict(endpoint_snapshot["runtime_by_device"])
        radio_by_device = dict(endpoint_snapshot["radio_by_device"])
        audit_by_device = dict(endpoint_snapshot["audit_by_device"])
        result = []
        now = datetime.now().astimezone()
        for train in trains:
            endpoints = []
            for endpoint in train.endpoints:
                mr_key = (train.train_id, f"mr:{endpoint.mr_id}")
                end_key = (train.train_id, f"end:{endpoint.endpoint}")
                summary = summaries.get(mr_key) or summaries.get(end_key) or {}
                operation = operations.get((train.train_id, endpoint.endpoint)) or {}
                boot = boot_by_device.get(endpoint.mr_id)
                wmesh = wmesh_by_device.get(endpoint.mr_id)
                radio_runtime = runtime_by_device.get(endpoint.mr_id)
                radio_interfaces = (
                    [
                        _radio_interface_projection(item)
                        for item in radio_by_device.get(endpoint.mr_id, [])
                    ]
                    if endpoint.mr_id
                    else []
                )
                config_audit = audit_by_device.get(endpoint.mr_id)
                wmesh_received_at = self._parse_datetime(
                    (wmesh or {}).get("receive_time")
                )
                wmesh_age_seconds = (
                    max(
                        0.0,
                        (
                            now
                            - wmesh_received_at.astimezone(now.tzinfo)
                        ).total_seconds(),
                    )
                    if wmesh_received_at is not None
                    else None
                )
                wmesh_fresh = bool(
                    wmesh_received_at is not None
                    and wmesh_age_seconds is not None
                    and wmesh_age_seconds <= profile.ac_stale_grace_seconds
                )
                wmesh_active = bool(
                    wmesh_fresh
                    and str((wmesh or {}).get("event_type") or "").upper()
                    != "MESH_LINKDOWN"
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
                            ) if wmesh_active else "",
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
        detection = getattr(self.supervisor, "_storage_detection", None)
        detection_values = detection.to_dict() if detection is not None else {}
        if receiver is None:
            return {
                "volume": detection_values.get("volume", ""),
                "media_type": detection_values.get("media_type", "UNKNOWN"),
                "media_confidence": detection_values.get("confidence", "LOW"),
                "storage_profile": detection_values.get("profile", "CONSERVATIVE_STORAGE"),
                "profile_source": "MANUAL" if self.repository.get_profile().storage_io_profile != "AUTO" else "AUTO",
                "storage_detection_reason": detection_values.get("reason", ""),
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
        values = dict(receiver.health_snapshot())
        values.update({
            "volume": detection_values.get("volume", ""),
            "media_type": detection_values.get("media_type", "UNKNOWN"),
            "media_confidence": detection_values.get("confidence", "LOW"),
            "storage_profile": detection_values.get("profile", values.get("storage_profile", "CONSERVATIVE_STORAGE")),
            "profile_source": "MANUAL" if self.repository.get_profile().storage_io_profile != "AUTO" else "AUTO",
            "storage_detection_reason": detection_values.get("reason", ""),
        })
        return values

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
        raw_summary = row.get("summary")
        summary = dict(raw_summary) if isinstance(raw_summary, Mapping) else {}

        def _text(key: str) -> str:
            value = row.get(key)
            return str(value) if value is not None else ""

        def _integer(value: object) -> int:
            try:
                return int(value or 0)
            except (TypeError, ValueError):
                return 0

        return GroundArchiveDTO(
            archive_id=_text("archive_id"),
            site_id=_text("site_id"),
            run_id=_text("run_id"),
            run_date=_text("run_date"),
            actual_started_at=_text("actual_started_at"),
            actual_ended_at=_text("actual_ended_at"),
            mainline_train_count=_integer(summary.get("mainline_train_count")),
            ping_target_count=_integer(summary.get("ping_target_count")),
            ping_sample_count=_integer(summary.get("ping_sample_count")),
            covered_train_count=_integer(summary.get("covered_train_count")),
            session_count=_integer(summary.get("session_count")),
            complete_session_count=_integer(summary.get("complete_session_count")),
            partial_session_count=_integer(summary.get("partial_session_count")),
            syslog_record_count=_integer(summary.get("syslog_record_count")),
            archive_size_bytes=_integer(row.get("archive_size_bytes")),
            sha256=_text("sha256"),
            manifest_sha256=_text("manifest_sha256"),
            archive_status=_text("archive_status"),
            retention_until=_text("retention_until"),
            summary=summary,
            message=_text("message"),
            created_at=_text("created_at"),
            updated_at=_text("updated_at"),
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


_ALL_DEEP_RECORD_SOURCES = (
    "init",
    "collector",
    "collector_output",
    "terminal_monitor",
    "reconnect",
    "mesh_link",
    "switch_history",
    "ap_radio_statistics",
    "channel_busy",
    "wireless_status",
    "interface_rate",
)
_DEEP_RECORD_SOURCES = {
    "ALL": _ALL_DEEP_RECORD_SOURCES,
    "WMESH": ("mesh_link", "switch_history", "terminal_monitor"),
    "RSSI": (
        "mesh_link",
        "switch_history",
        "ap_radio_statistics",
        "terminal_monitor",
    ),
    "RADIO": (
        "ap_radio_statistics",
        "channel_busy",
        "wireless_status",
        "interface_rate",
        "terminal_monitor",
    ),
    "STATUS": ("init", "collector", "terminal_monitor", "reconnect"),
    "RAW_OUTPUT": _ALL_DEEP_RECORD_SOURCES,
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


_DEEP_MAC_RE = re.compile(
    r"(?i)(?:[0-9a-f]{4}[-.:]){2}[0-9a-f]{4}|(?:[0-9a-f]{2}:){5}[0-9a-f]{2}"
)
_DEEP_RSSI_RE = re.compile(
    r"(?i)\bRSSI\b\s*(?::|=|\s)\s*-?\d+(?:\s*/\s*-?\d+)?"
)
_DEEP_SWITCH_RSSI_RE = re.compile(r"\b-?\d{1,3}\s*/\s*-?\d{1,3}\b")
_DEEP_RAW_CONTROL_RE = re.compile(
    r"(?i)(?:\bdisplay\s+clock\b|\btime\s+zone\b|^\s*[<>\[][^\r\n]*[>#]\s*$|\bRX\s+<[^>]+>\s*display\b|>>>\s*display\b)"
)


def _deep_record_categories(source: str, text: str) -> frozenset[str]:
    value = str(text or "").strip()
    folded = value.casefold()
    categories = {"RAW_OUTPUT"}
    if not value or _DEEP_RAW_CONTROL_RE.search(value):
        return frozenset(categories)
    if re.search(r"(?i)\bdisplay\s+(?:wlan\s+mesh-link|ar5drv|counters)\b", value):
        return frozenset(categories)

    has_mac = bool(_DEEP_MAC_RE.search(value))
    has_rssi = has_mac and bool(
        _DEEP_RSSI_RE.search(value) or _DEEP_SWITCH_RSSI_RE.search(value)
    )
    has_wmesh_event = any(
        token in folded
        for token in (
            "mesh_linkup",
            "mesh_linkdown",
            "mesh_activelink_switch",
            "active link transition",
        )
    )
    has_mesh_state = has_mac and any(
        token in folded
        for token in (
            " active",
            " standby",
            " link state",
            " linkup",
            " linkdown",
            "better rssi",
            "peer name",
        )
    )
    if has_wmesh_event or (
        source in {"mesh_link", "switch_history"} and has_mesh_state
    ):
        categories.add("WMESH")
    if has_rssi:
        categories.add("RSSI")

    radio_value = bool(
        re.search(
            r"(?i)(?:channel\s*busy|txbusy|rxbusy|radio\s+statistics|"
            r"txframe|rxframe|txretry|txerr|discard|packets?/s|\bpps\b|"
            r"interface\s+rate|wlan-radio\S*\s+(?:up|down))",
            value,
        )
    )
    if radio_value:
        categories.add("RADIO")

    status_value = bool(
        re.search(
            r"(?i)(?:\b(?:session|collector)\b[^\r\n]{0,80}\b(?:start(?:ed|ing)?|"
            r"stop(?:ped|ping)?|running|completed|failed|error)\b|"
            r"\b(?:retry|reconnect(?:ed|ing)?|disconnected|heartbeat|device\s+status)\b|"
            r"\b(?:start(?:ed|ing)?|stop(?:ped|ping)?)\b[^\r\n]{0,80}"
            r"\b(?:session|collector)\b)",
            value,
        )
    )
    if (
        source in {"init", "collector", "terminal_monitor", "reconnect"}
        and not ({"WMESH", "RSSI", "RADIO"} & categories)
        and status_value
    ):
        categories.add("STATUS")
    return frozenset(categories)


def _deep_primary_category(categories: frozenset[str]) -> str:
    for category in ("WMESH", "RSSI", "RADIO", "STATUS"):
        if category in categories:
            return category
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
