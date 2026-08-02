from __future__ import annotations

from dataclasses import dataclass

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
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
