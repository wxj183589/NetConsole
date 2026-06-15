from __future__ import annotations

from dataclasses import dataclass

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver


@dataclass(frozen=True)
class NeighborMatchResult:
    device_uuid: str | None = None
    device_name: str | None = None
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
                SELECT d.device_uuid, d.name
                FROM devices d
                LEFT JOIN device_facts f ON f.device_uuid = d.device_uuid
                WHERE d.sysname = ? OR f.sysname = ?
                LIMIT 1
                """,
                (sysname, sysname),
            ).fetchone()
        if row:
            return NeighborMatchResult(str(row["device_uuid"]), str(row["name"]), "sysname", 1.0)

    mac = _normalize_mac(neighbor_mac)
    if mac:
        with database.connect() as conn:
            row = conn.execute(
                """
                SELECT d.device_uuid, d.name
                FROM device_interfaces i
                JOIN devices d ON d.device_uuid = i.device_uuid
                WHERE lower(replace(i.mac_address, ':', '-')) = ?
                LIMIT 1
                """,
                (mac,),
            ).fetchone()
        if row:
            return NeighborMatchResult(str(row["device_uuid"]), str(row["name"]), "mac", 0.9)

    return NeighborMatchResult()


def find_neighbor_rx_power(site_name: str, device_uuid: str | None, interface_name: str | None, paths: PathResolver | None = None) -> str | None:
    if not device_uuid or not interface_name:
        return None
    database = Database((paths or PathResolver()).site_db_path(site_name))
    with database.connect() as conn:
        row = conn.execute(
            """
            SELECT rx_power
            FROM device_optical_modules
            WHERE device_uuid = ? AND interface_name = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (device_uuid, interface_name),
        ).fetchone()
    return str(row["rx_power"]) if row and row["rx_power"] else None


def _normalize_mac(value: str | None) -> str:
    return str(value or "").strip().lower().replace(":", "-")
