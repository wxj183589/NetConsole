"""Read and maintain site-specific engineering relationships."""

from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from netconsole.core.database import Database
from netconsole.core.rail_infrastructure_schema import RAIL_INFRASTRUCTURE_TABLES
from netconsole.models.device_detail import normalize_device_role
from netconsole.models.api.rail_infrastructure import (
    InfrastructureDeviceDTO,
    InfrastructureNameDTO,
    InfrastructureProjectDTO,
)
from netconsole.repositories.rail_relationship_repository import RelationshipError, now

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
            if not (RAIL_INFRASTRUCTURE_TABLES - {"rail_infra_device_section", "rail_infra_relation_history", "rail_infra_relation_audit", "rail_infra_relation_state"}).issubset(tables):
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
