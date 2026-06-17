from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from netconsole.core.database import Database
from netconsole.utils.interface_sort import interface_sort_key


FACT_FIELDS = (
    "device_uuid",
    "sysname",
    "model",
    "serial_number",
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
    "protocol_status",
    "speed",
    "duplex",
    "interface_type",
    "port_status",
    "pvid",
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
    "neighbor_sysname",
    "neighbor_mac",
    "neighbor_interface",
    "neighbor_ip",
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
        now = self._now()
        with self.database.connect() as conn:
            conn.execute("DELETE FROM device_interfaces WHERE device_uuid = ?", (device_uuid,))
            for item in interfaces:
                payload = self._payload(INTERFACE_FIELDS, {**item, "device_uuid": device_uuid})
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
        return sorted([dict(row) for row in rows], key=lambda row: interface_sort_key(row.get("interface_name")))

    def append_interface_history(self, data: dict[str, object | None]) -> None:
        payload = self._payload(INTERFACE_HISTORY_FIELDS, data)
        self._set_required_defaults(payload, ("collected_at", "created_at"))
        with self.database.connect() as conn:
            self._insert(conn, "device_interfaces_history", INTERFACE_HISTORY_FIELDS, payload)
            conn.commit()

    def replace_optical_modules(self, device_uuid: str, modules: list[dict[str, object | None]]) -> None:
        now = self._now()
        with self.database.connect() as conn:
            conn.execute("DELETE FROM device_optical_modules WHERE device_uuid = ?", (device_uuid,))
            for item in modules:
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
        return sorted([dict(row) for row in rows], key=lambda row: interface_sort_key(row.get("interface_name")))

    def append_optical_history(self, data: dict[str, object | None]) -> None:
        payload = self._payload(OPTICAL_MODULE_HISTORY_FIELDS, data)
        self._set_required_defaults(payload, ("collected_at", "created_at"))
        with self.database.connect() as conn:
            self._insert(conn, "device_optical_modules_history", OPTICAL_MODULE_HISTORY_FIELDS, payload)
            conn.commit()

    def replace_lldp_neighbors(self, device_uuid: str, neighbors: list[dict[str, object | None]]) -> None:
        now = self._now()
        with self.database.connect() as conn:
            conn.execute("DELETE FROM device_lldp_neighbors WHERE device_uuid = ?", (device_uuid,))
            for item in neighbors:
                payload = self._payload(LLDP_FIELDS, {**item, "device_uuid": device_uuid})
                payload["collected_at"] = payload.get("collected_at") or now
                payload["updated_at"] = payload.get("updated_at") or now
                self._insert(conn, "device_lldp_neighbors", LLDP_FIELDS, payload)
                self._insert_history(conn, "device_lldp_neighbors_history", LLDP_HISTORY_FIELDS, payload)
            conn.commit()

    def list_lldp_neighbors(self, device_uuid: str) -> list[dict[str, object | None]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM device_lldp_neighbors WHERE device_uuid = ?",
                (device_uuid,),
            ).fetchall()
        return sorted([dict(row) for row in rows], key=lambda row: (interface_sort_key(row.get("local_interface")), str(row.get("neighbor_sysname") or "")))

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
        return self._list_history(
            "device_optical_modules_history",
            "device_uuid = ? AND interface_name = ?",
            (device_uuid, interface_name),
        )

    def list_lldp_history(self, device_uuid: str, local_interface: str) -> list[dict[str, object | None]]:
        return self._list_history(
            "device_lldp_neighbors_history",
            "device_uuid = ? AND local_interface = ?",
            (device_uuid, local_interface),
        )

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
