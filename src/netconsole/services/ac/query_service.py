from __future__ import annotations

import ipaddress
import json
import re
import sqlite3
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from netconsole.core.database import Database
from netconsole.core.ap_optical_capability import (
    OPTICAL_NOT_APPLICABLE_REASON,
    OPTICAL_NOT_APPLICABLE_STATUS,
    is_ap_optical_applicable,
)
from netconsole.core.optical_severity_engine import (
    classify_optical_freshness,
    classify_optical_health,
    display_optical_status,
)
from netconsole.core.optical_rx_threshold import (
    OPTICAL_BUSINESS_RX_MIN_DBM,
    evaluate_dual_optical_rx,
    parse_optical_rx_dbm,
)
from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.core.sources.ap_source import compute_ap_status
from netconsole.core.sources.switch_source import compute_switch_status
from netconsole.models.api.ac_management import (
    AcApDTO,
    AcApDetailDTO,
    AcApFilterOptionsDTO,
    AcApHistoryPageDTO,
    AcApPageDTO,
    AcConfigContentDTO,
    AcConfigDiffDTO,
    AcConfigSnapshotDTO,
    AcConfigSnapshotPageDTO,
    AcConnectionRecordDTO,
    AcLldpDTO,
    AcManagementSummaryDTO,
    AcOpticalDTO,
    AcOverviewDTO,
    AcRadioDTO,
)
from netconsole.parsers.h3c.ac.state_mapper import classify_fit_ap_state
from netconsole.repositories.ac_repository import AcRepository
from netconsole.services.ac.fit_ap_resource_identity import coalesce_fit_ap_resource_rows
from netconsole.services.ap_extension_import import normalize_ap_mac
from netconsole.services.ap_identity import ApIdentityQueryService
from netconsole.services.ap_identity.normalizers import normalize_mac_key
from netconsole.services.ap_topology import (
    ApTopologyEvidence,
    ResolvedApTopology,
    resolve_ap_topology,
)
from netconsole.services.config_text import (
    build_side_by_side_rows,
    compare_config_text,
    extract_h3c_configuration_body,
)
from netconsole.services.device_web_service import build_https_url, effective_https_port
from netconsole.services.fit_ap_link_info import lldp_display_status
from netconsole.services.neighbor_matcher import is_generic_neighbor_name
from netconsole.services.offline_ap_ledger import is_fit_ap_offline
from netconsole.utils.interface_normalize import normalize_interface_name
from netconsole.utils.mileage import format_track_mileage, parse_mileage_to_meters
from netconsole.utils.natural_sort import natural_text_key


_AP_HISTORY_FIELDS = {
    "radio": (
        "collected_at",
        "ap_name",
        "rid",
        "status",
        "mode",
        "band",
        "channel",
        "bandwidth",
        "usage",
        "tx_power",
        "clients",
        "bbssid",
    ),
    "lldp": (
        "collected_at",
        "source",
        "is_changed",
        "conflict_flag",
        "local_interface",
        "lldp_neighbor",
        "neighbor_interface",
        "neighbor_mac",
        "neighbor_device_name",
        "neighbor_name",
    ),
    "optical": (
        "collected_at",
        "interface_name",
        "optical_alarm_status",
        "temperature",
        "voltage",
        "bias_current",
        "tx_power",
        "rx_power",
        "rx_low_alarm",
        "rx_high_alarm",
        "tx_low_alarm",
        "tx_high_alarm",
        "rx_low_warning",
        "rx_high_warning",
        "tx_low_warning",
        "tx_high_warning",
        "module_model",
        "module_vendor",
        "wavelength",
        "transmission_distance",
        "connector_type",
        "status",
        "error_message",
    ),
}


def fit_ap_topology_sort_key(item: AcApDTO) -> tuple[object, ...]:
    """按连接交换机和规范化端口自然升序排列 FIT-AP。"""
    switch_name = str(item.switch_name or "").strip()
    interface_name = normalize_interface_name(item.switch_interface)
    return (
        0 if switch_name else 1,
        natural_text_key(switch_name),
        0 if interface_name else 1,
        natural_text_key(interface_name),
        natural_text_key(item.name),
        natural_text_key(item.id),
    )


class _ReadonlyDatabase:
    """供现有 Repository 复用的 SQLite 只读连接门面。"""

    def __init__(self, path: Path) -> None:
        self.path = path

    def connect(self) -> sqlite3.Connection:
        return AcManagementQueryService._connect(self.path)


class AcManagementQueryService:
    """AC 管理 Web 页面的 GET-only 查询边界。"""

    def __init__(
        self,
        paths: PathResolver,
        *,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.paths = paths
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    def current_site_id(self, default: str = "demo") -> str:
        try:
            payload = json.loads(self.paths.app_config_path.read_text(encoding="utf-8"))
            site_id = str(payload.get("current_site") or default) if isinstance(payload, dict) else default
            return SiteManager(self.paths).validate_site_name(site_id)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return default

    def get_summary(self, site_id: str) -> AcManagementSummaryDTO:
        db_path = self._db_path(site_id)
        if not db_path.is_file():
            return AcManagementSummaryDTO(site_id=site_id, message="暂无 AC 资源数据，请先在 Qt AC 管理页面完成数据采集。")
        repository = AcRepository(_ReadonlyDatabase(db_path))  # type: ignore[arg-type]
        with closing(self._connect(db_path)) as conn:
            ac_rows = self._ac_rows(conn)
            context = self._switch_context(conn)
        overviews: list[AcOverviewDTO] = []
        for ac in ac_rows:
            ac_id = str(ac["device_uuid"])
            resources = repository.list_fit_ap_resources_with_metadata(ac_id)
            resources = coalesce_fit_ap_resource_rows(resources)
            unauthenticated = repository.list_fit_ap_unauthenticated(ac_id)
            optical_by_ap = self._optical_index(repository.list_fit_ap_optical(ac_id))
            summary = dict(ac.get("summary") or {})
            anomalous_ap_ids: set[str] = set()
            for row in resources:
                optical = self._optical_for(row, optical_by_ap, context)
                if optical.is_current_anomaly:
                    identity = self._clean_text(row.get("ap_uuid") or row.get("ap_mac") or row.get("ap_name"))
                    if identity:
                        anomalous_ap_ids.add(identity.casefold())
            online = self._int(
                summary.get("online_aps"),
                sum(self._online_status(row) == "online" for row in resources),
            )
            offline = self._int(
                summary.get("offline_aps"),
                sum(self._online_status(row) == "offline" for row in resources),
            )
            total = self._int(summary.get("total_aps"), len(resources))
            updated_at = self._latest_text(
                summary.get("updated_at"),
                *(row.get("updated_at") for row in resources),
            )
            management_ip = str(ac.get("primary_address") or "")
            https_port = effective_https_port(ac.get("https_port"))[0]
            overviews.append(
                AcOverviewDTO(
                    id=ac_id,
                    name=str(ac.get("name") or ac_id),
                    management_ip=management_ip,
                    web_url=build_https_url(management_ip, https_port) or "",
                    model=str(summary.get("model") or ac.get("model") or ""),
                    software_version=str(summary.get("software_version") or ac.get("software_version") or ""),
                    cpu_usage=str(summary.get("cpu_usage") or ""),
                    memory_usage=str(summary.get("memory_usage") or ""),
                    https_port=self._optional_int(ac.get("https_port")),
                    ap_total=total,
                    online_aps=online,
                    offline_aps=offline,
                    unauthenticated_aps=len(unauthenticated),
                    radio_total=sum(self._radio_present(row, rid) for row in resources for rid in (1, 2)),
                    optical_anomalies=len(anomalous_ap_ids),
                    updated_at=updated_at,
                )
            )
        if not overviews:
            return AcManagementSummaryDTO(site_id=site_id, message="暂无 AC 资源数据，请先在 Qt AC 管理页面完成数据采集。")
        return AcManagementSummaryDTO(
            site_id=site_id,
            acs=overviews,
            ap_total=sum(item.ap_total for item in overviews),
            online_aps=sum(item.online_aps for item in overviews),
            offline_aps=sum(item.offline_aps for item in overviews),
            unauthenticated_aps=sum(item.unauthenticated_aps for item in overviews),
            radio_total=sum(item.radio_total for item in overviews),
            optical_anomalies=sum(item.optical_anomalies for item in overviews),
            updated_at=self._latest_text(*(item.updated_at for item in overviews)),
        )

    def list_aps(
        self,
        site_id: str,
        *,
        ac_id: str = "",
        page: int = 1,
        page_size: int = 50,
        query: str = "",
        status: str = "",
        station: str = "",
        section: str = "",
        model: str = "",
        switch: str = "",
        optical_status: str = "",
        sort_by: str = "topology",
        sort_order: str = "asc",
    ) -> AcApPageDTO:
        records = self._ap_records(site_id, ac_id=ac_id)
        all_items = [record[0] for record in records]
        items = self._apply_identity_query(site_id, all_items, query)
        if items is not all_items:
            query = ""
        items = self._filter_ap_items(
            items,
            query=query,
            status=status,
            station=station,
            section=section,
            model=model,
            switch=switch,
            optical_statuses={optical_status} if optical_status else set(),
            sort_by=sort_by,
            sort_order=sort_order,
        )
        return self._page(
            items,
            page,
            page_size,
            filter_options=self._ap_filter_options(all_items),
        )

    def _apply_identity_query(self, site_id: str, items: list[AcApDTO], query: str) -> list[AcApDTO]:
        if not normalize_mac_key(query):
            return items
        identity_rows = ApIdentityQueryService(
            Database(self._db_path(site_id))
        ).search_aps(query)
        matched_macs = {
            mac
            for row in identity_rows
            for field in ("ap_mac", "ac_ap_mac", "base_ap_mac")
            if (mac := normalize_mac_key(row.get(field)))
        }
        matched_names = {
            str(row.get("ap_name") or "").strip().casefold()
            for row in identity_rows
            if str(row.get("ap_name") or "").strip()
        }
        return [
            item
            for item in items
            if normalize_mac_key(item.mac) in matched_macs
            or str(item.name or "").strip().casefold() in matched_names
        ]

    def _filtered_aps(
        self,
        site_id: str,
        *,
        ac_id: str = "",
        query: str = "",
        status: str = "",
        station: str = "",
        section: str = "",
        model: str = "",
        switch: str = "",
        optical_statuses: set[str] | None = None,
        current_optical_only: bool = False,
        sort_by: str = "topology",
        sort_order: str = "asc",
    ) -> list[AcApDTO]:
        records = self._ap_records(site_id, ac_id=ac_id)
        items = self._apply_identity_query(site_id, [record[0] for record in records], query)
        if items:
            query = "" if normalize_mac_key(query) else query
        return self._filter_ap_items(
            items,
            query=query,
            status=status,
            station=station,
            section=section,
            model=model,
            switch=switch,
            optical_statuses=optical_statuses,
            current_optical_only=current_optical_only,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    @staticmethod
    def _option_values(items: list[AcApDTO], field: str) -> list[str]:
        values = {text for item in items if (text := AcManagementQueryService._clean_text(getattr(item, field, "")))}
        return sorted(values, key=natural_text_key)

    @classmethod
    def _ap_filter_options(cls, items: list[AcApDTO]) -> AcApFilterOptionsDTO:
        return AcApFilterOptionsDTO(
            stations=cls._option_values(items, "station"),
            sections=cls._option_values(items, "section"),
            models=cls._option_values(items, "model"),
            switches=cls._option_values(items, "switch_name"),
        )

    def list_optical_anomalies(
        self,
        site_id: str,
        *,
        ac_id: str = "",
        page: int = 1,
        page_size: int = 50,
        query: str = "",
    ) -> AcApPageDTO:
        items = self._filtered_aps(
            site_id,
            ac_id=ac_id,
            query=query,
            optical_statuses={"warning", "critical"},
            current_optical_only=True,
            sort_by="topology",
            sort_order="asc",
        )
        return self._page(items, page, page_size)

    def get_ap_detail(self, site_id: str, ap_id: str) -> AcApDetailDTO | None:
        record = self._find_ap(site_id, ap_id)
        if record is None:
            return None
        item, raw, optical, lldp = record
        repository = AcRepository(_ReadonlyDatabase(self._db_path(site_id)))  # type: ignore[arg-type]
        detail = repository.get_fit_ap_detail(item.id) or {}
        radio_details = repository.list_fit_ap_radio_details(item.id)
        return AcApDetailDTO(
            ap=item,
            radios=self._radios(raw),
            lldp=lldp,
            optical=optical,
            connection=self._connection(raw),
            detail=detail,
            radio_details=radio_details,
        )

    def get_ap_history(
        self,
        site_id: str,
        ap_id: str,
        history_kind: str,
        *,
        page: int = 1,
        page_size: int = 100,
    ) -> AcApHistoryPageDTO | None:
        record = self._find_ap(site_id, ap_id)
        if record is None:
            return None
        kind = str(history_kind or "").casefold()
        try:
            fields = _AP_HISTORY_FIELDS[kind]
        except KeyError as exc:
            raise ValueError("不支持的 FIT-AP 历史类型") from exc
        size = max(1, min(int(page_size), 200))
        repository = AcRepository(_ReadonlyDatabase(self._db_path(site_id)))  # type: ignore[arg-type]
        total = repository.count_fit_ap_history(kind, record[0].id)
        total_pages = max((total + size - 1) // size, 1)
        current_page = min(max(int(page), 1), total_pages)
        rows = repository.list_fit_ap_history_page(
            kind,
            record[0].id,
            limit=size,
            offset=(current_page - 1) * size,
        )
        items = [{field: row.get(field) for field in fields} for row in rows]
        return AcApHistoryPageDTO(
            kind=kind,
            ap_id=record[0].id,
            items=items,
            total=total,
            page=current_page,
            page_size=size,
        )

    def list_all_ap_details(self, site_id: str) -> list[AcApDetailDTO]:
        repository = AcRepository(_ReadonlyDatabase(self._db_path(site_id)))  # type: ignore[arg-type]
        details = {str(row.get("ap_uuid") or ""): row for row in repository.list_fit_ap_details("")}
        # list_fit_ap_details is AC-scoped; use a direct latest index for the cross-AC export path.
        if not details:
            with closing(self._connect(self._db_path(site_id))) as conn:
                if self._table_exists(conn, "ac_fit_ap_details"):
                    details = {
                        str(row["ap_uuid"]): dict(row)
                        for row in conn.execute("SELECT * FROM ac_fit_ap_details")
                    }
        return [
            AcApDetailDTO(
                ap=item,
                radios=self._radios(raw),
                lldp=lldp,
                optical=optical,
                connection=self._connection(raw),
                detail=details.get(item.id, {}),
                radio_details=repository.list_fit_ap_radio_details(item.id),
            )
            for item, raw, optical, lldp in self._ap_records(site_id)
        ]

    def list_ap_details_for_macs(
        self,
        site_id: str,
        macs: list[str],
    ) -> list[AcApDetailDTO]:
        """批量读取当前页 AP 的轻量运行态，不展开全局 FIT-AP 资源。"""
        normalized = sorted({value for value in (normalize_ap_mac(mac).normalized for mac in macs) if value})
        if not normalized:
            return []
        db_path = self._db_path(site_id)
        if not db_path.is_file():
            return []
        repository = AcRepository(_ReadonlyDatabase(db_path))  # type: ignore[arg-type]
        resources = repository.list_fit_ap_resources_with_metadata_for_macs(normalized)
        optical_rows = repository.list_fit_ap_optical_for_macs(normalized)
        optical_by_ap = self._optical_index(optical_rows)
        with closing(self._connect(db_path)) as conn:
            context = self._switch_context_for_resources(conn, resources, optical_rows)
            ac_names = {
                str(row["device_uuid"]): str(row["name"] or row["device_uuid"])
                for row in self._safe_devices(conn)
            }
        context["fit_ap_details_by_uuid"] = {
            str(row.get("ap_uuid") or ""): row
            for row in repository.list_fit_ap_details_for_macs(normalized)
        } if hasattr(repository, "list_fit_ap_details_for_macs") else {}
        result: list[AcApDetailDTO] = []
        for row in resources:
            optical = self._optical_for(row, optical_by_ap, context)
            lldp = self._lldp_for(row, optical_by_ap, context)
            result.append(
                AcApDetailDTO(
                    ap=self._ap_dto(row, optical, lldp, ac_names, context),
                    radios=[],
                    lldp=lldp,
                    optical=optical,
                    connection=self._connection(row),
                    detail=context["fit_ap_details_by_uuid"].get(str(row.get("ap_uuid") or ""), {}),
                    radio_details=repository.list_fit_ap_radio_details(str(row.get("ap_uuid") or "")),
                )
            )
        return result

    def list_ap_details_for_export(
        self,
        site_id: str,
        *,
        ac_id: str,
        filters: dict[str, object] | None = None,
        selected_ap_ids: list[str] | None = None,
    ) -> list[AcApDetailDTO]:
        values = dict(filters or {})
        records = self._ap_records(site_id, ac_id=ac_id)
        items = self._filter_ap_items(
            [record[0] for record in records],
            query=str(values.get("query") or ""),
            status=str(values.get("status") or ""),
            station=str(values.get("station") or ""),
            section=str(values.get("section") or ""),
            model=str(values.get("model") or ""),
            switch=str(values.get("switch") or ""),
            optical_statuses={str(values.get("optical_status") or "")} if values.get("optical_status") else set(),
            sort_by="topology",
            sort_order="asc",
        )
        selected = {str(value) for value in selected_ap_ids or [] if str(value)}
        if selected:
            items = [item for item in items if item.id in selected]
        by_id = {record[0].id: record for record in records}
        return [
            AcApDetailDTO(
                ap=item,
                radios=self._radios(by_id[item.id][1]),
                lldp=by_id[item.id][3],
                optical=by_id[item.id][2],
                connection=self._connection(by_id[item.id][1]),
                detail=self._detail_for_ap(site_id, item.id),
                radio_details=self._radio_details_for_ap(site_id, item.id),
            )
            for item in items
        ]

    def get_ac_export_identity(self, site_id: str, ac_id: str) -> AcOverviewDTO | None:
        db_path = self._db_path(site_id)
        if not db_path.is_file():
            return None
        with closing(self._connect(db_path)) as conn:
            row = next((item for item in self._ac_rows(conn) if str(item["device_uuid"]) == ac_id), None)
        if row is None:
            return None
        summary = dict(row.get("summary") or {})
        management_ip = str(row.get("primary_address") or "")
        return AcOverviewDTO(
            id=ac_id,
            name=str(row.get("name") or ac_id),
            management_ip=management_ip,
            web_url=build_https_url(management_ip, effective_https_port(row.get("https_port"))[0]) or "",
            model=str(summary.get("model") or row.get("model") or ""),
            software_version=str(summary.get("software_version") or row.get("software_version") or ""),
            updated_at=self._latest_text(summary.get("updated_at"), summary.get("collected_at")),
        )

    def get_ap_radios(self, site_id: str, ap_id: str) -> list[AcRadioDTO] | None:
        detail = self.get_ap_detail(site_id, ap_id)
        return detail.radios if detail else None

    def get_ap_lldp(self, site_id: str, ap_id: str) -> AcLldpDTO | None:
        detail = self.get_ap_detail(site_id, ap_id)
        return detail.lldp if detail else None

    def get_ap_optical(self, site_id: str, ap_id: str) -> AcOpticalDTO | None:
        detail = self.get_ap_detail(site_id, ap_id)
        return detail.optical if detail else None

    def list_config_snapshots(
        self,
        site_id: str,
        *,
        ac_id: str = "",
        snapshot_type: str = "",
        page: int = 1,
        page_size: int = 30,
    ) -> AcConfigSnapshotPageDTO:
        db_path = self._db_path(site_id)
        if not db_path.is_file():
            return AcConfigSnapshotPageDTO(page=page, page_size=page_size)
        with closing(self._connect(db_path)) as conn:
            if not self._table_exists(conn, "config_snapshots"):
                return AcConfigSnapshotPageDTO(page=page, page_size=page_size)
            clauses = ["(upper(coalesce(d.device_type, '')) = 'AC' OR s.ac_device_uuid IS NOT NULL)"]
            params: list[object] = []
            if ac_id:
                clauses.append("snapshot.device_uuid = ?")
                params.append(ac_id)
            if snapshot_type:
                clauses.append("snapshot.type = ?")
                params.append(snapshot_type)
            where = " AND ".join(clauses)
            total = int(
                conn.execute(
                    f"""
                    SELECT count(*)
                    FROM config_snapshots snapshot
                    LEFT JOIN devices d ON d.device_uuid = snapshot.device_uuid
                    LEFT JOIN ac_ap_summary s ON s.ac_device_uuid = snapshot.device_uuid
                    WHERE {where}
                    """,
                    params,
                ).fetchone()[0]
            )
            size = max(1, min(int(page_size), 100))
            current_page = max(1, int(page))
            rows = conn.execute(
                f"""
                SELECT snapshot.*, d.name AS ac_name
                FROM config_snapshots snapshot
                LEFT JOIN devices d ON d.device_uuid = snapshot.device_uuid
                LEFT JOIN ac_ap_summary s ON s.ac_device_uuid = snapshot.device_uuid
                WHERE {where}
                ORDER BY snapshot.timestamp DESC, snapshot.id DESC
                LIMIT ? OFFSET ?
                """,
                [*params, size, (current_page - 1) * size],
            ).fetchall()
        items = [self._snapshot_dto(site_id, dict(row)) for row in rows]
        return AcConfigSnapshotPageDTO(items=items, total=total, page=current_page, page_size=size)

    def get_config_snapshot(
        self,
        site_id: str,
        snapshot_id: int,
        *,
        offset: int = 0,
        limit: int = 100_000,
    ) -> AcConfigContentDTO | None:
        row = self._snapshot_row(site_id, snapshot_id)
        if row is None:
            return None
        text = self._snapshot_text(site_id, row)
        start = max(0, int(offset))
        size = max(1, min(int(limit), 200_000))
        content = text[start : start + size]
        next_offset = start + len(content) if start + len(content) < len(text) else None
        return AcConfigContentDTO(
            snapshot=self._snapshot_dto(site_id, row),
            content=content,
            offset=start,
            next_offset=next_offset,
            total_chars=len(text),
            truncated=next_offset is not None,
        )

    def get_config_diff(
        self,
        site_id: str,
        snapshot_id: int,
        *,
        other_snapshot_id: int | None = None,
        limit: int = 200_000,
    ) -> AcConfigDiffDTO | None:
        selected = self._snapshot_row(site_id, snapshot_id)
        if selected is None:
            return None
        other = self._snapshot_row(site_id, other_snapshot_id) if other_snapshot_id is not None else None
        running, saved = self._config_pair(site_id, selected, other)
        running_text = self._snapshot_text(site_id, running)
        saved_text = self._snapshot_text(site_id, saved)
        result = compare_config_text(running_text, saved_text)
        rows, added_count, removed_count, modified_count = build_side_by_side_rows(
            saved_text.splitlines(),
            running_text.splitlines(),
        )
        max_chars = max(1, min(int(limit), 500_000))
        raw_diff = result.raw_diff[:max_chars]
        return AcConfigDiffDTO(
            from_snapshot_id=int(saved["id"]),
            to_snapshot_id=int(running["id"]),
            left_label=self._snapshot_label(saved),
            right_label=self._snapshot_label(running),
            left_content=saved_text,
            right_content=running_text,
            diff_rows=[asdict(row) for row in rows],
            diff_summary={
                "added": added_count,
                "removed": removed_count,
                "modified": modified_count,
            },
            added=result.added,
            removed=result.removed,
            modified=result.modified,
            raw_diff=raw_diff,
            truncated=len(result.raw_diff) > len(raw_diff),
        )

    @staticmethod
    def _snapshot_label(row: dict[str, object]) -> str:
        snapshot_type = str(row.get("type") or "config")
        timestamp = str(row.get("timestamp") or "")
        return f"{snapshot_type} · {timestamp}" if timestamp else snapshot_type

    def _filter_ap_items(
        self,
        items: list[AcApDTO],
        *,
        query: str = "",
        status: str = "",
        station: str = "",
        section: str = "",
        model: str = "",
        switch: str = "",
        optical_statuses: set[str] | None = None,
        current_optical_only: bool = False,
        sort_by: str = "topology",
        sort_order: str = "asc",
    ) -> list[AcApDTO]:
        items = list(items)
        keyword = str(query or "").strip().casefold()
        if keyword:
            items = [item for item in items if keyword in " ".join((item.name, item.ip, item.mac)).casefold()]
        if status:
            items = [item for item in items if item.status == status]
        for value, field in ((station, "station"), (section, "section"), (model, "model"), (switch, "switch_name")):
            needle = str(value or "").strip().casefold()
            if needle:
                items = [item for item in items if needle in str(getattr(item, field) or "").casefold()]
        wanted_optical = {value for value in optical_statuses or set() if value}
        if wanted_optical:
            items = [item for item in items if item.optical_status in wanted_optical]
        if current_optical_only:
            items = [item for item in items if item.optical_is_current_anomaly]
        reverse = str(sort_order or "asc").casefold() == "desc"
        items.sort(key=lambda item: self._ap_sort_key(item, sort_by), reverse=reverse)
        return items

    def _ap_records(
        self,
        site_id: str,
        *,
        ac_id: str = "",
    ) -> list[tuple[AcApDTO, dict[str, object | None], AcOpticalDTO, AcLldpDTO]]:
        db_path = self._db_path(site_id)
        if not db_path.is_file():
            return []
        repository = AcRepository(_ReadonlyDatabase(db_path))  # type: ignore[arg-type]
        resources = (
            repository.list_fit_ap_resources_with_metadata(ac_id)
            if ac_id
            else repository.list_all_fit_ap_resources_with_metadata()
        )
        unauthenticated = (
            repository.list_fit_ap_unauthenticated(ac_id)
            if ac_id
            else repository.list_all_fit_ap_unauthenticated()
        )
        resources = self._append_unmatched_unauthenticated(resources, unauthenticated)
        resources = coalesce_fit_ap_resource_rows(resources)
        optical_rows = repository.list_fit_ap_optical(ac_id) if ac_id else repository.list_all_fit_ap_optical()
        optical_by_ap = self._optical_index(optical_rows)
        with closing(self._connect(db_path)) as conn:
            context = self._switch_context(conn)
            ac_names = {str(row["device_uuid"]): str(row["name"] or row["device_uuid"]) for row in self._safe_devices(conn)}
        context["fit_ap_details_by_uuid"] = {
            str(row.get("ap_uuid") or ""): row
            for row in repository.list_fit_ap_details(ac_id)
        } if ac_id else {
            str(row.get("ap_uuid") or ""): row
            for row in self._list_all_fit_ap_details(repository)
        }
        records = []
        for row in resources:
            optical = self._optical_for(row, optical_by_ap, context)
            lldp = self._lldp_for(row, optical_by_ap, context)
            records.append((self._ap_dto(row, optical, lldp, ac_names, context), row, optical, lldp))
        return records

    @staticmethod
    def _list_all_fit_ap_details(repository: AcRepository) -> list[dict[str, object | None]]:
        with repository.database.connect() as conn:
            if not AcManagementQueryService._table_exists(conn, "ac_fit_ap_details"):
                return []
            return [dict(row) for row in conn.execute("SELECT * FROM ac_fit_ap_details")]

    def _detail_for_ap(self, site_id: str, ap_id: str) -> dict[str, object | None]:
        repository = AcRepository(_ReadonlyDatabase(self._db_path(site_id)))  # type: ignore[arg-type]
        return repository.get_fit_ap_detail(ap_id) or {}

    def _radio_details_for_ap(self, site_id: str, ap_id: str) -> list[dict[str, object | None]]:
        repository = AcRepository(_ReadonlyDatabase(self._db_path(site_id)))  # type: ignore[arg-type]
        return repository.list_fit_ap_radio_details(ap_id)

    def _find_ap(
        self,
        site_id: str,
        ap_id: str,
    ) -> tuple[AcApDTO, dict[str, object | None], AcOpticalDTO, AcLldpDTO] | None:
        return next((record for record in self._ap_records(site_id) if record[0].id == str(ap_id)), None)

    def _ap_dto(
        self,
        row: dict[str, object | None],
        optical: AcOpticalDTO,
        lldp: AcLldpDTO,
        ac_names: dict[str, str],
        context: dict[str, Any],
    ) -> AcApDTO:
        ac_id = str(row.get("ac_device_uuid") or "")
        unauthenticated = bool(row.get("is_new_online_ap") or row.get("_web_unauthenticated"))
        status = "unauthenticated" if unauthenticated else "offline" if is_fit_ap_offline(row) else self._online_status(row)
        mileage = format_track_mileage(row.get("mileage"), direction=str(row.get("direction") or ""))
        station_info = self._station(row, lldp, context)
        station = str(station_info["effective_station_name"] or "")
        station_source_detail = str(station_info["station_source"] or "empty")
        station_source = {
            "manual_override": "metadata",
            "base_ap_mac": "metadata",
            "ac_resource": "resource",
        }.get(station_source_detail, station_source_detail)
        detail = context.get("fit_ap_details_by_uuid", {}).get(str(row.get("ap_uuid") or ""), {})
        topology = station_info.get("topology")
        resolved_section = (
            topology.section.value
            if isinstance(topology, ResolvedApTopology)
            else str(row.get("section_name") or row.get("metadata_belong_section") or "")
        )
        resolved_mileage = (
            topology.mileage.value
            if isinstance(topology, ResolvedApTopology)
            else mileage
        )
        resolved_direction = (
            topology.direction.value
            if isinstance(topology, ResolvedApTopology)
            else str(row.get("direction") or row.get("extension_line_side") or "")
        )
        resolved_location = (
            topology.location.value
            if isinstance(topology, ResolvedApTopology)
            else str(row.get("location_note") or row.get("extension_location_desc") or "")
        )
        display_mileage = format_track_mileage(
            resolved_mileage,
            direction=resolved_direction,
        )
        return AcApDTO(
            id=str(row.get("ap_uuid") or f"unauth-{row.get('id') or row.get('ap_name') or 'unknown'}"),
            ac_id=ac_id,
            ac_name=ac_names.get(ac_id, ac_id),
            name=str(row.get("ap_name") or "未命名 AP"),
            ip=str(row.get("ap_ip") or ""),
            mac=str(row.get("ap_mac") or row.get("inferred_ap_mac") or ""),
            status=status,
            state_display=str(row.get("state_display") or row.get("state_raw") or row.get("state") or ""),
            model=str(row.get("model") or ""),
            serial_number=str(row.get("serial_number") or ""),
            online_time=str(row.get("online_time") or ""),
            is_unauthenticated=unauthenticated,
            radio1_status=str(row.get("rid1_status") or ""),
            radio2_status=str(row.get("rid2_status") or ""),
            radio1_channel=str(row.get("rid1_channel") or ""),
            radio2_channel=str(row.get("rid2_channel") or ""),
            radio1_power=str(row.get("rid1_tx_power") or ""),
            radio2_power=str(row.get("rid2_tx_power") or ""),
            station=station,
            station_source=station_source,
            station_source_detail=station_source_detail,
            effective_station_id=str(station_info["effective_station_id"] or ""),
            effective_station_name=station,
            station_confidence=float(station_info["station_confidence"] or 0.0),
            manual_station_id=str(station_info["manual_station_id"] or ""),
            manual_station_name=str(station_info["manual_station_name"] or ""),
            manual_override_enabled=bool(station_info["manual_override_enabled"]),
            auto_station_id=str(station_info["auto_station_id"] or ""),
            auto_station_name=str(station_info["auto_station_name"] or ""),
            auto_match_basis=str(station_info["auto_match_basis"] or ""),
            lldp_suggested_station_id=str(station_info["lldp_suggested_station_id"] or ""),
            lldp_suggested_station_name=str(station_info["lldp_suggested_station_name"] or ""),
            resource_station_text=str(station_info["resource_station_text"] or ""),
            software_version=str(detail.get("software_version") or ""),
            hardware_version=str(detail.get("hardware_version") or ""),
            boot_version=str(detail.get("boot_version") or ""),
            detail_updated_at=str(detail.get("updated_at") or ""),
            detail_available=bool(detail),
            section=resolved_section,
            mileage=display_mileage if display_mileage != "-" else "",
            direction=resolved_direction,
            location_note=resolved_location,
            point_code=str(row.get("extension_ap_point_code") or ""),
            trackside_ap_name=str(row.get("extension_ap_name") or ""),
            remark=str(row.get("extension_remark") or ""),
            switch_name=lldp.switch_name,
            switch_interface=lldp.interface_name,
            lldp_status=lldp.match_status,
            optical_status=optical.optical_status,
            optical_applicable=optical.optical_applicable,
            optical_severity=optical.optical_severity,
            optical_data_freshness=optical.data_freshness,
            optical_is_current_anomaly=optical.is_current_anomaly,
            optical_rx_power=optical.rx_power,
            updated_at=self._latest_text(row.get("updated_at"), optical.updated_at, lldp.updated_at),
        )

    @staticmethod
    def _radios(row: dict[str, object | None]) -> list[AcRadioDTO]:
        radios: list[AcRadioDTO] = []
        for rid in (1, 2, 3):
            values = {
                "status": str(row.get(f"rid{rid}_status") or ""),
                "mode": str(row.get(f"rid{rid}_mode") or ""),
                "band": str(row.get(f"rid{rid}_band") or ""),
                "channel": str(row.get(f"rid{rid}_channel") or ""),
                "bandwidth": str(row.get(f"rid{rid}_bandwidth") or ""),
                "usage": str(row.get(f"rid{rid}_usage") or ""),
                "tx_power": str(row.get(f"rid{rid}_tx_power") or ""),
                "bssid": str(row.get(f"rid{rid}_bbssid") or ""),
            }
            clients = int(row.get(f"rid{rid}_clients") or 0)
            if not any(values.values()) and clients == 0:
                continue
            radios.append(
                AcRadioDTO(
                radio_id=rid,
                clients=clients,
                updated_at=str(row.get("updated_at") or row.get("collected_at") or ""),
                **values,
                )
            )
        return radios

    @staticmethod
    def _connection(row: dict[str, object | None]) -> AcConnectionRecordDTO:
        return AcConnectionRecordDTO(
            ip_address=str(row.get("connection_ip") or ""),
            state=str(row.get("connection_state") or ""),
            connected_at=str(row.get("connection_time") or ""),
            updated_at=str(row.get("updated_at") or row.get("collected_at") or ""),
        )

    def _optical_for(
        self,
        resource: dict[str, object | None],
        optical_by_ap: dict[tuple[str, str], dict[str, object | None]],
        context: dict[str, Any],
    ) -> AcOpticalDTO:
        if not is_ap_optical_applicable(resource.get("model")):
            offline = is_fit_ap_offline(resource)
            return AcOpticalDTO(
                optical_applicable=False,
                optical_status=OPTICAL_NOT_APPLICABLE_STATUS,
                optical_severity=OPTICAL_NOT_APPLICABLE_STATUS,
                raw_status=OPTICAL_NOT_APPLICABLE_STATUS,
                ap_rx_status=OPTICAL_NOT_APPLICABLE_STATUS,
                switch_rx_status=OPTICAL_NOT_APPLICABLE_STATUS,
                tx_power_status=OPTICAL_NOT_APPLICABLE_STATUS,
                ap_online_status=(
                    "offline" if offline else self._online_status(resource)
                ),
                data_freshness=OPTICAL_NOT_APPLICABLE_STATUS,
                anomaly_reason=OPTICAL_NOT_APPLICABLE_REASON,
                threshold_status="不适用",
            )
        row = self._indexed_row(resource, optical_by_ap)
        if row is None:
            return AcOpticalDTO(anomaly_reason="未采集光衰数据")
        switch_name = str(row.get("neighbor_device_name") or row.get("lldp_neighbor_name") or resource.get("lldp_neighbor_name") or "")
        interface = str(row.get("neighbor_interface") or row.get("lldp_neighbor_interface") or resource.get("lldp_neighbor_interface") or "")
        switch_uuid = self._switch_uuid(resource, row, switch_name, context)
        interface_key = normalize_interface_name(interface).casefold()
        module = context["optical_by_interface"].get((switch_uuid, interface_key), {})
        port = context["port_by_interface"].get((switch_uuid, interface_key), {})
        has_ap_data = any(row.get(field) not in (None, "") for field in ("rx_power", "tx_power", "temperature", "voltage"))
        has_switch_data = bool(module) or row.get("neighbor_rx_power") not in (None, "")
        if not has_ap_data and not has_switch_data and str(row.get("status") or "").casefold() != "success":
            return AcOpticalDTO(
                anomaly_reason="光衰采集无有效结果",
                source_switch=switch_name,
                source_interface=interface,
                error_summary=str(row.get("error_message") or ""),
                updated_at=str(row.get("updated_at") or row.get("collected_at") or ""),
            )
        if module:
            module_status = module.get("module_status") or module.get("status")
            module_rx = module.get("rx_power")
            explicit_module_state = str(module_status or "").strip().casefold()
            has_switch_evidence = bool(
                re.search(r"[-+]?\d+(?:\.\d+)?", str(module_rx or ""))
                or str(port.get("port_status") or port.get("link_status") or "")
                .strip()
                .casefold()
                == "down"
                or module.get("module_present") is False
                or module.get("has_module") is False
                or module.get("no_module")
                or explicit_module_state
                in {
                    "no_module",
                    "no module",
                    "no_light",
                    "no light",
                    "link_down",
                    "link down",
                    "link_abnormal",
                    "link abnormal",
                    "alarm",
                    "abnormal",
                    "warning",
                }
            )
            switch_status = (
                compute_switch_status(
                    switch_rx_power=module_rx,
                    switch_port_status=port.get("port_status")
                    or port.get("link_status"),
                    alarm_low=module.get("rx_low_alarm"),
                    alarm_high=module.get("rx_high_alarm"),
                    warning_low=module.get("rx_low_warning"),
                    module_present=(
                        module.get("module_present")
                        if "module_present" in module
                        else module.get("has_module")
                    ),
                    no_module=module.get("no_module"),
                    module_status=module_status,
                )
                if has_switch_evidence
                else "unknown"
            )
            switch_rx = str(module.get("rx_power") or "")
        elif row.get("neighbor_rx_power") not in (None, ""):
            switch_status = compute_switch_status(switch_rx_power=row.get("neighbor_rx_power"))
            switch_rx = str(row.get("neighbor_rx_power") or "")
        else:
            switch_status = "unknown"
            switch_rx = ""
        ap_status = compute_ap_status(row)
        evaluation = evaluate_dual_optical_rx(
            row.get("rx_power"),
            switch_rx,
            ap_reported_status=ap_status,
            switch_reported_status=switch_status,
        )
        ap_status = evaluation.ap.status
        switch_status = evaluation.switch.status
        raw_status = evaluation.status
        offline = is_fit_ap_offline(resource)
        status = classify_optical_health(raw_status)
        if raw_status == "abnormal":
            status = "critical"
        freshness = self._optical_freshness(row, module, raw_status, ap_status, switch_status)
        is_current_anomaly = status in {"warning", "critical"} and freshness == "fresh"
        label = display_optical_status(raw_status)
        ap_online_status = "offline" if offline else self._online_status(resource)
        return AcOpticalDTO(
            optical_status=status,
            optical_severity=status,
            raw_status=raw_status,
            ap_rx_status=ap_status,
            switch_rx_status=switch_status,
            tx_power_status="unknown",
            ap_offline_related=offline and is_current_anomaly,
            ap_online_status=ap_online_status,
            data_freshness=freshness,
            is_current_anomaly=is_current_anomaly,
            anomaly_reason=self._optical_reason(
                status=status,
                freshness=freshness,
                ap_status=ap_status,
                switch_status=switch_status,
                ap_rx_power=row.get("rx_power"),
                switch_rx_power=switch_rx,
                offline=offline,
            ),
            source_switch=switch_name,
            source_interface=interface,
            tx_power=str(row.get("tx_power") or ""),
            rx_power=str(row.get("rx_power") or ""),
            switch_rx_power=switch_rx,
            temperature=str(row.get("temperature") or ""),
            voltage=str(row.get("voltage") or ""),
            bias_current=str(row.get("bias_current") or ""),
            threshold_status=label,
            error_summary=str(row.get("error_message") or ""),
            updated_at=self._latest_text(row.get("updated_at"), row.get("collected_at"), module.get("updated_at")),
        )

    @classmethod
    def _optical_reason(
        cls,
        *,
        status: str,
        freshness: str,
        ap_status: str,
        switch_status: str,
        ap_rx_power: object,
        switch_rx_power: object,
        offline: bool,
    ) -> str:
        label = "严重光衰异常" if status == "critical" else "异常 AP 光衰"
        side_summaries = [
            cls._optical_side_summary("AP 侧收光", ap_status, ap_rx_power),
            cls._optical_side_summary("交换机侧收光", switch_status, switch_rx_power),
        ]
        abnormal_sides = [
            summary
            for summary, side_status in zip(side_summaries, (ap_status, switch_status), strict=True)
            if summary and classify_optical_health(side_status) in {"warning", "critical"}
        ]
        normal_sides = [
            summary
            for summary, side_status in zip(side_summaries, (ap_status, switch_status), strict=True)
            if summary and classify_optical_health(side_status) == "normal"
        ]
        if status in {"warning", "critical"}:
            detail = "；".join([*abnormal_sides, *normal_sides])
            reason = (
                f"检测到{detail}。已计入{label}；当前 AP {'离线' if offline else '在线'}。"
                if detail
                else f"检测到光功率异常，已计入{label}；当前 AP {'离线' if offline else '在线'}。"
            )
        elif status == "normal":
            detail = "；".join(normal_sides)
            reason = f"{detail}。光衰结果正常" if detail else "光衰结果正常"
        else:
            reason = "无可用光衰数据"
        if freshness == "stale":
            reason = f"{reason} 数据已过期，不作为当前实时状态统计。"
        return reason

    @classmethod
    def _optical_side_summary(cls, side_label: str, status: str, power: object) -> str:
        if classify_optical_health(status) == "no_data":
            return ""
        power_text = cls._format_optical_power(power)
        suffix = f"：{power_text}" if power_text else ""
        if status == "abnormal" and parse_optical_rx_dbm(power) is not None:
            suffix = f"{suffix}（低于 {OPTICAL_BUSINESS_RX_MIN_DBM:.2f} dBm）"
        return f"{side_label}{display_optical_status(status)}{suffix}"

    @classmethod
    def _format_optical_power(cls, value: object) -> str:
        text = cls._clean_text(value)
        if not text:
            return ""
        if "dbm" in text.casefold():
            return text
        return f"{text} dBm" if re.search(r"[-+]?\d+(?:\.\d+)?", text) else text

    def _optical_freshness(
        self,
        ap_row: dict[str, object | None],
        module: dict[str, object],
        raw_status: str,
        ap_status: str,
        switch_status: str,
    ) -> str:
        if classify_optical_health(raw_status) == "no_data":
            return "unknown"
        timestamps = [ap_row.get("updated_at"), ap_row.get("collected_at")]
        if raw_status == switch_status:
            timestamps.extend((module.get("updated_at"), module.get("collected_at")))
        return classify_optical_freshness(*timestamps, now=self._now())

    def _now(self) -> datetime:
        now = self._now_provider()
        return now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)

    def _lldp_for(
        self,
        resource: dict[str, object | None],
        optical_by_ap: dict[tuple[str, str], dict[str, object | None]],
        context: dict[str, Any],
    ) -> AcLldpDTO:
        row = self._indexed_row(resource, optical_by_ap) or {}
        raw_neighbor_name = str(row.get("lldp_neighbor_name") or resource.get("lldp_neighbor_name") or resource.get("lldp_neighbor") or "")
        interface = str(row.get("neighbor_interface") or row.get("lldp_neighbor_interface") or resource.get("lldp_neighbor_interface") or "")
        switch_uuid = self._switch_uuid(resource, row, str(row.get("neighbor_device_name") or raw_neighbor_name), context)
        switch_name = str(context.get("device_name_by_uuid", {}).get(switch_uuid, "")) if switch_uuid else ""
        local_interface = str(row.get("lldp_local_interface") or resource.get("lldp_local_interface") or "")
        neighbor_mac = str(row.get("lldp_neighbor_mac") or resource.get("lldp_neighbor_mac") or row.get("neighbor_mac") or resource.get("neighbor_mac") or "")
        key = (switch_uuid, normalize_interface_name(interface).casefold())
        port = context["port_by_interface"].get(key, {})
        module = context["optical_by_interface"].get(key, {})
        module_status = ""
        if module:
            module_status = display_optical_status(
                compute_switch_status(
                    switch_rx_power=module.get("rx_power"),
                    switch_port_status=port.get("port_status") or port.get("link_status"),
                    alarm_low=module.get("rx_low_alarm"),
                    alarm_high=module.get("rx_high_alarm"),
                    warning_low=module.get("rx_low_warning"),
                    module_present=module.get("module_present") if "module_present" in module else module.get("has_module"),
                    no_module=module.get("no_module"),
                    module_status=module.get("module_status") or module.get("status"),
                )
            )
        match_status = str(row.get("lldp_match_status") or row.get("link_match_status") or resource.get("lldp_match_status") or "")
        return AcLldpDTO(
            switch_device_uuid=switch_uuid,
            switch_name=switch_name,
            switch_ip=str(context["device_ip_by_uuid"].get(switch_uuid, "")),
            interface_name=interface,
            lldp_neighbor=raw_neighbor_name,
            lldp_local_interface=local_interface,
            lldp_neighbor_mac=neighbor_mac,
            lldp_neighbor_interface=interface,
            port_status=str(port.get("port_status") or port.get("link_status") or ""),
            vlan=str(port.get("vlan") or port.get("pvid") or ""),
            optical_module_status=module_status,
            raw_match_status=match_status.casefold(),
            match_status=lldp_display_status(match_status) if match_status else "",
            source=str(row.get("lldp_source") or resource.get("lldp_source") or ""),
            updated_at=self._latest_text(row.get("lldp_collected_at"), resource.get("lldp_collected_at"), port.get("updated_at")),
        )

    def _switch_context(self, conn: sqlite3.Connection) -> dict[str, Any]:
        devices = self._safe_devices(conn)
        uuids_by_name: dict[str, set[str]] = {}
        ip_by_uuid: dict[str, str] = {}
        switch_uuids: set[str] = set()
        switch_station_by_uuid: dict[str, str] = {}
        switch_station_id_by_uuid: dict[str, str] = {}
        device_name_by_uuid: dict[str, str] = {}
        station_name_by_id, station_id_by_name = self._station_reference_context(conn)
        for row in devices:
            device_uuid = str(row["device_uuid"])
            device_name_by_uuid[device_uuid] = str(row["name"] or device_uuid)
            ip_by_uuid[device_uuid] = str(row["primary_address"] or "")
            if str(row["device_type"] or "").strip().casefold() in {"sw", "switch", "交换机"}:
                switch_uuids.add(device_uuid)
                station = self._clean_text(row["station"])
                if station:
                    switch_station_by_uuid[device_uuid] = station
                station_id = self._clean_text(row["station_id"])
                if station_id:
                    switch_station_id_by_uuid[device_uuid] = station_id
            for value in (row["name"], row["system_name"]):
                name = str(value or "").strip().casefold()
                if name:
                    uuids_by_name.setdefault(name, set()).add(device_uuid)
        uuid_by_name = {
            name: next(iter(device_uuids))
            for name, device_uuids in uuids_by_name.items()
            if len(device_uuids) == 1
        }
        port_by_interface: dict[tuple[str, str], dict[str, object]] = {}
        if self._table_exists(conn, "device_interfaces"):
            for row in conn.execute("SELECT * FROM device_interfaces"):
                item = dict(row)
                port_by_interface[(str(item.get("device_uuid") or ""), normalize_interface_name(item.get("interface_name")).casefold())] = item
        optical_by_interface: dict[tuple[str, str], dict[str, object]] = {}
        if self._table_exists(conn, "device_optical_modules"):
            for row in conn.execute("SELECT * FROM device_optical_modules"):
                item = dict(row)
                optical_by_interface[(str(item.get("device_uuid") or ""), normalize_interface_name(item.get("interface_name")).casefold())] = item
        return {
            "device_uuid_by_name": uuid_by_name,
            "device_ip_by_uuid": ip_by_uuid,
            "switch_device_uuids": switch_uuids,
            "switch_station_by_uuid": switch_station_by_uuid,
            "switch_station_id_by_uuid": switch_station_id_by_uuid,
            "device_name_by_uuid": device_name_by_uuid,
            "station_name_by_id": station_name_by_id,
            "station_id_by_name": station_id_by_name,
            "port_by_interface": port_by_interface,
            "optical_by_interface": optical_by_interface,
        }

    def _switch_context_for_resources(
        self,
        conn: sqlite3.Connection,
        resources: list[dict[str, object | None]],
        optical_rows: list[dict[str, object | None]],
    ) -> dict[str, Any]:
        """只为页内 AP 涉及的交换机读取端口和光模块上下文。"""
        devices = self._safe_devices(conn)
        uuids_by_name: dict[str, set[str]] = {}
        ip_by_uuid: dict[str, str] = {}
        switch_uuids: set[str] = set()
        switch_station_by_uuid: dict[str, str] = {}
        switch_station_id_by_uuid: dict[str, str] = {}
        device_name_by_uuid: dict[str, str] = {}
        station_name_by_id, station_id_by_name = self._station_reference_context(conn)
        for row in devices:
            device_uuid = str(row["device_uuid"])
            device_name_by_uuid[device_uuid] = str(row["name"] or device_uuid)
            ip_by_uuid[device_uuid] = str(row["primary_address"] or "")
            if str(row["device_type"] or "").strip().casefold() in {"sw", "switch", "交换机"}:
                switch_uuids.add(device_uuid)
                station = self._clean_text(row["station"])
                if station:
                    switch_station_by_uuid[device_uuid] = station
                station_id = self._clean_text(row["station_id"])
                if station_id:
                    switch_station_id_by_uuid[device_uuid] = station_id
            for value in (row["name"], row["system_name"]):
                name = str(value or "").strip().casefold()
                if name:
                    uuids_by_name.setdefault(name, set()).add(device_uuid)
        uuid_by_name = {
            name: next(iter(device_uuids))
            for name, device_uuids in uuids_by_name.items()
            if len(device_uuids) == 1
        }
        scoped_switch_uuids: set[str] = set()
        for row in [*resources, *optical_rows]:
            for field in ("switch_device_uuid", "neighbor_device_uuid", "lldp_neighbor_device_uuid"):
                value = self._clean_text(row.get(field))
                if value in switch_uuids:
                    scoped_switch_uuids.add(value)
            name = self._clean_text(
                row.get("neighbor_device_name")
                or row.get("lldp_neighbor_name")
                or row.get("lldp_neighbor")
            )
            resolved = uuid_by_name.get(name.casefold()) if name else None
            if resolved in switch_uuids:
                scoped_switch_uuids.add(str(resolved))

        def scoped_rows(table: str) -> list[dict[str, object]]:
            if not scoped_switch_uuids or not self._table_exists(conn, table):
                return []
            placeholders = ", ".join("?" for _ in scoped_switch_uuids)
            rows = conn.execute(
                f"SELECT * FROM {table} WHERE device_uuid IN ({placeholders})",
                sorted(scoped_switch_uuids),
            ).fetchall()
            return [dict(row) for row in rows]

        port_by_interface = {
            (
                str(row.get("device_uuid") or ""),
                normalize_interface_name(row.get("interface_name")).casefold(),
            ): row
            for row in scoped_rows("device_interfaces")
        }
        optical_by_interface = {
            (
                str(row.get("device_uuid") or ""),
                normalize_interface_name(row.get("interface_name")).casefold(),
            ): row
            for row in scoped_rows("device_optical_modules")
        }
        return {
            "device_uuid_by_name": uuid_by_name,
            "device_ip_by_uuid": ip_by_uuid,
            "switch_device_uuids": switch_uuids,
            "switch_station_by_uuid": switch_station_by_uuid,
            "switch_station_id_by_uuid": switch_station_id_by_uuid,
            "device_name_by_uuid": device_name_by_uuid,
            "station_name_by_id": station_name_by_id,
            "station_id_by_name": station_id_by_name,
            "port_by_interface": port_by_interface,
            "optical_by_interface": optical_by_interface,
        }

    @classmethod
    def _switch_uuid(
        cls,
        resource: dict[str, object | None],
        lldp_row: dict[str, object | None],
        switch_name: str,
        context: dict[str, Any],
    ) -> str:
        for field in ("switch_device_uuid", "neighbor_device_uuid", "lldp_neighbor_device_uuid"):
            explicit_uuid = cls._clean_text(lldp_row.get(field) or resource.get(field))
            if explicit_uuid:
                return explicit_uuid if explicit_uuid in context["switch_device_uuids"] else ""
        if is_generic_neighbor_name(switch_name):
            return ""
        return str(context["device_uuid_by_name"].get(switch_name.strip().casefold(), ""))

    @classmethod
    def _station(
        cls,
        row: dict[str, object | None],
        lldp: AcLldpDTO,
        context: dict[str, Any],
    ) -> dict[str, object]:
        manual_id = cls._clean_text(row.get("manual_station_id"))
        manual_name = cls._clean_text(row.get("manual_station_name"))
        manual_enabled = bool(row.get("manual_override_enabled"))
        station_names = context.get("station_name_by_id", {})
        auto_id = cls._clean_text(row.get("extension_station_id") or row.get("station_id"))
        auto_name = cls._clean_text(row.get("extension_station_name") or row.get("extension_station"))
        extension_status = str(row.get("extension_match_status") or "")
        lldp_station_id = str(context.get("switch_station_id_by_uuid", {}).get(lldp.switch_device_uuid, ""))
        lldp_station_name = str(
            station_names.get(lldp_station_id)
            or context.get("switch_station_by_uuid", {}).get(lldp.switch_device_uuid, "")
        )
        resource_station = cls._clean_text(row.get("resource_station_text"))
        topology = resolve_ap_topology(
            ApTopologyEvidence(
                lldp_valid=bool(
                    lldp.raw_match_status in {"matched", "partial"}
                    and lldp.switch_device_uuid
                ),
                lldp_conflict=not bool(lldp.switch_device_uuid)
                and lldp.raw_match_status in {"matched", "partial"},
                lldp_switch_uuid=lldp.switch_device_uuid,
                lldp_station_id=lldp_station_id,
                lldp_station=lldp_station_name,
                fit_ap_station=resource_station,
                fit_ap_section=cls._clean_text(
                    row.get("metadata_belong_section") or row.get("section_name")
                ),
                fit_ap_location=cls._clean_text(
                    row.get("metadata_location_note") or row.get("location_note")
                ),
                fit_ap_mileage=cls._clean_text(
                    row.get("metadata_mileage") or row.get("mileage")
                ),
                fit_ap_direction=cls._clean_text(
                    row.get("metadata_direction") or row.get("direction")
                ),
                fit_ap_belong_type=cls._clean_text(
                    row.get("metadata_belong_type") or row.get("belong_type")
                ),
                ac_runtime_station=manual_name if manual_enabled else "",
                base_station=(
                    str(station_names.get(auto_id) or auto_name)
                    if extension_status == "matched_by_mac"
                    else ""
                ),
                base_section=cls._clean_text(row.get("extension_section_name")),
                base_location=cls._clean_text(row.get("extension_location_desc")),
                base_mileage=cls._clean_text(row.get("extension_mileage_text")),
                base_direction=cls._clean_text(
                    row.get("extension_line_side") or row.get("extension_direction")
                ),
                base_belong_type=cls._clean_text(row.get("extension_belong_type")),
            )
        )
        station_source = topology.station.source
        station_detail = {
            "lldp_switch": "lldp_switch_suggestion",
            "fit_ap_runtime": "resource",
            "ac_runtime": "metadata",
            "base_data": "base_ap_mac",
        }.get(station_source, "conflict" if extension_status == "ambiguous_mac" else "empty")
        return {
            "effective_station_id": lldp_station_id if station_source == "lldp_switch" else "",
            "effective_station_name": topology.station.value,
            "station_source": station_detail,
            "station_source_detail": station_source,
            "station_confidence": topology.station.confidence / 100,
            "manual_station_id": manual_id,
            "manual_station_name": manual_name,
            "manual_override_enabled": manual_enabled,
            "auto_station_id": auto_id if extension_status == "matched_by_mac" else "",
            "auto_station_name": auto_name if extension_status == "matched_by_mac" else "",
            "auto_match_basis": "",
            "lldp_suggested_station_id": lldp_station_id,
            "lldp_suggested_station_name": lldp_station_name,
            "resource_station_text": resource_station,
            "topology": topology,
        }

    @staticmethod
    def _station_reference_context(conn: sqlite3.Connection) -> tuple[dict[str, str], dict[str, str]]:
        if not AcManagementQueryService._table_exists(conn, "ap_extension_points"):
            return {}, {}
        rows = conn.execute(
            """
            SELECT station_id, station_name
            FROM ap_extension_points
            WHERE belong_type = '__base_station__' AND TRIM(COALESCE(station_id, '')) != ''
            ORDER BY id
            """
        ).fetchall()
        by_id: dict[str, str] = {}
        by_name: dict[str, str] = {}
        for row in rows:
            station_id = str(row["station_id"] or "").strip()
            station_name = str(row["station_name"] or "").strip()
            if station_id and station_id not in by_id:
                by_id[station_id] = station_name
            if station_name and station_name.casefold() not in by_name:
                by_name[station_name.casefold()] = station_id
            elif station_name and by_name.get(station_name.casefold()) != station_id:
                by_name[station_name.casefold()] = ""
        return by_id, {key: value for key, value in by_name.items() if value}

    @staticmethod
    def _clean_text(value: object) -> str:
        text = str(value or "").strip()
        return "" if text.casefold() in {"", "-", "--", "n/a", "na", "none", "null", "unknown"} else text

    def _ac_rows(self, conn: sqlite3.Connection) -> list[dict[str, object]]:
        summaries = {
            str(row["ac_device_uuid"]): dict(row)
            for row in conn.execute("SELECT * FROM ac_ap_summary")
        } if self._table_exists(conn, "ac_ap_summary") else {}
        devices = {str(row["device_uuid"]): dict(row) for row in self._safe_devices(conn)}
        ids = {uuid for uuid, row in devices.items() if str(row.get("device_type") or "").upper() == "AC"} | set(summaries)
        rows: list[dict[str, object]] = []
        for device_uuid in sorted(ids, key=lambda value: str(devices.get(value, {}).get("name") or value)):
            device = devices.get(device_uuid, {})
            summary = summaries.get(device_uuid, {})
            rows.append(
                {
                    "device_uuid": device_uuid,
                    "name": device.get("name") or device_uuid,
                    "primary_address": device.get("primary_address") or "",
                    "https_port": device.get("https_port"),
                    "model": summary.get("model") or "",
                    "software_version": summary.get("software_version") or "",
                    "summary": summary,
                }
            )
        return rows

    @staticmethod
    def _safe_devices(conn: sqlite3.Connection) -> list[sqlite3.Row]:
        return conn.execute(
            "SELECT device_uuid, name, system_name, station, station_id, primary_address, https_port, device_type FROM devices ORDER BY name"
        ).fetchall()

    @staticmethod
    def _optical_index(rows: list[dict[str, object | None]]) -> dict[tuple[str, str], dict[str, object | None]]:
        result: dict[tuple[str, str], dict[str, object | None]] = {}
        for row in rows:
            ac_id = str(row.get("ac_device_uuid") or "")
            if row.get("ap_uuid"):
                result[(ac_id, f"uuid:{row['ap_uuid']}")] = row
            mac = normalize_ap_mac(row.get("ap_mac")).normalized
            if mac:
                result[(ac_id, f"mac:{mac}")] = row
        return result

    @staticmethod
    def _indexed_row(
        resource: dict[str, object | None],
        index: dict[tuple[str, str], dict[str, object | None]],
    ) -> dict[str, object | None] | None:
        ac_id = str(resource.get("ac_device_uuid") or "")
        if resource.get("ap_uuid"):
            found = index.get((ac_id, f"uuid:{resource['ap_uuid']}"))
            if found:
                return found
        mac = normalize_ap_mac(resource.get("ap_mac")).normalized
        return index.get((ac_id, f"mac:{mac}")) if mac else None

    @staticmethod
    def _append_unmatched_unauthenticated(
        resources: list[dict[str, object | None]],
        unauthenticated: list[dict[str, object | None]],
    ) -> list[dict[str, object | None]]:
        macs = {normalize_ap_mac(row.get("ap_mac")).normalized for row in resources if row.get("ap_mac")}
        result = [dict(row) for row in resources]
        for row in unauthenticated:
            mac = normalize_ap_mac(row.get("inferred_ap_mac")).normalized
            if mac and mac in macs:
                continue
            result.append(
                {
                    **row,
                    "ap_uuid": f"unauth-{row.get('id') or row.get('apid') or row.get('ap_name')}",
                    "ap_mac": row.get("inferred_ap_mac"),
                    "_web_unauthenticated": True,
                }
            )
        return result

    def _snapshot_row(self, site_id: str, snapshot_id: int | None) -> dict[str, object] | None:
        if snapshot_id is None:
            return None
        db_path = self._db_path(site_id)
        if not db_path.is_file():
            return None
        with closing(self._connect(db_path)) as conn:
            if not self._table_exists(conn, "config_snapshots"):
                return None
            row = conn.execute(
                """
                SELECT snapshot.*, d.name AS ac_name
                FROM config_snapshots snapshot
                LEFT JOIN devices d ON d.device_uuid = snapshot.device_uuid
                LEFT JOIN ac_ap_summary s ON s.ac_device_uuid = snapshot.device_uuid
                WHERE snapshot.id = ?
                  AND (upper(coalesce(d.device_type, '')) = 'AC' OR s.ac_device_uuid IS NOT NULL)
                LIMIT 1
                """,
                (int(snapshot_id),),
            ).fetchone()
        return dict(row) if row is not None else None

    def _snapshot_dto(self, site_id: str, row: dict[str, object]) -> AcConfigSnapshotDTO:
        try:
            path = self._snapshot_path(site_id, row)
            exists = path.is_file()
            size = path.stat().st_size if exists else 0
        except ValueError:
            exists = False
            size = 0
            path = Path(str(row.get("file_path") or ""))
        error = str(row.get("error_message") or "")
        status = "FAILED" if error else "AVAILABLE" if exists else "MISSING"
        return AcConfigSnapshotDTO(
            id=int(row["id"]),
            device_id=str(row.get("device_uuid") or ""),
            ac_name=str(row.get("ac_name") or row.get("device_uuid") or ""),
            timestamp=str(row.get("timestamp") or ""),
            type=str(row.get("type") or ""),
            status=status,
            size_bytes=size,
            error_summary=error,
            path_id=f"snapshot:{row['id']}",
            file_name=path.name,
            created_at=str(row.get("created_at") or ""),
        )

    def _snapshot_text(self, site_id: str, row: dict[str, object]) -> str:
        path = self._snapshot_path(site_id, row)
        text = path.read_text(encoding="utf-8")
        return extract_h3c_configuration_body(text) if str(row.get("type") or "") in {"running", "saved"} else text

    def _snapshot_path(self, site_id: str, row: dict[str, object]) -> Path:
        raw = Path(str(row.get("file_path") or ""))
        if raw.is_absolute() or ".." in raw.parts:
            raise ValueError("配置快照路径越界")
        root = self.paths.site_dir(SiteManager(self.paths).validate_site_name(site_id)).resolve()
        candidate = (root / raw).resolve()
        if candidate == root or root not in candidate.parents:
            raise ValueError("配置快照路径越界")
        return candidate

    def _config_pair(
        self,
        site_id: str,
        selected: dict[str, object],
        other: dict[str, object] | None,
    ) -> tuple[dict[str, object], dict[str, object]]:
        rows = [selected, other] if other is not None else []
        if other is None:
            db_path = self._db_path(site_id)
            with closing(self._connect(db_path)) as conn:
                rows = [
                    dict(row)
                    for row in conn.execute(
                        """
                        SELECT snapshot.*, d.name AS ac_name
                        FROM config_snapshots snapshot
                        LEFT JOIN devices d ON d.device_uuid = snapshot.device_uuid
                        WHERE snapshot.device_uuid = ? AND snapshot.timestamp = ? AND snapshot.type IN ('running', 'saved')
                        ORDER BY snapshot.id DESC
                        """,
                        (selected["device_uuid"], selected["timestamp"]),
                    ).fetchall()
                ]
        by_type = {str(row.get("type") or ""): row for row in rows if row is not None}
        running = by_type.get("running")
        saved = by_type.get("saved")
        if running is None or saved is None:
            raise ValueError("当前快照缺少同批次 running/saved 配置，无法对比")
        if str(running.get("device_uuid")) != str(saved.get("device_uuid")):
            raise ValueError("只能对比同一 AC 的配置快照")
        return running, saved

    def _db_path(self, site_id: str) -> Path:
        selected = SiteManager(self.paths).validate_site_name(str(site_id or "demo"))
        return self.paths.site_db_path(selected)

    @staticmethod
    def _connect(db_path: Path) -> sqlite3.Connection:
        conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
            (table_name,),
        ).fetchone() is not None

    @staticmethod
    def _radio_present(row: dict[str, object | None], rid: int) -> int:
        return int(any(row.get(f"rid{rid}_{field}") not in (None, "") for field in ("channel", "bandwidth", "tx_power", "bbssid")))

    @staticmethod
    def _online_status(row: dict[str, object | None]) -> str:
        return classify_fit_ap_state(
            row.get("state"),
            row.get("state_raw"),
            row.get("state_display"),
        )

    @staticmethod
    def _page(
        items: list[AcApDTO],
        page: int,
        page_size: int,
        *,
        filter_options: AcApFilterOptionsDTO | None = None,
    ) -> AcApPageDTO:
        current_page = max(1, int(page))
        size = max(1, min(int(page_size), 200))
        start = (current_page - 1) * size
        return AcApPageDTO(
            items=items[start : start + size],
            total=len(items),
            page=current_page,
            page_size=size,
            filter_options=filter_options or AcApFilterOptionsDTO(),
        )

    @staticmethod
    def _ap_sort_key(item: AcApDTO, sort_by: str) -> object:
        if sort_by == "topology":
            return fit_ap_topology_sort_key(item)
        if sort_by == "ip":
            try:
                return (0, int(ipaddress.ip_address(item.ip)))
            except ValueError:
                return (1, item.ip.casefold())
        if sort_by == "status":
            return item.status
        if sort_by == "station":
            return (item.station.casefold(), item.section.casefold(), item.name.casefold())
        if sort_by == "section":
            return (item.section.casefold(), item.station.casefold(), item.name.casefold())
        if sort_by == "mileage":
            return parse_mileage_to_meters(item.mileage) or -1
        if sort_by in {"optical_status", "optical_value"}:
            rank = {"no_data": 0, "normal": 1, "warning": 2, "critical": 3}
            return (rank.get(item.optical_status, 0), item.optical_rx_power)
        if sort_by == "updated_at":
            return item.updated_at
        return item.name.casefold()

    @staticmethod
    def _int(value: object, default: int) -> int:
        try:
            return int(value) if value is not None else int(default)
        except (TypeError, ValueError):
            return int(default)

    @staticmethod
    def _optional_int(value: object) -> int | None:
        try:
            return int(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _latest_text(*values: object) -> str:
        return max((str(value) for value in values if value not in (None, "")), default="")


__all__ = ["AcManagementQueryService"]
