"""Site engineering relationship persistence. Never opens runtime observation stores for writes."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from uuid import uuid4

from netconsole.core.database import Database
from netconsole.core.site_identity import load_site_metadata
from netconsole.models.api.rail_relationship import (
    RelationshipRecord,
    RelationshipPage,
    RelationshipHistoryPage,
    RelationshipHistoryRecord,
    RelationshipMutationResult,
)


class RelationshipError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


# Table and column names are constants, never supplied by a request.
TABLES = {
    "node_project": ("rail_infra_node_project", "node_uid", "project_id"),
    "device_node": ("rail_infra_device_link", "node_uid", "device_uuid"),
    "device_section": ("rail_infra_device_section", "device_uuid", "section_uid"),
    "ac_service": ("rail_infra_ac_service", "ac_device_uuid", "node_uid"),
    "train_mr": ("rail_infra_train_mr", "train_uid", "device_uuid"),
}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def timestamp(value, default=""):
    if not value:
        return default
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        # Existing Phase 1 uses dates for business-effective times.
        dt = (
            dt.replace(tzinfo=timezone.utc)
            if dt.tzinfo is None
            else dt.astimezone(timezone.utc)
        )
        if dt > datetime.now(timezone.utc):
            raise ValueError("future")
        return dt.isoformat(timespec="microseconds")
    except ValueError as exc:
        raise RelationshipError(
            "RELATION_TIME_INVALID", "生效时间必须是已发生的有效日期或时间"
        ) from exc


class RailRelationshipRepository:
    def __init__(self, paths):
        self.paths = paths

    def database(self, site_id):
        path = self.paths.site_db_path(site_id).resolve()
        if not path.is_file() or self.paths.sites_dir.resolve() not in path.parents:
            raise RelationshipError("RELATION_REFERENCE_MISSING", "局点数据库不存在")
        return Database(path)

    def _revision(self, conn, site_id):
        row = conn.execute(
            "SELECT value FROM schema_metadata WHERE key='base_data_revision'"
        ).fetchone()
        counter = str(row[0] if row else "0")
        db_revision = hashlib.sha256(
            f"base-data-counter-v1\n{counter}".encode()
        ).hexdigest()
        meta = json.dumps(
            load_site_metadata(self.paths, site_id),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(f"{db_revision}\n{meta}".encode()).hexdigest()

    def revision(self, site_id):
        with closing(self.database(site_id).connect_readonly()) as conn:
            return self._revision(conn, site_id)

    def _require_schema(self, conn):
        names = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        version = conn.execute(
            "SELECT value FROM schema_metadata WHERE key='rail_infrastructure_schema_version'"
        ).fetchone()
        if "rail_infra_relation_state" not in names or not version or version[0] != "2":
            raise RelationshipError(
                "RELATION_MIGRATION_REQUIRED", "工程关系数据库需要通过正式维护入口升级"
            )

    def _records(self, conn, kind="", entity_uid=""):
        if kind and kind not in TABLES:
            raise RelationshipError("RELATION_INVALID", "未知工程关系类型")
        self._require_schema(conn)
        states = {
            r["relation_id"]: json.loads(r["state_json"])
            for r in conn.execute("SELECT * FROM rail_infra_relation_state")
        }
        result = []
        for k in [kind] if kind else TABLES:
            table, source, target = TABLES[k]
            where = " WHERE active_to IS NULL" if k == "train_mr" else ""
            for row in conn.execute(f"SELECT * FROM {table}{where}"):
                values = dict(row)
                rid = (
                    str(row["assignment_id"])
                    if k == "train_mr"
                    else json.dumps(
                        [k, row[source], row[target]],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
                # Read IDs emitted by Phase 3 only; callers never split IDs into SQL keys.
                saved = states.get(rid, {})
                item = RelationshipRecord(
                    relationship_type=k,
                    relationship_id=rid,
                    source_uid=str(row[source]),
                    target_uid=str(row[target]),
                    source_name=saved.get("source_name", ""),
                    target_name=saved.get("target_name", ""),
                    status="active",
                    values={**values, **saved.get("values", {})},
                    effective_from=saved.get(
                        "effective_from", str(values.get("active_from") or "")
                    ),
                    effective_to=saved.get("effective_to", ""),
                    created_at=saved.get("created_at", ""),
                    updated_at=saved.get("updated_at", ""),
                    actor=saved.get("actor", "legacy"),
                    reason=saved.get("reason", ""),
                    revision=saved.get("revision", ""),
                )
                if not entity_uid or entity_uid in (
                    item.source_uid,
                    item.target_uid,
                    rid,
                ):
                    result.append(item)
        return result

    def list_current(self, site_id, *, relationship_type="", entity_uid="", at_time=""):
        with closing(self.database(site_id).connect_readonly()) as conn:
            conn.execute("BEGIN")
            items = self._records(conn, relationship_type, entity_uid)
            if at_time:
                at = timestamp(at_time)
                # Business-time intervals, including repeated association lifecycles.
                # Later corrections replace the same (ID, effective_from) interval;
                # advancing effective_from closes the previous version.
                by_interval = {(r.relationship_id, r.effective_from): r for r in items}
                for event in conn.execute(
                    "SELECT before_json,after_json FROM rail_infra_relation_history ORDER BY rowid"
                ):
                    before_data, after_data = (
                        json.loads(event[k]) for k in ("before_json", "after_json")
                    )
                    if not after_data or "relationship_type" not in after_data:
                        continue
                    after = RelationshipRecord.model_validate(after_data)
                    if before_data and "relationship_type" in before_data:
                        before = RelationshipRecord.model_validate(before_data)
                        if before.effective_from != after.effective_from:
                            before.effective_to = after.effective_from
                        by_interval[(before.relationship_id, before.effective_from)] = (
                            before
                        )
                    by_interval[(after.relationship_id, after.effective_from)] = after
                # Phase 1 MR intervals predate event history and remain queryable.
                for row in conn.execute(
                    "SELECT * FROM rail_infra_train_mr WHERE active_to IS NOT NULL"
                ):
                    key = (row["assignment_id"], str(row["active_from"]))
                    by_interval.setdefault(
                        key,
                        RelationshipRecord(
                            relationship_type="train_mr",
                            relationship_id=row["assignment_id"],
                            source_uid=row["train_uid"],
                            target_uid=row["device_uuid"],
                            status="terminated",
                            values=dict(row),
                            effective_from=row["active_from"],
                            effective_to=row["active_to"],
                            actor="legacy",
                        ),
                    )
                items = [
                    r.model_copy(update={"status": "active"})
                    for r in by_interval.values()
                    if (
                        not relationship_type
                        or r.relationship_type == relationship_type
                    )
                    and (
                        not entity_uid
                        or entity_uid in (r.source_uid, r.target_uid, r.relationship_id)
                    )
                    and (not r.effective_from or timestamp(r.effective_from) <= at)
                    and (not r.effective_to or timestamp(r.effective_to) > at)
                ]
            return RelationshipPage(
                items=items, total=len(items), revision=self._revision(conn, site_id)
            )

    def fit_ap_overview(self, site_id, ac_uuid):
        with closing(self.database(site_id).connect_readonly()) as conn:
            columns = {
                r[1] for r in conn.execute("PRAGMA table_info(ac_fit_ap_resources)")
            }
            if "ac_device_uuid" not in columns:
                return dict(
                    ac_device_uuid=ac_uuid, total=0, items=[], service_stations=[]
                )
            selected = [
                c
                for c in (
                    "ap_uuid",
                    "ap_name",
                    "station",
                    "online_status",
                    "management_ip",
                )
                if c in columns
            ]
            items = (
                [
                    dict(r)
                    for r in conn.execute(
                        "SELECT "
                        + ",".join(selected)
                        + " FROM ac_fit_ap_resources WHERE ac_device_uuid=? LIMIT 200",
                        (ac_uuid,),
                    )
                ]
                if selected
                else []
            )
            total = conn.execute(
                "SELECT count(*) FROM ac_fit_ap_resources WHERE ac_device_uuid=?",
                (ac_uuid,),
            ).fetchone()[0]
            stations = [
                dict(r)
                for r in conn.execute(
                    "SELECT n.node_uid,n.official_name FROM rail_infra_ac_service s JOIN rail_infra_node n ON n.node_uid=s.node_uid WHERE s.ac_device_uuid=?",
                    (ac_uuid,),
                )
            ]
            return dict(
                ac_device_uuid=ac_uuid,
                total=total,
                items=items,
                service_stations=stations,
                identity_inferred=False,
            )

    def list_history(
        self, site_id, *, relationship_type="", entity_uid="", page=1, page_size=100
    ):
        with closing(self.database(site_id).connect_readonly()) as conn:
            self._require_schema(conn)
            clauses, args = [], []
            if relationship_type:
                clauses.append("relation_type=?")
                args.append(relationship_type)
            if entity_uid:
                clauses.append("(source_uid=? OR target_uid=? OR relation_id=?)")
                args.extend([entity_uid] * 3)
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            total = conn.execute(
                "SELECT count(*) FROM rail_infra_relation_history" + where, args
            ).fetchone()[0]
            rows = conn.execute(
                "SELECT * FROM rail_infra_relation_history"
                + where
                + " ORDER BY changed_at DESC,rowid DESC LIMIT ? OFFSET ?",
                [*args, page_size, (page - 1) * page_size],
            ).fetchall()
            items = [
                RelationshipHistoryRecord(
                    event_id=r["event_id"],
                    relationship_type=r["relation_type"],
                    relationship_id=r["relation_id"],
                    action=r["action"],
                    source_uid=r["source_uid"],
                    target_uid=r["target_uid"],
                    before=json.loads(r["before_json"]),
                    after=json.loads(r["after_json"]),
                    effective_from=r["effective_from"] or "",
                    effective_to=r["effective_to"] or "",
                    reason=r["reason"],
                    actor=r["actor"],
                    changed_at=r["changed_at"],
                    revision=r["revision"],
                )
                for r in rows
            ]
            return RelationshipHistoryPage(items=items, total=total)

    def catalog(self, site_id, *, nodes, sections):
        with closing(self.database(site_id).connect_readonly()) as conn:
            self._require_schema(conn)
            # No credentials or raw observations leave the Repository.
            devices = [
                dict(r)
                for r in conn.execute(
                    "SELECT d.device_uuid,d.name,COALESCE(d.device_type,'') AS device_type,COALESCE(g.name,'') AS group_name FROM devices d LEFT JOIN device_groups g ON g.id=d.group_id ORDER BY d.name"
                )
            ]
            projects = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM rail_infra_project ORDER BY name,project_id"
                )
            ]
            existing_nodes = [
                dict(r)
                for r in conn.execute(
                    "SELECT node_uid AS uid,node_type AS kind,code,official_name AS name FROM rail_infra_node UNION ALL SELECT train_uid,'train',train_no,name FROM rail_infra_train"
                )
            ]
            by_uid = {n["uid"]: n for n in nodes}
            for n in existing_nodes:
                # Keep the canonical station ID projection when overlaying the
                # stored node facts; the write guard must recognize the same
                # existing station binding rather than reject it as foreign.
                by_uid[n["uid"]] = {**by_uid.get(n["uid"], {}), **n}
            return dict(
                nodes=list(by_uid.values()),
                sections=sections,
                devices=devices,
                projects=projects,
                revision=self._revision(conn, site_id),
            )

    def mutate(self, req, *, context, preview=False):
        payload = req.model_dump(mode="json")
        canonical = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        request_hash = hashlib.sha256(canonical.encode()).hexdigest()
        op_id = req.idempotency_key or request_hash
        with closing(self.database(req.site_id).connect()) as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                self._require_schema(conn)
                replay = conn.execute(
                    "SELECT request_hash,response_json FROM rail_infra_relation_audit WHERE audit_id=?",
                    (op_id,),
                ).fetchone()
                if replay:
                    if replay["request_hash"] != request_hash:
                        raise RelationshipError(
                            "RELATION_CONFLICT", "重复操作标识对应了不同请求"
                        )
                    conn.rollback()
                    return RelationshipMutationResult.model_validate_json(
                        replay["response_json"]
                    )
                if (
                    self._revision(conn, req.site_id) != req.base_revision
                    or context["revision"] != req.base_revision
                ):
                    raise RelationshipError(
                        "BASE_DATA_REVISION_CONFLICT",
                        "工程关系已变化，请保留草稿并刷新预览",
                    )
                changes = []
                targets = (
                    list(dict.fromkeys(req.target_uids))
                    if req.target_uids
                    else [req.target_uid]
                )
                if len(targets) > 1 and (
                    req.relationship_type != "ac_service" or req.action != "create"
                ):
                    raise RelationshipError(
                        "RELATION_INVALID", "只有 AC 服务站点支持批量关联"
                    )
                result_record = None
                for target in targets:
                    change_request = req.model_copy(
                        update={
                            "target_uid": target,
                            "effective_to": timestamp(req.effective_to, now())
                            if req.action == "terminate"
                            else req.effective_to,
                        }
                    )
                    before, after = self._change(conn, change_request, context)
                    if before == after:
                        result_record = after
                        continue
                    changed = now()
                    if req.action == "replace":
                        ended = before.model_copy(
                            update={
                                "status": "terminated",
                                "effective_to": after.effective_from,
                            }
                        )
                        changes.append(
                            self._record_event(
                                conn, req, before, ended, "terminate", changed
                            )
                        )
                        changes.append(
                            self._record_event(
                                conn, req, None, after, "replace", changed
                            )
                        )
                    else:
                        state = after or before.model_copy(
                            update={
                                "status": "terminated",
                                "effective_to": change_request.effective_to,
                            }
                        )
                        changes.append(
                            self._record_event(
                                conn, req, before, state, req.action, changed
                            )
                        )
                    result_record = after
                revision = self._revision(conn, req.site_id)
                for change in changes:
                    change["after"]["revision"] = revision
                    conn.execute(
                        "UPDATE rail_infra_relation_history SET revision=?,after_json=? WHERE event_id=?",
                        (
                            revision,
                            json.dumps(change["after"], ensure_ascii=False),
                            change["event_id"],
                        ),
                    )
                    conn.execute(
                        "UPDATE rail_infra_relation_state SET state_json=? WHERE relation_id=?",
                        (
                            json.dumps(change["after"], ensure_ascii=False),
                            change["after"]["relationship_id"],
                        ),
                    )
                if result_record:
                    result_record.revision = revision
                result = RelationshipMutationResult(
                    relationship=result_record,
                    revision=revision,
                    history_event_id=changes[-1]["event_id"] if changes else "",
                    changes=changes,
                    preview=preview,
                )
                if preview:
                    conn.rollback()
                    return result
                conn.execute(
                    "INSERT INTO rail_infra_relation_audit(audit_id,event_id,site_id,operation,payload_json,response_json,request_hash,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        op_id,
                        result.history_event_id or None,
                        req.site_id,
                        req.action,
                        canonical,
                        result.model_dump_json(),
                        request_hash,
                        now(),
                    ),
                )
                conn.commit()
                return result
            except sqlite3.IntegrityError as exc:
                conn.rollback()
                raise RelationshipError(
                    "RELATION_CONFLICT", "关系违反唯一性或引用约束，未写入任何变更"
                ) from exc
            except Exception:
                conn.rollback()
                raise

    def _change(self, conn, req, context):
        kind = req.relationship_type
        records = self._records(conn, kind)
        before = (
            next((r for r in records if r.relationship_id == req.relationship_id), None)
            if req.relationship_id
            else next(
                (
                    r
                    for r in records
                    if r.source_uid == req.source_uid and r.target_uid == req.target_uid
                ),
                None,
            )
        )
        if req.action != "create" and before is None:
            raise RelationshipError("RELATION_NOT_FOUND", "关系不存在或已经结束")
        if req.action == "replace" and kind != "train_mr":
            raise RelationshipError("RELATION_INVALID", "更换操作只适用于列车 MR")
        source = req.source_uid or (before.source_uid if before else "")
        target = req.target_uid or (before.target_uid if before else "")
        if (
            before
            and req.action in {"update", "terminate"}
            and (source != before.source_uid or target != before.target_uid)
        ):
            raise RelationshipError("RELATION_CONFLICT", "不能使用关系 ID 修改其他对象")
        table, skey, tkey = TABLES[kind]
        if req.action == "terminate":
            end = timestamp(req.effective_to, now())
            if before.effective_from and end <= timestamp(before.effective_from):
                raise RelationshipError(
                    "RELATION_TIME_INVALID", "结束时间必须晚于生效时间"
                )
            self._end(conn, before, end)
            return before, None
        if req.effective_to:
            raise RelationshipError("RELATION_INVALID", "结束时间仅用于解除关系")
        values = {**(before.values if before else {}), **req.values}
        begin = timestamp(
            req.effective_from,
            before.effective_from if before and req.action == "update" else now(),
        )
        if (
            before
            and req.action == "update"
            and before.effective_from
            and begin < timestamp(before.effective_from)
        ):
            raise RelationshipError(
                "RELATION_TIME_INVALID", "属性变更不能早于该关系原生效时间"
            )
        nodes = {n["uid"]: n for n in context["nodes"]}
        devices = {d["device_uuid"]: d for d in context["devices"]}
        sections = {s["id"]: s for s in context["sections"]}
        projects = {p["project_id"]: p for p in context["projects"]}

        def need(mapping, uid, label):
            if uid not in mapping:
                raise RelationshipError(
                    "RELATION_REFERENCE_MISSING", f"{label}不存在或没有正式稳定 ID"
                )
            return mapping[uid]

        def node(uid):
            n = need(nodes, uid, "工程节点")
            if n["kind"] == "train":
                if not conn.execute(
                    "SELECT 1 FROM rail_infra_train WHERE train_uid=?", (uid,)
                ).fetchone():
                    conn.execute(
                        "INSERT INTO rail_infra_train VALUES(?,?,?)",
                        (uid, n["code"], n["name"]),
                    )
            else:
                conn.execute(
                    "INSERT OR IGNORE INTO rail_infra_node VALUES(?,?,?,?)",
                    (uid, n["kind"], n["code"], n["name"]),
                )
            return n

        if kind == "node_project":
            n = node(source)
            if n["kind"] != "station":
                raise RelationshipError("RELATION_INVALID", "建设项目关联需要正式车站")
            need(projects, target, "建设项目")
            values = {
                skey: source,
                tkey: target,
                "relationship_status": str(
                    values.get("relationship_status") or "active"
                ),
            }
        elif kind == "device_node":
            n = node(source)
            if n["kind"] == "train":
                raise RelationshipError("RELATION_INVALID", "列车 MR 使用独立关系")
            need(devices, target, "设备")
            if any(r.target_uid == target and r.source_uid != source for r in records):
                raise RelationshipError(
                    "RELATION_CONFLICT",
                    "设备已有主要安装节点；服务多区间应使用工程服务范围",
                )
            binding = conn.execute(
                "SELECT station_id FROM devices WHERE device_uuid=?", (target,)
            ).fetchone()
            legacy_ids = {source, str(n.get("station", {}).get("id", ""))}
            if binding and binding[0] and binding[0] not in legacy_ids:
                raise RelationshipError(
                    "RELATION_CONFLICT", "设备已有正式单站点绑定，不能被工程关系覆盖"
                )
            values = {
                skey: source,
                tkey: target,
                "engineering_role": str(values.get("engineering_role") or ""),
                "installation_location": str(values.get("installation_location") or ""),
            }
        elif kind == "device_section":
            need(devices, source, "设备")
            need(sections, target, "正式区间")
            values = {
                skey: source,
                tkey: target,
                "engineering_role": str(values.get("engineering_role") or ""),
                "installation_location": str(values.get("installation_location") or ""),
            }
        elif kind == "ac_service":
            d = need(devices, source, "AC")
            if d["device_type"].lower() not in {"ac", "wireless_controller"}:
                raise RelationshipError("RELATION_INVALID", "服务源设备必须是 AC")
            n = node(target)
            if n["kind"] == "train":
                raise RelationshipError("RELATION_INVALID", "AC 服务对象必须是工程站点")
            values = {
                skey: source,
                tkey: target,
                "relationship_status": str(
                    values.get("relationship_status") or "active"
                ),
            }
        else:
            n = node(source)
            if n["kind"] != "train":
                raise RelationshipError("RELATION_INVALID", "MR 必须关联列车")
            d = need(devices, target, "MR")
            if (
                d["device_type"].lower() not in {"mr", "cloud-ap", "vehicle_mr"}
                and d["group_name"] != "车载-MR"
            ):
                raise RelationshipError("RELATION_INVALID", "关联设备必须是已有车载 MR")
            position = values.get("position", "")
            if position not in {"CT", "CW"}:
                raise RelationshipError("RELATION_INVALID", "MR 角色必须为 CT 或 CW")
            if req.action == "replace":
                if (
                    source != before.source_uid
                    or position != before.values["position"]
                    or target == before.target_uid
                ):
                    raise RelationshipError(
                        "RELATION_CONFLICT", "MR 更换必须保留列车和端位，并选择其他设备"
                    )
                self._end(conn, before, begin)
            history = conn.execute(
                "SELECT * FROM rail_infra_train_mr WHERE (train_uid=? AND position=?) OR device_uuid=?",
                (source, position, target),
            ).fetchall()
            for h in history:
                if before and h["assignment_id"] == before.relationship_id:
                    continue
                if h["active_to"] is None or timestamp(h["active_to"]) > begin:
                    raise RelationshipError(
                        "RELATION_CONFLICT", "该列车端位或 MR 的生效时间与已有关系重叠"
                    )
            rid = (
                before.relationship_id
                if before and req.action == "update"
                else (
                    req.relationship_id
                    if req.action == "create" and req.relationship_id
                    else str(uuid4())
                )
            )
            values = {
                "assignment_id": rid,
                skey: source,
                tkey: target,
                "position": position,
                "active_from": begin,
                "active_to": None,
            }
        if before and req.action == "create":
            if all(
                before.values.get(k) == v
                for k, v in values.items()
                if k not in {"active_from", "assignment_id", "active_to"}
            ):
                return before, before
            raise RelationshipError("RELATION_CONFLICT", "关系已存在，请使用修改操作")
        rid = (
            values["assignment_id"]
            if kind == "train_mr"
            else json.dumps(
                [kind, source, target], ensure_ascii=False, separators=(",", ":")
            )
        )
        if kind == "train_mr":
            if req.action == "update":
                conn.execute(
                    "UPDATE rail_infra_train_mr SET active_from=?,position=? WHERE assignment_id=?",
                    (begin, values["position"], rid),
                )
            else:
                conn.execute(
                    "INSERT INTO rail_infra_train_mr VALUES(?,?,?,?,?,NULL)",
                    (rid, source, target, values["position"], begin),
                )
        elif kind == "device_node":
            conn.execute(
                "INSERT INTO rail_infra_device_link(node_uid,device_uuid,engineering_role,section_uid) VALUES(?,?,?,NULL) ON CONFLICT(node_uid,device_uuid) DO UPDATE SET engineering_role=excluded.engineering_role",
                (source, target, values["engineering_role"]),
            )
        elif kind == "device_section":
            conn.execute(
                "INSERT INTO rail_infra_device_section VALUES(?,?,?,?) ON CONFLICT(device_uuid,section_uid) DO UPDATE SET engineering_role=excluded.engineering_role,installation_location=excluded.installation_location",
                (
                    source,
                    target,
                    values["engineering_role"],
                    values["installation_location"],
                ),
            )
        else:
            conn.execute(
                f"INSERT OR IGNORE INTO {table}({skey},{tkey}) VALUES(?,?)",
                (source, target),
            )
        after = RelationshipRecord(
            relationship_type=kind,
            relationship_id=rid,
            source_uid=source,
            target_uid=target,
            status="active",
            values=values,
            effective_from=begin,
            created_at=before.created_at if before else "",
        )
        names = {
            **{k: v["name"] for k, v in nodes.items()},
            **{k: v["name"] for k, v in devices.items()},
            **{k: v["name"] for k, v in projects.items()},
            **{k: v.get("name", k) for k, v in sections.items()},
        }
        after.source_name = names.get(source, source)
        after.target_name = names.get(target, target)
        return before, after

    def _record_event(self, conn, req, before, state, action, changed):
        state.updated_at = changed
        state.created_at = state.created_at or changed
        state.actor = req.actor or "desktop-session"
        state.reason = req.reason.strip()
        event_id = str(uuid4())
        conn.execute(
            "INSERT INTO rail_infra_relation_state VALUES(?,?,?,?,?) "
            "ON CONFLICT(relation_id) DO UPDATE SET state_json=excluded.state_json",
            (
                state.relationship_id,
                state.relationship_type,
                state.source_uid,
                state.target_uid,
                state.model_dump_json(),
            ),
        )
        conn.execute(
            "INSERT INTO rail_infra_relation_history(event_id,relation_type,relation_id,action,source_uid,target_uid,before_json,after_json,effective_from,effective_to,reason,actor,changed_at,revision) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                event_id,
                state.relationship_type,
                state.relationship_id,
                action,
                state.source_uid,
                state.target_uid,
                before.model_dump_json() if before else "{}",
                state.model_dump_json(),
                state.effective_from,
                state.effective_to,
                state.reason,
                state.actor,
                changed,
                "",
            ),
        )
        return dict(
            event_id=event_id,
            before=before.model_dump(mode="json") if before else {},
            after=state.model_dump(mode="json"),
        )

    def _end(self, conn, record, end):
        if record.effective_from and timestamp(record.effective_from) >= end:
            raise RelationshipError(
                "RELATION_TIME_INVALID", "结束时间必须晚于原关系生效时间"
            )
        table, source, target = TABLES[record.relationship_type]
        if record.relationship_type == "train_mr":
            conn.execute(
                "UPDATE rail_infra_train_mr SET active_to=? WHERE assignment_id=? AND active_to IS NULL",
                (end, record.relationship_id),
            )
        else:
            conn.execute(
                f"DELETE FROM {table} WHERE {source}=? AND {target}=?",
                (record.source_uid, record.target_uid),
            )

    def deletion_preflight(self, site_id, entity_uid):
        with closing(self.database(site_id).connect_readonly()) as conn:
            self._require_schema(conn)
            current = len(self._records(conn, entity_uid=entity_uid))
            history = conn.execute(
                "SELECT count(*) FROM rail_infra_relation_history WHERE source_uid=? OR target_uid=?",
                (entity_uid, entity_uid),
            ).fetchone()[0]
            return dict(
                entity_uid=entity_uid,
                current_relationships=current,
                historical_relationships=history,
                can_delete=False,
                external_reference_checks={
                    "tasks": "NOT_VERIFIED",
                    "reports": "NOT_VERIFIED",
                    "ap_identity": "NOT_VERIFIED",
                    "online_mr_sessions": "NOT_VERIFIED",
                },
                reason="工程对象不在关系接口删除；请使用资产/基础资料删除预检，历史证据必须保留",
            )

    def save_project(self, site_id, payload, *, preview=False):
        name = payload["name"].strip()
        if not name:
            raise RelationshipError("RELATION_INVALID", "项目名称不能为空")
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        request_hash = hashlib.sha256(canonical.encode()).hexdigest()
        op_id = payload["idempotency_key"]
        with closing(self.database(site_id).connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            self._require_schema(conn)
            replay = conn.execute(
                "SELECT request_hash,response_json FROM rail_infra_relation_audit WHERE audit_id=?",
                (op_id,),
            ).fetchone()
            if replay:
                if replay["request_hash"] != request_hash:
                    raise RelationshipError(
                        "RELATION_CONFLICT", "重复操作标识对应不同请求"
                    )
                return json.loads(replay["response_json"])
            if self._revision(conn, site_id) != payload.get("base_revision"):
                raise RelationshipError("BASE_DATA_REVISION_CONFLICT", "基础资料已变化")
            pid = payload.get("project_id") or str(uuid4())
            previous = conn.execute(
                "SELECT * FROM rail_infra_project WHERE project_id=?", (pid,)
            ).fetchone()
            if payload.get("project_id") and not previous:
                raise RelationshipError("RELATION_REFERENCE_MISSING", "项目不存在")
            conn.execute(
                "INSERT INTO rail_infra_project VALUES(?,?,?) ON CONFLICT(project_id) DO UPDATE SET name=excluded.name,stage=excluded.stage",
                (pid, name, payload.get("stage", "")),
            )
            eid = str(uuid4())
            after = dict(project_id=pid, name=name, stage=payload.get("stage", ""))
            conn.execute(
                "INSERT INTO rail_infra_relation_history(event_id,relation_type,relation_id,action,source_uid,target_uid,before_json,after_json,reason,actor,changed_at,revision) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    eid,
                    "project",
                    pid,
                    "update" if previous else "create",
                    pid,
                    pid,
                    json.dumps(dict(previous), ensure_ascii=False)
                    if previous
                    else "{}",
                    json.dumps(after, ensure_ascii=False),
                    payload.get("reason", ""),
                    "desktop-session",
                    now(),
                    "",
                ),
            )
            rev = self._revision(conn, site_id)
            conn.execute(
                "UPDATE rail_infra_relation_history SET revision=? WHERE event_id=?",
                (rev, eid),
            )
            response = dict(**after, revision=rev, preview=preview)
            if preview:
                conn.rollback()
                return response
            conn.execute(
                "INSERT INTO rail_infra_relation_audit VALUES(?,?,?,?,?,?,?,?)",
                (
                    op_id,
                    eid,
                    site_id,
                    "project",
                    canonical,
                    json.dumps(response, ensure_ascii=False),
                    request_hash,
                    now(),
                ),
            )
            return response
