from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from netconsole.core.database import Database
from netconsole.core.sqlite_utils import configure_sqlite_connection, initialize_sqlite_wal
from netconsole.parsers.h3c.arp_parser import ArpRecord, ArpParseResult


SCHEMA = """
CREATE TABLE IF NOT EXISTS ground_arp_collections (
    collection_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL,
    source_device_uuid TEXT NOT NULL,
    source_device_name TEXT NOT NULL DEFAULT '',
    query_mode TEXT NOT NULL,
    query_scope TEXT NOT NULL,
    requested_vlans_json TEXT NOT NULL DEFAULT '[]',
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    completeness TEXT NOT NULL,
    record_count INTEGER NOT NULL DEFAULT 0,
    matched_count INTEGER NOT NULL DEFAULT 0,
    conflict_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT NOT NULL DEFAULT '',
    raw_reference TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ground_arp_collections_scope
ON ground_arp_collections(site_id, source_device_uuid, query_scope, started_at DESC);

CREATE TABLE IF NOT EXISTS ground_arp_observations (
    observation_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL,
    source_device_uuid TEXT NOT NULL,
    source_device_name TEXT NOT NULL DEFAULT '',
    query_scope TEXT NOT NULL,
    vlan TEXT NOT NULL DEFAULT '',
    ip_address TEXT NOT NULL,
    mac_address TEXT NOT NULL,
    interface_name TEXT NOT NULL DEFAULT '',
    aging TEXT NOT NULL DEFAULT '',
    entry_type TEXT NOT NULL DEFAULT '',
    first_observed_at TEXT NOT NULL,
    last_observed_at TEXT NOT NULL,
    last_collection_id TEXT NOT NULL,
    last_success_collection_id TEXT NOT NULL DEFAULT '',
    observed_in_last_success INTEGER NOT NULL DEFAULT 0,
    last_collection_success INTEGER NOT NULL DEFAULT 0,
    observation_count INTEGER NOT NULL DEFAULT 1,
    freshness_status TEXT NOT NULL DEFAULT 'NOT_OBSERVED',
    raw_line TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(site_id, source_device_uuid, query_scope, vlan, ip_address, mac_address)
);
CREATE INDEX IF NOT EXISTS idx_ground_arp_observations_ip
ON ground_arp_observations(site_id, ip_address, last_observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_ground_arp_observations_mac
ON ground_arp_observations(site_id, mac_address, last_observed_at DESC);

CREATE TABLE IF NOT EXISTS ground_mr_identity_relations (
    relation_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL,
    mr_uuid TEXT NOT NULL,
    train_id TEXT NOT NULL DEFAULT '',
    train_no TEXT NOT NULL DEFAULT '',
    mr_role TEXT NOT NULL DEFAULT '',
    management_ip TEXT NOT NULL DEFAULT '',
    identity_mac TEXT NOT NULL,
    alias_type TEXT NOT NULL,
    source TEXT NOT NULL,
    first_discovered_at TEXT NOT NULL,
    last_verified_at TEXT NOT NULL,
    confirmation_status TEXT NOT NULL DEFAULT 'UNCONFIRMED',
    evidence_count INTEGER NOT NULL DEFAULT 1,
    last_collection_id TEXT NOT NULL DEFAULT '',
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(site_id, mr_uuid, identity_mac, alias_type)
);
CREATE INDEX IF NOT EXISTS idx_ground_mr_identity_mac
ON ground_mr_identity_relations(site_id, identity_mac, confirmation_status);
CREATE INDEX IF NOT EXISTS idx_ground_mr_identity_mr
ON ground_mr_identity_relations(site_id, mr_uuid, confirmation_status);

CREATE TABLE IF NOT EXISTS ground_mr_identity_conflicts (
    conflict_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL,
    conflict_key TEXT NOT NULL,
    conflict_type TEXT NOT NULL,
    mr_uuid TEXT NOT NULL DEFAULT '',
    ip_address TEXT NOT NULL DEFAULT '',
    mac_address TEXT NOT NULL DEFAULT '',
    details_json TEXT NOT NULL DEFAULT '{}',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    collection_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'OPEN',
    UNIQUE(site_id, conflict_key)
);
CREATE INDEX IF NOT EXISTS idx_ground_mr_conflicts_open
ON ground_mr_identity_conflicts(site_id, status, last_seen_at DESC);
"""


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


class GroundArpRepository:
    """Durable ARP evidence and MR identity index for one Ground site.

    This repository deliberately has no delete operation for observations or
    identities. A complete collection only changes the current-observation bit
    inside its exact source/query scope; failed collections do not touch it.
    """

    def __init__(self, db_path: Path, *, site_id: str) -> None:
        self.db_path = Path(db_path)
        self.site_id = str(site_id)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def initialize(self) -> None:
        with self._connection() as conn:
            conn.executescript(SCHEMA)

    def save_collection(
        self,
        *,
        source_device_uuid: str,
        source_device_name: str,
        query_mode: str,
        query_scope: str,
        requested_vlans: Iterable[int],
        started_at: str,
        completed_at: str,
        parse_result: ArpParseResult,
        error_message: str = "",
        raw_reference: str = "",
    ) -> dict[str, Any]:
        collection_id = str(uuid.uuid4())
        records = tuple(parse_result.records)
        now = _now()
        status = str(parse_result.status or "FAILED").upper()
        if error_message and status == "SUCCESS":
            status = "FAILED"
        with self._transaction() as conn:
            if parse_result.complete:
                conn.execute(
                    """
                    UPDATE ground_arp_observations
                    SET observed_in_last_success=0,
                        last_collection_success=1,
                        freshness_status='NOT_OBSERVED',
                        updated_at=?
                    WHERE site_id=? AND source_device_uuid=? AND query_scope=?
                    """,
                    (now, self.site_id, str(source_device_uuid), str(query_scope)),
                )
            for record in records:
                self._upsert_observation(
                    conn,
                    source_device_uuid=str(source_device_uuid),
                    source_device_name=str(source_device_name or ""),
                    query_scope=str(query_scope),
                    record=record,
                    collection_id=collection_id,
                    observed_at=completed_at or started_at or now,
                    complete=parse_result.complete,
                )
            conn.execute(
                """
                INSERT INTO ground_arp_collections(
                    collection_id, site_id, source_device_uuid, source_device_name,
                    query_mode, query_scope, requested_vlans_json, started_at,
                    completed_at, status, completeness, record_count,
                    error_message, raw_reference, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    collection_id, self.site_id, str(source_device_uuid),
                    str(source_device_name or ""), str(query_mode), str(query_scope),
                    json.dumps(sorted({int(v) for v in requested_vlans}), ensure_ascii=False),
                    str(started_at or now), str(completed_at or ""), status,
                    str(parse_result.completeness), len(records), str(error_message or ""),
                    str(raw_reference or ""), now,
                ),
            )
        return self.get_collection(collection_id) or {
            "collection_id": collection_id, "status": status,
        }

    def _upsert_observation(
        self,
        conn: sqlite3.Connection,
        *,
        source_device_uuid: str,
        source_device_name: str,
        query_scope: str,
        record: ArpRecord,
        collection_id: str,
        observed_at: str,
        complete: bool,
    ) -> None:
        existing = conn.execute(
            """
            SELECT observation_id, first_observed_at, observation_count
            FROM ground_arp_observations
            WHERE site_id=? AND source_device_uuid=? AND query_scope=?
              AND vlan=? AND ip_address=? AND mac_address=?
            """,
            (self.site_id, source_device_uuid, query_scope, record.vlan,
             record.ip_address, record.mac_address),
        ).fetchone()
        observation_id = str(existing[0]) if existing else str(uuid.uuid4())
        first = str(existing[1]) if existing else observed_at
        count = int(existing[2] or 0) + 1 if existing else 1
        conn.execute(
            """
            INSERT INTO ground_arp_observations(
                observation_id, site_id, source_device_uuid, source_device_name,
                query_scope, vlan, ip_address, mac_address, interface_name, aging,
                entry_type, first_observed_at, last_observed_at, last_collection_id,
                last_success_collection_id, observed_in_last_success,
                last_collection_success, observation_count, freshness_status,
                raw_line, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(site_id, source_device_uuid, query_scope, vlan, ip_address, mac_address)
            DO UPDATE SET
                source_device_name=excluded.source_device_name,
                interface_name=excluded.interface_name,
                aging=excluded.aging,
                entry_type=excluded.entry_type,
                last_observed_at=excluded.last_observed_at,
                last_collection_id=excluded.last_collection_id,
                last_success_collection_id=CASE WHEN excluded.last_collection_success=1
                    THEN excluded.last_success_collection_id ELSE ground_arp_observations.last_success_collection_id END,
                observed_in_last_success=CASE WHEN excluded.last_collection_success=1
                    THEN 1 ELSE ground_arp_observations.observed_in_last_success END,
                last_collection_success=CASE WHEN excluded.last_collection_success=1
                    THEN 1 ELSE ground_arp_observations.last_collection_success END,
                observation_count=ground_arp_observations.observation_count + 1,
                freshness_status=CASE WHEN excluded.last_collection_success=1
                    THEN 'CURRENT' ELSE ground_arp_observations.freshness_status END,
                raw_line=excluded.raw_line,
                updated_at=excluded.updated_at
            """,
            (
                observation_id, self.site_id, source_device_uuid, source_device_name,
                query_scope, record.vlan, record.ip_address, record.mac_address,
                record.interface_name, record.aging, record.entry_type, first,
                observed_at, collection_id, collection_id if complete else "",
                int(complete), int(complete), count, "CURRENT" if complete else "UNKNOWN",
                record.raw_line, _now(), _now(),
            ),
        )

    def get_collection(self, collection_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM ground_arp_collections WHERE collection_id=?",
                (str(collection_id),),
            ).fetchone()
        return dict(row) if row else None

    def update_collection_stats(self, collection_id: str, *, matched_count: int, conflict_count: int) -> None:
        with self._transaction() as conn:
            conn.execute(
                "UPDATE ground_arp_collections SET matched_count=?, conflict_count=? WHERE collection_id=?",
                (max(0, int(matched_count)), max(0, int(conflict_count)), str(collection_id)),
            )

    def list_collections(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM ground_arp_collections WHERE site_id=? ORDER BY started_at DESC LIMIT ?",
                (self.site_id, max(1, min(500, int(limit)))),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_observations(
        self, *, source_device_uuid: str = "", query_scope: str = "", ip_address: str = "", limit: int = 5000
    ) -> list[dict[str, Any]]:
        clauses = ["site_id=?"]
        params: list[object] = [self.site_id]
        for field, value in (("source_device_uuid", source_device_uuid), ("query_scope", query_scope), ("ip_address", ip_address)):
            if value:
                clauses.append(f"{field}=?")
                params.append(str(value))
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM ground_arp_observations WHERE {' AND '.join(clauses)} ORDER BY ip_address, mac_address LIMIT ?",
                [*params, max(1, min(20_000, int(limit)))],
            ).fetchall()
        return [dict(row) for row in rows]

    def save_identity_relation(
        self,
        *,
        mr: Mapping[str, Any],
        identity_mac: str,
        alias_type: str,
        source: str,
        confirmation_status: str,
        management_ip: str = "",
        collection_id: str = "",
        details: Mapping[str, Any] | None = None,
        verified_at: str = "",
    ) -> dict[str, Any]:
        now = verified_at or _now()
        mr_uuid = str(mr.get("mr_uuid") or mr.get("id") or mr.get("device_uuid") or "")
        if not mr_uuid or not identity_mac:
            raise ValueError("MR identity relation requires mr_uuid and identity_mac")
        with self._transaction() as conn:
            current = conn.execute(
                """
                SELECT relation_id, first_discovered_at, evidence_count, confirmation_status
                FROM ground_mr_identity_relations
                WHERE site_id=? AND mr_uuid=? AND identity_mac=? AND alias_type=?
                """,
                (self.site_id, mr_uuid, identity_mac, alias_type),
            ).fetchone()
            relation_id = str(current[0]) if current else str(uuid.uuid4())
            first = str(current[1]) if current else now
            count = int(current[2] or 0) + 1 if current else 1
            old_status = str(current[3] or "") if current else ""
            final_status = "CONFIRMED" if old_status == "CONFIRMED" else str(confirmation_status)
            conn.execute(
                """
                INSERT INTO ground_mr_identity_relations(
                    relation_id, site_id, mr_uuid, train_id, train_no, mr_role,
                    management_ip, identity_mac, alias_type, source,
                    first_discovered_at, last_verified_at, confirmation_status,
                    evidence_count, last_collection_id, details_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(site_id, mr_uuid, identity_mac, alias_type)
                DO UPDATE SET
                    train_id=excluded.train_id, train_no=excluded.train_no,
                    mr_role=excluded.mr_role, management_ip=excluded.management_ip,
                    source=excluded.source, last_verified_at=excluded.last_verified_at,
                    confirmation_status=CASE WHEN ground_mr_identity_relations.confirmation_status='CONFIRMED'
                        THEN 'CONFIRMED' ELSE excluded.confirmation_status END,
                    evidence_count=ground_mr_identity_relations.evidence_count + 1,
                    last_collection_id=excluded.last_collection_id,
                    details_json=excluded.details_json, updated_at=excluded.updated_at
                """,
                (
                    relation_id, self.site_id, mr_uuid, str(mr.get("train_id") or ""),
                    str(mr.get("train_no") or ""), str(mr.get("role") or mr.get("mr_role") or ""),
                    str(management_ip or mr.get("management_ip") or ""), identity_mac,
                    str(alias_type), str(source), first, now, final_status, count,
                    str(collection_id or ""), json.dumps(dict(details or {}), ensure_ascii=False),
                    now, now,
                ),
            )
        return self.find_identity_relations(mr_uuid=mr_uuid)[-1]

    def find_identity_relations(
        self, *, mr_uuid: str = "", identity_mac: str = "", confirmed_only: bool = False
    ) -> list[dict[str, Any]]:
        clauses = ["site_id=?"]
        params: list[object] = [self.site_id]
        if mr_uuid:
            clauses.append("mr_uuid=?")
            params.append(str(mr_uuid))
        if identity_mac:
            clauses.append("identity_mac=?")
            params.append(str(identity_mac))
        if confirmed_only:
            clauses.append("confirmation_status='CONFIRMED'")
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM ground_mr_identity_relations WHERE {' AND '.join(clauses)} ORDER BY last_verified_at DESC",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def find_confirmed_by_mac_readonly(
        db_path: Path, *, site_id: str, identity_mac: str
    ) -> list[dict[str, Any]]:
        """Read confirmed identity evidence without initializing or mutating the DB.

        AC/Mesh-Link query paths are read-only. They must not create the Ground
        database merely because a site has not started ARP collection yet.
        """
        path = Path(db_path)
        if not path.is_file() or not identity_mac:
            return []
        uri = f"{path.resolve().as_uri()}?mode=ro"
        try:
            with sqlite3.connect(uri, uri=True) as conn:
                conn.row_factory = sqlite3.Row
                table = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    ("ground_mr_identity_relations",),
                ).fetchone()
                if table is None:
                    return []
                rows = conn.execute(
                    """
                    SELECT * FROM ground_mr_identity_relations
                    WHERE site_id=? AND identity_mac=? AND confirmation_status='CONFIRMED'
                    ORDER BY last_verified_at DESC
                    """,
                    (str(site_id), str(identity_mac)),
                ).fetchall()
        except sqlite3.Error:
            return []
        return [dict(row) for row in rows]

    def save_conflict(
        self, *, conflict_type: str, conflict_key: str, details: Mapping[str, Any],
        mr_uuid: str = "", ip_address: str = "", mac_address: str = "", collection_id: str = ""
    ) -> dict[str, Any]:
        now = _now()
        with self._transaction() as conn:
            conn.execute(
                """
                INSERT INTO ground_mr_identity_conflicts(
                    conflict_id, site_id, conflict_key, conflict_type, mr_uuid,
                    ip_address, mac_address, details_json, first_seen_at, last_seen_at,
                    collection_id, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
                ON CONFLICT(site_id, conflict_key)
                DO UPDATE SET last_seen_at=excluded.last_seen_at,
                    collection_id=excluded.collection_id, details_json=excluded.details_json,
                    status='OPEN'
                """,
                (
                    str(uuid.uuid4()), self.site_id, str(conflict_key), str(conflict_type),
                    str(mr_uuid), str(ip_address), str(mac_address),
                    json.dumps(dict(details), ensure_ascii=False), now, now,
                    str(collection_id or ""),
                ),
            )
            row = conn.execute(
                "SELECT * FROM ground_mr_identity_conflicts WHERE site_id=? AND conflict_key=?",
                (self.site_id, str(conflict_key)),
            ).fetchone()
        return dict(row) if row else {}

    def list_conflicts(self, *, status: str = "OPEN") -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM ground_mr_identity_conflicts WHERE site_id=? AND (?='' OR status=?) ORDER BY last_seen_at DESC",
                (self.site_id, status, status),
            ).fetchall()
        return [dict(row) for row in rows]

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = Database(self.db_path).connect()
        configure_sqlite_connection(conn, busy_timeout_ms=10_000, foreign_keys=True, temp_store_memory=True)
        initialize_sqlite_wal(conn)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except Exception:
                conn.rollback()
                raise


__all__ = ["GroundArpRepository"]
