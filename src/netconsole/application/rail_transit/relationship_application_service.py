from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from typing import Any

from netconsole.core.paths import PathResolver
from netconsole.core.site_identity import load_site_metadata
from netconsole.models.api.rail_relationship import (
    RelationshipHistoryPage,
    RelationshipHistoryRecord,
    RelationshipMutationRequest,
    RelationshipMutationResult,
    RelationshipPage,
    RelationshipRecord,
)
from netconsole.repositories.rail_transit_base_data_repository import RailTransitBaseDataRepository
from netconsole.services.rail_transit.base_data_write_guard import (
    BaseDataWriteGuard,
    BaseDataWriteGuardError,
)
from netconsole.services.site_manager import SiteManager


class RelationshipApplicationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


_TABLES = {
    "node_project": "rail_infra_node_project",
    "device_node": "rail_infra_device_link",
    "device_section": "rail_infra_device_section",
    "ac_service": "rail_infra_ac_service",
    "train_mr": "rail_infra_train_mr",
}


class RailRelationshipApplicationService:
    """Transactional write boundary for formal rail engineering relations."""

    def __init__(self, paths: PathResolver, guard: BaseDataWriteGuard) -> None:
        self.paths = paths
        self.guard = guard
        self.repository = RailTransitBaseDataRepository(paths)

    def list_current(
        self,
        site_id: str,
        *,
        relationship_type: str = "",
        entity_uid: str = "",
    ) -> RelationshipPage:
        site_id = SiteManager(self.paths).validate_site_name(site_id)
        path = self._database_path(site_id)
        allowed = self._types(relationship_type)
        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            items: list[RelationshipRecord] = []
            for kind in allowed:
                for row in self._select_current(conn, kind, entity_uid):
                    items.append(self._record(kind, row))
            revision = self._revision(conn, site_id)
        return RelationshipPage(items=items, total=len(items), revision=revision)

    def list_history(
        self,
        site_id: str,
        *,
        relationship_type: str = "",
        entity_uid: str = "",
    ) -> RelationshipHistoryPage:
        site_id = SiteManager(self.paths).validate_site_name(site_id)
        with sqlite3.connect(self._database_path(site_id)) as conn:
            conn.row_factory = sqlite3.Row
            clauses: list[str] = []
            params: list[str] = []
            if relationship_type:
                self._types(relationship_type)
                clauses.append("relation_type = ?")
                params.append(relationship_type)
            if entity_uid:
                clauses.append("(source_uid = ? OR target_uid = ? OR relation_id = ?)")
                params.extend((entity_uid, entity_uid, entity_uid))
            where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = conn.execute(
                "SELECT * FROM rail_infra_relation_history" + where + " ORDER BY changed_at DESC, event_id DESC",
                params,
            ).fetchall()
        return RelationshipHistoryPage(
            items=[
                RelationshipHistoryRecord(
                    event_id=str(row["event_id"]), relationship_type=str(row["relation_type"]),
                    relationship_id=str(row["relation_id"]), action=str(row["action"]),
                    source_uid=str(row["source_uid"]), target_uid=str(row["target_uid"]),
                    before=json.loads(row["before_json"] or "{}"), after=json.loads(row["after_json"] or "{}"),
                    effective_from=str(row["effective_from"] or ""), effective_to=str(row["effective_to"] or ""),
                    reason=str(row["reason"] or ""), actor=str(row["actor"] or ""),
                    changed_at=str(row["changed_at"]), revision=str(row["revision"] or ""),
                )
                for row in rows
            ],
            total=len(rows),
        )

    def mutate(self, request: RelationshipMutationRequest) -> RelationshipMutationResult:
        site_id = SiteManager(self.paths).validate_site_name(request.site_id)
        try:
            self.guard.authorize_apply(site_id, explicit_confirmation=request.explicit_confirmation)
        except BaseDataWriteGuardError as exc:
            raise RelationshipApplicationError(exc.code, str(exc)) from exc
        kind = self._types(request.relationship_type)[0]
        path = self._database_path(site_id)
        connection = sqlite3.connect(path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("BEGIN IMMEDIATE")
            current_revision = self._revision(connection, site_id)
            if current_revision != request.base_revision:
                raise RelationshipApplicationError("BASE_DATA_REVISION_CONFLICT", "工程关系已被其他操作修改")
            lookup_id = request.relationship_id or (
                f"{request.source_uid}:{request.target_uid}" if kind != "train_mr" else ""
            )
            before = self._find_current(connection, kind, lookup_id)
            if request.action == "create" and before is not None:
                raise RelationshipApplicationError("RELATION_ALREADY_EXISTS", "工程关系已存在")
            if request.action in {"update", "terminate", "replace"} and before is None and kind != "train_mr":
                raise RelationshipApplicationError("RELATION_NOT_FOUND", "工程关系不存在或已解除")
            if not request.relationship_id and lookup_id:
                request = request.model_copy(update={"relationship_id": lookup_id})
            after = self._apply(connection, site_id, kind, request, before)
            effective_relation_id = request.relationship_id or (
                self._record(kind, after).relationship_id if after else ""
            )
            revision = self._revision(connection, site_id)
            event_id = str(uuid4())
            changed_at = self._now()
            connection.execute(
                "INSERT INTO rail_infra_relation_history "
                "(event_id, relation_type, relation_id, action, source_uid, target_uid, before_json, after_json, effective_from, effective_to, reason, actor, changed_at, revision) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event_id, kind, effective_relation_id, request.action,
                    request.source_uid, request.target_uid, json.dumps(before or {}, ensure_ascii=False),
                    json.dumps(after or {}, ensure_ascii=False), request.effective_from or None,
                    request.effective_to or None, request.reason.strip(), request.actor.strip() or "desktop",
                    changed_at, revision,
                ),
            )
            connection.execute(
                "INSERT INTO rail_infra_relation_audit (audit_id, event_id, site_id, operation, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (str(uuid4()), event_id, site_id, request.action, json.dumps(request.model_dump(mode="json"), ensure_ascii=False), changed_at),
            )
            connection.commit()
            final_revision = self.repository.base_data_revision(site_id)
            return RelationshipMutationResult(
                relationship=self._record(kind, after) if after else None,
                revision=final_revision,
                history_event_id=event_id,
            )
        except RelationshipApplicationError:
            connection.rollback()
            raise
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise RelationshipApplicationError("RELATION_CONFLICT", "工程关系违反唯一性或引用约束") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _apply(self, conn: sqlite3.Connection, site_id: str, kind: str, req: RelationshipMutationRequest, before: dict[str, Any] | None) -> dict[str, Any] | None:
        action = req.action
        if action == "terminate":
            self._delete(conn, kind, req.relationship_id)
            return None
        if action == "replace" and kind == "train_mr" and before:
            conn.execute("UPDATE rail_infra_train_mr SET active_to = ? WHERE assignment_id = ? AND active_to IS NULL", (req.effective_to or self._now(), req.relationship_id))
            action = "create"
        if action == "update" and before:
            self._delete(conn, kind, req.relationship_id)
            action = "create"
        values = dict(req.values)
        if kind == "node_project":
            source, target = req.source_uid, req.target_uid
            self._require_exists(conn, "rail_infra_node", "node_uid", source)
            self._require_exists(conn, "rail_infra_project", "project_id", target)
            conn.execute("INSERT INTO rail_infra_node_project(node_uid, project_id) VALUES (?, ?)", (source, target))
            return {"node_uid": source, "project_id": target}
        if kind == "device_node":
            source, target = req.source_uid, req.target_uid
            self._require_exists(conn, "rail_infra_node", "node_uid", source)
            self._require_exists(conn, "devices", "device_uuid", target)
            conn.execute("INSERT OR REPLACE INTO rail_infra_device_link(node_uid, device_uuid, engineering_role, section_uid) VALUES (?, ?, ?, ?)", (source, target, str(values.get("engineering_role") or ""), values.get("section_uid")))
            return {"node_uid": source, "device_uuid": target, "engineering_role": str(values.get("engineering_role") or ""), "section_uid": values.get("section_uid")}
        if kind == "device_section":
            source, target = req.source_uid, req.target_uid
            self._require_exists(conn, "devices", "device_uuid", source)
            conn.execute("INSERT OR REPLACE INTO rail_infra_device_section(device_uuid, section_uid, engineering_role, installation_location) VALUES (?, ?, ?, ?)", (source, target, str(values.get("engineering_role") or ""), str(values.get("installation_location") or "")))
            return {"device_uuid": source, "section_uid": target, "engineering_role": str(values.get("engineering_role") or ""), "installation_location": str(values.get("installation_location") or "")}
        if kind == "ac_service":
            source, target = req.source_uid, req.target_uid
            self._require_exists(conn, "devices", "device_uuid", source)
            self._require_exists(conn, "rail_infra_node", "node_uid", target)
            conn.execute("INSERT INTO rail_infra_ac_service(ac_device_uuid, node_uid) VALUES (?, ?)", (source, target))
            return {"ac_device_uuid": source, "node_uid": target}
        if kind == "train_mr":
            assignment_id = req.relationship_id or str(uuid4())
            train_uid = req.source_uid or str(values.get("train_uid") or "")
            device_uuid = req.target_uid or str(values.get("device_uuid") or "")
            position = str(values.get("position") or "")
            if position not in {"CT", "CW"}:
                raise RelationshipApplicationError("RELATION_INVALID", "MR 角色必须为 CT 或 CW")
            self._require_exists(conn, "rail_infra_train", "train_uid", train_uid)
            self._require_exists(conn, "devices", "device_uuid", device_uuid)
            conn.execute("INSERT INTO rail_infra_train_mr(assignment_id, train_uid, device_uuid, position, active_from, active_to) VALUES (?, ?, ?, ?, ?, NULL)", (assignment_id, train_uid, device_uuid, position, req.effective_from or self._now()))
            return {"assignment_id": assignment_id, "train_uid": train_uid, "device_uuid": device_uuid, "position": position, "active_from": req.effective_from or self._now(), "active_to": None}
        raise RelationshipApplicationError("RELATION_INVALID", "未知工程关系类型")

    def _delete(self, conn: sqlite3.Connection, kind: str, relation_id: str) -> None:
        keys = relation_id.split(":", 1)
        if kind == "node_project":
            conn.execute("DELETE FROM rail_infra_node_project WHERE node_uid = ? AND project_id = ?", keys)
        elif kind == "device_node":
            conn.execute("DELETE FROM rail_infra_device_link WHERE node_uid = ? AND device_uuid = ?", keys)
        elif kind == "device_section":
            conn.execute("DELETE FROM rail_infra_device_section WHERE device_uuid = ? AND section_uid = ?", keys)
        elif kind == "ac_service":
            conn.execute("DELETE FROM rail_infra_ac_service WHERE ac_device_uuid = ? AND node_uid = ?", keys)
        elif kind == "train_mr":
            conn.execute("UPDATE rail_infra_train_mr SET active_to = ? WHERE assignment_id = ? AND active_to IS NULL", (self._now(), relation_id))

    def _select_current(self, conn: sqlite3.Connection, kind: str, entity_uid: str) -> list[sqlite3.Row]:
        queries = {
            "node_project": "SELECT node_uid, project_id FROM rail_infra_node_project",
            "device_node": "SELECT node_uid, device_uuid, engineering_role, section_uid FROM rail_infra_device_link",
            "device_section": "SELECT device_uuid, section_uid, engineering_role, installation_location FROM rail_infra_device_section",
            "ac_service": "SELECT ac_device_uuid, node_uid FROM rail_infra_ac_service",
            "train_mr": "SELECT assignment_id, train_uid, device_uuid, position, active_from, active_to FROM rail_infra_train_mr WHERE active_to IS NULL",
        }
        rows = conn.execute(queries[kind]).fetchall()
        return [row for row in rows if not entity_uid or entity_uid in {str(value) for value in row}]

    def _find_current(self, conn: sqlite3.Connection, kind: str, relation_id: str) -> dict[str, Any] | None:
        rows = self._select_current(conn, kind, "")
        for row in rows:
            record = self._record(kind, row)
            if record.relationship_id == relation_id:
                return record.model_dump(mode="json")
        return None

    @staticmethod
    def _record(kind: str, row: sqlite3.Row | dict[str, Any]) -> RelationshipRecord:
        data = dict(row)
        if kind == "node_project":
            source, target, rid = data["node_uid"], data["project_id"], f"{data['node_uid']}:{data['project_id']}"
        elif kind == "device_node":
            source, target, rid = data["node_uid"], data["device_uuid"], f"{data['node_uid']}:{data['device_uuid']}"
        elif kind == "device_section":
            source, target, rid = data["device_uuid"], data["section_uid"], f"{data['device_uuid']}:{data['section_uid']}"
        elif kind == "ac_service":
            source, target, rid = data["ac_device_uuid"], data["node_uid"], f"{data['ac_device_uuid']}:{data['node_uid']}"
        else:
            source, target, rid = data["train_uid"], data["device_uuid"], data["assignment_id"]
        return RelationshipRecord(relationship_type=kind, relationship_id=rid, source_uid=str(source), target_uid=str(target), status="active", values=data, effective_from=str(data.get("active_from") or ""), effective_to=str(data.get("active_to") or ""))

    @staticmethod
    def _types(value: str) -> list[str]:
        if value and value not in _TABLES:
            raise RelationshipApplicationError("RELATION_INVALID", "未知工程关系类型")
        return [value] if value else list(_TABLES)

    def _database_path(self, site_id: str) -> Path:
        path = self.paths.site_db_path(site_id).resolve()
        if not path.is_file() or self.paths.sites_dir.resolve() not in path.parents:
            raise RelationshipApplicationError("BASE_DATA_SOURCE_INVALID", "基础资料数据库不存在")
        return path

    @staticmethod
    def _require_exists(conn: sqlite3.Connection, table: str, key: str, value: str) -> None:
        if not value or conn.execute(f"SELECT 1 FROM {table} WHERE {key} = ? LIMIT 1", (value,)).fetchone() is None:
            raise RelationshipApplicationError("RELATION_REFERENCE_MISSING", f"关系引用对象不存在: {value}")

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _revision(self, conn: sqlite3.Connection, site_id: str) -> str:
        row = conn.execute("SELECT value FROM schema_metadata WHERE key = 'base_data_revision'").fetchone()
        counter = str(row[0] if row else "0")
        database_revision = hashlib.sha256(f"base-data-counter-v1\n{counter}".encode()).hexdigest()
        metadata = load_site_metadata(self.paths, site_id)
        payload = json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(f"{database_revision}\n{payload}".encode()).hexdigest()
