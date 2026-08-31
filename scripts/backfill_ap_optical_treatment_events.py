"""Backfill AP optical treatment lifecycle events from persisted evidence.

The command is dry-run by default.  It accepts the previously audited JSON
evidence as candidate input, but never reads an Excel workbook as a database
authority and never reads the Production data root.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from typing import Any
from uuid import NAMESPACE_URL, uuid5


DEVELOPMENT_DATA_ROOT = Path(r"D:\NetConsoleData-dev")
PRODUCTION_DATA_ROOT = Path(r"D:\NetConsoleData")
DEFAULT_EVIDENCE_DIR = (
    Path(__file__).resolve().parents[2]
    / "diagnostic"
    / "treatment-event-design-20260831"
)
EVENT_TABLE = "ap_optical_treatment_events"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AP 光衰 Treatment Event History 回填（默认 dry-run）"
    )
    parser.add_argument("--site", required=True, help="限定 Development site，例如 hzl10")
    parser.add_argument(
        "--data-root",
        default=str(DEVELOPMENT_DATA_ROOT),
        help="数据根；默认且 apply 允许的真实根为 D:\\NetConsoleData-dev",
    )
    parser.add_argument(
        "--database",
        default="",
        help="可选的单个 SQLite 路径；用于隔离测试，不改变默认 Development 目标",
    )
    parser.add_argument(
        "--evidence-dir",
        default=str(DEFAULT_EVIDENCE_DIR),
        help="审计 evidence JSON 所在目录",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="只规划，不写 DB（默认）")
    mode.add_argument("--apply", action="store_true", help="应用到指定 Development DB")
    parser.add_argument("--json-output", default="", help="可选的报告 JSON 输出路径")
    return parser.parse_args()


def _text(value: object) -> str:
    return str(value or "").strip()


def _timestamp(value: object) -> str:
    value = _text(value)
    if not value:
        return ""
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return ""
    return value


def _number(value: object) -> float | None:
    try:
        return float(_text(value))
    except ValueError:
        return None


def _worse(previous: object, current: object) -> str:
    previous_text = _text(previous)
    current_text = _text(current)
    if not previous_text:
        return current_text
    if not current_text:
        return previous_text
    previous_number = _number(previous_text)
    current_number = _number(current_text)
    if previous_number is None or current_number is None:
        return previous_text
    return previous_text if previous_number <= current_number else current_text


def _status_priority(status: object) -> int:
    return {
        "notice": 1,
        "warning": 2,
        "abnormal": 3,
        "link_abnormal": 4,
        "link_down": 4,
        "no_light": 5,
        "alarm": 6,
    }.get(_text(status).casefold(), 0)


def _worst_status(*statuses: object) -> str:
    values = [_text(value).casefold() for value in statuses if _status_priority(value)]
    return max(values, key=_status_priority, default="")


def _side(value: object) -> str:
    value = _text(value).upper()
    return value if value in {"AP", "SWITCH", "BOTH"} else "UNKNOWN"


def _merge_side(previous: object, current: object) -> str:
    values = {
        value
        for value in (_side(previous), _side(current))
        if value != "UNKNOWN"
    }
    if "BOTH" in values or len(values) > 1:
        return "BOTH"
    return next(iter(values), "UNKNOWN")


def _tokens(value: object) -> list[str]:
    result: list[str] = []
    for token in _text(value).split(";"):
        if token and token not in result:
            result.append(token)
    return result


def _join_tokens(*values: object) -> str:
    result: list[str] = []
    for value in values:
        for token in _tokens(value):
            if token not in result:
                result.append(token)
    return ";".join(result)


def _json_object(value: object) -> dict[str, Any]:
    try:
        parsed = json.loads(_text(value) or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _evidence_json(
    *,
    keys: list[str],
    source: str,
    quality: str,
    audit_rows: list[dict[str, Any]],
) -> str:
    return json.dumps(
        {
            "backfill_keys": keys,
            "source": source,
            "evidence_quality": quality,
            "audits": [
                {
                    "audit_id": _text(row.get("audit_id")),
                    "classification": _text(row.get("classification")),
                    "occurrence": _text(row.get("recoverable_occurrence")),
                    "source_revision_evidence": _text(row.get("source_revision_evidence")),
                    "raw_log_evidence": _text(row.get("raw_log_evidence")),
                }
                for row in audit_rows
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _load_trace(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise SystemExit(f"evidence 文件不存在：{path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("rows") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise SystemExit(f"evidence rows 无效：{path}")
    return [row for row in rows if isinstance(row, dict)]


def _event_columns() -> tuple[str, ...]:
    return (
        "event_uuid",
        "site_id",
        "ap_identity",
        "ap_uuid",
        "ap_name",
        "ap_mac",
        "ap_mac_normalized",
        "serial_number",
        "ap_id",
        "station_id",
        "station_name",
        "section_name",
        "direction",
        "first_abnormal_side",
        "worst_abnormal_side",
        "last_abnormal_side",
        "switch_device_id",
        "switch_name",
        "switch_interface",
        "issue_type",
        "initial_severity",
        "worst_severity",
        "first_detected_at",
        "last_abnormal_at",
        "resolved_at",
        "first_ap_rx_dbm",
        "worst_ap_rx_dbm",
        "recovered_ap_rx_dbm",
        "first_switch_rx_dbm",
        "worst_switch_rx_dbm",
        "recovered_switch_rx_dbm",
        "first_rx_dbm",
        "worst_rx_dbm",
        "recovered_rx_dbm",
        "event_status",
        "treatment_status",
        "remark",
        "source_revision_first",
        "source_revision_last",
        "backfill_key",
        "backfill_source",
        "evidence_quality",
        "evidence_json",
        "last_observation_fingerprint",
        "created_at",
        "updated_at",
    )


def _base_event(*, site: str, identity: str, key: str, now: str) -> dict[str, Any]:
    values = {column: "" for column in _event_columns()}
    values.update(
        {
            "event_uuid": uuid5(
                NAMESPACE_URL, f"netconsole:ap-optical-treatment-event:{site}:{key}"
            ).hex,
            "site_id": site,
            "ap_identity": identity,
            "first_abnormal_side": "UNKNOWN",
            "worst_abnormal_side": "UNKNOWN",
            "last_abnormal_side": "UNKNOWN",
            "event_status": "OPEN",
            "treatment_status": "PENDING",
            "evidence_quality": "PARTIAL",
            "evidence_json": "{}",
            "backfill_key": key,
            "created_at": now,
            "updated_at": now,
        }
    )
    return values


def _summary_event(row: sqlite3.Row, site: str, now: str) -> dict[str, Any]:
    identity = _text(row["ap_identity"] or row["ap_uuid"])
    key = f"CURRENT_SUMMARY:{site}:{identity}"
    current_status = _text(row["current_status"]).upper()
    event_status = "OPEN" if current_status == "ABNORMAL" else "RESOLVED"
    first_side = _side(row["first_abnormal_side"])
    current_side = _side(row["current_abnormal_side"])
    latest_side = current_side if current_status == "ABNORMAL" else first_side
    issue = _worst_status(row["current_ap_status"], row["current_switch_status"])
    first_ap = _text(row["first_ap_rx_dbm"])
    first_switch = _text(row["first_switch_rx_dbm"])
    current_ap = _text(row["current_ap_rx_dbm"])
    current_switch = _text(row["current_switch_rx_dbm"])
    recovered_ap = _text(row["recovered_ap_rx_dbm"])
    recovered_switch = _text(row["recovered_switch_rx_dbm"])
    treatment_status = _text(row["treatment_status"]).upper()
    if treatment_status not in {"IN_PROGRESS", "COMPLETED", "IGNORED"}:
        treatment_status = "PENDING"
    event = _base_event(site=site, identity=identity, key=key, now=now)
    event.update(
        {
            "ap_uuid": _text(row["ap_uuid"]),
            "ap_name": _text(row["ap_name"]),
            "ap_mac": _text(row["ap_mac"]),
            "ap_mac_normalized": _text(row["ap_mac_normalized"]),
            "serial_number": _text(row["serial_number"]),
            "ap_id": _text(row["ap_id"]),
            "station_id": _text(row["station_id"]),
            "station_name": _text(row["station_name"]),
            "section_name": _text(row["section_name"]),
            "direction": _text(row["direction"]),
            "first_abnormal_side": first_side,
            "worst_abnormal_side": _merge_side(first_side, current_side),
            "last_abnormal_side": latest_side,
            "switch_device_id": _text(row["switch_device_id"]),
            "switch_name": _text(row["switch_name"]),
            "switch_interface": _text(row["switch_interface"]),
            "issue_type": issue,
            "initial_severity": issue,
            "worst_severity": _worst_status(issue),
            "first_detected_at": _timestamp(row["first_detected_at"]),
            "last_abnormal_at": _timestamp(row["last_abnormal_at"]),
            "resolved_at": _timestamp(row["last_resolved_at"] or row["first_resolved_at"]),
            "first_ap_rx_dbm": first_ap,
            "worst_ap_rx_dbm": _worse(first_ap, current_ap),
            "recovered_ap_rx_dbm": recovered_ap,
            "first_switch_rx_dbm": first_switch,
            "worst_switch_rx_dbm": _worse(first_switch, current_switch),
            "recovered_switch_rx_dbm": recovered_switch,
            "first_rx_dbm": first_ap or first_switch,
            "worst_rx_dbm": _worse(_worse(first_ap, current_ap), _worse(first_switch, current_switch)),
            "recovered_rx_dbm": recovered_ap or recovered_switch,
            "event_status": event_status,
            "treatment_status": treatment_status,
            "source_revision_first": _text(row["source_revision"]),
            "source_revision_last": _text(row["source_revision"]),
            "backfill_source": "CURRENT_SUMMARY",
            "evidence_quality": "SUMMARY",
            "evidence_json": _evidence_json(
                keys=[key],
                source="CURRENT_SUMMARY",
                quality="SUMMARY",
                audit_rows=[],
            ),
        }
    )
    return event


def _trace_event(
    row: dict[str, Any],
    *,
    site: str,
    source_name: str,
    now: str,
) -> tuple[dict[str, Any] | None, str]:
    classification = _text(row.get("classification"))
    if classification == "LEGACY_ONLY_EVIDENCE":
        return None, "legacy_only"
    identity = _text(row.get("resolved_ap_uuid"))
    first_detected = _timestamp(row.get("recoverable_first_detected_at"))
    if (
        not identity
        or not first_detected
        or _text(row.get("identity_resolution_status"))
        != "RESOLVED_PERSISTED_IDENTITY_NO_TREATMENT"
    ):
        return None, "unresolved"
    if _text(row.get("raw_log_evidence")) != "PRESENT_DEV":
        return None, "unresolved"
    audit_id = _text(row.get("audit_id"))
    key = f"{source_name}:{audit_id}"
    side = _side(row.get("recoverable_side"))
    issue = _text(row.get("recoverable_issue_type")).casefold()
    if issue not in {"notice", "warning", "abnormal", "alarm", "no_light", "link_abnormal", "link_down"}:
        issue = ""
    first_rx = _text(row.get("recoverable_first_rx"))
    recovered_rx = _text(row.get("recoverable_recovered_rx"))
    resolved_at = _timestamp(row.get("recoverable_resolved_at"))
    normal_rows = row.get("event_normal_rows") or {}
    normal_after = _timestamp(normal_rows.get("time_max"))
    completed_at = _timestamp(row.get("completed_at"))
    resolution_basis = ""
    if resolved_at:
        event_status = "RESOLVED"
        resolution_basis = "EXACT_PERSISTED_NORMAL_BOUNDARY"
    elif completed_at:
        event_status = "RESOLVED"
        resolution_basis = "EXPLICIT_TREATMENT_COMPLETION_BOUNDARY_UNKNOWN"
    elif normal_after and normal_after > first_detected:
        event_status = "RESOLVED"
        resolution_basis = "PERSISTED_NORMAL_EVIDENCE_BOUNDARY_UNKNOWN"
    else:
        event_status = "OPEN"
    event = _base_event(site=site, identity=identity, key=key, now=now)
    last_abnormal = _timestamp((row.get("event_issue_rows") or {}).get("time_max")) or first_detected
    event.update(
        {
            "ap_uuid": identity,
            "ap_name": _text(row.get("ap_name")),
            "ap_mac": _text(row.get("ap_mac")),
            "serial_number": _text(row.get("serial_number")),
            "station_name": _text(row.get("site")),
            "first_abnormal_side": side,
            "worst_abnormal_side": side,
            "last_abnormal_side": side,
            "switch_name": _text(row.get("switch_name")),
            "switch_interface": _text(row.get("interface_name")),
            "issue_type": issue,
            "initial_severity": issue,
            "worst_severity": issue,
            "first_detected_at": first_detected,
            "last_abnormal_at": last_abnormal,
            "resolved_at": resolved_at,
            "event_status": event_status,
            "treatment_status": "COMPLETED" if completed_at else "PENDING",
            "source_revision_first": _text(row.get("source_revision_evidence")),
            "source_revision_last": _text(row.get("source_revision_evidence")),
            "backfill_source": source_name,
            "evidence_quality": "FULL" if classification == "RECOVERABLE_FROM_EXISTING_PERSISTED_EVIDENCE" else "PARTIAL",
            "first_rx_dbm": first_rx,
            "worst_rx_dbm": first_rx,
            "recovered_rx_dbm": recovered_rx,
            "evidence_json": _evidence_json(
                keys=[key],
                source=source_name,
                quality="FULL" if classification == "RECOVERABLE_FROM_EXISTING_PERSISTED_EVIDENCE" else "PARTIAL",
                audit_rows=[{**row, "resolution_basis": resolution_basis}],
            ),
        }
    )
    if side in {"AP", "BOTH"}:
        event["first_ap_rx_dbm"] = first_rx
        event["worst_ap_rx_dbm"] = first_rx
        event["recovered_ap_rx_dbm"] = recovered_rx if side == "AP" else ""
    if side in {"SWITCH", "BOTH"}:
        event["first_switch_rx_dbm"] = first_rx
        event["worst_switch_rx_dbm"] = first_rx
        event["recovered_switch_rx_dbm"] = recovered_rx if side == "SWITCH" else ""
    return event, "partial" if event["evidence_quality"] == "PARTIAL" else "full"


def _load_existing(conn: sqlite3.Connection, site: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"SELECT * FROM {EVENT_TABLE} WHERE site_id=? ORDER BY first_detected_at, id",
        (site,),
    ).fetchall()
    return [dict(row) for row in rows]


def _consumed_keys(existing: list[dict[str, Any]]) -> set[str]:
    result: set[str] = set()
    for row in existing:
        result.update(_text(row.get("backfill_key")).split(";") if _text(row.get("backfill_key")) else [])
        evidence = _json_object(row.get("evidence_json"))
        keys = evidence.get("backfill_keys")
        if isinstance(keys, list):
            result.update(_text(key) for key in keys if _text(key))
    return result


def _append_evidence(existing: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    evidence = _json_object(existing.get("evidence_json"))
    candidate_evidence = _json_object(candidate.get("evidence_json"))
    keys = [
        *_text_list(evidence.get("backfill_keys")),
        *_text_list(candidate_evidence.get("backfill_keys")),
    ]
    unique_keys = list(dict.fromkeys(key for key in keys if key))
    audits = [
        *_dict_list(evidence.get("audits")),
        *_dict_list(candidate_evidence.get("audits")),
    ]
    source = _join_tokens(existing.get("backfill_source"), candidate.get("backfill_source"))
    quality = _join_tokens(existing.get("evidence_quality"), candidate.get("evidence_quality"))
    return {
        "backfill_key": _text(existing.get("backfill_key")) or _text(candidate.get("backfill_key")),
        "backfill_source": source,
        "evidence_quality": quality,
        "source_revision_first": _text(existing.get("source_revision_first"))
        or _text(candidate.get("source_revision_first")),
        "source_revision_last": _join_tokens(
            existing.get("source_revision_last"), candidate.get("source_revision_last")
        ),
        "evidence_json": json.dumps(
            {"backfill_keys": unique_keys, "source": source, "audits": audits},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
    }


def _text_list(value: object) -> list[str]:
    return [_text(item) for item in value] if isinstance(value, list) else []


def _dict_list(value: object) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _merge_event(primary: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    result = dict(primary)
    result["worst_abnormal_side"] = _merge_side(
        result.get("worst_abnormal_side"), candidate.get("worst_abnormal_side")
    )
    result["worst_ap_rx_dbm"] = _worse(
        result.get("worst_ap_rx_dbm"), candidate.get("worst_ap_rx_dbm")
    )
    result["worst_switch_rx_dbm"] = _worse(
        result.get("worst_switch_rx_dbm"), candidate.get("worst_switch_rx_dbm")
    )
    result["worst_rx_dbm"] = _worse(result.get("worst_rx_dbm"), candidate.get("worst_rx_dbm"))
    result["source_revision_last"] = _join_tokens(
        result.get("source_revision_last"), candidate.get("source_revision_last")
    )
    result["backfill_source"] = _join_tokens(
        result.get("backfill_source"), candidate.get("backfill_source")
    )
    result["evidence_quality"] = _join_tokens(
        result.get("evidence_quality"), candidate.get("evidence_quality")
    )
    existing_evidence = _json_object(result.get("evidence_json"))
    candidate_evidence = _json_object(candidate.get("evidence_json"))
    evidence_keys = list(
        dict.fromkeys(
            [
                *_text_list(existing_evidence.get("backfill_keys")),
                *_text_list(candidate_evidence.get("backfill_keys")),
            ]
        )
    )
    evidence_audits = [
        *_dict_list(existing_evidence.get("audits")),
        *_dict_list(candidate_evidence.get("audits")),
    ]
    result["evidence_json"] = json.dumps(
        {
            "backfill_keys": evidence_keys,
            "source": result["backfill_source"],
            "audits": evidence_audits,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    for field in (
        "ap_uuid",
        "ap_name",
        "ap_mac",
        "ap_mac_normalized",
        "serial_number",
        "ap_id",
        "station_id",
        "station_name",
        "section_name",
        "direction",
        "switch_device_id",
        "switch_name",
        "switch_interface",
    ):
        if not _text(result.get(field)) and _text(candidate.get(field)):
            result[field] = candidate[field]
    return result


def _covers_summary(summary: dict[str, Any], candidate: dict[str, Any]) -> bool:
    if summary["ap_identity"] != candidate["ap_identity"]:
        return False
    start = _timestamp(candidate.get("first_detected_at"))
    summary_start = _timestamp(summary.get("first_detected_at"))
    summary_end = _timestamp(summary.get("resolved_at") or summary.get("last_abnormal_at"))
    return bool(start and summary_start and summary_end and summary_start <= start <= summary_end)


def _plan(
    conn: sqlite3.Connection,
    *,
    site: str,
    evidence_dir: Path,
    now: str,
) -> dict[str, Any]:
    summaries = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM ap_optical_treatment WHERE site_id=? ORDER BY ap_identity",
            (site,),
        ).fetchall()
    ]
    existing = _load_existing(conn, site)
    consumed = _consumed_keys(existing)
    groups = [_summary_event(row, site, now) for row in conn.execute(
        "SELECT * FROM ap_optical_treatment WHERE site_id=? ORDER BY ap_identity", (site,)
    ).fetchall()]
    summary_groups = list(groups)
    merged: list[dict[str, str]] = []
    counts = defaultdict(int)
    unresolved: list[dict[str, Any]] = []
    legacy_only: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for filename, source_name in (
        ("canonical_missing_42_trace.json", "CANONICAL_MISSING_42"),
        ("recurrence_26_trace.json", "RECURRENCE_26"),
    ):
        for row in _load_trace(evidence_dir / filename):
            event, classification = _trace_event(
                row, site=site, source_name=source_name, now=now
            )
            if classification == "legacy_only":
                legacy_only.append({"source": source_name, "audit_id": _text(row.get("audit_id"))})
                continue
            if event is None:
                unresolved.append({"source": source_name, "audit_id": _text(row.get("audit_id"))})
                continue
            counts[(source_name, event["evidence_quality"])] += 1
            if event["backfill_key"] in consumed:
                continue
            candidates.append(event)

    for candidate in candidates:
        if candidate["backfill_key"] in consumed:
            continue
        # Only the current-summary event may absorb a later candidate inside
        # its currently authoritative interval.  Historical candidates from
        # the two audit sets must not absorb one another merely because their
        # broad evidence spans overlap; their independent occurrence keys are
        # the reason the recurrence audit exists.
        target = next(
            (summary for summary in summary_groups if _covers_summary(summary, candidate)),
            None,
        )
        if target is not None:
            target_key = str(target["backfill_key"])
            target.update(_merge_event(target, candidate))
            merged.append(
                {
                    "source": _text(candidate.get("backfill_source")),
                    "backfill_key": _text(candidate.get("backfill_key")),
                    "target": target_key,
                }
            )
            continue
        existing_group = next(
            (
                group
                for group in groups
                if group["ap_identity"] == candidate["ap_identity"]
                and group["first_detected_at"] == candidate["first_detected_at"]
            ),
            None,
        )
        if existing_group is not None:
            existing_group.update(_merge_event(existing_group, candidate))
            merged.append(
                {
                    "source": _text(candidate.get("backfill_source")),
                    "backfill_key": _text(candidate.get("backfill_key")),
                    "target": _text(existing_group.get("backfill_key")),
                }
            )
            continue
        groups.append(candidate)

    operations: list[dict[str, Any]] = []
    existing_by_key: dict[str, dict[str, Any]] = {}
    for row in existing:
        existing_by_key[_text(row.get("backfill_key"))] = row
        for key in _text_list(_json_object(row.get("evidence_json")).get("backfill_keys")):
            existing_by_key[key] = row
    for group in groups:
        keys = _text_list(_json_object(group.get("evidence_json")).get("backfill_keys"))
        keys = list(dict.fromkeys([_text(group.get("backfill_key")), *keys]))
        not_consumed = [key for key in keys if key and key not in consumed]
        if not not_consumed:
            continue
        current = next((existing_by_key[key] for key in keys if key in existing_by_key), None)
        if current is None:
            operations.append({"action": "create", "event": group, "keys": keys})
        else:
            operations.append(
                {
                    "action": "update",
                    "id": current["id"],
                    "event": _append_evidence(current, group),
                    "keys": keys,
                }
            )

    projected = [*existing]
    for operation in operations:
        if operation["action"] == "create":
            projected.append(operation["event"])
    open_by_identity: dict[str, int] = defaultdict(int)
    for row in projected:
        if _text(row.get("event_status")).upper() == "OPEN":
            open_by_identity[_text(row.get("ap_identity"))] += 1
    conflicts = [
        {"ap_identity": identity, "open_events": count}
        for identity, count in open_by_identity.items()
        if identity and count > 1
    ]
    return {
        "site": site,
        "existing_event_rows": len(existing),
        "summary_rows": len(summaries),
        "would_create": sum(operation["action"] == "create" for operation in operations),
        "would_update": sum(operation["action"] == "update" for operation in operations),
        "merged_candidates": len(merged),
        "canonical_missing_total": 42,
        "canonical_missing_fully_recoverable": counts[("CANONICAL_MISSING_42", "FULL")],
        "canonical_missing_partially_recoverable": counts[("CANONICAL_MISSING_42", "PARTIAL")],
        "recurrence_total": 26,
        "recurrence_fully_recoverable": counts[("RECURRENCE_26", "FULL")],
        "recurrence_partially_recoverable": counts[("RECURRENCE_26", "PARTIAL")],
        "legacy_only_skipped": len(legacy_only),
        "unresolved": unresolved,
        "conflicts": conflicts,
        "operations": operations,
        "merged": merged,
    }


def _apply_plan(conn: sqlite3.Connection, plan: dict[str, Any], now: str) -> None:
    if plan["conflicts"] or plan["unresolved"]:
        raise SystemExit("backfill 存在 conflict/unresolved，拒绝 apply")
    conn.execute("BEGIN IMMEDIATE")
    try:
        for operation in plan["operations"]:
            if operation["action"] == "create":
                event = dict(operation["event"])
                event["updated_at"] = now
                fields = tuple(field for field in _event_columns() if field in event)
                conn.execute(
                    f"INSERT INTO {EVENT_TABLE} ({', '.join(fields)}) VALUES ({', '.join('?' for _ in fields)})",
                    [event[field] for field in fields],
                )
            else:
                event = operation["event"]
                conn.execute(
                    f"UPDATE {EVENT_TABLE} SET backfill_key=?, backfill_source=?, evidence_quality=?, "
                    "source_revision_first=?, source_revision_last=?, evidence_json=?, updated_at=? WHERE id=?",
                    (
                        event["backfill_key"],
                        event["backfill_source"],
                        event["evidence_quality"],
                        event["source_revision_first"],
                        event["source_revision_last"],
                        event["evidence_json"],
                        now,
                        operation["id"],
                    ),
                )
        site = plan["site"]
        conn.execute(
            f"UPDATE ap_optical_treatment SET recurrence_count = CASE WHEN "
            f"(SELECT COUNT(*) FROM {EVENT_TABLE} e WHERE e.site_id=ap_optical_treatment.site_id "
            "AND e.ap_identity=ap_optical_treatment.ap_identity) > 1 THEN "
            f"(SELECT COUNT(*) - 1 FROM {EVENT_TABLE} e WHERE e.site_id=ap_optical_treatment.site_id "
            "AND e.ap_identity=ap_optical_treatment.ap_identity) ELSE 0 END "
            "WHERE site_id=?",
            (site,),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _database_path(args: argparse.Namespace) -> Path:
    if args.database:
        path = Path(args.database).resolve()
    else:
        root = Path(args.data_root).resolve()
        path = root / "sites" / args.site / "db" / "devices.db"
    if PRODUCTION_DATA_ROOT.resolve() == path or PRODUCTION_DATA_ROOT.resolve() in path.parents:
        raise SystemExit("拒绝访问 Production 数据库：D:\\NetConsoleData")
    if not path.is_file() or path.is_symlink():
        raise SystemExit(f"Development 数据库不存在或为符号链接：{path}")
    return path


def main() -> int:
    args = _parse_args()
    database = _database_path(args)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    conn = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        tables = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if EVENT_TABLE not in tables:
            raise SystemExit("数据库缺少事件表，请先完成 schema migration")
        plan = _plan(
            conn,
            site=args.site,
            evidence_dir=Path(args.evidence_dir).resolve(),
            now=now,
        )
    finally:
        conn.close()

    if args.apply:
        writable = sqlite3.connect(str(database))
        writable.row_factory = sqlite3.Row
        try:
            _apply_plan(writable, plan, now)
        finally:
            writable.close()
        plan["applied"] = True
    else:
        plan["applied"] = False
    report = {
        key: value
        for key, value in plan.items()
        if key not in {"operations"}
    }
    print(f"MODE={'APPLY' if args.apply else 'DRY_RUN'}")
    print(f"WOULD_CREATE={plan['would_create']}")
    print(f"WOULD_UPDATE={plan['would_update']}")
    print(f"CANONICAL_MISSING_FULLY_RECOVERABLE={plan['canonical_missing_fully_recoverable']}")
    print(f"CANONICAL_MISSING_PARTIALLY_RECOVERABLE={plan['canonical_missing_partially_recoverable']}")
    print(f"RECURRENCE_RECOVERABLE={plan['recurrence_fully_recoverable'] + plan['recurrence_partially_recoverable']}")
    print(f"LEGACY_ONLY_SKIPPED={plan['legacy_only_skipped']}")
    print(f"BACKFILL_CONFLICTS={len(plan['conflicts'])}")
    print(f"BACKFILL_UNRESOLVED={len(plan['unresolved'])}")
    if args.json_output:
        output = Path(args.json_output).resolve()
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if not plan["conflicts"] and not plan["unresolved"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
