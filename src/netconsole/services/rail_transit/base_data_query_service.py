from __future__ import annotations

import hashlib
import ipaddress
import json
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable, TypeVar

from netconsole.core.paths import PathResolver
from netconsole.models.api.rail_transit_base_data import (
    DataQualityEntityGroupDTO,
    DataQualityEntityGroupPageDTO,
    DataQualityIssueDTO,
    DataQualityIssuePageDTO,
    MileageDTO,
    MeshRadioDTO,
    RailTransitRelationDTO,
    RailTransitRelationPageDTO,
    RailTransitSummaryDTO,
    RelatedRuntimeStatusDTO,
    SectionDTO,
    SectionPageDTO,
    StationDTO,
    StationPageDTO,
    TracksideApDTO,
    TracksideApDetailDTO,
    TracksideApPageDTO,
    TrainDTO,
    TrainDetailDTO,
    TrainPageDTO,
    VehicleMrDTO,
    VehicleMrDetailDTO,
    VehicleMrPageDTO,
)
from netconsole.models.device import Device
from netconsole.services.ac.mesh_link_query_service import AcMeshLinkQueryService
from netconsole.services.ac.query_service import AcManagementQueryService
from netconsole.services.ap_extension_import import normalize_ap_mac
from netconsole.services.ap_identity.normalizers import normalize_mac
from netconsole.services.online_mr.query_service import OnlineMrQueryService
from netconsole.services.rail_transit.source_policy import is_blocking_issue
from netconsole.services.vehicle_mr_online import parse_train_identity_from_device
from netconsole.utils.mileage import parse_track_mileage


T = TypeVar("T")
_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2, "": 3}
_AP_FIELDS = (
    "id",
    "line_name",
    "system_type",
    "network_domain",
    "station_name",
    "section_name",
    "line_side",
    "direction",
    "mileage_text",
    "mileage_m",
    "ap_point_code",
    "ap_name",
    "ap_mac_norm",
    "ap_mac_display",
    "remark",
    "source_file",
    "source_sheet",
    "source_row",
    "updated_at",
    "section_start_station",
    "section_end_station",
)
_DEVICE_FIELDS = (
    "id",
    "device_uuid",
    "name",
    "system_name",
    "mac_address",
    "station",
    "location",
    "group_id",
    "device_vendor",
    "device_type",
    "primary_address",
    "backup_address",
    "protocol",
    "port",
    "remark",
    "created_at",
    "updated_at",
)


class RailTransitBaseDataQueryService:
    """轨道交通基础资料 GET-only 查询边界，不初始化或修改数据库。"""

    def __init__(
        self,
        paths: PathResolver,
        *,
        ac_query: AcManagementQueryService | None = None,
        mesh_query: AcMeshLinkQueryService | None = None,
        online_mr_query: OnlineMrQueryService | None = None,
    ) -> None:
        self.paths = paths
        self.ac_query = ac_query or AcManagementQueryService(paths)
        self.mesh_query = mesh_query or AcMeshLinkQueryService(paths)
        self.online_mr_query = online_mr_query or OnlineMrQueryService(paths)

    def current_site_id(self) -> str:
        return self.ac_query.current_site_id()

    def get_summary(self, site_id: str) -> RailTransitSummaryDTO:
        meta = self._site_meta(site_id)
        points = self._all_points(site_id, include_runtime=False)
        aps = [item for item in points if self._is_ap_record(item)]
        stations = self._stations(points)
        sections = self._sections(points)
        mrs = self._all_mrs(site_id, include_runtime=False)
        trains = self._trains(mrs, self._issues(site_id, aps=aps, mrs=mrs))
        issues = self._issues(site_id, aps=aps, mrs=mrs)
        codes = Counter(issue.code for issue in issues)
        return RailTransitSummaryDTO(
            site_id=site_id,
            site_name=str(meta.get("display_name") or site_id),
            line_name=str(meta.get("line_name") or self._first(aps, "line_name") or ""),
            project_type=str(meta.get("system_type") or ""),
            network_type=str(meta.get("network_domain") or ""),
            remark=str(meta.get("remark") or ""),
            created_at=str(meta.get("created_at") or ""),
            updated_at=max(
                [str(meta.get("updated_at") or ""), *(item.updated_at for item in aps)],
                default="",
            ),
            station_count=len(stations),
            section_count=len(sections),
            ap_count=len(aps),
            train_count=len(trains),
            mr_count=len(mrs),
            missing_location_ap_count=codes["ap_location_missing"],
            invalid_mileage_count=codes["ap_mileage_invalid"],
            duplicate_ap_mac_count=codes["ap_mac_duplicate"],
            duplicate_static_ip_count=codes["static_ip_duplicate"],
            unbound_mr_count=codes["mr_train_unbound"],
            issue_count=len(issues),
            message="站点和区间为 AP 扩展资料派生的只读视图。" if aps else "当前局点暂无轨旁 AP 扩展资料。",
        )

    def list_stations(
        self, site_id: str, *, query: str = "", page: int = 1, page_size: int = 50, sort_order: str = "asc"
    ) -> StationPageDTO:
        items = self._stations(self._all_points(site_id, include_runtime=False))
        if query:
            needle = query.casefold()
            items = [item for item in items if needle in f"{item.name} {item.code}".casefold()]
        items.sort(key=lambda item: (item.sort_order, item.name), reverse=sort_order == "desc")
        selected, current, size = self._page(items, page, page_size)
        return StationPageDTO(items=selected, total=len(items), page=current, page_size=size)

    def list_sections(
        self,
        site_id: str,
        *,
        station: str = "",
        query: str = "",
        page: int = 1,
        page_size: int = 50,
        sort_order: str = "asc",
    ) -> SectionPageDTO:
        items = self._sections(self._all_points(site_id, include_runtime=False))
        if station:
            needle = station.casefold()
            items = [
                item
                for item in items
                if needle in f"{item.start_station} {item.end_station} {item.name}".casefold()
            ]
        if query:
            needle = query.casefold()
            items = [item for item in items if needle in f"{item.name} {item.start_station} {item.end_station}".casefold()]
        items.sort(key=lambda item: (item.mileage_min is None, item.mileage_min or 0, item.name), reverse=sort_order == "desc")
        selected, current, size = self._page(items, page, page_size)
        return SectionPageDTO(items=selected, total=len(items), page=current, page_size=size)

    def list_aps(
        self,
        site_id: str,
        *,
        station: str = "",
        section: str = "",
        line_side: str = "",
        query: str = "",
        has_issue: bool | None = None,
        issue_severity: str = "",
        fit_ap_status: str = "",
        optical_status: str = "",
        page: int = 1,
        page_size: int = 50,
        sort_by: str = "name",
        sort_order: str = "asc",
    ) -> TracksideApPageDTO:
        items = self._all_aps(site_id, include_runtime=True)
        issues = self._issues(site_id, aps=self._all_aps(site_id, include_runtime=False), mrs=self._all_mrs(site_id, include_runtime=False))
        issue_map = self._issue_map(issues, "ap")
        items = [self._with_ap_issues(item, issue_map.get(item.id, [])) for item in items]
        for field, value in (("station", station), ("section", section), ("line_side", line_side)):
            if value:
                needle = value.casefold()
                items = [item for item in items if needle in str(getattr(item, field)).casefold()]
        if fit_ap_status:
            items = [item for item in items if item.runtime.fit_ap_status == fit_ap_status]
        if optical_status:
            items = [item for item in items if item.runtime.optical_status == optical_status]
        if query:
            needle = query.casefold()
            items = [item for item in items if needle in f"{item.name} {item.point_code} {item.mac} {item.management_ip}".casefold()]
        if has_issue is not None:
            items = [item for item in items if (item.issue_count > 0) is has_issue]
        if issue_severity:
            items = [item for item in items if item.highest_issue_severity == issue_severity]
        items.sort(key=lambda item: self._ap_sort_key(item, sort_by), reverse=sort_order == "desc")
        selected, current, size = self._page(items, page, page_size)
        return TracksideApPageDTO(items=selected, total=len(items), page=current, page_size=size)

    def get_ap(self, site_id: str, ap_id: str) -> TracksideApDetailDTO | None:
        item = next((row for row in self._all_aps(site_id, include_runtime=True) if row.id == ap_id), None)
        if item is None:
            return None
        issues = [issue for issue in self._issues(site_id) if issue.entity_type == "ap" and issue.entity_id == ap_id]
        return TracksideApDetailDTO(ap=self._with_ap_issues(item, issues), issues=issues)

    def list_mrs(
        self,
        site_id: str,
        *,
        train: str = "",
        mr_role: str = "",
        query: str = "",
        has_issue: bool | None = None,
        issue_severity: str = "",
        page: int = 1,
        page_size: int = 50,
        sort_by: str = "train_no",
        sort_order: str = "asc",
    ) -> VehicleMrPageDTO:
        items = self._all_mrs(site_id, include_runtime=True)
        issues = self._issues(site_id, aps=self._all_aps(site_id, include_runtime=False), mrs=self._all_mrs(site_id, include_runtime=False))
        issue_map = self._issue_map(issues, "mr")
        items = [self._with_mr_issues(item, issue_map.get(item.id, [])) for item in items]
        if train:
            needle = train.casefold()
            items = [item for item in items if needle in f"{item.train_id} {item.train_no}".casefold()]
        if mr_role:
            items = [item for item in items if item.role.casefold() == mr_role.casefold()]
        if query:
            needle = query.casefold()
            items = [item for item in items if needle in f"{item.name} {item.management_ip} {item.mac} {item.device_id}".casefold()]
        if has_issue is not None:
            items = [item for item in items if (item.issue_count > 0) is has_issue]
        if issue_severity:
            items = [item for item in items if item.highest_issue_severity == issue_severity]
        items.sort(key=lambda item: self._mr_sort_key(item, sort_by), reverse=sort_order == "desc")
        selected, current, size = self._page(items, page, page_size)
        return VehicleMrPageDTO(items=selected, total=len(items), page=current, page_size=size)

    def get_mr(self, site_id: str, mr_id: str) -> VehicleMrDetailDTO | None:
        item = next((row for row in self._all_mrs(site_id, include_runtime=True) if row.id == mr_id), None)
        if item is None:
            return None
        issues = [issue for issue in self._issues(site_id) if issue.entity_type == "mr" and issue.entity_id == mr_id]
        return VehicleMrDetailDTO(mr=self._with_mr_issues(item, issues), issues=issues)

    def list_trains(
        self,
        site_id: str,
        *,
        query: str = "",
        has_issue: bool | None = None,
        page: int = 1,
        page_size: int = 50,
        sort_order: str = "asc",
    ) -> TrainPageDTO:
        mrs = self._all_mrs(site_id, include_runtime=True)
        items = self._trains(mrs, self._issues(site_id))
        if query:
            needle = query.casefold()
            items = [item for item in items if needle in f"{item.name} {item.train_no}".casefold()]
        if has_issue is not None:
            items = [item for item in items if (item.issue_count > 0) is has_issue]
        items.sort(key=lambda item: self._natural_key(item.train_no), reverse=sort_order == "desc")
        selected, current, size = self._page(items, page, page_size)
        return TrainPageDTO(items=selected, total=len(items), page=current, page_size=size)

    def get_train(self, site_id: str, train_id: str) -> TrainDetailDTO | None:
        mrs = [item for item in self._all_mrs(site_id, include_runtime=True) if item.train_id == train_id]
        if not mrs:
            return None
        issues = [issue for issue in self._issues(site_id) if issue.entity_id in {train_id, *(item.id for item in mrs)}]
        train = self._trains(mrs, issues)[0]
        return TrainDetailDTO(train=train, mrs=mrs, issues=issues)

    def list_issues(
        self,
        site_id: str,
        *,
        severity: str = "",
        entity_type: str = "",
        query: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> DataQualityIssuePageDTO:
        items = self._issues(site_id)
        if severity:
            items = [item for item in items if item.severity == severity]
        if entity_type:
            items = [item for item in items if item.entity_type == entity_type]
        if query:
            needle = query.casefold()
            items = [item for item in items if needle in f"{item.entity_name} {item.code} {item.message} {item.original_value}".casefold()]
        items.sort(key=lambda item: (_SEVERITY_ORDER[item.severity], item.entity_type, item.entity_name, item.code))
        selected, current, size = self._page(items, page, page_size)
        return DataQualityIssuePageDTO(items=selected, total=len(items), page=current, page_size=size)

    def list_issue_groups(
        self,
        site_id: str,
        *,
        blocking_only: bool | None = None,
        needs_confirmation_only: bool | None = None,
        query: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> DataQualityEntityGroupPageDTO:
        issues = self._issues(site_id)
        grouped: dict[tuple[str, str], list[DataQualityIssueDTO]] = defaultdict(list)
        for issue in issues:
            grouped[(issue.entity_type, issue.entity_id)].append(issue)
        items = []
        for (entity_type, entity_id), rows in grouped.items():
            blocking = any(row.blocking for row in rows)
            needs_confirmation = not blocking and any(row.severity == "warning" for row in rows)
            actions = list(dict.fromkeys(row.suggested_action for row in rows if row.suggested_action))
            items.append(
                DataQualityEntityGroupDTO(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    display_name=next((row.entity_name for row in rows if row.entity_name), entity_id),
                    issue_count=len(rows),
                    error_count=sum(row.severity == "error" for row in rows),
                    warning_count=sum(row.severity == "warning" for row in rows),
                    info_count=sum(row.severity == "info" for row in rows),
                    blocking=blocking,
                    needs_confirmation=needs_confirmation,
                    issues=rows,
                    suggested_action="；".join(actions),
                )
            )
        if blocking_only is not None:
            items = [item for item in items if item.blocking is blocking_only]
        if needs_confirmation_only is not None:
            items = [item for item in items if item.needs_confirmation is needs_confirmation_only]
        if query:
            needle = query.casefold()
            items = [
                item
                for item in items
                if needle
                in f"{item.entity_type} {item.display_name} {item.suggested_action} {' '.join(row.code for row in item.issues)}".casefold()
            ]
        items.sort(key=lambda item: (not item.blocking, -item.error_count, -item.warning_count, item.display_name))
        selected, current, size = self._page(items, page, page_size)
        return DataQualityEntityGroupPageDTO(
            items=selected,
            total=len(items),
            issue_total=len(issues),
            blocking_total=sum(item.blocking for item in items),
            warning_total=sum(issue.severity == "warning" for issue in issues),
            info_total=sum(issue.severity == "info" for issue in issues),
            code_counts=dict(Counter(issue.code for issue in issues)),
            page=current,
            page_size=size,
        )

    def list_relations(
        self, site_id: str, *, query: str = "", page: int = 1, page_size: int = 50
    ) -> RailTransitRelationPageDTO:
        try:
            links = self.mesh_query.list_current_links(site_id, page=1, page_size=200).items
        except (OSError, ValueError, sqlite3.Error):
            links = []
        items = [
            RailTransitRelationDTO(
                mr_id=item.mr_device_id or item.mr_id,
                mr_name=item.mr_name,
                train_no=item.train_no,
                ap_id=item.peer_ap_id,
                ap_name=item.peer_ap_name,
                station=item.station,
                section=item.section,
                status=item.mr_online_status,
                updated_at=item.last_seen_at,
            )
            for item in links
        ]
        if query:
            needle = query.casefold()
            items = [item for item in items if needle in f"{item.mr_name} {item.ap_name} {item.station} {item.section}".casefold()]
        selected, current, size = self._page(items, page, page_size)
        return RailTransitRelationPageDTO(items=selected, total=len(items), page=current, page_size=size)

    def known_locations(self, site_id: str) -> tuple[set[str], set[str]]:
        points = self._all_points(site_id, include_runtime=False)
        return ({item.name for item in self._stations(points)}, {item.name for item in self._sections(points)})

    def _all_aps(self, site_id: str, *, include_runtime: bool) -> list[TracksideApDTO]:
        return [item for item in self._all_points(site_id, include_runtime=include_runtime) if self._is_ap_record(item)]

    def _all_points(self, site_id: str, *, include_runtime: bool) -> list[TracksideApDTO]:
        rows = self._read_rows(site_id, "ap_extension_points", _AP_FIELDS)
        ac_by_mac: dict[str, Any] = {}
        ac_by_name: dict[str, Any] = {}
        links_by_ap: dict[str, list[Any]] = defaultdict(list)
        if include_runtime:
            try:
                for detail in self.ac_query.list_all_ap_details(site_id):
                    mac_key = self._mac_key(detail.ap.mac)
                    if mac_key:
                        ac_by_mac[mac_key] = detail
                    ac_by_name[detail.ap.name.casefold()] = detail
            except (OSError, ValueError, sqlite3.Error):
                pass
            try:
                for link in self.mesh_query.list_current_links(site_id, page=1, page_size=200).items:
                    for key in (self._mac_key(link.peer_ap_mac), link.peer_ap_name.casefold()):
                        if key:
                            links_by_ap[key].append(link)
            except (OSError, ValueError, sqlite3.Error):
                pass
        result: list[TracksideApDTO] = []
        for row in rows:
            name = str(row.get("ap_name") or "")
            mac_key = self._mac_key(row.get("ap_mac_norm") or row.get("ap_mac_display"))
            ac = ac_by_mac.get(mac_key) or ac_by_name.get(name.casefold())
            links = links_by_ap.get(mac_key) or links_by_ap.get(name.casefold()) or []
            parsed = self._mileage(row.get("mileage_text"), row.get("mileage_m"))
            radios = []
            if ac:
                radios = [
                    MeshRadioDTO(
                        radio_id=radio.radio_id,
                        channel=radio.channel,
                        bandwidth=radio.bandwidth,
                        power=radio.tx_power,
                        bssid=radio.bssid,
                    )
                    for radio in ac.radios
                    if radio.radio_id <= 2
                ]
            related_names = sorted({link.mr_name for link in links if link.mr_name})
            runtime = RelatedRuntimeStatusDTO(
                fit_ap_status=ac.ap.status if ac else "unknown",
                optical_status=ac.optical.optical_status if ac else "no_data",
                mesh_status="online" if links else "unknown",
                mesh_related_name="、".join(related_names),
                updated_at=max([*(link.last_seen_at for link in links), ac.ap.updated_at if ac else ""], default=""),
            )
            result.append(
                TracksideApDTO(
                    id=f"ap:{row.get('id')}",
                    site_id=site_id,
                    line_name=str(row.get("line_name") or ""),
                    name=name,
                    point_code=str(row.get("ap_point_code") or ""),
                    mac=self._display_mac(row.get("ap_mac_norm") or row.get("ap_mac_display")),
                    management_ip=ac.ap.ip if ac else "",
                    model=ac.ap.model if ac else "",
                    station=str(row.get("station_name") or ""),
                    section=str(row.get("section_name") or ""),
                    section_start_station=str(row.get("section_start_station") or ""),
                    section_end_station=str(row.get("section_end_station") or ""),
                    mileage=parsed,
                    line_side=str(row.get("line_side") or ""),
                    direction=str(row.get("direction") or ""),
                    radios=radios,
                    remark=str(row.get("remark") or ""),
                    source_file=Path(str(row.get("source_file") or "")).name,
                    source_sheet=str(row.get("source_sheet") or ""),
                    source_row=self._int_or_none(row.get("source_row")),
                    updated_at=str(row.get("updated_at") or ""),
                    runtime=runtime,
                )
            )
        return result

    def _all_mrs(self, site_id: str, *, include_runtime: bool) -> list[VehicleMrDTO]:
        db_path = self.paths.site_db_path(site_id)
        if not db_path.is_file():
            return []
        with closing(self._connect(db_path)) as conn:
            rows = self._select_rows(conn, "devices", _DEVICE_FIELDS)
            groups = {
                int(row["id"]): str(row["name"] or "")
                for row in self._select_rows(conn, "device_groups", ("id", "name"))
                if row.get("id") is not None
            }
        has_mr_group = any("车载-MR" in name for name in groups.values())
        mesh_by_id: dict[str, Any] = {}
        mesh_by_name: dict[str, Any] = {}
        session_by_name: dict[str, Any] = {}
        if include_runtime:
            try:
                for item in self.mesh_query.list_mrs(site_id, page=1, page_size=200).items:
                    if item.mr_device_id:
                        mesh_by_id[item.mr_device_id] = item
                    mesh_by_name[item.mr_name.casefold()] = item
            except (OSError, ValueError, sqlite3.Error):
                pass
            try:
                for item in self.online_mr_query.list_sessions(site_id, limit=1000):
                    session_by_name.setdefault(item.mr_name.casefold(), item)
            except (OSError, ValueError, sqlite3.Error):
                pass
        result: list[VehicleMrDTO] = []
        for row in rows:
            group_name = groups.get(int(row.get("group_id") or 0), "")
            device = Device.from_mapping(row)
            identity = parse_train_identity_from_device(device)
            if identity is None:
                continue
            if has_mr_group and "车载-MR" not in group_name:
                continue
            if not has_mr_group and "MR" not in f"{row.get('name')} {row.get('device_type')}".upper():
                continue
            item_id = str(row.get("device_uuid") or f"device:{row.get('id')}")
            mesh = mesh_by_id.get(item_id) or mesh_by_name.get(str(row.get("name") or "").casefold())
            session = session_by_name.get(str(row.get("name") or "").casefold())
            runtime = RelatedRuntimeStatusDTO(
                mesh_status=mesh.online_status if mesh else "unknown",
                mesh_related_name=mesh.peer_ap_name if mesh else "",
                latest_session_id=session.session_id if session else "",
                latest_session_status=session.status if session else "",
                updated_at=max(mesh.last_seen_at if mesh else "", session.started_at if session else ""),
            )
            result.append(
                VehicleMrDTO(
                    id=item_id,
                    device_id=self._int_or_none(row.get("id")),
                    name=str(row.get("name") or ""),
                    train_id=identity.train_id,
                    train_no=identity.train_no,
                    role="TC" if identity.car_end == "CW" else identity.car_end,
                    management_ip=str(row.get("primary_address") or ""),
                    mac=self._display_mac(row.get("mac_address")),
                    protocol=str(row.get("protocol") or ""),
                    port=self._int_or_none(row.get("port")),
                    remark=str(row.get("remark") or ""),
                    runtime=runtime,
                )
            )
        return result

    def _issues(
        self,
        site_id: str,
        *,
        aps: list[TracksideApDTO] | None = None,
        mrs: list[VehicleMrDTO] | None = None,
    ) -> list[DataQualityIssueDTO]:
        aps = aps if aps is not None else self._all_aps(site_id, include_runtime=False)
        mrs = mrs if mrs is not None else self._all_mrs(site_id, include_runtime=False)
        issues: list[DataQualityIssueDTO] = []
        ap_macs = Counter(self._mac_key(ap.mac) for ap in aps if self._mac_key(ap.mac))
        for ap in aps:
            if not ap.name:
                issues.append(self._issue("warning", "ap_name_missing", "ap", ap.id, ap.name, "name", "", "AP 正式名称为空", "补充正式 AP 名称"))
            mac_key = self._mac_key(ap.mac)
            if not ap.mac:
                issues.append(self._issue("warning", "ap_mac_missing", "ap", ap.id, ap.name, "mac", "", "AP MAC 为空", "补充有效 AP MAC"))
            elif not mac_key:
                issues.append(self._issue("error", "ap_mac_invalid", "ap", ap.id, ap.name, "mac", ap.mac, "AP MAC 格式无效", "补充有效 AP MAC"))
            elif ap_macs[mac_key] > 1:
                issues.append(self._issue("error", "ap_mac_duplicate", "ap", ap.id, ap.name, "mac", ap.mac, "同一局点存在重复 AP MAC", "核对 AP 点表"))
            if not ap.station and not ap.section:
                issues.append(self._issue("warning", "ap_location_missing", "ap", ap.id, ap.name, "station/section", "", "AP 未填写站点或区间", "补充位置归属"))
            if not ap.mileage.raw:
                issues.append(self._issue("warning", "ap_mileage_missing", "ap", ap.id, ap.name, "mileage", "", "AP 里程为空", "补充正式里程"))
            elif not ap.mileage.valid:
                issues.append(self._issue("error", "ap_mileage_invalid", "ap", ap.id, ap.name, "mileage", ap.mileage.raw, ap.mileage.error or "里程格式无效", "按现有 ZDK/YDK/CDK/RDK 格式修正"))
            expected = self._expected_prefix(ap.line_side, ap.direction)
            if ap.mileage.valid and expected and ap.mileage.line_type and expected != ap.mileage.line_type:
                issues.append(self._issue("warning", "ap_mileage_direction_mismatch", "ap", ap.id, ap.name, "mileage", ap.mileage.raw, "里程前缀与线路方向不一致", "核对线别和里程前缀"))
        mr_macs = Counter(self._mac_key(mr.mac) for mr in mrs if self._mac_key(mr.mac))
        role_counts = Counter((mr.train_id, mr.role) for mr in mrs if mr.train_id and mr.role)
        for mr in mrs:
            if not mr.train_id:
                issues.append(self._issue("error", "mr_train_unbound", "mr", mr.id, mr.name, "train", "", "MR 未关联列车", "核对正式 MR 命名或设备分组"))
            mac_key = self._mac_key(mr.mac)
            if not mac_key:
                issues.append(self._issue("warning", "mr_mac_missing", "mr", mr.id, mr.name, "mac", mr.mac, "MR MAC 为空或格式无效", "补充有效 MR MAC"))
            elif mr_macs[mac_key] > 1:
                issues.append(self._issue("error", "mr_mac_duplicate", "mr", mr.id, mr.name, "mac", mr.mac, "同一局点存在重复 MR MAC", "核对车载 MR 资料"))
            if mr.train_id and mr.role and role_counts[(mr.train_id, mr.role)] > 1:
                issues.append(self._issue("error", "mr_role_duplicate", "mr", mr.id, mr.name, "role", mr.role, "同一列车存在重复 MR 角色", "核对列车 MR 配置"))
        issues.extend(self._unbound_mr_issues(site_id))
        issues.extend(self._static_ip_issues(site_id))
        return issues

    def _unbound_mr_issues(self, site_id: str) -> list[DataQualityIssueDTO]:
        db_path = self.paths.site_db_path(site_id)
        if not db_path.is_file():
            return []
        with closing(self._connect(db_path)) as conn:
            rows = self._select_rows(conn, "devices", _DEVICE_FIELDS)
            groups = {
                int(row["id"]): str(row["name"] or "")
                for row in self._select_rows(conn, "device_groups", ("id", "name"))
                if row.get("id") is not None
            }
        result = []
        for row in rows:
            if "车载-MR" not in groups.get(int(row.get("group_id") or 0), ""):
                continue
            if parse_train_identity_from_device(Device.from_mapping(row)) is not None:
                continue
            entity_id = str(row.get("device_uuid") or f"device:{row.get('id')}")
            result.append(
                self._issue(
                    "error",
                    "mr_train_unbound",
                    "mr",
                    entity_id,
                    str(row.get("name") or ""),
                    "train",
                    "",
                    "MR 名称无法关联正式列车",
                    "核对正式 MR 命名；Agent 临时名称不得自动转为正式资产",
                )
            )
        return result

    def _static_ip_issues(self, site_id: str) -> list[DataQualityIssueDTO]:
        db_path = self.paths.site_db_path(site_id)
        if not db_path.is_file():
            return []
        with closing(self._connect(db_path)) as conn:
            rows = self._select_rows(conn, "devices", _DEVICE_FIELDS)
            groups = {
                int(row["id"]): str(row["name"] or "")
                for row in self._select_rows(conn, "device_groups", ("id", "name"))
                if row.get("id") is not None
            }
        candidates: list[tuple[dict[str, Any], str]] = []
        issues: list[DataQualityIssueDTO] = []
        for row in rows:
            ip = str(row.get("primary_address") or "").strip()
            device_type = str(row.get("device_type") or "").upper()
            group = groups.get(int(row.get("group_id") or 0), "")
            is_vehicle_mr = "车载-MR" in group
            is_dynamic_ap = device_type in {"FIT-AP", "CLOUD-AP"} and not is_vehicle_mr
            if is_dynamic_ap or not ip:
                continue
            entity_id = str(row.get("device_uuid") or f"device:{row.get('id')}")
            try:
                normalized = str(ipaddress.ip_address(ip))
            except ValueError:
                issues.append(self._issue("error", "static_ip_invalid", "device", entity_id, str(row.get("name") or ""), "primary_address", ip, "静态设备 IP 格式无效", "修正设备管理 IP"))
                continue
            candidates.append((row, normalized))
        counts = Counter(ip for _, ip in candidates)
        for row, ip in candidates:
            if counts[ip] > 1:
                entity_id = str(row.get("device_uuid") or f"device:{row.get('id')}")
                issues.append(self._issue("error", "static_ip_duplicate", "device", entity_id, str(row.get("name") or ""), "primary_address", ip, "同一局点静态设备 IP 重复", "核对设备点表；FIT-AP DHCP 地址不参与此规则"))
        return issues

    def _stations(self, aps: list[TracksideApDTO]) -> list[StationDTO]:
        names = {ap.station for ap in aps if ap.station}
        names.update(ap.section_start_station for ap in aps if ap.section_start_station)
        names.update(ap.section_end_station for ap in aps if ap.section_end_station)
        result = []
        for index, name in enumerate(sorted(names, key=self._natural_key), 1):
            related = [ap for ap in aps if ap.station == name and self._is_ap_record(ap)]
            section_names = {
                ap.section
                for ap in aps
                if ap.section and name in {ap.station, ap.section_start_station, ap.section_end_station}
            }
            mileages = [ap.mileage.meters for ap in related if ap.mileage.meters is not None]
            result.append(
                StationDTO(
                    id=self._derived_id("station", name),
                    name=name,
                    line_name=next((ap.line_name for ap in related if ap.line_name), ""),
                    sort_order=index,
                    ap_count=len(related),
                    section_count=len(section_names),
                    mileage_min=min(mileages, default=None),
                    mileage_max=max(mileages, default=None),
                )
            )
        return result

    def _sections(self, aps: list[TracksideApDTO]) -> list[SectionDTO]:
        grouped: dict[tuple[str, str, str, str], list[TracksideApDTO]] = defaultdict(list)
        for ap in aps:
            if ap.section:
                grouped[(ap.section, ap.section_start_station, ap.section_end_station, ap.line_side)].append(ap)
        result = []
        for key, rows in grouped.items():
            name, start, end, line_side = key
            ap_rows = [ap for ap in rows if self._is_ap_record(ap)]
            mileages = [ap.mileage.meters for ap in ap_rows if ap.mileage.meters is not None]
            result.append(
                SectionDTO(
                    id=self._derived_id("section", *key),
                    name=name,
                    start_station=start,
                    end_station=end,
                    line_side=line_side,
                    ap_count=len(ap_rows),
                    mileage_min=min(mileages, default=None),
                    mileage_max=max(mileages, default=None),
                )
            )
        return result

    def _trains(self, mrs: list[VehicleMrDTO], issues: list[DataQualityIssueDTO]) -> list[TrainDTO]:
        grouped: dict[str, list[VehicleMrDTO]] = defaultdict(list)
        for mr in mrs:
            grouped[mr.train_id].append(mr)
        result = []
        for train_id, rows in grouped.items():
            issue_rows = [issue for issue in issues if issue.entity_id in {train_id, *(row.id for row in rows)}]
            sessions = [row.runtime.latest_session_id for row in rows if row.runtime.latest_session_id]
            statuses = [row.runtime.mesh_status for row in rows]
            result.append(
                TrainDTO(
                    id=train_id,
                    train_no=rows[0].train_no,
                    name=train_id,
                    mr_count=len(rows),
                    roles=sorted({row.role for row in rows if row.role}),
                    latest_mesh_status="online" if "online" in statuses else statuses[0] if statuses else "unknown",
                    latest_session_id=sessions[0] if sessions else "",
                    issue_count=len(issue_rows),
                    highest_issue_severity=self._highest(issue_rows),
                )
            )
        return result

    def _read_rows(self, site_id: str, table: str, fields: Iterable[str]) -> list[dict[str, Any]]:
        path = self.paths.site_db_path(site_id)
        if not path.is_file():
            return []
        with closing(self._connect(path)) as conn:
            return self._select_rows(conn, table, fields)

    @staticmethod
    def _connect(path: Path) -> sqlite3.Connection:
        uri = f"file:{path.resolve().as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=2.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        return conn

    @staticmethod
    def _select_rows(conn: sqlite3.Connection, table: str, fields: Iterable[str]) -> list[dict[str, Any]]:
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        if not exists:
            return []
        columns = {str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")')}
        selected = [field for field in fields if field in columns]
        if not selected:
            return []
        sql = ", ".join(f'"{field}"' for field in selected)
        return [dict(row) for row in conn.execute(f'SELECT {sql} FROM "{table}"')]

    def _site_meta(self, site_id: str) -> dict[str, Any]:
        path = self.paths.site_dir(site_id) / "site_meta.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _mileage(raw: Any, meters: Any) -> MileageDTO:
        parsed = parse_track_mileage(raw if str(raw or "").strip() else meters)
        return MileageDTO(
            raw=str(raw or ""),
            normalized=parsed.display if parsed.meters is not None else "",
            meters=parsed.meters,
            line_type=parsed.prefix or "",
            valid=parsed.meters is not None and not parsed.error,
            error=parsed.error or "",
        )

    @staticmethod
    def _expected_prefix(line_side: str, direction: str) -> str:
        text = f"{line_side} {direction}"
        if "左" in text or "下行" in text:
            return "ZDK"
        if "右" in text or "上行" in text:
            return "YDK"
        if "出" in text:
            return "CDK"
        if "入" in text:
            return "RDK"
        return ""

    @staticmethod
    def _issue(severity: str, code: str, entity_type: str, entity_id: str, entity_name: str, field: str, original: str, message: str, action: str) -> DataQualityIssueDTO:
        return DataQualityIssueDTO(
            severity=severity,  # type: ignore[arg-type]
            code=code,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            field_name=field,
            original_value=str(original or ""),
            message=message,
            suggested_action=action,
            blocking=is_blocking_issue(code, severity),
        )

    @staticmethod
    def _issue_map(issues: list[DataQualityIssueDTO], entity_type: str) -> dict[str, list[DataQualityIssueDTO]]:
        result: dict[str, list[DataQualityIssueDTO]] = defaultdict(list)
        for issue in issues:
            if issue.entity_type == entity_type:
                result[issue.entity_id].append(issue)
        return result

    def _with_ap_issues(self, item: TracksideApDTO, issues: list[DataQualityIssueDTO]) -> TracksideApDTO:
        return item.model_copy(update={"issue_count": len(issues), "highest_issue_severity": self._highest(issues)})

    def _with_mr_issues(self, item: VehicleMrDTO, issues: list[DataQualityIssueDTO]) -> VehicleMrDTO:
        return item.model_copy(update={"issue_count": len(issues), "highest_issue_severity": self._highest(issues)})

    @staticmethod
    def _highest(issues: list[DataQualityIssueDTO]) -> str:
        return min((issue.severity for issue in issues), key=lambda value: _SEVERITY_ORDER[value], default="")

    @staticmethod
    def _mac_key(value: Any) -> str:
        normalized = normalize_mac(value)
        if normalized:
            return normalized.replace(":", "")
        return normalize_ap_mac(value).normalized

    @classmethod
    def _display_mac(cls, value: Any) -> str:
        key = cls._mac_key(value)
        return ":".join(key[index : index + 2] for index in range(0, 12, 2)) if key else str(value or "")

    @classmethod
    def _is_ap_record(cls, item: TracksideApDTO) -> bool:
        return bool(item.name or item.mac or item.point_code.strip() not in {"", "-"})

    @staticmethod
    def _derived_id(prefix: str, *parts: str) -> str:
        digest = hashlib.sha1("\0".join(parts).encode("utf-8")).hexdigest()[:12]
        return f"{prefix}:{digest}"

    @staticmethod
    def _page(items: list[T], page: int, page_size: int) -> tuple[list[T], int, int]:
        current = max(1, int(page))
        size = max(1, min(int(page_size), 200))
        start = (current - 1) * size
        return items[start : start + size], current, size

    @staticmethod
    def _natural_key(value: str) -> tuple[Any, ...]:
        import re

        return tuple(int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", str(value or "")))

    @staticmethod
    def _ap_sort_key(item: TracksideApDTO, sort_by: str) -> Any:
        mapping = {
            "name": item.name.casefold(),
            "station": item.station.casefold(),
            "section": item.section.casefold(),
            "mileage": (item.mileage.meters is None, item.mileage.meters or 0),
            "updated_at": item.updated_at,
        }
        return mapping.get(sort_by, mapping["name"])

    @classmethod
    def _mr_sort_key(cls, item: VehicleMrDTO, sort_by: str) -> Any:
        return {
            "train_no": cls._natural_key(item.train_no),
            "name": item.name.casefold(),
            "role": item.role.casefold(),
            "ip": item.management_ip,
        }.get(sort_by, cls._natural_key(item.train_no))

    @staticmethod
    def _int_or_none(value: Any) -> int | None:
        try:
            return int(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _first(items: list[Any], field: str) -> str:
        return next((str(getattr(item, field)) for item in items if getattr(item, field, "")), "")


__all__ = ["RailTransitBaseDataQueryService"]
