from __future__ import annotations

import re
import sqlite3
import threading
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.models.api.ac_management import AcApDetailDTO, AcRadioDTO
from netconsole.models.api.ac_mesh_link import (
    AcMeshLinkPageDTO,
    AcMeshLinkRecordDTO,
    AcMeshLinkSummaryDTO,
    AcMeshMrDetailDTO,
    AcMeshMrEventDTO,
    AcMeshMrPageDTO,
    AcMeshMrStatusDTO,
    AcMeshRawTailDTO,
    AcMeshSnapshotDTO,
    AcMeshSnapshotDetailDTO,
    AcMeshSnapshotPageDTO,
)
from netconsole.services.ac.query_service import AcManagementQueryService


_FRESH_SECONDS = 30
_STALE_SECONDS = 300


def _normalize_vehicle_mac(value: object) -> str:
    from netconsole.services.vehicle_mr_online import normalize_mac

    return normalize_mac(value)


def _parse_train_identity(value: str):
    from netconsole.services.vehicle_mr_online import parse_train_identity

    return parse_train_identity(value)


def _online_link_statuses() -> set[str]:
    from netconsole.services.vehicle_mr_online import ONLINE_LINK_STATUSES

    return ONLINE_LINK_STATUSES


@dataclass(frozen=True)
class _MrDevice:
    id: int
    uuid: str
    name: str
    system_name: str
    mac_address: str
    management_ip: str
    train_no: str
    car_end: str


@dataclass(frozen=True)
class _ApCandidate:
    detail: AcApDetailDTO
    radio: AcRadioDTO | None = None


_ApIndexes = dict[str, dict[str, list[_ApCandidate]]]


class AcMeshLinkQueryService:
    """读取 Qt AC Mesh-Link 监控已落盘快照，不执行采集或写入。"""

    def __init__(
        self,
        paths: PathResolver,
        *,
        now_provider: Callable[[], datetime] | None = None,
        fresh_seconds: int = _FRESH_SECONDS,
        stale_seconds: int = _STALE_SECONDS,
    ) -> None:
        self.paths = paths
        self.ac_query = AcManagementQueryService(paths)
        self.now_provider = now_provider or datetime.now
        self.fresh_seconds = max(1, int(fresh_seconds))
        self.stale_seconds = max(self.fresh_seconds, int(stale_seconds))
        self._ap_cache: dict[str, tuple[tuple[int, int, int, int], _ApIndexes]] = {}
        self._ap_cache_lock = threading.Lock()

    def current_site_id(self) -> str:
        return self.ac_query.current_site_id()

    def get_summary(self, site_id: str) -> AcMeshLinkSummaryDTO:
        snapshot = self._latest_snapshot(site_id)
        mrs = self._mr_rows(site_id, snapshot=snapshot)
        links = self._link_rows(site_id, snapshot=snapshot)
        if snapshot is None:
            return AcMeshLinkSummaryDTO(
                site_id=site_id,
                registered_mrs=len(mrs),
                unknown_mrs=len(mrs),
                message="暂无 AC Mesh-Link 快照，请先在 Qt 列车在线页面完成采集。",
            )
        return AcMeshLinkSummaryDTO(
            site_id=site_id,
            controller_id=snapshot.controller_id,
            controller_name=snapshot.controller_name,
            registered_mrs=sum(bool(item.mr_device_id) for item in mrs),
            online_mrs=sum(item.online_status == "online" for item in mrs),
            offline_mrs=sum(item.online_status == "offline" for item in mrs),
            stale_mrs=sum(item.online_status == "stale" for item in mrs),
            unknown_mrs=sum(item.online_status == "unknown" for item in mrs),
            active_links=sum(item.data_status == "fresh" and self._is_active(item.link_status) for item in links),
            link_total=len(links),
            unmatched_links=sum(item.match_method == "unmatched" for item in links),
            offline_ap_links=sum(item.ap_online_status == "offline" for item in links),
            updated_at=snapshot.collected_at,
            age_seconds=snapshot.age_seconds,
            data_status=snapshot.data_status,
            source_type=snapshot.source_type,
            raw_available=self._raw_path(site_id, snapshot).is_file(),
            message=snapshot.error_summary,
        )

    def list_current_links(
        self,
        site_id: str,
        *,
        controller_id: str = "",
        mr_name: str = "",
        mr_mac: str = "",
        peer_ap_name: str = "",
        peer_ap_mac: str = "",
        station: str = "",
        section: str = "",
        line_side: str = "",
        link_status: str = "",
        ap_online_status: str = "",
        match_status: str = "",
        query: str = "",
        page: int = 1,
        page_size: int = 50,
        sort_by: str = "mr_name",
        sort_order: str = "asc",
    ) -> AcMeshLinkPageDTO:
        items = self._link_rows(site_id)
        filters = {
            "controller_id": controller_id,
            "mr_name": mr_name,
            "mr_mac": mr_mac,
            "peer_ap_name": peer_ap_name,
            "peer_ap_mac": peer_ap_mac,
            "station": station,
            "section": section,
            "line_side": line_side,
            "link_status": link_status,
            "ap_online_status": ap_online_status,
        }
        for field, value in filters.items():
            if value:
                needle = value.casefold()
                items = [item for item in items if needle in str(getattr(item, field)).casefold()]
        if match_status == "matched":
            items = [item for item in items if item.match_method != "unmatched"]
        elif match_status == "unmatched":
            items = [item for item in items if item.match_method == "unmatched"]
        if query:
            needle = query.casefold()
            items = [
                item
                for item in items
                if needle
                in " ".join(
                    (item.mr_name, item.mr_mac, item.peer_ap_name, item.peer_ap_mac, item.station, item.section)
                ).casefold()
            ]
        items.sort(key=lambda item: self._link_sort_key(item, sort_by), reverse=sort_order == "desc")
        return self._page_links(items, page, page_size)

    def list_unmatched_links(self, site_id: str, **kwargs) -> AcMeshLinkPageDTO:
        return self.list_current_links(site_id, match_status="unmatched", **kwargs)

    def list_mrs(
        self,
        site_id: str,
        *,
        online_status: str = "",
        train_no: str = "",
        mr_name: str = "",
        station: str = "",
        section: str = "",
        line_side: str = "",
        peer_ap_name: str = "",
        unmatched_only: bool = False,
        offline_ap_only: bool = False,
        optical_anomaly_only: bool = False,
        query: str = "",
        page: int = 1,
        page_size: int = 50,
        sort_by: str = "train_no",
        sort_order: str = "asc",
    ) -> AcMeshMrPageDTO:
        items = self._mr_rows(site_id)
        filters = {
            "online_status": online_status,
            "train_no": train_no,
            "mr_name": mr_name,
            "station": station,
            "section": section,
            "line_side": line_side,
            "peer_ap_name": peer_ap_name,
        }
        for field, value in filters.items():
            if value:
                needle = value.casefold()
                items = [item for item in items if needle in str(getattr(item, field)).casefold()]
        if unmatched_only:
            items = [item for item in items if item.match_method == "unmatched"]
        if offline_ap_only:
            items = [item for item in items if item.ap_online_status == "offline"]
        if optical_anomaly_only:
            items = [item for item in items if item.optical_status in {"warning", "critical"}]
        if query:
            needle = query.casefold()
            items = [
                item
                for item in items
                if needle
                in " ".join(
                    (item.train_display_name, item.mr_name, item.mr_mac, item.peer_ap_name, item.station, item.section)
                ).casefold()
            ]
        items.sort(key=lambda item: self._mr_sort_key(item, sort_by), reverse=sort_order == "desc")
        return self._page_mrs(items, page, page_size)

    def list_offline_mrs(self, site_id: str, **kwargs) -> AcMeshMrPageDTO:
        return self.list_mrs(site_id, online_status="offline", **kwargs)

    def get_mr_link_detail(self, site_id: str, mr_id: str) -> AcMeshMrDetailDTO | None:
        mr = next((item for item in self._mr_rows(site_id) if item.mr_id == mr_id), None)
        if mr is None:
            return None
        links = [item for item in self._link_rows(site_id) if item.mr_id == mr_id]
        return AcMeshMrDetailDTO(mr=mr, current_links=links, recent_events=self._recent_events(site_id, mr))

    def list_recent_snapshots(
        self,
        site_id: str,
        *,
        page: int = 1,
        page_size: int = 30,
    ) -> AcMeshSnapshotPageDTO:
        db_path = self._snapshot_db_path(site_id)
        if not db_path.is_file():
            return AcMeshSnapshotPageDTO(page=page, page_size=page_size)
        with closing(self._connect(db_path)) as conn:
            if not self._table_exists(conn, "vehicle_mr_online_snapshots"):
                return AcMeshSnapshotPageDTO(page=page, page_size=page_size)
            total = int(conn.execute("SELECT COUNT(*) FROM vehicle_mr_online_snapshots").fetchone()[0])
            size = max(1, min(int(page_size), 100))
            current = max(1, int(page))
            rows = conn.execute(
                """
                SELECT snapshot.*, session.ac_device_id, session.ac_name
                FROM vehicle_mr_online_snapshots snapshot
                LEFT JOIN vehicle_mr_online_sessions session ON session.session_id = snapshot.session_id
                ORDER BY snapshot.id DESC LIMIT ? OFFSET ?
                """,
                (size, (current - 1) * size),
            ).fetchall()
        devices = self._device_rows(site_id)
        return AcMeshSnapshotPageDTO(
            items=[self._snapshot_dto(site_id, dict(row), devices) for row in rows],
            total=total,
            page=current,
            page_size=size,
        )

    def get_snapshot(self, site_id: str, snapshot_id: int) -> AcMeshSnapshotDetailDTO | None:
        snapshot = self._snapshot(site_id, snapshot_id)
        if snapshot is None:
            return None
        return AcMeshSnapshotDetailDTO(snapshot=snapshot, links=self._link_rows(site_id, snapshot=snapshot))

    def get_raw_tail(self, site_id: str, *, snapshot_id: int | None = None, limit: int = 300) -> AcMeshRawTailDTO:
        snapshot = self._snapshot(site_id, snapshot_id) if snapshot_id else self._latest_snapshot(site_id)
        if snapshot is None:
            return AcMeshRawTailDTO(message="暂无 Mesh-Link 快照。")
        raw_path = self._raw_path(site_id, snapshot)
        if raw_path.is_file():
            lines = raw_path.read_text(encoding="utf-8", errors="replace").splitlines()
            selected = lines[-max(1, min(int(limit), 300)) :]
            return AcMeshRawTailDTO(
                snapshot_id=snapshot.id,
                available=True,
                lines=selected,
                line_count=len(lines),
                source_reference=self._raw_reference(site_id, snapshot),
                updated_at=snapshot.collected_at,
                message="",
            )
        return AcMeshRawTailDTO(
            snapshot_id=snapshot.id,
            source_reference=snapshot.source_reference,
            updated_at=snapshot.collected_at,
            message="现有 AC Mesh-Link 采集器仅持久化结构化快照，暂无可读取的原始回显。",
        )

    def _mr_rows(
        self,
        site_id: str,
        *,
        snapshot: AcMeshSnapshotDTO | None = None,
    ) -> list[AcMeshMrStatusDTO]:
        snapshot = snapshot or self._latest_snapshot(site_id)
        links = self._link_rows(site_id, snapshot=snapshot)
        devices = self._mr_devices(site_id)
        states = self._current_state_rows(site_id)
        links_by_device = {item.mr_device_id: item for item in links if item.mr_device_id}
        links_by_identity: dict[tuple[str, str], AcMeshLinkRecordDTO] = {}
        for item in sorted(links, key=lambda value: value.rssi or -999, reverse=True):
            links_by_identity.setdefault((item.train_no, item.car_end), item)
        states_by_train = {str(row.get("train_no") or "").zfill(2): row for row in states if row.get("train_no")}
        result: list[AcMeshMrStatusDTO] = []
        used_mr_ids: set[str] = set()
        for device in devices:
            link = links_by_device.get(device.uuid) or links_by_identity.get((device.train_no, device.car_end))
            state = states_by_train.get(device.train_no, {})
            end_prefix = "tc1" if device.car_end == "CT" else "tc2"
            last_seen = str(state.get(f"{end_prefix}_last_seen_at") or "")
            seen = bool(state.get(f"{end_prefix}_seen"))
            status = self._mr_status(snapshot, link, bool(last_seen or seen))
            row = self._mr_from_link(device, link, status, last_seen, state, end_prefix, snapshot)
            result.append(row)
            used_mr_ids.add(row.mr_id)
        for link in links:
            if link.mr_id in used_mr_ids:
                continue
            result.append(self._mr_from_unregistered_link(link))
        return result

    def _mr_from_link(
        self,
        device: _MrDevice,
        link: AcMeshLinkRecordDTO | None,
        status: str,
        last_seen: str,
        state: dict[str, object],
        end_prefix: str,
        snapshot: AcMeshSnapshotDTO | None,
    ) -> AcMeshMrStatusDTO:
        if link is not None:
            return AcMeshMrStatusDTO(
                mr_id=device.uuid,
                train_no=device.train_no,
                train_display_name=f"{device.train_no}车",
                car_end=device.car_end,
                mr_name=device.name,
                mr_mac=link.mr_mac,
                mr_device_id=device.uuid,
                management_ip=device.management_ip,
                online_status=status,
                peer_ap_id=link.peer_ap_id,
                peer_ap_name=link.peer_ap_name,
                peer_ap_mac=link.peer_ap_mac,
                mesh_radio=link.peer_radio,
                rssi=link.rssi,
                link_status=link.link_status,
                station=link.station,
                section=link.section,
                mileage=link.mileage,
                line_side=link.line_side,
                ap_online_status=link.ap_online_status,
                optical_status=link.optical_status,
                last_seen_at=link.last_seen_at,
                match_method=link.match_method,
                match_warning=link.match_warning,
                data_status=link.data_status,
            )
        ap_name = str(state.get(f"{end_prefix}_ap_name") or "")
        return AcMeshMrStatusDTO(
            mr_id=device.uuid,
            train_no=device.train_no,
            train_display_name=f"{device.train_no}车",
            car_end=device.car_end,
            mr_name=device.name,
            mr_device_id=device.uuid,
            management_ip=device.management_ip,
            online_status=status,
            peer_ap_name=ap_name,
            rssi=self._optional_int(state.get(f"{end_prefix}_rssi")),
            station=str(state.get(f"{end_prefix}_station") or ""),
            last_seen_at=last_seen,
            match_warning="最近快照未包含该 MR，显示历史状态。" if last_seen else "",
            data_status=snapshot.data_status if snapshot else "no_data",
        )

    @staticmethod
    def _mr_from_unregistered_link(link: AcMeshLinkRecordDTO) -> AcMeshMrStatusDTO:
        return AcMeshMrStatusDTO(
            mr_id=link.mr_id,
            train_no=link.train_no,
            train_display_name=f"{link.train_no}车" if link.train_no else "未登记 MR",
            car_end=link.car_end,
            mr_name=link.mr_name,
            mr_mac=link.mr_mac,
            online_status=link.mr_online_status,
            peer_ap_id=link.peer_ap_id,
            peer_ap_name=link.peer_ap_name,
            peer_ap_mac=link.peer_ap_mac,
            mesh_radio=link.peer_radio,
            rssi=link.rssi,
            link_status=link.link_status,
            station=link.station,
            section=link.section,
            mileage=link.mileage,
            line_side=link.line_side,
            ap_online_status=link.ap_online_status,
            optical_status=link.optical_status,
            last_seen_at=link.last_seen_at,
            match_method=link.match_method,
            match_warning=link.match_warning or "MR 未匹配设备管理记录。",
            data_status=link.data_status,
        )

    def _link_rows(
        self,
        site_id: str,
        *,
        snapshot: AcMeshSnapshotDTO | None = None,
    ) -> list[AcMeshLinkRecordDTO]:
        snapshot = snapshot or self._latest_snapshot(site_id)
        if snapshot is None:
            return []
        db_path = self._snapshot_db_path(site_id)
        with closing(self._connect(db_path)) as conn:
            if not self._table_exists(conn, "vehicle_mr_online_links"):
                return []
            rows = conn.execute(
                "SELECT * FROM vehicle_mr_online_links WHERE snapshot_id = ? ORDER BY id",
                (snapshot.id,),
            ).fetchall()
        devices = self._mr_devices(site_id)
        ap_indexes = self._ap_indexes(site_id)
        controller_id = snapshot.controller_id
        controller_name = snapshot.controller_name
        result: list[AcMeshLinkRecordDTO] = []
        for row in rows:
            raw = dict(row)
            identity = _parse_train_identity(str(raw.get("peer_name") or ""))
            device = self._match_mr_device(raw, devices, identity)
            candidate, method, warning = self._match_ap(raw, ap_indexes)
            radio = candidate.radio if candidate else None
            ap = candidate.detail.ap if candidate else None
            mr_id = device.uuid if device else _normalize_vehicle_mac(raw.get("peer_mac")) or self._normalize_name(raw.get("peer_name")) or f"link-{raw['id']}"
            link_status = str(raw.get("status") or "")
            result.append(
                AcMeshLinkRecordDTO(
                    id=int(raw["id"]),
                    snapshot_id=snapshot.id,
                    controller_id=controller_id,
                    controller_name=controller_name,
                    mr_id=mr_id,
                    train_no=device.train_no if device else (identity.train_no if identity else str(raw.get("train_no") or "")),
                    car_end=device.car_end if device else (identity.car_end if identity else str(raw.get("car_end") or "")),
                    mr_name=device.name if device else str(raw.get("peer_name") or ""),
                    mr_mac=_normalize_vehicle_mac(raw.get("peer_mac")),
                    mr_device_id=device.uuid if device else "",
                    mr_management_ip=device.management_ip if device else "",
                    mr_online_status=("online" if self._is_active(link_status) else "offline") if snapshot.data_status == "fresh" else "stale",
                    peer_ap_id=ap.id if ap else "",
                    peer_ap_name=ap.name if ap else str(raw.get("local_ap_name") or raw.get("matched_ap_name") or ""),
                    peer_ap_mac=ap.mac if ap else "",
                    peer_radio=f"Mesh Radio {radio.radio_id}" if radio else "",
                    mesh_interface=f"Mesh Radio {radio.radio_id}" if radio else "",
                    link_status=link_status,
                    rssi=self._optional_int(raw.get("rssi")),
                    channel=radio.channel if radio else "",
                    bandwidth=radio.bandwidth if radio else "",
                    station=ap.station if ap else str(raw.get("matched_station") or ""),
                    section=ap.section if ap else "",
                    mileage=ap.mileage if ap else "",
                    line_side=ap.direction if ap else "",
                    ap_online_status=ap.status if ap else "unknown",
                    optical_status=ap.optical_status if ap else "no_data",
                    last_seen_at=str(raw.get("ac_time") or raw.get("created_at") or snapshot.collected_at),
                    match_method=method,
                    match_warning=warning,
                    data_status=snapshot.data_status,
                )
            )
        return result

    def _ap_indexes(self, site_id: str) -> _ApIndexes:
        signature = self._path_signature(self.paths.site_db_path(site_id))
        with self._ap_cache_lock:
            cached = self._ap_cache.get(site_id)
            if cached and cached[0] == signature:
                return cached[1]
            by_mac: dict[str, list[_ApCandidate]] = {}
            by_name: dict[str, list[_ApCandidate]] = {}
            by_normalized_name: dict[str, list[_ApCandidate]] = {}
            for detail in self.ac_query.list_all_ap_details(site_id):
                candidate = _ApCandidate(detail)
                self._append_index(by_name, detail.ap.name.strip().casefold(), candidate)
                self._append_index(by_normalized_name, self._normalize_name(detail.ap.name), candidate)
                self._append_index(by_mac, _normalize_vehicle_mac(detail.ap.mac), candidate)
                for radio in detail.radios:
                    self._append_index(by_mac, _normalize_vehicle_mac(radio.bssid), _ApCandidate(detail, radio))
            indexes = {"mac": by_mac, "name": by_name, "normalized_name": by_normalized_name}
            self._ap_cache[site_id] = (signature, indexes)
            return indexes

    @staticmethod
    def _path_signature(path: Path) -> tuple[int, int, int, int]:
        wal_path = path.with_name(f"{path.name}-wal")

        def values(candidate: Path) -> tuple[int, int]:
            try:
                stat = candidate.stat()
            except FileNotFoundError:
                return 0, 0
            return stat.st_mtime_ns, stat.st_size

        return (*values(path), *values(wal_path))

    def _match_ap(
        self,
        row: dict[str, object],
        indexes: dict[str, dict[str, list[_ApCandidate]]],
    ) -> tuple[_ApCandidate | None, str, str]:
        mac = _normalize_vehicle_mac(row.get("local_mac"))
        if mac:
            candidate, warning = self._unique(indexes["mac"].get(mac, []), "Mesh Radio/BSSID MAC")
            if candidate or warning:
                return candidate, "peer_mac" if candidate else "unmatched", warning
        name = str(row.get("local_ap_name") or "").strip()
        if name:
            candidate, warning = self._unique(indexes["name"].get(name.casefold(), []), "AP 名称")
            if candidate or warning:
                return candidate, "peer_name" if candidate else "unmatched", warning
            candidate, warning = self._unique(indexes["normalized_name"].get(self._normalize_name(name), []), "规范化 AP 名称")
            if candidate or warning:
                return candidate, "normalized_peer_name" if candidate else "unmatched", warning
        return None, "unmatched", "未与当前 FIT-AP/AP 扩展信息精确匹配。"

    @staticmethod
    def _unique(candidates: list[_ApCandidate], label: str) -> tuple[_ApCandidate | None, str]:
        unique = {(item.detail.ap.id, item.radio.radio_id if item.radio else 0): item for item in candidates}
        ap_ids = {item.detail.ap.id for item in unique.values()}
        if len(ap_ids) == 1 and unique:
            return next(iter(unique.values())), ""
        if len(ap_ids) > 1:
            return None, f"{label}匹配到多个轨旁 AP，未自动选择。"
        return None, ""

    def _latest_snapshot(self, site_id: str) -> AcMeshSnapshotDTO | None:
        return self._snapshot(site_id, None)

    def _snapshot(self, site_id: str, snapshot_id: int | None) -> AcMeshSnapshotDTO | None:
        db_path = self._snapshot_db_path(site_id)
        if not db_path.is_file():
            return None
        with closing(self._connect(db_path)) as conn:
            if not self._table_exists(conn, "vehicle_mr_online_snapshots"):
                return None
            clause = "WHERE snapshot.id = ?" if snapshot_id is not None else ""
            params = (int(snapshot_id),) if snapshot_id is not None else ()
            row = conn.execute(
                f"""
                SELECT snapshot.*, session.ac_device_id, session.ac_name
                FROM vehicle_mr_online_snapshots snapshot
                LEFT JOIN vehicle_mr_online_sessions session ON session.session_id = snapshot.session_id
                {clause}
                ORDER BY snapshot.id DESC LIMIT 1
                """,
                params,
            ).fetchone()
        return self._snapshot_dto(site_id, dict(row), self._device_rows(site_id)) if row else None

    def _snapshot_dto(
        self,
        site_id: str,
        row: dict[str, object],
        devices: list[dict[str, object]],
    ) -> AcMeshSnapshotDTO:
        controller = next((item for item in devices if int(item.get("id") or 0) == int(row.get("ac_device_id") or 0)), None)
        collected_at = str(row.get("created_at") or row.get("local_time") or row.get("ac_time") or "")
        age = self._age_seconds(collected_at)
        parse_status = str(row.get("parse_status") or "")
        if parse_status and parse_status.casefold() not in {"ok", "success"}:
            data_status = "error"
        elif age is None:
            data_status = "unknown"
        elif age <= self.fresh_seconds:
            data_status = "fresh"
        elif age <= self.stale_seconds:
            data_status = "recent"
        else:
            data_status = "stale"
        live_raw = self.paths.ac_mesh_link_snapshot_dir(site_id, str(row.get("session_id") or "")).is_dir()
        return AcMeshSnapshotDTO(
            id=int(row["id"]),
            session_id=str(row.get("session_id") or ""),
            controller_id=str(controller.get("device_uuid") or "") if controller else "",
            controller_name=str(row.get("ac_name") or (controller or {}).get("name") or ""),
            site_id=site_id,
            collected_at=collected_at,
            ac_time=str(row.get("ac_time") or ""),
            source_type="ac_live_refresh" if live_raw else "vehicle_mr_online_snapshot",
            source_reference=(
                self._raw_reference_from_session(site_id, str(row.get("session_id") or ""))
                if live_raw
                else f"vehicle_mr_online.sqlite#snapshot:{row['id']}"
            ),
            data_status=data_status,
            age_seconds=age,
            link_count=int(row.get("link_count") or 0),
            parse_status=parse_status,
            error_summary=str(row.get("error_message") or ""),
        )

    def _mr_devices(self, site_id: str) -> list[_MrDevice]:
        result: list[_MrDevice] = []
        for row in self._device_rows(site_id):
            name = str(row.get("name") or "")
            system_name = str(row.get("system_name") or "")
            identity = _parse_train_identity(name) or _parse_train_identity(system_name)
            if identity is None:
                continue
            result.append(
                _MrDevice(
                    id=int(row.get("id") or 0),
                    uuid=str(row.get("device_uuid") or ""),
                    name=name or system_name,
                    system_name=system_name,
                    mac_address=_normalize_vehicle_mac(row.get("mac_address")),
                    management_ip=str(row.get("primary_address") or ""),
                    train_no=identity.train_no,
                    car_end=identity.car_end,
                )
            )
        return result

    def _device_rows(self, site_id: str) -> list[dict[str, object]]:
        db_path = self.paths.site_db_path(site_id)
        if not db_path.is_file():
            return []
        with closing(self._connect(db_path)) as conn:
            if not self._table_exists(conn, "devices"):
                return []
            rows = conn.execute(
                "SELECT id, device_uuid, name, system_name, mac_address, primary_address, device_type FROM devices"
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _match_mr_device(
        row: dict[str, object],
        devices: list[_MrDevice],
        identity,
    ) -> _MrDevice | None:
        name = str(row.get("peer_name") or "").strip().casefold()
        exact = [item for item in devices if name and name in {item.name.casefold(), item.system_name.casefold()}]
        if len(exact) == 1:
            return exact[0]
        if identity is not None:
            by_end = [item for item in devices if item.train_no == identity.train_no and item.car_end == identity.car_end]
            if len(by_end) == 1:
                return by_end[0]
        peer_mac = _normalize_vehicle_mac(row.get("peer_mac"))
        by_mac = [item for item in devices if peer_mac and item.mac_address == peer_mac]
        if len(by_mac) == 1:
            return by_mac[0]
        return None

    def _raw_path(self, site_id: str, snapshot: AcMeshSnapshotDTO) -> Path:
        return self.paths.ac_mesh_link_snapshot_dir(site_id, snapshot.session_id) / "raw" / "mesh_link_raw.log"

    def _raw_reference(self, site_id: str, snapshot: AcMeshSnapshotDTO) -> str:
        return self._raw_reference_from_session(site_id, snapshot.session_id)

    def _raw_reference_from_session(self, site_id: str, session_id: str) -> str:
        path = self.paths.ac_mesh_link_snapshot_dir(site_id, session_id) / "raw" / "mesh_link_raw.log"
        return path.relative_to(self.paths.site_dir(site_id)).as_posix()

    def _current_state_rows(self, site_id: str) -> list[dict[str, object]]:
        db_path = self._snapshot_db_path(site_id)
        if not db_path.is_file():
            return []
        with closing(self._connect(db_path)) as conn:
            if not self._table_exists(conn, "vehicle_mr_train_current_state"):
                return []
            rows = conn.execute("SELECT * FROM vehicle_mr_train_current_state").fetchall()
        return [dict(row) for row in rows]

    def _recent_events(self, site_id: str, mr: AcMeshMrStatusDTO) -> list[AcMeshMrEventDTO]:
        db_path = self._snapshot_db_path(site_id)
        if not db_path.is_file():
            return []
        end_label = "TC1" if mr.car_end == "CT" else "TC2" if mr.car_end == "CW" else ""
        with closing(self._connect(db_path)) as conn:
            if not self._table_exists(conn, "vehicle_mr_train_pass_events"):
                return []
            clauses = ["train_no = ?"]
            params: list[object] = [mr.train_no]
            if end_label:
                clauses.append("car_end_label = ?")
                params.append(end_label)
            params.append(50)
            rows = conn.execute(
                f"SELECT * FROM vehicle_mr_train_pass_events WHERE {' AND '.join(clauses)} ORDER BY id DESC LIMIT ?",
                params,
            ).fetchall()
        return [
            AcMeshMrEventDTO(
                id=int(row["id"]),
                event_time=str(row["event_time"] or row["created_at"] or ""),
                event_type=str(row["event_type"] or ""),
                status=str(row["status"] or ""),
                station=str(row["station"] or ""),
                ap_name=str(row["ap_name"] or ""),
                rssi=self._optional_int(row["rssi"]),
                car_end=str(row["car_end_label"] or row["car_end"] or ""),
            )
            for row in rows
        ]

    def _mr_status(
        self,
        snapshot: AcMeshSnapshotDTO | None,
        link: AcMeshLinkRecordDTO | None,
        has_history: bool,
    ) -> str:
        if snapshot is None or snapshot.data_status in {"error", "unknown", "no_data"}:
            return "unknown"
        if snapshot.data_status == "fresh":
            return "online" if link and self._is_active(link.link_status) else "offline"
        return "stale" if link or has_history else "unknown"

    @staticmethod
    def _is_active(status: str) -> bool:
        return str(status or "").strip().casefold() in _online_link_statuses()

    @staticmethod
    def _append_index(index: dict[str, list[_ApCandidate]], key: str, candidate: _ApCandidate) -> None:
        if key:
            index.setdefault(key, []).append(candidate)

    @staticmethod
    def _normalize_name(value: object) -> str:
        return re.sub(r"[\s_-]+", "", str(value or "").strip()).casefold()

    def _age_seconds(self, value: str) -> int | None:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            now = self.now_provider()
            if parsed.tzinfo is not None and now.tzinfo is None:
                parsed = parsed.replace(tzinfo=None)
            return max(0, int((now - parsed).total_seconds()))
        except (TypeError, ValueError):
            return None

    def _snapshot_db_path(self, site_id: str) -> Path:
        selected = SiteManager(self.paths).validate_site_name(site_id)
        return self.paths.online_mr_root(selected) / "parsed" / "vehicle_mr_online.sqlite"

    @staticmethod
    def _connect(path: Path) -> sqlite3.Connection:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (table,),
        ).fetchone() is not None

    @staticmethod
    def _optional_int(value: object) -> int | None:
        try:
            return int(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _link_sort_key(item: AcMeshLinkRecordDTO, field: str) -> object:
        if field == "rssi":
            return item.rssi if item.rssi is not None else -999
        if field == "updated_at":
            return item.last_seen_at
        if field in {"peer_ap_name", "station", "section", "link_status", "ap_online_status"}:
            return str(getattr(item, field)).casefold()
        return (item.train_no, item.car_end, item.mr_name.casefold())

    @staticmethod
    def _mr_sort_key(item: AcMeshMrStatusDTO, field: str) -> object:
        if field == "rssi":
            return item.rssi if item.rssi is not None else -999
        if field in {"online_status", "station", "section", "peer_ap_name", "last_seen_at"}:
            return str(getattr(item, field)).casefold()
        return (int(item.train_no) if item.train_no.isdigit() else 9999, item.car_end, item.mr_name.casefold())

    @staticmethod
    def _page_links(items: list[AcMeshLinkRecordDTO], page: int, page_size: int) -> AcMeshLinkPageDTO:
        current = max(1, int(page))
        size = max(1, min(int(page_size), 200))
        start = (current - 1) * size
        return AcMeshLinkPageDTO(items=items[start : start + size], total=len(items), page=current, page_size=size)

    @staticmethod
    def _page_mrs(items: list[AcMeshMrStatusDTO], page: int, page_size: int) -> AcMeshMrPageDTO:
        current = max(1, int(page))
        size = max(1, min(int(page_size), 200))
        start = (current - 1) * size
        return AcMeshMrPageDTO(items=items[start : start + size], total=len(items), page=current, page_size=size)


__all__ = ["AcMeshLinkQueryService"]
