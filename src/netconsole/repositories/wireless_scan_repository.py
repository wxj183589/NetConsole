from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from netconsole.core.sqlite_utils import connect_sqlite, initialize_sqlite_wal
from netconsole.models.wireless_scan_models import WirelessScanResult


class WirelessScanRepository:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def initialize(self) -> None:
        with self._connect() as conn:
            initialize_sqlite_wal(conn)
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS wireless_scan_runs (
                    scan_id TEXT PRIMARY KEY,
                    site TEXT NOT NULL,
                    project_id TEXT DEFAULT '',
                    project_name TEXT DEFAULT '',
                    project_description TEXT DEFAULT '',
                    adapter_name TEXT DEFAULT '',
                    adapter_guid TEXT DEFAULT '',
                    started_at TEXT NOT NULL,
                    ended_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    network_count INTEGER DEFAULT 0,
                    raw_file TEXT DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS wireless_scan_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scan_id TEXT NOT NULL REFERENCES wireless_scan_runs(scan_id) ON DELETE CASCADE,
                    ssid TEXT DEFAULT '',
                    bssid TEXT DEFAULT '',
                    rssi_dbm INTEGER NULL,
                    quality INTEGER NULL,
                    band TEXT DEFAULT '',
                    channel INTEGER NULL,
                    frequency_mhz INTEGER NULL,
                    channel_width_mhz INTEGER NULL,
                    channel_width_text TEXT DEFAULT '',
                    channel_width_source TEXT DEFAULT '',
                    channel_width TEXT DEFAULT '',
                    phy_type TEXT DEFAULT '',
                    auth TEXT DEFAULT '',
                    encryption TEXT DEFAULT '',
                    mimo TEXT DEFAULT '',
                    mimo_source TEXT DEFAULT '',
                    mimo_note TEXT DEFAULT '',
                    scan_source TEXT DEFAULT '',
                    has_wlan_api_data INTEGER DEFAULT 0,
                    has_netsh_data INTEGER DEFAULT 0,
                    source_flags_json TEXT DEFAULT '',
                    wlan_api_raw_json TEXT DEFAULT '',
                    netsh_raw_text TEXT DEFAULT '',
                    auth_method TEXT DEFAULT '',
                    security TEXT DEFAULT '',
                    encryption_method TEXT DEFAULT '',
                    raw_ie_available INTEGER DEFAULT 0,
                    parse_warnings_json TEXT DEFAULT '',
                    vendor TEXT DEFAULT '',
                    is_hidden INTEGER DEFAULT 0,
                    last_seen TEXT DEFAULT '',
                    raw_json TEXT DEFAULT '',
                    matched_trackside_ap INTEGER DEFAULT 0,
                    match_status TEXT DEFAULT '',
                    matched_ap_name TEXT DEFAULT '',
                    matched_ap_mac TEXT DEFAULT '',
                    matched_station TEXT DEFAULT '',
                    matched_section TEXT DEFAULT '',
                    matched_belong_type TEXT DEFAULT '',
                    matched_belonging_source TEXT DEFAULT '',
                    matched_location TEXT DEFAULT '',
                    matched_direction TEXT DEFAULT '',
                    matched_radio_id INTEGER NULL,
                    match_rule TEXT DEFAULT '',
                    match_candidates_json TEXT DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_wireless_scan_results_scan ON wireless_scan_results(scan_id);
                CREATE INDEX IF NOT EXISTS idx_wireless_scan_results_bssid ON wireless_scan_results(bssid);
                """
            )
            self._ensure_runs_columns(conn)
            self._ensure_results_columns(conn)

    def save_scan(
        self,
        scan_id: str,
        site: str,
        adapter_name: str,
        adapter_guid: str,
        started_at: str,
        ended_at: str,
        status: str,
        raw_file: str,
        results: list[WirelessScanResult],
        project_id: str = "",
        project_name: str = "",
        project_description: str = "",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO wireless_scan_runs (
                    scan_id, site, project_id, project_name, project_description,
                    adapter_name, adapter_guid, started_at, ended_at, status, network_count, raw_file
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scan_id,
                    site,
                    project_id,
                    project_name,
                    project_description,
                    adapter_name,
                    adapter_guid,
                    started_at,
                    ended_at,
                    status,
                    len(results),
                    raw_file,
                ),
            )
            conn.execute("DELETE FROM wireless_scan_results WHERE scan_id = ?", (scan_id,))
            conn.executemany(
                """
                INSERT INTO wireless_scan_results (
                    scan_id, ssid, bssid, rssi_dbm, quality, band, channel, frequency_mhz, channel_width_mhz, channel_width_text,
                    channel_width_source, channel_width, phy_type, auth, encryption, mimo, mimo_source, mimo_note,
                    scan_source, has_wlan_api_data, has_netsh_data, source_flags_json, wlan_api_raw_json, netsh_raw_text,
                    auth_method, security, encryption_method, raw_ie_available, parse_warnings_json, vendor, is_hidden, last_seen, raw_json,
                    matched_trackside_ap, match_status, matched_ap_name, matched_ap_mac, matched_station,
                    matched_section, matched_belong_type, matched_belonging_source,
                    matched_location, matched_direction, matched_radio_id, match_rule, match_candidates_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [self._result_row(scan_id, result) for result in results],
            )
            conn.commit()

    def list_runs(self, limit: int = 200, offset: int = 0) -> list[dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM wireless_scan_runs ORDER BY started_at DESC, scan_id DESC LIMIT ? OFFSET ?",
                (max(1, int(limit)), max(0, int(offset))),
            ).fetchall()
        return [dict(row) for row in rows]

    def count_runs(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS value FROM wireless_scan_runs").fetchone()
        return int(row["value"] if row is not None else 0)

    def get_run(self, scan_id: str) -> dict[str, object] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM wireless_scan_runs WHERE scan_id = ?", (scan_id,)).fetchone()
        return dict(row) if row is not None else None

    def list_results(
        self,
        scan_id: str,
        *,
        limit: int | None = None,
        offset: int = 0,
        only_trackside: bool = False,
        band: str = "",
        radio: str = "",
        search: str = "",
    ) -> list[dict[str, object]]:
        where, values = self._result_filters(scan_id, only_trackside=only_trackside, band=band, radio=radio, search=search)
        query = f"""
            SELECT * FROM wireless_scan_results
            WHERE {' AND '.join(where)}
            ORDER BY matched_trackside_ap DESC, rssi_dbm DESC, matched_station, matched_ap_name, id
        """
        if limit is not None:
            query += " LIMIT ? OFFSET ?"
            values.extend((max(1, int(limit)), max(0, int(offset))))
        with self._connect() as conn:
            rows = conn.execute(query, values).fetchall()
        return [dict(row) for row in rows]

    def count_results(
        self,
        scan_id: str,
        *,
        only_trackside: bool = False,
        band: str = "",
        radio: str = "",
        search: str = "",
    ) -> int:
        where, values = self._result_filters(scan_id, only_trackside=only_trackside, band=band, radio=radio, search=search)
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) AS value FROM wireless_scan_results WHERE {' AND '.join(where)}",
                values,
            ).fetchone()
        return int(row["value"] if row is not None else 0)

    @staticmethod
    def _result_filters(
        scan_id: str,
        *,
        only_trackside: bool,
        band: str,
        radio: str,
        search: str,
    ) -> tuple[list[str], list[object]]:
        where = ["scan_id = ?"]
        values: list[object] = [scan_id]
        if only_trackside:
            where.append("matched_trackside_ap = 1")
        if band:
            where.append("band = ?")
            values.append(band)
        if radio:
            where.append("CAST(matched_radio_id AS TEXT) = ?")
            values.append(radio)
        if search:
            where.append(
                "(instr(lower(ssid), lower(?)) > 0 OR instr(lower(bssid), lower(?)) > 0 "
                "OR instr(lower(matched_ap_mac), lower(?)) > 0 OR instr(lower(matched_ap_name), lower(?)) > 0 "
                "OR instr(lower(matched_station), lower(?)) > 0 OR instr(lower(matched_section), lower(?)) > 0 "
                "OR instr(lower(matched_location), lower(?)) > 0)"
            )
            values.extend([search] * 7)
        return where, values

    def backfill_project_snapshot(self, project_id: str, project_name: str, project_description: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE wireless_scan_runs
                SET project_name = ?, project_description = ?
                WHERE project_id = ? AND project_name = ''
                """,
                (project_name, project_description, project_id),
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.path)

    @staticmethod
    def _ensure_runs_columns(conn: sqlite3.Connection) -> None:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(wireless_scan_runs)").fetchall()}
        if "project_id" not in columns:
            conn.execute("ALTER " "TABLE wireless_scan_runs ADD COLUMN project_id TEXT DEFAULT ''")
        if "project_name" not in columns:
            conn.execute("ALTER " "TABLE wireless_scan_runs ADD COLUMN project_name TEXT DEFAULT ''")
        if "project_description" not in columns:
            conn.execute("ALTER " "TABLE wireless_scan_runs ADD COLUMN project_description TEXT DEFAULT ''")

    @staticmethod
    def _ensure_results_columns(conn: sqlite3.Connection) -> None:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(wireless_scan_results)").fetchall()}
        if "channel_width_mhz" not in columns:
            conn.execute("ALTER " "TABLE wireless_scan_results ADD COLUMN channel_width_mhz INTEGER NULL")
        if "channel_width_text" not in columns:
            conn.execute("ALTER " "TABLE wireless_scan_results ADD COLUMN channel_width_text TEXT DEFAULT ''")
        if "channel_width_source" not in columns:
            conn.execute("ALTER " "TABLE wireless_scan_results ADD COLUMN channel_width_source TEXT DEFAULT ''")
        if "channel_width" not in columns:
            conn.execute("ALTER " "TABLE wireless_scan_results ADD COLUMN channel_width TEXT DEFAULT ''")
        for column in ("mimo", "mimo_source", "mimo_note", "scan_source"):
            if column not in columns:
                conn.execute(f"ALTER " f"TABLE wireless_scan_results ADD COLUMN {column} TEXT DEFAULT ''")
        for column in ("has_wlan_api_data", "has_netsh_data"):
            if column not in columns:
                conn.execute(f"ALTER " f"TABLE wireless_scan_results ADD COLUMN {column} INTEGER DEFAULT 0")
        for column in ("source_flags_json", "wlan_api_raw_json", "netsh_raw_text", "auth_method", "security", "encryption_method"):
            if column not in columns:
                conn.execute(f"ALTER " f"TABLE wireless_scan_results ADD COLUMN {column} TEXT DEFAULT ''")
        if "raw_ie_available" not in columns:
            conn.execute("ALTER " "TABLE wireless_scan_results ADD COLUMN raw_ie_available INTEGER DEFAULT 0")
        if "parse_warnings_json" not in columns:
            conn.execute("ALTER " "TABLE wireless_scan_results ADD COLUMN parse_warnings_json TEXT DEFAULT ''")
        for column in ("matched_section", "matched_belong_type", "matched_belonging_source"):
            if column not in columns:
                conn.execute(f"ALTER " f"TABLE wireless_scan_results ADD COLUMN {column} TEXT DEFAULT ''")

    @staticmethod
    def _result_row(scan_id: str, result: WirelessScanResult) -> tuple[object, ...]:
        network = result.network
        match = result.match
        return (
            scan_id,
            network.ssid,
            network.bssid,
            network.rssi_dbm,
            network.quality,
            network.band,
            network.channel,
            network.frequency_mhz,
            network.channel_width_mhz,
            network.channel_width_text,
            network.channel_width_source,
            network.channel_width,
            network.phy_type,
            network.auth,
            network.encryption,
            network.mimo or "-",
            network.mimo_source or "unavailable",
            network.mimo_note or "",
            network.scan_source,
            1 if network.has_wlan_api_data else 0,
            1 if network.has_netsh_data else 0,
            json.dumps(dict(network.source_flags), ensure_ascii=False),
            json.dumps(network.raw.get("wlan_api_raw", {}), ensure_ascii=False),
            json.dumps(network.raw.get("netsh_raw", {}), ensure_ascii=False),
            network.auth,
            network.auth,
            network.encryption,
            1 if network.raw_ie_available else 0,
            json.dumps(list(network.parse_warnings), ensure_ascii=False),
            network.vendor,
            1 if network.is_hidden else 0,
            network.last_seen,
            json.dumps(network.raw, ensure_ascii=False),
            1 if match.matched else 0,
            match.match_status,
            match.ap_name,
            match.ap_mac,
            match.station,
            match.section,
            match.belong_type,
            match.belonging_source or match.match_rule,
            match.location or match.mileage,
            match.direction,
            match.radio_id,
            match.match_rule,
            json.dumps(list(match.candidates), ensure_ascii=False),
        )
