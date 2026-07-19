from __future__ import annotations

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.api.trackside_ap_business import (
    TracksideApBusinessPageDTO,
    TracksideApBusinessRowDTO,
)
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService
from netconsole.services.trackside_ap_business import (
    filter_trackside_ap_business_rows,
    is_trackside_optical_abnormal_status,
    trackside_row_status,
)
from netconsole.services.trackside_ap_export_service import load_trackside_ap_business_snapshot


class TracksideApBusinessQueryService:
    """读取 Qt 轨旁 AP 业务页同一份 Repository 与光衰规则。"""

    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths
        self.base_query = RailTransitBaseDataQueryService(paths)

    def current_site_id(self) -> str:
        return self.base_query.current_site_id()

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
        snapshot = load_trackside_ap_business_snapshot(
            DeviceRepository(Database(self.paths.site_db_path(site_id))),
            site_id,
            generation=0,
        )
        rows = filter_trackside_ap_business_rows(snapshot.rows, station, query)
        enriched = [(row, trackside_row_status(row)) for row in rows]
        if optical_anomaly_only:
            enriched = [(row, severity) for row, severity in enriched if is_trackside_optical_abnormal_status(severity)]
        current_page = max(1, int(page))
        size = max(1, min(int(page_size), 200))
        start = (current_page - 1) * size
        items = [self._row(row, severity) for row, severity in enriched[start : start + size]]
        return TracksideApBusinessPageDTO(
            items=items,
            total=len(enriched),
            page=current_page,
            page_size=size,
            site_id=site_id,
            device_count=snapshot.device_count,
            candidate_interface_count=snapshot.candidate_ap_interface_count,
            optical_abnormal_count=sum(
                is_trackside_optical_abnormal_status(trackside_row_status(row)) for row in snapshot.rows
            ),
            fit_ap_resource_count=snapshot.fit_ap_resource_count,
            query_ms=snapshot.query_ms,
            build_ms=snapshot.build_ms,
            empty_reason=snapshot.empty_reason,
            identity_shadow=snapshot.identity_shadow,
        )

    @staticmethod
    def _row(row: dict[str, object | None], severity: str) -> TracksideApBusinessRowDTO:
        return TracksideApBusinessRowDTO(
            site=str(row.get("site") or ""),
            device_name=str(row.get("device_name") or ""),
            interface_name=str(row.get("interface_name") or ""),
            link_status=str(row.get("link_status") or ""),
            port_type=str(row.get("port_type") or ""),
            description=str(row.get("description") or ""),
            pvid=row.get("pvid"),
            vlan=row.get("vlan"),
            switch_rx_power=row.get("switch_rx_power"),
            switch_optical_status=str(row.get("switch_optical_status") or ""),
            ap_mac=str(row.get("ap_mac") or ""),
            ap_name=str(row.get("ap_name") or ""),
            ap_rx_power=row.get("ap_rx_power"),
            ap_optical_status=str(row.get("ap_optical_status") or ""),
            updated_at=str(row.get("updated_at") or ""),
            optical_severity=severity,
        )


__all__ = ["TracksideApBusinessQueryService"]
