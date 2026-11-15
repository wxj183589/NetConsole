from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Iterable, Mapping
import json

from netconsole.core.ap_identity.normalizers import normalize_mac_key
from netconsole.services.fit_ap_link_info import normalize_interface_key
from netconsole.parsers.h3c.ac.fit_ap_lldp_neighbor_parser import parse_fit_ap_lldp_neighbors
from netconsole.parsers.h3c.ac.wlan_ap_address_parser import parse_wlan_ap_addresses
from netconsole.parsers.h3c.ac.wlan_ap_parser import parse_wlan_ap_list


LEDGER_HEADERS = (
    "线路名称", "系统类型", "网络域", "归属类型", "位置类型",
    "是否参与正线判断", "车站", "AP名称", "AP MAC", "上联交换机",
    "上联端口", "点位说明", "备注", "来源文件", "来源工作表", "来源行号",
    "建设阶段", "来源类型", "来源设备", "来源时间", "邻居侧 Port ID",
)


@dataclass(frozen=True)
class ApLedgerRow:
    station_name: str
    ap_name: str
    ap_mac_display: str = ""
    uplink_switch: str = ""
    uplink_port: str = ""
    status: str = "MATCHED"
    match_method: str = ""
    source_file: str = ""
    source_sheet: str = ""
    source_row: int = 0
    reason: str = ""
    build_phase: str = ""
    source_type: str = "LLDP"
    source_device: str = ""
    source_timestamp: str = ""
    lldp_neighbor_interface: str = ""
    location_class: str = "UNKNOWN"
    participates_in_mainline: int | None = None

    def import_values(self) -> dict[str, object]:
        return {
            "station_name": self.station_name,
            "ap_name": self.ap_name,
            "ap_mac_display": self.ap_mac_display,
            "uplink_switch": self.uplink_switch,
            "uplink_port": self.uplink_port,
            "belong_type": "station",
            "location_class": self.location_class,
            "participates_in_mainline": self.participates_in_mainline,
            "source_file": self.source_file,
            "source_sheet": self.source_sheet,
            "source_row": self.source_row,
            "remark": self.reason,
            "raw_payload_json": json.dumps(
                {
                    "source_type": self.source_type,
                    "source_device": self.source_device,
                    "source_timestamp": self.source_timestamp,
                    "build_phase": self.build_phase,
                    "lldp_neighbor_interface": self.lldp_neighbor_interface,
                    "identity_evidence": "exact_full_mac",
                    "static_authority": "switch_lldp",
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        }


@dataclass(frozen=True)
class ApLedgerReport:
    rows: tuple[ApLedgerRow, ...] = ()
    unmatched: tuple[ApLedgerRow, ...] = ()
    conflicts: tuple[ApLedgerRow, ...] = ()
    stats: dict[str, int] = field(default_factory=dict)

    def write_xlsx(self, path: Path, *, include_audit_sheets: bool = False) -> Path:
        from openpyxl import Workbook

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "ap_switch_port_point_table"
        sheet.append(LEDGER_HEADERS)
        for row in self.rows:
            values = row.import_values()
            sheet.append([
                "", "轨旁 AP", "", values["belong_type"], values["location_class"],
                values["participates_in_mainline"], values["station_name"], values["ap_name"],
                values["ap_mac_display"], values["uplink_switch"], values["uplink_port"],
                "", values["remark"], values["source_file"], values["source_sheet"], values["source_row"],
                row.build_phase, row.source_type, row.source_device, row.source_timestamp,
                row.lldp_neighbor_interface,
            ])
        if include_audit_sheets:
            self._write_rows(workbook, "unmatched", self.unmatched)
            self._write_rows(workbook, "conflicts", self.conflicts)
            stats = workbook.create_sheet("stats")
            stats.append(("指标", "数量"))
            for key, value in sorted(self.stats.items()):
                stats.append((key, value))
        workbook.save(target)
        return target

    @staticmethod
    def _write_rows(workbook, title: str, rows: Iterable[ApLedgerRow]) -> None:
        sheet = workbook.create_sheet(title)
        sheet.append(("车站", "AP名称", "AP MAC", "上联交换机", "上联端口", "状态", "匹配方式", "原因", "来源文件", "来源行号", "建设阶段", "来源设备", "来源时间", "邻居侧 Port ID"))
        for row in rows:
            sheet.append((row.station_name, row.ap_name, row.ap_mac_display, row.uplink_switch, row.uplink_port, row.status, row.match_method, row.reason, row.source_file, row.source_row, row.build_phase, row.source_device, row.source_timestamp, row.lldp_neighbor_interface))


@dataclass(frozen=True)
class ApLedgerSource:
    """One authoritative switch LLDP capture with its explicit station scope."""

    station_name: str
    lldp_output: str
    switch_name: str = ""
    source_file: str = ""
    source_sheet: str = ""
    source_timestamp: str = ""
    build_phase: str = ""


def build_ap_ledger(
    *,
    station_name: str,
    ac_ap_all_output: str,
    ac_ap_address_output: str,
    switch_lldp_outputs: Iterable[str],
    switch_name: str = "",
    source_file: str = "",
    source_sheet: str = "",
) -> ApLedgerReport:
    """Build the importable AP ledger using exact MAC/name evidence only.

    A switch's local interface is exported as the AP uplink port. The LLDP
    neighbor port is retained only as evidence and is never substituted for
    the switch local interface.
    """

    report = build_ap_ledger_from_sources(
        ac_ap_all_output=ac_ap_all_output,
        ac_ap_address_output=ac_ap_address_output,
        sources=(ApLedgerSource(
            station_name=station_name,
            lldp_output="\n".join(switch_lldp_outputs),
            switch_name=switch_name,
            source_file=source_file,
            source_sheet=source_sheet,
        ),),
    )
    # Preserve the original narrow stats contract for existing callers. The
    # multi-source entry point exposes the additional audit counters.
    legacy_keys = ("ac_ap_rows", "matched_rows", "unmatched_rows", "conflict_rows", "lldp_rows")
    return ApLedgerReport(
        report.rows,
        report.unmatched,
        report.conflicts,
        {key: report.stats.get(key, 0) for key in legacy_keys},
    )


def build_ap_ledger_from_sources(
    *,
    ac_ap_all_output: str,
    ac_ap_address_output: str,
    sources: Iterable[ApLedgerSource | Mapping[str, object]],
) -> ApLedgerReport:
    """Build one Site-scoped ledger from multiple raw switch captures.

    LLDP is authoritative for station, switch and switch-local port. The AC
    address table only supplies the known AP MAC set; no station or port is
    inferred from AC fields.
    """

    ap_rows = parse_wlan_ap_list(ac_ap_all_output)
    addresses = parse_wlan_ap_addresses(ac_ap_address_output)
    address_mac_keys = {
        key for value in addresses.values()
        if (key := _mac_key(value.get("ap_mac")))
    }
    normalized_sources = [_source_value(value) for value in sources]
    lldp_rows: list[dict[str, object | None]] = []
    for source in normalized_sources:
        for row_number, row in enumerate(parse_fit_ap_lldp_neighbors(source.lldp_output), start=1):
            mac_key = _mac_key(row.get("lldp_neighbor_mac_normalized") or row.get("lldp_neighbor_mac"))
            lldp_rows.append({
                **row,
                "_station_name": source.station_name,
                "_switch_name": source.switch_name,
                "_source_file": source.source_file,
                "_source_sheet": source.source_sheet,
                "_source_row": row_number,
                "_source_timestamp": source.source_timestamp,
                "_build_phase": source.build_phase,
                "_is_ap": bool(mac_key and mac_key in address_mac_keys),
            })
    lldp_by_mac: dict[str, list[dict[str, object | None]]] = defaultdict(list)
    lldp_by_name: dict[str, list[dict[str, object | None]]] = defaultdict(list)
    for row in lldp_rows:
        if not row.get("_is_ap"):
            continue
        mac = str(row.get("lldp_neighbor_mac_normalized") or "").casefold()
        name = str(row.get("lldp_neighbor_name") or "").strip().casefold()
        if mac:
            lldp_by_mac[mac].append(row)
        if name:
            lldp_by_name[name].append(row)

    matched: list[ApLedgerRow] = []
    unmatched: list[ApLedgerRow] = []
    conflicts: list[ApLedgerRow] = []
    for index, ap in enumerate(ap_rows, start=1):
        ap_name = str(ap.get("ap_name") or "").strip()
        address = addresses.get(ap_name) or addresses.get(next((key for key in addresses if key.casefold() == ap_name.casefold()), ""), {})
        raw_mac = str(address.get("ap_mac") or "").strip()
        mac_key = _mac_key(raw_mac)
        candidates = _distinct_lldp_rows(lldp_by_mac.get(mac_key, [])) if mac_key else []
        exact_name_candidates = lldp_by_name.get(ap_name.casefold(), []) if not mac_key else []
        if len(candidates) > 1:
            row = _row_from_lldp(ap_name, raw_mac, candidates[0], "CONFLICT", "exact MAC matched multiple switch ports")
            conflicts.append(row)
            continue
        if not candidates and len(exact_name_candidates) == 1:
            candidates = exact_name_candidates
        if not candidates:
            unmatched.append(_row(
                "",
                ap_name, raw_mac,
                "",
                "",
                "",
                index, "UNMATCHED", "no exact AP MAC or AP name LLDP match",
            ))
            continue
        lldp = candidates[0]
        lldp_mac = str(lldp.get("lldp_neighbor_mac") or "")
        if mac_key and _mac_key(lldp_mac) and mac_key != _mac_key(lldp_mac):
            conflicts.append(_row_from_lldp(ap_name, raw_mac, lldp, "CONFLICT", "AP MAC and LLDP MAC disagree"))
            continue
        neighbor_name = str(lldp.get("lldp_neighbor_name") or "").strip()
        name_reason = (
            f"MAC 精确匹配但名称字段不同：AC={ap_name}，LLDP={neighbor_name}"
            if neighbor_name and ap_name.casefold() != neighbor_name.casefold()
            else ""
        )
        missing_switch_reason = (
            "LLDP 回显缺少交换机提示符，交换机身份待现场确认"
            if not str(lldp.get("_switch_name") or "").strip()
            else ""
        )
        matched.append(ApLedgerRow(
            station_name=str(lldp.get("_station_name") or ""), ap_name=ap_name,
            ap_mac_display=raw_mac or lldp_mac,
            uplink_switch=str(lldp.get("_switch_name") or ""),
            uplink_port=str(lldp.get("lldp_local_interface") or ""),
            match_method="exact_mac" if mac_key else "exact_ap_name",
            source_file=str(lldp.get("_source_file") or ""),
            source_sheet=str(lldp.get("_source_sheet") or ""),
            source_row=int(lldp.get("_source_row") or 0),
            build_phase=str(lldp.get("_build_phase") or ""),
            source_device=str(lldp.get("_switch_name") or ""),
            source_timestamp=str(lldp.get("_source_timestamp") or ""),
            lldp_neighbor_interface=str(lldp.get("lldp_neighbor_interface") or ""),
            reason="；".join(reason for reason in (name_reason, missing_switch_reason) if reason),
        ))

    matched_by_mac: dict[str, list[ApLedgerRow]] = defaultdict(list)
    for item in matched:
        key = _mac_key(item.ap_mac_display)
        if key:
            matched_by_mac[key].append(item)
    for mac_key, items in matched_by_mac.items():
        names = {item.ap_name.casefold() for item in items if item.ap_name.strip()}
        if len(names) <= 1:
            continue
        conflicts.extend(
            replace(
                item,
                status="CONFLICT",
                reason="同一完整 MAC 在 AC 资料中关联多个 AP 名称，未自动选择",
            )
            for item in items
        )
        matched[:] = [item for item in matched if _mac_key(item.ap_mac_display) != mac_key]

    # Keep evidence but reject automatic choice when the same MAC moves or is
    # duplicated across station/switch/local-port observations.
    for mac_key, candidates in lldp_by_mac.items():
        identities = {
            (str(row.get("_station_name") or ""), str(row.get("_switch_name") or ""), str(row.get("lldp_local_interface_normalized") or ""))
            for row in candidates
        }
        if len(identities) > 1:
            conflicts.extend(
                _row_from_lldp(
                    str(row.get("lldp_neighbor_name") or ""),
                    str(row.get("lldp_neighbor_mac") or ""),
                    row,
                    "CONFLICT",
                    "same MAC is observed at different station/switch/local ports",
                )
                for row in candidates
            )
            matched[:] = [item for item in matched if _mac_key(item.ap_mac_display) != mac_key]

    by_port: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    rows_by_port: dict[tuple[str, str, str], list[dict[str, object | None]]] = defaultdict(list)
    for row in lldp_rows:
        if not row.get("_is_ap"):
            continue
        key = (str(row.get("_station_name") or ""), str(row.get("_switch_name") or ""), str(row.get("lldp_local_interface_normalized") or ""))
        mac = _mac_key(row.get("lldp_neighbor_mac_normalized") or row.get("lldp_neighbor_mac"))
        if key[2] and mac:
            by_port[key].add(mac)
            rows_by_port[key].append(row)
    for key, macs in by_port.items():
        if len(macs) > 1:
            conflicts.extend(
                _row_from_lldp(
                    str(row.get("lldp_neighbor_name") or ""),
                    str(row.get("lldp_neighbor_mac") or ""),
                    row,
                    "CONFLICT",
                    "same switch local port is observed for different AP MACs",
                )
                for row in rows_by_port[key]
            )
            matched[:] = [item for item in matched if not (
                item.station_name == key[0]
                and item.uplink_switch == key[1]
                and normalize_interface_key(item.uplink_port).casefold() == key[2].casefold()
            )]
    stats = {
        "ac_ap_rows": len(ap_rows),
        "ac_address_rows": len(addresses),
        "matched_rows": len(matched),
        "unmatched_rows": len(unmatched),
        "conflict_rows": len(conflicts),
        "lldp_rows": len(lldp_rows),
        "lldp_ap_rows": sum(bool(row.get("_is_ap")) for row in lldp_rows),
        "non_ap_lldp_rows": sum(not bool(row.get("_is_ap")) for row in lldp_rows),
        "station_count": len({str(row.get("_station_name") or "") for row in lldp_rows if row.get("_station_name")}),
        "pending_switch_rows": sum(
            bool(row.get("_is_ap")) and not str(row.get("_switch_name") or "").strip()
            for row in lldp_rows
        ),
    }
    return ApLedgerReport(tuple(matched), tuple(unmatched), tuple(conflicts), stats)


def _source_value(value: ApLedgerSource | Mapping[str, object]) -> ApLedgerSource:
    if isinstance(value, ApLedgerSource):
        return value
    return ApLedgerSource(
        station_name=str(value.get("station_name") or ""),
        lldp_output=str(value.get("lldp_output") or ""),
        switch_name=str(value.get("switch_name") or ""),
        source_file=str(value.get("source_file") or ""),
        source_sheet=str(value.get("source_sheet") or ""),
        source_timestamp=str(value.get("source_timestamp") or ""),
        build_phase=str(value.get("build_phase") or ""),
    )


def _distinct_lldp_rows(rows: Iterable[Mapping[str, object | None]]) -> list[dict[str, object | None]]:
    """Collapse repeated identical observations without hiding real conflicts."""
    result: list[dict[str, object | None]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for row in rows:
        key = (
            str(row.get("_station_name") or ""),
            str(row.get("_switch_name") or ""),
            str(row.get("lldp_local_interface_normalized") or ""),
            _mac_key(row.get("lldp_neighbor_mac_normalized") or row.get("lldp_neighbor_mac")),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(dict(row))
    return result


def _row_from_lldp(ap_name: str, mac: str, lldp: Mapping[str, object], status: str, reason: str) -> ApLedgerRow:
    return ApLedgerRow(
        station_name=str(lldp.get("_station_name") or ""),
        ap_name=ap_name,
        ap_mac_display=mac or str(lldp.get("lldp_neighbor_mac") or ""),
        uplink_switch=str(lldp.get("_switch_name") or ""),
        uplink_port=str(lldp.get("lldp_local_interface") or ""),
        status=status,
        match_method="exact_mac",
        source_file=str(lldp.get("_source_file") or ""),
        source_sheet=str(lldp.get("_source_sheet") or ""),
        source_row=int(lldp.get("_source_row") or 0),
        reason=reason,
        build_phase=str(lldp.get("_build_phase") or ""),
        source_device=str(lldp.get("_switch_name") or ""),
        source_timestamp=str(lldp.get("_source_timestamp") or ""),
        lldp_neighbor_interface=str(lldp.get("lldp_neighbor_interface") or ""),
    )


def _row(station: str, ap_name: str, mac: str, switch: str, source_file: str, source_sheet: str, source_row: int, status: str, reason: str) -> ApLedgerRow:
    return ApLedgerRow(
        station_name=station, ap_name=ap_name, ap_mac_display=mac,
        uplink_switch=switch, status=status, source_file=source_file,
        source_sheet=source_sheet, source_row=source_row, reason=reason,
    )


def _mac_key(value: object) -> str:
    try:
        normalized = normalize_mac_key(str(value or ""))
        return str(normalized or "").casefold()
    except ValueError:
        return ""


__all__ = ["ApLedgerReport", "ApLedgerRow", "ApLedgerSource", "build_ap_ledger", "build_ap_ledger_from_sources"]
