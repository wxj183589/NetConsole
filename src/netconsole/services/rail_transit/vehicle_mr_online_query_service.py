from __future__ import annotations

from dataclasses import asdict

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.api.vehicle_mr_online import (
    VehicleMrEndStateDTO,
    VehicleMrControllerDTO,
    VehicleMrEventPageDTO,
    VehicleMrOnlinePageDTO,
    VehicleMrTrainMappingDTO,
    VehicleMrTrainStateDTO,
)
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.models.api.ac_mesh_link import AcMeshMrStatusDTO
from netconsole.services.ac.mesh_link_query_service import AcMeshLinkQueryService
from netconsole.services.rail_transit.base_data_query_service import (
    RailTransitBaseDataQueryService,
)
from netconsole.services.vehicle_mr_online import (
    VehicleMrOnlineStore,
    VehicleMrTrainState,
    is_ac_device,
)


_REASON_TEXT = {
    "both_offline": "CT 与 TC 两端均离线",
    "dual_active_ok": "CT 与 TC 两端均在线",
    "tc1_missing": "CT 端未在线",
    "tc2_missing": "TC 端未在线",
    "both_ends_online": "CT 与 TC 两端均在线",
    "expected_tc1_online": "预期 CT 端在线",
    "expected_tc2_online": "预期 TC 端在线",
    "unexpected_tc1_online": "当前在线端与策略不一致",
    "unexpected_tc2_online": "当前在线端与策略不一致",
    "expected_tail_online": "预期尾端在线",
    "unexpected_end_online": "当前在线端与运行方向不一致",
    "direction_unknown_any_end_online": "运行方向未知，按任一端在线处理",
    "policy_unknown_any_end_online": "在线策略未明确，按任一端在线处理",
    "mesh_data_stale": "Mesh-Link 数据已过期",
    "mesh_data_unavailable": "暂无可用 Mesh-Link 数据",
}


class VehicleMrOnlineQueryService:
    """列车在线页的持久化查询边界。"""

    def __init__(
        self, paths: PathResolver, *, mesh_query: AcMeshLinkQueryService | None = None
    ) -> None:
        self.paths = paths
        self.base_query = RailTransitBaseDataQueryService(paths)
        self.mesh_query = mesh_query or AcMeshLinkQueryService(paths)

    def current_site_id(self) -> str:
        return self.base_query.current_site_id()

    def list_trains(
        self,
        site_id: str,
        *,
        query: str = "",
        status: str = "",
        station: str = "",
        section: str = "",
        data_status: str = "",
        unmatched_only: bool = False,
        page: int = 1,
        page_size: int = 50,
    ) -> VehicleMrOnlinePageDTO:
        rows = self._all_trains(site_id)
        all_rows = list(rows)
        if query:
            needle = query.casefold()
            rows = [row for row in rows if needle in self._search_text(row).casefold()]
        if status:
            rows = [row for row in rows if row.overall_status == status]
        if station:
            needle = station.casefold()
            rows = [
                row
                for row in rows
                if any(
                    needle in str(value or "").casefold()
                    for value in (row.ct.station_name, row.tc.station_name)
                )
            ]
        if section:
            needle = section.casefold()
            rows = [
                row
                for row in rows
                if any(
                    needle in str(value or "").casefold()
                    for value in (row.ct.section_name, row.tc.section_name)
                )
            ]
        if data_status:
            rows = [
                row
                for row in rows
                if data_status in {row.ct.data_status, row.tc.data_status}
            ]
        if unmatched_only:
            rows = [
                row
                for row in rows
                if "UNMATCHED" in {row.ct.match_status, row.tc.match_status}
            ]
        current = max(1, int(page))
        size = max(1, min(int(page_size), 200))
        start = (current - 1) * size
        return VehicleMrOnlinePageDTO(
            items=rows[start : start + size],
            total=len(rows),
            page=current,
            page_size=size,
            site_id=site_id,
            mr_total=sum(
                bool(endpoint.mr_id)
                for row in all_rows
                for endpoint in (row.ct, row.tc)
            ),
            both_online_count=sum(
                row.overall_status == "BOTH_ONLINE" for row in all_rows
            ),
            one_side_online_count=sum(
                row.overall_status == "ONE_SIDE_ONLINE" for row in all_rows
            ),
            both_offline_count=sum(
                row.overall_status == "BOTH_OFFLINE" for row in all_rows
            ),
            stale_count=sum(row.overall_status == "STALE" for row in all_rows),
            unknown_count=sum(row.overall_status == "UNKNOWN" for row in all_rows),
            active_mesh_link_count=sum(
                endpoint.online_status == "ONLINE" and bool(endpoint.current_ap_name)
                for row in all_rows
                for endpoint in (row.ct, row.tc)
            ),
            unmatched_ap_count=sum(
                endpoint.match_status == "UNMATCHED"
                for row in all_rows
                for endpoint in (row.ct, row.tc)
            ),
        )

    def _all_trains(self, site_id: str) -> list[VehicleMrTrainStateDTO]:
        mesh_rows = self._mesh_rows(site_id)
        mesh_by_endpoint = {
            (self._train_key(item.train_no), self._endpoint_key(item.car_end)): item
            for item in mesh_rows
            if item.train_no and self._endpoint_key(item.car_end)
        }
        state_rows = self._store(site_id).list_current_states()
        known_trains = {
            self._train_key(row.train_no) for row in state_rows if row.train_no
        }
        for item in mesh_rows:
            key = self._train_key(item.train_no)
            if not key or key in known_trains:
                continue
            state_rows.append(
                VehicleMrTrainState(
                    train_id=f"mesh:{key}", train_no=item.train_no, is_registered=False
                )
            )
            known_trains.add(key)
        return [self._train(row, mesh_by_endpoint) for row in state_rows]

    def get_train(self, site_id: str, train_id: str) -> VehicleMrTrainStateDTO | None:
        return next(
            (item for item in self._all_trains(site_id) if item.train_id == train_id),
            None,
        )

    def list_mappings(self, site_id: str) -> list[VehicleMrTrainMappingDTO]:
        return [
            VehicleMrTrainMappingDTO(**asdict(row))
            for row in self._store(site_id).list_mappings()
        ]

    def list_controllers(self, site_id: str) -> list[VehicleMrControllerDTO]:
        repository = DeviceRepository(Database(self.paths.site_db_path(site_id)))
        result = []
        for device in repository.list():
            if device.id is None or not is_ac_device(device):
                continue
            protocol = (
                "SSH"
                if device.ssh_enabled
                else "Telnet"
                if device.telnet_enabled
                else ""
            )
            username = (
                device.ssh_username if protocol == "SSH" else device.telnet_username
            )
            password = (
                device.ssh_password if protocol == "SSH" else device.telnet_password
            )
            result.append(
                VehicleMrControllerDTO(
                    controller_id=str(device.device_uuid or ""),
                    device_id=device.id,
                    name=device.name,
                    primary_address=device.primary_address,
                    protocol=protocol,
                    connection_ready=bool(
                        device.device_uuid
                        and protocol
                        and device.primary_address
                        and username
                        and password
                    ),
                )
            )
        return sorted(
            result,
            key=lambda item: (
                item.name.casefold(),
                item.primary_address,
                item.device_id,
            ),
        )

    def list_events(
        self,
        site_id: str,
        train_id: str,
        *,
        start_time: str = "",
        end_time: str = "",
        car_end_label: str = "",
        status: str = "",
        station: str = "",
        ap_name: str = "",
        limit: int = 200,
    ) -> VehicleMrEventPageDTO:
        size = min(max(int(limit), 1), 2000)
        if any((start_time, end_time, car_end_label, status, station, ap_name)):
            rows = self._store(site_id).query_events(
                train_id,
                start_time,
                end_time,
                car_end_label=car_end_label,
                status=status,
                station=station,
                ap_name=ap_name,
                limit=size,
            )
        else:
            rows = self._store(site_id).list_events(train_id, size)
        return VehicleMrEventPageDTO(items=rows, total=len(rows))

    def _store(self, site_id: str) -> VehicleMrOnlineStore:
        return VehicleMrOnlineStore(self.paths, site_id)

    def _train(
        self,
        row,
        mesh_by_endpoint: dict[tuple[str, str], AcMeshMrStatusDTO],
    ) -> VehicleMrTrainStateDTO:
        key = self._train_key(row.train_no)
        ct = self._endpoint("CT", row.tc1, mesh_by_endpoint.get((key, "CT")))
        tc = self._endpoint("TC", row.tc2, mesh_by_endpoint.get((key, "TC")))
        overall_status = self._overall_status(ct, tc)
        reason_code = str(row.status_reason or "") or None
        if overall_status == "STALE":
            reason_code = "mesh_data_stale"
        elif overall_status == "UNKNOWN":
            reason_code = "mesh_data_unavailable"
        return VehicleMrTrainStateDTO(
            train_id=row.train_id,
            train_no=row.train_no,
            train_name=row.display_name,
            is_registered=row.is_registered,
            overall_status=overall_status,
            ct=ct,
            tc=tc,
            current_station=self._joined(ct.station_name, tc.station_name),
            current_section=self._joined(ct.section_name, tc.section_name),
            current_mileage=self._joined(ct.mileage, tc.mileage),
            direction=self._first_value(
                row.direction if row.direction != "未知" else None,
                ct.direction,
                tc.direction,
            ),
            policy=row.online_policy or None,
            reason_code=reason_code,
            reason_text=_REASON_TEXT.get(reason_code or "", reason_code),
            updated_at=max(
                (
                    value
                    for value in (
                        ct.updated_at,
                        tc.updated_at,
                        row.last_seen_at,
                        row.last_ac_time,
                    )
                    if value
                ),
                default=None,
            ),
        )

    def _endpoint(
        self, endpoint: str, persisted, mesh: AcMeshMrStatusDTO | None
    ) -> VehicleMrEndStateDTO:
        online_status = self._online_status(
            mesh.online_status if mesh else ("stale" if persisted.seen else "unknown")
        )
        return VehicleMrEndStateDTO(
            endpoint=endpoint,
            mr_id=(mesh.mr_id or None) if mesh else None,
            mr_name=(mesh.mr_name or None) if mesh else None,
            online_status=online_status,
            current_ap_name=(mesh.peer_ap_name or None)
            if mesh
            else (persisted.ap_name or None),
            current_ap_mac=(mesh.peer_ap_mac or None) if mesh else None,
            mesh_radio=(mesh.mesh_radio or None) if mesh else None,
            rssi_dbm=mesh.rssi if mesh else persisted.rssi,
            station_name=(mesh.station or None)
            if mesh
            else (persisted.station or None),
            section_name=(mesh.section or None) if mesh else None,
            mileage=(mesh.mileage or None) if mesh else None,
            direction=(mesh.line_side or None) if mesh else None,
            match_status=self._match_status(
                mesh.match_method if mesh else persisted.match_method,
                bool((mesh.peer_ap_name if mesh else persisted.ap_name)),
            ),
            outdoor_optical_power=(mesh.ap_rx_power or None) if mesh else None,
            indoor_optical_power=(mesh.switch_rx_power or None) if mesh else None,
            updated_at=(mesh.last_seen_at or None)
            if mesh
            else (persisted.last_seen_at or None),
            data_status=self._data_status(mesh.data_status if mesh else "no_data"),
        )

    def _mesh_rows(self, site_id: str) -> list[AcMeshMrStatusDTO]:
        first = self.mesh_query.list_mrs(site_id, page=1, page_size=200)
        result = list(first.items)
        page = 2
        while len(result) < first.total:
            current = self.mesh_query.list_mrs(site_id, page=page, page_size=200)
            if not current.items:
                break
            result.extend(current.items)
            page += 1
        return result

    @staticmethod
    def _online_status(value: str) -> str:
        return {"online": "ONLINE", "offline": "OFFLINE", "stale": "STALE"}.get(
            str(value or "").casefold(), "UNKNOWN"
        )

    @staticmethod
    def _data_status(value: str) -> str:
        return {
            "fresh": "FRESH",
            "recent": "STALE",
            "stale": "STALE",
            "error": "ERROR",
            "no_data": "NO_DATA",
        }.get(str(value or "").casefold(), "UNKNOWN")

    @staticmethod
    def _match_status(value: str, has_ap: bool) -> str:
        normalized = str(value or "").casefold()
        if normalized == "unmatched":
            return "UNMATCHED" if has_ap else "UNKNOWN"
        if "mac" in normalized:
            return "MAC_MATCHED"
        if "normal" in normalized:
            return "NAME_NORMALIZED"
        if normalized and has_ap:
            return "EXACT"
        return "UNKNOWN"

    @staticmethod
    def _overall_status(ct: VehicleMrEndStateDTO, tc: VehicleMrEndStateDTO) -> str:
        statuses = {ct.online_status, tc.online_status}
        if "STALE" in statuses:
            return "STALE"
        online = sum(
            value == "ONLINE" for value in (ct.online_status, tc.online_status)
        )
        if online == 2:
            return "BOTH_ONLINE"
        if online == 1:
            return "ONE_SIDE_ONLINE"
        if ct.online_status == tc.online_status == "OFFLINE":
            return "BOTH_OFFLINE"
        return "UNKNOWN"

    @staticmethod
    def _train_key(value: str) -> str:
        text = str(value or "").strip()
        return text.zfill(2) if text.isdigit() else text.casefold()

    @staticmethod
    def _endpoint_key(value: str) -> str:
        text = str(value or "").strip().upper()
        return "CT" if text == "CT" else "TC" if text in {"TC", "CW"} else ""

    @staticmethod
    def _joined(*values: str | None) -> str | None:
        unique = list(dict.fromkeys(value for value in values if value))
        return " / ".join(unique) if unique else None

    @staticmethod
    def _first_value(*values: str | None) -> str | None:
        return next((value for value in values if value), None)

    @staticmethod
    def _search_text(row) -> str:
        return " ".join(
            str(value or "")
            for value in (
                row.train_id,
                row.train_no,
                row.train_name,
                row.current_station,
                row.current_section,
                row.ct.mr_name,
                row.tc.mr_name,
                row.ct.current_ap_name,
                row.tc.current_ap_name,
                row.ct.current_ap_mac,
                row.tc.current_ap_mac,
            )
        )


__all__ = ["VehicleMrOnlineQueryService"]
