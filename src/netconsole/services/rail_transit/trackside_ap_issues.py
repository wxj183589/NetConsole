from __future__ import annotations

import json
from datetime import datetime, timezone

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.repositories.ac_repository import AcRepository


ISSUE_ACTIONS = ("confirm", "handle", "verify", "close")
AUDIT_FIELD = "trackside_issue_operations"


class TracksideIssueConflict(ValueError):
    pass


class TracksideIssueService:
    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths

    def list(self, site_id: str, ap_uuid: str) -> dict:
        return list_trackside_issues(Database(self.paths.site_db_path(site_id)), site_id, ap_uuid)

    def apply(self, site_id: str, event_uuid: str, action: str, note: str) -> dict:
        return apply_trackside_issue_action(Database(self.paths.site_db_path(site_id)), site_id, event_uuid, action, note)


def _evidence(row) -> dict:
    try:
        evidence = json.loads(row["evidence_json"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise TracksideIssueConflict("问题证据格式无效") from exc
    if not isinstance(evidence, dict) or not isinstance(evidence.get(AUDIT_FIELD, []), list):
        raise TracksideIssueConflict("问题证据格式无效")
    return evidence


def _issue(row) -> dict:
    evidence = _evidence(row)
    operations = evidence.get(AUDIT_FIELD, [])
    return {
        **{field: row[field] for field in (
            "event_uuid", "ap_name", "ap_uuid", "station_name", "switch_name",
            "switch_interface", "issue_type", "first_detected_at", "last_abnormal_at",
            "first_ap_rx_dbm", "first_switch_rx_dbm", "event_status", "resolved_at",
            "recovered_ap_rx_dbm", "recovered_switch_rx_dbm", "evidence_quality",
            "source_revision_first", "source_revision_last",
        )},
        "operations": operations,
    }


def list_trackside_issues(database: Database, site_id: str, ap_uuid: str) -> dict:
    if not database.exists():
        return {"history_available": False, "items": []}
    with database.connect_readonly() as conn:
        if not AcRepository._bounded_optical_authority_enabled(conn):
            return {"history_available": False, "items": []}
        rows = conn.execute(
            "SELECT * FROM ap_optical_treatment_events WHERE site_id=? AND ap_identity=? "
            "ORDER BY first_detected_at DESC, id DESC LIMIT 200",
            (site_id, ap_uuid),
        ).fetchall()
    return {"history_available": True, "items": [_issue(row) for row in rows]}


def apply_trackside_issue_action(
    database: Database, site_id: str, event_uuid: str, action: str, note: str,
) -> dict:
    if not database.exists():
        raise LookupError(event_uuid)
    with database.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if not AcRepository._bounded_optical_authority_enabled(conn):
            raise LookupError(event_uuid)
        row = conn.execute(
            "SELECT * FROM ap_optical_treatment_events WHERE site_id=? AND event_uuid=?",
            (site_id, event_uuid),
        ).fetchone()
        if row is None:
            raise LookupError(event_uuid)
        evidence = _evidence(row)
        operations = evidence.setdefault(AUDIT_FIELD, [])
        if any(operation["action"] == action for operation in operations):
            return _issue(row)
        if len(operations) >= len(ISSUE_ACTIONS) or action != ISSUE_ACTIONS[len(operations)]:
            raise TracksideIssueConflict("请按确认、处理、恢复验证、关闭的顺序操作")
        if action == "handle" and not note.strip():
            raise TracksideIssueConflict("请填写处理措施")
        if action == "verify" and not (
            row["event_status"] == "RESOLVED"
            and row["resolved_at"]
            and (row["recovered_ap_rx_dbm"] or row["recovered_switch_rx_dbm"])
        ):
            raise TracksideIssueConflict("缺少带收光值的恢复记录")
        operation = {
            "action": action,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "note": note.strip(),
        }
        if action == "verify":
            operation["recovery"] = {
                field: row[field] for field in (
                    "resolved_at", "recovered_ap_rx_dbm", "recovered_switch_rx_dbm",
                    "source_revision_last",
                )
            }
        operations.append(operation)
        serialized = json.dumps(evidence, ensure_ascii=False)
        conn.execute(
            "UPDATE ap_optical_treatment_events SET evidence_json=? WHERE site_id=? AND event_uuid=?",
            (serialized, site_id, event_uuid),
        )
        return _issue({**dict(row), "evidence_json": serialized})
