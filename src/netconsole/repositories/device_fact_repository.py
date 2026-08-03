from __future__ import annotations

import json
from datetime import datetime
from uuid import uuid4

from netconsole.core.database import Database
from netconsole.core.optical_severity_engine import (
    is_zte_optical_record,
    normalize_zte_optical_record,
)
from netconsole.utils.interface_normalize import normalize_interface_name
from netconsole.utils.interface_sort import interface_sort_key
from netconsole.utils.natural_sort import natural_text_key


FACT_FIELDS = (
    "device_uuid",
    "sysname",
    "model",
    "serial_number",
    "mac_address",
    "software_version",
    "bootrom_version",
    "vendor",
    "uptime",
    "collected_at",
    "collect_run_uuid",
    "raw_log_path",
    "updated_at",
)

INTERFACE_FIELDS = (
    "device_uuid",
    "interface_name",
    "link_status",
    "admin_status",
    "physical_status",
    "protocol_status",
    "media_attribute",
    "media_type",
    "category",
    "speed",
    "duplex",
    "interface_type",
    "port_status",
    "port_mode",
    "pvid",
    "native_vlan",
    "tagged_vlans",
    "untagged_vlans",
    "pvid_source",
    "pvid_verified",
    "vlan_config_status",
    "vlan_config_collected_at",
    "vlan_warnings",
    "description",
    "ip_address",
    "mac_address",
    "vlan",
    "last_change",
    "collected_at",
    "collect_run_uuid",
    "raw_log_path",
    "updated_at",
)

OPTICAL_MODULE_FIELDS = (
    "device_uuid",
    "interface_name",
    "rx_power",
    "tx_power",
    "temperature",
    "voltage",
    "bias_current",
    "module_model",
    "module_serial_number",
    "module_vendor",
    "wavelength",
    "transmission_distance",
    "connector_type",
    "device_vendor",
    "device_reported_status",
    "threshold_source",
    "transceiver_mode",
    "vendor_part_number",
    "vendor_revision",
    "vendor_serial_number",
    "rx_low_alarm",
    "rx_high_alarm",
    "tx_low_alarm",
    "tx_high_alarm",
    "rx_low_warning",
    "rx_high_warning",
    "tx_low_warning",
    "tx_high_warning",
    "status",
    "collected_at",
    "collect_run_uuid",
    "raw_log_path",
    "updated_at",
)

LLDP_FIELDS = (
    "device_uuid",
    "local_interface",
    "scope",
    "chassis_type",
    "chassis_id",
    "neighbor_sysname",
    "neighbor_mac",
    "port_id_type",
    "neighbor_interface",
    "neighbor_ip",
    "holdtime",
    "ttl",
    "port_description",
    "system_description",
    "system_capabilities",
    "pvid",
    "operational_mau",
    "max_frame_size",
    "neighbor_device_uuid",
    "collected_at",
    "collect_run_uuid",
    "raw_log_path",
    "updated_at",
)

FACT_HISTORY_FIELDS = (*FACT_FIELDS, "created_at")
INTERFACE_HISTORY_FIELDS = (*INTERFACE_FIELDS, "created_at")
OPTICAL_MODULE_HISTORY_FIELDS = (*OPTICAL_MODULE_FIELDS, "created_at")
LLDP_HISTORY_FIELDS = (*LLDP_FIELDS, "created_at")

COLLECT_RUN_FIELDS = (
    "collect_run_uuid",
    "collect_type",
    "status",
    "started_at",
    "ended_at",
    "raw_log_dir",
    "error_message",
    "created_at",
)

_PAGE_SORT_FIELDS = {
    "device_interfaces": frozenset(
        {
            "interface_name",
            "link_status",
            "admin_status",
            "physical_status",
            "protocol_status",
            "speed",
            "duplex",
            "media_type",
            "category",
            "port_mode",
            "pvid",
            "description",
            "collected_at",
        }
    ),
    "device_optical_modules": frozenset(
        {
            "interface_name",
            "rx_power",
            "tx_power",
            "temperature",
            "voltage",
            "bias_current",
            "module_model",
            "module_serial_number",
            "module_vendor",
            "wavelength",
            "transmission_distance",
            "connector_type",
            "collected_at",
        }
    ),
    "device_lldp_neighbors": frozenset(
        {
            "local_interface",
            "neighbor_sysname",
            "neighbor_mac",
            "neighbor_interface",
            "neighbor_ip",
            "pvid",
            "ttl",
            "port_description",
            "collected_at",
        }
    ),
}
_INTERFACE_NATURAL_SORT_FIELDS = frozenset(
    {"interface_name", "local_interface", "neighbor_interface"}
)
_NATURAL_TEXT_SORT_FIELDS = frozenset({"neighbor_sysname", "module_model"})
_NUMERIC_SORT_FIELDS = frozenset(
    {
        "pvid",
        "ttl",
        "rx_power",
        "tx_power",
        "temperature",
        "voltage",
        "bias_current",
        "wavelength",
    }
)


class DeviceFactRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def upsert_device_fact(self, data: dict[str, object | None]) -> dict[str, object | None]:
        payload = self._payload(FACT_FIELDS, data)
        self._set_required_defaults(payload, ("collected_at", "updated_at"))
        columns = ", ".join(FACT_FIELDS)
        placeholders = ", ".join("?" for _ in FACT_FIELDS)
        updates = ", ".join(f"{field} = excluded.{field}" for field in FACT_FIELDS if field != "device_uuid")
        with self.database.connect() as conn:
            conn.execute(
                f"""
                INSERT INTO device_facts ({columns})
                VALUES ({placeholders})
                ON CONFLICT(device_uuid) DO UPDATE SET {updates}
                """,
                [payload[field] for field in FACT_FIELDS],
            )
            self._insert_history(conn, "device_facts_history", FACT_HISTORY_FIELDS, payload)
            conn.commit()
        return self.get_device_fact(str(payload["device_uuid"])) or payload

    def get_device_fact(self, device_uuid: str) -> dict[str, object | None] | None:
        with self.database.connect() as conn:
            row = conn.execute("SELECT * FROM device_facts WHERE device_uuid = ?", (device_uuid,)).fetchone()
        return dict(row) if row is not None else None

    def get_latest_raw_log_path(self, device_uuid: str) -> str | None:
        fact = self.get_device_fact(device_uuid)
        value = fact.get("raw_log_path") if fact else None
        return str(value) if value else None

    def update_latest_raw_log_path(self, device_uuid: str, collect_run_uuid: str, raw_log_path: str) -> None:
        now = self._now()
        with self.database.connect() as conn:
            conn.execute(
                """
                UPDATE device_facts
                SET collect_run_uuid = ?, raw_log_path = ?, updated_at = ?
                WHERE device_uuid = ?
                """,
                (collect_run_uuid, raw_log_path, now, device_uuid),
            )
            conn.commit()

    def mark_device_collection_attempt(
        self,
        device_uuid: str,
        collect_run_uuid: str,
        raw_log_path: str = "",
    ) -> None:
        now = self._now()
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO device_facts (
                    device_uuid, collect_run_uuid, raw_log_path, collected_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(device_uuid) DO UPDATE SET
                    collect_run_uuid = excluded.collect_run_uuid,
                    raw_log_path = CASE
                        WHEN excluded.raw_log_path = '' THEN device_facts.raw_log_path
                        ELSE excluded.raw_log_path
                    END,
                    updated_at = excluded.updated_at
                """,
                (device_uuid, collect_run_uuid, raw_log_path, now, now),
            )
            conn.commit()

    def list_device_facts(self) -> list[dict[str, object | None]]:
        with self.database.connect() as conn:
            rows = conn.execute("SELECT * FROM device_facts ORDER BY sysname, device_uuid").fetchall()
        return [dict(row) for row in rows]

    def append_fact_history(self, data: dict[str, object | None]) -> None:
        payload = self._payload(FACT_HISTORY_FIELDS, data)
        self._set_required_defaults(payload, ("collected_at", "created_at"))
        with self.database.connect() as conn:
            self._insert(conn, "device_facts_history", FACT_HISTORY_FIELDS, payload)
            conn.commit()

    def replace_device_interfaces(self, device_uuid: str, interfaces: list[dict[str, object | None]]) -> None:
        if not interfaces:
            raise ValueError("接口快照为空，保留上一份有效数据")
        if any(not str(item.get("interface_name") or "").strip() for item in interfaces):
            raise ValueError("接口快照包含空接口名，保留上一份有效数据")
        now = self._now()
        with self.database.connect() as conn:
            conn.execute("DELETE FROM device_interfaces WHERE device_uuid = ?", (device_uuid,))
            for item in interfaces:
                payload = self._payload(INTERFACE_FIELDS, {**item, "device_uuid": device_uuid})
                for field in ("tagged_vlans", "untagged_vlans", "vlan_warnings"):
                    value = payload.get(field)
                    if isinstance(value, (list, tuple)):
                        payload[field] = json.dumps(
                            list(value),
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                if payload.get("pvid_verified") is not None:
                    payload["pvid_verified"] = int(bool(payload["pvid_verified"]))
                payload["collected_at"] = payload.get("collected_at") or now
                payload["updated_at"] = payload.get("updated_at") or now
                self._insert(conn, "device_interfaces", INTERFACE_FIELDS, payload)
                self._insert_history(conn, "device_interfaces_history", INTERFACE_HISTORY_FIELDS, payload)
            conn.commit()

    def list_device_interfaces(self, device_uuid: str) -> list[dict[str, object | None]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM device_interfaces WHERE device_uuid = ?",
                (device_uuid,),
            ).fetchall()
        latest = _latest_rows_by_interface([dict(row) for row in rows], "interface_name")
        return sorted(latest, key=lambda row: interface_sort_key(row.get("interface_name")))

    def list_device_interfaces_page(
        self,
        device_uuid: str,
        *,
        search: str = "",
        status: str = "",
        interface_type: str = "",
        admin_status: str = "",
        physical_status: str = "",
        protocol_status: str = "",
        media_type: str = "",
        sort_by: str = "interface_name",
        sort_order: str = "asc",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, object | None]], int]:
        clauses = ["device_uuid = ?"]
        params: list[object] = [device_uuid]
        _append_search_clause(clauses, params, search, _INTERFACE_SEARCH_FIELDS)
        selected_status = str(status or "").strip().casefold()
        if selected_status:
            clauses.append("LOWER(TRIM(COALESCE(link_status, ''))) = ?")
            params.append(selected_status)
        selected_type = str(interface_type or "").strip().casefold()
        if selected_type:
            clauses.append("LOWER(TRIM(COALESCE(interface_type, ''))) = ?")
            params.append(selected_type)
        for field, selected in (
            ("admin_status", admin_status),
            ("physical_status", physical_status),
            ("protocol_status", protocol_status),
            ("media_type", media_type),
        ):
            normalized = str(selected or "").strip().casefold()
            if normalized:
                clauses.append(f"LOWER(TRIM(COALESCE({field}, ''))) = ?")
                params.append(normalized)
        return self._current_page(
            "device_interfaces",
            "interface_name",
            clauses,
            params,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    def get_device_interface(
        self, device_uuid: str, interface_name: str
    ) -> dict[str, object | None] | None:
        return self._get_current_interface_row(
            "device_interfaces", "interface_name", device_uuid, interface_name
        )

    def append_interface_history(self, data: dict[str, object | None]) -> None:
        payload = self._payload(INTERFACE_HISTORY_FIELDS, data)
        self._set_required_defaults(payload, ("collected_at", "created_at"))
        with self.database.connect() as conn:
            self._insert(conn, "device_interfaces_history", INTERFACE_HISTORY_FIELDS, payload)
            conn.commit()

    def replace_optical_modules(self, device_uuid: str, modules: list[dict[str, object | None]]) -> None:
        if not modules:
            raise ValueError("光模块快照为空，保留上一份有效数据")
        if any(not str(item.get("interface_name") or "").strip() for item in modules):
            raise ValueError("光模块快照包含空接口名，保留上一份有效数据")
        now = self._now()
        with self.database.connect() as conn:
            conn.execute("DELETE FROM device_optical_modules WHERE device_uuid = ?", (device_uuid,))
            for item in modules:
                if is_zte_optical_record(item):
                    item = normalize_zte_optical_record(item)
                payload = self._payload(OPTICAL_MODULE_FIELDS, {**item, "device_uuid": device_uuid})
                payload["collected_at"] = payload.get("collected_at") or now
                payload["updated_at"] = payload.get("updated_at") or now
                self._insert(conn, "device_optical_modules", OPTICAL_MODULE_FIELDS, payload)
                self._insert_history(conn, "device_optical_modules_history", OPTICAL_MODULE_HISTORY_FIELDS, payload)
            conn.commit()

    def list_optical_modules(self, device_uuid: str) -> list[dict[str, object | None]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM device_optical_modules WHERE device_uuid = ?",
                (device_uuid,),
            ).fetchall()
        latest = _normalize_optical_rows(
            _latest_rows_by_interface([dict(row) for row in rows], "interface_name")
        )
        return sorted(latest, key=lambda row: interface_sort_key(row.get("interface_name")))

    def list_optical_modules_page(
        self,
        device_uuid: str,
        *,
        search: str = "",
        sort_by: str = "interface_name",
        sort_order: str = "asc",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, object | None]], int]:
        clauses = ["device_uuid = ?"]
        params: list[object] = [device_uuid]
        _append_search_clause(clauses, params, search, _OPTICAL_SEARCH_FIELDS)
        rows, total = self._current_page(
            "device_optical_modules",
            "interface_name",
            clauses,
            params,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        return _normalize_optical_rows(rows), total

    def list_optical_modules_bounded(
        self,
        device_uuid: str,
        *,
        search: str = "",
        sort_by: str = "interface_name",
        sort_order: str = "asc",
        limit: int = 1000,
    ) -> tuple[list[dict[str, object | None]], int, bool]:
        scan_limit = max(1, min(int(limit), 1000))
        clauses = ["device_uuid = ?"]
        params: list[object] = [device_uuid]
        _append_search_clause(clauses, params, search, _OPTICAL_SEARCH_FIELDS)
        where = " AND ".join(clauses)
        with self.database.connect() as conn:
            _register_sort_collations(conn)
            total_row = conn.execute(
                f"SELECT COUNT(*) AS total FROM device_optical_modules WHERE {where}",
                params,
            ).fetchone()
            rows = conn.execute(
                f"SELECT * FROM device_optical_modules WHERE {where} "
                f"ORDER BY {_page_order_clause('device_optical_modules', sort_by, sort_order)} "
                "LIMIT ?",
                [*params, scan_limit],
            ).fetchall()
        total = int(total_row["total"] if total_row is not None else 0)
        mapped = _normalize_optical_rows([dict(row) for row in rows])
        return mapped, total, total > len(mapped)

    def get_optical_module(
        self, device_uuid: str, interface_name: str
    ) -> dict[str, object | None] | None:
        row = self._get_current_interface_row(
            "device_optical_modules", "interface_name", device_uuid, interface_name
        )
        return _normalize_optical_row(row) if row is not None else None

    def append_optical_history(self, data: dict[str, object | None]) -> None:
        if is_zte_optical_record(data):
            data = normalize_zte_optical_record(data)
        payload = self._payload(OPTICAL_MODULE_HISTORY_FIELDS, data)
        self._set_required_defaults(payload, ("collected_at", "created_at"))
        with self.database.connect() as conn:
            self._insert(conn, "device_optical_modules_history", OPTICAL_MODULE_HISTORY_FIELDS, payload)
            conn.commit()

    def replace_lldp_neighbors(
        self,
        device_uuid: str,
        neighbors: list[dict[str, object | None]],
        *,
        preserve_existing: bool = True,
    ) -> None:
        now = self._now()
        with self.database.connect() as conn:
            existing_rows = (
                conn.execute(
                    "SELECT * FROM device_lldp_neighbors WHERE device_uuid = ?",
                    (device_uuid,),
                ).fetchall()
                if preserve_existing
                else ()
            )
            merged: dict[str, dict[str, object | None]] = {}
            passthrough: list[dict[str, object | None]] = []
            for row in existing_rows:
                item = dict(row)
                key = _lldp_neighbor_key(
                    item,
                    include_neighbor=not preserve_existing,
                )
                if key:
                    merged[key] = item
                else:
                    passthrough.append(item)
            current_payloads: list[dict[str, object | None]] = []
            for item in neighbors:
                payload = self._payload(LLDP_FIELDS, {**item, "device_uuid": device_uuid})
                payload["collected_at"] = payload.get("collected_at") or now
                payload["updated_at"] = payload.get("updated_at") or now
                key = _lldp_neighbor_key(
                    payload,
                    include_neighbor=not preserve_existing,
                )
                if key:
                    merged[key] = payload
                else:
                    passthrough.append(payload)
                current_payloads.append(payload)
            conn.execute("DELETE FROM device_lldp_neighbors WHERE device_uuid = ?", (device_uuid,))
            for payload in [*merged.values(), *passthrough]:
                self._insert(conn, "device_lldp_neighbors", LLDP_FIELDS, payload)
            for payload in current_payloads:
                self._insert_history(conn, "device_lldp_neighbors_history", LLDP_HISTORY_FIELDS, payload)
            conn.commit()

    def list_lldp_neighbors(self, device_uuid: str) -> list[dict[str, object | None]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM device_lldp_neighbors WHERE device_uuid = ?",
                (device_uuid,),
            ).fetchall()
        return sorted(
            (dict(row) for row in rows),
            key=lambda row: (
                interface_sort_key(row.get("local_interface")),
                natural_text_key(row.get("neighbor_sysname")),
                interface_sort_key(row.get("neighbor_interface")),
                int(row.get("id") or 0),
            ),
        )

    def list_lldp_neighbors_page(
        self,
        device_uuid: str,
        *,
        search: str = "",
        linked_only: bool = False,
        sort_by: str = "local_interface",
        sort_order: str = "asc",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, object | None]], int]:
        clauses = ["device_uuid = ?"]
        params: list[object] = [device_uuid]
        _append_search_clause(clauses, params, search, _LLDP_SEARCH_FIELDS)
        if linked_only:
            clauses.append("TRIM(COALESCE(neighbor_device_uuid, '')) != ''")
        return self._current_page(
            "device_lldp_neighbors",
            "local_interface",
            clauses,
            params,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    def list_lldp_neighbors_for_interface(
        self,
        device_uuid: str,
        local_interface: str,
        *,
        limit: int = 200,
    ) -> tuple[list[dict[str, object | None]], int, bool]:
        aliases = _interface_name_aliases(local_interface)
        if not aliases:
            return [], 0, False
        placeholders = ", ".join("?" for _ in aliases)
        params: list[object] = [device_uuid, *aliases]
        where = (
            "device_uuid = ? "
            f"AND LOWER(TRIM(local_interface)) IN ({placeholders})"
        )
        size = max(1, min(int(limit), 200))
        with self.database.connect() as conn:
            total_row = conn.execute(
                f"SELECT COUNT(*) AS total FROM device_lldp_neighbors WHERE {where}",
                params,
            ).fetchone()
            rows = conn.execute(
                f"SELECT * FROM device_lldp_neighbors WHERE {where} "
                "ORDER BY neighbor_sysname COLLATE NOCASE, id DESC LIMIT ?",
                [*params, size],
            ).fetchall()
        total = int(total_row["total"] if total_row is not None else 0)
        return [dict(row) for row in rows], total, total > len(rows)

    def append_lldp_history(self, data: dict[str, object | None]) -> None:
        payload = self._payload(LLDP_HISTORY_FIELDS, data)
        self._set_required_defaults(payload, ("collected_at", "created_at"))
        with self.database.connect() as conn:
            self._insert(conn, "device_lldp_neighbors_history", LLDP_HISTORY_FIELDS, payload)
            conn.commit()

    def list_fact_history(self, device_uuid: str) -> list[dict[str, object | None]]:
        return self._list_history("device_facts_history", "device_uuid = ?", (device_uuid,))

    def list_interface_history(self, device_uuid: str, interface_name: str) -> list[dict[str, object | None]]:
        return self._list_history(
            "device_interfaces_history",
            "device_uuid = ? AND interface_name = ?",
            (device_uuid, interface_name),
        )

    def list_optical_history(self, device_uuid: str, interface_name: str) -> list[dict[str, object | None]]:
        return _normalize_optical_rows(self._list_history(
            "device_optical_modules_history",
            "device_uuid = ? AND interface_name = ?",
            (device_uuid, interface_name),
        ))

    def list_all_optical_history(self, device_uuids: list[str] | None = None, limit: int = 100000) -> list[dict[str, object | None]]:
        params: list[object] = []
        where = ""
        if device_uuids is not None:
            device_uuids = [str(device_uuid) for device_uuid in device_uuids if str(device_uuid or "").strip()]
            if not device_uuids:
                return []
        if device_uuids:
            placeholders = ", ".join("?" for _ in device_uuids)
            where = f"WHERE device_uuid IN ({placeholders})"
            params.extend(device_uuids)
        params.append(limit)
        with self.database.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM device_optical_modules_history
                {where}
                ORDER BY collected_at DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return _normalize_optical_rows([dict(row) for row in rows])

    def get_previous_optical_history(
        self,
        device_uuid: str,
        interface_name: str,
        before_collected_at: str | None = None,
    ) -> dict[str, object | None] | None:
        if not device_uuid or not interface_name:
            return None
        params: list[object] = [device_uuid, interface_name]
        before_clause = ""
        if before_collected_at:
            before_clause = "AND collected_at < ?"
            params.append(before_collected_at)
        with self.database.connect() as conn:
            row = conn.execute(
                f"""
                SELECT * FROM device_optical_modules_history
                WHERE device_uuid = ?
                  AND interface_name = ?
                  {before_clause}
                  AND (
                    rx_power IS NOT NULL OR status IS NOT NULL OR rx_low_alarm IS NOT NULL OR rx_low_warning IS NOT NULL
                  )
                ORDER BY collected_at DESC, id DESC
                LIMIT 1
                """,
                params,
            ).fetchone()
        return _normalize_optical_row(dict(row)) if row is not None else None

    def list_lldp_history(self, device_uuid: str, local_interface: str) -> list[dict[str, object | None]]:
        return self._list_history(
            "device_lldp_neighbors_history",
            "device_uuid = ? AND local_interface = ?",
            (device_uuid, local_interface),
        )

    def list_object_history_page(
        self,
        history_kind: str,
        device_uuid: str,
        object_name: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, object | None]]:
        table, object_field = _device_object_history_source(history_kind)
        with self.database.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM {table} WHERE device_uuid = ? AND {object_field} = ? "
                "ORDER BY collected_at DESC, id DESC LIMIT ? OFFSET ?",
                (
                    device_uuid,
                    object_name,
                    max(1, min(int(limit), 200)),
                    max(0, int(offset)),
                ),
            ).fetchall()
        mapped = [dict(row) for row in rows]
        return (
            _normalize_optical_rows(mapped)
            if str(history_kind or "").strip().casefold() in {"optical", "optical_module"}
            else mapped
        )

    def count_object_history(self, history_kind: str, device_uuid: str, object_name: str) -> int:
        table, object_field = _device_object_history_source(history_kind)
        with self.database.connect() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) AS total FROM {table} WHERE device_uuid = ? AND {object_field} = ?",
                (device_uuid, object_name),
            ).fetchone()
        return int(row["total"] if row is not None else 0)

    def _current_page(
        self,
        table: str,
        order_field: str,
        clauses: list[str],
        params: list[object],
        *,
        limit: int,
        offset: int,
        sort_by: str,
        sort_order: str,
    ) -> tuple[list[dict[str, object | None]], int]:
        if table not in {
            "device_interfaces",
            "device_optical_modules",
            "device_lldp_neighbors",
        }:
            raise ValueError(f"不支持的设备当前快照表：{table}")
        if order_field not in {"interface_name", "local_interface"}:
            raise ValueError(f"不支持的设备快照排序字段：{order_field}")
        where = " AND ".join(clauses)
        size = max(1, min(int(limit), 200))
        start = max(0, int(offset))
        with self.database.connect() as conn:
            _register_sort_collations(conn)
            total_row = conn.execute(
                f"SELECT COUNT(*) AS total FROM {table} WHERE {where}", params
            ).fetchone()
            rows = conn.execute(
                f"SELECT * FROM {table} WHERE {where} "
                f"ORDER BY {_page_order_clause(table, sort_by or order_field, sort_order)} "
                "LIMIT ? OFFSET ?",
                [*params, size, start],
            ).fetchall()
        return (
            [dict(row) for row in rows],
            int(total_row["total"] if total_row is not None else 0),
        )

    def _get_current_interface_row(
        self,
        table: str,
        field: str,
        device_uuid: str,
        interface_name: str,
    ) -> dict[str, object | None] | None:
        if table not in {"device_interfaces", "device_optical_modules"}:
            raise ValueError(f"不支持的设备接口快照表：{table}")
        if field != "interface_name":
            raise ValueError(f"不支持的设备接口字段：{field}")
        aliases = _interface_name_aliases(interface_name)
        if not aliases:
            return None
        placeholders = ", ".join("?" for _ in aliases)
        with self.database.connect() as conn:
            row = conn.execute(
                f"SELECT * FROM {table} WHERE device_uuid = ? "
                f"AND LOWER(TRIM({field})) IN ({placeholders}) "
                "ORDER BY collected_at DESC, id DESC LIMIT 1",
                [device_uuid, *aliases],
            ).fetchone()
        return dict(row) if row is not None else None

    def current_snapshot_source(
        self, device_uuid: str, dataset: str
    ) -> dict[str, object | None] | None:
        tables = {
            "interfaces": "device_interfaces",
            "transceivers": "device_optical_modules",
            "lldp": "device_lldp_neighbors",
        }
        try:
            table = tables[str(dataset)]
        except KeyError as exc:
            raise ValueError("不支持的设备快照数据集") from exc
        with self.database.connect() as conn:
            row = conn.execute(
                f"SELECT collected_at, collect_run_uuid FROM {table} "
                "WHERE device_uuid = ? "
                "ORDER BY collected_at DESC, id DESC LIMIT 1",
                (device_uuid,),
            ).fetchone()
        if row is None:
            return None
        return {
            "collected_at": row["collected_at"],
            "collect_run_uuid": row["collect_run_uuid"],
            "task_id": None,
        }

    def create_collect_run(self, data: dict[str, object | None]) -> dict[str, object | None]:
        payload = self._payload(COLLECT_RUN_FIELDS, data)
        now = self._now()
        payload["collect_run_uuid"] = payload.get("collect_run_uuid") or str(uuid4())
        payload["started_at"] = payload.get("started_at") or now
        payload["created_at"] = payload.get("created_at") or now
        columns = ", ".join(COLLECT_RUN_FIELDS)
        placeholders = ", ".join("?" for _ in COLLECT_RUN_FIELDS)
        with self.database.connect() as conn:
            conn.execute(
                f"INSERT INTO collect_runs ({columns}) VALUES ({placeholders})",
                [payload[field] for field in COLLECT_RUN_FIELDS],
            )
            conn.commit()
        return self.get_collect_run(str(payload["collect_run_uuid"])) or payload

    def get_collect_run(self, collect_run_uuid: str) -> dict[str, object | None] | None:
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT * FROM collect_runs WHERE collect_run_uuid = ?",
                (collect_run_uuid,),
            ).fetchone()
        return dict(row) if row is not None else None

    def update_collect_run_status(
        self,
        collect_run_uuid: str,
        status: str,
        ended_at: str | None = None,
        error_message: str | None = None,
    ) -> dict[str, object | None] | None:
        ended = ended_at or self._now()
        with self.database.connect() as conn:
            conn.execute(
                """
                UPDATE collect_runs
                SET status = ?, ended_at = ?, error_message = ?
                WHERE collect_run_uuid = ?
                """,
                (status, ended, error_message, collect_run_uuid),
            )
            conn.commit()
        return self.get_collect_run(collect_run_uuid)

    @classmethod
    def _payload(cls, fields: tuple[str, ...], data: dict[str, object | None]) -> dict[str, object | None]:
        return {field: data.get(field) for field in fields}

    @classmethod
    def _set_required_defaults(cls, payload: dict[str, object | None], fields: tuple[str, ...]) -> None:
        now = cls._now()
        for field in fields:
            payload[field] = payload.get(field) or now

    @staticmethod
    def _insert(conn, table: str, fields: tuple[str, ...], payload: dict[str, object | None]) -> None:
        columns = ", ".join(fields)
        placeholders = ", ".join("?" for _ in fields)
        conn.execute(
            f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
            [payload[field] for field in fields],
        )

    @classmethod
    def _insert_history(cls, conn, table: str, fields: tuple[str, ...], payload: dict[str, object | None]) -> None:
        history_payload = {field: payload.get(field) for field in fields}
        history_payload["created_at"] = history_payload.get("created_at") or cls._now()
        cls._insert(conn, table, fields, history_payload)

    def _list_history(self, table: str, where: str, params: tuple[object, ...]) -> list[dict[str, object | None]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM {table} WHERE {where} ORDER BY collected_at DESC, id DESC",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")


def _compare_interface_names(left: str, right: str) -> int:
    left_key = interface_sort_key(left)
    right_key = interface_sort_key(right)
    return (left_key > right_key) - (left_key < right_key)


def _compare_natural_text(left: str, right: str) -> int:
    left_key = natural_text_key(left)
    right_key = natural_text_key(right)
    return (left_key > right_key) - (left_key < right_key)


def _register_sort_collations(conn) -> None:
    conn.create_collation("NETCONSOLE_INTERFACE_NATURAL", _compare_interface_names)
    conn.create_collation("NETCONSOLE_NATURAL_TEXT", _compare_natural_text)


def _page_order_clause(table: str, sort_by: str, sort_order: str) -> str:
    allowed = _PAGE_SORT_FIELDS.get(table)
    field = str(sort_by or "").strip()
    if allowed is None or field not in allowed:
        raise ValueError(f"不支持的设备详情排序字段：{field}")
    direction = str(sort_order or "").strip().casefold()
    if direction not in {"asc", "desc"}:
        raise ValueError("设备详情排序方向必须为 asc 或 desc")

    terms = [_field_order_term(field, direction)]
    default_interface = {
        "device_interfaces": "interface_name",
        "device_optical_modules": "interface_name",
        "device_lldp_neighbors": "local_interface",
    }[table]
    if field != default_interface:
        terms.append(_field_order_term(default_interface, "asc"))
    if table == "device_lldp_neighbors":
        if field != "neighbor_sysname":
            terms.append(_field_order_term("neighbor_sysname", "asc"))
        if field != "neighbor_interface":
            terms.append(_field_order_term("neighbor_interface", "asc"))
    terms.append("id ASC")
    return ", ".join(terms)


def _field_order_term(field: str, direction: str) -> str:
    empty_last = f"CASE WHEN TRIM(COALESCE({field}, '')) = '' THEN 1 ELSE 0 END"
    if field in _INTERFACE_NATURAL_SORT_FIELDS:
        value = f"{field} COLLATE NETCONSOLE_INTERFACE_NATURAL"
    elif field in _NATURAL_TEXT_SORT_FIELDS:
        value = f"{field} COLLATE NETCONSOLE_NATURAL_TEXT"
    elif field in _NUMERIC_SORT_FIELDS:
        value = f"CAST({field} AS REAL)"
    else:
        value = f"{field} COLLATE NOCASE"
    return f"{empty_last} ASC, {value} {direction.upper()}"


def _latest_rows_by_interface(rows: list[dict[str, object | None]], field: str) -> list[dict[str, object | None]]:
    latest: dict[str, dict[str, object | None]] = {}
    passthrough: list[dict[str, object | None]] = []
    for row in rows:
        interface_name = normalize_interface_name(row.get(field))
        key = interface_name.casefold()
        if not key:
            passthrough.append(row)
            continue
        current = latest.get(key)
        if current is None or _latest_fact_score(row) >= _latest_fact_score(current):
            latest[key] = row
    return [*latest.values(), *passthrough]


def _device_object_history_source(history_kind: str) -> tuple[str, str]:
    sources = {
        "interface": ("device_interfaces_history", "interface_name"),
        "optical": ("device_optical_modules_history", "interface_name"),
        "lldp": ("device_lldp_neighbors_history", "local_interface"),
    }
    try:
        return sources[str(history_kind or "").strip().casefold()]
    except KeyError as exc:
        raise ValueError(f"不支持的设备历史类型：{history_kind}") from exc


def _latest_fact_score(row: dict[str, object | None]) -> tuple[str, str, int]:
    return (
        str(row.get("collected_at") or ""),
        str(row.get("updated_at") or ""),
        _int_value(row.get("id")),
    )


def _int_value(value: object) -> int:
    try:
        return int(str(value or "0"))
    except ValueError:
        return 0


_INTERFACE_SEARCH_FIELDS = (
    "interface_name",
    "description",
    "media_type",
    "category",
    "ip_address",
    "mac_address",
    "vlan",
    "pvid",
)
_OPTICAL_SEARCH_FIELDS = (
    "interface_name",
    "module_model",
    "module_serial_number",
    "module_vendor",
)
_LLDP_SEARCH_FIELDS = (
    "local_interface",
    "neighbor_sysname",
    "neighbor_mac",
    "neighbor_interface",
    "neighbor_ip",
    "chassis_id",
    "port_description",
    "system_description",
    "neighbor_device_uuid",
)


def _append_search_clause(
    clauses: list[str],
    params: list[object],
    search: str,
    fields: tuple[str, ...],
) -> None:
    query = str(search or "").strip().casefold()
    if not query:
        return
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    clauses.append(
        "("
        + " OR ".join(
            f"LOWER(COALESCE({field}, '')) LIKE ? ESCAPE '\\'" for field in fields
        )
        + ")"
    )
    params.extend([f"%{escaped}%"] * len(fields))


def _normalize_optical_row(
    row: dict[str, object | None],
) -> dict[str, object | None]:
    if is_zte_optical_record(row):
        return normalize_zte_optical_record(row)
    return row


def _normalize_optical_rows(
    rows: list[dict[str, object | None]],
) -> list[dict[str, object | None]]:
    return [_normalize_optical_row(row) for row in rows]


def _interface_name_aliases(value: object) -> list[str]:
    raw = str(value or "").strip().rstrip(":")
    canonical = normalize_interface_name(raw)
    if not canonical:
        return []
    aliases = {raw.casefold(), canonical.casefold()}
    reverse_prefixes = (
        ("Ten-GigabitEthernet", ("XGE", "XGigabitEthernet", "TenGigabitEthernet")),
        ("GigabitEthernet", ("GE",)),
        ("Bridge-Aggregation", ("BAGG",)),
        ("Vlan-interface", ("VLAN",)),
    )
    for full, short_names in reverse_prefixes:
        if canonical.casefold().startswith(full.casefold()):
            suffix = canonical[len(full) :]
            aliases.update(f"{short}{suffix}".casefold() for short in short_names)
            break
    return sorted(alias for alias in aliases if alias)


def _lldp_neighbor_key(
    item: dict[str, object | None],
    *,
    include_neighbor: bool,
) -> str:
    local = normalize_interface_name(item.get("local_interface")).casefold()
    if not include_neighbor:
        return local
    values = (
        local,
        str(item.get("chassis_id") or item.get("neighbor_mac") or "")
        .strip()
        .casefold(),
        str(item.get("neighbor_interface") or "").strip().casefold(),
    )
    return "\x1f".join(values) if values[0] else ""
