from __future__ import annotations

from dataclasses import asdict

from netconsole.core.paths import PathResolver
from netconsole.models.api.vehicle_mr_online import (
    VehicleMrEndStateDTO,
    VehicleMrEventPageDTO,
    VehicleMrOnlinePageDTO,
    VehicleMrTrainMappingDTO,
    VehicleMrTrainStateDTO,
)
from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService
from netconsole.services.vehicle_mr_online import (
    TRAIN_STATUS_ABNORMAL_SINGLE,
    TRAIN_STATUS_DUAL_ONLINE,
    TRAIN_STATUS_OFFLINE,
    TRAIN_STATUS_ONLINE,
    TRAIN_STATUS_PARTIAL,
    TRAIN_STATUS_UNEXPECTED_END,
    VehicleMrOnlineStore,
)


class VehicleMrOnlineQueryService:
    """列车在线页的持久化查询边界。"""

    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths
        self.base_query = RailTransitBaseDataQueryService(paths)

    def current_site_id(self) -> str:
        return self.base_query.current_site_id()

    def list_trains(
        self,
        site_id: str,
        *,
        query: str = "",
        status: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> VehicleMrOnlinePageDTO:
        rows = self._store(site_id).list_current_states()
        all_rows = list(rows)
        if query:
            needle = query.casefold()
            rows = [row for row in rows if needle in self._search_text(row).casefold()]
        if status:
            rows = [row for row in rows if row.status == status]
        current = max(1, int(page))
        size = max(1, min(int(page_size), 200))
        start = (current - 1) * size
        return VehicleMrOnlinePageDTO(
            items=[self._train(row) for row in rows[start : start + size]],
            total=len(rows),
            page=current,
            page_size=size,
            site_id=site_id,
            online_count=sum(row.status in {TRAIN_STATUS_ONLINE, TRAIN_STATUS_DUAL_ONLINE} for row in all_rows),
            abnormal_count=sum(row.status in {TRAIN_STATUS_ABNORMAL_SINGLE, TRAIN_STATUS_UNEXPECTED_END, TRAIN_STATUS_PARTIAL} for row in all_rows),
            offline_count=sum(row.status == TRAIN_STATUS_OFFLINE for row in all_rows),
            unregistered_count=sum(not row.is_registered for row in all_rows),
        )

    def list_mappings(self, site_id: str) -> list[VehicleMrTrainMappingDTO]:
        return [VehicleMrTrainMappingDTO(**asdict(row)) for row in self._store(site_id).list_mappings()]

    def list_events(self, site_id: str, train_id: str, *, limit: int = 200) -> VehicleMrEventPageDTO:
        rows = self._store(site_id).list_events(train_id, min(max(int(limit), 1), 2000))
        return VehicleMrEventPageDTO(items=rows, total=len(rows))

    def _store(self, site_id: str) -> VehicleMrOnlineStore:
        return VehicleMrOnlineStore(self.paths, site_id)

    @staticmethod
    def _train(row) -> VehicleMrTrainStateDTO:
        return VehicleMrTrainStateDTO(
            train_id=row.train_id,
            train_no=row.train_no,
            display_name=row.display_name,
            is_registered=row.is_registered,
            status=row.status,
            current_station=row.current_station,
            last_ac_time=row.last_ac_time,
            last_seen_at=row.last_seen_at,
            tc1=VehicleMrEndStateDTO(**asdict(row.tc1)),
            tc2=VehicleMrEndStateDTO(**asdict(row.tc2)),
            online_policy=row.online_policy,
            expected_end=row.expected_end,
            direction=row.direction,
            status_reason=row.status_reason,
        )

    @staticmethod
    def _search_text(row) -> str:
        return " ".join(
            str(value or "")
            for value in (
                row.train_id,
                row.train_no,
                row.display_name,
                row.current_station,
                row.tc1.ap_name,
                row.tc2.ap_name,
                row.tc1.station,
                row.tc2.station,
            )
        )


__all__ = ["VehicleMrOnlineQueryService"]
