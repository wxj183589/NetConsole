from __future__ import annotations

import ipaddress
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from netconsole.core.optical_severity_engine import display_optical_status, worse_optical_severity
from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.core.sources.ap_source import compute_ap_status
from netconsole.core.sources.switch_source import compute_switch_status
from netconsole.models.api.ac_management import (
    AcApDTO,
    AcApDetailDTO,
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
from netconsole.repositories.ac_repository import AcRepository
from netconsole.services.ap_extension_import import normalize_ap_mac
from netconsole.services.config_lifecycle_service import compare_config_text, extract_h3c_configuration_body
from netconsole.services.fit_ap_link_info import lldp_display_status
from netconsole.services.offline_ap_ledger import is_fit_ap_offline
from netconsole.utils.interface_normalize import normalize_interface_name
from netconsole.utils.mileage import format_track_mileage, parse_mileage_to_meters


_ABNORMAL_OPTICAL = {"notice", "warning", "alarm", "link_abnormal", "link_down", "no_light"}
_CRITICAL_OPTICAL = {"alarm", "link_abnormal", "link_down", "no_light"}
_NO_DATA_OPTICAL = {"", "unknown", "not_collected", "skipped", "offline", "no_module"}


class _ReadonlyDatabase:
    """供现有 Repository 复用的 SQLite 只读连接门面。"""

    def __init__(self, path: Path) -> None:
        self.path = path

    def connect(self) -> sqlite3.Connection:
        return AcManagementQueryService._connect(self.path)


class AcManagementQueryService:
    """AC 管理 Web 页面的 GET-only 查询边界。"""

    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths

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
            unauthenticated = repository.list_fit_ap_unauthenticated(ac_id)
            optical_by_ap = self._optical_index(repository.list_fit_ap_optical(ac_id))
            summary = dict(ac.get("summary") or {})
            optical_count = 0
            for row in resources:
                optical = self._optical_for(row, optical_by_ap, context)
                optical_count += optical.optical_status in {"warning", "critical"}
            online = self._int(summary.get("online_aps"), sum(not is_fit_ap_offline(row) for row in resources))
            offline = self._int(summary.get("offline_aps"), sum(is_fit_ap_offline(row) for row in resources))
            total = self._int(summary.get("total_aps"), len(resources))
            updated_at = self._latest_text(
                summary.get("updated_at"),
                *(row.get("updated_at") for row in resources),
            )
            overviews.append(
                AcOverviewDTO(
                    id=ac_id,
                    name=str(ac.get("name") or ac_id),
                    management_ip=str(ac.get("primary_address") or ""),
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
                    optical_anomalies=optical_count,
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
        sort_by: str = "name",
        sort_order: str = "asc",
    ) -> AcApPageDTO:
        items = self._filtered_aps(
            site_id,
            ac_id=ac_id,
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
        return self._page(items, page, page_size)

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
            sort_by="optical_status",
            sort_order="desc",
        )
        return self._page(items, page, page_size)

    def get_ap_detail(self, site_id: str, ap_id: str) -> AcApDetailDTO | None:
        record = self._find_ap(site_id, ap_id)
        if record is None:
            return None
        item, raw, optical, lldp = record
        return AcApDetailDTO(ap=item, radios=self._radios(raw), lldp=lldp, optical=optical, connection=self._connection(raw))

    def list_all_ap_details(self, site_id: str) -> list[AcApDetailDTO]:
        return [
            AcApDetailDTO(ap=item, radios=self._radios(raw), lldp=lldp, optical=optical, connection=self._connection(raw))
            for item, raw, optical, lldp in self._ap_records(site_id)
        ]

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
        result = compare_config_text(self._snapshot_text(site_id, running), self._snapshot_text(site_id, saved))
        max_chars = max(1, min(int(limit), 500_000))
        raw_diff = result.raw_diff[:max_chars]
        return AcConfigDiffDTO(
            from_snapshot_id=int(saved["id"]),
            to_snapshot_id=int(running["id"]),
            added=result.added,
            removed=result.removed,
            modified=result.modified,
            raw_diff=raw_diff,
            truncated=len(result.raw_diff) > len(raw_diff),
        )

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
        sort_by: str = "name",
        sort_order: str = "asc",
    ) -> list[AcApDTO]:
        records = self._ap_records(site_id, ac_id=ac_id)
        items = [record[0] for record in records]
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
        optical_rows = repository.list_fit_ap_optical(ac_id) if ac_id else repository.list_all_fit_ap_optical()
        optical_by_ap = self._optical_index(optical_rows)
        with closing(self._connect(db_path)) as conn:
            context = self._switch_context(conn)
            ac_names = {str(row["device_uuid"]): str(row["name"] or row["device_uuid"]) for row in self._safe_devices(conn)}
        records = []
        for row in resources:
            optical = self._optical_for(row, optical_by_ap, context)
            lldp = self._lldp_for(row, optical_by_ap, context)
            records.append((self._ap_dto(row, optical, lldp, ac_names), row, optical, lldp))
        return records

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
    ) -> AcApDTO:
        ac_id = str(row.get("ac_device_uuid") or "")
        unauthenticated = bool(row.get("is_new_online_ap") or row.get("_web_unauthenticated"))
        status = "unauthenticated" if unauthenticated else "offline" if is_fit_ap_offline(row) else self._online_status(row)
        mileage = format_track_mileage(row.get("mileage"), direction=str(row.get("direction") or ""))
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
            online_time=str(row.get("online_time") or ""),
            is_unauthenticated=unauthenticated,
            radio1_status=str(row.get("rid1_status") or ""),
            radio2_status=str(row.get("rid2_status") or ""),
            radio1_channel=str(row.get("rid1_channel") or ""),
            radio2_channel=str(row.get("rid2_channel") or ""),
            radio1_power=str(row.get("rid1_tx_power") or ""),
            radio2_power=str(row.get("rid2_tx_power") or ""),
            station=str(row.get("site") or row.get("site_name") or row.get("extension_station_name") or ""),
            section=str(row.get("section_name") or row.get("metadata_belong_section") or ""),
            mileage=mileage if mileage != "-" else "",
            direction=str(row.get("direction") or row.get("extension_line_side") or ""),
            switch_name=lldp.switch_name,
            switch_interface=lldp.interface_name,
            lldp_status=lldp.match_status,
            optical_status=optical.optical_status,
            optical_severity=optical.optical_severity,
            optical_rx_power=optical.rx_power or optical.switch_rx_power,
            updated_at=self._latest_text(row.get("updated_at"), optical.updated_at, lldp.updated_at),
        )

    @staticmethod
    def _radios(row: dict[str, object | None]) -> list[AcRadioDTO]:
        return [
            AcRadioDTO(
                radio_id=rid,
                status=str(row.get(f"rid{rid}_status") or ""),
                mode=str(row.get(f"rid{rid}_mode") or ""),
                band=str(row.get(f"rid{rid}_band") or ""),
                channel=str(row.get(f"rid{rid}_channel") or ""),
                bandwidth=str(row.get(f"rid{rid}_bandwidth") or ""),
                usage=str(row.get(f"rid{rid}_usage") or ""),
                tx_power=str(row.get(f"rid{rid}_tx_power") or ""),
                clients=int(row.get(f"rid{rid}_clients") or 0),
                bssid=str(row.get(f"rid{rid}_bbssid") or ""),
                updated_at=str(row.get("updated_at") or row.get("collected_at") or ""),
            )
            for rid in (1, 2)
        ]

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
        row = self._indexed_row(resource, optical_by_ap)
        if row is None:
            return AcOpticalDTO(anomaly_reason="未采集光衰数据")
        switch_name = str(row.get("neighbor_device_name") or row.get("lldp_neighbor_name") or resource.get("lldp_neighbor_name") or "")
        interface = str(row.get("neighbor_interface") or row.get("lldp_neighbor_interface") or resource.get("lldp_neighbor_interface") or "")
        switch_uuid = context["device_uuid_by_name"].get(switch_name.casefold(), "")
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
            switch_status = compute_switch_status(
                switch_rx_power=module.get("rx_power"),
                switch_port_status=port.get("port_status") or port.get("link_status"),
                alarm_low=module.get("rx_low_alarm"),
                alarm_high=module.get("rx_high_alarm"),
                warning_low=module.get("rx_low_warning"),
            )
            switch_rx = str(module.get("rx_power") or "")
        else:
            switch_status = compute_switch_status(switch_rx_power=row.get("neighbor_rx_power"))
            switch_rx = str(row.get("neighbor_rx_power") or "")
        raw_status = worse_optical_severity(switch_status, compute_ap_status(row))
        offline = is_fit_ap_offline(resource)
        if raw_status in _ABNORMAL_OPTICAL:
            status = ("critical" if raw_status in _CRITICAL_OPTICAL else "warning") if offline else "unrelated"
        elif raw_status in _NO_DATA_OPTICAL:
            status = "no_data"
        else:
            status = "normal"
        label = display_optical_status(raw_status)
        if status == "unrelated":
            reason = f"检测到{label}，但 AP 未离线，不计入光衰异常"
        elif status in {"warning", "critical"}:
            reason = f"AP 离线且光衰状态为{label}"
        elif status == "normal":
            reason = "光衰结果正常"
        else:
            reason = "无可用光衰数据"
        return AcOpticalDTO(
            optical_status=status,
            optical_severity=status,
            raw_status=raw_status,
            ap_offline_related=offline and status in {"warning", "critical"},
            anomaly_reason=reason,
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

    def _lldp_for(
        self,
        resource: dict[str, object | None],
        optical_by_ap: dict[tuple[str, str], dict[str, object | None]],
        context: dict[str, Any],
    ) -> AcLldpDTO:
        row = self._indexed_row(resource, optical_by_ap) or {}
        switch_name = str(row.get("neighbor_device_name") or row.get("lldp_neighbor_name") or resource.get("lldp_neighbor_name") or resource.get("lldp_neighbor") or "")
        interface = str(row.get("neighbor_interface") or row.get("lldp_neighbor_interface") or resource.get("lldp_neighbor_interface") or "")
        switch_uuid = context["device_uuid_by_name"].get(switch_name.casefold(), "")
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
                )
            )
        match_status = str(row.get("lldp_match_status") or row.get("link_match_status") or resource.get("lldp_match_status") or "")
        return AcLldpDTO(
            switch_name=switch_name,
            switch_ip=str(context["device_ip_by_uuid"].get(switch_uuid, "")),
            interface_name=interface,
            lldp_neighbor=str(row.get("lldp_neighbor") or resource.get("lldp_neighbor") or switch_name),
            port_status=str(port.get("port_status") or port.get("link_status") or ""),
            vlan=str(port.get("vlan") or port.get("pvid") or ""),
            optical_module_status=module_status,
            match_status=lldp_display_status(match_status) if match_status else "",
            source=str(row.get("lldp_source") or resource.get("lldp_source") or ""),
            updated_at=self._latest_text(row.get("lldp_collected_at"), resource.get("lldp_collected_at"), port.get("updated_at")),
        )

    def _switch_context(self, conn: sqlite3.Connection) -> dict[str, Any]:
        devices = self._safe_devices(conn)
        uuid_by_name: dict[str, str] = {}
        ip_by_uuid: dict[str, str] = {}
        for row in devices:
            device_uuid = str(row["device_uuid"])
            ip_by_uuid[device_uuid] = str(row["primary_address"] or "")
            for value in (row["name"], row["system_name"]):
                name = str(value or "").strip().casefold()
                if name:
                    uuid_by_name[name] = device_uuid
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
            "port_by_interface": port_by_interface,
            "optical_by_interface": optical_by_interface,
        }

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
            "SELECT device_uuid, name, system_name, primary_address, https_port, device_type FROM devices ORDER BY name"
        ).fetchall()

    @staticmethod
    def _optical_index(rows: list[dict[str, object | None]]) -> dict[tuple[str, str], dict[str, object | None]]:
        result: dict[tuple[str, str], dict[str, object | None]] = {}
        for row in rows:
            ac_id = str(row.get("ac_device_uuid") or "")
            if row.get("ap_uuid"):
                result[(ac_id, f"uuid:{row['ap_uuid']}")] = row
            if row.get("ap_name"):
                result[(ac_id, f"name:{str(row['ap_name']).strip().casefold()}")] = row
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
        return index.get((ac_id, f"name:{str(resource.get('ap_name') or '').strip().casefold()}"))

    @staticmethod
    def _append_unmatched_unauthenticated(
        resources: list[dict[str, object | None]],
        unauthenticated: list[dict[str, object | None]],
    ) -> list[dict[str, object | None]]:
        names = {str(row.get("ap_name") or "").strip().casefold() for row in resources}
        macs = {normalize_ap_mac(row.get("ap_mac")).normalized for row in resources if row.get("ap_mac")}
        result = [dict(row) for row in resources]
        for row in unauthenticated:
            name = str(row.get("ap_name") or "").strip().casefold()
            mac = normalize_ap_mac(row.get("inferred_ap_mac")).normalized
            if (name and name in names) or (mac and mac in macs):
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
        text = " ".join(str(row.get(field) or "") for field in ("state", "state_raw", "state_display")).upper()
        return "online" if any(token in text for token in ("R/M", "运行", "ONLINE", " UP", "RUN")) else "unknown"

    @staticmethod
    def _page(items: list[AcApDTO], page: int, page_size: int) -> AcApPageDTO:
        current_page = max(1, int(page))
        size = max(1, min(int(page_size), 200))
        start = (current_page - 1) * size
        return AcApPageDTO(items=items[start : start + size], total=len(items), page=current_page, page_size=size)

    @staticmethod
    def _ap_sort_key(item: AcApDTO, sort_by: str) -> object:
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
            rank = {"no_data": 0, "normal": 1, "unrelated": 2, "warning": 3, "critical": 4}
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
