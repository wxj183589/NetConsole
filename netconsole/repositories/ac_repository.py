from __future__ import annotations

from datetime import datetime

from netconsole.core.database import Database


SUMMARY_FIELDS = (
    "ac_device_uuid",
    "total_aps",
    "online_aps",
    "offline_aps",
    "total_ap_licenses",
    "local_ap_licenses",
    "remaining_local_ap_licenses",
    "cpu_usage",
    "cpu_5s",
    "cpu_1m",
    "cpu_5m",
    "memory_usage",
    "memory_total",
    "memory_used",
    "memory_free",
    "memory_free_ratio",
    "model",
    "serial_number",
    "software_version",
    "collected_at",
    "collect_run_uuid",
    "raw_log_path",
    "updated_at",
)

FIT_AP_RESOURCE_FIELDS = (
    "ac_device_uuid",
    "ap_name",
    "apid",
    "ap_ip",
    "ap_mac",
    "model",
    "serial_number",
    "state",
    "state_raw",
    "state_display",
    "group_name",
    "online_time",
    "site",
    "mileage",
    "location_note",
    "direction",
    "rid1_channel",
    "rid1_bandwidth",
    "rid1_tx_power",
    "rid2_channel",
    "rid2_bandwidth",
    "rid2_tx_power",
    "rid3_channel",
    "rid3_bandwidth",
    "rid3_tx_power",
    "lldp_neighbor",
    "ap_optical_power",
    "collected_at",
    "collect_run_uuid",
    "raw_log_path",
    "updated_at",
)

FIT_AP_METADATA_FIELDS = (
    "ap_name",
    "site_name",
    "mileage",
    "location_note",
    "direction",
    "created_at",
    "updated_at",
)

FIT_AP_OPTICAL_FIELDS = (
    "ac_device_uuid",
    "ap_name",
    "ap_ip",
    "site",
    "lldp_neighbor",
    "neighbor_interface",
    "neighbor_mac",
    "neighbor_device_name",
    "neighbor_rx_power",
    "interface_name",
    "temperature",
    "tx_power",
    "rx_power",
    "status",
    "error_message",
    "collected_at",
    "collect_run_uuid",
    "raw_log_path",
    "updated_at",
)


class AcRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def upsert_ac_ap_summary(self, data: dict[str, object | None]) -> dict[str, object | None]:
        payload = self._payload(SUMMARY_FIELDS, data)
        self._set_time_defaults(payload)
        columns = ", ".join(SUMMARY_FIELDS)
        placeholders = ", ".join("?" for _ in SUMMARY_FIELDS)
        updates = ", ".join(f"{field} = excluded.{field}" for field in SUMMARY_FIELDS if field != "ac_device_uuid")
        with self.database.connect() as conn:
            conn.execute(
                f"""
                INSERT INTO ac_ap_summary ({columns})
                VALUES ({placeholders})
                ON CONFLICT(ac_device_uuid) DO UPDATE SET {updates}
                """,
                [payload[field] for field in SUMMARY_FIELDS],
            )
            conn.commit()
        return self.get_ac_ap_summary(str(payload["ac_device_uuid"])) or payload

    def get_ac_ap_summary(self, ac_device_uuid: str) -> dict[str, object | None] | None:
        with self.database.connect() as conn:
            row = conn.execute("SELECT * FROM ac_ap_summary WHERE ac_device_uuid = ?", (ac_device_uuid,)).fetchone()
        return dict(row) if row is not None else None

    def replace_fit_ap_resources(self, ac_device_uuid: str, rows: list[dict[str, object | None]]) -> None:
        self._replace_rows("ac_fit_ap_resources", FIT_AP_RESOURCE_FIELDS, ac_device_uuid, rows)

    def list_fit_ap_resources(self, ac_device_uuid: str) -> list[dict[str, object | None]]:
        return self._list_fit_ap_resources(ac_device_uuid, include_metadata=False)

    def list_fit_ap_resources_with_metadata(self, ac_device_uuid: str) -> list[dict[str, object | None]]:
        return self._list_fit_ap_resources(ac_device_uuid, include_metadata=True)

    def replace_fit_ap_optical(self, ac_device_uuid: str, rows: list[dict[str, object | None]]) -> None:
        self._replace_rows("ac_fit_ap_optical", FIT_AP_OPTICAL_FIELDS, ac_device_uuid, rows)

    def list_fit_ap_optical(self, ac_device_uuid: str) -> list[dict[str, object | None]]:
        return self._list_rows("ac_fit_ap_optical", ac_device_uuid, "ap_name, id")

    def get_fit_ap_optical_by_ap(self, ac_device_uuid: str, ap_name: str) -> dict[str, object | None] | None:
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT * FROM ac_fit_ap_optical WHERE ac_device_uuid = ? AND ap_name = ? ORDER BY id DESC LIMIT 1",
                (ac_device_uuid, ap_name),
            ).fetchone()
        return dict(row) if row is not None else None

    def get_fit_ap_resource(self, ac_device_uuid: str, ap_name: str) -> dict[str, object | None] | None:
        rows = self.list_fit_ap_resources_with_metadata(ac_device_uuid)
        return next((row for row in rows if row.get("ap_name") == ap_name), None)

    def upsert_fit_ap_metadata(self, data: dict[str, object | None]) -> dict[str, object | None]:
        payload = self._payload(FIT_AP_METADATA_FIELDS, data)
        now = self._now()
        payload["created_at"] = payload.get("created_at") or now
        payload["updated_at"] = payload.get("updated_at") or now
        columns = ", ".join(FIT_AP_METADATA_FIELDS)
        placeholders = ", ".join("?" for _ in FIT_AP_METADATA_FIELDS)
        updates = ", ".join(f"{field} = excluded.{field}" for field in FIT_AP_METADATA_FIELDS if field not in {"ap_name", "created_at"})
        with self.database.connect() as conn:
            conn.execute(
                f"""
                INSERT INTO ac_fit_ap_metadata ({columns})
                VALUES ({placeholders})
                ON CONFLICT(ap_name) DO UPDATE SET {updates}
                """,
                [payload[field] for field in FIT_AP_METADATA_FIELDS],
            )
            conn.commit()
        return self.get_fit_ap_metadata(str(payload["ap_name"])) or payload

    def get_fit_ap_metadata(self, ap_name: str) -> dict[str, object | None] | None:
        with self.database.connect() as conn:
            row = conn.execute("SELECT * FROM ac_fit_ap_metadata WHERE ap_name = ?", (ap_name,)).fetchone()
        return dict(row) if row is not None else None

    def list_fit_ap_metadata(self) -> list[dict[str, object | None]]:
        with self.database.connect() as conn:
            rows = conn.execute("SELECT * FROM ac_fit_ap_metadata ORDER BY ap_name").fetchall()
        return [dict(row) for row in rows]

    def update_fit_ap_site(self, ap_names: list[str], site_name: str) -> int:
        return self.update_fit_ap_metadata_fields(ap_names, {"site_name": site_name})

    def update_fit_ap_metadata_fields(self, ap_names: list[str], fields: dict[str, object | None]) -> int:
        allowed = {"site_name", "mileage", "location_note", "direction"}
        values = {key: value for key, value in fields.items() if key in allowed}
        count = 0
        now = self._now()
        for ap_name in ap_names:
            current = self.get_fit_ap_metadata(ap_name) or {"ap_name": ap_name, "created_at": now}
            payload = {**current, **values, "ap_name": ap_name, "updated_at": now}
            self.upsert_fit_ap_metadata(payload)
            count += 1
        return count

    def delete_fit_aps(self, ac_device_uuid: str, ap_names: list[str]) -> int:
        if not ap_names:
            return 0
        placeholders = ", ".join("?" for _ in ap_names)
        with self.database.connect() as conn:
            count = conn.execute(
                f"DELETE FROM ac_fit_ap_resources WHERE ac_device_uuid = ? AND ap_name IN ({placeholders})",
                [ac_device_uuid, *ap_names],
            ).rowcount
            conn.execute(f"DELETE FROM ac_fit_ap_optical WHERE ac_device_uuid = ? AND ap_name IN ({placeholders})", [ac_device_uuid, *ap_names])
            conn.execute(f"DELETE FROM ac_fit_ap_metadata WHERE ap_name IN ({placeholders})", ap_names)
            conn.commit()
        return int(count or 0)

    def _replace_rows(
        self,
        table: str,
        fields: tuple[str, ...],
        ac_device_uuid: str,
        rows: list[dict[str, object | None]],
    ) -> None:
        now = self._now()
        with self.database.connect() as conn:
            conn.execute(f"DELETE FROM {table} WHERE ac_device_uuid = ?", (ac_device_uuid,))
            for row in rows:
                payload = self._payload(fields, {**row, "ac_device_uuid": ac_device_uuid})
                payload["collected_at"] = payload.get("collected_at") or now
                payload["updated_at"] = payload.get("updated_at") or now
                columns = ", ".join(fields)
                placeholders = ", ".join("?" for _ in fields)
                conn.execute(
                    f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
                    [payload[field] for field in fields],
                )
            conn.commit()

    def _list_rows(self, table: str, ac_device_uuid: str, order_by: str) -> list[dict[str, object | None]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM {table} WHERE ac_device_uuid = ? ORDER BY {order_by}",
                (ac_device_uuid,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _list_fit_ap_resources(self, ac_device_uuid: str, include_metadata: bool) -> list[dict[str, object | None]]:
        if not include_metadata:
            return self._list_rows("ac_fit_ap_resources", ac_device_uuid, "ap_name, id")
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT r.*,
                       m.site_name,
                       m.mileage AS metadata_mileage,
                       m.location_note AS metadata_location_note,
                       m.direction AS metadata_direction
                FROM ac_fit_ap_resources r
                LEFT JOIN ac_fit_ap_metadata m ON m.ap_name = r.ap_name
                WHERE r.ac_device_uuid = ?
                ORDER BY r.ap_name, r.id
                """,
                (ac_device_uuid,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["site"] = item.get("site_name") or item.get("site")
            item["mileage"] = item.get("metadata_mileage") or item.get("mileage")
            item["location_note"] = item.get("metadata_location_note") or item.get("location_note")
            item["direction"] = item.get("metadata_direction") or item.get("direction")
            result.append(item)
        return result

    @classmethod
    def _payload(cls, fields: tuple[str, ...], data: dict[str, object | None]) -> dict[str, object | None]:
        return {field: data.get(field) for field in fields}

    @classmethod
    def _set_time_defaults(cls, payload: dict[str, object | None]) -> None:
        now = cls._now()
        payload["collected_at"] = payload.get("collected_at") or now
        payload["updated_at"] = payload.get("updated_at") or now

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")
