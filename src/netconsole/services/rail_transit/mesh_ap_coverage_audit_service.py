from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from typing import Any, Iterable

from netconsole.core.database import Database
from netconsole.models.api.mesh_analysis import (
    MeshApCoverageAuditDTO,
    MeshApCoverageRowDTO,
    MeshApCoverageSourceDTO,
    MeshApCoverageSummaryDTO,
)
from netconsole.services.ap_identity import ApIdentityQueryService
from netconsole.services.ap_identity.normalizers import format_mac, normalize_mac_key
from netconsole.services.rail_transit.base_data_query_service import (
    RailTransitBaseDataQueryService,
)


_NON_MAINLINE_KEYWORDS = ("车辆段", "停车场", "出入段线", "出段线", "入段线")
_NON_MAINLINE_CLASSES = {
    "DEPOT": "车辆段",
    "PARKING_YARD": "停车场",
    "STABLING": "停车场",
    "DEPOT_CONNECTION": "出入段线",
    "TEST_TRACK": "非正线试验线",
    "NON_MAINLINE": "非正线",
}


class MeshApCoverageAuditError(ValueError):
    pass


@dataclass(frozen=True)
class _ObservedAp:
    raw_mac: str
    name: str
    source_index: int
    active_count: int
    standby_count: int
    triangle_count: int
    first_seen: str
    last_seen: str
    station: str
    section: str


class MeshApCoverageAuditService:
    """Compare two parsed MESH sources with current FIT-AP resources.

    This is a read-only aggregation.  It never opens, decompresses or reparses
    raw MESH logs; per-source detail SQLite is the only observation source.
    """

    def __init__(
        self,
        query_service: Any,
        base_query: RailTransitBaseDataQueryService,
        *,
        identity_query: ApIdentityQueryService | None = None,
    ) -> None:
        self.query_service = query_service
        self.base_query = base_query
        self._identity_query = identity_query

    def audit(self, site_id: str, session_ids: Iterable[str]) -> MeshApCoverageAuditDTO:
        selected = [str(value or "").strip() for value in session_ids]
        if len(selected) != 2 or not all(selected) or selected[0] == selected[1]:
            raise MeshApCoverageAuditError("请选择两个不同的 MESH 来源进行 AP 覆盖核查。")
        contexts = [self.query_service._context(site_id, session_id) for session_id in selected]
        if any(context.site_id != site_id for context in contexts):
            raise MeshApCoverageAuditError("核查来源必须属于当前局点。")
        if any(context.detail_db is None or not context.detail_db.is_file() for context in contexts):
            raise MeshApCoverageAuditError("所选来源缺少可用的结构化 MESH 结果，请先重新解析。")

        sources = [self._source_dto(context) for context in contexts]
        observed = [self._observed_rows(context, index) for index, context in enumerate(contexts)]
        identity_query = self._identity(site_id)
        observed_by_ap, unmatched = self._resolve_observed(observed, identity_query)
        expected, excluded_expected, all_fit_keys = self._expected_fit_aps(site_id, identity_query)

        route_stations, route_sections = self._route_scope(observed_by_ap.values())
        route_expected_keys = {
            key
            for key, row in expected.items()
            if self._in_route_scope(row, route_stations, route_sections)
        }
        route_scope_mode = "observed_route" if route_expected_keys else "all_mainline_fallback"
        scoped_expected_keys = route_expected_keys or set(expected)

        connected: list[MeshApCoverageRowDTO] = []
        unconnected: list[MeshApCoverageRowDTO] = []
        for key, row in expected.items():
            seen = observed_by_ap.get(key)
            payload = self._merge_expected_observed(row, seen, key in scoped_expected_keys)
            if seen is None:
                unconnected.append(payload)
            else:
                connected.append(payload)

        unmatched_rows = [
            self._unmatched_dto(item)
            for key, item in unmatched.items()
            if key not in all_fit_keys
        ]
        excluded = [
            self._merge_expected_observed(
                row,
                observed_by_ap.get(key),
                False,
                result="excluded",
            )
            for key, row in excluded_expected.items()
        ]
        connected.sort(key=self._row_sort_key)
        unconnected.sort(key=self._row_sort_key)
        unmatched_rows.sort(key=self._row_sort_key)
        excluded.sort(key=self._row_sort_key)

        scoped_connected = sum(1 for row in connected if row.in_observed_route_scope)
        scoped_unconnected = sum(1 for row in unconnected if row.in_observed_route_scope)
        expected_count = len(scoped_expected_keys)
        return MeshApCoverageAuditDTO(
            site_id=site_id,
            sources=sources,
            summary=MeshApCoverageSummaryDTO(
                expected_mainline_count=len(expected),
                expected_route_scope_count=expected_count,
                connected_count=scoped_connected,
                unconnected_count=scoped_unconnected,
                full_mainline_connected_count=len(connected),
                full_mainline_unconnected_count=len(unconnected),
                observed_count=len(observed_by_ap),
                unmatched_observed_count=len(unmatched_rows),
                excluded_count=len(excluded),
                coverage_percent=round((scoped_connected / expected_count) * 100, 2) if expected_count else 0.0,
                route_scope_mode=route_scope_mode,
                observed_station_count=len(route_stations),
                observed_section_count=len(route_sections),
            ),
            connected=connected,
            unconnected=unconnected,
            unmatched=unmatched_rows,
            excluded=excluded,
        )

    def _identity(self, site_id: str) -> ApIdentityQueryService:
        if self._identity_query is None:
            self._identity_query = ApIdentityQueryService(
                Database(self.base_query.paths.site_db_path(site_id)), site_id=site_id
            )
        return self._identity_query

    @staticmethod
    def _source_dto(context: Any) -> MeshApCoverageSourceDTO:
        return MeshApCoverageSourceDTO(
            session_id=context.session_id,
            mr_name=context.mr_name,
            original_filename=str(
                context.source.get("original_filename")
                or context.source.get("archived_filename")
                or ""
            ),
            first_sample_time=str(context.source.get("first_sample_time") or "") or None,
            last_sample_time=str(context.source.get("last_sample_time") or "") or None,
        )

    def _observed_rows(self, context: Any, source_index: int) -> list[_ObservedAp]:
        with closing(self.query_service._connect_readonly(context.detail_db)) as conn:
            columns = self.query_service._table_columns(conn, "mesh_links")
            required = {"link_count", "link_state", "sample_time"}
            if not required.issubset(columns):
                raise MeshApCoverageAuditError("所选来源的结构化 MESH 结果版本过旧，请先重新解析。")
            mac_columns = [name for name in ("peer_radio_mac", "peer_mac_normalized", "peer_mac_raw") if name in columns]
            if not mac_columns:
                raise MeshApCoverageAuditError("所选来源缺少 Peer MAC 身份字段，请先重新解析。")
            mac_expr = "COALESCE(" + ", ".join(f"NULLIF({name}, '')" for name in mac_columns) + ", '')"
            name_expr = "MAX(COALESCE(peer_ap_name, ''))" if "peer_ap_name" in columns else "''"
            station_expr = "MAX(COALESCE(peer_site, ''))" if "peer_site" in columns else "''"
            section_expr = "MAX(COALESCE(peer_section, ''))" if "peer_section" in columns else "''"
            link_count_expr = "SUM(CASE WHEN link_count = 2 THEN 1 ELSE 0 END)"
            rows = conn.execute(
                f"""
                SELECT {mac_expr} AS peer_mac,
                       {name_expr} AS peer_name,
                       {station_expr} AS station,
                       {section_expr} AS section,
                       SUM(CASE WHEN link_state = 'ACTIVE' THEN 1 ELSE 0 END) AS active_count,
                       SUM(CASE WHEN link_state = 'STANDBY' THEN 1 ELSE 0 END) AS standby_count,
                       {link_count_expr} AS triangle_count,
                       MIN(sample_time) AS first_seen,
                       MAX(sample_time) AS last_seen
                FROM mesh_links
                WHERE link_count > 0 AND link_state IN ('ACTIVE', 'STANDBY')
                  AND {mac_expr} <> ''
                GROUP BY {mac_expr}
                """
            ).fetchall()
        return [
            _ObservedAp(
                raw_mac=str(row["peer_mac"] or ""),
                name=str(row["peer_name"] or ""),
                source_index=source_index,
                active_count=int(row["active_count"] or 0),
                standby_count=int(row["standby_count"] or 0),
                triangle_count=int(row["triangle_count"] or 0),
                first_seen=str(row["first_seen"] or ""),
                last_seen=str(row["last_seen"] or ""),
                station=str(row["station"] or ""),
                section=str(row["section"] or ""),
            )
            for row in rows
        ]

    def _resolve_observed(
        self,
        source_rows: list[list[_ObservedAp]],
        identity_query: ApIdentityQueryService,
    ) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
        all_rows = [row for rows in source_rows for row in rows]
        batch = identity_query.resolve_peer_macs([row.raw_mac for row in all_rows])
        matched: dict[str, dict[str, Any]] = {}
        unmatched: dict[str, dict[str, Any]] = {}
        for row in all_rows:
            raw_key = normalize_mac_key(row.raw_mac) or row.raw_mac.casefold()
            resolution = batch.matches.get(normalize_mac_key(row.raw_mac) or "")
            if resolution is None or not resolution.matched:
                target = unmatched.setdefault(raw_key, self._observed_bucket(row, canonical_mac=""))
                target["identity_status"] = str(getattr(resolution, "status", "unresolved") or "unresolved")
                target["identity_reason"] = str(getattr(resolution, "unresolved_reason", "") or "未找到唯一 AP Identity")
            else:
                canonical_key = normalize_mac_key(resolution.effective_ap_mac)
                if not canonical_key:
                    target = unmatched.setdefault(raw_key, self._observed_bucket(row, canonical_mac=""))
                    target["identity_reason"] = "AP Identity 未返回物理 AP MAC"
                else:
                    target = matched.setdefault(canonical_key, self._observed_bucket(row, canonical_mac=resolution.effective_ap_mac))
                    target.update(
                        ap_name=str(resolution.effective_ap_name or target["ap_name"]),
                        station=str(resolution.station or target["station"]),
                        section=str(resolution.section or target["section"]),
                        direction=str(resolution.direction or target["direction"]),
                        identity_status="matched",
                        identity_reason=str(resolution.data_quality_warning or ""),
                    )
            self._accumulate_observed(target, row)
        return matched, unmatched

    @staticmethod
    def _observed_bucket(row: _ObservedAp, *, canonical_mac: str) -> dict[str, Any]:
        return {
            "ap_name": row.name,
            "physical_ap_mac": format_mac(canonical_mac),
            "radio_mac": format_mac(row.raw_mac),
            "station": row.station,
            "section": row.section,
            "direction": "",
            "identity_status": "unresolved",
            "identity_reason": "",
            "source": [{"active": 0, "standby": 0, "triangle": 0, "first": "", "last": ""} for _ in range(2)],
        }

    @staticmethod
    def _accumulate_observed(bucket: dict[str, Any], row: _ObservedAp) -> None:
        source = bucket["source"][row.source_index]
        source["active"] += row.active_count
        source["standby"] += row.standby_count
        source["triangle"] += row.triangle_count
        source["first"] = min(value for value in (source["first"], row.first_seen) if value) if source["first"] or row.first_seen else ""
        source["last"] = max(value for value in (source["last"], row.last_seen) if value) if source["last"] or row.last_seen else ""

    def _expected_fit_aps(
        self,
        site_id: str,
        identity_query: ApIdentityQueryService,
    ) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], set[str]]:
        base_items = self.base_query.list_ap_status_items(site_id)
        base_by_mac = {normalize_mac_key(item.mac): item for item in base_items if normalize_mac_key(item.mac)}
        base_by_id = {str(item.id).removeprefix("ap:"): item for item in base_items}
        expected: dict[str, dict[str, Any]] = {}
        excluded: dict[str, dict[str, Any]] = {}
        all_fit_keys: set[str] = set()
        for detail in self.base_query.ac_query.list_all_ap_details(site_id):
            ap = detail.ap
            resolution = identity_query.resolve_current_ap_mac(ap.mac)
            physical = resolution.effective_ap_mac if resolution.matched else ap.mac
            key = normalize_mac_key(physical)
            if not key or key in all_fit_keys:
                continue
            all_fit_keys.add(key)
            base = base_by_id.get(str(resolution.base_record_id or "")) or base_by_mac.get(key)
            name = str(resolution.effective_ap_name or getattr(ap, "name", "") or "")
            station = str(resolution.station or getattr(base, "station", "") or "")
            section = str(resolution.section or getattr(base, "section", "") or "")
            reason = self._exclude_reason(base, name, station, section)
            row = {
                "ap_name": name,
                "physical_ap_mac": format_mac(physical),
                "radio_mac": "",
                "station": station,
                "section": section,
                "direction": str(resolution.direction or getattr(base, "direction", "") or ""),
                "fit_ap_status": str(getattr(ap, "status", "") or ""),
                "last_updated_at": str(getattr(ap, "updated_at", "") or ""),
                "identity_status": "matched" if resolution.matched else "unresolved",
                "identity_reason": str(resolution.unresolved_reason or resolution.data_quality_warning or ""),
                "source": [{"active": 0, "standby": 0, "triangle": 0, "first": "", "last": ""} for _ in range(2)],
            }
            if reason:
                excluded[key] = {**row, "exclude_reason": reason}
            else:
                expected[key] = row
        return expected, excluded, all_fit_keys

    @staticmethod
    def _exclude_reason(base: Any, name: str, station: str, section: str) -> str:
        if base is not None:
            if not bool(getattr(base, "participates_in_mainline", True)):
                return _NON_MAINLINE_CLASSES.get(str(getattr(base, "location_class", "") or ""), "基础资料标记为非正线")
            location_class = str(getattr(base, "location_class", "") or "")
            if location_class in _NON_MAINLINE_CLASSES:
                return _NON_MAINLINE_CLASSES[location_class]
        text = " ".join((name, station, section))
        return next((keyword for keyword in _NON_MAINLINE_KEYWORDS if keyword in text), "")

    @staticmethod
    def _route_scope(observed: Iterable[dict[str, Any]]) -> tuple[set[str], set[str]]:
        return (
            {str(row.get("station") or "").strip() for row in observed if str(row.get("station") or "").strip()},
            {str(row.get("section") or "").strip() for row in observed if str(row.get("section") or "").strip()},
        )

    @staticmethod
    def _in_route_scope(row: dict[str, Any], stations: set[str], sections: set[str]) -> bool:
        return bool((stations and str(row.get("station") or "") in stations) or (sections and str(row.get("section") or "") in sections))

    @staticmethod
    def _merge_expected_observed(
        expected: dict[str, Any],
        observed: dict[str, Any] | None,
        in_scope: bool,
        *,
        result: str | None = None,
    ) -> MeshApCoverageRowDTO:
        value = {**expected, **(observed or {})}
        source = value["source"]
        first = min((item["first"] for item in source if item["first"]), default="")
        last = max((item["last"] for item in source if item["last"]), default="")
        return MeshApCoverageRowDTO(
            ap_name=str(value.get("ap_name") or ""),
            physical_ap_mac=str(value.get("physical_ap_mac") or ""),
            radio_mac=str(value.get("radio_mac") or ""),
            station=str(value.get("station") or ""),
            section=str(value.get("section") or ""),
            direction=str(value.get("direction") or ""),
            fit_ap_status=str(value.get("fit_ap_status") or ""),
            last_updated_at=str(value.get("last_updated_at") or "") or None,
            seen_in_source_a=bool(source[0]["active"] or source[0]["standby"]),
            seen_in_source_b=bool(source[1]["active"] or source[1]["standby"]),
            active_count=source[0]["active"] + source[1]["active"],
            standby_count=source[0]["standby"] + source[1]["standby"],
            triangle_link_count=source[0]["triangle"] + source[1]["triangle"],
            first_seen=first or None,
            last_seen=last or None,
            identity_status=str(value.get("identity_status") or "unresolved"),
            identity_reason=str(value.get("identity_reason") or ""),
            in_observed_route_scope=in_scope,
            exclude_reason=str(value.get("exclude_reason") or ""),
            result=result or ("connected" if observed is not None else "unconnected"),
            description=(
                "两个所选 MESH 来源均未观测到"
                if observed is None and result != "excluded"
                else str(value.get("exclude_reason") or "")
            ),
        )

    def _unmatched_dto(self, observed: dict[str, Any]) -> MeshApCoverageRowDTO:
        return self._merge_expected_observed(observed, observed, True, result="unmatched")

    @staticmethod
    def _row_sort_key(row: MeshApCoverageRowDTO) -> tuple[str, str, str]:
        return (row.station, row.section, row.ap_name or row.physical_ap_mac or row.radio_mac)
