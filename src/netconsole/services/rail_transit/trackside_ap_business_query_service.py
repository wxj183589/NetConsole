from __future__ import annotations

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.models.api.trackside_ap_business import (
    TracksideApBusinessPageDTO,
    TracksideApBusinessRowDTO,
    TracksideSwitchAdapterCatalogDTO,
    TracksideSwitchDeviceDTO,
)
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.adapters.trackside_switch import resolve_trackside_switch_adapter
from netconsole.services.ap_identity import ApIdentityQueryService
from netconsole.services.ap_identity.normalizers import normalize_mac_key
from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService
from netconsole.services.trackside_ap_business import (
    count_current_optical_abnormal_aps,
    filter_trackside_ap_business_rows,
    is_current_optical_abnormal_row,
    normalize_trackside_ap_business_row,
    trackside_station_options,
    trackside_row_status,
    is_trackside_device_eligible,
)
from netconsole.services.trackside_ap_export_service import load_trackside_ap_business_snapshot
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
    ) -> TracksideApBusinessPageDTO:
        database = Database(self.paths.site_db_path(site_id))
        snapshot = load_trackside_ap_business_snapshot(
            DeviceRepository(database),
            site_id,
            generation=0,
            scope_context=TracksideApScopeContext.from_metadata(
                site_id,
                SiteManager(self.paths).load_site_metadata(site_id),
            ),
        )
        business_rows = [
            normalize_trackside_ap_business_row(row)
            for row in snapshot.rows
        ]
        station_options = trackside_station_options(business_rows)
        if normalize_mac_key(query):
            identity_rows = ApIdentityQueryService(database).search_aps(query)
            matched_macs = {
                mac
                for item in identity_rows
                for field in ("ap_mac", "ac_ap_mac", "base_ap_mac")
                if (mac := normalize_mac_key(item.get(field)))
            }
            matched_names = {
                str(item.get("ap_name") or "").strip().casefold()
                for item in identity_rows
                if str(item.get("ap_name") or "").strip()
            }
            rows = [
                row
                for row in filter_trackside_ap_business_rows(
                    business_rows, station, ""
                )
                if normalize_mac_key(row.get("ap_mac")) in matched_macs
                or str(row.get("ap_name") or "").strip().casefold()
                in matched_names
            ]
        else:
            rows = filter_trackside_ap_business_rows(
                business_rows, station, query
            )
        enriched = [(row, trackside_row_status(row)) for row in rows]
        if optical_anomaly_only:
            enriched = [(row, severity) for row, severity in enriched if is_current_optical_abnormal_row(row)]
        current_page = max(1, int(page))
        size = max(1, min(int(page_size), 200))
        start = (current_page - 1) * size
        try:
            identity_query: ApIdentityQueryService | None = ApIdentityQueryService(database)
            identity_query.pin_index_health()
        except (AttributeError, OSError):
            identity_query = None
        items = [
            self._row(row, severity, identity_query)
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
            fit_ap_unmatched_online_count=snapshot.fit_ap_unmatched_online_count,
            business_row_count=snapshot.business_row_count or len(business_rows),
            query_ms=snapshot.query_ms,
            build_ms=snapshot.build_ms,
            empty_reason=snapshot.empty_reason,
            identity_shadow=snapshot.identity_shadow,
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
        )

    @staticmethod
    def _row(
        row: dict[str, object | None],
        severity: str,
        identity_query: ApIdentityQueryService | None,
    ) -> TracksideApBusinessRowDTO:
        observed_neighbor_mac = str(row.get("lldp_observed_neighbor_mac") or "")
        identity_mac = observed_neighbor_mac or str(row.get("ap_mac") or "")
        identity_match = identity_query.resolve_mac(identity_mac) if identity_query else None
        lldp_match_status = str(row.get("lldp_match_status") or "")
        if observed_neighbor_mac:
            lldp_match_status = (
                identity_match.status.upper() if identity_match else "UNAVAILABLE"
            )
        effective_station_id = str(
            row.get("effective_station_id") or row.get("station_id") or ""
        )
        return TracksideApBusinessRowDTO(
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
            ap_rx_power=row.get("ap_rx_power"),
            ap_tx_power=row.get("ap_tx_power"),
            ap_optical_status=str(row.get("ap_optical_status") or ""),
            ap_match_source=str(row.get("ap_match_source") or ""),
            ap_match_confidence=int(row.get("ap_match_confidence") or 0),
            ap_identity_entity_id=(identity_match.matched_entity_id if identity_match else ""),
            identity_match_status=(identity_match.status if identity_match else "unavailable"),
            identity_match_rule=(
                (
                    identity_match.match_rule
                    or identity_match.matched_alias_type
                    or identity_match.unresolved_reason
                )
                if identity_match
                else "IDENTITY_INDEX_UNAVAILABLE"
            ),
            lldp_observed_neighbor_mac=observed_neighbor_mac,
            lldp_match_status=lldp_match_status,
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
