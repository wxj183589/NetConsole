from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any, Mapping

from netconsole.core.database import Database


DEFAULT_ALLOCATION_STRATEGY = "station_then_point"
STATION_INDEPENDENT = "station_independent"


class ApManagementVlanRevisionConflict(RuntimeError):
    pass


class ApManagementVlanRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def get_draft(self) -> dict[str, object]:
        with self.database.connect_readonly() as connection:
            return self.get_draft_from_connection(connection)

    @staticmethod
    def get_draft_from_connection(
        connection: sqlite3.Connection,
    ) -> dict[str, object]:
        plan = connection.execute(
            """
            SELECT line_id, planning_mode, auto_group_station_count,
                   address_allocation_strategy, revision, created_at, updated_at
            FROM rail_ap_vlan_plans
            ORDER BY line_id
            LIMIT 1
            """
        ).fetchone()
        if plan is None:
            return {
                "planning": {
                    "line_id": "current",
                    "planning_mode": STATION_INDEPENDENT,
                    "auto_group_station_count": 1,
                    "address_allocation_strategy": DEFAULT_ALLOCATION_STRATEGY,
                    "revision": 0,
                    "updated_at": "",
                },
                "groups": [],
                "assignments": [],
                "allocations": [],
            }
        line_id = str(plan["line_id"])
        group_rows = connection.execute(
            """
            SELECT group_id, line_id, group_code, group_name, sequence,
                   management_vlan, legacy_management_vlans, network_address,
                   prefix_length, subnet_mask, default_gateway, ap_start_ip,
                   ap_end_ip, address_allocation_strategy, notes,
                   created_at, updated_at
            FROM rail_ap_vlan_groups
            WHERE line_id = ?
            ORDER BY sequence, group_code
            """,
            (line_id,),
        ).fetchall()
        members_by_group: dict[str, list[dict[str, object]]] = {}
        for row in connection.execute(
            """
            SELECT m.group_id, m.station_id, m.station_name,
                   m.station_sequence, m.ap_count
            FROM rail_ap_vlan_group_members AS m
            JOIN rail_ap_vlan_groups AS g ON g.group_id = m.group_id
            WHERE g.line_id = ?
            ORDER BY g.sequence, m.station_sequence, m.station_name
            """,
            (line_id,),
        ):
            members_by_group.setdefault(str(row["group_id"]), []).append(dict(row))
        groups = []
        for row in group_rows:
            group = dict(row)
            group["members"] = members_by_group.get(str(row["group_id"]), [])
            groups.append(group)
        group_ids = [str(row["group_id"]) for row in group_rows]
        assignments: list[dict[str, object]] = []
        allocations: list[dict[str, object]] = []
        if group_ids:
            placeholders = ", ".join("?" for _ in group_ids)
            assignments = [
                dict(row)
                for row in connection.execute(
                    f"""
                    SELECT assignment_id, assignment_type, target_id, group_id,
                           source, created_at, updated_at
                    FROM rail_ap_vlan_assignments
                    WHERE group_id IN ({placeholders})
                    ORDER BY assignment_type, target_id
                    """,
                    group_ids,
                )
            ]
            allocations = [
                {
                    **dict(row),
                    "is_manual": bool(row["is_manual"]),
                    "is_locked": bool(row["is_locked"]),
                }
                for row in connection.execute(
                    f"""
                    SELECT ap_id, ap_name, point_code, station_id, station_name,
                           section_name, group_id, planned_ip, allocation_order,
                           is_manual, is_locked, source, group_source, created_at,
                           updated_at
                    FROM rail_ap_vlan_allocations
                    WHERE group_id IN ({placeholders})
                    ORDER BY group_id, allocation_order, ap_id
                    """,
                    group_ids,
                )
            ]
        return {
            "planning": dict(plan),
            "groups": groups,
            "assignments": assignments,
            "allocations": allocations,
        }

    def replace(
        self,
        draft: Mapping[str, Any],
        *,
        expected_revision: int,
    ) -> int:
        with self.database.connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                revision = self.replace_with_connection(
                    connection,
                    draft,
                    expected_revision=expected_revision,
                )
                connection.commit()
                return revision
            except Exception:
                connection.rollback()
                raise

    @classmethod
    def replace_with_connection(
        cls,
        connection: sqlite3.Connection,
        draft: Mapping[str, Any],
        *,
        expected_revision: int,
    ) -> int:
        normalized = draft
        planning = dict(normalized["planning"])
        current = connection.execute(
            "SELECT revision, created_at FROM rail_ap_vlan_plans WHERE line_id = ?",
            (str(planning["line_id"]),),
        ).fetchone()
        current_revision = int(current["revision"]) if current is not None else 0
        if current_revision != int(expected_revision):
            raise ApManagementVlanRevisionConflict(
                "AP 管理 VLAN 规划已被其他编辑会话更新"
            )
        now = datetime.now(timezone.utc).isoformat()
        next_revision = current_revision + 1
        created_at = str(current["created_at"] or now) if current is not None else now
        line_id = str(planning["line_id"])
        old_group_created = {
            str(row["group_id"]): str(row["created_at"] or now)
            for row in connection.execute(
                "SELECT group_id, created_at FROM rail_ap_vlan_groups WHERE line_id = ?",
                (line_id,),
            )
        }
        connection.execute(
            "DELETE FROM rail_ap_vlan_groups WHERE line_id = ?",
            (line_id,),
        )
        connection.execute(
            """
            INSERT INTO rail_ap_vlan_plans (
                line_id, planning_mode, auto_group_station_count,
                address_allocation_strategy, revision, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(line_id) DO UPDATE SET
                planning_mode = excluded.planning_mode,
                auto_group_station_count = excluded.auto_group_station_count,
                address_allocation_strategy = excluded.address_allocation_strategy,
                revision = excluded.revision,
                updated_at = excluded.updated_at
            """,
            (
                line_id,
                str(planning["planning_mode"]),
                int(planning["auto_group_station_count"]),
                str(planning["address_allocation_strategy"]),
                next_revision,
                created_at,
                now,
            ),
        )
        for group in normalized["groups"]:
            group_id = str(group["group_id"])
            group_created = old_group_created.get(group_id, now)
            connection.execute(
                """
                INSERT INTO rail_ap_vlan_groups (
                    group_id, line_id, group_code, group_name, sequence,
                    management_vlan, legacy_management_vlans, network_address,
                    prefix_length, subnet_mask, default_gateway, ap_start_ip,
                    ap_end_ip, address_allocation_strategy, notes,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    group_id,
                    line_id,
                    str(group["group_code"]),
                    str(group["group_name"]),
                    int(group["sequence"]),
                    group.get("management_vlan"),
                    str(group.get("legacy_management_vlans") or ""),
                    str(group.get("network_address") or ""),
                    group.get("prefix_length"),
                    str(group.get("subnet_mask") or ""),
                    str(group.get("default_gateway") or ""),
                    str(group.get("ap_start_ip") or ""),
                    str(group.get("ap_end_ip") or ""),
                    str(
                        group.get("address_allocation_strategy")
                        or DEFAULT_ALLOCATION_STRATEGY
                    ),
                    str(group.get("notes") or ""),
                    group_created,
                    now,
                ),
            )
            for member in group["members"]:
                connection.execute(
                    """
                    INSERT INTO rail_ap_vlan_group_members (
                        group_id, station_id, station_name, station_sequence,
                        ap_count, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        group_id,
                        str(member["station_id"]),
                        str(member["station_name"]),
                        int(member["station_sequence"]),
                        max(0, int(member.get("ap_count") or 0)),
                        now,
                        now,
                    ),
                )
        for assignment in normalized["assignments"]:
            connection.execute(
                """
                INSERT INTO rail_ap_vlan_assignments (
                    assignment_id, assignment_type, target_id, group_id,
                    source, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(assignment["assignment_id"]),
                    str(assignment["assignment_type"]),
                    str(assignment["target_id"]),
                    str(assignment["group_id"]),
                    str(assignment["source"]),
                    now,
                    now,
                ),
            )
        for allocation in normalized["allocations"]:
            planned_ip = str(allocation.get("planned_ip") or "").strip()
            if not planned_ip:
                continue
            connection.execute(
                """
                INSERT INTO rail_ap_vlan_allocations (
                    ap_id, ap_name, point_code, station_id, station_name,
                    section_name, group_id, planned_ip, allocation_order,
                    is_manual, is_locked, source, group_source,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(allocation["ap_id"]),
                    str(allocation.get("ap_name") or ""),
                    str(allocation.get("point_code") or ""),
                    str(allocation.get("station_id") or ""),
                    str(allocation.get("station_name") or ""),
                    str(allocation.get("section_name") or ""),
                    str(allocation["group_id"]),
                    planned_ip,
                    int(allocation.get("allocation_order") or 0),
                    int(bool(allocation.get("is_manual"))),
                    int(bool(allocation.get("is_locked"))),
                    str(allocation.get("source") or "generated"),
                    str(allocation.get("group_source") or ""),
                    now,
                    now,
                ),
            )
        cls._replace_legacy_projection(connection, normalized, now)
        return next_revision

    def list_export_rows(self) -> list[dict[str, object]]:
        draft = self.get_draft()
        if draft["groups"]:
            return self._export_rows(draft)
        with self.database.connect() as connection:
            rows = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT station_name, ap_count, ap_start_address,
                           mask_length, ap_gateway, ap_management_vlans,
                           remark, sort_order
                    FROM ac_trackside_ap_plan
                    WHERE mode = 'unified'
                    ORDER BY sort_order, station_name
                    """
                )
            ]
        if not rows:
            return []
        return [
            {
                "planning_mode": STATION_INDEPENDENT,
                "group_code": f"G{index + 1:03d}",
                "group_name": str(row["station_name"] or ""),
                "start_station_name": str(row["station_name"] or ""),
                "end_station_name": str(row["station_name"] or ""),
                "station_ids": "",
                "station_names": str(row["station_name"] or ""),
                "station_name": str(row["station_name"] or ""),
                "ap_count": int(row["ap_count"] or 0),
                "management_vlan": str(row["ap_management_vlans"] or ""),
                "network_address": "",
                "prefix_length": row["mask_length"],
                "subnet_mask": "",
                "default_gateway": str(row["ap_gateway"] or ""),
                "ap_start_ip": str(row["ap_start_address"] or ""),
                "ap_end_ip": "",
                "allocation_order": 0,
                "is_locked": False,
                "notes": str(row["remark"] or ""),
                "ap_start_address": str(row["ap_start_address"] or ""),
                "mask_length": row["mask_length"],
                "ap_gateway": str(row["ap_gateway"] or ""),
                "ap_management_vlans": str(row["ap_management_vlans"] or ""),
                "remark": str(row["remark"] or ""),
            }
            for index, row in enumerate(rows)
        ]

    @staticmethod
    def _export_rows(draft: Mapping[str, Any]) -> list[dict[str, object]]:
        planning = draft["planning"]
        allocations_by_station: dict[str, list[Mapping[str, Any]]] = {}
        for allocation in draft.get("allocations") or []:
            allocations_by_station.setdefault(
                str(allocation.get("station_id") or ""), []
            ).append(allocation)
        rows: list[dict[str, object]] = []
        for group in draft.get("groups") or []:
            members = list(group.get("members") or [])
            start_station = str(members[0].get("station_name") or "") if members else ""
            end_station = str(members[-1].get("station_name") or "") if members else ""
            for member in members or [{}]:
                station_allocations = allocations_by_station.get(
                    str(member.get("station_id") or ""), []
                )
                vlan = group.get("management_vlan")
                rows.append(
                    {
                        "planning_mode": planning["planning_mode"],
                        "group_code": group["group_code"],
                        "group_name": group["group_name"],
                        "start_station_name": start_station,
                        "end_station_name": end_station,
                        "station_ids": ",".join(
                            str(item["station_id"]) for item in members
                        ),
                        "station_names": "、".join(
                            str(item["station_name"]) for item in members
                        ),
                        "station_name": str(member.get("station_name") or ""),
                        "ap_count": int(member.get("ap_count") or 0),
                        "management_vlan": vlan,
                        "network_address": group.get("network_address") or "",
                        "prefix_length": group.get("prefix_length"),
                        "subnet_mask": group.get("subnet_mask") or "",
                        "default_gateway": group.get("default_gateway") or "",
                        "ap_start_ip": group.get("ap_start_ip") or "",
                        "ap_end_ip": group.get("ap_end_ip") or "",
                        "allocation_order": min(
                            (
                                int(row.get("allocation_order") or 0)
                                for row in station_allocations
                            ),
                            default=0,
                        ),
                        "is_locked": any(
                            bool(row.get("is_locked"))
                            for row in station_allocations
                        ),
                        "notes": group.get("notes") or "",
                        "ap_start_address": group.get("ap_start_ip") or "",
                        "mask_length": group.get("prefix_length"),
                        "ap_gateway": group.get("default_gateway") or "",
                        "ap_management_vlans": str(vlan or ""),
                        "remark": group.get("notes") or "",
                    }
                )
        return rows

    @staticmethod
    def _replace_legacy_projection(
        connection: sqlite3.Connection,
        draft: Mapping[str, Any],
        now: str,
    ) -> None:
        connection.execute("DELETE FROM ac_trackside_ap_plan WHERE mode = 'unified'")
        fields = (
            "mode",
            "station_name",
            "ap_count",
            "ap_start_address",
            "mask_length",
            "ap_gateway",
            "ap_management_vlans",
            "remark",
            "sort_order",
            "created_at",
            "updated_at",
        )
        for group in draft.get("groups") or []:
            vlan_text = str(group.get("legacy_management_vlans") or "").strip()
            if not vlan_text and group.get("management_vlan") is not None:
                vlan_text = str(group["management_vlan"])
            for member in group.get("members") or []:
                values = (
                    "unified",
                    str(member.get("station_name") or ""),
                    int(member.get("ap_count") or 0),
                    str(group.get("ap_start_ip") or ""),
                    group.get("prefix_length"),
                    str(group.get("default_gateway") or ""),
                    vlan_text,
                    str(group.get("notes") or ""),
                    int(member.get("station_sequence") or 0),
                    now,
                    now,
                )
                connection.execute(
                    f"""
                    INSERT INTO ac_trackside_ap_plan ({", ".join(fields)})
                    VALUES ({", ".join("?" for _ in fields)})
                    """,
                    values,
                )


__all__ = [
    "ApManagementVlanRepository",
    "ApManagementVlanRevisionConflict",
]
