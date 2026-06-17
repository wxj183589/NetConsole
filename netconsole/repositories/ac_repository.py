from __future__ import annotations

from datetime import datetime
from uuid import uuid4

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
    "ap_uuid",
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
    "ap_uuid",
    "ap_name",
    "site_name",
    "mileage",
    "location_note",
    "direction",
    "created_at",
    "updated_at",
)

FIT_AP_RESOURCE_HISTORY_FIELDS = (
    "ac_device_uuid",
    "ap_uuid",
    "ap_name",
    "ap_mac",
    "ap_ip",
    "serial_number",
    "state_raw",
    "state_display",
    "site_name",
    "collected_at",
    "collect_run_uuid",
    "raw_log_path",
    "created_at",
)

FIT_AP_OPTICAL_FIELDS = (
    "ac_device_uuid",
    "ap_uuid",
    "ap_name",
    "ap_mac",
    "ap_ip",
    "site",
    "lldp_neighbor",
    "neighbor_interface",
    "neighbor_mac",
    "neighbor_device_name",
    "neighbor_rx_power",
    "interface_name",
    "temperature",
    "voltage",
    "bias_current",
    "tx_power",
    "rx_power",
    "rx_low_alarm",
    "rx_high_alarm",
    "tx_low_alarm",
    "tx_high_alarm",
    "rx_low_warning",
    "rx_high_warning",
    "tx_low_warning",
    "tx_high_warning",
    "optical_alarm_status",
    "status",
    "error_message",
    "module_model",
    "module_serial_number",
    "module_vendor",
    "wavelength",
    "transmission_distance",
    "connector_type",
    "collected_at",
    "collect_run_uuid",
    "raw_log_path",
    "updated_at",
)

FIT_AP_OPTICAL_HISTORY_FIELDS = (
    "ac_device_uuid",
    "ap_uuid",
    "ap_name",
    "ap_mac",
    "ap_ip",
    "site",
    "lldp_neighbor",
    "neighbor_interface",
    "neighbor_mac",
    "neighbor_device_name",
    "neighbor_rx_power",
    "interface_name",
    "temperature",
    "voltage",
    "bias_current",
    "tx_power",
    "rx_power",
    "rx_low_alarm",
    "rx_high_alarm",
    "tx_low_alarm",
    "tx_high_alarm",
    "rx_low_warning",
    "rx_high_warning",
    "tx_low_warning",
    "tx_high_warning",
    "optical_alarm_status",
    "status",
    "error_message",
    "module_model",
    "module_serial_number",
    "module_vendor",
    "wavelength",
    "transmission_distance",
    "connector_type",
    "collected_at",
    "collect_run_uuid",
    "raw_log_path",
    "created_at",
)

FIT_AP_LLDP_HISTORY_FIELDS = (
    "ac_device_uuid",
    "ap_uuid",
    "ap_name",
    "ap_mac",
    "local_interface",
    "lldp_neighbor",
    "neighbor_interface",
    "neighbor_mac",
    "neighbor_device_name",
    "collected_at",
    "collect_run_uuid",
    "raw_log_path",
    "created_at",
)

FIT_AP_RADIO_HISTORY_FIELDS = (
    "ac_device_uuid",
    "ap_uuid",
    "ap_name",
    "rid",
    "channel",
    "bandwidth",
    "tx_power",
    "collected_at",
    "collect_run_uuid",
    "raw_log_path",
    "created_at",
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
        now = self._now()
        with self.database.connect() as conn:
            existing_rows = conn.execute("SELECT ap_uuid, serial_number FROM ac_fit_ap_resources WHERE ac_device_uuid = ?", (ac_device_uuid,)).fetchall()
            uuid_by_serial = {str(row["serial_number"]): str(row["ap_uuid"]) for row in existing_rows if row["serial_number"]}
            current_uuids: list[str] = []
            for row in rows:
                serial_number = str(row.get("serial_number") or "").strip()
                ap_uuid = str(row.get("ap_uuid") or uuid_by_serial.get(serial_number) or uuid4())
                current_uuids.append(ap_uuid)
                payload = self._payload(FIT_AP_RESOURCE_FIELDS, {**row, "ac_device_uuid": ac_device_uuid, "ap_uuid": ap_uuid})
                payload["collected_at"] = payload.get("collected_at") or now
                payload["updated_at"] = payload.get("updated_at") or now
                columns = ", ".join(FIT_AP_RESOURCE_FIELDS)
                placeholders = ", ".join("?" for _ in FIT_AP_RESOURCE_FIELDS)
                updates = ", ".join(f"{field} = excluded.{field}" for field in FIT_AP_RESOURCE_FIELDS if field not in {"ac_device_uuid", "ap_uuid", "serial_number"})
                conn.execute(
                    f"""
                    INSERT INTO ac_fit_ap_resources ({columns})
                    VALUES ({placeholders})
                    ON CONFLICT(ac_device_uuid, serial_number) DO UPDATE SET
                        ap_uuid = ac_fit_ap_resources.ap_uuid,
                        {updates}
                    """,
                    [payload[field] for field in FIT_AP_RESOURCE_FIELDS],
                )
                self._append_resource_history(conn, payload)
                self._append_radio_history(conn, payload)
            if current_uuids:
                placeholders = ", ".join("?" for _ in current_uuids)
                conn.execute(f"DELETE FROM ac_fit_ap_resources WHERE ac_device_uuid = ? AND ap_uuid NOT IN ({placeholders})", [ac_device_uuid, *current_uuids])
            else:
                conn.execute("DELETE FROM ac_fit_ap_resources WHERE ac_device_uuid = ?", (ac_device_uuid,))
            conn.commit()

    def list_fit_ap_resources(self, ac_device_uuid: str) -> list[dict[str, object | None]]:
        return self._list_fit_ap_resources(ac_device_uuid, include_metadata=False)

    def list_fit_ap_resources_with_metadata(self, ac_device_uuid: str) -> list[dict[str, object | None]]:
        return self._list_fit_ap_resources(ac_device_uuid, include_metadata=True)

    def list_all_fit_ap_resources_with_metadata(self) -> list[dict[str, object | None]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT r.*,
                       m.site_name,
                       m.mileage AS metadata_mileage,
                       m.location_note AS metadata_location_note,
                       m.direction AS metadata_direction
                FROM ac_fit_ap_resources r
                LEFT JOIN ac_fit_ap_metadata m ON m.ap_uuid = r.ap_uuid
                ORDER BY r.ap_name, r.id
                """
            ).fetchall()
        return [self._resource_with_metadata(dict(row)) for row in rows]

    def list_fit_ap_resource_history(self, ac_device_uuid: str, limit: int = 10000) -> list[dict[str, object | None]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM ac_fit_ap_resource_history
                WHERE ac_device_uuid = ?
                ORDER BY collected_at DESC, id DESC
                LIMIT ?
                """,
                (ac_device_uuid, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def replace_fit_ap_optical(self, ac_device_uuid: str, rows: list[dict[str, object | None]]) -> None:
        now = self._now()
        with self.database.connect() as conn:
            conn.execute("DELETE FROM ac_fit_ap_optical WHERE ac_device_uuid = ?", (ac_device_uuid,))
            for row in rows:
                resource = self._resource_for_payload(conn, ac_device_uuid, row)
                payload = self._payload(FIT_AP_OPTICAL_FIELDS, {**row, "ac_device_uuid": ac_device_uuid})
                payload["ap_uuid"] = payload.get("ap_uuid") or resource.get("ap_uuid") or str(uuid4())
                payload["ap_name"] = payload.get("ap_name") or resource.get("ap_name")
                payload["ap_mac"] = payload.get("ap_mac") or resource.get("ap_mac")
                payload["ap_ip"] = payload.get("ap_ip") or resource.get("ap_ip")
                payload["site"] = payload.get("site") or resource.get("site_name") or resource.get("site")
                payload["collected_at"] = payload.get("collected_at") or now
                payload["updated_at"] = payload.get("updated_at") or now
                columns = ", ".join(FIT_AP_OPTICAL_FIELDS)
                placeholders = ", ".join("?" for _ in FIT_AP_OPTICAL_FIELDS)
                conn.execute(f"INSERT INTO ac_fit_ap_optical ({columns}) VALUES ({placeholders})", [payload[field] for field in FIT_AP_OPTICAL_FIELDS])
                history_payload = self._payload(FIT_AP_OPTICAL_HISTORY_FIELDS, {**row, **payload, "created_at": now})
                history_columns = ", ".join(FIT_AP_OPTICAL_HISTORY_FIELDS)
                history_placeholders = ", ".join("?" for _ in FIT_AP_OPTICAL_HISTORY_FIELDS)
                conn.execute(
                    f"INSERT INTO ac_fit_ap_optical_history ({history_columns}) VALUES ({history_placeholders})",
                    [history_payload[field] for field in FIT_AP_OPTICAL_HISTORY_FIELDS],
                )
                lldp_payload = self._payload(
                    FIT_AP_LLDP_HISTORY_FIELDS,
                    {
                        **payload,
                        "local_interface": payload.get("interface_name"),
                        "created_at": now,
                    },
                )
                lldp_columns = ", ".join(FIT_AP_LLDP_HISTORY_FIELDS)
                lldp_placeholders = ", ".join("?" for _ in FIT_AP_LLDP_HISTORY_FIELDS)
                conn.execute(
                    f"INSERT INTO ac_fit_ap_lldp_history ({lldp_columns}) VALUES ({lldp_placeholders})",
                    [lldp_payload[field] for field in FIT_AP_LLDP_HISTORY_FIELDS],
                )
            conn.commit()

    def list_fit_ap_optical(self, ac_device_uuid: str) -> list[dict[str, object | None]]:
        return self._list_rows("ac_fit_ap_optical", ac_device_uuid, "ap_name, id")

    def list_all_fit_ap_optical(self) -> list[dict[str, object | None]]:
        with self.database.connect() as conn:
            rows = conn.execute("SELECT * FROM ac_fit_ap_optical ORDER BY neighbor_device_name, neighbor_interface, ap_name, id").fetchall()
        return [dict(row) for row in rows]

    def get_fit_ap_optical_by_uuid(self, ac_device_uuid: str, ap_uuid: str) -> dict[str, object | None] | None:
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT * FROM ac_fit_ap_optical WHERE ac_device_uuid = ? AND ap_uuid = ? ORDER BY id DESC LIMIT 1",
                (ac_device_uuid, ap_uuid),
            ).fetchone()
        return dict(row) if row is not None else None

    def get_fit_ap_optical_by_ap(self, ac_device_uuid: str, ap_name: str) -> dict[str, object | None] | None:
        resource = self.get_fit_ap_resource(ac_device_uuid, ap_name)
        if resource and resource.get("ap_uuid"):
            return self.get_fit_ap_optical_by_uuid(ac_device_uuid, str(resource["ap_uuid"]))
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT * FROM ac_fit_ap_optical WHERE ac_device_uuid = ? AND ap_name = ? ORDER BY id DESC LIMIT 1",
                (ac_device_uuid, ap_name),
            ).fetchone()
        return dict(row) if row is not None else None

    def list_fit_ap_optical_history(self, ap_uuid: str | None = None, ap_name: str | None = None, limit: int = 100) -> list[dict[str, object | None]]:
        clauses: list[str] = []
        params: list[object] = []
        if ap_uuid:
            clauses.append("ap_uuid = ?")
            params.append(ap_uuid)
        if ap_name:
            clauses.append("ap_name = ?")
            params.append(ap_name)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self.database.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM ac_fit_ap_optical_history {where} ORDER BY collected_at DESC, id DESC LIMIT ?",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def list_fit_ap_optical_history_by_ap(self, ap_uuid: str, limit: int = 100) -> list[dict[str, object | None]]:
        return self.list_fit_ap_optical_history(ap_uuid=ap_uuid, limit=limit)

    def list_fit_ap_radio_history_by_ap(self, ap_uuid: str, limit: int = 100) -> list[dict[str, object | None]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM ac_fit_ap_radio_history
                WHERE ap_uuid = ?
                ORDER BY collected_at DESC, id DESC
                LIMIT ?
                """,
                (ap_uuid, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_fit_ap_lldp_history_by_ap(self, ap_uuid: str, limit: int = 100) -> list[dict[str, object | None]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM ac_fit_ap_lldp_history
                WHERE ap_uuid = ?
                ORDER BY collected_at DESC, id DESC
                LIMIT ?
                """,
                (ap_uuid, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_fit_ap_resource(self, ac_device_uuid: str, ap_name: str) -> dict[str, object | None] | None:
        rows = self.list_fit_ap_resources_with_metadata(ac_device_uuid)
        return next((row for row in rows if row.get("ap_name") == ap_name), None)

    def get_fit_ap_resource_by_uuid(self, ac_device_uuid: str, ap_uuid: str) -> dict[str, object | None] | None:
        rows = self.list_fit_ap_resources_with_metadata(ac_device_uuid)
        return next((row for row in rows if row.get("ap_uuid") == ap_uuid), None)

    def upsert_fit_ap_metadata(self, data: dict[str, object | None]) -> dict[str, object | None]:
        payload = self._payload(FIT_AP_METADATA_FIELDS, data)
        if not payload.get("ap_uuid") and payload.get("ap_name"):
            resource = self.get_fit_ap_resource_by_name_any_ac(str(payload["ap_name"]))
            if resource:
                payload["ap_uuid"] = resource.get("ap_uuid")
        if not payload.get("ap_uuid"):
            payload["ap_uuid"] = str(uuid4())
        now = self._now()
        payload["created_at"] = payload.get("created_at") or now
        payload["updated_at"] = payload.get("updated_at") or now
        columns = ", ".join(FIT_AP_METADATA_FIELDS)
        placeholders = ", ".join("?" for _ in FIT_AP_METADATA_FIELDS)
        updates = ", ".join(f"{field} = excluded.{field}" for field in FIT_AP_METADATA_FIELDS if field not in {"ap_uuid", "created_at"})
        with self.database.connect() as conn:
            conn.execute(
                f"""
                INSERT INTO ac_fit_ap_metadata ({columns})
                VALUES ({placeholders})
                ON CONFLICT(ap_uuid) DO UPDATE SET {updates}
                """,
                [payload[field] for field in FIT_AP_METADATA_FIELDS],
            )
            conn.commit()
        return self.get_fit_ap_metadata_by_uuid(str(payload["ap_uuid"])) or payload

    def get_fit_ap_metadata(self, ap_name: str) -> dict[str, object | None] | None:
        resource = self.get_fit_ap_resource_by_name_any_ac(ap_name)
        if resource and resource.get("ap_uuid"):
            return self.get_fit_ap_metadata_by_uuid(str(resource["ap_uuid"]))
        with self.database.connect() as conn:
            row = conn.execute("SELECT * FROM ac_fit_ap_metadata WHERE ap_name = ?", (ap_name,)).fetchone()
        return dict(row) if row is not None else None

    def get_fit_ap_metadata_by_uuid(self, ap_uuid: str) -> dict[str, object | None] | None:
        with self.database.connect() as conn:
            row = conn.execute("SELECT * FROM ac_fit_ap_metadata WHERE ap_uuid = ?", (ap_uuid,)).fetchone()
        return dict(row) if row is not None else None

    def get_fit_ap_resource_by_name_any_ac(self, ap_name: str) -> dict[str, object | None] | None:
        with self.database.connect() as conn:
            row = conn.execute("SELECT * FROM ac_fit_ap_resources WHERE ap_name = ? ORDER BY id DESC LIMIT 1", (ap_name,)).fetchone()
        return dict(row) if row is not None else None

    def list_fit_ap_metadata(self) -> list[dict[str, object | None]]:
        with self.database.connect() as conn:
            rows = conn.execute("SELECT * FROM ac_fit_ap_metadata ORDER BY ap_name").fetchall()
        return [dict(row) for row in rows]

    def update_fit_ap_site(self, ap_uuids: list[str], site_name: str) -> int:
        return self.update_fit_ap_metadata_fields(ap_uuids, {"site_name": site_name})

    def update_fit_ap_metadata_fields(self, ap_uuids: list[str], fields: dict[str, object | None]) -> int:
        allowed = {"site_name", "mileage", "location_note", "direction"}
        values = {key: value for key, value in fields.items() if key in allowed}
        count = 0
        now = self._now()
        for value in ap_uuids:
            ap_uuid = self._resolve_ap_uuid(value) or value
            resource = self.get_fit_ap_resource_by_uuid_any_ac(ap_uuid) or {}
            current = self.get_fit_ap_metadata_by_uuid(ap_uuid) or {"ap_uuid": ap_uuid, "ap_name": resource.get("ap_name"), "created_at": now}
            payload = {**current, **values, "ap_uuid": ap_uuid, "ap_name": resource.get("ap_name") or current.get("ap_name"), "updated_at": now}
            self.upsert_fit_ap_metadata(payload)
            count += 1
        return count

    def delete_fit_aps(self, ac_device_uuid: str, ap_uuids: list[str]) -> int:
        if not ap_uuids:
            return 0
        ap_uuids = [self._resolve_ap_uuid(value, ac_device_uuid=ac_device_uuid) or value for value in ap_uuids]
        placeholders = ", ".join("?" for _ in ap_uuids)
        with self.database.connect() as conn:
            count = conn.execute(
                f"DELETE FROM ac_fit_ap_resources WHERE ac_device_uuid = ? AND ap_uuid IN ({placeholders})",
                [ac_device_uuid, *ap_uuids],
            ).rowcount
            conn.execute(f"DELETE FROM ac_fit_ap_optical WHERE ac_device_uuid = ? AND ap_uuid IN ({placeholders})", [ac_device_uuid, *ap_uuids])
            conn.execute(f"DELETE FROM ac_fit_ap_metadata WHERE ap_uuid IN ({placeholders})", ap_uuids)
            conn.commit()
        return int(count or 0)

    def get_fit_ap_resource_by_uuid_any_ac(self, ap_uuid: str) -> dict[str, object | None] | None:
        with self.database.connect() as conn:
            row = conn.execute("SELECT * FROM ac_fit_ap_resources WHERE ap_uuid = ? ORDER BY id DESC LIMIT 1", (ap_uuid,)).fetchone()
        return dict(row) if row is not None else None

    def upsert_station_ap_capacity(self, site_name: str, ap_total: int | None) -> None:
        if not site_name or site_name == "合计":
            return
        total = max(int(ap_total or 0), 0)
        now = self._now()
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO ac_station_ap_capacity (site_name, ap_total, remark, created_at, updated_at)
                VALUES (?, ?, '', ?, ?)
                ON CONFLICT(site_name) DO UPDATE SET
                    ap_total = excluded.ap_total,
                    updated_at = excluded.updated_at
                """,
                (site_name, total, now, now),
            )
            conn.commit()

    def list_station_ap_capacities(self) -> dict[str, int]:
        with self.database.connect() as conn:
            rows = conn.execute("SELECT site_name, ap_total FROM ac_station_ap_capacity").fetchall()
        return {str(row["site_name"]): int(row["ap_total"]) for row in rows if row["ap_total"] is not None}

    def upsert_station_ap_remark(self, site_name: str, remark: str | None) -> None:
        if not site_name or site_name == "合计":
            return
        text = str(remark or "")[:500]
        now = self._now()
        with self.database.connect() as conn:
            existing = conn.execute("SELECT ap_total FROM ac_station_ap_capacity WHERE site_name = ?", (site_name,)).fetchone()
            total = int(existing["ap_total"]) if existing is not None and existing["ap_total"] is not None else 0
            conn.execute(
                """
                INSERT INTO ac_station_ap_capacity (site_name, ap_total, remark, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(site_name) DO UPDATE SET
                    remark = excluded.remark,
                    updated_at = excluded.updated_at
                """,
                (site_name, total, text, now, now),
            )
            conn.commit()

    def list_station_ap_capacity_details(self) -> dict[str, dict[str, object | None]]:
        with self.database.connect() as conn:
            rows = conn.execute("SELECT site_name, ap_total, remark FROM ac_station_ap_capacity").fetchall()
        return {
            str(row["site_name"]): {
                "ap_total": int(row["ap_total"] or 0),
                "remark": row["remark"] or "",
            }
            for row in rows
        }

    def save_station_online_summary_history(self, rows: list[dict[str, object | None]], collected_at: str | None = None) -> int:
        now = self._now()
        stamp = collected_at or now
        payload_rows = [row for row in rows if str(row.get("site") or "") != "合计"]
        with self.database.connect() as conn:
            for row in payload_rows:
                conn.execute(
                    """
                    INSERT INTO ac_station_online_summary_history (
                        site_name, ap_total, online_count, offline_count, online_rate, remark, collected_at, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(row.get("site") or ""),
                        int(row.get("total") or 0),
                        int(row.get("online") or 0),
                        int(row.get("offline") or 0),
                        str(row.get("online_rate") or ""),
                        str(row.get("remark") or ""),
                        stamp,
                        now,
                    ),
                )
            conn.commit()
        return len(payload_rows)

    def list_station_online_summary_history(self, site_name: str | None = None, limit: int = 500) -> list[dict[str, object | None]]:
        clauses: list[str] = []
        params: list[object] = []
        if site_name:
            clauses.append("site_name = ?")
            params.append(site_name)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self.database.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM ac_station_online_summary_history
                {where}
                ORDER BY collected_at DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def _resolve_ap_uuid(self, value: str, ac_device_uuid: str | None = None) -> str | None:
        with self.database.connect() as conn:
            if ac_device_uuid:
                row = conn.execute(
                    "SELECT ap_uuid FROM ac_fit_ap_resources WHERE ac_device_uuid = ? AND (ap_uuid = ? OR ap_name = ?) ORDER BY id DESC LIMIT 1",
                    (ac_device_uuid, value, value),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT ap_uuid FROM ac_fit_ap_resources WHERE ap_uuid = ? OR ap_name = ? ORDER BY id DESC LIMIT 1",
                    (value, value),
                ).fetchone()
        return str(row["ap_uuid"]) if row is not None and row["ap_uuid"] else None

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
                if "ap_uuid" in fields and not payload.get("ap_uuid"):
                    resource = self.get_fit_ap_resource(ac_device_uuid, str(row.get("ap_name") or ""))
                    payload["ap_uuid"] = resource.get("ap_uuid") if resource else str(uuid4())
                payload["collected_at"] = payload.get("collected_at") or now
                payload["updated_at"] = payload.get("updated_at") or now
                columns = ", ".join(fields)
                placeholders = ", ".join("?" for _ in fields)
                conn.execute(
                    f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
                    [payload[field] for field in fields],
                )
            conn.commit()

    def _append_radio_history(self, conn, payload: dict[str, object | None]) -> None:
        now = self._now()
        for rid in (1, 2, 3):
            channel = payload.get(f"rid{rid}_channel")
            bandwidth = payload.get(f"rid{rid}_bandwidth")
            tx_power = payload.get(f"rid{rid}_tx_power")
            if not any(value not in (None, "") for value in (channel, bandwidth, tx_power)):
                continue
            row = {
                "ac_device_uuid": payload.get("ac_device_uuid"),
                "ap_uuid": payload.get("ap_uuid"),
                "ap_name": payload.get("ap_name"),
                "rid": rid,
                "channel": channel,
                "bandwidth": bandwidth,
                "tx_power": tx_power,
                "collected_at": payload.get("collected_at"),
                "collect_run_uuid": payload.get("collect_run_uuid"),
                "raw_log_path": payload.get("raw_log_path"),
                "created_at": now,
            }
            columns = ", ".join(FIT_AP_RADIO_HISTORY_FIELDS)
            placeholders = ", ".join("?" for _ in FIT_AP_RADIO_HISTORY_FIELDS)
            conn.execute(f"INSERT INTO ac_fit_ap_radio_history ({columns}) VALUES ({placeholders})", [row[field] for field in FIT_AP_RADIO_HISTORY_FIELDS])

    def _append_resource_history(self, conn, payload: dict[str, object | None]) -> None:
        now = self._now()
        row = self._payload(
            FIT_AP_RESOURCE_HISTORY_FIELDS,
            {
                **payload,
                "site_name": payload.get("site_name") or payload.get("site"),
                "created_at": now,
            },
        )
        row["collected_at"] = row.get("collected_at") or now
        columns = ", ".join(FIT_AP_RESOURCE_HISTORY_FIELDS)
        placeholders = ", ".join("?" for _ in FIT_AP_RESOURCE_HISTORY_FIELDS)
        conn.execute(f"INSERT INTO ac_fit_ap_resource_history ({columns}) VALUES ({placeholders})", [row[field] for field in FIT_AP_RESOURCE_HISTORY_FIELDS])

    def _resource_for_payload(self, conn, ac_device_uuid: str, row: dict[str, object | None]) -> dict[str, object | None]:
        if row.get("ap_uuid"):
            found = conn.execute(
                "SELECT r.*, m.site_name FROM ac_fit_ap_resources r LEFT JOIN ac_fit_ap_metadata m ON m.ap_uuid = r.ap_uuid WHERE r.ac_device_uuid = ? AND r.ap_uuid = ? ORDER BY r.id DESC LIMIT 1",
                (ac_device_uuid, row.get("ap_uuid")),
            ).fetchone()
            if found:
                return dict(found)
        if row.get("ap_name"):
            found = conn.execute(
                "SELECT r.*, m.site_name FROM ac_fit_ap_resources r LEFT JOIN ac_fit_ap_metadata m ON m.ap_uuid = r.ap_uuid WHERE r.ac_device_uuid = ? AND r.ap_name = ? ORDER BY r.id DESC LIMIT 1",
                (ac_device_uuid, row.get("ap_name")),
            ).fetchone()
            if found:
                return dict(found)
        return {}

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
                LEFT JOIN ac_fit_ap_metadata m ON m.ap_uuid = r.ap_uuid
                WHERE r.ac_device_uuid = ?
                ORDER BY r.ap_name, r.id
                """,
                (ac_device_uuid,),
            ).fetchall()
        result = []
        for row in rows:
            result.append(self._resource_with_metadata(dict(row)))
        return result

    @staticmethod
    def _resource_with_metadata(item: dict[str, object | None]) -> dict[str, object | None]:
        item["site"] = item.get("site_name") or item.get("site")
        item["mileage"] = item.get("metadata_mileage") or item.get("mileage")
        item["location_note"] = item.get("metadata_location_note") or item.get("location_note")
        item["direction"] = item.get("metadata_direction") or item.get("direction")
        return item

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
