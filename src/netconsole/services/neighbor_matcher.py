from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import re
import unicodedata

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.device_address import normalize_ip_address
from netconsole.services.ap_identity.normalizers import normalize_mac
from netconsole.utils.interface_normalize import normalize_interface_name


GENERIC_NEIGHBOR_NAMES = frozenset(
    {
        "",
        "h3c",
        "comware",
        "switch",
        "ethernet switch",
        "unknown",
        "n/a",
        "na",
        "none",
        "null",
        "-",
        "--",
        "未知",
    }
)
_GENERIC_NORMALIZED_NAMES = frozenset(
    re.sub(r"[-_\s]+", "-", unicodedata.normalize("NFKC", value).strip().casefold())
    for value in GENERIC_NEIGHBOR_NAMES
)
_VENDOR_NAME_PREFIXES = frozenset(
    {
        "comware",
        "h3c",
        "zte",
        "zxr10",
    }
)
_SWITCH_TYPES = frozenset({"sw", "switch", "交换机"})
_ACTIVE_SCOPE_STATES = frozenset({"", "active", "enabled", "included", "in-service", "normal"})


@dataclass(frozen=True)
class NeighborMatchResult:
    device_uuid: str | None = None
    device_name: str | None = None
    station: str | None = None
    local_interface: str | None = None
    ap_interface: str | None = None
    matched_by: str | None = None
    confidence: float = 0.0
    match_status: str = "unresolved"
    candidate_count: int = 0
    reason: str | None = None
    station_id: str | None = None
    normalized_chassis_id: str | None = None
    normalized_management_ip: str | None = None
    normalized_system_name: str | None = None


def normalize_neighbor_identity_name(value: object) -> str:
    """Normalize an exact switch identity name without fuzzy matching."""

    text = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    if not text:
        return ""
    text = text.rstrip(".").split(".", 1)[0]
    parts = [part for part in re.split(r"[-_\s]+", text) if part]
    while parts and parts[0] in _VENDOR_NAME_PREFIXES:
        parts.pop(0)
    return "-".join(parts)


class NeighborDeviceIdentityIndex:
    """Resolve LLDP switch identity inside one caller-provided site scope."""

    def __init__(
        self,
        rows: Iterable[Mapping[str, object | None]],
    ) -> None:
        self._devices: dict[str, dict[str, object | None]] = {}
        self._mac_index: dict[str, set[str]] = defaultdict(set)
        self._ip_index: dict[str, set[str]] = defaultdict(set)
        self._system_name_index: dict[str, set[str]] = defaultdict(set)
        self._alias_index: dict[str, set[str]] = defaultdict(set)
        for raw in rows:
            row = dict(raw)
            device_uuid = str(row.get("device_uuid") or "").strip()
            if not device_uuid or not self._eligible(row):
                continue
            current = self._devices.setdefault(device_uuid, {})
            for field, value in row.items():
                if value not in (None, "") and current.get(field) in (None, ""):
                    current[field] = value
            current.setdefault("device_uuid", device_uuid)
            for field in (
                "mac_address",
                "fact_mac_address",
                "interface_mac_address",
                "chassis_id",
            ):
                if mac := normalize_mac(row.get(field)):
                    self._mac_index[mac].add(device_uuid)
            for field in (
                "normalized_primary_address",
                "primary_address",
                "management_ip",
            ):
                if address := self._normalized_ip(row.get(field)):
                    self._ip_index[address].add(device_uuid)
            for field in ("system_name", "fact_sysname", "sysname", "hostname"):
                if name := self._normalized_name(row.get(field)):
                    self._system_name_index[name].add(device_uuid)
            for field in ("name", "display_name", "device_alias"):
                if name := self._normalized_name(row.get(field)):
                    self._alias_index[name].add(device_uuid)

    def resolve(
        self,
        observation: Mapping[str, object | None],
    ) -> NeighborMatchResult:
        explicit_ids = self._values(
            observation,
            "switch_device_uuid",
            "neighbor_device_uuid",
            "lldp_neighbor_device_uuid",
            "lldp_neighbor_device_id",
        )
        if explicit_ids:
            candidates = {value for value in explicit_ids if value in self._devices}
            if len(candidates) == 1:
                return self._matched(next(iter(candidates)), "device_id", 1.0)
            return self._unresolved_or_ambiguous(
                candidates,
                matched_by="device_id",
                reason="稳定设备 ID 未命中当前局点交换机" if not candidates else "稳定设备 ID 对应多个交换机",
            )

        chassis_ids = {
            mac
            for field in (
                "lldp_neighbor_mac_normalized",
                "lldp_neighbor_mac",
                "neighbor_mac",
                "chassis_id",
                "lldp_chassis_id",
            )
            if (mac := normalize_mac(observation.get(field)))
        }
        result = self._resolve_index(
            chassis_ids,
            self._mac_index,
            matched_by="chassis_id",
            confidence=1.0,
            reason="邻居 Chassis ID 对应多个交换机",
            normalized_chassis_id=next(iter(chassis_ids), None),
        )
        if result is not None:
            return result

        management_ips = {
            address
            for field in (
                "lldp_management_ip",
                "lldp_neighbor_ip",
                "neighbor_ip",
                "management_ip",
            )
            if (address := self._normalized_ip(observation.get(field)))
        }
        result = self._resolve_index(
            management_ips,
            self._ip_index,
            matched_by="management_ip",
            confidence=0.98,
            reason="LLDP 管理地址对应多个交换机",
            normalized_management_ip=next(iter(management_ips), None),
        )
        if result is not None:
            return result

        names = {
            name
            for field in (
                "lldp_neighbor_name",
                "lldp_neighbor",
                "neighbor_device_name",
                "neighbor_sysname",
                "lldp_system_name",
                "system_name",
            )
            if (name := self._normalized_name(observation.get(field)))
        }
        result = self._resolve_index(
            names,
            self._system_name_index,
            matched_by="system_name",
            confidence=0.95,
            reason="规范化 LLDP System Name 对应多个交换机",
            normalized_system_name=next(iter(names), None),
        )
        if result is not None:
            return result
        result = self._resolve_index(
            names,
            self._alias_index,
            matched_by="device_alias",
            confidence=0.9,
            reason="规范化设备别名对应多个交换机",
            normalized_system_name=next(iter(names), None),
        )
        if result is not None:
            return result
        return NeighborMatchResult(
            match_status="unresolved",
            normalized_chassis_id=next(iter(chassis_ids), None),
            normalized_management_ip=next(iter(management_ips), None),
            normalized_system_name=next(iter(names), None),
            reason="LLDP 交换机身份未命中当前局点设备管理记录",
        )

    @staticmethod
    def _eligible(row: Mapping[str, object | None]) -> bool:
        device_type = str(row.get("device_type") or "").strip().casefold()
        if device_type and device_type not in _SWITCH_TYPES:
            return False
        scope = str(row.get("work_scope_status") or "").strip().casefold().replace("_", "-")
        return scope in _ACTIVE_SCOPE_STATES

    @staticmethod
    def _values(
        row: Mapping[str, object | None],
        *fields: str,
    ) -> set[str]:
        return {
            value
            for field in fields
            if (value := str(row.get(field) or "").strip())
        }

    @staticmethod
    def _normalized_ip(value: object) -> str:
        try:
            return normalize_ip_address(value) or ""
        except ValueError:
            return ""

    @staticmethod
    def _normalized_name(value: object) -> str:
        name = normalize_neighbor_identity_name(value)
        return "" if name in _GENERIC_NORMALIZED_NAMES else name

    def _resolve_index(
        self,
        keys: set[str],
        index: Mapping[str, set[str]],
        *,
        matched_by: str,
        confidence: float,
        reason: str,
        normalized_chassis_id: str | None = None,
        normalized_management_ip: str | None = None,
        normalized_system_name: str | None = None,
    ) -> NeighborMatchResult | None:
        if not keys:
            return None
        candidates = {
            device_uuid
            for key in keys
            for device_uuid in index.get(key, set())
        }
        if len(candidates) == 1:
            return self._matched(
                next(iter(candidates)),
                matched_by,
                confidence,
                normalized_chassis_id=normalized_chassis_id,
                normalized_management_ip=normalized_management_ip,
                normalized_system_name=normalized_system_name,
            )
        if len(candidates) > 1:
            return self._unresolved_or_ambiguous(
                candidates,
                matched_by=matched_by,
                reason=reason,
                normalized_chassis_id=normalized_chassis_id,
                normalized_management_ip=normalized_management_ip,
                normalized_system_name=normalized_system_name,
            )
        return None

    def _matched(
        self,
        device_uuid: str,
        matched_by: str,
        confidence: float,
        *,
        normalized_chassis_id: str | None = None,
        normalized_management_ip: str | None = None,
        normalized_system_name: str | None = None,
    ) -> NeighborMatchResult:
        row = self._devices[device_uuid]
        return NeighborMatchResult(
            device_uuid=device_uuid,
            device_name=str(row.get("name") or row.get("system_name") or device_uuid),
            station=str(row.get("station") or "") or None,
            station_id=str(row.get("station_id") or "") or None,
            matched_by=matched_by,
            confidence=confidence,
            match_status="matched",
            candidate_count=1,
            normalized_chassis_id=normalized_chassis_id,
            normalized_management_ip=normalized_management_ip,
            normalized_system_name=normalized_system_name,
        )

    @staticmethod
    def _unresolved_or_ambiguous(
        candidates: set[str],
        *,
        matched_by: str,
        reason: str,
        normalized_chassis_id: str | None = None,
        normalized_management_ip: str | None = None,
        normalized_system_name: str | None = None,
    ) -> NeighborMatchResult:
        return NeighborMatchResult(
            matched_by=matched_by,
            match_status="ambiguous" if len(candidates) > 1 else "unresolved",
            candidate_count=len(candidates),
            reason=reason,
            normalized_chassis_id=normalized_chassis_id,
            normalized_management_ip=normalized_management_ip,
            normalized_system_name=normalized_system_name,
        )


def is_generic_neighbor_name(value: object) -> bool:
    return str(value or "").strip().casefold() in GENERIC_NEIGHBOR_NAMES


def match_neighbor_device(
    site_name: str,
    neighbor_mac: str | None = None,
    neighbor_sysname: str | None = None,
    neighbor_interface: str | None = None,
    paths: PathResolver | None = None,
) -> NeighborMatchResult:
    database = Database((paths or PathResolver()).site_db_path(site_name))
    mac = normalize_mac(neighbor_mac)
    if mac:
        compact_mac = mac.replace(":", "")
        with database.connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT d.device_uuid, d.name, d.station,
                       COALESCE(i.interface_name, '') AS interface_name
                FROM devices d
                LEFT JOIN device_interfaces i ON i.device_uuid = d.device_uuid
                LEFT JOIN device_facts f ON f.device_uuid = d.device_uuid
                WHERE lower(replace(replace(replace(replace(COALESCE(d.mac_address, ''), ':', ''), '-', ''), '.', ''), ' ', '')) = ?
                   OR lower(replace(replace(replace(replace(COALESCE(i.mac_address, ''), ':', ''), '-', ''), '.', ''), ' ', '')) = ?
                   OR lower(replace(replace(replace(replace(COALESCE(f.mac_address, ''), ':', ''), '-', ''), '.', ''), ' ', '')) = ?
                ORDER BY d.name, i.interface_name
                """,
                (compact_mac, compact_mac, compact_mac),
            ).fetchall()
        candidates = {str(row["device_uuid"]): row for row in rows}
        if len(candidates) == 1:
            row = next(iter(candidates.values()))
            return NeighborMatchResult(
                device_uuid=str(row["device_uuid"]),
                device_name=str(row["name"]),
                station=row["station"],
                local_interface=str(row["interface_name"] or "") or None,
                matched_by="mac",
                confidence=1.0,
                match_status="matched",
            )
        if len(candidates) > 1:
            return NeighborMatchResult(match_status="ambiguous", candidate_count=len(candidates), reason="邻居 Chassis MAC 对应多个设备")

    sysname = (neighbor_sysname or "").strip()
    if sysname and not is_generic_neighbor_name(sysname):
        with database.connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT d.device_uuid, d.name, d.station
                FROM devices d
                LEFT JOIN device_facts f ON f.device_uuid = d.device_uuid
                WHERE f.sysname = ? OR d.system_name = ? OR d.name = ?
                ORDER BY d.name
                """,
                (sysname, sysname, sysname),
            ).fetchall()
        candidates = {str(row["device_uuid"]): row for row in rows}
        if len(candidates) == 1:
            row = next(iter(candidates.values()))
            return NeighborMatchResult(
                device_uuid=str(row["device_uuid"]),
                device_name=str(row["name"]),
                station=row["station"],
                matched_by="sysname",
                confidence=0.9,
                match_status="matched",
            )
        if len(candidates) > 1:
            return NeighborMatchResult(match_status="ambiguous", candidate_count=len(candidates), reason="邻居 System Name 对应多个设备")

    return NeighborMatchResult()


def match_ap_from_device_lldp(
    site_name: str,
    ap_mac: str | None = None,
    ap_name: str | None = None,
    paths: PathResolver | None = None,
) -> NeighborMatchResult:
    normalized_ap_mac = normalize_mac(ap_mac)
    if not normalized_ap_mac:
        return NeighborMatchResult()
    database = Database((paths or PathResolver()).site_db_path(site_name))
    compact_mac = normalized_ap_mac.replace(":", "")
    with database.connect() as conn:
        rows = conn.execute(
            """
            SELECT l.local_interface, l.neighbor_interface,
                   d.device_uuid, d.name, d.station
            FROM device_lldp_neighbors l
            JOIN devices d ON d.device_uuid = l.device_uuid
            WHERE lower(
                replace(replace(replace(l.neighbor_mac, ':', ''), '-', ''), '.', '')
            ) = ?
            ORDER BY l.id DESC
            """,
            (compact_mac,),
        ).fetchall()
    candidates = {(str(row["device_uuid"]), normalize_interface_name(row["local_interface"])): row for row in rows}
    if len(candidates) == 1:
        row = next(iter(candidates.values()))
        return NeighborMatchResult(
            device_uuid=str(row["device_uuid"]),
            device_name=str(row["name"]),
            station=row["station"],
            local_interface=row["local_interface"],
            ap_interface=row["neighbor_interface"],
            matched_by="device_lldp",
            confidence=1.0,
            match_status="matched",
        )
    if len(candidates) > 1:
        return NeighborMatchResult(match_status="ambiguous", candidate_count=len(candidates), reason="交换机侧 LLDP 按 AP MAC 对应多个端口")
    return NeighborMatchResult()


def find_neighbor_rx_power(site_name: str, device_uuid: str | None, interface_name: str | None, paths: PathResolver | None = None) -> str | None:
    module = find_neighbor_optical_module(site_name, device_uuid, interface_name, paths=paths)
    value = module.get("rx_power") if module else None
    return str(value) if value else None


def find_neighbor_optical_module(site_name: str, device_uuid: str | None, interface_name: str | None, paths: PathResolver | None = None) -> dict[str, object | None] | None:
    if not device_uuid or not interface_name:
        return None
    database = Database((paths or PathResolver()).site_db_path(site_name))
    with database.connect() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM device_optical_modules
            WHERE device_uuid = ? AND interface_name = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (device_uuid, interface_name),
        ).fetchone()
        if row is None:
            normalized = normalize_interface_name(interface_name)
            rows = conn.execute(
                """
                SELECT *
                FROM device_optical_modules
                WHERE device_uuid = ?
                ORDER BY id DESC
                """,
                (device_uuid,),
            ).fetchall()
            for item in rows:
                if normalize_interface_name(item["interface_name"]) == normalized:
                    return dict(item)
    return dict(row) if row else None
