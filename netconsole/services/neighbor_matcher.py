from __future__ import annotations

from dataclasses import dataclass

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver


@dataclass(frozen=True)
class NeighborMatchResult:
    device_uuid: str | None = None
    device_name: str | None = None
    station: str | None = None
    local_interface: str | None = None
    ap_interface: str | None = None
    matched_by: str | None = None
    confidence: float = 0.0


def match_neighbor_device(
    site_name: str,
    neighbor_mac: str | None = None,
    neighbor_sysname: str | None = None,
    neighbor_interface: str | None = None,
    paths: PathResolver | None = None,
) -> NeighborMatchResult:
    database = Database((paths or PathResolver()).site_db_path(site_name))
    sysname = (neighbor_sysname or "").strip()
    if sysname:
        with database.connect() as conn:
            row = conn.execute(
                """
                SELECT d.device_uuid, d.name, d.station
                FROM device_facts f
                JOIN devices d ON d.device_uuid = f.device_uuid
                WHERE f.sysname = ?
                LIMIT 1
                """,
                (sysname,),
            ).fetchone()
            if row is None:
                row = conn.execute(
                    """
                    SELECT d.device_uuid, d.name, d.station
                    FROM devices d
                    WHERE d.sysname = ?
                    LIMIT 1
                    """,
                    (sysname,),
                ).fetchone()
            if row is None:
                row = conn.execute(
                    """
                    SELECT d.device_uuid, d.name, d.station
                    FROM devices d
                    WHERE d.name = ?
                    LIMIT 1
                    """,
                    (sysname,),
                ).fetchone()
        if row:
            return NeighborMatchResult(device_uuid=str(row["device_uuid"]), device_name=str(row["name"]), station=row["station"], matched_by="sysname", confidence=1.0)

    mac = _normalize_mac(neighbor_mac)
    if mac:
        with database.connect() as conn:
            row = conn.execute(
                """
                SELECT d.device_uuid, d.name, d.station
                FROM device_interfaces i
                JOIN devices d ON d.device_uuid = i.device_uuid
                WHERE lower(replace(i.mac_address, ':', '-')) = ?
                LIMIT 1
                """,
                (mac,),
            ).fetchone()
        if row:
            return NeighborMatchResult(device_uuid=str(row["device_uuid"]), device_name=str(row["name"]), station=row["station"], matched_by="mac", confidence=0.9)

    return NeighborMatchResult()


def match_ap_from_device_lldp(
    site_name: str,
    ap_mac: str | None = None,
    ap_name: str | None = None,
    paths: PathResolver | None = None,
) -> NeighborMatchResult:
    candidates = [item for item in {_normalize_mac(ap_mac), _normalize_mac(ap_name), str(ap_name or "").strip()} if item]
    if not candidates:
        return NeighborMatchResult()
    database = Database((paths or PathResolver()).site_db_path(site_name))
    with database.connect() as conn:
        for value in candidates:
            row = conn.execute(
                """
                SELECT l.local_interface, l.neighbor_interface,
                       d.device_uuid, d.name, d.station
                FROM device_lldp_neighbors l
                JOIN devices d ON d.device_uuid = l.device_uuid
                WHERE lower(replace(l.neighbor_mac, ':', '-')) = ?
                   OR lower(replace(l.neighbor_sysname, ':', '-')) = ?
                   OR l.neighbor_sysname = ?
                ORDER BY l.id DESC
                LIMIT 1
                """,
                (value, value, value),
            ).fetchone()
            if row:
                return NeighborMatchResult(
                    device_uuid=str(row["device_uuid"]),
                    device_name=str(row["name"]),
                    station=row["station"],
                    local_interface=row["local_interface"],
                    ap_interface=row["neighbor_interface"],
                    matched_by="device_lldp",
                    confidence=1.0,
                )
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


def _normalize_mac(value: str | None) -> str:
    return str(value or "").strip().lower().replace(":", "-")


def normalize_interface_name(value: object) -> str:
    text = str(value or "").strip()
    lower = text.lower()
    replacements = (
        ("xge", "Ten-GigabitEthernet"),
        ("ge", "GigabitEthernet"),
        ("bagg", "Bridge-Aggregation"),
        ("vlan", "Vlan-interface"),
    )
    for prefix, full in replacements:
        if lower.startswith(prefix) and len(text) > len(prefix) and text[len(prefix)].isdigit():
            return full + text[len(prefix):]
    return text
