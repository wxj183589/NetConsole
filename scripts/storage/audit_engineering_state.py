"""Read-only inventory for engineering-state storage in NetConsoleData-dev."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import zlib
from contextlib import closing
from pathlib import Path
from typing import Any


TARGET_TABLES = (
    "device_facts_history",
    "device_interfaces_history",
    "device_optical_modules_history",
    "device_lldp_neighbors_history",
    "ac_fit_ap_resource_history",
    "ac_fit_ap_radio_history",
    "ac_fit_ap_lldp_history",
    "ac_fit_ap_optical_history",
    "ac_fit_ap_unauthenticated_history",
    "ap_lldp_history",
    "ap_optical_history",
)

KIND_CATEGORY = {
    "device_lldp": "LLDP",
    "fit_ap_lldp": "LLDP",
    "device_interface": "Interface",
    "fit_ap_radio": "Radio",
    "device_optical": "Optical",
    "fit_ap_optical": "Optical",
}


def _read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }


def _decode_v2(row: sqlite3.Row) -> dict[str, Any]:
    raw = bytes(row["payload"])
    if int(row["payload_codec"]) == 1:
        raw = zlib.decompress(raw)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"_payload_decode_error": True}
    return value if isinstance(value, dict) else {"_payload_type": type(value).__name__}


def _payload_type(payload: dict[str, Any]) -> str:
    if payload.get("_payload_decode_error"):
        return "decode_error"
    if payload.get("_payload_type"):
        return str(payload["_payload_type"])
    return "object"


def _event_category(kind: str, payload: dict[str, Any]) -> str:
    category = KIND_CATEGORY.get(kind)
    if category:
        return category
    text = " ".join((kind, json.dumps(payload, ensure_ascii=False, default=str))).casefold()
    if any(token in text for token in ("lldp", "neighbor")):
        return "LLDP"
    if any(token in text for token in ("radio", "rid", "channel", "bbssid")):
        return "Radio"
    if any(token in text for token in ("interface", "pvid", "port_mode")):
        return "Interface"
    if any(token in text for token in ("optical", "rx_power", "tx_power", "transceiver")):
        return "Optical"
    if not kind:
        return "UNKNOWN"
    return "Other"


def _add_event(
    events: dict[tuple[str, str, str, str], dict[str, Any]],
    *,
    site: str,
    source: str,
    event_id: str,
    kind: str,
    event_type: str,
    collected_at: str,
    payload: dict[str, Any],
    payload_bytes: int,
) -> None:
    category = _event_category(kind, payload)
    key = (site, kind or "<empty>", event_type or "<empty>", _payload_type(payload))
    item = events.setdefault(
        key,
        {
            "site": site,
            "source_files": set(),
            "kind": kind,
            "event_type": event_type,
            "payload_type": _payload_type(payload),
            "category": category,
            "row_count": 0,
            "payload_bytes": 0,
            "min_time": "",
            "max_time": "",
            "resource_keys": set(),
            "event_ids_sha256": hashlib.sha256(),
        },
    )
    item["source_files"].add(source)
    item["row_count"] += 1
    item["payload_bytes"] += payload_bytes
    item["min_time"] = min(item["min_time"] or collected_at, collected_at or item["min_time"])
    item["max_time"] = max(item["max_time"], collected_at)
    resource = payload.get("resource_key") or payload.get("ap_uuid") or payload.get("entity_key")
    if resource not in (None, ""):
        item["resource_keys"].add(str(resource))
    item["event_ids_sha256"].update(str(event_id).encode("utf-8", errors="replace"))


def _scan_history(site_dir: Path, events: dict[tuple[str, str, str], dict[str, Any]]) -> dict[str, Any]:
    history_dir = site_dir / "db" / "history"
    result = {"path": str(history_dir), "exists": history_dir.exists(), "bytes": 0, "files": []}
    if not history_dir.exists():
        return result
    for path in sorted(history_dir.glob("*.db")):
        result["bytes"] += path.stat().st_size
        result["files"].append({"name": path.name, "bytes": path.stat().st_size})
        try:
            with closing(_read_only(path)) as conn:
                conn.row_factory = sqlite3.Row
                tables = _tables(conn)
                if "history_events" in tables:
                    for row in conn.execute(
                        "SELECT event_id, kind, event_type, collected_at, payload_json FROM history_events"
                    ):
                        try:
                            payload = json.loads(str(row["payload_json"] or "{}"))
                        except json.JSONDecodeError:
                            payload = {"_payload_decode_error": True}
                        _add_event(
                            events,
                            site=site_dir.name,
                            source=str(path),
                            event_id=str(row["event_id"]),
                            kind=str(row["kind"] or ""),
                            event_type=str(row["event_type"] or ""),
                            collected_at=str(row["collected_at"] or ""),
                            payload=payload if isinstance(payload, dict) else {"_payload_type": type(payload).__name__},
                            payload_bytes=len(str(row["payload_json"] or "").encode("utf-8")),
                        )
                if "history_events_v2" in tables:
                    for row in conn.execute(
                        """
                        SELECT e.event_id, k.name AS kind, t.name AS event_type,
                               e.collected_at, e.payload, e.payload_codec
                        FROM history_events_v2 AS e
                        JOIN history_kinds_v2 AS k ON k.kind_id=e.kind_id
                        JOIN history_event_types_v2 AS t ON t.event_type_id=e.event_type_id
                        """
                    ):
                        payload = _decode_v2(row)
                        _add_event(
                            events,
                            site=site_dir.name,
                            source=str(path),
                            event_id=bytes(row["event_id"]).hex(),
                            kind=str(row["kind"] or ""),
                            event_type=str(row["event_type"] or ""),
                            collected_at=str(row["collected_at"] or ""),
                            payload=payload,
                            payload_bytes=len(bytes(row["payload"])),
                        )
        except (OSError, sqlite3.Error) as exc:
            result.setdefault("errors", []).append(f"{path}: {exc}")
    return result


def _scan_direct_db(site_dir: Path) -> dict[str, Any]:
    path = site_dir / "db" / "devices.db"
    result: dict[str, Any] = {"path": str(path), "exists": path.exists(), "tables": {}}
    if not path.exists():
        return result
    try:
        with closing(_read_only(path)) as conn:
            conn.row_factory = sqlite3.Row
            names = _tables(conn)
            for table in TARGET_TABLES:
                if table not in names:
                    continue
                row = conn.execute(f"SELECT COUNT(*) AS total FROM {table}").fetchone()
                result["tables"][table] = {"rows": int(row["total"] if row else 0)}
            for table in (
                "fit_ap_lldp_current",
                "fit_ap_lldp_history",
                "fit_ap_radio_current",
                "fit_ap_radio_history",
                "device_interfaces",
                "device_interfaces_history",
                "optical_current",
                "optical_history",
                "ap_optical_treatment",
                "history_outbox",
                "history_state",
            ):
                if table in names:
                    row = conn.execute(f"SELECT COUNT(*) AS total FROM {table}").fetchone()
                    result["tables"][table] = {"rows": int(row["total"] if row else 0)}
            try:
                dbstat = conn.execute(
                    "SELECT name, SUM(pgsize) AS bytes FROM dbstat GROUP BY name"
                ).fetchall()
                result["dbstat_bytes"] = {str(row["name"]): int(row["bytes"] or 0) for row in dbstat}
            except sqlite3.Error:
                result["dbstat_bytes"] = {}
    except (OSError, sqlite3.Error) as exc:
        result["error"] = str(exc)
    return result


def inventory(root: Path) -> dict[str, Any]:
    resolved = root.resolve()
    if resolved.name.casefold() != "netconsoledata-dev":
        raise SystemExit(f"refusing non-dev data root: {resolved}")
    sites_root = resolved / "sites"
    events: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    site_records = []
    for site_dir in sorted(path for path in sites_root.iterdir() if path.is_dir()):
        site_records.append(
            {
                "site": site_dir.name,
                "history": _scan_history(site_dir, events),
                "devices_db": _scan_direct_db(site_dir),
            }
        )
    event_records = []
    for item in events.values():
        item = dict(item)
        item["source_files"] = sorted(item["source_files"])
        item["resource_count"] = len(item.pop("resource_keys"))
        item["event_ids_sha256"] = item.pop("event_ids_sha256").hexdigest()
        event_records.append(item)
    event_records.sort(key=lambda item: (item["category"], item["kind"], item["event_type"], item["payload_type"]))
    return {
        "data_root": str(resolved),
        "site_count": len(site_records),
        "sites": site_records,
        "history_events": event_records,
        "history_bytes": sum(int(site["history"]["bytes"]) for site in site_records),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", default=r"D:\NetConsoleData-dev")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    payload = json.dumps(inventory(Path(args.data_root)), ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)


if __name__ == "__main__":
    main()
