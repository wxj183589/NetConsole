from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from netconsole.core.ap_identity.normalizers import normalize_mac_key
from netconsole.parsers.h3c.ac.fit_ap_lldp_neighbor_parser import parse_fit_ap_lldp_neighbors
from netconsole.parsers.h3c.ac.wlan_ap_address_parser import parse_wlan_ap_addresses
from netconsole.parsers.h3c.ac.wlan_ap_parser import parse_wlan_ap_list


LEDGER_HEADERS = (
    "线路名称", "系统类型", "网络域", "归属类型", "位置类型",
    "是否参与正线判断", "车站", "AP名称", "AP MAC", "上联交换机",
    "上联端口", "点位说明", "备注", "来源文件", "来源工作表", "来源行号",
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

    def import_values(self) -> dict[str, object]:
        return {
            "station_name": self.station_name,
            "ap_name": self.ap_name,
            "ap_mac_display": self.ap_mac_display,
            "uplink_switch": self.uplink_switch,
            "uplink_port": self.uplink_port,
            "belong_type": "station",
            "location_class": "MAINLINE",
            "participates_in_mainline": 1,
            "source_file": self.source_file,
            "source_sheet": self.source_sheet,
            "source_row": self.source_row,
            "remark": self.reason,
        }


@dataclass(frozen=True)
class ApLedgerReport:
    rows: tuple[ApLedgerRow, ...] = ()
    unmatched: tuple[ApLedgerRow, ...] = ()
    conflicts: tuple[ApLedgerRow, ...] = ()
    stats: dict[str, int] = field(default_factory=dict)

    def write_xlsx(self, path: Path) -> Path:
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
            ])
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
        sheet.append(("车站", "AP名称", "AP MAC", "上联交换机", "上联端口", "状态", "匹配方式", "原因", "来源文件", "来源行号"))
        for row in rows:
            sheet.append((row.station_name, row.ap_name, row.ap_mac_display, row.uplink_switch, row.uplink_port, row.status, row.match_method, row.reason, row.source_file, row.source_row))


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

    ap_rows = parse_wlan_ap_list(ac_ap_all_output)
    addresses = parse_wlan_ap_addresses(ac_ap_address_output)
    lldp_rows = [row for output in switch_lldp_outputs for row in parse_fit_ap_lldp_neighbors(output)]
    lldp_by_mac: dict[str, list[dict[str, object | None]]] = defaultdict(list)
    lldp_by_name: dict[str, list[dict[str, object | None]]] = defaultdict(list)
    for row in lldp_rows:
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
        candidates = lldp_by_mac.get(mac_key, []) if mac_key else lldp_by_name.get(ap_name.casefold(), [])
        exact_name_candidates = lldp_by_name.get(ap_name.casefold(), [])
        if len(candidates) > 1:
            row = _row(station_name, ap_name, raw_mac, switch_name, source_file, source_sheet, index, "CONFLICT", "exact MAC/name matched multiple switch ports")
            conflicts.append(row)
            continue
        if not candidates and len(exact_name_candidates) == 1:
            candidates = exact_name_candidates
        if not candidates:
            unmatched.append(_row(station_name, ap_name, raw_mac, switch_name, source_file, source_sheet, index, "UNMATCHED", "no exact AP MAC or AP name LLDP match"))
            continue
        lldp = candidates[0]
        lldp_mac = str(lldp.get("lldp_neighbor_mac") or "")
        if mac_key and _mac_key(lldp_mac) and mac_key != _mac_key(lldp_mac):
            conflicts.append(_row(station_name, ap_name, raw_mac, switch_name, source_file, source_sheet, index, "CONFLICT", "AP MAC and LLDP MAC disagree"))
            continue
        matched.append(ApLedgerRow(
            station_name=station_name, ap_name=ap_name,
            ap_mac_display=raw_mac or lldp_mac,
            uplink_switch=switch_name,
            uplink_port=str(lldp.get("lldp_local_interface") or ""),
            match_method="exact_mac" if mac_key else "exact_ap_name",
            source_file=source_file, source_sheet=source_sheet, source_row=index,
        ))
    stats = {
        "ac_ap_rows": len(ap_rows),
        "matched_rows": len(matched),
        "unmatched_rows": len(unmatched),
        "conflict_rows": len(conflicts),
        "lldp_rows": len(lldp_rows),
    }
    return ApLedgerReport(tuple(matched), tuple(unmatched), tuple(conflicts), stats)


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


__all__ = ["ApLedgerReport", "ApLedgerRow", "build_ap_ledger"]
