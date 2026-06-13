from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from netconsole.core.database import Database


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
    "interface_type",
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
            conn.commit()
        return self.get_device_fact(str(payload["device_uuid"])) or payload

    def get_device_fact(self, device_uuid: str) -> dict[str, object | None] | None:
        with self.database.connect() as conn:
            row = conn.execute("SELECT * FROM device_facts WHERE device_uuid = ?", (device_uuid,)).fetchone()
        return dict(row) if row is not None else None

    def list_device_facts(self) -> list[dict[str, object | None]]:
        with self.database.connect() as conn:
            rows = conn.execute("SELECT * FROM device_facts ORDER BY sysname, device_uuid").fetchall()
        return [dict(row) for row in rows]

    def replace_device_interfaces(self, device_uuid: str, interfaces: list[dict[str, object | None]]) -> None:
        now = self._now()
        with self.database.connect() as conn:
            conn.execute("DELETE FROM device_interfaces WHERE device_uuid = ?", (device_uuid,))
            for item in interfaces:
                payload = self._payload(INTERFACE_FIELDS, {**item, "device_uuid": device_uuid})
                payload["collected_at"] = payload.get("collected_at") or now
                payload["updated_at"] = payload.get("updated_at") or now
                self._insert(conn, "device_interfaces", INTERFACE_FIELDS, payload)
            conn.commit()

    def list_device_interfaces(self, device_uuid: str) -> list[dict[str, object | None]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM device_interfaces WHERE device_uuid = ? ORDER BY interface_name",
                (device_uuid,),
            ).fetchall()
        return [dict(row) for row in rows]

    def replace_optical_modules(self, device_uuid: str, modules: list[dict[str, object | None]]) -> None:
        now = self._now()
        with self.database.connect() as conn:
            conn.execute("DELETE FROM device_optical_modules WHERE device_uuid = ?", (device_uuid,))
            for item in modules:
                payload = self._payload(OPTICAL_MODULE_FIELDS, {**item, "device_uuid": device_uuid})
                payload["collected_at"] = payload.get("collected_at") or now
                payload["updated_at"] = payload.get("updated_at") or now
                self._insert(conn, "device_optical_modules", OPTICAL_MODULE_FIELDS, payload)
            conn.commit()

    def list_optical_modules(self, device_uuid: str) -> list[dict[str, object | None]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM device_optical_modules WHERE device_uuid = ? ORDER BY interface_name",
                (device_uuid,),
            ).fetchall()
        return [dict(row) for row in rows]

    def replace_lldp_neighbors(self, device_uuid: str, neighbors: list[dict[str, object | None]]) -> None:
        now = self._now()
        with self.database.connect() as conn:
            conn.execute("DELETE FROM device_lldp_neighbors WHERE device_uuid = ?", (device_uuid,))
            for item in neighbors:
                payload = self._payload(LLDP_FIELDS, {**item, "device_uuid": device_uuid})
                payload["collected_at"] = payload.get("collected_at") or now
                payload["updated_at"] = payload.get("updated_at") or now
                self._insert(conn, "device_lldp_neighbors", LLDP_FIELDS, payload)
            conn.commit()

    def list_lldp_neighbors(self, device_uuid: str) -> list[dict[str, object | None]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM device_lldp_neighbors WHERE device_uuid = ? ORDER BY local_interface, neighbor_sysname",
                (device_uuid,),
            ).fetchall()
        return [dict(row) for row in rows]

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

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")
