"""在数据库副本上回填轨道基础资料的稳定 ID 与物理关联字段。

默认 dry-run；apply 必须同时给出副本当前哈希和显式确认。脚本只采用唯一的
正式站点/区间候选，不通过相似名称、设备名、IP 或系统名猜测关系。
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from netconsole.services.ap_identity.normalizers import normalize_mac


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="回填轨旁 AP station_id（默认 dry-run）")
    parser.add_argument("--database-copy", required=True, help="只读验证或受控 apply 使用的 SQLite 副本路径")
    parser.add_argument("--site", default="", help="限定 site_id")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="只输出候选，不写库（默认）")
    mode.add_argument("--apply", action="store_true", help="在副本上应用安全回填")
    parser.add_argument(
        "--confirm",
        default="",
        help="apply 时必须填写 APPLY_RAIL_BASE_IDENTITY_BACKFILL",
    )
    parser.add_argument("--json-output", default="", help="将报告写入 JSON 文件")
    parser.add_argument("--revision-hash", default="", help="apply 前要求数据库序列化哈希等于该值")
    return parser.parse_args()


def _db_hash(conn: sqlite3.Connection) -> str:
    try:
        return hashlib.sha256(conn.serialize()).hexdigest()
    except AttributeError:
        rows = conn.execute(
            "SELECT id, site_id, ap_mac_norm, station_name, raw_payload_json, updated_at "
            "FROM ap_extension_points ORDER BY id"
        ).fetchall()
        return hashlib.sha256(
            json.dumps([tuple(row) for row in rows], ensure_ascii=False, default=str).encode("utf-8")
        ).hexdigest()


def _metadata(value: object) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _station_id(site: str, row_id: object, node_uid: str) -> str:
    seed = node_uid.strip()
    if not seed:
        seed = str(
            uuid5(
                NAMESPACE_URL,
                f"netconsole:{site}:station:ap:{str(row_id or '').strip()}",
            )
        )
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
    return f"station:{digest}"


def _online(state: object) -> bool:
    return str(state or "").strip().casefold() in {"run", "online", "up", "active", "正常", "在线"}


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")')}


def build_report(
    database: Path,
    site: str,
    *,
    apply: bool,
    expected_hash: str = "",
    confirmed: bool = False,
) -> dict[str, Any]:
    if not database.is_file() or database.is_symlink():
        raise SystemExit(f"数据库副本不存在或为符号链接：{database}")
    conn = sqlite3.connect(str(database))
    conn.row_factory = sqlite3.Row
    try:
        tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "ap_extension_points" not in tables:
            raise SystemExit("数据库缺少 ap_extension_points 表")
        if apply and not expected_hash:
            raise SystemExit("apply 必须提供 dry-run 报告中的 revision/hash")
        if apply and not confirmed:
            raise SystemExit("apply 必须显式确认 APPLY_RAIL_BASE_IDENTITY_BACKFILL")
        before_hash = _db_hash(conn)
        if expected_hash and expected_hash != before_hash:
            raise SystemExit(f"revision/hash 不匹配：expected={expected_hash} actual={before_hash}")

        station_site_clause = " AND site_id = ?" if site else ""
        ap_columns = _columns(conn, "ap_extension_points")
        station_rows = conn.execute(
            "SELECT * FROM ap_extension_points "
            f"WHERE belong_type = '__base_station__'{station_site_clause} ORDER BY id",
            (site,) if site else (),
        ).fetchall()
        stations: dict[str, set[str]] = defaultdict(set)
        station_display: dict[str, str] = {}
        station_master_candidates: list[dict[str, Any]] = []
        for row in station_rows:
            metadata = _metadata(row["raw_payload_json"])
            name = str(row["station_name"] or "").strip()
            key = name
            node_uid = str(metadata.get("node_uid") or "").strip()
            row_site = str(row["site_id"] or site).strip()
            sid = (
                str(row["station_id"] or "").strip()
                if "station_id" in ap_columns
                else str(metadata.get("station_id") or "").strip()
            ) or _station_id(row_site, row["id"], node_uid)
            if key:
                stations[key.casefold()].add(sid)
                station_display.setdefault(sid, name)
            if "station_id" in ap_columns and not str(row["station_id"] or "").strip():
                station_master_candidates.append(
                    {
                        "entity_type": "station_master",
                        "id": int(row["id"]),
                        "station_id": sid,
                        "station_name": name,
                        "source": "BASE_STATION_MASTER",
                    }
                )

        sections: dict[str, set[str]] = defaultdict(set)
        section_master_candidates: list[dict[str, Any]] = []
        section_rows = conn.execute(
            "SELECT * FROM ap_extension_points "
            f"WHERE belong_type = '__base_section__'{station_site_clause} ORDER BY id",
            (site,) if site else (),
        ).fetchall()
        for row in section_rows:
            metadata = _metadata(row["raw_payload_json"])
            name = (
                str(row["section_name"] or "").strip()
                if "section_name" in ap_columns
                else ""
            )
            identity = str(metadata.get("generation_key") or f"ap:{row['id']}")
            sid = (
                str(row["section_id"] or "").strip()
                if "section_id" in ap_columns
                else str(metadata.get("section_id") or "").strip()
            ) or f"section:{hashlib.sha1(identity.encode('utf-8')).hexdigest()[:12]}"
            if name:
                sections[name.casefold()].add(sid)
            if "section_id" in ap_columns and not str(row["section_id"] or "").strip():
                section_master_candidates.append(
                    {
                        "entity_type": "section_master",
                        "id": int(row["id"]),
                        "section_id": sid,
                        "section_name": name,
                        "source": "BASE_SECTION_MASTER",
                    }
                )

        site_clause = " AND site_id = ?" if site else ""
        rows = conn.execute(
            "SELECT * FROM ap_extension_points "
            "WHERE COALESCE(belong_type, '') NOT IN ('__base_station__', '__base_section__') "
            f"{site_clause} ORDER BY id",
            (site,) if site else (),
        ).fetchall()
        resources = []
        if "ac_fit_ap_resources" in tables:
            resources = conn.execute(
                "SELECT ap_mac, state, site FROM ac_fit_ap_resources"
            ).fetchall()
        resource_by_mac: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for resource in resources:
            mac = normalize_mac(resource["ap_mac"])
            if mac:
                resource_by_mac[mac].append(resource)

        counts = Counter(
            {
                "invalid_mac": 0,
                "valid_mac": 0,
                "duplicate_mac": 0,
                "total_trackside_ap": 0,
                "current_lldp_hits": 0,
                "historical_lldp_hits": 0,
                "lldp_station_suggestion_count": 0,
                "switch_ap_station_conflict_count": 0,
                "base_data_mac_hits": 0,
                "station_id_existing": 0,
                "station_master_backfill": len(station_master_candidates),
                "section_master_backfill": len(section_master_candidates),
                "ap_section_id_existing": 0,
                "safe_section_backfill": 0,
                "device_binding_existing": 0,
                "safe_device_binding_backfill": 0,
                "plan_station_id_existing": 0,
                "safe_plan_backfill": 0,
                "safe_backfill": 0,
                "ambiguous": 0,
                "unresolved": 0,
                "online_before": 0,
                "online_after": 0,
            }
        )
        candidates: list[dict[str, Any]] = [
            *station_master_candidates,
            *section_master_candidates,
        ]
        duplicate_macs: set[str] = set()
        mac_rows: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for row in rows:
            metadata = _metadata(row["raw_payload_json"])
            mac = normalize_mac(row["ap_mac_norm"] or row["ap_mac_display"])
            if not mac:
                counts["invalid_mac"] += 1
            else:
                counts["valid_mac"] += 1
                mac_rows[mac].append(row)
            current = (
                str(row["station_id"] or "").strip()
                if "station_id" in ap_columns
                else str(metadata.get("station_id") or "").strip()
            )
            if current:
                counts["station_id_existing"] += 1
            station_text = str(row["station_name"] or "").strip()
            ap_candidate: dict[str, Any] = {
                "entity_type": "trackside_ap",
                "id": int(row["id"]),
                "mac": mac,
                "source": "EXACT_BASE_DATA_DISPLAY_NAME",
            }
            if not current:
                key = station_text
                station_candidates = stations.get(key.casefold(), set()) if key else set()
                if len(station_candidates) == 1:
                    sid = next(iter(station_candidates))
                    ap_candidate.update(
                        station_id=sid,
                        station_name=station_display.get(sid, station_text),
                    )
                    counts["safe_backfill"] += 1
                elif len(station_candidates) > 1:
                    counts["ambiguous"] += 1
                else:
                    counts["unresolved"] += 1
            current_section = (
                str(row["section_id"] or "").strip()
                if "section_id" in ap_columns
                else str(metadata.get("section_id") or "").strip()
            )
            if current_section:
                counts["ap_section_id_existing"] += 1
            else:
                section_name = (
                    str(row["section_name"] or "").strip()
                    if "section_name" in ap_columns
                    else ""
                )
                section_candidates = sections.get(section_name.casefold(), set()) if section_name else set()
                if len(section_candidates) == 1:
                    ap_candidate.update(
                        section_id=next(iter(section_candidates)),
                        section_name=section_name,
                    )
                    counts["safe_section_backfill"] += 1
                elif len(section_candidates) > 1:
                    counts["ambiguous"] += 1
                elif section_name:
                    counts["unresolved"] += 1
            if ap_candidate.get("station_id") or ap_candidate.get("section_id"):
                candidates.append(ap_candidate)

        for mac, matching in mac_rows.items():
            if len(matching) > 1:
                duplicate_macs.add(mac)
        counts["duplicate_mac"] = len(duplicate_macs)
        if duplicate_macs:
            duplicate_candidates = [
                item
                for item in candidates
                if item.get("entity_type") == "trackside_ap"
                and item.get("mac") in duplicate_macs
            ]
            if duplicate_candidates:
                candidates = [
                    item
                    for item in candidates
                    if item.get("entity_type") != "trackside_ap"
                    or item.get("mac") not in duplicate_macs
                ]
                counts["safe_backfill"] -= sum(
                    bool(item.get("station_id")) for item in duplicate_candidates
                )
                counts["safe_section_backfill"] -= sum(
                    bool(item.get("section_id")) for item in duplicate_candidates
                )
                counts["ambiguous"] += len(duplicate_candidates)

        if "devices" in tables:
            device_columns = _columns(conn, "devices")
            if {"station", "station_id"} <= device_columns:
                device_id_column = (
                    "device_uuid" if "device_uuid" in device_columns else "id"
                )
                for row in conn.execute(
                    f"SELECT {device_id_column}, station, station_id FROM devices ORDER BY {device_id_column}"
                ).fetchall():
                    if str(row["station_id"] or "").strip():
                        counts["device_binding_existing"] += 1
                        continue
                    station_name = str(row["station"] or "").strip()
                    matches = stations.get(station_name.casefold(), set()) if station_name else set()
                    if len(matches) == 1:
                        candidates.append(
                            {
                                "entity_type": "device_station_binding",
                                "id": str(row[device_id_column]),
                                "id_column": device_id_column,
                                "station_id": next(iter(matches)),
                                "station_name": station_name,
                                "source": "EXACT_DEVICE_STATION_FIELD",
                            }
                        )
                        counts["safe_device_binding_backfill"] += 1
                    elif len(matches) > 1:
                        counts["ambiguous"] += 1
                    elif station_name:
                        counts["unresolved"] += 1

        if "ac_trackside_ap_plan" in tables:
            plan_columns = _columns(conn, "ac_trackside_ap_plan")
            if {"id", "station_name", "station_id"} <= plan_columns:
                plan_site_clause = " AND site_id = ?" if site and "site_id" in plan_columns else ""
                for row in conn.execute(
                    "SELECT id, station_name, station_id FROM ac_trackside_ap_plan "
                    f"WHERE 1 = 1{plan_site_clause} ORDER BY id",
                    (site,) if plan_site_clause else (),
                ).fetchall():
                    if str(row["station_id"] or "").strip():
                        counts["plan_station_id_existing"] += 1
                        continue
                    station_name = str(row["station_name"] or "").strip()
                    matches = stations.get(station_name.casefold(), set()) if station_name else set()
                    if len(matches) == 1:
                        candidates.append(
                            {
                                "entity_type": "trackside_ap_plan",
                                "id": int(row["id"]),
                                "station_id": next(iter(matches)),
                                "station_name": station_name,
                                "source": "EXACT_PLAN_STATION_NAME",
                            }
                        )
                        counts["safe_plan_backfill"] += 1
                    elif len(matches) > 1:
                        counts["ambiguous"] += 1
                    elif station_name:
                        counts["unresolved"] += 1
        counts["total_trackside_ap"] = len(rows)
        current_lldp_macs, historical_lldp_macs = _lldp_hit_macs(
            conn,
            tables,
            set(mac_rows),
        )
        counts["current_lldp_hits"] = len(current_lldp_macs)
        counts["historical_lldp_hits"] = len(historical_lldp_macs - current_lldp_macs)
        lldp_station_evidence = _device_lldp_station_evidence(
            conn,
            tables,
            rows,
            ap_columns,
            station_display,
        )
        counts["lldp_station_suggestion_count"] = sum(
            item["status"] == "SUGGESTED" for item in lldp_station_evidence
        )
        counts["switch_ap_station_conflict_count"] = sum(
            item["status"] == "CONFLICT" for item in lldp_station_evidence
        )
        counts["base_data_mac_hits"] = sum(1 for mac in mac_rows if mac in resource_by_mac)
        before_station_ids = sum(
            1
            for row in rows
            if (
                str(row["station_id"] or "").strip()
                if "station_id" in ap_columns
                else str(_metadata(row["raw_payload_json"]).get("station_id") or "").strip()
            )
        )
        before_online_macs: set[str] = set()
        after_online_macs: set[str] = set()
        for resource in resources:
            mac = normalize_mac(resource["ap_mac"])
            if not mac or not _online(resource["state"]) or mac not in mac_rows:
                continue
            after_online_macs.add(mac)
            if any(
                (
                    str(row["station_id"] or "").strip()
                    if "station_id" in ap_columns
                    else str(_metadata(row["raw_payload_json"]).get("station_id") or "").strip()
                )
                for row in mac_rows[mac]
            ):
                before_online_macs.add(mac)
        counts["online_before"] = len(before_online_macs)
        counts["online_after"] = len(after_online_macs)

        applied = 0
        applied_by_type: Counter[str] = Counter()
        audit_id = str(uuid4())
        if apply and candidates:
            # Re-check the hash inside the write transaction before touching rows.
            conn.execute("BEGIN IMMEDIATE")
            if _db_hash(conn) != before_hash:
                conn.rollback()
                raise SystemExit("apply 前数据库 revision/hash 已变化，已取消")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trackside_ap_station_backfill_audit (
                    run_id TEXT PRIMARY KEY,
                    site_id TEXT NOT NULL DEFAULT '',
                    before_hash TEXT NOT NULL,
                    after_hash TEXT NOT NULL DEFAULT '',
                    applied_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                """
            )
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            for item in candidates:
                entity_type = str(item.get("entity_type") or "trackside_ap")
                if entity_type == "station_master":
                    cursor = conn.execute(
                        """
                        UPDATE ap_extension_points SET station_id = ?, updated_at = ?
                        WHERE id = ? AND TRIM(COALESCE(station_id, '')) = ''
                        """,
                        (item["station_id"], now, item["id"]),
                    )
                elif entity_type == "section_master":
                    cursor = conn.execute(
                        """
                        UPDATE ap_extension_points SET section_id = ?, updated_at = ?
                        WHERE id = ? AND TRIM(COALESCE(section_id, '')) = ''
                        """,
                        (item["section_id"], now, item["id"]),
                    )
                elif entity_type == "device_station_binding":
                    id_column = str(item["id_column"])
                    if id_column not in {"id", "device_uuid"}:
                        raise SystemExit("设备绑定主键字段不受支持")
                    cursor = conn.execute(
                        f"UPDATE devices SET station_id = ?, updated_at = ? WHERE {id_column} = ? AND TRIM(COALESCE(station_id, '')) = ''",
                        (item["station_id"], now, item["id"]),
                    )
                elif entity_type == "trackside_ap_plan":
                    cursor = conn.execute(
                        """
                        UPDATE ac_trackside_ap_plan SET station_id = ?, updated_at = ?
                        WHERE id = ? AND TRIM(COALESCE(station_id, '')) = ''
                        """,
                        (item["station_id"], now, item["id"]),
                    )
                elif "station_id" in ap_columns or "section_id" in ap_columns:
                    assignments: list[str] = []
                    values: list[object] = []
                    if item.get("station_id") and "station_id" in ap_columns:
                        assignments.append("station_id = CASE WHEN TRIM(COALESCE(station_id, '')) = '' THEN ? ELSE station_id END")
                        values.append(item["station_id"])
                    if item.get("section_id") and "section_id" in ap_columns:
                        assignments.append("section_id = CASE WHEN TRIM(COALESCE(section_id, '')) = '' THEN ? ELSE section_id END")
                        values.append(item["section_id"])
                    assignments.append("updated_at = ?")
                    values.extend((now, item["id"]))
                    cursor = conn.execute(
                        f"UPDATE ap_extension_points SET {', '.join(assignments)} WHERE id = ?",
                        values,
                    )
                else:
                    row = conn.execute(
                        "SELECT raw_payload_json FROM ap_extension_points WHERE id = ?",
                        (item["id"],),
                    ).fetchone()
                    metadata = _metadata(row["raw_payload_json"] if row else "")
                    changed = False
                    for field in ("station_id", "section_id"):
                        if item.get(field) and not metadata.get(field):
                            metadata[field] = item[field]
                            changed = True
                    if item.get("station_name"):
                        metadata.setdefault("station_name", item["station_name"])
                    cursor = conn.execute(
                        "UPDATE ap_extension_points SET raw_payload_json = ?, updated_at = ? WHERE id = ?",
                        (json.dumps(metadata, ensure_ascii=False, sort_keys=True), now, item["id"]),
                    ) if changed else None
                changed_count = int(bool(cursor and cursor.rowcount))
                applied += changed_count
                if changed_count:
                    applied_by_type[entity_type] += 1
            after_hash = _db_hash(conn)
            conn.execute(
                "INSERT INTO trackside_ap_station_backfill_audit "
                "(run_id, site_id, before_hash, after_hash, applied_count, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (audit_id, site, before_hash, after_hash, applied, now),
            )
            conn.commit()
        else:
            after_hash = before_hash

        return {
            "database_copy": str(database),
            "site": site,
            "mode": "apply" if apply else "dry-run",
            "run_id": audit_id,
            "before_hash": before_hash,
            "after_hash": after_hash,
            "counts": {
                **dict(counts),
                "station_id_before": before_station_ids,
                "station_id_after": before_station_ids
                + sum(
                    1
                    for item in candidates
                    if item.get("entity_type") == "trackside_ap"
                    and item.get("station_id")
                )
                if apply
                else before_station_ids,
                "safe_backfill_applied": applied_by_type["trackside_ap"],
                "total_applied": applied,
                "station_master_applied": applied_by_type["station_master"],
                "section_master_applied": applied_by_type["section_master"],
                "device_binding_applied": applied_by_type["device_station_binding"],
                "plan_station_id_applied": applied_by_type["trackside_ap_plan"],
                "online_before": len(before_online_macs),
                "online_after": len(after_online_macs),
            },
            "candidates": candidates,
            "lldp_station_evidence": lldp_station_evidence,
        }
    finally:
        conn.close()


def _lldp_hit_macs(
    conn: sqlite3.Connection,
    tables: set[str],
    known_macs: set[str],
) -> tuple[set[str], set[str]]:
    """Return unique AP MACs evidenced by current and historical LLDP rows."""

    current: set[str] = set()
    historical: set[str] = set()
    if "ac_fit_ap_resources" in tables:
        columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(ac_fit_ap_resources)")
        }
        selected = [
            field
            for field in (
                "ap_mac",
                "lldp_neighbor_mac_normalized",
                "lldp_neighbor_mac",
                "neighbor_mac",
                "lldp_source",
            )
            if field in columns
        ]
        if selected:
            rows = conn.execute(
                f"SELECT {', '.join(selected)} FROM ac_fit_ap_resources"
            ).fetchall()
            for row in rows:
                source = str(row["lldp_source"] or "").casefold() if "lldp_source" in columns else ""
                lldp_values = [
                    row[field]
                    for field in (
                        "lldp_neighbor_mac_normalized",
                        "lldp_neighbor_mac",
                        "neighbor_mac",
                    )
                    if field in columns
                ]
                if not source and not any(str(value or "").strip() for value in lldp_values):
                    continue
                mac = next(
                    (
                        normalized
                        for value in row
                        if (normalized := normalize_mac(value)) in known_macs
                    ),
                    "",
                )
                if not mac:
                    continue
                if source and any(token in source for token in ("history", "historical", "previous")):
                    historical.add(mac)
                else:
                    current.add(mac)

    for table in ("ac_fit_ap_lldp_history", "ap_lldp_history"):
        if table not in tables:
            continue
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        for row in rows:
            mac = next(
                (
                    normalized
                    for value in row
                    if (normalized := normalize_mac(value)) in known_macs
                ),
                "",
            )
            if mac:
                historical.add(mac)
    return current, historical


def _device_lldp_station_evidence(
    conn: sqlite3.Connection,
    tables: set[str],
    ap_rows: list[sqlite3.Row],
    ap_columns: set[str],
    station_display: dict[str, str],
) -> list[dict[str, Any]]:
    """Audit exact current LLDP observations without turning them into writes."""

    if not {"device_lldp_neighbors", "devices"} <= tables:
        return []
    device_columns = _columns(conn, "devices")
    lldp_columns = _columns(conn, "device_lldp_neighbors")
    if not {"device_uuid", "station_id"} <= device_columns or not {
        "device_uuid",
        "local_interface",
        "neighbor_mac",
    } <= lldp_columns:
        return []

    ap_by_id = {str(row["id"]): row for row in ap_rows}
    ap_ids_by_alias: dict[str, set[str]] = defaultdict(set)
    for ap_id, row in ap_by_id.items():
        mac = normalize_mac(row["ap_mac_norm"] or row["ap_mac_display"])
        if mac:
            ap_ids_by_alias[mac].add(ap_id)
    if {"ap_identity_entities", "ap_identity_mac_aliases"} <= tables:
        for row in conn.execute(
            """
            SELECT a.mac_key, e.base_record_id
            FROM ap_identity_mac_aliases AS a
            JOIN ap_identity_entities AS e ON e.entity_id = a.entity_id
            WHERE a.is_active = 1 AND a.is_exact = 1
              AND TRIM(COALESCE(e.base_record_id, '')) != ''
            """
        ).fetchall():
            ap_id = str(row["base_record_id"] or "")
            mac = normalize_mac(row["mac_key"])
            if ap_id in ap_by_id and mac:
                ap_ids_by_alias[mac].add(ap_id)

    selected_fields = [
        "n.device_uuid",
        "n.local_interface",
        "n.neighbor_mac",
        "d.station_id",
    ]
    selected_fields.append(
        "n.collected_at" if "collected_at" in lldp_columns else "'' AS collected_at"
    )
    selected_fields.append("d.name AS switch_name" if "name" in device_columns else "'' AS switch_name")
    selected_fields.append("d.station AS station_name" if "station" in device_columns else "'' AS station_name")
    rows = conn.execute(
        f"""
        SELECT {', '.join(selected_fields)}
        FROM device_lldp_neighbors AS n
        JOIN devices AS d ON d.device_uuid = n.device_uuid
        WHERE TRIM(COALESCE(n.neighbor_mac, '')) != ''
          AND TRIM(COALESCE(d.station_id, '')) != ''
        ORDER BY collected_at DESC, n.device_uuid, n.local_interface
        """
    ).fetchall()
    evidence: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for row in rows:
        neighbor_mac = normalize_mac(row["neighbor_mac"])
        matched_ap_ids = ap_ids_by_alias.get(neighbor_mac, set())
        if len(matched_ap_ids) != 1:
            continue
        ap_id = next(iter(matched_ap_ids))
        ap = ap_by_id[ap_id]
        ap_metadata = _metadata(ap["raw_payload_json"])
        ap_station_id = (
            str(ap["station_id"] or "").strip()
            if "station_id" in ap_columns
            else str(ap_metadata.get("station_id") or "").strip()
        )
        switch_station_id = str(row["station_id"] or "").strip()
        key = (
            ap_id,
            str(row["device_uuid"] or ""),
            str(row["local_interface"] or ""),
            switch_station_id,
        )
        if key in seen:
            continue
        seen.add(key)
        status = (
            "SUGGESTED"
            if not ap_station_id
            else "CONSISTENT"
            if ap_station_id == switch_station_id
            else "CONFLICT"
        )
        evidence.append(
            {
                "trackside_ap_id": int(ap_id),
                "ap_mac": neighbor_mac,
                "ap_station_id": ap_station_id,
                "switch_station_id": switch_station_id,
                "switch_station_name": station_display.get(
                    switch_station_id,
                    str(row["station_name"] or ""),
                ),
                "switch_device_id": str(row["device_uuid"] or ""),
                "switch_name": str(row["switch_name"] or ""),
                "interface": str(row["local_interface"] or ""),
                "observed_at": str(row["collected_at"] or ""),
                "status": status,
            }
        )
    return evidence


def _human_report(report: dict[str, Any]) -> str:
    counts = report.get("counts") if isinstance(report.get("counts"), dict) else {}
    evidence = report.get("lldp_station_evidence")
    evidence_count = len(evidence) if isinstance(evidence, list) else 0
    return "\n".join(
        [
            "轨旁 AP 稳定关系回填报告",
            f"模式：{report.get('mode', '')}",
            f"数据库副本：{report.get('database_copy', '')}",
            f"执行前哈希：{report.get('before_hash', '')}",
            (
                "主记录候选："
                f"站点 {counts.get('station_master_backfill', 0)}，"
                f"区间 {counts.get('section_master_backfill', 0)}"
            ),
            (
                "关系候选："
                f"设备 {counts.get('safe_device_binding_backfill', 0)}，"
                f"AP 站点 {counts.get('safe_backfill', 0)}，"
                f"AP 区间 {counts.get('safe_section_backfill', 0)}，"
                f"规划 {counts.get('safe_plan_backfill', 0)}"
            ),
            (
                "待复核："
                f"歧义 {counts.get('ambiguous', 0)}，"
                f"未解析 {counts.get('unresolved', 0)}，"
                f"LLDP 证据 {evidence_count}，"
                f"交换机/AP 站点冲突 {counts.get('switch_ap_station_conflict_count', 0)}"
            ),
            f"本次实际写入：{counts.get('total_applied', 0)}",
        ]
    )


def main() -> int:
    args = _args()
    report = build_report(
        Path(args.database_copy).resolve(),
        str(args.site or "").strip(),
        apply=bool(args.apply),
        expected_hash=str(args.revision_hash or "").strip(),
        confirmed=(
            str(args.confirm or "").strip()
            == "APPLY_RAIL_BASE_IDENTITY_BACKFILL"
        ),
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_output:
        Path(args.json_output).resolve().write_text(payload + "\n", encoding="utf-8")
    print(_human_report(report), file=sys.stderr)
    print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
