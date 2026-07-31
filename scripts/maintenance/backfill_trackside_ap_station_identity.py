"""为轨旁 AP 基础资料回填稳定 station_id。

脚本默认只读 dry-run。station_id 目前属于基础资料派生 metadata，
因此回填不会引入第二张 AP 主表或修改 AP 名称身份。
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
from netconsole.services.rail_transit.station_source_utils import canonical_station_name
from netconsole.utils.station_normalize import normalize_station_value


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="回填轨旁 AP station_id（默认 dry-run）")
    parser.add_argument("--database-copy", required=True, help="只读验证或受控 apply 使用的 SQLite 副本路径")
    parser.add_argument("--site", default="", help="限定 site_id")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="只输出候选，不写库（默认）")
    mode.add_argument("--apply", action="store_true", help="在副本上应用安全回填")
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


def build_report(database: Path, site: str, *, apply: bool, expected_hash: str = "") -> dict[str, Any]:
    if not database.is_file() or database.is_symlink():
        raise SystemExit(f"数据库副本不存在或为符号链接：{database}")
    conn = sqlite3.connect(str(database))
    conn.row_factory = sqlite3.Row
    try:
        tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "ap_extension_points" not in tables:
            raise SystemExit("数据库缺少 ap_extension_points 表")
        before_hash = _db_hash(conn)
        if expected_hash and expected_hash != before_hash:
            raise SystemExit(f"revision/hash 不匹配：expected={expected_hash} actual={before_hash}")

        station_site_clause = " AND site_id = ?" if site else ""
        station_rows = conn.execute(
            "SELECT id, station_name, raw_payload_json FROM ap_extension_points "
            f"WHERE belong_type = '__base_station__'{station_site_clause} ORDER BY id",
            (site,) if site else (),
        ).fetchall()
        stations: dict[str, set[str]] = defaultdict(set)
        station_display: dict[str, str] = {}
        for row in station_rows:
            metadata = _metadata(row["raw_payload_json"])
            name = str(row["station_name"] or "").strip()
            key = canonical_station_name(name) or normalize_station_value({"station": name}) or name
            node_uid = str(metadata.get("node_uid") or "").strip()
            sid = _station_id(site, row["id"], node_uid)
            if key:
                stations[key.casefold()].add(sid)
                station_display.setdefault(sid, name)

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
                "base_data_mac_hits": 0,
                "station_id_existing": 0,
                "safe_backfill": 0,
                "ambiguous": 0,
                "unresolved": 0,
                "online_before": 0,
                "online_after": 0,
            }
        )
        candidates: list[dict[str, Any]] = []
        duplicate_macs: set[str] = set()
        mac_rows: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for row in rows:
            metadata = _metadata(row["raw_payload_json"])
            mac = normalize_mac(row["ap_mac_norm"] or row["ap_mac_display"])
            if not mac:
                counts["invalid_mac"] += 1
                continue
            counts["valid_mac"] += 1
            mac_rows[mac].append(row)
            current = str(metadata.get("station_id") or "").strip()
            if current:
                counts["station_id_existing"] += 1
                continue
            station_text = str(
                row["station_name"]
                or metadata.get("station_name")
                or metadata.get("belong_station")
                or ""
            ).strip()
            key = canonical_station_name(station_text) or normalize_station_value({"station": station_text}) or station_text
            station_candidates = stations.get(key.casefold(), set()) if key else set()
            if len(station_candidates) == 1:
                sid = next(iter(station_candidates))
                candidates.append(
                    {
                        "id": int(row["id"]),
                        "mac": mac,
                        "station_id": sid,
                        "station_name": station_display.get(sid, station_text),
                        "source": "BASE_DATA_STATION_NAME",
                    }
                )
                counts["safe_backfill"] += 1
            elif len(station_candidates) > 1:
                counts["ambiguous"] += 1
            else:
                counts["unresolved"] += 1

        for mac, matching in mac_rows.items():
            if len(matching) > 1:
                duplicate_macs.add(mac)
        counts["duplicate_mac"] = len(duplicate_macs)
        if duplicate_macs:
            duplicate_candidates = [item for item in candidates if item["mac"] in duplicate_macs]
            if duplicate_candidates:
                candidates = [
                    item for item in candidates if item["mac"] not in duplicate_macs
                ]
                counts["safe_backfill"] -= len(duplicate_candidates)
                counts["ambiguous"] += len(duplicate_candidates)
        counts["total_trackside_ap"] = len(rows)
        current_lldp_macs, historical_lldp_macs = _lldp_hit_macs(
            conn,
            tables,
            set(mac_rows),
        )
        counts["current_lldp_hits"] = len(current_lldp_macs)
        counts["historical_lldp_hits"] = len(historical_lldp_macs - current_lldp_macs)
        counts["base_data_mac_hits"] = sum(1 for mac in mac_rows if mac in resource_by_mac)
        before_station_ids = sum(1 for row in rows if _metadata(row["raw_payload_json"]).get("station_id"))
        before_online_macs: set[str] = set()
        after_online_macs: set[str] = set()
        for resource in resources:
            mac = normalize_mac(resource["ap_mac"])
            if not mac or not _online(resource["state"]) or mac not in mac_rows:
                continue
            after_online_macs.add(mac)
            if any(
                str(_metadata(row["raw_payload_json"]).get("station_id") or "").strip()
                for row in mac_rows[mac]
            ):
                before_online_macs.add(mac)
        counts["online_before"] = len(before_online_macs)
        counts["online_after"] = len(after_online_macs)

        applied = 0
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
                row = conn.execute(
                    "SELECT raw_payload_json FROM ap_extension_points WHERE id = ?",
                    (item["id"],),
                ).fetchone()
                metadata = _metadata(row["raw_payload_json"] if row else "")
                if metadata.get("station_id"):
                    continue
                metadata["station_id"] = item["station_id"]
                metadata.setdefault("station_name", item["station_name"])
                conn.execute(
                    "UPDATE ap_extension_points SET raw_payload_json = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(metadata, ensure_ascii=False, sort_keys=True), now, item["id"]),
                )
                applied += 1
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
                "station_id_after": before_station_ids + applied,
                "safe_backfill_applied": applied,
                "online_before": len(before_online_macs),
                "online_after": len(after_online_macs),
            },
            "candidates": candidates,
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


def main() -> int:
    args = _args()
    report = build_report(
        Path(args.database_copy).resolve(),
        str(args.site or "").strip(),
        apply=bool(args.apply),
        expected_hash=str(args.revision_hash or "").strip(),
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_output:
        Path(args.json_output).resolve().write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
