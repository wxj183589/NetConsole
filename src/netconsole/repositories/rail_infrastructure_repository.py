"""Read and maintain site-specific engineering relationships."""

from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass, field
import json
from typing import Any
from uuid import uuid4

from netconsole.core.database import Database
from netconsole.core.rail_infrastructure_schema import RAIL_INFRASTRUCTURE_TABLES
from netconsole.models.device_detail import normalize_device_role
from netconsole.models.api.rail_infrastructure import (
    InfrastructureDeviceDTO,
    InfrastructureNameDTO,
    InfrastructureProjectDTO,
    OrganizationAssetChangeDTO,
    OrganizationAssetDTO,
    OrganizationBatchRequest,
    OrganizationBatchResultDTO,
    OrganizationCatalogDTO,
    OrganizationNodeRequest,
)
from netconsole.repositories.rail_relationship_repository import RelationshipError, now
from netconsole.models.api.rail_relationship import RelationshipRecord

_DEVICE_FIELDS = "d.device_uuid AS device_uuid, d.name AS name, COALESCE(d.device_type, '') AS device_type, COALESCE(d.device_vendor, '') AS vendor"
_ORGANIZATION_MARKER = "rail_organization_initialized_v1"


@dataclass
class InfrastructureFacts:
    schema_available: bool = False
    organization_initialized: bool = False
    nodes: list[dict[str, Any]] = field(default_factory=list)
    devices: list[dict[str, Any]] = field(default_factory=list)
    links: dict[str, list[InfrastructureDeviceDTO]] = field(default_factory=lambda: defaultdict(list))
    aliases: dict[str, list[InfrastructureNameDTO]] = field(default_factory=lambda: defaultdict(list))
    projects: dict[str, list[InfrastructureProjectDTO]] = field(default_factory=lambda: defaultdict(list))
    device_service_stations: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    section_links: dict[str, list[InfrastructureDeviceDTO]] = field(default_factory=lambda: defaultdict(list))
    service_stations: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))


class RailInfrastructureRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def read(self) -> InfrastructureFacts:
        facts = InfrastructureFacts()
        if not self.database.exists():
            return facts
        with closing(self.database.connect_readonly()) as conn, conn:
            conn.execute("BEGIN")
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            if "devices" not in tables:
                return facts
            columns = {row[1] for row in conn.execute("PRAGMA table_info(devices)")}
            station_id = "d.station_id" if "station_id" in columns else "'' AS station_id"
            facts.devices = [
                dict(row) for row in conn.execute(
                    f"SELECT {_DEVICE_FIELDS}, {station_id} FROM devices d ORDER BY d.name, d.device_uuid"
                )
            ]
            if not (RAIL_INFRASTRUCTURE_TABLES - {"rail_infra_device_section", "rail_infra_relation_history", "rail_infra_relation_audit", "rail_infra_relation_state", "rail_infra_node_layout"}).issubset(tables):
                return facts
            facts.schema_available = True
            facts.organization_initialized = self._organization_initialized(conn)
            facts.nodes = [
                dict(row) for row in conn.execute(
                    "SELECT node_uid AS uid, node_type AS kind, code, official_name AS name "
                    "FROM rail_infra_node UNION ALL "
                    "SELECT train_uid, 'train', train_no, name FROM rail_infra_train ORDER BY code, uid"
                )
            ]
            if "rail_infra_node_layout" in tables:
                layouts = {
                    row["node_uid"]: dict(row)
                    for row in conn.execute("SELECT * FROM rail_infra_node_layout")
                }
                for node in facts.nodes:
                    layout = layouts.get(node["uid"])
                    if layout:
                        node["parent_uid"] = layout["parent_uid"] or ""
                        node["sort_order"] = layout["sort_order"]
                        node["custom"] = bool(layout["custom"])
                        node["name"] = layout["display_name"] or node["name"]
                        node["code"] = layout["display_code"]
            for row in conn.execute(
                f"SELECT l.node_uid AS uid, {_DEVICE_FIELDS}, l.engineering_role AS role, l.section_uid "
                "FROM rail_infra_device_link l JOIN devices d ON d.device_uuid = l.device_uuid "
                "UNION ALL "
                f"SELECT a.train_uid, {_DEVICE_FIELDS}, 'MR-' || a.position, NULL "
                "FROM rail_infra_train_mr a JOIN devices d ON d.device_uuid = a.device_uuid "
                "WHERE a.active_to IS NULL ORDER BY role, name, device_uuid"
            ):
                values = dict(row)
                uid = values.pop("uid")
                facts.links[uid].append(InfrastructureDeviceDTO(
                    **values, source="engineering", device_role=normalize_device_role(values["device_type"], vendor=values.get("vendor"), platform=values.get("platform")),
                ))
            for row in conn.execute(
                "SELECT node_uid, name, name_type, source, valid_from, valid_to FROM rail_infra_node_name "
                "ORDER BY name_type, valid_from DESC, name_id"
            ):
                values = dict(row)
                uid = values.pop("node_uid")
                facts.aliases[uid].append(InfrastructureNameDTO(**values))
            for row in conn.execute(
                "SELECT n.node_uid, p.project_id, p.name, p.stage FROM rail_infra_node_project n "
                "JOIN rail_infra_project p ON p.project_id = n.project_id ORDER BY p.stage, p.project_id"
            ):
                values = dict(row)
                uid = values.pop("node_uid")
                facts.projects[uid].append(InfrastructureProjectDTO(**values))
            section_rows = conn.execute(
                f"SELECT s.section_uid, {_DEVICE_FIELDS}, s.engineering_role AS role "
                "FROM rail_infra_device_section s JOIN devices d ON d.device_uuid=s.device_uuid"
            ) if "rail_infra_device_section" in tables else []
            for row in section_rows:
                values = dict(row)
                uid = values.pop("section_uid")
                facts.section_links[uid].append(InfrastructureDeviceDTO(
                    **values, source="engineering", device_role=normalize_device_role(values["device_type"], vendor=values.get("vendor"), platform=values.get("platform"))))
            for row in conn.execute(
                "SELECT a.ac_device_uuid, station.code, station.official_name FROM rail_infra_ac_service a "
                "JOIN rail_infra_node station ON station.node_uid=a.node_uid ORDER BY station.code"
            ):
                facts.device_service_stations[row["ac_device_uuid"]].append(f"{row['code']} {row['official_name']}".strip())
            for row in conn.execute(
                "SELECT l.node_uid AS owner_uid, station.code, station.official_name "
                "FROM rail_infra_device_link l JOIN rail_infra_ac_service a ON a.ac_device_uuid = l.device_uuid "
                "JOIN rail_infra_node station ON station.node_uid = a.node_uid "
                "ORDER BY station.code, station.node_uid"
            ):
                label = f"{row['code']} {row['official_name']}".strip()
                if label not in facts.service_stations[row["owner_uid"]]:
                    facts.service_stations[row["owner_uid"]].append(label)
        return facts

    @staticmethod
    def _organization_initialized(conn) -> bool:
        return conn.execute(
            "SELECT 1 FROM schema_metadata WHERE key=?", (_ORGANIZATION_MARKER,)
        ).fetchone() is not None

    def base_revision(self) -> str:
        with closing(self.database.connect_readonly()) as conn:
            return self._base_revision(conn)

    @staticmethod
    def _base_revision(conn) -> str:
        row = conn.execute(
            "SELECT value FROM schema_metadata WHERE key='base_data_revision'"
        ).fetchone()
        return str(row[0]) if row is not None else "0"

    def initialize_organization(self, site_id: str, stations: dict[str, dict], revision: str) -> None:
        if not self.database.exists():
            raise RelationshipError("RELATION_REFERENCE_MISSING", "局点数据库不存在")
        with closing(self.database.connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            if self._organization_initialized(conn):
                return
            if self._base_revision(conn) != revision:
                raise RelationshipError("BASE_DATA_REVISION_CONFLICT", "工程资料已变化，请刷新后重试")
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"rail_infra_node", "rail_infra_device_link", "rail_infra_train_mr", "device_groups"} <= tables:
                raise RelationshipError("RELATION_MIGRATION_REQUIRED", "局点数据库需要升级")

            centers = {}
            for kind in ("cocc", "bocc"):
                matches = conn.execute(
                    "SELECT node_uid FROM rail_infra_node WHERE node_type=?", (kind,)
                ).fetchall()
                if not matches:
                    uid = uuid4().hex
                    conn.execute(
                        "INSERT INTO rail_infra_node VALUES (?, ?, '', ?)", (uid, kind, kind.upper())
                    )
                    centers[kind.upper()] = uid
                elif len(matches) == 1:
                    centers[kind.upper()] = matches[0]["node_uid"]

            rows = conn.execute(
                f"SELECT {_DEVICE_FIELDS}, d.station_id, COALESCE(g.name, '') AS group_name "
                "FROM devices d LEFT JOIN device_groups g ON g.id=d.group_id AND g.site_id=? "
                "WHERE NOT EXISTS (SELECT 1 FROM rail_infra_device_link l WHERE l.device_uuid=d.device_uuid) "
                "AND NOT EXISTS (SELECT 1 FROM rail_infra_train_mr m WHERE m.device_uuid=d.device_uuid AND m.active_to IS NULL)",
                (site_id,),
            )
            for device in rows:
                role = normalize_device_role(device["device_type"], vendor=device["vendor"])
                if role in {"access_point", "mobile_router"}:
                    continue
                group = device["group_name"].strip().upper()
                uid = centers.get(group)
                if group in {"车站", "车辆段", "停车场"}:
                    station = stations.get(device["station_id"])
                    expected_kind = {"车站": "station", "车辆段": "depot", "停车场": "parking_yard"}[group]
                    if station is None or station["kind"] != expected_kind:
                        continue
                    uid = station["uid"]
                    conn.execute(
                        "INSERT INTO rail_infra_node(node_uid, node_type, code, official_name) "
                        "VALUES (:uid, :kind, :code, :name) ON CONFLICT(node_uid) DO NOTHING",
                        station,
                    )
                if uid:
                    conn.execute(
                        "INSERT INTO rail_infra_device_link(node_uid, device_uuid) VALUES (?, ?)",
                        (uid, device["device_uuid"]),
                    )
            changed = now()
            conn.execute(
                "INSERT INTO schema_metadata(key, value, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (_ORGANIZATION_MARKER, "device_groups", changed, changed),
            )

    @staticmethod
    def _organization_assets(conn, site_id: str) -> list[OrganizationAssetDTO]:
        device_columns = {row["name"] for row in conn.execute("PRAGMA table_info(devices)")}
        serial = (
            "COALESCE(df.serial_number, '')"
            if "device_facts" in {
                row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            else "''"
        )
        facts_join = "LEFT JOIN device_facts df ON df.device_uuid=d.device_uuid" if "device_facts" in {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        } else ""
        mac = "COALESCE(d.mac_address, '')" if "mac_address" in device_columns else "''"
        links = defaultdict(list)
        projects = defaultdict(list)
        for row in conn.execute(
            "SELECT device_uuid, node_uid FROM rail_infra_device_link "
            "UNION SELECT device_uuid, train_uid FROM rail_infra_train_mr WHERE active_to IS NULL "
            "ORDER BY device_uuid, node_uid"
        ):
            links[row["device_uuid"]].append(row["node_uid"])
        for row in conn.execute("SELECT device_uuid, project_id FROM rail_infra_device_project ORDER BY project_id"):
            projects[row["device_uuid"]].append(row["project_id"])
        return [
            OrganizationAssetDTO(
                **dict(row), node_uids=links[row["device_uuid"]], project_ids=projects[row["device_uuid"]]
            )
            for row in conn.execute(
                "SELECT d.device_uuid, d.name, COALESCE(d.primary_address, '') AS address, "
                f"{mac} AS mac, {serial} AS serial, "
                "COALESCE(d.device_type, '') AS device_type, COALESCE(g.name, '') AS group_name, "
                "COALESCE(d.work_scope_status, 'included') AS collection FROM devices d "
                f"{facts_join} LEFT JOIN device_groups g ON g.id=d.group_id AND g.site_id=? ORDER BY d.name, d.device_uuid",
                (site_id,),
            )
        ]

    def organization_catalog(self, site_id: str) -> OrganizationCatalogDTO:
        with closing(self.database.connect_readonly()) as conn, conn:
            conn.execute("BEGIN")
            if not self._organization_initialized(conn):
                raise RelationshipError("ORGANIZATION_NOT_INITIALIZED", "请先初始化组织结构")
            projects = [
                InfrastructureProjectDTO(**dict(row)) for row in conn.execute(
                    "SELECT project_id, name, stage FROM rail_infra_project ORDER BY stage, name"
                )
            ]
            return OrganizationCatalogDTO(
                revision=self._base_revision(conn), projects=projects, devices=self._organization_assets(conn, site_id)
            )

    def save_organization_node(self, site_id: str, request: OrganizationNodeRequest) -> str:
        with closing(self.database.connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            if not self._organization_initialized(conn) or self._base_revision(conn) != request.revision:
                raise RelationshipError("BASE_DATA_REVISION_CONFLICT", "设备或组织已变化，请刷新")
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='rail_infra_relation_audit'"
            ).fetchone() is None:
                raise RelationshipError("RELATION_MIGRATION_REQUIRED", "组织历史记录需要局点数据库升级")
            if not conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='rail_infra_node_layout'"
            ).fetchone():
                raise RelationshipError("RELATION_MIGRATION_REQUIRED", "组织层级需要局点数据库升级")
            nodes = {
                row["node_uid"]: dict(row) for row in conn.execute(
                    "SELECT n.*, l.parent_uid, l.display_name, l.display_code, l.sort_order, l.custom "
                    "FROM rail_infra_node n LEFT JOIN rail_infra_node_layout l USING(node_uid)"
                )
            }
            before = nodes.get(request.node_uid)
            name = request.name.strip()
            if not name or (request.node_uid and not before):
                raise RelationshipError("RELATION_INVALID", "组织名称或节点无效")
            if before and before["node_type"] != request.kind:
                raise RelationshipError("RELATION_INVALID", "既有节点的组织类型不可修改")
            uid = request.node_uid or uuid4().hex
            parent = request.parent_uid
            visited = {uid}
            while parent:
                ancestor = nodes.get(parent)
                if parent in visited or not ancestor or ancestor["node_type"] != request.kind:
                    raise RelationshipError("RELATION_INVALID", "上级组织不兼容或形成循环")
                visited.add(parent)
                parent = ancestor["parent_uid"]

            changed_at = now()
            if before is None:
                conn.execute(
                    "INSERT INTO rail_infra_node VALUES (?, ?, '', ?)", (uid, request.kind, name)
                )
            else:
                previous_name = before["display_name"] or before["official_name"]
                if previous_name != name:
                    conn.execute(
                        "INSERT INTO rail_infra_node_name(name_id,node_uid,name,name_type,source,valid_to) "
                        "VALUES (?, ?, ?, 'historical', 'organization', ?)",
                        (uuid4().hex, uid, previous_name, changed_at),
                    )
            conn.execute(
                "INSERT INTO rail_infra_node_layout VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(node_uid) DO UPDATE SET parent_uid=excluded.parent_uid, "
                "display_name=excluded.display_name, display_code=excluded.display_code, sort_order=excluded.sort_order",
                (uid, request.parent_uid or None, name, request.code.strip(), request.sort_order, int(not before)),
            )
            conn.execute(
                "INSERT INTO rail_infra_relation_audit(audit_id,site_id,operation,payload_json,created_at) "
                "VALUES (?, ?, 'organization_node', ?, ?)",
                (uuid4().hex, site_id, json.dumps({"before": before, "after": request.model_dump(), "uid": uid}), changed_at),
            )
            return uid

    def change_organization_assets(
        self, site_id: str, request: OrganizationBatchRequest, *, preview: bool,
    ) -> OrganizationBatchResultDTO:
        with closing(self.database.connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            if not self._organization_initialized(conn) or self._base_revision(conn) != request.revision:
                raise RelationshipError("BASE_DATA_REVISION_CONFLICT", "设备或组织已变化，请刷新预览")
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='rail_infra_relation_audit'"
            ).fetchone() is None:
                raise RelationshipError("RELATION_MIGRATION_REQUIRED", "组织历史记录需要局点数据库升级")
            assets = {asset.device_uuid: asset for asset in self._organization_assets(conn, site_id)}
            device_ids = set(request.device_uuids)
            additions, removals = set(request.add_projects), set(request.remove_projects)
            projects = {row[0] for row in conn.execute("SELECT project_id FROM rail_infra_project")}
            if not device_ids <= assets.keys() or not (additions | removals) <= projects or additions & removals:
                raise RelationshipError("RELATION_INVALID", "设备或建设项目选择无效")
            if request.node_uid and not conn.execute(
                "SELECT 1 FROM rail_infra_node WHERE node_uid=?", (request.node_uid,)
            ).fetchone():
                raise RelationshipError("RELATION_REFERENCE_MISSING", "目标组织不可用")
            changes = []
            for device_uuid in dict.fromkeys(request.device_uuids):
                asset = assets[device_uuid]
                nodes = asset.node_uids
                if request.node_uid:
                    self._validate_organization_move(conn, device_uuid, request.node_uid, nodes)
                    nodes = [request.node_uid]
                result = asset.model_copy(update={
                    "collection": request.collection or asset.collection,
                    "node_uids": nodes,
                    "project_ids": sorted((set(asset.project_ids) | additions) - removals),
                })
                if result != asset:
                    changes.append(OrganizationAssetChangeDTO(before=asset, after=result))
            if not preview and changes:
                self._write_organization_assets(conn, site_id, changes)
            return OrganizationBatchResultDTO(revision=self._base_revision(conn), changes=changes)

    @staticmethod
    def _validate_organization_move(conn, device_uuid: str, target: str, current: list[str]) -> None:
        row = conn.execute(
            "SELECT device_type, device_vendor, station_id FROM devices WHERE device_uuid=?", (device_uuid,)
        ).fetchone()
        role = normalize_device_role(row["device_type"], vendor=row["device_vendor"])
        if role in {"mobile_router", "access_point"} or len(current) > 1:
            raise RelationshipError("RELATION_INVALID", "AP、车载 MR 或多重工程归属需要使用专用关系")
        if conn.execute(
            "SELECT 1 FROM rail_infra_train_mr WHERE device_uuid=? AND active_to IS NULL", (device_uuid,)
        ).fetchone():
            raise RelationshipError("RELATION_INVALID", "列车资产需要使用专用关系")
        if row["station_id"] and target not in current:
            raise RelationshipError("RELATION_CONFLICT", "设备有正式站点绑定，请先核对工程资料")

    @staticmethod
    def _write_organization_assets(conn, site_id: str, changes: list[OrganizationAssetChangeDTO]) -> None:
        changed_at = now()
        history_events = []
        for change in changes:
            before, after = change.before, change.after
            uid = before.device_uuid
            if after.node_uids != before.node_uids:
                for node_uid in before.node_uids:
                    conn.execute(
                        "DELETE FROM rail_infra_device_link WHERE node_uid=? AND device_uuid=?",
                        (node_uid, uid),
                    )
                    history_events.append((node_uid, uid, "terminate"))
                for node_uid in after.node_uids:
                    conn.execute(
                        "INSERT INTO rail_infra_device_link(node_uid, device_uuid) VALUES (?, ?)",
                        (node_uid, uid),
                    )
                    history_events.append((node_uid, uid, "create"))
            if before.collection != after.collection:
                conn.execute(
                    "UPDATE devices SET work_scope_status=?, work_scope_reason=NULL, work_scope_updated_at=?, "
                    "work_scope_updated_by='organization', updated_at=? WHERE device_uuid=?",
                    (after.collection, changed_at, changed_at, uid),
                )
            for project in set(after.project_ids) - set(before.project_ids):
                conn.execute(
                    "INSERT INTO rail_infra_device_project(device_uuid, project_id) VALUES (?, ?)", (uid, project)
                )
            for project in set(before.project_ids) - set(after.project_ids):
                conn.execute(
                    "DELETE FROM rail_infra_device_project WHERE device_uuid=? AND project_id=?", (uid, project)
                )
        event_id = uuid4().hex
        # Store only stable identities and changed attributes in the engineering audit.
        payload = [
            change.model_dump(include={
                "before": {"device_uuid", "node_uids", "collection", "project_ids"},
                "after": {"device_uuid", "node_uids", "collection", "project_ids"},
            }) for change in changes
        ]
        conn.execute(
            "INSERT INTO rail_infra_relation_audit(audit_id, site_id, operation, payload_json, created_at) "
            "VALUES (?, ?, 'organization_assets', ?, ?)", (event_id, site_id, json.dumps(payload), changed_at)
        )
        for node_uid, device_uuid, action in history_events:
            relationship_id = json.dumps(
                ["device_node", node_uid, device_uuid], ensure_ascii=False, separators=(",", ":")
            )
            record = RelationshipRecord(
                relationship_type="device_node",
                relationship_id=relationship_id,
                source_uid=node_uid,
                target_uid=device_uuid,
                source_name=node_uid,
                target_name=device_uuid,
                status="active" if action == "create" else "terminated",
                created_at=changed_at,
                updated_at=changed_at,
                actor="organization",
                reason="组织结构设备批量变更",
            )
            state = record.model_dump_json()
            conn.execute(
                "INSERT INTO rail_infra_relation_history "
                "(event_id,relation_type,relation_id,action,source_uid,target_uid,before_json,after_json,actor,reason,changed_at) "
                "VALUES (?, 'device_node', ?, ?, ?, ?, '{}', ?, 'organization', ?, ?)",
                (uuid4().hex, relationship_id, action, node_uid, device_uuid, state, record.reason, changed_at),
            )
            conn.execute(
                "INSERT INTO rail_infra_relation_state VALUES (?, 'device_node', ?, ?, ?) "
                "ON CONFLICT(relation_id) DO UPDATE SET state_json=excluded.state_json",
                (relationship_id, node_uid, device_uuid, state),
            )
        # Project-only edits also invalidate outstanding organization previews.
        conn.execute(
            "UPDATE schema_metadata SET value=CAST(CAST(value AS INTEGER)+1 AS TEXT), updated_at=? "
            "WHERE key='base_data_revision'", (changed_at,)
        )

    def end_train_mr_assignment(self, assignment_id: str, device_uuid: str, ended_at: str) -> bool:
        """End only the requested active assignment. Keep the device and its history."""
        with closing(self.database.connect()) as conn, conn:
            cursor = conn.execute(
                "UPDATE rail_infra_train_mr SET active_to = ? "
                "WHERE assignment_id = ? AND device_uuid = ? AND active_to IS NULL",
                (ended_at, assignment_id, device_uuid),
            )
            return cursor.rowcount == 1

    def mr_assignments(self) -> tuple[list[dict[str, Any]], set[str], set[tuple[str, str]]]:
        """Current explicit assignments and legacy identities superseded by engineering."""
        with closing(self.database.connect_readonly()) as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='rail_infra_train_mr'").fetchone():
                return [], set(), set()
            rows = [dict(r) for r in conn.execute(
                "SELECT a.*,t.train_no,t.name AS train_name FROM rail_infra_train_mr a "
                "JOIN rail_infra_train t ON t.train_uid=a.train_uid"
            )]
            return ([r for r in rows if not r['active_to']],
                    {r['device_uuid'] for r in rows}, {(r['train_no'], r['position']) for r in rows})
