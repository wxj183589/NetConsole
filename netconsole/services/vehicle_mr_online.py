from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Protocol

from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.models.online_mr_models import OnlineMrConnectionConfig
from netconsole.repositories.device_group_repository import DeviceGroupRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.online_mr_collector import NetmikoShellConnection


VEHICLE_INIT_COMMAND = "screen-length disable"
VEHICLE_SAMPLE_COMMANDS = ("display clock", "display wlan mesh-link ap")
TRAIN_STATUS_ONLINE = "在线"
TRAIN_STATUS_PARTIAL = "单端在线"
TRAIN_STATUS_OFFLINE = "离线"
TRAIN_STATUS_ABNORMAL_SINGLE = "异常单端"
TRAIN_STATUS_UNEXPECTED_END = "非预期端在线"
TRAIN_STATUS_DUAL_ONLINE = "双端在线"
UNKNOWN_STATION = "未知车站"
ONLINE_POLICY_AUTO = "auto"
ONLINE_POLICY_SINGLE_TAIL = "single_tail"
ONLINE_POLICY_DUAL_ACTIVE = "dual_active"
ONLINE_POLICY_SINGLE_TC1 = "single_tc1"
ONLINE_POLICY_SINGLE_TC2 = "single_tc2"
ONLINE_POLICIES = {
    ONLINE_POLICY_AUTO,
    ONLINE_POLICY_SINGLE_TAIL,
    ONLINE_POLICY_DUAL_ACTIVE,
    ONLINE_POLICY_SINGLE_TC1,
    ONLINE_POLICY_SINGLE_TC2,
}
ONLINE_POLICY_LABELS = {
    ONLINE_POLICY_AUTO: "自动/未知",
    ONLINE_POLICY_SINGLE_TAIL: "单端在线-尾端在线",
    ONLINE_POLICY_DUAL_ACTIVE: "双端在线",
    ONLINE_POLICY_SINGLE_TC1: "单端在线-TC1固定在线",
    ONLINE_POLICY_SINGLE_TC2: "单端在线-TC2固定在线",
}
ONLINE_POLICY_VALUES_BY_LABEL = {label: value for value, label in ONLINE_POLICY_LABELS.items()}


@dataclass(frozen=True)
class VehicleMrMeshLink:
    local_ap_name: str
    peer_name: str
    peer_name_canonical: str = ""
    peer_mac: str = ""
    local_mac: str = ""
    status: str = ""
    rssi: int | None = None
    rx_packets: int | None = None
    tx_packets: int | None = None


@dataclass(frozen=True)
class VehicleMrMeshParseResult:
    ac_time: str = ""
    links: list[VehicleMrMeshLink] = field(default_factory=list)
    parse_status: str = "OK"
    error_message: str = ""


@dataclass(frozen=True)
class TrainIdentity:
    peer_name: str
    train_id: str
    train_no: str
    car_end: str
    car_end_label: str
    online_policy: str = ONLINE_POLICY_AUTO


@dataclass(frozen=True)
class MatchedAp:
    ap_name: str
    station: str
    match_method: str = "unmatched"
    match_score: int = 0
    ap_mac: str = ""
    station_source: str = ""


@dataclass(frozen=True)
class VehicleMrEndState:
    seen: bool = False
    station: str = ""
    ap_name: str = ""
    rssi: int | None = None
    last_seen_at: str = ""
    match_method: str = "unmatched"
    match_score: int = 0

    def display(self) -> str:
        if not self.seen:
            return "离线"
        station = self.station or UNKNOWN_STATION
        ap_name = self.ap_name or "未匹配AP"
        rssi = "-" if self.rssi is None else str(self.rssi)
        return f"{station} / {ap_name} / {rssi}"


@dataclass
class VehicleMrTrainState:
    train_id: str
    train_no: str
    is_registered: bool
    status: str = TRAIN_STATUS_OFFLINE
    current_station: str = "-"
    last_ac_time: str = ""
    last_seen_at: str = ""
    tc1: VehicleMrEndState = field(default_factory=VehicleMrEndState)
    tc2: VehicleMrEndState = field(default_factory=VehicleMrEndState)
    online_policy: str = ONLINE_POLICY_AUTO
    expected_end: str = ""
    direction: str = "未知"
    status_reason: str = ""

    @property
    def display_name(self) -> str:
        return f"{self.train_no}车" if self.train_no else self.train_id


@dataclass(frozen=True)
class VehicleMrOnlineSnapshot:
    session_id: str
    status: str
    ac_time: str = ""
    trains: list[VehicleMrTrainState] = field(default_factory=list)
    error_message: str = ""

    def stats(self) -> dict[str, int]:
        return {
            "online": sum(1 for train in self.trains if train.status in {TRAIN_STATUS_ONLINE, TRAIN_STATUS_DUAL_ONLINE}),
            "abnormal": sum(1 for train in self.trains if train.status in {TRAIN_STATUS_ABNORMAL_SINGLE, TRAIN_STATUS_UNEXPECTED_END, TRAIN_STATUS_PARTIAL}),
            "offline": sum(1 for train in self.trains if train.status == TRAIN_STATUS_OFFLINE),
            "unregistered": sum(1 for train in self.trains if not train.is_registered),
        }


@dataclass
class VehicleMrTrainMapping:
    id: int | None = None
    enabled: bool = True
    train_display_name: str = ""
    train_id: str = ""
    train_no: str = ""
    tc1_peer_name: str = ""
    tc2_peer_name: str = ""
    online_policy: str = ONLINE_POLICY_AUTO
    remark: str = ""
    created_at: str = ""
    updated_at: str = ""

    @property
    def display_name(self) -> str:
        return self.train_display_name or (f"{self.train_no}车" if self.train_no else self.train_id)


class VehicleMrMeshLinkParser:
    def parse(self, raw_text: str) -> VehicleMrMeshParseResult:
        raise NotImplementedError


class H3CComwareV9VehicleMrMeshLinkParser(VehicleMrMeshLinkParser):
    _clock_re = re.compile(r"^\s*(?P<time>\d{1,2}:\d{2}:\d{2})\b")
    _clock_date_re = re.compile(r"^\s*(?P<time>\d{1,2}:\d{2}:\d{2})\b.*?\b(?P<date>\d{1,2}/\d{1,2}/\d{4})\b")
    _ap_re = re.compile(r"^\s*AP\s+name\s*:\s*(?P<name>.+?)\s*$", re.IGNORECASE)
    _peer_re = re.compile(
        r"^\s*(?P<peer>.+?)\s+"
        r"(?P<peer_mac>[0-9a-fA-F]{4}[-:.]?[0-9a-fA-F]{4}[-:.]?[0-9a-fA-F]{4})\s+"
        r"(?P<local_mac>[0-9a-fA-F]{4}[-:.]?[0-9a-fA-F]{4}[-:.]?[0-9a-fA-F]{4})\s+"
        r"(?P<status>\S+)\s+"
        r"(?P<rssi>-?\d+|-)\s+"
        r"(?P<rx>\d+)\s*/\s*(?P<tx>\d+)\s*$"
    )

    def parse(self, raw_text: str) -> VehicleMrMeshParseResult:
        ac_time = ""
        links: list[VehicleMrMeshLink] = []
        current_ap = ""
        try:
            for raw_line in raw_text.splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                clock_match = self._clock_date_re.match(line) or self._clock_re.match(line)
                if clock_match and not ac_time:
                    ac_time = parse_ac_clock_line(line)
                    continue
                ap_match = self._ap_re.match(line)
                if ap_match:
                    current_ap = ap_match.group("name").strip()
                    continue
                if "Peer Name" in line and "Peer Mac" in line:
                    continue
                if line.startswith("<") or line.lower().startswith("display ") or line.lower().startswith("time zone"):
                    continue
                match = self._peer_re.match(line)
                if not match or not current_ap:
                    continue
                rssi_text = match.group("rssi")
                links.append(
                    VehicleMrMeshLink(
                        local_ap_name=current_ap,
                        peer_name=match.group("peer").strip(),
                        peer_name_canonical=canonical_peer_name(match.group("peer")),
                        peer_mac=normalize_mac(match.group("peer_mac")),
                        local_mac=normalize_mac(match.group("local_mac")),
                        status=match.group("status").strip(),
                        rssi=int(rssi_text) if rssi_text.lstrip("-").isdigit() else None,
                        rx_packets=int(match.group("rx")),
                        tx_packets=int(match.group("tx")),
                    )
                )
        except Exception as exc:
            return VehicleMrMeshParseResult(ac_time=ac_time, links=links, parse_status="FAILED", error_message=str(exc))
        if not ac_time:
            ac_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if not links:
                return VehicleMrMeshParseResult(ac_time=ac_time, links=links, parse_status="FAILED", error_message="解析失败/格式未适配：未找到 AC 时间")
        return VehicleMrMeshParseResult(ac_time=ac_time, links=links, parse_status="OK")


def parse_ac_clock_line(line: str, fallback: datetime | None = None) -> str:
    fallback = fallback or datetime.now()
    date_match = re.search(r"(?P<date>\d{1,2}/\d{1,2}/\d{4})", str(line or ""))
    time_match = re.search(r"(?P<time>\d{1,2}:\d{2}:\d{2})", str(line or ""))
    if not time_match:
        return fallback.strftime("%Y-%m-%d %H:%M:%S")
    time_text = time_match.group("time")
    if date_match:
        parsed = datetime.strptime(f"{date_match.group('date')} {time_text}", "%m/%d/%Y %H:%M:%S")
        return parsed.strftime("%Y-%m-%d %H:%M:%S")
    return f"{fallback:%Y-%m-%d} {time_text}"


_MR_NAME_RE = re.compile(r"^(?P<train_id>.+?-LC(?P<train_no>\d+))-(?:MR|AP)-(?P<end>CT|CW)$", re.IGNORECASE)
_CN_MR_NAME_RE = re.compile(r"^列车(?P<train_no>\d+)-(?:MR|AP)-(?P<end>CT|CW)$", re.IGNORECASE)
_STATION_END_RE = re.compile(r"(?P<train_no>\d+)车.*(?P<end>车头|车尾|CT|CW)", re.IGNORECASE)
_TRAIN_NO_RE = re.compile(r"(?:LC|列车)?0*(?P<train_no>\d{1,3})车?", re.IGNORECASE)
EMPTY_STATION_VALUES = {"", "-", "—", "未知", "unknown", "none", "null"}
ONLINE_LINK_STATUSES = {"forwarding", "active", "up"}


def canonical_peer_name(value: object) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    text = re.sub(r"(?i)\b(AP|MR)\s*-\s*(CT|CW)\b", lambda match: f"{match.group(1).upper()}-{match.group(2).upper()}", text)
    return text


def normalize_train_no(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for pattern in (r"LC0*(?P<train_no>\d{1,3})", r"列车0*(?P<train_no>\d{1,3})", r"0*(?P<train_no>\d{1,3})车"):
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group("train_no").zfill(2)
    match = _TRAIN_NO_RE.search(text)
    if match and not re.search(r"[A-Za-z]\d+", text.replace(match.group(0), ""), re.IGNORECASE):
        return match.group("train_no").zfill(2)
    digits = re.sub(r"\D+", "", text)
    return digits.zfill(2) if digits else ""


def normalize_online_policy(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ONLINE_POLICY_AUTO
    if text in ONLINE_POLICIES:
        return text
    if text in ONLINE_POLICY_VALUES_BY_LABEL:
        return ONLINE_POLICY_VALUES_BY_LABEL[text]
    lowered = text.casefold()
    for policy in ONLINE_POLICIES:
        if lowered == policy.casefold():
            return policy
    aliases = {
        "双活": ONLINE_POLICY_DUAL_ACTIVE,
        "双端": ONLINE_POLICY_DUAL_ACTIVE,
        "双端在线": ONLINE_POLICY_DUAL_ACTIVE,
        "单活": ONLINE_POLICY_SINGLE_TAIL,
        "尾端在线": ONLINE_POLICY_SINGLE_TAIL,
        "单端尾端在线": ONLINE_POLICY_SINGLE_TAIL,
        "tc1": ONLINE_POLICY_SINGLE_TC1,
        "tc1固定": ONLINE_POLICY_SINGLE_TC1,
        "tc1固定在线": ONLINE_POLICY_SINGLE_TC1,
        "tc2": ONLINE_POLICY_SINGLE_TC2,
        "tc2固定": ONLINE_POLICY_SINGLE_TC2,
        "tc2固定在线": ONLINE_POLICY_SINGLE_TC2,
        "自动": ONLINE_POLICY_AUTO,
        "未知": ONLINE_POLICY_AUTO,
        "自动/未知": ONLINE_POLICY_AUTO,
    }
    compact = re.sub(r"[\s_\-/]+", "", text.casefold())
    return aliases.get(compact, ONLINE_POLICY_AUTO)


def online_policy_label(policy: object) -> str:
    return ONLINE_POLICY_LABELS.get(normalize_online_policy(policy), ONLINE_POLICY_LABELS[ONLINE_POLICY_AUTO])


def build_canonical_train_key(value: object) -> str:
    train_no = normalize_train_no(value)
    return f"train:{train_no}" if train_no else ""


def normalize_mac(mac: object) -> str:
    text = re.sub(r"[^0-9a-fA-F]", "", str(mac or "")).casefold()
    return text if len(text) == 12 else ""


def is_empty_station(value: object) -> bool:
    return str(value or "").strip().casefold() in EMPTY_STATION_VALUES


def is_same_or_h3c_radio_mac(mac_a: object, mac_b: object) -> bool:
    return h3c_radio_mac_match_method(mac_a, mac_b) != ""


def h3c_radio_mac_match_method(mac_a: object, mac_b: object) -> str:
    left = normalize_mac(mac_a)
    right = normalize_mac(mac_b)
    if not left or not right:
        return ""
    if left == right:
        return "exact_mac"
    if left[:10] == right[:10]:
        try:
            if abs(int(left[10], 16) - int(right[10], 16)) <= 1:
                return "h3c_radio_mac"
        except ValueError:
            pass
    if left[:11] == right[:11]:
        return "h3c_radio_bssid"
    return ""


def parse_train_identity(peer_name: str) -> TrainIdentity | None:
    text = canonical_peer_name(peer_name)
    match = _MR_NAME_RE.match(text)
    if match:
        train_id = match.group("train_id")
        train_no = normalize_train_no(match.group("train_no"))
        end = match.group("end").upper()
    else:
        match = _CN_MR_NAME_RE.match(text)
        if not match:
            return None
        train_no = normalize_train_no(match.group("train_no"))
        train_id = f"列车{train_no}"
        end = match.group("end").upper()
    return TrainIdentity(
        peer_name=str(peer_name or "").strip(),
        train_id=train_id,
        train_no=train_no,
        car_end=end,
        car_end_label="TC1" if end == "CT" else "TC2",
    )


def parse_train_identity_from_device(device: Device) -> TrainIdentity | None:
    identity = parse_train_identity(device.name)
    if identity is not None:
        return identity
    station_text = str(device.station or "").strip()
    match = _STATION_END_RE.search(station_text)
    if not match:
        return None
    end_text = match.group("end").upper()
    end = "CT" if end_text in {"车头", "CT"} else "CW"
    train_no = normalize_train_no(match.group("train_no"))
    return TrainIdentity(
        peer_name=device.name,
        train_id=f"列车{train_no}",
        train_no=train_no,
        car_end=end,
        car_end_label="TC1" if end == "CT" else "TC2",
    )


def train_sort_key(train: VehicleMrTrainState | tuple[str, str]) -> tuple[str, int, str]:
    train_id, train_no = (train.train_id, train.train_no) if isinstance(train, VehicleMrTrainState) else train
    prefix = train_id.rsplit("-LC", 1)[0] if "-LC" in train_id else train_id
    try:
        number = int(train_no)
    except (TypeError, ValueError):
        number = 10**9
    return prefix, number, train_id


def build_registered_trains(devices: list[Device], group_names: dict[int, str] | None = None) -> dict[str, VehicleMrTrainState]:
    result: dict[str, VehicleMrTrainState] = {}
    group_names = group_names or {}
    has_vehicle_mr_group = any("车载-MR" in name for name in group_names.values())
    for device in devices:
        group_name = group_names.get(int(device.group_id or 0), "")
        if has_vehicle_mr_group:
            if "车载-MR" not in group_name:
                continue
        elif group_name != "车载":
            continue
        identity = parse_train_identity_from_device(device)
        if identity is None:
            continue
        type_text = str(device.device_type or "").upper()
        candidate = "AP" in type_text or "MR" in type_text or bool(type_text)
        if not candidate:
            continue
        result.setdefault(identity.train_id, VehicleMrTrainState(identity.train_id, identity.train_no, True))
    return result


def load_vehicle_mr_mapping_trains(repository: DeviceRepository) -> dict[str, VehicleMrTrainState]:
    table_names = (
        "vehicle_mr_mapping",
        "vehicle_mr_mappings",
        "vehicle_mr_train_mapping",
        "vehicle_mr_train_mappings",
    )
    result: dict[str, VehicleMrTrainState] = {}
    with repository.database.connect() as conn:
        existing = {
            str(row["name"])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if row["name"]
        }
        for table in table_names:
            if table not in existing:
                continue
            columns = {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}
            try:
                rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            except sqlite3.Error:
                continue
            for row in rows:
                row_data = dict(row)
                identity = _identity_from_mapping_row(row_data, columns)
                if identity is not None:
                    result[identity.train_id] = VehicleMrTrainState(identity.train_id, identity.train_no, True, online_policy=identity.online_policy)
    return result


def build_mapping_trains(mappings: list[VehicleMrTrainMapping]) -> dict[str, VehicleMrTrainState]:
    result: dict[str, VehicleMrTrainState] = {}
    for mapping in mappings:
        if not mapping.enabled:
            continue
        train_no = mapping.train_no or normalize_train_no(mapping.display_name)
        if not train_no:
            continue
        train_id = mapping.train_id or f"列车{train_no}"
        result[train_id] = VehicleMrTrainState(train_id, train_no, True, online_policy=normalize_online_policy(mapping.online_policy))
    return result


def build_mapping_lookup(mappings: list[VehicleMrTrainMapping]) -> dict[str, TrainIdentity]:
    result: dict[str, TrainIdentity] = {}
    for mapping in mappings:
        if not mapping.enabled:
            continue
        train_no = mapping.train_no or normalize_train_no(mapping.display_name)
        train_id = mapping.train_id or f"列车{train_no}"
        for peer, end in ((mapping.tc1_peer_name, "CT"), (mapping.tc2_peer_name, "CW")):
            peer = peer.strip()
            if peer:
                result[peer] = TrainIdentity(peer, train_id, train_no, end, "TC1" if end == "CT" else "TC2", normalize_online_policy(mapping.online_policy))
    return result


def load_vehicle_mr_mapping_lookup(repository: DeviceRepository) -> dict[str, TrainIdentity]:
    return {}


def _identity_from_mapping_row(row: dict[str, object], columns: set[str]) -> TrainIdentity | None:
    for field in ("peer_name", "mr_name", "device_name", "name"):
        if field in columns:
            identity = parse_train_identity(str(row.get(field) or ""))
            if identity is not None:
                return identity
    train_no = _first_text(row, columns, ("train_no", "train_number", "车号"))
    train_id = _first_text(row, columns, ("train_id", "列车ID", "列车"))
    end_text = _first_text(row, columns, ("car_end", "end", "端别"))
    if not train_no and train_id:
        match = re.search(r"(\d+)", train_id)
        train_no = match.group(1) if match else ""
    if not train_no:
        return None
    normalized_no = normalize_train_no(train_no)
    end = "CT" if str(end_text).upper() in {"CT", "TC1", "车头"} else "CW"
    return TrainIdentity(
        peer_name=str(row),
        train_id=train_id or f"列车{normalized_no}",
        train_no=normalized_no,
        car_end=end,
        car_end_label="TC1" if end == "CT" else "TC2",
    )


def _first_text(row: dict[str, object], columns: set[str], names: tuple[str, ...]) -> str:
    for name in names:
        if name in columns:
            value = str(row.get(name) or "").strip()
            if value:
                return value
    return ""


def _mapping_from_row(row: sqlite3.Row) -> VehicleMrTrainMapping:
    return VehicleMrTrainMapping(
        id=int(row["id"]) if row["id"] is not None else None,
        enabled=bool(row["enabled"]),
        train_display_name=str(row["train_display_name"] or ""),
        train_id=str(row["train_id"] or ""),
        train_no=str(row["train_no"] or ""),
        tc1_peer_name=str(row["tc1_peer_name"] or ""),
        tc2_peer_name=str(row["tc2_peer_name"] or ""),
        online_policy=normalize_online_policy(row["online_policy"] if "online_policy" in row.keys() else ""),
        remark=str(row["remark"] or ""),
        created_at=str(row["created_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
    )


def choose_best_links(links: list[VehicleMrMeshLink]) -> dict[str, VehicleMrMeshLink]:
    best: dict[str, VehicleMrMeshLink] = {}
    for link in links:
        status = str(link.status or "").strip().casefold()
        if status and status not in ONLINE_LINK_STATUSES:
            continue
        if link.rssi is None:
            continue
        key = link.peer_name_canonical or canonical_peer_name(link.peer_name) or link.peer_name
        current = best.get(key)
        if current is None or (current.rssi is None or link.rssi > current.rssi):
            best[key] = link
    return best


def build_train_states(
    registered_trains: dict[str, VehicleMrTrainState],
    parse_result: VehicleMrMeshParseResult,
    ap_lookup: dict[str, MatchedAp] | None = None,
    previous: dict[str, VehicleMrTrainState] | None = None,
    mapping_lookup: dict[str, TrainIdentity] | None = None,
) -> list[VehicleMrTrainState]:
    ap_lookup = ap_lookup or {}
    previous = previous or {}
    mapping_lookup = mapping_lookup or {}
    states = {
        train_id: VehicleMrTrainState(
            train.train_id,
            train.train_no,
            train.is_registered,
            online_policy=normalize_online_policy(train.online_policy),
            expected_end=train.expected_end,
            direction=train.direction or "未知",
            status_reason=train.status_reason,
        )
        for train_id, train in registered_trains.items()
    }
    registered_by_no = {train.train_no: train_id for train_id, train in registered_trains.items() if train.train_no}
    best_links = choose_best_links(parse_result.links)
    for peer_name, link in best_links.items():
        identity = mapping_lookup.get(link.peer_name) or mapping_lookup.get(peer_name) or parse_train_identity(peer_name)
        if identity is None:
            continue
        canonical_train_id = registered_by_no.get(identity.train_no, identity.train_id)
        is_registered = identity.train_no in registered_by_no
        state = states.setdefault(
            canonical_train_id,
            VehicleMrTrainState(canonical_train_id, identity.train_no, is_registered, online_policy=normalize_online_policy(identity.online_policy)),
        )
        if is_registered:
            state.is_registered = True
        if state.online_policy == ONLINE_POLICY_AUTO and identity.online_policy != ONLINE_POLICY_AUTO:
            state.online_policy = normalize_online_policy(identity.online_policy)
        matched = match_ap(link.local_ap_name, ap_lookup, link.local_mac)
        end_state = VehicleMrEndState(
            seen=True,
            station=matched.station if matched else UNKNOWN_STATION,
            ap_name=matched.ap_name if matched else link.local_ap_name,
            rssi=link.rssi,
            last_seen_at=parse_result.ac_time,
            match_method=matched.match_method if matched else "unmatched",
            match_score=matched.match_score if matched else 0,
        )
        if identity.car_end == "CT":
            state.tc1 = end_state
        else:
            state.tc2 = end_state
    for train_id, state in states.items():
        previous_state = previous.get(train_id) or _find_previous_by_train_no(previous, state.train_no)
        apply_online_policy(state)
        seen_ends = [end for end in (state.tc1, state.tc2) if end.seen]
        stations = [end.station for end in (state.tc1, state.tc2) if end.seen and end.station and end.station != UNKNOWN_STATION]
        if len(set(stations)) > 1:
            state.current_station = " / ".join(dict.fromkeys(stations))
        elif stations:
            state.current_station = stations[0]
        elif seen_ends:
            state.current_station = UNKNOWN_STATION
        else:
            state.current_station = "-"
        state.last_ac_time = parse_result.ac_time or (previous_state.last_ac_time if previous_state else "")
        state.last_seen_at = parse_result.ac_time if seen_ends else (previous_state.last_seen_at if previous_state else "")
        if previous_state and not state.tc1.seen:
            state.tc1 = VehicleMrEndState(last_seen_at=previous_state.tc1.last_seen_at)
        if previous_state and not state.tc2.seen:
            state.tc2 = VehicleMrEndState(last_seen_at=previous_state.tc2.last_seen_at)
    return sorted(states.values(), key=train_sort_key)


def apply_online_policy(state: VehicleMrTrainState) -> None:
    policy = normalize_online_policy(state.online_policy)
    state.online_policy = policy
    state.direction = state.direction or "未知"
    state.expected_end = ""
    tc1_seen = state.tc1.seen
    tc2_seen = state.tc2.seen
    if not tc1_seen and not tc2_seen:
        state.status = TRAIN_STATUS_OFFLINE
        state.status_reason = "both_offline"
        return
    if policy == ONLINE_POLICY_DUAL_ACTIVE:
        if tc1_seen and tc2_seen:
            state.status = TRAIN_STATUS_ONLINE
            state.status_reason = "dual_active_ok"
        else:
            state.status = TRAIN_STATUS_ABNORMAL_SINGLE
            state.status_reason = "tc2_missing" if tc1_seen else "tc1_missing"
        return
    if policy == ONLINE_POLICY_SINGLE_TC1:
        state.expected_end = "TC1"
        if tc1_seen and tc2_seen:
            state.status = TRAIN_STATUS_DUAL_ONLINE
            state.status_reason = "both_ends_online"
        elif tc1_seen:
            state.status = TRAIN_STATUS_ONLINE
            state.status_reason = "expected_tc1_online"
        else:
            state.status = TRAIN_STATUS_UNEXPECTED_END
            state.status_reason = "unexpected_tc2_online"
        return
    if policy == ONLINE_POLICY_SINGLE_TC2:
        state.expected_end = "TC2"
        if tc1_seen and tc2_seen:
            state.status = TRAIN_STATUS_DUAL_ONLINE
            state.status_reason = "both_ends_online"
        elif tc2_seen:
            state.status = TRAIN_STATUS_ONLINE
            state.status_reason = "expected_tc2_online"
        else:
            state.status = TRAIN_STATUS_UNEXPECTED_END
            state.status_reason = "unexpected_tc1_online"
        return
    if policy == ONLINE_POLICY_SINGLE_TAIL:
        if tc1_seen and tc2_seen:
            state.status = TRAIN_STATUS_DUAL_ONLINE
            state.status_reason = "both_ends_online"
            return
        if state.direction in {"上行", "下行"} and state.expected_end in {"TC1", "TC2"}:
            expected_seen = (state.expected_end == "TC1" and tc1_seen) or (state.expected_end == "TC2" and tc2_seen)
            state.status = TRAIN_STATUS_ONLINE if expected_seen else TRAIN_STATUS_UNEXPECTED_END
            state.status_reason = "expected_tail_online" if expected_seen else "unexpected_end_online"
            return
        state.status = TRAIN_STATUS_ONLINE
        state.status_reason = "direction_unknown_any_end_online"
        return
    state.status = TRAIN_STATUS_ONLINE
    state.status_reason = "policy_unknown_any_end_online"


def _find_previous_by_train_no(previous: dict[str, VehicleMrTrainState], train_no: str) -> VehicleMrTrainState | None:
    for state in previous.values():
        if state.train_no == train_no:
            return state
    return None


def match_ap(ap_name: str, ap_lookup: dict[str, object], local_mac: str = "") -> MatchedAp | None:
    name_key = str(ap_name or "").strip().casefold()
    if name_key:
        value = ap_lookup.get(f"name:{name_key}") or ap_lookup.get(name_key)
        if isinstance(value, MatchedAp):
            return value
    for mac in (ap_name, local_mac):
        normalized = normalize_mac(mac)
        if not normalized:
            continue
        value = ap_lookup.get(f"mac:{normalized}") or ap_lookup.get(normalized)
        if isinstance(value, MatchedAp):
            return value
    resources = ap_lookup.get("__resources__")
    if isinstance(resources, list):
        candidates: list[MatchedAp] = []
        for resource in resources:
            if not isinstance(resource, MatchedAp) or not resource.ap_mac:
                continue
            for mac in (local_mac, ap_name):
                method = h3c_radio_mac_match_method(mac, resource.ap_mac)
                if method and method != "exact_mac":
                    score = 80 if method == "h3c_radio_mac" else 78
                    candidates.append(MatchedAp(resource.ap_name, resource.station, method, score, resource.ap_mac, resource.station_source))
                    break
        if candidates:
            return sorted(candidates, key=lambda item: (-item.match_score, item.ap_name))[0]
    return None


class VehicleMrOnlineStore:
    def __init__(self, paths: PathResolver, site_name: str) -> None:
        self.paths = paths
        self.site_name = site_name
        self.db_path = paths.site_dir(site_name) / "rail_transit" / "vehicle_mr_online" / "vehicle_mr_online.sqlite"
        self.initialize()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS vehicle_mr_online_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL UNIQUE,
                    ac_device_id INTEGER,
                    ac_name TEXT,
                    started_at TEXT,
                    stopped_at TEXT,
                    sample_interval_seconds INTEGER,
                    status TEXT,
                    last_ac_time TEXT,
                    last_error TEXT,
                    created_at TEXT,
                    updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS vehicle_mr_online_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    sample_index INTEGER,
                    ac_time TEXT,
                    local_time TEXT,
                    command_duration_ms INTEGER,
                    link_count INTEGER,
                    parse_status TEXT,
                    error_message TEXT,
                    created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS vehicle_mr_online_links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    snapshot_id INTEGER,
                    ac_time TEXT,
                    peer_name TEXT,
                    peer_mac TEXT,
                    local_ap_name TEXT,
                    local_mac TEXT,
                    status TEXT,
                    rssi INTEGER,
                    rx_packets INTEGER,
                    tx_packets INTEGER,
                    train_id TEXT,
                    train_display_name TEXT,
                    train_no TEXT,
                    car_end TEXT,
                    car_end_label TEXT,
                    matched_station TEXT,
                    matched_ap_name TEXT,
                    match_method TEXT,
                    match_score INTEGER,
                    station_source TEXT,
                    created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS vehicle_mr_train_current_state (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    train_id TEXT NOT NULL UNIQUE,
                    train_display_name TEXT,
                    train_no TEXT,
                    is_registered INTEGER,
                    status TEXT,
                    current_station TEXT,
                    last_ac_time TEXT,
                    last_seen_at TEXT,
                    tc1_seen INTEGER,
                    tc1_station TEXT,
                    tc1_ap_name TEXT,
                    tc1_rssi INTEGER,
                    tc1_last_seen_at TEXT,
                    tc2_seen INTEGER,
                    tc2_station TEXT,
                    tc2_ap_name TEXT,
                    tc2_rssi INTEGER,
                    tc2_last_seen_at TEXT,
                    online_policy TEXT DEFAULT 'auto',
                    expected_end TEXT,
                    direction TEXT,
                    status_reason TEXT,
                    updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS vehicle_mr_train_pass_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    train_id TEXT,
                    train_display_name TEXT,
                    train_no TEXT,
                    car_end TEXT,
                    car_end_label TEXT,
                    event_time TEXT,
                    event_type TEXT,
                    status TEXT,
                    station TEXT,
                    ap_name TEXT,
                    rssi INTEGER,
                    online_policy TEXT DEFAULT 'auto',
                    expected_end TEXT,
                    direction TEXT,
                    status_reason TEXT,
                    created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS vehicle_mr_train_mapping (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    enabled INTEGER DEFAULT 1,
                    train_display_name TEXT NOT NULL,
                    train_id TEXT,
                    train_no TEXT,
                    tc1_peer_name TEXT,
                    tc2_peer_name TEXT,
                    online_policy TEXT DEFAULT 'auto',
                    remark TEXT,
                    created_at TEXT,
                    updated_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_vehicle_mr_pass_train_time ON vehicle_mr_train_pass_events(train_id, event_time);
                CREATE INDEX IF NOT EXISTS idx_vehicle_mr_pass_no_time ON vehicle_mr_train_pass_events(train_no, event_time);
                CREATE INDEX IF NOT EXISTS idx_vehicle_mr_pass_display_time ON vehicle_mr_train_pass_events(train_display_name, event_time);
                CREATE INDEX IF NOT EXISTS idx_vehicle_mr_pass_filters ON vehicle_mr_train_pass_events(car_end_label, status, event_time);
                """
            )
            self._ensure_columns(conn)

    def _ensure_columns(self, conn: sqlite3.Connection) -> None:
        additions = {
            "vehicle_mr_online_links": {
                "train_display_name": "TEXT",
                "match_method": "TEXT",
                "match_score": "INTEGER",
                "station_source": "TEXT",
            },
            "vehicle_mr_train_current_state": {
                "train_display_name": "TEXT",
                "online_policy": "TEXT DEFAULT 'auto'",
                "expected_end": "TEXT",
                "direction": "TEXT",
                "status_reason": "TEXT",
            },
            "vehicle_mr_train_pass_events": {
                "train_display_name": "TEXT",
                "online_policy": "TEXT DEFAULT 'auto'",
                "expected_end": "TEXT",
                "direction": "TEXT",
                "status_reason": "TEXT",
            },
            "vehicle_mr_train_mapping": {
                "enabled": "INTEGER DEFAULT 1",
                "train_display_name": "TEXT",
                "train_id": "TEXT",
                "train_no": "TEXT",
                "tc1_peer_name": "TEXT",
                "tc2_peer_name": "TEXT",
                "online_policy": "TEXT DEFAULT 'auto'",
                "remark": "TEXT",
                "created_at": "TEXT",
                "updated_at": "TEXT",
            },
        }
        for table, columns in additions.items():
            existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            for column, column_type in columns.items():
                if column not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def cleanup_history(self, retention_days: int = 30, now: datetime | None = None) -> int:
        cutoff = (now or datetime.now()) - timedelta(days=max(1, int(retention_days)))
        cutoff_text = cutoff.strftime("%Y-%m-%d %H:%M:%S")
        deleted = 0
        with self.connect() as conn:
            for table, field in (
                ("vehicle_mr_online_links", "created_at"),
                ("vehicle_mr_online_snapshots", "created_at"),
                ("vehicle_mr_train_pass_events", "created_at"),
                ("vehicle_mr_online_sessions", "created_at"),
            ):
                cursor = conn.execute(f"DELETE FROM {table} WHERE {field} < ?", (cutoff_text,))
                deleted += int(cursor.rowcount if cursor.rowcount is not None else 0)
        try:
            from netconsole.core import app_logger

            app_logger.log_info("VEHICLE_MR_HISTORY_CLEANUP", f"retention_days={retention_days}, deleted={deleted}")
        except Exception:
            pass
        return deleted

    def list_mappings(self) -> list[VehicleMrTrainMapping]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM vehicle_mr_train_mapping ORDER BY CAST(train_no AS INTEGER), id").fetchall()
        return [_mapping_from_row(row) for row in rows]

    def save_mappings(self, mappings: list[VehicleMrTrainMapping]) -> None:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._validate_mappings(mappings)
        with self.connect() as conn:
            conn.execute("DELETE FROM vehicle_mr_train_mapping")
            conn.executemany(
                """
                INSERT INTO vehicle_mr_train_mapping (
                    enabled, train_display_name, train_id, train_no, tc1_peer_name, tc2_peer_name,
                    online_policy, remark, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        1 if mapping.enabled else 0,
                        mapping.display_name,
                        mapping.train_id or f"列车{mapping.train_no}",
                        mapping.train_no or normalize_train_no(mapping.display_name),
                        mapping.tc1_peer_name.strip(),
                        mapping.tc2_peer_name.strip(),
                        normalize_online_policy(mapping.online_policy),
                        mapping.remark.strip(),
                        mapping.created_at or now,
                        now,
                    )
                    for mapping in mappings
                    if mapping.display_name and (mapping.tc1_peer_name.strip() or mapping.tc2_peer_name.strip())
                ],
            )

    def import_mapping_rows(self, rows: list[dict[str, object]]) -> int:
        mappings: list[VehicleMrTrainMapping] = []
        for row in rows:
            display_name = str(row.get("车次") or row.get("train") or row.get("train_display_name") or "").strip()
            tc1 = str(row.get("TC1") or row.get("tc1") or "").strip()
            tc2 = str(row.get("TC2") or row.get("tc2") or "").strip()
            online_policy = normalize_online_policy(row.get("在线策略") or row.get("online_policy") or row.get("policy") or "")
            remark = str(row.get("备注") or row.get("remark") or "").strip()
            if not display_name and not tc1 and not tc2 and not remark:
                continue
            if not display_name:
                raise ValueError("车次不能为空")
            if not tc1 and not tc2:
                raise ValueError(f"{display_name} 的 TC1 和 TC2 不能同时为空")
            train_no = normalize_train_no(display_name)
            mappings.append(
                VehicleMrTrainMapping(
                    enabled=True,
                    train_display_name=f"{train_no}车" if train_no else display_name,
                    train_id=f"列车{train_no}" if train_no else display_name,
                    train_no=train_no,
                    tc1_peer_name=tc1,
                    tc2_peer_name=tc2,
                    online_policy=online_policy,
                    remark=remark,
                )
            )
        self.save_mappings(mappings)
        return len(mappings)

    def _validate_mappings(self, mappings: list[VehicleMrTrainMapping]) -> None:
        seen: dict[str, str] = {}
        for mapping in mappings:
            if not mapping.enabled:
                continue
            display_name = mapping.display_name
            for label, peer in (("TC1", mapping.tc1_peer_name.strip()), ("TC2", mapping.tc2_peer_name.strip())):
                if not peer:
                    continue
                owner = seen.get(peer)
                if owner:
                    raise ValueError(f"Peer Name 重复：{peer} 已用于 {owner}")
                seen[peer] = f"{display_name} {label}"

    def create_session(self, ac: Device, interval: int) -> str:
        now = datetime.now().isoformat(sep=" ", timespec="seconds")
        session_id = f"{datetime.now():%Y%m%d_%H%M%S}_{int(time.time() * 1000) & 0xFFFFFF:06x}"
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO vehicle_mr_online_sessions (
                    session_id, ac_device_id, ac_name, started_at, sample_interval_seconds,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, ac.id, ac.name, now, interval, "连接中", now, now),
            )
        return session_id

    def update_session(self, session_id: str, status: str, ac_time: str = "", error: str = "", stopped: bool = False) -> None:
        now = datetime.now().isoformat(sep=" ", timespec="seconds")
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE vehicle_mr_online_sessions
                SET status = ?, last_ac_time = COALESCE(NULLIF(?, ''), last_ac_time),
                    last_error = ?, stopped_at = CASE WHEN ? THEN ? ELSE stopped_at END, updated_at = ?
                WHERE session_id = ?
                """,
                (status, ac_time, error, 1 if stopped else 0, now, now, session_id),
            )

    def load_current_states(self) -> dict[str, VehicleMrTrainState]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM vehicle_mr_train_current_state").fetchall()
        result: dict[str, VehicleMrTrainState] = {}
        for row in rows:
            result[str(row["train_id"])] = _state_from_row(row)
        return result

    def list_current_states(self) -> list[VehicleMrTrainState]:
        return sorted(self.load_current_states().values(), key=train_sort_key)

    def merge_duplicate_current_states_by_train_no(self, registered_trains: dict[str, VehicleMrTrainState]) -> None:
        registered_by_no = {train.train_no: train for train in registered_trains.values() if train.train_no}
        if not registered_by_no:
            return
        current = self.load_current_states()
        updates: list[tuple[str, str]] = []
        deletes: list[str] = []
        with self.connect() as conn:
            for train in current.values():
                official = registered_by_no.get(train.train_no)
                if official is None or train.train_id == official.train_id or train.is_registered:
                    continue
                merged = _merge_train_state(official, train)
                conn.execute(
                    """
                    INSERT INTO vehicle_mr_train_current_state (
                        session_id, train_id, train_no, is_registered, status, current_station, last_ac_time,
                        train_display_name, last_seen_at, tc1_seen, tc1_station, tc1_ap_name, tc1_rssi, tc1_last_seen_at,
                        tc2_seen, tc2_station, tc2_ap_name, tc2_rssi, tc2_last_seen_at,
                        online_policy, expected_end, direction, status_reason, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(train_id) DO UPDATE SET
                        status = excluded.status,
                        current_station = excluded.current_station,
                        last_ac_time = excluded.last_ac_time,
                        train_display_name = excluded.train_display_name,
                        last_seen_at = excluded.last_seen_at,
                        tc1_seen = excluded.tc1_seen,
                        tc1_station = excluded.tc1_station,
                        tc1_ap_name = excluded.tc1_ap_name,
                        tc1_rssi = excluded.tc1_rssi,
                        tc1_last_seen_at = excluded.tc1_last_seen_at,
                        tc2_seen = excluded.tc2_seen,
                        tc2_station = excluded.tc2_station,
                        tc2_ap_name = excluded.tc2_ap_name,
                        tc2_rssi = excluded.tc2_rssi,
                        tc2_last_seen_at = excluded.tc2_last_seen_at,
                        online_policy = excluded.online_policy,
                        expected_end = excluded.expected_end,
                        direction = excluded.direction,
                        status_reason = excluded.status_reason,
                        updated_at = excluded.updated_at
                    """,
                    _state_values("", merged, datetime.now().isoformat(sep=" ", timespec="seconds")),
                )
                updates.append((official.train_id, train.train_id))
                deletes.append(train.train_id)
            for official_id, duplicate_id in updates:
                conn.execute("UPDATE vehicle_mr_train_pass_events SET train_id = ?, train_display_name = ? WHERE train_id = ?", (official_id, registered_trains[official_id].display_name, duplicate_id))
            for duplicate_id in deletes:
                conn.execute("DELETE FROM vehicle_mr_train_current_state WHERE train_id = ?", (duplicate_id,))


    def list_events(self, train_id: str, limit: int = 200) -> list[dict[str, object]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM vehicle_mr_train_pass_events
                WHERE train_id = ? OR train_no = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (train_id, normalize_train_no(train_id), int(limit)),
            ).fetchall()
        return [dict(row) for row in rows]

    def query_events(
        self,
        train_identifier: str,
        start_time: str,
        end_time: str,
        car_end_label: str = "",
        status: str = "",
        station: str = "",
        ap_name: str = "",
        limit: int = 5000,
    ) -> list[dict[str, object]]:
        train_no = normalize_train_no(train_identifier)
        clauses = ["(train_id = ? OR train_no = ? OR train_display_name = ?)", "event_time >= ?", "event_time <= ?"]
        params: list[object] = [train_identifier, train_no, f"{train_no}车" if train_no else train_identifier, start_time, end_time]
        if car_end_label:
            clauses.append("car_end_label = ?")
            params.append(car_end_label)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if station:
            clauses.append("station LIKE ?")
            params.append(f"%{station}%")
        if ap_name:
            clauses.append("ap_name LIKE ?")
            params.append(f"%{ap_name}%")
        params.append(int(limit))
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM vehicle_mr_train_pass_events
                WHERE {' AND '.join(clauses)}
                ORDER BY event_time ASC, id ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def backfill_event_stations(self, ap_lookup: dict[str, object]) -> int:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, ap_name, station FROM vehicle_mr_train_pass_events
                WHERE station IS NULL OR station IN ('', '-', '未知车站', '未知')
                """
            ).fetchall()
            updates: list[tuple[str, int]] = []
            for row in rows:
                matched = match_ap(str(row["ap_name"] or ""), ap_lookup)
                if matched is not None and not is_empty_station(matched.station) and matched.station != UNKNOWN_STATION:
                    updates.append((matched.station, int(row["id"])))
            if updates:
                conn.executemany("UPDATE vehicle_mr_train_pass_events SET station = ? WHERE id = ?", updates)
            return len(updates)

    def persist_snapshot(
        self,
        session_id: str,
        sample_index: int,
        parse_result: VehicleMrMeshParseResult,
        trains: list[VehicleMrTrainState],
        ap_lookup: dict[str, MatchedAp],
        duration_ms: int,
    ) -> int:
        now = datetime.now().isoformat(sep=" ", timespec="seconds")
        previous = self.load_current_states()
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO vehicle_mr_online_snapshots (
                    session_id, sample_index, ac_time, local_time, command_duration_ms,
                    link_count, parse_status, error_message, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    sample_index,
                    parse_result.ac_time,
                    now,
                    duration_ms,
                    len(parse_result.links),
                    parse_result.parse_status,
                    parse_result.error_message,
                    now,
                ),
            )
            snapshot_id = int(cursor.lastrowid)
            conn.executemany(
                """
                INSERT INTO vehicle_mr_online_links (
                    session_id, snapshot_id, ac_time, peer_name, peer_mac, local_ap_name, local_mac,
                    status, rssi, rx_packets, tx_packets, train_id, train_display_name, train_no, car_end, car_end_label,
                    matched_station, matched_ap_name, match_method, match_score, station_source, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [self._link_values(session_id, snapshot_id, parse_result.ac_time, link, ap_lookup, now) for link in parse_result.links],
            )
            for train in trains:
                conn.execute(
                    """
                    INSERT INTO vehicle_mr_train_current_state (
                        session_id, train_id, train_no, is_registered, status, current_station, last_ac_time,
                        train_display_name, last_seen_at, tc1_seen, tc1_station, tc1_ap_name, tc1_rssi, tc1_last_seen_at,
                        tc2_seen, tc2_station, tc2_ap_name, tc2_rssi, tc2_last_seen_at,
                        online_policy, expected_end, direction, status_reason, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(train_id) DO UPDATE SET
                        session_id = excluded.session_id,
                        train_no = excluded.train_no,
                        train_display_name = excluded.train_display_name,
                        is_registered = excluded.is_registered,
                        status = excluded.status,
                        current_station = excluded.current_station,
                        last_ac_time = excluded.last_ac_time,
                        last_seen_at = excluded.last_seen_at,
                        tc1_seen = excluded.tc1_seen,
                        tc1_station = excluded.tc1_station,
                        tc1_ap_name = excluded.tc1_ap_name,
                        tc1_rssi = excluded.tc1_rssi,
                        tc1_last_seen_at = excluded.tc1_last_seen_at,
                        tc2_seen = excluded.tc2_seen,
                        tc2_station = excluded.tc2_station,
                        tc2_ap_name = excluded.tc2_ap_name,
                        tc2_rssi = excluded.tc2_rssi,
                        tc2_last_seen_at = excluded.tc2_last_seen_at,
                        online_policy = excluded.online_policy,
                        expected_end = excluded.expected_end,
                        direction = excluded.direction,
                        status_reason = excluded.status_reason,
                        updated_at = excluded.updated_at
                    """,
                    _state_values(session_id, train, now),
                )
                self._append_events(conn, session_id, previous.get(train.train_id), train, now)
        return snapshot_id

    def _link_values(
        self,
        session_id: str,
        snapshot_id: int,
        ac_time: str,
        link: VehicleMrMeshLink,
        ap_lookup: dict[str, MatchedAp],
        now: str,
    ) -> tuple[object, ...]:
        identity = parse_train_identity(link.peer_name)
        matched = match_ap(link.local_ap_name, ap_lookup, link.local_mac)
        train_display_name = f"{identity.train_no}车" if identity else ""
        return (
            session_id,
            snapshot_id,
            ac_time,
            link.peer_name,
            link.peer_mac,
            link.local_ap_name,
            link.local_mac,
            link.status,
            link.rssi,
            link.rx_packets,
            link.tx_packets,
            identity.train_id if identity else "",
            train_display_name,
            identity.train_no if identity else "",
            identity.car_end if identity else "",
            identity.car_end_label if identity else "",
            matched.station if matched else UNKNOWN_STATION,
            matched.ap_name if matched else link.local_ap_name,
            matched.match_method if matched else "unmatched",
            matched.match_score if matched else 0,
            matched.station_source if matched else "",
            now,
        )

    def _append_events(
        self,
        conn: sqlite3.Connection,
        session_id: str,
        old: VehicleMrTrainState | None,
        new: VehicleMrTrainState,
        now: str,
    ) -> None:
        for car_end, label, old_end, new_end in (
            ("CT", "TC1", old.tc1 if old else None, new.tc1),
            ("CW", "TC2", old.tc2 if old else None, new.tc2),
        ):
            event_type = _event_type(old_end, new_end)
            if not event_type:
                continue
            conn.execute(
                """
                INSERT INTO vehicle_mr_train_pass_events (
                    session_id, train_id, train_display_name, train_no, car_end, car_end_label, event_time,
                    event_type, status, station, ap_name, rssi, online_policy, expected_end, direction,
                    status_reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    new.train_id,
                    new.display_name,
                    new.train_no,
                    car_end,
                    label,
                    new.last_ac_time or now,
                    event_type,
                    new.status,
                    new_end.station if new_end.seen else "-",
                    new_end.ap_name if new_end.seen else "-",
                    new_end.rssi,
                    normalize_online_policy(new.online_policy),
                    new.expected_end,
                    new.direction,
                    new.status_reason,
                    now,
                ),
            )


def _event_type(old: VehicleMrEndState | None, new: VehicleMrEndState) -> str:
    if old is None:
        return "online" if new.seen else ""
    if old.seen != new.seen:
        return "online" if new.seen else "offline"
    if new.seen and old.station != new.station:
        return "station_changed"
    if new.seen and old.ap_name != new.ap_name:
        return "ap_changed"
    return ""


def _state_values(session_id: str, train: VehicleMrTrainState, now: str) -> tuple[object, ...]:
    return (
        session_id,
        train.train_id,
        train.train_no,
        1 if train.is_registered else 0,
        train.status,
        train.current_station,
        train.last_ac_time,
        train.display_name,
        train.last_seen_at,
        1 if train.tc1.seen else 0,
        train.tc1.station,
        train.tc1.ap_name,
        train.tc1.rssi,
        train.tc1.last_seen_at,
        1 if train.tc2.seen else 0,
        train.tc2.station,
        train.tc2.ap_name,
        train.tc2.rssi,
        train.tc2.last_seen_at,
        normalize_online_policy(train.online_policy),
        train.expected_end,
        train.direction,
        train.status_reason,
        now,
    )


def _state_from_row(row: sqlite3.Row) -> VehicleMrTrainState:
    return VehicleMrTrainState(
        train_id=str(row["train_id"]),
        train_no=str(row["train_no"] or ""),
        is_registered=bool(row["is_registered"]),
        status=str(row["status"] or TRAIN_STATUS_OFFLINE),
        current_station=str(row["current_station"] or "-"),
        last_ac_time=str(row["last_ac_time"] or ""),
        last_seen_at=str(row["last_seen_at"] or ""),
        tc1=VehicleMrEndState(bool(row["tc1_seen"]), str(row["tc1_station"] or ""), str(row["tc1_ap_name"] or ""), row["tc1_rssi"], str(row["tc1_last_seen_at"] or "")),
        tc2=VehicleMrEndState(bool(row["tc2_seen"]), str(row["tc2_station"] or ""), str(row["tc2_ap_name"] or ""), row["tc2_rssi"], str(row["tc2_last_seen_at"] or "")),
        online_policy=normalize_online_policy(row["online_policy"] if "online_policy" in row.keys() else ""),
        expected_end=str(row["expected_end"] or "") if "expected_end" in row.keys() else "",
        direction=str(row["direction"] or "未知") if "direction" in row.keys() else "未知",
        status_reason=str(row["status_reason"] or "") if "status_reason" in row.keys() else "",
    )


def _merge_train_state(official: VehicleMrTrainState, duplicate: VehicleMrTrainState) -> VehicleMrTrainState:
    merged = VehicleMrTrainState(official.train_id, official.train_no, True)
    merged.tc1 = duplicate.tc1 if duplicate.tc1.seen or duplicate.tc1.last_seen_at else official.tc1
    merged.tc2 = duplicate.tc2 if duplicate.tc2.seen or duplicate.tc2.last_seen_at else official.tc2
    merged.status = duplicate.status
    merged.current_station = duplicate.current_station
    merged.last_ac_time = duplicate.last_ac_time
    merged.last_seen_at = duplicate.last_seen_at
    merged.online_policy = normalize_online_policy(official.online_policy or duplicate.online_policy)
    merged.expected_end = duplicate.expected_end
    merged.direction = duplicate.direction
    merged.status_reason = duplicate.status_reason
    return merged


def load_group_names(repository: DeviceRepository, site_name: str) -> dict[int, str]:
    groups = DeviceGroupRepository(repository.database, site_name).list()
    return {int(group.id): group.name for group in groups if group.id is not None}


def resolve_ap_station(record: dict[str, object]) -> tuple[str | None, str]:
    for key in (
        "optical.site",
        "optical.site_name",
        "resource.site",
        "resource.site_name",
        "metadata.site_name",
        "metadata.site",
        "resource.metadata_site",
        "resource.metadata_site_name",
    ):
        value = record.get(key)
        if not is_empty_station(value):
            return str(value).strip(), key
    return None, ""


def backfill_fit_ap_resource_station_from_optical(repository: DeviceRepository) -> int:
    with repository.database.connect() as conn:
        if not _table_exists(conn, "ac_fit_ap_resources") or not _table_exists(conn, "ac_fit_ap_optical"):
            return 0
        rows = conn.execute(
            """
            SELECT r.id AS resource_id, r.site AS resource_site, r.ap_name AS resource_ap_name, r.ap_mac AS resource_ap_mac,
                   o.site AS optical_site
            FROM ac_fit_ap_resources r
            JOIN ac_fit_ap_optical o
              ON (LOWER(COALESCE(r.ap_name, '')) = LOWER(COALESCE(o.ap_name, '')) AND COALESCE(r.ap_name, '') <> '')
              OR (LOWER(REPLACE(REPLACE(COALESCE(r.ap_mac, ''), '-', ''), ':', '')) =
                  LOWER(REPLACE(REPLACE(COALESCE(o.ap_mac, ''), '-', ''), ':', '')) AND COALESCE(r.ap_mac, '') <> '')
            """
        ).fetchall()
        updates: list[tuple[str, int]] = []
        for row in rows:
            if is_empty_station(row["resource_site"]) and not is_empty_station(row["optical_site"]):
                updates.append((str(row["optical_site"]).strip(), int(row["resource_id"])))
        if updates:
            conn.executemany("UPDATE ac_fit_ap_resources SET site = ?, updated_at = COALESCE(updated_at, datetime('now')) WHERE id = ?", updates)
            conn.commit()
        return len(updates)


def load_trackside_ap_lookup(repository: DeviceRepository) -> dict[str, object]:
    backfill_fit_ap_resource_station_from_optical(repository)
    lookup: dict[str, object] = {"__resources__": []}
    records: dict[str, dict[str, object]] = {}
    with repository.database.connect() as conn:
        _merge_ap_rows(conn, records, "resource", "ac_fit_ap_resources", ("ap_name", "ap_mac", "site", "site_name", "metadata_site", "metadata_site_name"))
        _merge_ap_rows(conn, records, "optical", "ac_fit_ap_optical", ("ap_name", "ap_mac", "site", "site_name"))
        _merge_ap_rows(conn, records, "metadata", "ac_fit_ap_metadata", ("ap_name", "site_name", "site", "mileage", "location_note", "direction"))
        _merge_ap_rows(conn, records, "entity", "ap_entities", ("ap_name", "ap_mac", "station"))
        _merge_ap_rows(conn, records, "cache", "trackside_ap_view_cache", ("ap_name", "ap_mac", "station"))
    for record in records.values():
        ap_name = str(record.get("ap_name") or "").strip()
        ap_mac = normalize_mac(record.get("ap_mac"))
        station, station_source = resolve_ap_station(record)
        station_name = station or UNKNOWN_STATION
        display_name = ap_name or ap_mac
        if not display_name:
            continue
        resource = MatchedAp(display_name, station_name, "resource", 0, ap_mac, station_source)
        resources = lookup.get("__resources__")
        if isinstance(resources, list):
            resources.append(resource)
        if ap_name:
            lookup[f"name:{ap_name.casefold()}"] = MatchedAp(display_name, station_name, "ap_name_exact", 100, ap_mac, station_source)
            name_as_mac = normalize_mac(ap_name)
            if name_as_mac:
                lookup[f"mac:{name_as_mac}"] = MatchedAp(display_name, station_name, "mac_exact", 95, ap_mac, station_source)
        if ap_mac:
            lookup[f"mac:{ap_mac}"] = MatchedAp(display_name, station_name, "mac_exact", 95, ap_mac, station_source)
    return lookup


def _merge_ap_rows(conn: sqlite3.Connection, records: dict[str, dict[str, object]], source: str, table: str, wanted: tuple[str, ...]) -> None:
    if not _table_exists(conn, table):
        return
    columns = {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}
    selected = [column for column in wanted if column in columns]
    if not selected:
        return
    for row in conn.execute(f"SELECT {', '.join(selected)} FROM {table}").fetchall():
        row_data = dict(row)
        ap_name = str(row_data.get("ap_name") or "").strip()
        ap_mac = normalize_mac(row_data.get("ap_mac"))
        key = ap_mac or ap_name.casefold()
        if not key:
            continue
        record = records.setdefault(key, {})
        if ap_name and not record.get("ap_name"):
            record["ap_name"] = ap_name
        if ap_mac and not record.get("ap_mac"):
            record["ap_mac"] = ap_mac
        for column, value in row_data.items():
            record[f"{source}.{column}"] = value
        if source in {"entity", "cache"} and "station" in row_data:
            record[f"{source}.site"] = row_data.get("station")


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (table,)).fetchone() is not None


def is_ac_device(device: Device) -> bool:
    text = " ".join(str(value or "") for value in (device.device_type, device.name, device.system_name)).upper()
    return "AC" in text or "无线控制器" in text


class VehicleMrConnectionFactory(Protocol):
    def __call__(self, config: OnlineMrConnectionConfig):
        ...


class VehicleMrOnlineCollector:
    def __init__(
        self,
        ac: Device,
        site_name: str,
        interval_seconds: int,
        store: VehicleMrOnlineStore,
        registered_trains: dict[str, VehicleMrTrainState],
        ap_lookup: dict[str, MatchedAp],
        mapping_lookup: dict[str, TrainIdentity] | None,
        connection_config: OnlineMrConnectionConfig,
        connection_factory: VehicleMrConnectionFactory | None = None,
        parser: VehicleMrMeshLinkParser | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self.ac = ac
        self.site_name = site_name
        self.interval_seconds = max(3, min(300, int(interval_seconds)))
        self.store = store
        self.registered_trains = registered_trains
        self.ap_lookup = ap_lookup
        self.mapping_lookup = mapping_lookup or {}
        self.connection_config = connection_config
        self.connection_factory = connection_factory or (lambda config: NetmikoShellConnection(config))
        self.parser = parser or H3CComwareV9VehicleMrMeshLinkParser()
        self.sleeper = sleeper or time.sleep
        self.cancelled = False
        self.session_id = ""
        self.connection = None
        self.sample_index = 0
        self.current_by_train = store.load_current_states()

    def run_forever(self, callback: Callable[[VehicleMrOnlineSnapshot], None] | None = None) -> None:
        self.session_id = self.store.create_session(self.ac, self.interval_seconds)
        self._emit(callback, "连接中")
        try:
            self.connection = self.connection_factory(self.connection_config)
            self.connection.send_command(VEHICLE_INIT_COMMAND, self.connection_config.command_timeout)
            self.store.update_session(self.session_id, "采集中")
            while not self.cancelled:
                started = time.monotonic()
                snapshot = self.run_once()
                if callback:
                    callback(snapshot)
                elapsed = time.monotonic() - started
                wait = max(0.0, self.interval_seconds - elapsed)
                deadline = time.monotonic() + wait
                while not self.cancelled and time.monotonic() < deadline:
                    self.sleeper(min(0.2, deadline - time.monotonic()))
        except Exception as exc:
            self.store.update_session(self.session_id, "连接失败", error=str(exc))
            self._emit(callback, "连接失败", str(exc))
        finally:
            if self.connection is not None:
                try:
                    self.connection.close()
                except Exception:
                    pass
            if self.session_id:
                final_status = "已停止" if self.cancelled else "连接失败"
                self.store.update_session(self.session_id, final_status, stopped=True)

    def run_once(self) -> VehicleMrOnlineSnapshot:
        if self.connection is None:
            raise RuntimeError("connection is not ready")
        self.sample_index += 1
        started = time.monotonic()
        try:
            raw_text = "\n".join(self.connection.send_command(command, self.connection_config.command_timeout) for command in VEHICLE_SAMPLE_COMMANDS)
        except Exception as exc:
            self.store.update_session(self.session_id, "连接失败", error=str(exc))
            return VehicleMrOnlineSnapshot(self.session_id, "连接失败", trains=list(self.current_by_train.values()), error_message=str(exc))
        parse_result = self.parser.parse(raw_text)
        duration_ms = int((time.monotonic() - started) * 1000)
        if parse_result.parse_status == "FAILED":
            self.store.update_session(self.session_id, "解析失败/格式未适配", parse_result.ac_time, parse_result.error_message)
            return VehicleMrOnlineSnapshot(self.session_id, "解析失败/格式未适配", parse_result.ac_time, list(self.current_by_train.values()), parse_result.error_message)
        trains = build_train_states(self.registered_trains, parse_result, self.ap_lookup, self.current_by_train, self.mapping_lookup)
        self.store.persist_snapshot(self.session_id, self.sample_index, parse_result, trains, self.ap_lookup, duration_ms)
        self.current_by_train = {train.train_id: train for train in trains}
        self.store.update_session(self.session_id, "采集中", parse_result.ac_time)
        return VehicleMrOnlineSnapshot(self.session_id, "采集中", parse_result.ac_time, trains)

    def _emit(self, callback: Callable[[VehicleMrOnlineSnapshot], None] | None, status: str, error: str = "") -> None:
        if callback:
            callback(VehicleMrOnlineSnapshot(self.session_id, status, trains=list(self.current_by_train.values()), error_message=error))


def ensure_vehicle_mr_root(paths: PathResolver, site_name: str) -> Path:
    root = paths.site_dir(site_name) / "rail_transit" / "vehicle_mr_online"
    root.mkdir(parents=True, exist_ok=True)
    return root
