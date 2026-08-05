from __future__ import annotations

from collections.abc import Mapping, Sequence

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.models.api.trackside_ap_business import (
    TracksideApBusinessPageDTO,
    TracksideApBusinessRowDTO,
    TracksideSwitchAdapterCatalogDTO,
    TracksideSwitchDeviceDTO,
)
from netconsole.models.device import Device
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.adapters.trackside_switch import resolve_trackside_switch_adapter
from netconsole.parsers.h3c.ac.state_mapper import classify_fit_ap_state
from netconsole.models.device_address import normalize_ip_address
from netconsole.services.netmiko_connection import connection_targets
from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService
from netconsole.services.trackside_ap_business import (
    count_current_optical_abnormal_aps,
    normalize_trackside_ap_business_row,
    trackside_station_options,
    trackside_row_status,
    is_trackside_device_eligible,
)
from netconsole.services.trackside_ap_export_service import (
    load_trackside_ap_business_snapshot,
    select_trackside_ap_business_rows,
)
from netconsole.services.rail_transit.trackside_ap_business_snapshot import (
    TracksideApBusinessSnapshotError,
    content_sha256,
)
from netconsole.services.rail_transit.effective_trackside_ap_scope import (
    TracksideApScopeContext,
)

class TracksideApBusinessQueryService:
    """读取 Qt 轨旁 AP 业务页同一份 Repository 与光衰规则。"""

    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths
        self.base_query = RailTransitBaseDataQueryService(paths)

    def current_site_id(self) -> str:
        return self.base_query.current_site_id()

    def list_switch_adapters(
        self, site_id: str
    ) -> TracksideSwitchAdapterCatalogDTO:
        repository = DeviceRepository(Database(self.paths.site_db_path(site_id)))
        scope_context = TracksideApScopeContext.from_metadata(
            site_id,
            SiteManager(self.paths).load_site_metadata(site_id),
        )
        items: list[TracksideSwitchDeviceDTO] = []
        for device in repository.list(device_type="SW"):
            if not is_trackside_device_eligible(
                device,
                project_phase=scope_context.project_phase,
            ):
                continue
            try:
                description = resolve_trackside_switch_adapter(
                    device
                ).describe_capabilities()
            except ValueError:
                continue
            items.append(
                TracksideSwitchDeviceDTO(
                    device_uuid=str(device.device_uuid or ""),
                    device_name=str(device.name or device.system_name or ""),
                    station=str(device.station or ""),
                    primary_address=str(device.primary_address or ""),
                    adapter=description.to_dict(),
                )
            )
        return TracksideSwitchAdapterCatalogDTO(items=items, total=len(items))

    def list_rows(
        self,
        site_id: str,
        *,
        station: str = "",
        query: str = "",
        optical_anomaly_only: bool = False,
        page: int = 1,
        page_size: int = 50,
        expected_revision: str = "",
    ) -> TracksideApBusinessPageDTO:
        database = Database(self.paths.site_db_path(site_id))
        repository = DeviceRepository(database)
        snapshot = load_trackside_ap_business_snapshot(
            repository,
            site_id,
            generation=0,
            scope_context=TracksideApScopeContext.from_metadata(
                site_id,
                SiteManager(self.paths).load_site_metadata(site_id),
            ),
            identity_query_macs=(query,),
        )
        if expected_revision and expected_revision != snapshot.business_revision:
            raise TracksideApBusinessSnapshotError(
                "TRACKSIDE_AP_SNAPSHOT_STALE",
                "轨旁 AP 数据已更新，请刷新后重试。",
            )
        business_rows = [
            normalize_trackside_ap_business_row(row)
            for row in snapshot.rows
        ]
        station_options = trackside_station_options(business_rows)
        rows = select_trackside_ap_business_rows(
            business_rows,
            station=station,
            query=query,
            optical_anomaly_only=optical_anomaly_only,
            identity_query_entities=snapshot.identity_query_entities,
        )
        enriched = [(row, trackside_row_status(row)) for row in rows]
        current_page = max(1, int(page))
        size = max(1, min(int(page_size), 200))
        start = (current_page - 1) * size
        terminal_devices = self._terminal_devices_by_uuid(snapshot.all_devices)
        items = [
            self._row(row, severity, terminal_devices)
            for row, severity in enriched[start : start + size]
        ]
        scope = snapshot.scope
        return TracksideApBusinessPageDTO(
            items=items,
            total=len(enriched),
            page=current_page,
            page_size=size,
            site_id=site_id,
            station_options=station_options,
            device_count=snapshot.device_count,
            candidate_interface_count=snapshot.candidate_ap_interface_count,
            optical_abnormal_count=count_current_optical_abnormal_aps(business_rows),
            fit_ap_resource_count=snapshot.fit_ap_resource_count,
            fit_ap_resource_total_count=snapshot.fit_ap_resource_total_count,
            fit_ap_matched_count=snapshot.fit_ap_matched_count,
            fit_ap_matched_online_count=snapshot.fit_ap_matched_online_count,
            fit_ap_online_total_count=snapshot.fit_ap_online_total_count,
            fit_ap_offline_total_count=snapshot.fit_ap_offline_total_count,
            fit_ap_unknown_total_count=snapshot.fit_ap_unknown_total_count,
            fit_ap_unmatched_online_count=snapshot.fit_ap_unmatched_online_count,
            fit_ap_lldp_snapshot_stale_count=snapshot.fit_ap_lldp_snapshot_stale_count,
            fit_ap_lldp_exact_match_pending_count=snapshot.fit_ap_lldp_exact_match_pending_count,
            fit_ap_current_conflict_count=snapshot.fit_ap_current_conflict_count,
            fit_ap_planning_missing_count=snapshot.fit_ap_planning_missing_count,
            fit_ap_ambiguous_online_count=snapshot.fit_ap_ambiguous_online_count,
            fit_ap_station_master_missing_count=snapshot.fit_ap_station_master_missing_count,
            fit_ap_unknown_association_count=snapshot.fit_ap_unknown_association_count,
            business_row_count=snapshot.business_row_count or len(business_rows),
            query_ms=snapshot.query_ms,
            build_ms=snapshot.build_ms,
            empty_reason=snapshot.empty_reason,
            identity_shadow=snapshot.identity_shadow,
            runtime_snapshot=snapshot.runtime_snapshot.to_dict(),
            scope_description=(
                scope.scope_description
                if scope is not None
                else "当前项目 · 当前工作范围轨旁 AP"
            ),
            scope_station_count=scope.scope_station_count if scope is not None else 0,
            scope_device_count=scope.scope_device_count if scope is not None else 0,
            scope_ap_reference_count=(
                scope.scope_ap_reference_count if scope is not None else 0
            ),
            excluded_device_count=(
                scope.excluded_device_count if scope is not None else 0
            ),
            excluded_items=(
                [item.to_dict() for item in scope.excluded_items[:200]]
                if scope is not None
                else []
            ),
            unmatched_online_items=(
                [
                    item.to_dict()
                    for item in scope.unmatched_online_items[:200]
                ]
                if scope is not None
                else []
            ),
            partial_data=snapshot.partial_data,
            source_statuses=snapshot.source_statuses,
            unavailable_sources=snapshot.unavailable_sources,
            snapshot_id=snapshot.snapshot_id,
            business_revision=snapshot.business_revision,
            source_revisions=dict(snapshot.source_revisions),
            identity_revision=snapshot.identity_revision,
            created_at=snapshot.created_at,
            content_sha256=content_sha256(rows),
            row_count=len(rows),
            abnormal_count=count_current_optical_abnormal_aps(rows),
            unresolved_count=sum(
                row.get("identity_match_status") == "unresolved"
                for row in rows
            ),
            ambiguous_count=sum(
                row.get("identity_match_status") == "ambiguous"
                for row in rows
            ),
            snapshot_retry_count=snapshot.snapshot_retry_count,
            identity_distinct_count=snapshot.identity_distinct_count,
        )

    @staticmethod
    def _terminal_devices_by_uuid(
        devices: Sequence[Device],
    ) -> Mapping[str, Device]:
        by_uuid: dict[str, Device] = {}
        for device in devices:
            device_uuid = str(device.device_uuid or "").strip()
            if device_uuid:
                by_uuid[device_uuid] = device
        return by_uuid

    @staticmethod
    def _device_terminal_status(
        device: Device | None,
    ) -> tuple[str, bool, str]:
        device_uuid = str(device.device_uuid or "").strip() if device else ""
        if not device_uuid:
            return "", False, "未找到可启动终端的设备管理记录"
        if not normalize_ip_address(device.primary_address):
            return device_uuid, False, "缺少管理地址"
        targets = connection_targets(device)
        if not targets:
            return device_uuid, False, "缺少连接协议或凭据"
        if not any(not target.via_tunnel for target in targets):
            return device_uuid, False, "外部终端暂不支持内部临时隧道"
        return device_uuid, True, ""

    @staticmethod
    def _fit_ap_terminal_status(
        row: Mapping[str, object | None],
    ) -> tuple[str, str, bool, str]:
        ac_id = str(row.get("ac_device_uuid") or "").strip()
        ap_id = str(row.get("ap_uuid") or "").strip()
        if not ac_id or not ap_id:
            return "", "", False, "未关联到 FIT-AP 资源"
        if not normalize_ip_address(row.get("ap_ip")):
            return ac_id, ap_id, False, "当前 AP 没有 IP，无法打开外部终端"
        status = classify_fit_ap_state(
            row.get("ap_state"),
            row.get("ap_state_display"),
        )
        if status != "online":
            return ac_id, ap_id, False, "当前 AP 离线或状态异常，无法打开外部终端"
        return ac_id, ap_id, True, ""

    @staticmethod
    def _row(
        row: dict[str, object | None],
        severity: str,
        terminal_devices: Mapping[str, Device],
    ) -> TracksideApBusinessRowDTO:
        observed_neighbor_mac = str(row.get("lldp_observed_neighbor_mac") or "")
        lldp_match_status = str(row.get("lldp_match_status") or "")
        effective_station_id = str(
            row.get("effective_station_id") or row.get("station_id") or ""
        )
        switch_device = terminal_devices.get(
            str(row.get("device_uuid") or "").strip()
        )
        switch_uuid, switch_available, switch_reason = TracksideApBusinessQueryService._device_terminal_status(
            switch_device
        )
        ap_ac_id, ap_id, ap_available, ap_reason = (
            TracksideApBusinessQueryService._fit_ap_terminal_status(row)
        )
        return TracksideApBusinessRowDTO(
            row_id=str(row.get("business_row_id") or ""),
            station_id=effective_station_id,
            switch_station_id=str(row.get("switch_station_id") or ""),
            ap_station_id=str(row.get("ap_station_id") or ""),
            planning_station_id=str(row.get("planning_station_id") or ""),
            effective_station_id=effective_station_id,
            station_consistency_status=str(
                row.get("station_consistency_status") or "unresolved"
            ),
            station_consistency_reason=str(
                row.get("station_consistency_reason") or "STATION_ID_MISSING"
            ),
            site=str(row.get("site") or ""),
            device_name=str(row.get("device_name") or ""),
            switch_device_uuid=switch_uuid,
            switch_terminal_available=switch_available,
            switch_terminal_unavailable_reason=switch_reason,
            switch_vendor=str(row.get("switch_vendor") or ""),
            interface_name=str(row.get("interface_name") or ""),
            link_status=str(row.get("link_status") or ""),
            port_type=str(row.get("port_type") or ""),
            description=str(row.get("description") or ""),
            pvid=row.get("pvid"),
            vlan=row.get("vlan"),
            planned_management_vlan=row.get("planned_management_vlan"),
            vlan_group_id=str(row.get("vlan_group_id") or ""),
            vlan_group_code=str(row.get("vlan_group_code") or ""),
            vlan_group_name=str(row.get("vlan_group_name") or ""),
            pvid_plan_status=str(row.get("pvid_plan_status") or "unresolved"),
            switch_rx_power=row.get("switch_rx_power"),
            switch_tx_power=row.get("switch_tx_power"),
            switch_rx_low_alarm=row.get("switch_rx_low_alarm"),
            switch_rx_high_alarm=row.get("switch_rx_high_alarm"),
            switch_tx_low_alarm=row.get("switch_tx_low_alarm"),
            switch_tx_high_alarm=row.get("switch_tx_high_alarm"),
            switch_optical_status=str(row.get("switch_optical_status") or ""),
            switch_interface_updated_at=str(
                row.get("switch_interface_updated_at") or ""
            ),
            switch_optical_updated_at=str(
                row.get("switch_optical_updated_at") or ""
            ),
            switch_interface_data_status=str(
                row.get("switch_interface_data_status") or "unknown"
            ),
            switch_optical_data_status=str(
                row.get("switch_optical_data_status") or "unknown"
            ),
            ap_uuid=str(row.get("ap_uuid") or ""),
            ap_mac=str(row.get("ap_mac") or ""),
            ap_name=str(row.get("ap_name") or ""),
            ap_terminal_ac_id=ap_ac_id,
            ap_terminal_ap_id=ap_id,
            ap_terminal_available=ap_available,
            ap_terminal_unavailable_reason=ap_reason,
            ap_rx_power=row.get("ap_rx_power"),
            ap_tx_power=row.get("ap_tx_power"),
            ap_device_optical_status=str(
                row.get("ap_device_optical_status") or ""
            ),
            ap_business_optical_status=str(
                row.get("ap_business_optical_status") or "unknown"
            ),
            ap_business_threshold_dbm=float(
                row.get("ap_business_threshold_dbm") or -13.90
            ),
            ap_business_reason=str(row.get("ap_business_reason") or ""),
            ap_optical_status=str(row.get("ap_optical_status") or ""),
            ap_match_source=str(row.get("ap_match_source") or ""),
            ap_match_confidence=int(row.get("ap_match_confidence") or 0),
            ap_identity_entity_id=str(row.get("ap_identity_entity_id") or ""),
            identity_match_status=str(row.get("identity_match_status") or "unresolved"),
            identity_match_rule=str(row.get("identity_match_rule") or ""),
            lldp_observed_neighbor_mac=observed_neighbor_mac,
            lldp_match_status=lldp_match_status,
            lldp_history_status=str(row.get("lldp_history_status") or "no_current_evidence"),
            runtime_snapshot_status=str(row.get("runtime_snapshot_status") or "unavailable"),
            fit_ap_snapshot_collected_at=str(row.get("fit_ap_snapshot_collected_at") or ""),
            lldp_snapshot_collected_at=str(row.get("lldp_snapshot_collected_at") or ""),
            lldp_snapshot_generation=str(row.get("lldp_snapshot_generation") or ""),
            local_rx_power_dbm=row.get("local_rx_power_dbm"),
            local_tx_power_dbm=row.get("local_tx_power_dbm"),
            remote_rx_power_dbm=row.get("remote_rx_power_dbm"),
            remote_tx_power_dbm=row.get("remote_tx_power_dbm"),
            forward_loss_db=row.get("forward_loss_db"),
            reverse_loss_db=row.get("reverse_loss_db"),
            calculation_status=str(row.get("calculation_status") or ""),
            calculation_reason=str(row.get("calculation_reason") or ""),
            local_sample_time=str(row.get("local_sample_time") or ""),
            remote_sample_time=str(row.get("remote_sample_time") or ""),
            sample_time_delta_seconds=row.get("sample_time_delta_seconds"),
            updated_at=str(row.get("updated_at") or ""),
            optical_severity=severity,
        )


__all__ = ["TracksideApBusinessQueryService"]
