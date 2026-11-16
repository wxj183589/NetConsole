from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping
import json

from netconsole.core.ap_identity.normalizers import normalize_mac_key
from netconsole.parsers.h3c.ac.fit_ap_lldp_neighbor_parser import parse_fit_ap_lldp_neighbors
from netconsole.parsers.h3c.ac.wlan_ap_address_parser import parse_wlan_ap_addresses
from netconsole.parsers.h3c.ac.wlan_ap_parser import parse_wlan_ap_list


LEDGER_HEADERS = (
    "线路名称", "系统类型", "网络域", "归属类型", "位置类型",
    "是否参与正线判断", "车站", "AP名称", "AP MAC", "上联交换机",
    "上联端口", "点位说明", "备注", "来源文件", "来源工作表", "来源行号",
    "建设阶段", "来源类型", "来源设备", "来源时间", "邻居侧 Port ID",
)

CONFIRMED_AP = "CONFIRMED_AP"
PENDING_DEVICE_TYPE = "PENDING_DEVICE_TYPE"
CONFIRMED_NON_AP = "CONFIRMED_NON_AP"
AC_ONLY_AP = "AC_ONLY_AP"
CONFLICT = "CONFLICT"


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
                    "classification": self.status,
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
    observations: tuple["ApLldpObservation", ...] = ()
    pending_device_type: tuple[ApLedgerRow, ...] = ()
    confirmed_non_ap: tuple[ApLedgerRow, ...] = ()
    ac_only: tuple[ApLedgerRow, ...] = ()

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
            self._write_rows(workbook, "pending_device_type", self.pending_device_type)
            self._write_rows(workbook, "confirmed_non_ap", self.confirmed_non_ap)
            self._write_rows(workbook, "ac_only", self.ac_only)
            self._write_observations(workbook)
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

    def _write_observations(self, workbook) -> None:
        sheet = workbook.create_sheet("lldp_observations")
        sheet.append((
            "车站", "LLDP名称", "MAC", "交换机", "交换机本地端口", "邻居侧Port ID",
            "分类", "分类依据", "AC精确MAC", "来源文件", "来源工作表", "来源行号",
            "来源设备", "来源时间", "建设阶段", "原始证据",
        ))
        for item in self.observations:
            sheet.append((
                item.station_name, item.lldp_neighbor_name, item.lldp_neighbor_mac,
                item.uplink_switch, item.uplink_port, item.lldp_neighbor_interface,
                item.classification, item.classification_reason,
                "是" if item.exact_ac_mac_match else "否", item.source_file,
                item.source_sheet, item.source_row, item.source_device,
                item.source_timestamp, item.build_phase, item.raw_payload_json,
            ))


@dataclass(frozen=True)
class ApLldpObservation:
    """An immutable raw LLDP observation plus its non-destructive classification."""

    station_name: str
    lldp_neighbor_name: str = ""
    lldp_neighbor_mac: str = ""
    uplink_switch: str = ""
    uplink_port: str = ""
    lldp_neighbor_interface: str = ""
    classification: str = PENDING_DEVICE_TYPE
    classification_reason: str = ""
    exact_ac_mac_match: bool = False
    source_file: str = ""
    source_sheet: str = ""
    source_row: int = 0
    source_device: str = ""
    source_timestamp: str = ""
    build_phase: str = ""
    raw_payload_json: str = "{}"


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
    device_type_evidence: str = ""
    device_type_by_mac: Mapping[str, str] = field(default_factory=dict)
    device_type_by_name: Mapping[str, str] = field(default_factory=dict)


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
        observations=report.observations,
        pending_device_type=report.pending_device_type,
        confirmed_non_ap=report.confirmed_non_ap,
        ac_only=report.ac_only,
    )


def build_ap_ledger_from_sources(
    *,
    ac_ap_all_output: str,
    ac_ap_address_output: str,
    sources: Iterable[ApLedgerSource | Mapping[str, object]],
) -> ApLedgerReport:
    """Build one Site-scoped ledger without discarding LLDP evidence.

    LLDP remains authoritative for station, switch and switch-local port. The
    AC tables are supplemental identity evidence: an exact AC MAC can confirm
    an AP, but absence from the AC address table never proves that a neighbor
    is not an AP. Every parsed LLDP row is retained in ``observations`` and is
    classified independently of the importable AP rows.
    """

    ap_rows = parse_wlan_ap_list(ac_ap_all_output)
    addresses = parse_wlan_ap_addresses(ac_ap_address_output)
    ap_by_name = {
        str(row.get("ap_name") or "").strip().casefold(): row
        for row in ap_rows
        if str(row.get("ap_name") or "").strip()
    }
    address_by_mac: dict[str, list[tuple[str, dict[str, object | None]]]] = defaultdict(list)
    for name, value in addresses.items():
        if (mac_key := _mac_key(value.get("ap_mac"))):
            address_by_mac[mac_key].append((name, value))
    address_mac_keys = set(address_by_mac)
    normalized_sources = [_source_value(value) for value in sources]
    lldp_rows: list[dict[str, object | None]] = []
    for source in normalized_sources:
        for row_number, row in enumerate(parse_fit_ap_lldp_neighbors(source.lldp_output), start=1):
            mac_key = _mac_key(row.get("lldp_neighbor_mac_normalized") or row.get("lldp_neighbor_mac"))
            classification, classification_reason = _classify_lldp_row(
                row,
                source,
                ap_by_name=ap_by_name,
                address_mac_keys=address_mac_keys,
            )
            lldp_rows.append({
                **row,
                "_station_name": source.station_name,
                "_switch_name": source.switch_name,
                "_source_file": source.source_file,
                "_source_sheet": source.source_sheet,
                "_source_row": row_number,
                "_source_timestamp": source.source_timestamp,
                "_build_phase": source.build_phase,
                "_classification": classification,
                "_classification_reason": classification_reason,
                "_exact_ac_mac": bool(mac_key and mac_key in address_mac_keys),
            })

    distinct_rows = _distinct_lldp_rows(lldp_rows)
    lldp_by_mac: dict[str, list[dict[str, object | None]]] = defaultdict(list)
    lldp_by_name: dict[str, list[dict[str, object | None]]] = defaultdict(list)
    for row in distinct_rows:
        mac = _mac_key(row.get("lldp_neighbor_mac_normalized") or row.get("lldp_neighbor_mac"))
        name = str(row.get("lldp_neighbor_name") or "").strip().casefold()
        if mac:
            lldp_by_mac[mac].append(row)
        if name and not _is_placeholder_identity(name) and not _is_generic_identity(name):
            lldp_by_name[name].append(row)

    conflict_reasons: dict[tuple[object, ...], set[str]] = defaultdict(set)
    conflict_mac_keys: set[str] = set()
    for mac_key, candidates in lldp_by_mac.items():
        identities = {
            (
                str(row.get("_station_name") or ""),
                str(row.get("_switch_name") or ""),
                str(row.get("lldp_local_interface_normalized") or ""),
            )
            for row in candidates
        }
        if len(identities) > 1:
            conflict_mac_keys.add(mac_key)
            for row in candidates:
                conflict_reasons[_row_key(row)].add(
                    "同一完整 MAC 在不同车站、交换机或本地端口出现，无法自动确认身份"
                )
        if len(address_by_mac.get(mac_key, [])) > 1:
            conflict_mac_keys.add(mac_key)
            for row in candidates:
                conflict_reasons[_row_key(row)].add("同一完整 MAC 在 AC 地址资料中关联多个名称")

    for name, candidates in lldp_by_name.items():
        macs = {_mac_key(row.get("lldp_neighbor_mac_normalized") or row.get("lldp_neighbor_mac")) for row in candidates}
        macs.discard("")
        if len(macs) > 1:
            conflict_mac_keys.update(macs)
            for row in candidates:
                conflict_reasons[_row_key(row)].add("同一 LLDP 名称关联多个 MAC，可能是地址变化或身份冲突")

    by_port: dict[tuple[str, str, str], list[dict[str, object | None]]] = defaultdict(list)
    for row in distinct_rows:
        key = (
            str(row.get("_station_name") or ""),
            str(row.get("_switch_name") or ""),
            str(row.get("lldp_local_interface_normalized") or ""),
        )
        if key[2] and _mac_key(row.get("lldp_neighbor_mac_normalized") or row.get("lldp_neighbor_mac")):
            by_port[key].append(row)
    for key, candidates in by_port.items():
        macs = {_mac_key(row.get("lldp_neighbor_mac_normalized") or row.get("lldp_neighbor_mac")) for row in candidates}
        if len(macs) > 1:
            for row in candidates:
                conflict_reasons[_row_key(row)].add("同一交换机本地端口观察到多个 MAC，无法自动选择")

    for row in lldp_rows:
        reasons = conflict_reasons.get(_row_key(row))
        if reasons:
            row["_classification"] = CONFLICT
            row["_classification_reason"] = "；".join(sorted(reasons))
    for row in distinct_rows:
        reasons = conflict_reasons.get(_row_key(row))
        if reasons:
            row["_classification"] = CONFLICT
            row["_classification_reason"] = "；".join(sorted(reasons))

    matched: list[ApLedgerRow] = []
    pending_device_type: list[ApLedgerRow] = []
    confirmed_non_ap: list[ApLedgerRow] = []
    conflicts: list[ApLedgerRow] = []
    for lldp in distinct_rows:
        classification = str(lldp.get("_classification") or PENDING_DEVICE_TYPE)
        if classification == CONFLICT:
            conflicts.append(_row_from_lldp(
                str(lldp.get("lldp_neighbor_name") or ""),
                str(lldp.get("lldp_neighbor_mac") or ""),
                lldp,
                CONFLICT,
                str(lldp.get("_classification_reason") or "身份冲突，未自动改写"),
            ))
            continue
        if classification == PENDING_DEVICE_TYPE:
            pending_device_type.append(_row_from_lldp(
                str(lldp.get("lldp_neighbor_name") or ""),
                str(lldp.get("lldp_neighbor_mac") or ""),
                lldp,
                PENDING_DEVICE_TYPE,
                str(lldp.get("_classification_reason") or "未获得足够设备类型证据，保留待确认"),
            ))
            continue
        if classification == CONFIRMED_NON_AP:
            confirmed_non_ap.append(_row_from_lldp(
                str(lldp.get("lldp_neighbor_name") or ""),
                str(lldp.get("lldp_neighbor_mac") or ""),
                lldp,
                CONFIRMED_NON_AP,
                str(lldp.get("_classification_reason") or "存在明确非 AP 设备类型证据"),
            ))
            continue

        lldp_mac = str(lldp.get("lldp_neighbor_mac") or "")
        mac_key = _mac_key(lldp.get("lldp_neighbor_mac_normalized") or lldp_mac)
        name = str(lldp.get("lldp_neighbor_name") or "").strip()
        ac_matches = address_by_mac.get(mac_key, []) if mac_key else []
        ac_name = ac_matches[0][0] if len(ac_matches) == 1 else ""
        ap_name = name if name.casefold() in ap_by_name else ac_name or name
        raw_mac = ac_matches[0][1].get("ap_mac") if len(ac_matches) == 1 else lldp_mac
        name_reason = (
            f"MAC 精确匹配但名称字段不同：AC={ac_name}，LLDP={name}"
            if ac_name and name and ac_name.casefold() != name.casefold()
            else ""
        )
        missing_switch_reason = (
            "LLDP 回显缺少交换机提示符，交换机身份待现场确认"
            if not str(lldp.get("_switch_name") or "").strip()
            else ""
        )
        matched.append(ApLedgerRow(
            station_name=str(lldp.get("_station_name") or ""),
            ap_name=ap_name,
            ap_mac_display=str(raw_mac or lldp_mac),
            uplink_switch=str(lldp.get("_switch_name") or ""),
            uplink_port=str(lldp.get("lldp_local_interface") or ""),
            status=CONFIRMED_AP,
            match_method="exact_mac" if lldp.get("_exact_ac_mac") else "lldp_device_type",
            source_file=str(lldp.get("_source_file") or ""),
            source_sheet=str(lldp.get("_source_sheet") or ""),
            source_row=int(lldp.get("_source_row") or 0),
            build_phase=str(lldp.get("_build_phase") or ""),
            source_device=str(lldp.get("_switch_name") or ""),
            source_timestamp=str(lldp.get("_source_timestamp") or ""),
            lldp_neighbor_interface=str(lldp.get("lldp_neighbor_interface") or ""),
            reason="；".join(reason for reason in (name_reason, missing_switch_reason) if reason),
        ))

    lldp_mac_keys = {
        _mac_key(row.get("lldp_neighbor_mac_normalized") or row.get("lldp_neighbor_mac"))
        for row in distinct_rows
    }
    lldp_mac_keys.discard("")
    ac_only: list[ApLedgerRow] = []
    for name, address in addresses.items():
        mac = str(address.get("ap_mac") or "").strip()
        mac_key = _mac_key(mac)
        if mac_key and mac_key not in lldp_mac_keys:
            ac_only.append(_row(
                "", name, mac, "", "", "", 0, AC_ONLY_AP,
                "AC 地址资料存在，但当前 LLDP 快照未观察到；不推断交换机、端口或在线状态",
            ))

    matched_ac_mac_keys = {_mac_key(row.ap_mac_display) for row in matched if _mac_key(row.ap_mac_display)}
    unmatched: list[ApLedgerRow] = []
    for index, ap in enumerate(ap_rows, start=1):
        ap_name = str(ap.get("ap_name") or "").strip()
        address = _lookup_casefold(addresses, ap_name)
        raw_mac = str(address.get("ap_mac") or "").strip()
        mac_key = _mac_key(raw_mac)
        if mac_key in matched_ac_mac_keys:
            continue
        if mac_key and mac_key in conflict_mac_keys:
            reason = "AC MAC 存在冲突 LLDP 观察，未自动改写身份"
        elif mac_key and mac_key in lldp_mac_keys:
            reason = "LLDP 已观察到该 MAC，但设备类型或身份证据未确认"
        else:
            reason = "没有精确 AP MAC 的 LLDP 观察"
        unmatched.append(_row("", ap_name, raw_mac, "", "", "", index, "UNMATCHED", reason))

    observations = tuple(_observation_from_lldp(row) for row in lldp_rows)
    stats = {
        "ac_ap_rows": len(ap_rows),
        "ac_address_rows": len(addresses),
        "matched_rows": len(matched),
        "confirmed_ap_rows": len(matched),
        "unmatched_rows": len(unmatched),
        "ac_only_rows": len(ac_only),
        "conflict_rows": len(conflicts),
        "lldp_rows": len(lldp_rows),
        "lldp_ap_rows": sum(row.status == CONFIRMED_AP for row in matched),
        "pending_device_type_rows": sum(item.classification == PENDING_DEVICE_TYPE for item in observations),
        "unknown_lldp_rows": sum(item.classification == PENDING_DEVICE_TYPE for item in observations),
        "confirmed_non_ap_rows": sum(item.classification == CONFIRMED_NON_AP for item in observations),
        "non_ap_lldp_rows": sum(item.classification == CONFIRMED_NON_AP for item in observations),
        "conflict_lldp_rows": sum(item.classification == CONFLICT for item in observations),
        "station_count": len({str(row.get("_station_name") or "") for row in lldp_rows if row.get("_station_name")}),
        "pending_switch_rows": sum(
            item.classification == CONFIRMED_AP and not item.uplink_switch.strip()
            for item in observations
        ),
    }
    return ApLedgerReport(
        tuple(matched), tuple(unmatched), tuple(conflicts), stats,
        observations=observations,
        pending_device_type=tuple(pending_device_type),
        confirmed_non_ap=tuple(confirmed_non_ap),
        ac_only=tuple(ac_only),
    )


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
        device_type_evidence=str(value.get("device_type_evidence") or ""),
        device_type_by_mac={
            str(key): str(item)
            for key, item in (value.get("device_type_by_mac") or {}).items()
        } if isinstance(value.get("device_type_by_mac"), Mapping) else {},
        device_type_by_name={
            str(key): str(item)
            for key, item in (value.get("device_type_by_name") or {}).items()
        } if isinstance(value.get("device_type_by_name"), Mapping) else {},
    )


def _classify_lldp_row(
    row: Mapping[str, object | None],
    source: ApLedgerSource,
    *,
    ap_by_name: Mapping[str, Mapping[str, object | None]],
    address_mac_keys: set[str],
) -> tuple[str, str]:
    """Classify using explicit evidence, never by OUI or a guessed name."""

    mac_key = _mac_key(row.get("lldp_neighbor_mac_normalized") or row.get("lldp_neighbor_mac"))
    name = str(row.get("lldp_neighbor_name") or "").strip()
    if mac_key and mac_key in address_mac_keys:
        return CONFIRMED_AP, "AC 地址表精确完整 MAC 匹配"

    evidence = ""
    for key, values in (
        (mac_key, source.device_type_by_mac),
        (name.casefold(), source.device_type_by_name),
    ):
        if key and key in values:
            evidence = str(values[key] or "")
            break
        if key:
            matched_value = next(
                (item for raw_key, item in values.items() if str(raw_key).casefold() == key.casefold()),
                None,
            )
            if matched_value is not None:
                evidence = str(matched_value or "")
                break
    if not evidence:
        evidence = source.device_type_evidence
    explicit = _device_type_classification(evidence)
    if explicit == CONFIRMED_AP:
        return CONFIRMED_AP, f"明确设备类型证据：{evidence}"
    if explicit == CONFIRMED_NON_AP:
        return CONFIRMED_NON_AP, f"明确非 AP 设备类型证据：{evidence}"

    # An exact AC AP name is only useful when the AC AP row also carries a
    # meaningful model/type. A System Name alone is deliberately insufficient.
    ac_row = ap_by_name.get(name.casefold())
    model = str(ac_row.get("model") or "").strip() if ac_row else ""
    if ac_row and model and not _is_placeholder_identity(model):
        return CONFIRMED_AP, f"AC AP 清单精确名称及型号证据：{model}"
    return PENDING_DEVICE_TYPE, "LLDP 已观察到，但没有足够设备类型证据"


def _device_type_classification(value: object) -> str | None:
    token = str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")
    if token in {"ap", "access_point", "fit_ap", "wireless_ap", "wlan_ap"}:
        return CONFIRMED_AP
    if token in {
        "non_ap", "switch", "router", "gateway", "firewall", "server",
        "host", "computer", "phone", "uplink", "network_device",
    }:
        return CONFIRMED_NON_AP
    return None


def _is_placeholder_identity(value: object) -> bool:
    return str(value or "").strip().casefold() in {"", "-", "--", "na", "n/a", "unknown", "none", "null"}


def _is_generic_identity(value: object) -> bool:
    return str(value or "").strip().casefold() in {
        "zxr10", "h3c", "comware", "switch", "router", "gateway", "uplink",
        "network_device", "network-device", "bridge", "nearest bridge neighbor",
    }


def _lookup_casefold(values: Mapping[str, Mapping[str, object | None]], key: str) -> Mapping[str, object | None]:
    if key in values:
        return values[key]
    folded = key.casefold()
    return next((value for name, value in values.items() if str(name).casefold() == folded), {})


def _row_key(row: Mapping[str, object | None]) -> tuple[object, ...]:
    return (
        str(row.get("_station_name") or ""),
        str(row.get("_switch_name") or ""),
        str(row.get("lldp_local_interface_normalized") or ""),
        _mac_key(row.get("lldp_neighbor_mac_normalized") or row.get("lldp_neighbor_mac")),
        str(row.get("_source_file") or ""),
        int(row.get("_source_row") or 0),
    )


def _observation_from_lldp(row: Mapping[str, object | None]) -> ApLldpObservation:
    payload = {
        key: value
        for key, value in row.items()
        if not key.startswith("_")
    }
    return ApLldpObservation(
        station_name=str(row.get("_station_name") or ""),
        lldp_neighbor_name=str(row.get("lldp_neighbor_name") or ""),
        lldp_neighbor_mac=str(row.get("lldp_neighbor_mac") or ""),
        uplink_switch=str(row.get("_switch_name") or ""),
        uplink_port=str(row.get("lldp_local_interface") or ""),
        lldp_neighbor_interface=str(row.get("lldp_neighbor_interface") or ""),
        classification=str(row.get("_classification") or PENDING_DEVICE_TYPE),
        classification_reason=str(row.get("_classification_reason") or ""),
        exact_ac_mac_match=bool(row.get("_exact_ac_mac")),
        source_file=str(row.get("_source_file") or ""),
        source_sheet=str(row.get("_source_sheet") or ""),
        source_row=int(row.get("_source_row") or 0),
        source_device=str(row.get("_switch_name") or ""),
        source_timestamp=str(row.get("_source_timestamp") or ""),
        build_phase=str(row.get("_build_phase") or ""),
        raw_payload_json=json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str),
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


__all__ = [
    "AC_ONLY_AP",
    "CONFIRMED_AP",
    "CONFIRMED_NON_AP",
    "CONFLICT",
    "PENDING_DEVICE_TYPE",
    "ApLedgerReport",
    "ApLedgerRow",
    "ApLedgerSource",
    "ApLldpObservation",
    "build_ap_ledger",
    "build_ap_ledger_from_sources",
]
