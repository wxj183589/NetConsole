from __future__ import annotations

from datetime import datetime
import re
from uuid import uuid4

from netconsole.core import app_logger
from netconsole.services.fit_ap_link_info import merge_lldp_payload, normalize_interface_key, normalize_lldp_payload, optical_payload_from_row, resolve_fit_ap_link_info, resolve_optical_match_status
from netconsole.utils.station_normalize import normalize_station_value

from netconsole.core.database import Database
from netconsole.services.ap_extension_import import normalize_ap_mac
from netconsole.services.trackside_ap_business import parse_vlan_set
from netconsole.utils.mileage import parse_mileage_to_meters


TRACKSIDE_AP_PLAN_MODE = "unified"
LEGACY_TRACKSIDE_PLAN_MODES = {"single_vlan", "multi_vlan"}
TRACKSIDE_PLAN_MODES = {TRACKSIDE_AP_PLAN_MODE, *LEGACY_TRACKSIDE_PLAN_MODES}
TRACKSIDE_PLAN_FIELDS = (
    "mode",
    "station_id",
    "sequence_no",
    "station_name",
    "ap_count",
    "ap_start_address",
    "subnet_mask",
    "mask_length",
    "ap_gateway",
    "management_vlan",
    "ap_management_vlans",
    "remark",
    "sort_order",
    "created_at",
    "updated_at",
)
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
    "connection_ip",
    "connection_state",
    "connection_time",
    "site",
    "mileage",
    "location_note",
    "direction",
    "rid1_status",
    "rid1_mode",
    "rid1_band",
    "rid1_channel",
    "rid1_bandwidth",
    "rid1_usage",
    "rid1_tx_power",
    "rid1_clients",
    "rid2_status",
    "rid2_mode",
    "rid2_band",
    "rid2_channel",
    "rid2_bandwidth",
    "rid2_usage",
    "rid2_tx_power",
    "rid2_clients",
    "rid3_status",
    "rid3_mode",
    "rid3_band",
    "rid3_channel",
    "rid3_bandwidth",
    "rid3_usage",
    "rid3_tx_power",
    "rid3_clients",
    "rid1_bbssid",
    "rid2_bbssid",
    "rid3_bbssid",
    "lldp_neighbor",
    "lldp_source",
    "lldp_confidence",
    "lldp_collected_at",
    "lldp_local_interface",
    "lldp_local_interface_normalized",
    "lldp_neighbor_name",
    "lldp_neighbor_mac",
    "lldp_neighbor_mac_normalized",
    "lldp_neighbor_interface",
    "lldp_match_status",
    "optical_interface",
    "optical_interface_normalized",
    "optical_rx_power",
    "optical_tx_power",
    "optical_collected_at",
    "optical_match_status",
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
    "station_id",
    "station_override_enabled",
    "station_override_source",
    "belong_type",
    "belong_section",
    "section_start_station",
    "section_end_station",
    "yard_name",
    "area_name",
    "mileage",
    "location_note",
    "direction",
    "created_at",
    "updated_at",
)

FIT_AP_DETAIL_FIELDS = (
    "ap_uuid",
    "ac_device_uuid",
    "ap_name",
    "ap_group_name",
    "backup_type",
    "ready_for_switchover",
    "system_uptime",
    "region_code",
    "region_code_lock",
    "hardware_version",
    "software_version",
    "boot_version",
    "map_file",
    "forwarding_mode",
    "power_level",
    "power_info",
    "capwap_data_tunnel_status",
    "discovery_type",
    "last_reboot_reason",
    "latest_ip_address",
    "current_ac_ip",
    "tunnel_down_reason",
    "connection_count",
    "control_tunnel_encryption_state",
    "data_tunnel_encryption_state",
    "remote_configuration",
    "energy_saving_level",
    "ap_type",
    "extra_fields_json",
    "collected_at",
    "collect_run_uuid",
    "raw_log_path",
    "created_at",
    "updated_at",
)

FIT_AP_RADIO_DETAIL_FIELDS = (
    "ap_uuid",
    "radio_id",
    "base_bssid",
    "state",
    "radio_type",
    "antenna_type",
    "channel_bandwidth",
    "operating_bandwidth",
    "secondary_channel_mode",
    "mimo",
    "channel",
    "channel_mode",
    "channel_usage",
    "max_power",
    "noise_floor",
    "distance",
    "beacon_interval",
    "protection_mode",
    "twt_negotiation",
    "radar_detect",
    "extra_fields_json",
    "collected_at",
    "collect_run_uuid",
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

AP_EXTENSION_POINT_FIELDS = (
    "site_id",
    "line_name",
    "system_type",
    "network_domain",
    "belong_type",
    "station_id",
    "station_name",
    "section_id",
    "section_name",
    "section_start_station",
    "section_end_station",
    "yard_name",
    "area_name",
    "line_side",
    "direction",
    "mileage_text",
    "mileage_m",
    "distance_to_prev_m",
    "ap_point_code",
    "ap_name",
    "ap_vendor",
    "ap_mac_norm",
    "ap_mac_display",
    "curve_radius_m",
    "curve_start_text",
    "curve_start_m",
    "curve_end_text",
    "curve_end_m",
    "curve_flag",
    "curve_impact_level",
    "interval_risk_level",
    "interval_risk_reason",
    "install_scene",
    "power_station",
    "power_distribution",
    "fiber_access_station",
    "fiber_distribution",
    "uplink_switch",
    "uplink_port",
    "optical_port",
    "location_desc",
    "remark",
    "source_file",
    "source_sheet",
    "source_row",
    "import_batch_id",
    "raw_payload_json",
    "created_at",
    "updated_at",
)

AP_EXTENSION_IMPORT_BATCH_FIELDS = (
    "site_id",
    "source_file",
    "template_type",
    "system_type",
    "network_domain",
    "import_time",
    "total_rows",
    "success_rows",
    "updated_rows",
    "skipped_rows",
    "error_rows",
    "operator",
    "remark",
)

FIT_AP_UNAUTHENTICATED_FIELDS = (
    "ac_device_uuid",
    "ap_name",
    "apid",
    "state",
    "state_raw",
    "state_display",
    "model",
    "serial_number",
    "dev_type",
    "work_mode",
    "inferred_ap_mac",
    "collect_run_uuid",
    "raw_log_path",
    "collected_at",
    "updated_at",
)

FIT_AP_UNAUTHENTICATED_HISTORY_FIELDS = (*FIT_AP_UNAUTHENTICATED_FIELDS, "created_at")

FIT_AP_UNAUTHENTICATED_SUMMARY_FIELDS = (
    "ac_device_uuid",
    "total_aps",
    "connected_aps",
    "connected_manual_aps",
    "connected_auto_aps",
    "connected_common_aps",
    "connected_wtus",
    "inside_aps",
    "maximum_supported_aps",
    "remaining_aps",
    "total_ap_licenses",
    "local_ap_licenses",
    "server_ap_licenses",
    "remaining_local_ap_licenses",
    "sync_ap_licenses",
    "collect_run_uuid",
    "raw_log_path",
    "collected_at",
    "updated_at",
)

FIT_AP_OPTICAL_FIELDS = (
    "ac_device_uuid",
    "ap_uuid",
    "ap_name",
    "ap_mac",
    "ap_ip",
    "site",
    "lldp_neighbor",
    "lldp_source",
    "lldp_confidence",
    "lldp_collected_at",
    "lldp_local_interface",
    "lldp_local_interface_normalized",
    "lldp_neighbor_name",
    "lldp_neighbor_mac",
    "lldp_neighbor_mac_normalized",
    "lldp_neighbor_interface",
    "lldp_match_status",
    "neighbor_interface",
    "neighbor_mac",
    "neighbor_device_name",
    "neighbor_rx_power",
    "optical_interface",
    "optical_interface_normalized",
    "interface_name",
    "link_match_status",
    "source",
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
    "lldp_local_interface",
    "lldp_local_interface_normalized",
    "lldp_neighbor_name",
    "lldp_neighbor_mac",
    "lldp_neighbor_mac_normalized",
    "lldp_neighbor_interface",
    "link_match_status",
    "source",
    "session_id",
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
    "source",
    "local_interface",
    "local_interface_normalized",
    "lldp_neighbor",
    "neighbor_interface",
    "neighbor_mac",
    "neighbor_mac_normalized",
    "neighbor_device_name",
    "neighbor_name",
    "session_id",
    "is_changed",
    "conflict_flag",
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
    "status",
    "mode",
    "band",
    "channel",
    "bandwidth",
    "usage",
    "tx_power",
    "clients",
    "bbssid",
    "collected_at",
    "collect_run_uuid",
    "raw_log_path",
    "created_at",
)

FIT_AP_OPTIONAL_DETAIL_FIELDS = (
    "connection_ip",
    "connection_state",
    "connection_time",
    *(f"rid{rid}_{field}" for rid in (1, 2, 3) for field in ("status", "mode", "band", "usage", "clients", "bbssid")),
)

AP_ENTITY_FIELDS = (
    "ap_uuid",
    "site_id",
    "ac_device_uuid",
    "ap_name",
    "ap_mac",
    "ap_id",
    "ap_ip",
    "serial_number",
    "model",
    "group_name",
    "mode",
    "state",
    "state_raw",
    "state_display",
    "station",
    "milestone",
    "direction",
    "location_note",
    "first_seen_at",
    "last_seen_at",
    "last_online_at",
    "last_resource_update_at",
    "is_offline",
    "source",
    "created_at",
    "updated_at",
)
AC_AP_DYNAMIC_SUMMARY_FIELDS = (
    "total_aps",
    "online_aps",
    "offline_aps",
    "total_ap_licenses",
    "local_ap_licenses",
    "remaining_local_ap_licenses",
    "collected_at",
    "collect_run_uuid",
    "raw_log_path",
    "updated_at",
)
AC_AP_STATIC_SUMMARY_FIELDS = (
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

AP_RESOURCE_SNAPSHOT_FIELDS = (
    "snapshot_uuid",
    "ap_uuid",
    "ac_device_uuid",
    "collected_at",
    "ap_name",
    "ap_mac",
    "ap_id",
    "ap_ip",
    "serial_number",
    "model",
    "group_name",
    "state",
    "state_raw",
    "online_time",
    "clients",
    "mode",
    "station",
    "raw_source_type",
    "created_at",
)

AP_LLDP_ENTITY_HISTORY_FIELDS = (
    "history_uuid",
    "ap_uuid",
    "ap_mac",
    "ap_name",
    "serial_number",
    "neighbor_switch_uuid",
    "neighbor_switch_name",
    "neighbor_switch_sysname",
    "neighbor_switch_ip",
    "neighbor_interface",
    "collected_at",
    "source_device_uuid",
    "is_latest",
    "created_at",
)

AP_OPTICAL_ENTITY_HISTORY_FIELDS = (
    "history_uuid",
    "ap_uuid",
    "side",
    "device_uuid",
    "interface_name",
    "rx_power",
    "tx_power",
    "alarm_status",
    "collected_at",
    "data_source",
    "is_latest",
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

    def upsert_ac_ap_dynamic_summary(self, ac_device_uuid: str, data: dict[str, object | None]) -> dict[str, object | None]:
        if not ac_device_uuid:
            raise ValueError("ac_device_uuid is required")
        payload = self._payload(AC_AP_DYNAMIC_SUMMARY_FIELDS, data)
        payload["ac_device_uuid"] = ac_device_uuid
        self._set_time_defaults(payload)
        fields = ("ac_device_uuid", *AC_AP_DYNAMIC_SUMMARY_FIELDS)
        columns = ", ".join(fields)
        placeholders = ", ".join("?" for _ in fields)
        updates = ", ".join(f"{field} = excluded.{field}" for field in AC_AP_DYNAMIC_SUMMARY_FIELDS)
        with self.database.connect() as conn:
            conn.execute(
                f"""
                INSERT INTO ac_ap_summary ({columns})
                VALUES ({placeholders})
                ON CONFLICT(ac_device_uuid) DO UPDATE SET {updates}
                """,
                [payload[field] for field in fields],
            )
            conn.commit()
        return self.get_ac_ap_summary(ac_device_uuid) or payload

    def upsert_ac_ap_static_summary(self, ac_device_uuid: str, data: dict[str, object | None]) -> dict[str, object | None]:
        if not ac_device_uuid:
            raise ValueError("ac_device_uuid is required")
        payload = self._payload(AC_AP_STATIC_SUMMARY_FIELDS, data)
        payload["ac_device_uuid"] = ac_device_uuid
        self._set_time_defaults(payload)
        fields = ("ac_device_uuid", *AC_AP_STATIC_SUMMARY_FIELDS)
        columns = ", ".join(fields)
        placeholders = ", ".join("?" for _ in fields)
        updates = ", ".join(f"{field} = excluded.{field}" for field in AC_AP_STATIC_SUMMARY_FIELDS)
        with self.database.connect() as conn:
            conn.execute(
                f"""
                INSERT INTO ac_ap_summary ({columns})
                VALUES ({placeholders})
                ON CONFLICT(ac_device_uuid) DO UPDATE SET {updates}
                """,
                [payload[field] for field in fields],
            )
            conn.commit()
        return self.get_ac_ap_summary(ac_device_uuid) or payload

    def get_ac_ap_summary(self, ac_device_uuid: str) -> dict[str, object | None] | None:
        with self.database.connect() as conn:
            row = conn.execute("SELECT * FROM ac_ap_summary WHERE ac_device_uuid = ?", (ac_device_uuid,)).fetchone()
        return dict(row) if row is not None else None

    def list_ac_ap_summaries(self) -> list[dict[str, object | None]]:
        with self.database.connect() as conn:
            rows = conn.execute("SELECT * FROM ac_ap_summary ORDER BY updated_at DESC, ac_device_uuid").fetchall()
        return [dict(row) for row in rows]

    def replace_fit_ap_resources(self, ac_device_uuid: str, rows: list[dict[str, object | None]]) -> None:
        now = self._now()
        rows = self._dedupe_fit_ap_resource_rows(rows)
        self._warn_duplicate_apid_identities(ac_device_uuid, rows)
        with self.database.connect() as conn:
            current_uuids: list[str] = []
            for row in rows:
                payload = self._upsert_fit_ap_resource(conn, ac_device_uuid, row, now)
                current_uuids.append(str(payload["ap_uuid"]))
            if current_uuids:
                placeholders = ", ".join("?" for _ in current_uuids)
                conn.execute(f"DELETE FROM ac_fit_ap_resources WHERE ac_device_uuid = ? AND ap_uuid NOT IN ({placeholders})", [ac_device_uuid, *current_uuids])
            else:
                conn.execute("DELETE FROM ac_fit_ap_resources WHERE ac_device_uuid = ?", (ac_device_uuid,))
            conn.commit()

    def upsert_fit_ap_resource(
        self,
        ac_device_uuid: str,
        row: dict[str, object | None],
    ) -> dict[str, object | None]:
        """Persist one selected AP without deleting the AC's other resources."""
        with self.database.connect() as conn:
            payload = self._upsert_fit_ap_resource(conn, ac_device_uuid, row, self._now())
            conn.commit()
        return payload

    def _upsert_fit_ap_resource(
        self,
        conn,
        ac_device_uuid: str,
        row: dict[str, object | None],
        now: str,
    ) -> dict[str, object | None]:
        ap_uuid = self._resolve_fit_ap_entity_uuid(conn, ac_device_uuid, row)
        resource_data = {**row, "ac_device_uuid": ac_device_uuid, "ap_uuid": ap_uuid}
        station = normalize_station_value(resource_data)
        if station and not str(resource_data.get("site") or "").strip():
            resource_data["site"] = station
        existing_resource = conn.execute(
            "SELECT * FROM ac_fit_ap_resources WHERE ap_uuid = ? ORDER BY id DESC LIMIT 1",
            (ap_uuid,),
        ).fetchone()
        if existing_resource is not None:
            existing_data = dict(existing_resource)
            for field in FIT_AP_OPTIONAL_DETAIL_FIELDS:
                if resource_data.get(field) in (None, "") and existing_data.get(field) not in (None, ""):
                    resource_data[field] = existing_data[field]
        if _has_lldp_payload(resource_data):
            source = resource_data.get("lldp_source") or resource_data.get("source") or "ac_bulk_lldp"
            lldp_data = normalize_lldp_payload({**resource_data, "lldp_source": source}, str(source))
            resource_data.update(
                merge_lldp_payload(dict(existing_resource) if existing_resource is not None else {}, lldp_data)
            )
            resource_data["lldp_neighbor"] = resource_data.get("lldp_neighbor_name")
        payload = self._payload(FIT_AP_RESOURCE_FIELDS, resource_data)
        payload["serial_number"] = self._clean_identity_value(payload.get("serial_number")) or None
        payload["collected_at"] = payload.get("collected_at") or now
        payload["updated_at"] = payload.get("updated_at") or now
        columns = ", ".join(FIT_AP_RESOURCE_FIELDS)
        placeholders = ", ".join("?" for _ in FIT_AP_RESOURCE_FIELDS)
        updates = ", ".join(
            f"{field} = excluded.{field}"
            for field in FIT_AP_RESOURCE_FIELDS
            if field not in {"ac_device_uuid", "ap_uuid"}
        )
        conn.execute(
            f"""
            INSERT INTO ac_fit_ap_resources ({columns})
            VALUES ({placeholders})
            ON CONFLICT(ap_uuid) DO UPDATE SET {updates}
            """,
            [payload[field] for field in FIT_AP_RESOURCE_FIELDS],
        )
        self._append_resource_history(conn, payload)
        self._upsert_ap_entity(conn, payload)
        self._append_ap_resource_snapshot(conn, payload)
        self._append_radio_history(conn, payload)
        self._append_resource_lldp_history(conn, payload)
        return payload

    def list_fit_ap_resources(self, ac_device_uuid: str) -> list[dict[str, object | None]]:
        return self._list_fit_ap_resources(ac_device_uuid, include_metadata=False)

    def list_fit_ap_resources_with_metadata(self, ac_device_uuid: str) -> list[dict[str, object | None]]:
        rows = self._list_fit_ap_resources(ac_device_uuid, include_metadata=True)
        rows = self._enrich_resources_with_extensions(rows)
        return self._enrich_resources_with_unauthenticated_status(rows, ac_device_uuid)

    def list_all_fit_ap_resources_with_metadata(self) -> list[dict[str, object | None]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT r.*,
                       m_uuid.site_name AS site_name,
                       m_uuid.station_id AS metadata_station_id,
                       m_uuid.station_override_enabled AS metadata_station_override_enabled,
                       m_uuid.station_override_source AS metadata_station_override_source,
                       m_uuid.belong_type AS metadata_belong_type,
                       m_uuid.belong_section AS metadata_belong_section,
                       m_uuid.section_start_station AS metadata_section_start_station,
                       m_uuid.section_end_station AS metadata_section_end_station,
                       m_uuid.yard_name AS metadata_yard_name,
                       m_uuid.area_name AS metadata_area_name,
                       m_uuid.mileage AS metadata_mileage,
                       m_uuid.location_note AS metadata_location_note,
                       m_uuid.direction AS metadata_direction
                FROM ac_fit_ap_resources r
                LEFT JOIN ac_fit_ap_metadata m_uuid ON m_uuid.ap_uuid = r.ap_uuid
                ORDER BY r.ap_name, r.id
                """
            ).fetchall()
        rows = self._enrich_resources_with_extensions([self._resource_with_metadata(dict(row)) for row in rows])
        return self._enrich_resources_with_unauthenticated_status(rows)

    def list_fit_ap_resources_with_metadata_for_macs(
        self,
        macs: list[str],
    ) -> list[dict[str, object | None]]:
        """按一页物理 AP MAC 批量读取 FIT-AP 资源，避免全量资源投影。"""
        normalized = sorted(
            {
                mac.replace("-", "")
                for value in macs
                if (mac := self._mac_from_text(value))
            }
        )
        if not normalized:
            return []
        expression = "replace(replace(replace(lower(COALESCE(r.ap_mac, '')), ':', ''), '-', ''), ' ', '')"
        placeholders = ", ".join("?" for _ in normalized)
        with self.database.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT r.*,
                       m_uuid.site_name AS site_name,
                       m_uuid.station_id AS metadata_station_id,
                       m_uuid.station_override_enabled AS metadata_station_override_enabled,
                       m_uuid.station_override_source AS metadata_station_override_source,
                       m_uuid.belong_type AS metadata_belong_type,
                       m_uuid.belong_section AS metadata_belong_section,
                       m_uuid.section_start_station AS metadata_section_start_station,
                       m_uuid.section_end_station AS metadata_section_end_station,
                       m_uuid.yard_name AS metadata_yard_name,
                       m_uuid.area_name AS metadata_area_name,
                       m_uuid.mileage AS metadata_mileage,
                       m_uuid.location_note AS metadata_location_note,
                       m_uuid.direction AS metadata_direction
                FROM ac_fit_ap_resources r
                LEFT JOIN ac_fit_ap_metadata m_uuid ON m_uuid.ap_uuid = r.ap_uuid
                WHERE {expression} IN ({placeholders})
                ORDER BY r.ap_name, r.id
                """,
                normalized,
            ).fetchall()
        return [self._resource_with_metadata(dict(row)) for row in rows]

    def replace_fit_ap_unauthenticated(
        self,
        ac_device_uuid: str,
        summary: dict[str, object | None],
        rows: list[dict[str, object | None]],
    ) -> None:
        now = self._now()
        with self.database.connect() as conn:
            summary_payload = self._payload(FIT_AP_UNAUTHENTICATED_SUMMARY_FIELDS, {**summary, "ac_device_uuid": ac_device_uuid})
            summary_payload["collected_at"] = summary_payload.get("collected_at") or now
            summary_payload["updated_at"] = summary_payload.get("updated_at") or now
            columns = ", ".join(FIT_AP_UNAUTHENTICATED_SUMMARY_FIELDS)
            placeholders = ", ".join("?" for _ in FIT_AP_UNAUTHENTICATED_SUMMARY_FIELDS)
            updates = ", ".join(f"{field} = excluded.{field}" for field in FIT_AP_UNAUTHENTICATED_SUMMARY_FIELDS if field != "ac_device_uuid")
            conn.execute(
                f"""
                INSERT INTO ac_fit_ap_unauthenticated_summary ({columns})
                VALUES ({placeholders})
                ON CONFLICT(ac_device_uuid) DO UPDATE SET {updates}
                """,
                [summary_payload[field] for field in FIT_AP_UNAUTHENTICATED_SUMMARY_FIELDS],
            )
            conn.execute("DELETE FROM ac_fit_ap_unauthenticated WHERE ac_device_uuid = ?", (ac_device_uuid,))
            for row in rows:
                payload = self._payload(FIT_AP_UNAUTHENTICATED_FIELDS, {**row, "ac_device_uuid": ac_device_uuid})
                payload["inferred_ap_mac"] = self._mac_from_text(payload.get("inferred_ap_mac")) or None
                payload["collected_at"] = payload.get("collected_at") or summary_payload["collected_at"] or now
                payload["updated_at"] = payload.get("updated_at") or now
                self._insert(conn, "ac_fit_ap_unauthenticated", FIT_AP_UNAUTHENTICATED_FIELDS, payload)
                history_payload = self._payload(FIT_AP_UNAUTHENTICATED_HISTORY_FIELDS, {**payload, "created_at": now})
                self._insert(conn, "ac_fit_ap_unauthenticated_history", FIT_AP_UNAUTHENTICATED_HISTORY_FIELDS, history_payload)
            conn.commit()

    def list_fit_ap_unauthenticated(self, ac_device_uuid: str) -> list[dict[str, object | None]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM ac_fit_ap_unauthenticated WHERE ac_device_uuid = ? ORDER BY ap_name, id",
                (ac_device_uuid,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_all_fit_ap_unauthenticated(self) -> list[dict[str, object | None]]:
        with self.database.connect() as conn:
            rows = conn.execute("SELECT * FROM ac_fit_ap_unauthenticated ORDER BY ac_device_uuid, ap_name, id").fetchall()
        return [dict(row) for row in rows]

    def list_fit_ap_unauthenticated_history(self, ac_device_uuid: str | None = None, limit: int = 100000) -> list[dict[str, object | None]]:
        params: list[object] = []
        where = ""
        if ac_device_uuid:
            where = "WHERE ac_device_uuid = ?"
            params.append(ac_device_uuid)
        params.append(limit)
        with self.database.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM ac_fit_ap_unauthenticated_history
                {where}
                ORDER BY collected_at DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def get_fit_ap_unauthenticated_summary(self, ac_device_uuid: str) -> dict[str, object | None] | None:
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT * FROM ac_fit_ap_unauthenticated_summary WHERE ac_device_uuid = ?",
                (ac_device_uuid,),
            ).fetchone()
        return dict(row) if row is not None else None

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

    def list_all_fit_ap_resource_history(self, limit: int = 100000) -> list[dict[str, object | None]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM ac_fit_ap_resource_history
                ORDER BY collected_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_ap_entities(self, ac_device_uuid: str | None = None) -> list[dict[str, object | None]]:
        params: list[object] = []
        where = ""
        if ac_device_uuid:
            where = "WHERE ac_device_uuid = ?"
            params.append(ac_device_uuid)
        with self.database.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM ap_entities
                {where}
                ORDER BY ap_name, id
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def list_offline_ap_entities(self, ac_device_uuid: str | None = None) -> list[dict[str, object | None]]:
        params: list[object] = []
        where = "WHERE is_offline = 1"
        if ac_device_uuid:
            where += " AND ac_device_uuid = ?"
            params.append(ac_device_uuid)
        with self.database.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM ap_entities
                {where}
                ORDER BY ap_name, id
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def list_ap_extension_points(
        self,
        *,
        search: str = "",
        station_name: str = "",
        line_side: str = "",
        direction: str = "",
        match_status: str = "",
    ) -> list[dict[str, object | None]]:
        clauses: list[str] = []
        params: list[object] = []
        if search:
            search_clauses = [
                "ap_mac_display LIKE ?",
                "ap_mac_norm LIKE ?",
                "ap_name LIKE ?",
                "ap_point_code LIKE ?",
                "belong_type LIKE ?",
                "station_name LIKE ?",
                "section_name LIKE ?",
                "section_start_station LIKE ?",
                "section_end_station LIKE ?",
                "yard_name LIKE ?",
                "area_name LIKE ?",
                "line_side LIKE ?",
                "direction LIKE ?",
                "mileage_text LIKE ?",
                "CAST(mileage_m AS TEXT) LIKE ?",
                "location_desc LIKE ?",
                "remark LIKE ?",
            ]
            clauses.append(
                f"({' OR '.join(search_clauses + (['mileage_m = ?'] if parse_mileage_to_meters(search) is not None else []))})"
            )
            like = f"%{search}%"
            params.extend([like] * len(search_clauses))
            parsed_mileage = parse_mileage_to_meters(search)
            if parsed_mileage is not None:
                params.append(float(parsed_mileage))
        for field, value in (("station_name", station_name), ("line_side", line_side), ("direction", direction)):
            if value:
                clauses.append(f"{field} = ?")
                params.append(value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.database.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM ap_extension_points
                {where}
                ORDER BY station_name, line_side, mileage_m, ap_point_code, id
                """,
                params,
            ).fetchall()
            resources = conn.execute("SELECT ap_name, ap_mac FROM ac_fit_ap_resources").fetchall()
        matched_macs = {self._extension_mac_norm(row["ap_mac"]) for row in resources if self._extension_mac_norm(row["ap_mac"])}
        result = [self._extension_with_match_status(dict(row), matched_macs) for row in rows]
        if match_status:
            result = [row for row in result if row.get("match_status") == match_status]
        return result

    def list_trackside_ap_scope_reference_rows(
        self,
    ) -> list[dict[str, object | None]]:
        with self.database.connect_readonly() as conn:
            rows = conn.execute(
                """
                  SELECT id, site_id, line_name, belong_type, station_id,
                         section_id, station_name,
                       ap_name, ap_mac_norm, ap_mac_display, raw_payload_json,
                       updated_at
                FROM ap_extension_points
                ORDER BY id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def list_fit_ap_online_scope_rows(
        self,
    ) -> list[dict[str, object | None]]:
        with self.database.connect_readonly() as conn:
            rows = conn.execute(
                """
                SELECT id, ac_device_uuid, ap_uuid, apid, ap_name, ap_mac,
                       state, state_raw, state_display, site, collected_at,
                       updated_at
                FROM ac_fit_ap_resources
                ORDER BY id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def list_trackside_ap_runtime_station_evidence_rows(
        self,
    ) -> list[dict[str, object | None]]:
        with self.database.connect_readonly() as conn:
            rows = conn.execute(
                """
                WITH normalized_lldp AS (
                    SELECT l.*,
                           LOWER(
                               REPLACE(
                                   REPLACE(REPLACE(TRIM(l.neighbor_mac), '-', ''), ':', ''),
                                   '.', ''
                               )
                           ) AS ap_mac_key
                    FROM device_lldp_neighbors l
                )
                SELECT l.neighbor_mac AS ap_mac,
                       d.station_id,
                       station.station_name,
                       d.device_uuid AS switch_device_uuid,
                       d.name AS switch_name,
                       l.local_interface AS switch_interface,
                       l.neighbor_mac AS observed_ap_mac,
                       l.collected_at AS observed_at,
                       d.device_type,
                       g.name AS group_name,
                       d.work_scope_status,
                       d.project_phase
                FROM normalized_lldp l
                JOIN devices d ON d.device_uuid = l.device_uuid
                JOIN device_groups g ON g.id = d.group_id
                JOIN ap_extension_points station
                  ON station.belong_type = '__base_station__'
                 AND station.station_id = d.station_id
                WHERE LENGTH(l.ap_mac_key) = 12
                  AND l.ap_mac_key NOT GLOB '*[^0-9a-f]*'
                  AND LOWER(TRIM(d.device_type)) IN ('sw', 'switch', '交换机')
                  AND TRIM(g.name) = '车站'
                  AND d.work_scope_status = 'included'
                  AND TRIM(d.station_id) != ''
                ORDER BY l.ap_mac_key, d.station_id, d.device_uuid, l.local_interface
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def trackside_online_status_revision(
        self,
    ) -> dict[str, object]:
        with self.database.connect_readonly() as conn:
            plan = conn.execute(
                """
                SELECT COUNT(*) AS row_count, COALESCE(MAX(updated_at), '') AS updated_at
                FROM ac_trackside_ap_plan
                WHERE mode = ?
                """,
                (TRACKSIDE_AP_PLAN_MODE,),
            ).fetchone()
            references = conn.execute(
                """
                SELECT COUNT(*) AS row_count, COALESCE(MAX(updated_at), '') AS updated_at
                FROM ap_extension_points
                """
            ).fetchone()
            resources = conn.execute(
                """
                SELECT COUNT(*) AS row_count, COALESCE(MAX(updated_at), '') AS updated_at
                FROM ac_fit_ap_resources
                """
            ).fetchone()
            station_switches = conn.execute(
                """
                SELECT COUNT(*) AS row_count, COALESCE(MAX(d.updated_at), '') AS updated_at
                FROM devices d
                JOIN device_groups g ON g.id = d.group_id
                WHERE LOWER(TRIM(d.device_type)) IN ('sw', 'switch', '交换机')
                  AND TRIM(g.name) = '车站'
                """
            ).fetchone()
            lldp = conn.execute(
                """
                SELECT COUNT(*) AS row_count, COALESCE(MAX(l.updated_at), '') AS updated_at
                FROM device_lldp_neighbors l
                JOIN devices d ON d.device_uuid = l.device_uuid
                JOIN device_groups g ON g.id = d.group_id
                WHERE LOWER(TRIM(d.device_type)) IN ('sw', 'switch', '交换机')
                  AND TRIM(g.name) = '车站'
                """
            ).fetchone()
            identity_columns = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(ap_identity_index_state)")
            }
            if identity_columns:
                fields = ["revision"]
                if "source_revision" in identity_columns:
                    fields.append("source_revision")
                identity = conn.execute(
                    f"""
                    SELECT {", ".join(fields)}
                    FROM ap_identity_index_state
                    WHERE site_id = 'current'
                    """
                ).fetchone()
            else:
                identity = None
        return {
            "plan_count": int(plan["row_count"] or 0),
            "plan_updated_at": str(plan["updated_at"] or ""),
            "reference_count": int(references["row_count"] or 0),
            "reference_updated_at": str(references["updated_at"] or ""),
            "fit_ap_count": int(resources["row_count"] or 0),
            "fit_ap_updated_at": str(resources["updated_at"] or ""),
            "station_switch_count": int(station_switches["row_count"] or 0),
            "station_switch_updated_at": str(station_switches["updated_at"] or ""),
            "station_switch_lldp_count": int(lldp["row_count"] or 0),
            "station_switch_lldp_updated_at": str(lldp["updated_at"] or ""),
            "identity_revision": int(identity["revision"] or 0) if identity else 0,
            "identity_source_revision": (
                int(identity["source_revision"])
                if (
                    identity
                    and "source_revision" in identity.keys()
                    and identity["source_revision"] is not None
                )
                else -1
            ),
        }

    def get_ap_extension_point(self, extension_id: int) -> dict[str, object | None] | None:
        with self.database.connect() as conn:
            row = conn.execute("SELECT * FROM ap_extension_points WHERE id = ?", (extension_id,)).fetchone()
        return dict(row) if row is not None else None

    def upsert_ap_extension_point(self, data: dict[str, object | None]) -> dict[str, object | None]:
        now = self._now()
        payload = self._payload(AP_EXTENSION_POINT_FIELDS, data)
        payload["station_id"] = str(payload.get("station_id") or "").strip()
        payload["section_id"] = str(payload.get("section_id") or "").strip()
        mac = normalize_ap_mac(payload.get("ap_mac_display") or payload.get("ap_mac_norm"))
        payload["ap_mac_norm"] = mac.normalized or str(payload.get("ap_mac_norm") or "").strip().casefold()
        payload["ap_mac_display"] = mac.display or str(payload.get("ap_mac_display") or "").strip()
        if payload.get("mileage_m") in (None, ""):
            payload["mileage_m"] = parse_mileage_to_meters(payload.get("mileage_text"))
        payload["created_at"] = payload.get("created_at") or now
        payload["updated_at"] = now
        extension_id = data.get("id")
        with self.database.connect() as conn:
            if extension_id:
                assignments = ", ".join(f"{field} = ?" for field in AP_EXTENSION_POINT_FIELDS if field != "created_at")
                conn.execute(
                    f"UPDATE ap_extension_points SET {assignments} WHERE id = ?",
                    [payload[field] for field in AP_EXTENSION_POINT_FIELDS if field != "created_at"] + [extension_id],
                )
            else:
                columns = ", ".join(AP_EXTENSION_POINT_FIELDS)
                placeholders = ", ".join("?" for _ in AP_EXTENSION_POINT_FIELDS)
                cursor = conn.execute(
                    f"INSERT INTO ap_extension_points ({columns}) VALUES ({placeholders})",
                    [payload[field] for field in AP_EXTENSION_POINT_FIELDS],
                )
                extension_id = cursor.lastrowid
            conn.commit()
        return self.get_ap_extension_point(int(extension_id)) or payload

    def delete_ap_extension_points(self, extension_ids: list[int]) -> int:
        ids = [int(value) for value in extension_ids if value]
        if not ids:
            return 0
        placeholders = ", ".join("?" for _ in ids)
        with self.database.connect() as conn:
            count = conn.execute(f"DELETE FROM ap_extension_points WHERE id IN ({placeholders})", ids).rowcount
            conn.commit()
        return int(count or 0)

    def clear_ap_extension_points(self) -> int:
        with self.database.connect() as conn:
            count = conn.execute("DELETE FROM ap_extension_points").rowcount
            conn.commit()
        return int(count or 0)

    def import_ap_extension_points(
        self,
        rows: list[dict[str, object | None]],
        *,
        source_file: str = "",
        template_type: str = "",
        duplicate_strategy: str = "update_by_priority",
    ) -> dict[str, int | str]:
        now = self._now()
        import_batch_id = str(uuid4())
        stats = {"total_rows": len(rows), "success_rows": 0, "updated_rows": 0, "skipped_rows": 0, "error_rows": 0}
        with self.database.connect() as conn:
            for row in rows:
                payload = self._payload(AP_EXTENSION_POINT_FIELDS, {**row, "import_batch_id": import_batch_id})
                payload["station_id"] = str(payload.get("station_id") or "").strip()
                payload["section_id"] = str(payload.get("section_id") or "").strip()
                mac = normalize_ap_mac(payload.get("ap_mac_display") or payload.get("ap_mac_norm"))
                if payload.get("ap_mac_display") and not mac.valid:
                    stats["error_rows"] += 1
                    continue
                payload["ap_mac_norm"] = mac.normalized or str(payload.get("ap_mac_norm") or "").strip().casefold()
                payload["ap_mac_display"] = mac.display or str(payload.get("ap_mac_display") or "").strip()
                payload["created_at"] = payload.get("created_at") or now
                payload["updated_at"] = now
                existing_id = self._find_ap_extension_existing_id(conn, row)
                if existing_id and duplicate_strategy == "skip_existing":
                    stats["skipped_rows"] += 1
                    continue
                if existing_id:
                    if not payload.get("ap_mac_norm") and not payload.get("ap_mac_display"):
                        existing = conn.execute("SELECT ap_mac_norm, ap_mac_display FROM ap_extension_points WHERE id = ?", (existing_id,)).fetchone()
                        if existing is not None:
                            payload["ap_mac_norm"] = existing["ap_mac_norm"]
                            payload["ap_mac_display"] = existing["ap_mac_display"]
                    assignments = ", ".join(f"{field} = ?" for field in AP_EXTENSION_POINT_FIELDS if field != "created_at")
                    conn.execute(
                        f"UPDATE ap_extension_points SET {assignments} WHERE id = ?",
                        [payload[field] for field in AP_EXTENSION_POINT_FIELDS if field != "created_at"] + [existing_id],
                    )
                    stats["updated_rows"] += 1
                else:
                    columns = ", ".join(AP_EXTENSION_POINT_FIELDS)
                    placeholders = ", ".join("?" for _ in AP_EXTENSION_POINT_FIELDS)
                    conn.execute(
                        f"INSERT INTO ap_extension_points ({columns}) VALUES ({placeholders})",
                        [payload[field] for field in AP_EXTENSION_POINT_FIELDS],
                    )
                    stats["success_rows"] += 1
            batch_payload = self._payload(
                AP_EXTENSION_IMPORT_BATCH_FIELDS,
                {
                    "source_file": source_file,
                    "template_type": template_type,
                    "import_time": now,
                    "total_rows": stats["total_rows"],
                    "success_rows": stats["success_rows"],
                    "updated_rows": stats["updated_rows"],
                    "skipped_rows": stats["skipped_rows"],
                    "error_rows": stats["error_rows"],
                },
            )
            columns = ", ".join(AP_EXTENSION_IMPORT_BATCH_FIELDS)
            placeholders = ", ".join("?" for _ in AP_EXTENSION_IMPORT_BATCH_FIELDS)
            conn.execute(
                f"INSERT INTO ap_extension_import_batches ({columns}) VALUES ({placeholders})",
                [batch_payload[field] for field in AP_EXTENSION_IMPORT_BATCH_FIELDS],
            )
            conn.commit()
        return {**stats, "import_batch_id": import_batch_id}

    def update_ap_entity_extension_by_mac(self, ap_mac: str, fields: dict[str, object | None]) -> int:
        normalized_mac = self._mac_from_text(ap_mac)
        if not normalized_mac:
            return 0
        allowed = {"station", "milestone", "location_note", "direction"}
        values = {key: str(value or "").strip() for key, value in fields.items() if key in allowed}
        if not values:
            return 0
        values["updated_at"] = self._now()
        assignments = ", ".join(f"{field} = ?" for field in values)
        with self.database.connect() as conn:
            count = conn.execute(
                f"UPDATE ap_entities SET {assignments} WHERE lower(ap_mac) = ?",
                [*values.values(), normalized_mac.casefold()],
            ).rowcount
            conn.commit()
        return int(count or 0)

    def replace_fit_ap_optical(self, ac_device_uuid: str, rows: list[dict[str, object | None]]) -> None:
        now = self._now()
        with self.database.connect() as conn:
            current_rows = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM ac_fit_ap_optical WHERE ac_device_uuid = ?",
                    (ac_device_uuid,),
                ).fetchall()
            ]
            merged: dict[tuple[str, str], dict[str, object | None]] = {}
            passthrough: list[dict[str, object | None]] = []
            for current in current_rows:
                key = _fit_ap_optical_merge_key(current)
                if key:
                    merged[key] = current
                else:
                    passthrough.append(current)

            current_payloads: list[dict[str, object | None]] = []
            success_count = 0
            for row in rows:
                resource = self._resource_for_payload(conn, ac_device_uuid, row)
                payload = self._payload(FIT_AP_OPTICAL_FIELDS, {**row, "ac_device_uuid": ac_device_uuid})
                payload["ap_uuid"] = payload.get("ap_uuid") or resource.get("ap_uuid") or str(uuid4())
                payload["ap_name"] = payload.get("ap_name") or resource.get("ap_name")
                payload["ap_mac"] = payload.get("ap_mac") or resource.get("ap_mac")
                payload["ap_ip"] = payload.get("ap_ip") or resource.get("ap_ip")
                payload["site"] = payload.get("site") or resource.get("site_name") or resource.get("site")
                if _has_lldp_payload(payload):
                    lldp_data = normalize_lldp_payload(
                        {**payload, "lldp_source": payload.get("lldp_source") or payload.get("source") or "ap_direct_lldp"},
                        str(payload.get("lldp_source") or payload.get("source") or "ap_direct_lldp"),
                    )
                    payload["_history_lldp_source"] = lldp_data.get("lldp_source")
                    payload.update(merge_lldp_payload(resource, lldp_data))
                    payload["lldp_neighbor"] = payload.get("lldp_neighbor_name")
                    payload["neighbor_device_name"] = payload.get("neighbor_device_name") or payload.get("lldp_neighbor_name")
                    payload["neighbor_mac"] = payload.get("neighbor_mac") or payload.get("lldp_neighbor_mac")
                    payload["neighbor_interface"] = payload.get("neighbor_interface") or payload.get("lldp_neighbor_interface")
                payload.update(resolve_fit_ap_link_info(payload))
                payload["link_match_status"] = payload.get("link_match_status") or payload.get("optical_match_status") or resolve_optical_match_status(payload, payload)
                payload["source"] = payload.get("source") or "ap_optical_diag"
                payload["collected_at"] = payload.get("collected_at") or now
                payload["updated_at"] = payload.get("updated_at") or now
                current_payloads.append(payload)
                key = _fit_ap_optical_merge_key(payload)
                current = merged.get(key) if key else None
                if current is not None and _fit_ap_optical_prefer_score(current) > _fit_ap_optical_prefer_score(payload):
                    merged[key] = _merge_failed_fit_ap_optical_payload(current, payload)
                    continue
                if _is_fit_ap_optical_success_payload(payload):
                    success_count += 1
                    if key:
                        merged[key] = payload
                    else:
                        passthrough.append(payload)
                    continue
                if key and key in merged:
                    merged[key] = _merge_failed_fit_ap_optical_payload(merged[key], payload)
                elif key:
                    merged[key] = payload
                else:
                    passthrough.append(payload)

            if rows and success_count == 0:
                app_logger.log_warning(
                    "FIT_AP_OPTICAL_DB_SAVE_SKIPPED",
                    f"ac_device_uuid={ac_device_uuid}, error=no successful AP optical rows; keeping previous data",
                )
                return

            conn.execute("DELETE FROM ac_fit_ap_optical WHERE ac_device_uuid = ?", (ac_device_uuid,))
            columns = ", ".join(FIT_AP_OPTICAL_FIELDS)
            placeholders = ", ".join("?" for _ in FIT_AP_OPTICAL_FIELDS)
            for payload in [*merged.values(), *passthrough]:
                conn.execute(f"INSERT INTO ac_fit_ap_optical ({columns}) VALUES ({placeholders})", [payload[field] for field in FIT_AP_OPTICAL_FIELDS])
                self._update_fit_ap_resource_link_info(conn, ac_device_uuid, payload)
            for payload in current_payloads:
                history_payload = self._payload(FIT_AP_OPTICAL_HISTORY_FIELDS, {**payload, "created_at": now})
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
                        "source": payload.get("_history_lldp_source") or payload.get("lldp_source") or "ap_direct_lldp",
                        "local_interface": payload.get("lldp_local_interface") or payload.get("interface_name"),
                        "local_interface_normalized": payload.get("lldp_local_interface_normalized"),
                        "lldp_neighbor": payload.get("lldp_neighbor_name") or payload.get("lldp_neighbor"),
                        "neighbor_name": payload.get("lldp_neighbor_name") or payload.get("neighbor_name"),
                        "neighbor_mac": payload.get("lldp_neighbor_mac") or payload.get("neighbor_mac"),
                        "neighbor_mac_normalized": payload.get("lldp_neighbor_mac_normalized"),
                        "neighbor_interface": payload.get("lldp_neighbor_interface") or payload.get("neighbor_interface"),
                        "neighbor_device_name": payload.get("neighbor_device_name") or payload.get("lldp_neighbor_name"),
                        "session_id": payload.get("collect_run_uuid"),
                        "is_changed": self._lldp_history_changed(conn, payload.get("ap_uuid"), payload),
                        "conflict_flag": 1 if str(payload.get("lldp_match_status") or payload.get("link_match_status") or "") == "conflict" else 0,
                        "created_at": now,
                    },
                )
                lldp_columns = ", ".join(FIT_AP_LLDP_HISTORY_FIELDS)
                lldp_placeholders = ", ".join("?" for _ in FIT_AP_LLDP_HISTORY_FIELDS)
                conn.execute(
                    f"INSERT INTO ac_fit_ap_lldp_history ({lldp_columns}) VALUES ({lldp_placeholders})",
                    [lldp_payload[field] for field in FIT_AP_LLDP_HISTORY_FIELDS],
                )
                self._append_ap_lldp_history(conn, lldp_payload)
                self._append_ap_optical_history(conn, payload)
            conn.commit()

    def list_fit_ap_optical(self, ac_device_uuid: str) -> list[dict[str, object | None]]:
        return sorted(
            _latest_rows_by_ap_identity(self._list_rows("ac_fit_ap_optical", ac_device_uuid, "ap_name, id")),
            key=lambda row: (str(row.get("ap_name") or ""), _int_value(row.get("id"))),
        )

    def repair_invalid_fit_ap_association_projection(
        self,
        ac_device_uuid: str,
        ap_uuids: list[str] | None = None,
        *,
        apply: bool = False,
    ) -> dict[str, object]:
        """Preview or clear known-invalid LLDP association projections.

        This deliberately leaves AP resources, history and raw collection files
        untouched. ``apply`` must be explicitly enabled by a maintenance caller.
        A subsequent optical refresh repopulates the cleared projection.
        """

        requested = {str(value or "").strip() for value in ap_uuids or [] if str(value or "").strip()}
        with self.database.connect() as conn:
            optical_rows = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM ac_fit_ap_optical WHERE ac_device_uuid = ?",
                    (str(ac_device_uuid),),
                ).fetchall()
            ]
            if requested:
                optical_rows = [row for row in optical_rows if str(row.get("ap_uuid") or "") in requested]
            candidates = [row for row in optical_rows if _is_invalid_fit_ap_association_projection(row)]
            candidate_ids = [int(row["id"]) for row in candidates if row.get("id") is not None]
            candidate_ap_uuids = sorted(
                {str(row.get("ap_uuid") or "") for row in candidates if str(row.get("ap_uuid") or "")}
            )
            result: dict[str, object] = {
                "applied": False,
                "candidate_count": len(candidates),
                "cleared_optical_rows": 0,
                "cleared_resource_rows": 0,
                "ap_uuids": candidate_ap_uuids,
                "raw_logs_preserved": True,
            }
            if not apply or not candidates:
                return result

            now = self._now()
            projection = {
                "lldp_neighbor": "",
                "lldp_source": "",
                "lldp_confidence": 0,
                "lldp_collected_at": None,
                "lldp_local_interface": "",
                "lldp_local_interface_normalized": "",
                "lldp_neighbor_name": "",
                "lldp_neighbor_mac": "",
                "lldp_neighbor_mac_normalized": "",
                "lldp_neighbor_interface": "",
                "lldp_match_status": "unknown",
                "neighbor_interface": "",
                "neighbor_mac": "",
                "neighbor_device_name": "",
                "neighbor_rx_power": None,
                "link_match_status": "unknown",
                "optical_match_status": "unknown",
                "optical_alarm_status": None,
                "updated_at": now,
            }
            optical_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(ac_fit_ap_optical)")}
            optical_updates = {key: value for key, value in projection.items() if key in optical_columns}
            assignments = ", ".join(f"{key} = ?" for key in optical_updates)
            for row_id in candidate_ids:
                conn.execute(
                    f"UPDATE ac_fit_ap_optical SET {assignments} WHERE id = ? AND ac_device_uuid = ?",
                    [*optical_updates.values(), row_id, str(ac_device_uuid)],
                )
            result["cleared_optical_rows"] = len(candidate_ids)

            resource_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(ac_fit_ap_resources)")}
            resource_updates = {key: value for key, value in projection.items() if key in resource_columns}
            resource_assignments = ", ".join(f"{key} = ?" for key in resource_updates)
            if candidate_ap_uuids and resource_assignments:
                placeholders = ", ".join("?" for _ in candidate_ap_uuids)
                cursor = conn.execute(
                    f"UPDATE ac_fit_ap_resources SET {resource_assignments} "
                    f"WHERE ac_device_uuid = ? AND ap_uuid IN ({placeholders})",
                    [*resource_updates.values(), str(ac_device_uuid), *candidate_ap_uuids],
                )
                result["cleared_resource_rows"] = int(cursor.rowcount or 0)
            conn.commit()
            result["applied"] = True
            return result

    def list_all_fit_ap_optical(self) -> list[dict[str, object | None]]:
        with self.database.connect() as conn:
            rows = conn.execute("SELECT * FROM ac_fit_ap_optical ORDER BY neighbor_device_name, neighbor_interface, ap_name, id").fetchall()
        return sorted(
            _latest_rows_by_ap_identity([dict(row) for row in rows]),
            key=lambda row: (str(row.get("neighbor_device_name") or ""), str(row.get("neighbor_interface") or ""), str(row.get("ap_name") or "")),
        )

    def list_fit_ap_optical_for_macs(
        self,
        macs: list[str],
    ) -> list[dict[str, object | None]]:
        normalized = sorted(
            {
                mac.replace("-", "")
                for value in macs
                if (mac := self._mac_from_text(value))
            }
        )
        if not normalized:
            return []
        expression = "replace(replace(replace(lower(COALESCE(ap_mac, '')), ':', ''), '-', ''), ' ', '')"
        placeholders = ", ".join("?" for _ in normalized)
        with self.database.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM ac_fit_ap_optical
                WHERE {expression} IN ({placeholders})
                ORDER BY ap_name, id
                """,
                normalized,
            ).fetchall()
        return _latest_rows_by_ap_identity([dict(row) for row in rows])

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

    def list_fit_ap_history_page(
        self,
        history_kind: str,
        ap_uuid: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, object | None]]:
        table = _fit_ap_history_table(history_kind)
        with self.database.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM {table} WHERE ap_uuid = ? ORDER BY collected_at DESC, id DESC LIMIT ? OFFSET ?",
                (ap_uuid, max(1, int(limit)), max(0, int(offset))),
            ).fetchall()
        return [dict(row) for row in rows]

    def count_fit_ap_history(self, history_kind: str, ap_uuid: str) -> int:
        table = _fit_ap_history_table(history_kind)
        with self.database.connect() as conn:
            row = conn.execute(f"SELECT COUNT(*) AS total FROM {table} WHERE ap_uuid = ?", (ap_uuid,)).fetchone()
        return int(row["total"] if row is not None else 0)

    def list_all_ap_optical_history(self, limit: int = 100000) -> list[dict[str, object | None]]:
        with self.database.connect() as conn:
            entity_rows = conn.execute(
                """
                SELECT id, ap_uuid, NULL AS ap_name, NULL AS ap_mac, side, device_uuid,
                       interface_name, rx_power, tx_power, alarm_status AS optical_alarm_status,
                       collected_at, data_source, created_at
                FROM ap_optical_history
                WHERE side = 'ap'
                ORDER BY collected_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            fit_rows = conn.execute(
                """
                SELECT id, ap_uuid, ap_name, ap_mac, 'ap' AS side, ac_device_uuid AS device_uuid,
                       interface_name, rx_power, tx_power,
                       COALESCE(optical_alarm_status, status) AS optical_alarm_status,
                       collected_at, 'ac_fit_ap_optical_history' AS data_source, created_at
                FROM ac_fit_ap_optical_history
                ORDER BY collected_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in entity_rows] + [dict(row) for row in fit_rows]

    def get_previous_ap_optical_history(
        self,
        identity: dict[str, str],
        before_collected_at: str | None = None,
    ) -> dict[str, object | None] | None:
        with self.database.connect() as conn:
            clauses, params = self._ap_identity_clauses(identity, allowed=("ap_uuid",))
            if clauses:
                before_clause = ""
                if before_collected_at:
                    before_clause = "AND collected_at < ?"
                    params.append(before_collected_at)
                row = conn.execute(
                    f"""
                    SELECT * FROM ap_optical_history
                    WHERE side = 'ap'
                      AND ({' OR '.join(clauses)})
                      {before_clause}
                    ORDER BY collected_at DESC, id DESC
                    LIMIT 1
                    """,
                    params,
                ).fetchone()
                if row is not None:
                    return dict(row)
            clauses, params = self._ap_identity_clauses(identity, allowed=("ap_uuid", "ap_mac"))
            if not clauses:
                return None
            before_clause = ""
            if before_collected_at:
                before_clause = "AND collected_at < ?"
                params.append(before_collected_at)
            row = conn.execute(
                f"""
                SELECT * FROM ac_fit_ap_optical_history
                WHERE ({' OR '.join(clauses)})
                  {before_clause}
                  AND (
                    rx_power IS NOT NULL OR optical_alarm_status IS NOT NULL OR status IS NOT NULL
                  )
                ORDER BY collected_at DESC, id DESC
                LIMIT 1
                """,
                params,
            ).fetchone()
        return dict(row) if row is not None else None

    def get_previous_ap_lldp_history(
        self,
        identity: dict[str, str],
        before_collected_at: str | None = None,
    ) -> dict[str, object | None] | None:
        clauses, params = self._ap_identity_clauses(identity, allowed=("ap_uuid", "ap_mac", "serial_number"))
        if not clauses:
            return None
        before_clause = ""
        if before_collected_at:
            before_clause = "AND collected_at < ?"
            params.append(before_collected_at)
        with self.database.connect() as conn:
            row = conn.execute(
                f"""
                SELECT * FROM ap_lldp_history
                WHERE ({' OR '.join(clauses)})
                  {before_clause}
                  AND neighbor_interface IS NOT NULL
                ORDER BY collected_at DESC, id DESC
                LIMIT 1
                """,
                params,
            ).fetchone()
            if row is not None:
                return dict(row)
            clauses, params = self._ap_identity_clauses(identity, allowed=("ap_uuid", "ap_mac"))
            before_clause = ""
            if before_collected_at:
                before_clause = "AND collected_at < ?"
                params.append(before_collected_at)
            row = conn.execute(
                f"""
                SELECT * FROM ac_fit_ap_lldp_history
                WHERE ({' OR '.join(clauses)})
                  {before_clause}
                  AND neighbor_interface IS NOT NULL
                ORDER BY collected_at DESC, id DESC
                LIMIT 1
                """,
                params,
            ).fetchone()
        return dict(row) if row is not None else None

    def list_latest_ap_lldp_history(self, ap_uuid: str) -> dict[str, object | None] | None:
        with self.database.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM ap_lldp_history
                WHERE ap_uuid = ?
                ORDER BY is_latest DESC, collected_at DESC, id DESC
                LIMIT 1
                """,
                (ap_uuid,),
            ).fetchone()
        return dict(row) if row is not None else None

    def list_latest_ap_lldp_histories(self, limit: int = 100000) -> list[dict[str, object | None]]:
        with self.database.connect() as conn:
            entity_rows = conn.execute(
                """
                SELECT id, ap_uuid, ap_mac, ap_name, serial_number,
                       neighbor_switch_name AS neighbor_device_name,
                       neighbor_switch_sysname AS lldp_neighbor,
                       neighbor_interface,
                       collected_at,
                       created_at,
                       'ap_lldp_history' AS data_source
                FROM ap_lldp_history
                WHERE neighbor_interface IS NOT NULL
                ORDER BY collected_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            fit_rows = conn.execute(
                """
                SELECT id, ap_uuid, ap_mac, ap_name, NULL AS serial_number,
                       neighbor_device_name,
                       lldp_neighbor,
                       neighbor_interface,
                       collected_at,
                       created_at,
                       'ac_fit_ap_lldp_history' AS data_source
                FROM ac_fit_ap_lldp_history
                WHERE neighbor_interface IS NOT NULL
                ORDER BY collected_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        rows = [dict(row) for row in entity_rows] + [dict(row) for row in fit_rows]
        latest: dict[tuple[str, str], dict[str, object | None]] = {}
        passthrough: list[dict[str, object | None]] = []
        for row in rows:
            key = _fit_ap_optical_merge_key(row) or _ap_identity_key(row)
            if key is None:
                passthrough.append(row)
                continue
            current = latest.get(key)
            if current is None or _latest_row_score(row) >= _latest_row_score(current):
                latest[key] = row
        return [*latest.values(), *passthrough]

    def list_all_ap_lldp_history(self, limit: int = 100000) -> list[dict[str, object | None]]:
        with self.database.connect() as conn:
            entity_rows = conn.execute(
                """
                SELECT id, ap_uuid, ap_mac, ap_name, serial_number,
                       neighbor_switch_name AS neighbor_device_name,
                       neighbor_switch_sysname AS lldp_neighbor,
                       neighbor_interface,
                       collected_at,
                       created_at,
                       'ap_lldp_history' AS data_source
                FROM ap_lldp_history
                WHERE neighbor_interface IS NOT NULL
                ORDER BY collected_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            fit_rows = conn.execute(
                """
                SELECT id, ap_uuid, ap_mac, ap_name, NULL AS serial_number,
                       neighbor_device_name,
                       lldp_neighbor,
                       neighbor_interface,
                       collected_at,
                       created_at,
                       'ac_fit_ap_lldp_history' AS data_source
                FROM ac_fit_ap_lldp_history
                WHERE neighbor_interface IS NOT NULL
                ORDER BY collected_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in entity_rows] + [dict(row) for row in fit_rows]

    def get_fit_ap_resource(self, ac_device_uuid: str, ap_name: str) -> dict[str, object | None] | None:
        rows = self.list_fit_ap_resources_with_metadata(ac_device_uuid)
        return next((row for row in rows if row.get("ap_name") == ap_name), None)

    def get_fit_ap_resource_by_uuid(self, ac_device_uuid: str, ap_uuid: str) -> dict[str, object | None] | None:
        rows = self.list_fit_ap_resources_with_metadata(ac_device_uuid)
        return next((row for row in rows if row.get("ap_uuid") == ap_uuid), None)

    def upsert_fit_ap_metadata(self, data: dict[str, object | None]) -> dict[str, object | None]:
        normalized_data = dict(data)
        if not normalized_data.get("site_name"):
            normalized_data["site_name"] = normalized_data.get("belong_station") or normalized_data.get("station_name")
        if not normalized_data.get("belong_section"):
            normalized_data["belong_section"] = normalized_data.get("section_name")
        payload = self._payload(FIT_AP_METADATA_FIELDS, normalized_data)
        payload["station_id"] = str(payload.get("station_id") or "")
        payload["station_override_enabled"] = bool(payload.get("station_override_enabled"))
        payload["station_override_source"] = str(payload.get("station_override_source") or "")
        if not payload.get("ap_uuid") and payload.get("ap_name"):
            resource = self.get_fit_ap_resource_by_name_any_ac(str(payload["ap_name"]))
            if resource:
                payload["ap_uuid"] = resource.get("ap_uuid")
        if not payload.get("ap_uuid"):
            payload["ap_uuid"] = str(uuid4())
        if "station_override_enabled" not in normalized_data:
            payload["station_override_enabled"] = int(bool(payload.get("station_id") or payload.get("site_name")))
        else:
            payload["station_override_enabled"] = int(bool(payload.get("station_override_enabled")))
        if payload["station_override_enabled"] and not payload.get("station_override_source"):
            payload["station_override_source"] = "manual"
        if not payload["station_override_enabled"]:
            payload["station_id"] = ""
            payload["site_name"] = ""
            payload["station_override_source"] = ""
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
        return self.update_fit_ap_metadata_fields(
            ap_uuids,
            {
                "site_name": site_name,
                "station_override_enabled": bool(str(site_name or "").strip()),
                "station_override_source": "manual" if str(site_name or "").strip() else "",
            },
        )

    def update_fit_ap_metadata_fields(self, ap_uuids: list[str], fields: dict[str, object | None]) -> int:
        allowed = {
            "site_name",
            "station_id",
            "station_override_enabled",
            "station_override_source",
            "belong_type",
            "belong_section",
            "section_start_station",
            "section_end_station",
            "yard_name",
            "area_name",
            "mileage",
            "location_note",
            "direction",
        }
        values = {key: value for key, value in fields.items() if key in allowed}
        if "station_override_enabled" in values:
            values["station_override_enabled"] = int(bool(values["station_override_enabled"]))
        if not values.get("station_override_enabled", 1):
            values.update(station_id="", site_name="", station_override_source="")
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

    def upsert_fit_ap_detail(self, data: dict[str, object | None]) -> dict[str, object | None]:
        payload = self._payload(FIT_AP_DETAIL_FIELDS, data)
        now = self._now()
        payload["collected_at"] = payload.get("collected_at") or now
        payload["created_at"] = payload.get("created_at") or now
        payload["updated_at"] = payload.get("updated_at") or now
        if not payload.get("ap_uuid") or not payload.get("ac_device_uuid"):
            raise ValueError("FIT-AP 详细信息缺少 AP 或 AC 身份")
        columns = ", ".join(FIT_AP_DETAIL_FIELDS)
        placeholders = ", ".join("?" for _ in FIT_AP_DETAIL_FIELDS)
        updates = ", ".join(
            f"{field} = excluded.{field}"
            for field in FIT_AP_DETAIL_FIELDS
            if field not in {"ap_uuid", "created_at"}
        )
        with self.database.connect() as conn:
            conn.execute(
                f"""
                INSERT INTO ac_fit_ap_details ({columns})
                VALUES ({placeholders})
                ON CONFLICT(ap_uuid) DO UPDATE SET {updates}
                """,
                [payload[field] for field in FIT_AP_DETAIL_FIELDS],
            )
            conn.commit()
        return self.get_fit_ap_detail(str(payload["ap_uuid"])) or payload

    def get_fit_ap_detail(self, ap_uuid: str) -> dict[str, object | None] | None:
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT * FROM ac_fit_ap_details WHERE ap_uuid = ?",
                (str(ap_uuid),),
            ).fetchone()
        return dict(row) if row is not None else None

    def list_fit_ap_details(self, ac_device_uuid: str) -> list[dict[str, object | None]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM ac_fit_ap_details WHERE ac_device_uuid = ? ORDER BY ap_name, ap_uuid",
                (str(ac_device_uuid),),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_fit_ap_details_for_macs(self, macs: list[str]) -> list[dict[str, object | None]]:
        """按当前页 AP MAC 批量读取详细信息索引，避免列表页逐 AP 查询。"""
        normalized = sorted(
            {
                self._mac_from_text(value).replace("-", "")
                for value in macs
                if self._mac_from_text(value)
            }
        )
        if not normalized:
            return []
        placeholders = ", ".join("?" for _ in normalized)
        expression = "replace(replace(replace(replace(lower(COALESCE(r.ap_mac, '')), ':', ''), '-', ''), '.', ''), ' ', '')"
        with self.database.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT d.*
                FROM ac_fit_ap_details d
                JOIN ac_fit_ap_resources r ON r.ap_uuid = d.ap_uuid
                WHERE {expression} IN ({placeholders})
                """,
                normalized,
            ).fetchall()
        return [dict(row) for row in rows]

    def replace_fit_ap_radio_details(
        self,
        ap_uuid: str,
        rows: list[dict[str, object | None]],
    ) -> None:
        now = self._now()
        with self.database.connect() as conn:
            conn.execute("DELETE FROM ac_fit_ap_radio_details WHERE ap_uuid = ?", (str(ap_uuid),))
            for row in rows:
                payload = self._payload(
                    FIT_AP_RADIO_DETAIL_FIELDS,
                    {**row, "ap_uuid": str(ap_uuid)},
                )
                payload["collected_at"] = payload.get("collected_at") or now
                payload["created_at"] = payload.get("created_at") or now
                payload["updated_at"] = payload.get("updated_at") or now
                columns = ", ".join(FIT_AP_RADIO_DETAIL_FIELDS)
                placeholders = ", ".join("?" for _ in FIT_AP_RADIO_DETAIL_FIELDS)
                conn.execute(
                    f"INSERT INTO ac_fit_ap_radio_details ({columns}) VALUES ({placeholders})",
                    [payload[field] for field in FIT_AP_RADIO_DETAIL_FIELDS],
                )
            conn.commit()

    def list_fit_ap_radio_details(self, ap_uuid: str) -> list[dict[str, object | None]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM ac_fit_ap_radio_details WHERE ap_uuid = ? ORDER BY radio_id",
                (str(ap_uuid),),
            ).fetchall()
        return [dict(row) for row in rows]

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
            conn.execute(f"DELETE FROM ac_fit_ap_details WHERE ap_uuid IN ({placeholders})", ap_uuids)
            conn.execute(f"DELETE FROM ac_fit_ap_radio_details WHERE ap_uuid IN ({placeholders})", ap_uuids)
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

    def get_trackside_ap_plan_mode(self) -> str:
        return TRACKSIDE_AP_PLAN_MODE

    def set_trackside_ap_plan_mode(self, mode: str) -> None:
        mode = self._normalize_trackside_plan_mode(mode)
        now = self._now()
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO ac_trackside_ap_plan_settings (key, value, updated_at)
                VALUES ('active_mode', ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (mode, now),
            )
            conn.commit()

    def list_trackside_ap_plan(self, mode: str | None = None) -> list[dict[str, object | None]]:
        if mode == TRACKSIDE_AP_PLAN_MODE:
            return self._list_trackside_ap_plan_by_mode(TRACKSIDE_AP_PLAN_MODE)

        params: list[object] = []
        where = ""
        if mode is not None:
            where = "WHERE mode = ?"
            params.append(self._normalize_trackside_plan_mode(mode))
        with self.database.connect_readonly() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM ac_trackside_ap_plan
                {where}
                ORDER BY mode, sort_order, station_name
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def replace_trackside_ap_plan_rows(self, mode: str, rows: list[dict[str, object | None]]) -> None:
        mode = self._normalize_trackside_plan_mode(mode)
        now = self._now()
        saved_payloads: list[dict[str, object | None]] = []
        with self.database.connect() as conn:
            conn.execute("DELETE FROM ac_trackside_ap_plan WHERE mode = ?", (mode,))
            for index, row in enumerate(rows):
                payload = self._trackside_plan_payload(mode, row, index, now)
                saved_payloads.append(payload)
                columns = ", ".join(TRACKSIDE_PLAN_FIELDS)
                placeholders = ", ".join("?" for _ in TRACKSIDE_PLAN_FIELDS)
                conn.execute(
                    f"INSERT INTO ac_trackside_ap_plan ({columns}) VALUES ({placeholders})",
                    [payload[field] for field in TRACKSIDE_PLAN_FIELDS],
                )
            conn.commit()

    def upsert_trackside_ap_plan_row(self, mode: str, row: dict[str, object | None]) -> None:
        mode = self._normalize_trackside_plan_mode(mode)
        now = self._now()
        payload = self._trackside_plan_payload(mode, row, int(row.get("sort_order") or 0), now)
        columns = ", ".join(TRACKSIDE_PLAN_FIELDS)
        placeholders = ", ".join("?" for _ in TRACKSIDE_PLAN_FIELDS)
        updates = ", ".join(f"{field} = excluded.{field}" for field in TRACKSIDE_PLAN_FIELDS if field not in {"mode", "station_name", "created_at"})
        with self.database.connect() as conn:
            conn.execute(
                f"""
                INSERT INTO ac_trackside_ap_plan ({columns})
                VALUES ({placeholders})
                ON CONFLICT(mode, station_name) DO UPDATE SET {updates}
                """,
                [payload[field] for field in TRACKSIDE_PLAN_FIELDS],
            )
            conn.commit()

    def delete_trackside_ap_plan_rows(self, mode: str, station_names: list[str]) -> None:
        mode = self._normalize_trackside_plan_mode(mode)
        names = [str(name or "").strip() for name in station_names if str(name or "").strip()]
        if not names:
            return
        placeholders = ", ".join("?" for _ in names)
        with self.database.connect() as conn:
            conn.execute(f"DELETE FROM ac_trackside_ap_plan WHERE mode = ? AND station_name IN ({placeholders})", [mode, *names])
            conn.commit()

    def list_active_trackside_plan_capacity_details(self) -> dict[str, dict[str, object | None]]:
        rows = self.list_trackside_ap_plan(TRACKSIDE_AP_PLAN_MODE)
        if not rows:
            return {}
        old_details = self.list_station_ap_capacity_details()
        return {
            str(row["station_name"]): {
                "ap_total": int(row.get("ap_count") or 0),
                "remark": str(row.get("remark") or "")
                or (old_details.get(str(row["station_name"])) or {}).get(
                    "remark", ""
                ),
                "source": "trackside_plan",
            }
            for row in rows
            if str(row.get("station_name") or "").strip()
        }

    def get_active_trackside_pvid_plan(self) -> dict[str, object]:
        mode = TRACKSIDE_AP_PLAN_MODE
        station_rows = self.list_trackside_ap_plan(mode)
        station_vlans: dict[str, set[int]] = {}
        station_vlans_by_id: dict[str, set[int]] = {}
        station_totals: dict[str, int] = {}
        all_vlans: set[int] = set()
        for row in station_rows:
            station = str(row.get("station_name") or "").strip()
            station_id = str(row.get("station_id") or "").strip()
            raw_vlan = (
                row.get("management_vlan")
                if row.get("management_vlan") not in (None, "")
                else row.get("ap_management_vlans")
            )
            vlans = parse_vlan_set(raw_vlan)
            if not station or not vlans:
                continue
            station_vlans[station] = vlans
            if station_id:
                station_vlans_by_id[station_id] = vlans
            all_vlans.update(vlans)
            station_totals[station] = int(row.get("ap_count") or 0)
        return {
            "mode": mode,
            "planning_mode": "station_rows",
            "station_vlans": station_vlans,
            "station_vlans_by_id": station_vlans_by_id,
            "all_vlans": all_vlans,
            "station_totals": station_totals,
            "group_networks": {},
            "ap_networks_by_mac": {},
            "ap_networks_by_name": {},
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

    def list_station_online_summary_history(self, site_name: str | None = None, limit: int = 500, offset: int = 0) -> list[dict[str, object | None]]:
        clauses: list[str] = []
        params: list[object] = []
        if site_name:
            clauses.append("site_name = ?")
            params.append(site_name)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend((max(int(limit), 1), max(int(offset), 0)))
        with self.database.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM ac_station_online_summary_history
                {where}
                ORDER BY collected_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def count_station_online_summary_history(self, site_name: str | None = None) -> int:
        clauses: list[str] = []
        params: list[object] = []
        if site_name:
            clauses.append("site_name = ?")
            params.append(site_name)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.database.connect() as conn:
            row = conn.execute(f"SELECT COUNT(*) AS total FROM ac_station_online_summary_history {where}", params).fetchone()
        return int(row["total"] if row is not None else 0)

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
                    mac = self._mac_from_text(row.get("ap_mac"))
                    resources = []
                    if mac:
                        resources = [
                            candidate
                            for candidate in conn.execute(
                                "SELECT ap_uuid, ap_mac FROM ac_fit_ap_resources WHERE ac_device_uuid = ?",
                                (ac_device_uuid,),
                            ).fetchall()
                            if self._mac_from_text(candidate["ap_mac"]) == mac
                        ]
                    payload["ap_uuid"] = resources[0]["ap_uuid"] if len(resources) == 1 else str(uuid4())
                payload["collected_at"] = payload.get("collected_at") or now
                payload["updated_at"] = payload.get("updated_at") or now
                columns = ", ".join(fields)
                placeholders = ", ".join("?" for _ in fields)
                conn.execute(
                    f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
                    [payload[field] for field in fields],
                )
            conn.commit()

    def _update_fit_ap_resource_link_info(self, conn, ac_device_uuid: str, payload: dict[str, object | None]) -> None:
        ap_uuid = payload.get("ap_uuid")
        if not ap_uuid:
            return
        existing = conn.execute(
            "SELECT * FROM ac_fit_ap_resources WHERE ac_device_uuid = ? AND ap_uuid = ? ORDER BY id DESC LIMIT 1",
            (ac_device_uuid, ap_uuid),
        ).fetchone()
        if existing is None:
            return
        existing_data = dict(existing)
        lldp_payload = merge_lldp_payload(existing_data, payload) if _has_lldp_payload(payload) else {
            field: existing_data.get(field)
            for field in (
                "lldp_source",
                "lldp_confidence",
                "lldp_collected_at",
                "lldp_local_interface",
                "lldp_local_interface_normalized",
                "lldp_neighbor_name",
                "lldp_neighbor_mac",
                "lldp_neighbor_mac_normalized",
                "lldp_neighbor_interface",
                "lldp_match_status",
            )
        }
        resolved_payload = resolve_fit_ap_link_info({**existing_data, **payload})
        optical_payload = optical_payload_from_row(resolved_payload)
        optical_payload["optical_match_status"] = payload.get("link_match_status") or payload.get("optical_match_status") or resolve_optical_match_status(lldp_payload, payload)
        updates = {
            **lldp_payload,
            **{
                field: resolved_payload.get(field)
                for field in (
                    "lldp_source",
                    "lldp_confidence",
                    "lldp_collected_at",
                    "lldp_local_interface",
                    "lldp_local_interface_normalized",
                    "lldp_neighbor_name",
                    "lldp_neighbor_mac",
                    "lldp_neighbor_mac_normalized",
                    "lldp_neighbor_interface",
                    "lldp_match_status",
                )
            },
            **optical_payload,
            "lldp_neighbor": resolved_payload.get("lldp_neighbor_name"),
            "ap_optical_power": optical_payload.get("optical_rx_power"),
            "updated_at": payload.get("updated_at") or self._now(),
        }
        fields = tuple(field for field, value in updates.items() if value not in (None, ""))
        if not fields:
            return
        assignments = ", ".join(f"{field} = ?" for field in fields)
        conn.execute(
            f"UPDATE ac_fit_ap_resources SET {assignments} WHERE ac_device_uuid = ? AND ap_uuid = ?",
            [updates[field] for field in fields] + [ac_device_uuid, ap_uuid],
        )

    def _lldp_history_changed(self, conn, ap_uuid: object, payload: dict[str, object | None]) -> int:
        if not ap_uuid:
            return 1
        previous = conn.execute(
            """
            SELECT * FROM ac_fit_ap_lldp_history
            WHERE ap_uuid = ?
            ORDER BY collected_at DESC, id DESC
            LIMIT 1
            """,
            (ap_uuid,),
        ).fetchone()
        if previous is None:
            return 1
        prev = dict(previous)
        current = normalize_lldp_payload(payload, str(payload.get("lldp_source") or payload.get("source") or "unknown"))
        previous_neighbor_name = str(prev.get("neighbor_name") or prev.get("neighbor_device_name") or prev.get("lldp_neighbor") or "")
        current_neighbor_name = str(current.get("lldp_neighbor_name") or "")
        return 0 if (
            str(prev.get("local_interface_normalized") or "") == str(current.get("lldp_local_interface_normalized") or "")
            and str(prev.get("neighbor_mac_normalized") or "") == str(current.get("lldp_neighbor_mac_normalized") or "")
            and normalize_interface_key(prev.get("neighbor_interface")) == normalize_interface_key(current.get("lldp_neighbor_interface"))
            and previous_neighbor_name == current_neighbor_name
        ) else 1

    def _append_radio_history(self, conn, payload: dict[str, object | None]) -> None:
        now = self._now()
        for rid in (1, 2, 3):
            status = payload.get(f"rid{rid}_status")
            mode = payload.get(f"rid{rid}_mode")
            band = payload.get(f"rid{rid}_band")
            channel = payload.get(f"rid{rid}_channel")
            bandwidth = payload.get(f"rid{rid}_bandwidth")
            usage = payload.get(f"rid{rid}_usage")
            tx_power = payload.get(f"rid{rid}_tx_power")
            clients = payload.get(f"rid{rid}_clients")
            bbssid = payload.get(f"rid{rid}_bbssid")
            if not any(value not in (None, "") for value in (status, mode, band, channel, bandwidth, usage, tx_power, clients, bbssid)):
                continue
            row = {
                "ac_device_uuid": payload.get("ac_device_uuid"),
                "ap_uuid": payload.get("ap_uuid"),
                "ap_name": payload.get("ap_name"),
                "rid": rid,
                "status": status,
                "mode": mode,
                "band": band,
                "channel": channel,
                "bandwidth": bandwidth,
                "usage": usage,
                "tx_power": tx_power,
                "clients": clients,
                "bbssid": bbssid,
                "collected_at": payload.get("collected_at"),
                "collect_run_uuid": payload.get("collect_run_uuid"),
                "raw_log_path": payload.get("raw_log_path"),
                "created_at": now,
            }
            columns = ", ".join(FIT_AP_RADIO_HISTORY_FIELDS)
            placeholders = ", ".join("?" for _ in FIT_AP_RADIO_HISTORY_FIELDS)
            conn.execute(f"INSERT INTO ac_fit_ap_radio_history ({columns}) VALUES ({placeholders})", [row[field] for field in FIT_AP_RADIO_HISTORY_FIELDS])

    def _append_resource_lldp_history(self, conn, payload: dict[str, object | None]) -> None:
        if not any(
            payload.get(field) not in (None, "")
            for field in (
                "lldp_local_interface",
                "lldp_neighbor_name",
                "lldp_neighbor_mac",
                "lldp_neighbor_interface",
            )
        ):
            return
        now = self._now()
        row = self._payload(
            FIT_AP_LLDP_HISTORY_FIELDS,
            {
                "ac_device_uuid": payload.get("ac_device_uuid"),
                "ap_uuid": payload.get("ap_uuid"),
                "ap_name": payload.get("ap_name"),
                "ap_mac": payload.get("ap_mac"),
                "source": payload.get("lldp_source") or "ac_bulk_lldp",
                "local_interface": payload.get("lldp_local_interface"),
                "local_interface_normalized": payload.get("lldp_local_interface_normalized"),
                "lldp_neighbor": payload.get("lldp_neighbor_name"),
                "neighbor_name": payload.get("lldp_neighbor_name"),
                "neighbor_interface": payload.get("lldp_neighbor_interface"),
                "neighbor_mac": payload.get("lldp_neighbor_mac"),
                "neighbor_mac_normalized": payload.get("lldp_neighbor_mac_normalized"),
                "neighbor_device_name": payload.get("lldp_neighbor_name"),
                "session_id": payload.get("collect_run_uuid"),
                "is_changed": self._lldp_history_changed(conn, payload.get("ap_uuid"), payload),
                "conflict_flag": 1 if str(payload.get("lldp_match_status") or "") == "conflict" else 0,
                "collected_at": payload.get("collected_at"),
                "collect_run_uuid": payload.get("collect_run_uuid"),
                "raw_log_path": payload.get("raw_log_path"),
                "created_at": now,
            },
        )
        columns = ", ".join(FIT_AP_LLDP_HISTORY_FIELDS)
        placeholders = ", ".join("?" for _ in FIT_AP_LLDP_HISTORY_FIELDS)
        conn.execute(f"INSERT INTO ac_fit_ap_lldp_history ({columns}) VALUES ({placeholders})", [row[field] for field in FIT_AP_LLDP_HISTORY_FIELDS])

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

    def _resolve_fit_ap_entity_uuid(self, conn, ac_device_uuid: str, row: dict[str, object | None]) -> str:
        site_id = str(row.get("site_id") or "demo")
        requested_uuid = str(row.get("ap_uuid") or "").strip()
        if requested_uuid:
            found = conn.execute("SELECT ap_uuid FROM ap_entities WHERE ap_uuid = ?", (requested_uuid,)).fetchone()
            if found and found["ap_uuid"]:
                return str(found["ap_uuid"])

        serial_number = self._clean_identity_value(row.get("serial_number"))
        if serial_number:
            matches = conn.execute(
                "SELECT ap_uuid FROM ap_entities WHERE site_id = ? AND serial_number = ? ORDER BY id DESC",
                (site_id, serial_number),
            ).fetchall()
            if len(matches) == 1 and matches[0]["ap_uuid"]:
                return str(matches[0]["ap_uuid"])
            if len(matches) > 1:
                app_logger.log_warning(
                    "FIT_AP_ENTITY_SERIAL_AMBIGUOUS",
                    f"ac_device_uuid={ac_device_uuid}, site_id={site_id}, serial_number={serial_number}, count={len(matches)}",
                )

        normalized_mac = self._normalized_explicit_ap_mac(row)
        if normalized_mac:
            matches = conn.execute(
                "SELECT ap_uuid FROM ap_entities WHERE site_id = ? AND ap_mac = ? ORDER BY id DESC",
                (site_id, normalized_mac),
            ).fetchall()
            if len(matches) == 1 and matches[0]["ap_uuid"]:
                return str(matches[0]["ap_uuid"])
            if len(matches) > 1:
                app_logger.log_warning(
                    "FIT_AP_ENTITY_MAC_AMBIGUOUS",
                    f"ac_device_uuid={ac_device_uuid}, site_id={site_id}, ap_mac={normalized_mac}, count={len(matches)}",
                )

        if requested_uuid:
            return requested_uuid
        return str(uuid4())

    def _upsert_ap_entity(self, conn, payload: dict[str, object | None]) -> None:
        now = self._now()
        ap_uuid = str(payload.get("ap_uuid") or uuid4())
        existing = conn.execute("SELECT * FROM ap_entities WHERE ap_uuid = ?", (ap_uuid,)).fetchone()
        existing_data = dict(existing) if existing is not None else {}
        state_display = payload.get("state_display") or self._state_display(payload.get("state") or payload.get("state_raw"))
        is_offline = 1 if self._is_ap_offline(payload.get("state") or payload.get("state_raw") or state_display) else 0
        row = self._payload(
            AP_ENTITY_FIELDS,
            {
                **existing_data,
                "ap_uuid": ap_uuid,
                "site_id": existing_data.get("site_id") or payload.get("site_id") or "demo",
                "ac_device_uuid": payload.get("ac_device_uuid") or existing_data.get("ac_device_uuid"),
                "ap_name": self._non_empty(payload.get("ap_name"), existing_data.get("ap_name")),
                "ap_mac": self._non_empty(self._normalized_ap_mac(payload), existing_data.get("ap_mac")),
                "ap_id": self._non_empty(payload.get("apid") or payload.get("ap_id"), existing_data.get("ap_id")),
                "ap_ip": self._non_empty(payload.get("ap_ip"), existing_data.get("ap_ip")),
                "serial_number": self._non_empty(payload.get("serial_number"), existing_data.get("serial_number")),
                "model": self._non_empty(payload.get("model"), existing_data.get("model")),
                "group_name": self._non_empty(payload.get("group_name"), existing_data.get("group_name")),
                "mode": self._non_empty(payload.get("mode"), existing_data.get("mode")),
                "state": payload.get("state") or existing_data.get("state"),
                "state_raw": payload.get("state_raw") or payload.get("state") or existing_data.get("state_raw"),
                "state_display": state_display or existing_data.get("state_display"),
                "station": self._non_empty(existing_data.get("station"), normalize_station_value(payload)),
                "milestone": self._non_empty(existing_data.get("milestone"), payload.get("mileage")),
                "direction": self._non_empty(existing_data.get("direction"), payload.get("direction")),
                "location_note": self._non_empty(existing_data.get("location_note"), payload.get("location_note")),
                "first_seen_at": existing_data.get("first_seen_at") or payload.get("collected_at") or now,
                "last_seen_at": payload.get("collected_at") or now,
                "last_online_at": (payload.get("collected_at") or now) if not is_offline else existing_data.get("last_online_at"),
                "last_resource_update_at": payload.get("collected_at") or now,
                "is_offline": is_offline,
                "source": "fit_ap_resource",
                "created_at": existing_data.get("created_at") or now,
                "updated_at": now,
            },
        )
        columns = ", ".join(AP_ENTITY_FIELDS)
        placeholders = ", ".join("?" for _ in AP_ENTITY_FIELDS)
        updates = ", ".join(f"{field} = excluded.{field}" for field in AP_ENTITY_FIELDS if field not in {"ap_uuid", "created_at"})
        conn.execute(
            f"""
            INSERT INTO ap_entities ({columns})
            VALUES ({placeholders})
            ON CONFLICT(ap_uuid) DO UPDATE SET {updates}
            """,
            [row[field] for field in AP_ENTITY_FIELDS],
        )

    def _append_ap_resource_snapshot(self, conn, payload: dict[str, object | None]) -> None:
        now = self._now()
        row = self._payload(
            AP_RESOURCE_SNAPSHOT_FIELDS,
            {
                **payload,
                "snapshot_uuid": str(uuid4()),
                "ap_id": payload.get("apid") or payload.get("ap_id"),
                "ap_mac": self._normalized_ap_mac(payload),
                "station": normalize_station_value(payload),
                "raw_source_type": "fit_ap_resource",
                "created_at": now,
            },
        )
        row["collected_at"] = row.get("collected_at") or now
        columns = ", ".join(AP_RESOURCE_SNAPSHOT_FIELDS)
        placeholders = ", ".join("?" for _ in AP_RESOURCE_SNAPSHOT_FIELDS)
        conn.execute(f"INSERT INTO ap_resource_snapshots ({columns}) VALUES ({placeholders})", [row[field] for field in AP_RESOURCE_SNAPSHOT_FIELDS])

    def _dedupe_fit_ap_resource_rows(self, rows: list[dict[str, object | None]]) -> list[dict[str, object | None]]:
        keyed: dict[tuple[str, str], dict[str, object | None]] = {}
        passthrough: list[dict[str, object | None]] = []
        for row in rows:
            normalized_mac = self._normalized_explicit_ap_mac(row)
            serial_number = self._clean_identity_value(row.get("serial_number"))
            key: tuple[str, str] | None = None
            if normalized_mac:
                key = ("mac", normalized_mac)
            elif serial_number:
                key = ("serial", serial_number)
            if key is None:
                passthrough.append(dict(row))
            else:
                keyed[key] = dict(row)
        return [*keyed.values(), *passthrough]

    def _warn_duplicate_apid_identities(self, ac_device_uuid: str, rows: list[dict[str, object | None]]) -> None:
        identities_by_apid: dict[str, set[tuple[str, str]]] = {}
        for row in rows:
            apid = str(row.get("apid") or row.get("ap_id") or "").strip()
            if not apid:
                continue
            identity = (self._normalized_explicit_ap_mac(row), self._clean_identity_value(row.get("serial_number")))
            if not any(identity):
                continue
            identities_by_apid.setdefault(apid, set()).add(identity)
        for apid, identities in identities_by_apid.items():
            if len(identities) > 1:
                app_logger.log_warning(
                    "FIT_AP_DUPLICATE_APID_IDENTITY",
                    f"ac_device_uuid={ac_device_uuid}, apid={apid}, identity_count={len(identities)}",
                )

    def _append_ap_lldp_history(self, conn, payload: dict[str, object | None]) -> None:
        ap_uuid = str(payload.get("ap_uuid") or "")
        neighbor_name = payload.get("neighbor_device_name") or payload.get("lldp_neighbor")
        neighbor_interface = payload.get("neighbor_interface")
        if not ap_uuid or not (neighbor_name or neighbor_interface):
            return
        now = self._now()
        conn.execute("UPDATE ap_lldp_history SET is_latest = 0 WHERE ap_uuid = ?", (ap_uuid,))
        row = self._payload(
            AP_LLDP_ENTITY_HISTORY_FIELDS,
            {
                "history_uuid": str(uuid4()),
                "ap_uuid": ap_uuid,
                "ap_mac": self._normalized_ap_mac(payload),
                "ap_name": payload.get("ap_name"),
                "serial_number": payload.get("serial_number"),
                "neighbor_switch_name": neighbor_name,
                "neighbor_switch_sysname": payload.get("lldp_neighbor"),
                "neighbor_interface": neighbor_interface,
                "collected_at": payload.get("collected_at") or now,
                "source_device_uuid": payload.get("ac_device_uuid"),
                "is_latest": 1,
                "created_at": now,
            },
        )
        columns = ", ".join(AP_LLDP_ENTITY_HISTORY_FIELDS)
        placeholders = ", ".join("?" for _ in AP_LLDP_ENTITY_HISTORY_FIELDS)
        conn.execute(f"INSERT INTO ap_lldp_history ({columns}) VALUES ({placeholders})", [row[field] for field in AP_LLDP_ENTITY_HISTORY_FIELDS])

    def _append_ap_optical_history(self, conn, payload: dict[str, object | None]) -> None:
        ap_uuid = str(payload.get("ap_uuid") or "")
        if not ap_uuid or not any(payload.get(field) for field in ("rx_power", "tx_power", "optical_alarm_status")):
            return
        now = self._now()
        conn.execute("UPDATE ap_optical_history SET is_latest = 0 WHERE ap_uuid = ? AND side = 'ap'", (ap_uuid,))
        row = self._payload(
            AP_OPTICAL_ENTITY_HISTORY_FIELDS,
            {
                "history_uuid": str(uuid4()),
                "ap_uuid": ap_uuid,
                "side": "ap",
                "device_uuid": payload.get("ac_device_uuid"),
                "interface_name": payload.get("interface_name"),
                "rx_power": payload.get("rx_power"),
                "tx_power": payload.get("tx_power"),
                "alarm_status": payload.get("optical_alarm_status") or payload.get("status"),
                "collected_at": payload.get("collected_at") or now,
                "data_source": payload.get("data_source") or "fit_ap_optical",
                "is_latest": 1,
                "created_at": now,
            },
        )
        columns = ", ".join(AP_OPTICAL_ENTITY_HISTORY_FIELDS)
        placeholders = ", ".join("?" for _ in AP_OPTICAL_ENTITY_HISTORY_FIELDS)
        conn.execute(f"INSERT INTO ap_optical_history ({columns}) VALUES ({placeholders})", [row[field] for field in AP_OPTICAL_ENTITY_HISTORY_FIELDS])

    def _resource_for_payload(self, conn, ac_device_uuid: str, row: dict[str, object | None]) -> dict[str, object | None]:
        if row.get("ap_uuid"):
            found = conn.execute(
                "SELECT r.*, m.site_name FROM ac_fit_ap_resources r LEFT JOIN ac_fit_ap_metadata m ON m.ap_uuid = r.ap_uuid WHERE r.ac_device_uuid = ? AND r.ap_uuid = ? ORDER BY r.id DESC LIMIT 1",
                (ac_device_uuid, row.get("ap_uuid")),
            ).fetchone()
            if found:
                return dict(found)
        mac = self._mac_from_text(row.get("ap_mac"))
        if mac:
            matches = [
                dict(candidate)
                for candidate in conn.execute(
                    "SELECT r.*, m.site_name FROM ac_fit_ap_resources r LEFT JOIN ac_fit_ap_metadata m ON m.ap_uuid = r.ap_uuid WHERE r.ac_device_uuid = ?",
                    (ac_device_uuid,),
                ).fetchall()
                if self._mac_from_text(candidate["ap_mac"]) == mac
            ]
            if len(matches) == 1:
                return matches[0]
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
                       m_uuid.site_name AS site_name,
                       m_uuid.station_id AS metadata_station_id,
                       m_uuid.station_override_enabled AS metadata_station_override_enabled,
                       m_uuid.station_override_source AS metadata_station_override_source,
                       m_uuid.belong_type AS metadata_belong_type,
                       m_uuid.belong_section AS metadata_belong_section,
                       m_uuid.section_start_station AS metadata_section_start_station,
                       m_uuid.section_end_station AS metadata_section_end_station,
                       m_uuid.yard_name AS metadata_yard_name,
                       m_uuid.area_name AS metadata_area_name,
                       m_uuid.mileage AS metadata_mileage,
                       m_uuid.location_note AS metadata_location_note,
                       m_uuid.direction AS metadata_direction
                FROM ac_fit_ap_resources r
                LEFT JOIN ac_fit_ap_metadata m_uuid ON m_uuid.ap_uuid = r.ap_uuid
                WHERE r.ac_device_uuid = ?
                ORDER BY r.ap_name, r.id
                """,
                (ac_device_uuid,),
            ).fetchall()
        result = []
        for row in rows:
            result.append(self._resource_with_metadata(dict(row)))
        return result

    def _enrich_resources_with_extensions(self, rows: list[dict[str, object | None]]) -> list[dict[str, object | None]]:
        if not rows:
            return rows
        extensions = self.list_ap_extension_points()
        by_mac: dict[str, list[dict[str, object | None]]] = {}
        for extension in extensions:
            key = str(extension.get("ap_mac_norm") or "").strip().casefold()
            if key:
                by_mac.setdefault(key, []).append(extension)
        enriched: list[dict[str, object | None]] = []
        for row in rows:
            item = dict(row)
            mac = self._extension_mac_norm(item.get("ap_mac"))
            candidates = by_mac.get(mac, [])
            extension = candidates[0] if len(candidates) == 1 else None
            match_status = "matched_by_mac" if extension else "ambiguous_mac" if len(candidates) > 1 else ""
            if extension:
                for field in (
                    "ap_name",
                    "station_id",
                    "section_id",
                    "belong_type",
                    "station_name",
                    "section_name",
                    "section_start_station",
                    "section_end_station",
                    "yard_name",
                    "area_name",
                    "network_domain",
                    "line_side",
                    "direction",
                    "mileage_text",
                    "mileage_m",
                    "distance_to_prev_m",
                    "ap_point_code",
                    "power_station",
                    "power_distribution",
                    "fiber_access_station",
                    "fiber_distribution",
                    "uplink_switch",
                    "uplink_port",
                    "optical_port",
                    "location_desc",
                    "remark",
                ):
                    item[f"extension_{field}"] = extension.get(field)
                item["belong_type"] = item.get("belong_type") or extension.get("belong_type")
                item["station_id"] = item.get("station_id") or extension.get("station_id")
                item["section_id"] = item.get("section_id") or extension.get("section_id")
                item["section_name"] = item.get("section_name") or extension.get("section_name")
                item["section_start_station"] = item.get("section_start_station") or extension.get("section_start_station")
                item["section_end_station"] = item.get("section_end_station") or extension.get("section_end_station")
                item["yard_name"] = item.get("yard_name") or extension.get("yard_name")
                item["area_name"] = item.get("area_name") or extension.get("area_name")
                item["extension_id"] = extension.get("id")
                item["extension_match_status"] = match_status
            else:
                item["extension_match_status"] = "no_extension"
            enriched.append(item)
        return enriched

    @staticmethod
    def _resource_with_metadata(item: dict[str, object | None]) -> dict[str, object | None]:
        item["resource_station_text"] = item.get("site")
        item["manual_station_id"] = item.get("metadata_station_id") or ""
        item["manual_station_name"] = item.get("site_name") or ""
        item["manual_override_enabled"] = bool(item.get("metadata_station_override_enabled")) or bool(
            item.get("site_name") and not item.get("metadata_station_override_source")
        )
        item["manual_override_source"] = item.get("metadata_station_override_source") or ""
        item["site"] = item.get("site_name") or item.get("site")
        item["belong_type"] = item.get("metadata_belong_type") or item.get("belong_type")
        item["section_name"] = item.get("metadata_belong_section") or item.get("section_name")
        item["section_start_station"] = item.get("metadata_section_start_station") or item.get("section_start_station")
        item["section_end_station"] = item.get("metadata_section_end_station") or item.get("section_end_station")
        item["yard_name"] = item.get("metadata_yard_name") or item.get("yard_name")
        item["area_name"] = item.get("metadata_area_name") or item.get("area_name")
        item["mileage"] = item.get("metadata_mileage") or item.get("mileage")
        item["location_note"] = item.get("metadata_location_note") or item.get("location_note")
        item["direction"] = item.get("metadata_direction") or item.get("direction")
        return item

    def _find_ap_extension_existing_id(self, conn, row: dict[str, object | None]) -> int | None:
        extension_id = row.get("id")
        if extension_id:
            found = conn.execute("SELECT id FROM ap_extension_points WHERE id = ?", (extension_id,)).fetchone()
            if found:
                return int(found["id"])
        mac = self._extension_mac_norm(row.get("ap_mac_norm") or row.get("ap_mac_display"))
        if mac:
            found = conn.execute("SELECT id FROM ap_extension_points WHERE ap_mac_norm = ? ORDER BY id LIMIT 1", (mac,)).fetchone()
            if found:
                return int(found["id"])
        ap_point_code = str(row.get("ap_point_code") or "").strip()
        station_name = str(row.get("station_name") or "").strip()
        line_side = str(row.get("line_side") or "").strip()
        mileage_m = row.get("mileage_m")
        if ap_point_code and station_name and line_side and mileage_m is not None:
            found = conn.execute(
                """
                SELECT id FROM ap_extension_points
                WHERE ap_point_code = ? AND station_name = ? AND line_side = ? AND mileage_m = ?
                ORDER BY id LIMIT 1
                """,
                (ap_point_code, station_name, line_side, mileage_m),
            ).fetchone()
            if found:
                return int(found["id"])
        return None

    @staticmethod
    def _extension_mac_norm(value: object) -> str:
        return normalize_ap_mac(value).normalized

    @staticmethod
    def _extension_with_match_status(
        row: dict[str, object | None],
        matched_macs: set[str],
    ) -> dict[str, object | None]:
        mac = str(row.get("ap_mac_norm") or "").strip()
        if mac and mac in matched_macs:
            row["match_status"] = "matched_by_mac"
        elif mac:
            row["match_status"] = "extension_not_online"
        else:
            row["match_status"] = "unbound_no_mac"
        return row

    def _enrich_resources_with_unauthenticated_status(
        self,
        resources: list[dict[str, object | None]],
        ac_device_uuid: str | None = None,
    ) -> list[dict[str, object | None]]:
        if not resources:
            return resources
        current_rows = self.list_fit_ap_unauthenticated(ac_device_uuid) if ac_device_uuid else self.list_all_fit_ap_unauthenticated()
        history_rows = self.list_fit_ap_unauthenticated_history(ac_device_uuid)
        current_index = _unauthenticated_identity_index(current_rows)
        history_index = _unauthenticated_identity_index(history_rows)
        enriched: list[dict[str, object | None]] = []
        for resource in resources:
            item = dict(resource)
            current = _find_unauthenticated_match(item, current_index)
            history = _find_unauthenticated_match(item, history_index)
            if current:
                item.update(
                    {
                        "is_new_online_ap": 1,
                        "new_online_source": "display wlan ap unauthenticated",
                        "new_online_status": "当前新上线Auto AP",
                        "register_status": "未固化",
                        "unauthenticated_state": "pending_confirm",
                        "unauthenticated_collected_at": current.get("collected_at"),
                        "last_unauthenticated_at": current.get("collected_at"),
                    }
                )
            elif history:
                item.update(
                    {
                        "is_new_online_ap": 0,
                        "new_online_source": "",
                        "new_online_status": "历史新上线",
                        "register_status": "已固化/已确认",
                        "unauthenticated_state": "confirmed_manual",
                        "unauthenticated_collected_at": None,
                        "last_unauthenticated_at": history.get("collected_at"),
                    }
                )
            else:
                item.update(
                    {
                        "is_new_online_ap": 0,
                        "new_online_source": "",
                        "new_online_status": "-",
                        "register_status": "已手动固化或普通AP",
                        "unauthenticated_state": "",
                        "unauthenticated_collected_at": None,
                        "last_unauthenticated_at": None,
                    }
                )
            enriched.append(item)
        return enriched

    @classmethod
    def _payload(cls, fields: tuple[str, ...], data: dict[str, object | None]) -> dict[str, object | None]:
        return {field: data.get(field) for field in fields}

    @staticmethod
    def _insert(conn, table: str, fields: tuple[str, ...], payload: dict[str, object | None]) -> None:
        columns = ", ".join(fields)
        placeholders = ", ".join("?" for _ in fields)
        conn.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", [payload[field] for field in fields])

    @staticmethod
    def _ap_identity_clauses(identity: dict[str, str], allowed: tuple[str, ...]) -> tuple[list[str], list[object]]:
        clauses: list[str] = []
        params: list[object] = []
        for field in ("ap_uuid", "serial_number", "ap_mac", "ap_name"):
            if field not in allowed:
                continue
            value = str(identity.get(field) or "").strip()
            if not value or value in {"-", "N/A", "n/a"}:
                continue
            clauses.append(f"lower(trim({field})) = lower(trim(?))")
            params.append(value)
        return clauses, params

    @classmethod
    def _normalized_ap_mac(cls, data: dict[str, object | None]) -> str:
        for field in ("ap_mac", "mac"):
            mac = cls._mac_from_text(data.get(field))
            if mac:
                return mac
        return ""

    @classmethod
    def _normalized_explicit_ap_mac(cls, data: dict[str, object | None]) -> str:
        for field in ("ap_mac", "mac"):
            mac = cls._mac_from_text(data.get(field))
            if mac:
                return mac
        return ""

    @staticmethod
    def _mac_from_text(value: object) -> str:
        hex_text = re.sub(r"[^0-9a-fA-F]", "", str(value or ""))
        if len(hex_text) != 12:
            return ""
        hex_text = hex_text.casefold()
        return f"{hex_text[0:4]}-{hex_text[4:8]}-{hex_text[8:12]}"

    @staticmethod
    def _non_empty(primary: object, fallback: object = None) -> object:
        text = str(primary or "").strip()
        if text and text not in {"-", "N/A", "n/a"}:
            return primary
        return fallback

    @staticmethod
    def _clean_identity_value(value: object) -> str:
        text = str(value or "").strip()
        if text and text not in {"-", "N/A", "n/a"}:
            return text
        return ""

    @staticmethod
    def _state_display(value: object) -> str:
        token = str(value or "").split("=", 1)[0].strip().upper()
        if token in {"I", "IDLE"}:
            return "Idle"
        if token in {"R", "RUN"}:
            return "Online"
        if token == "J":
            return "Join"
        if token == "JA":
            return "JoinAck"
        if token == "IL":
            return "ImageLoad"
        return str(value or "")

    @staticmethod
    def _is_ap_offline(value: object) -> bool:
        token = str(value or "").split("=", 1)[0].strip().upper()
        return token in {"I", "IDLE"}

    @staticmethod
    def _normalize_trackside_plan_mode(mode: str) -> str:
        if mode not in TRACKSIDE_PLAN_MODES:
            raise ValueError(f"Unsupported trackside AP plan mode: {mode}")
        return mode

    @classmethod
    def _trackside_plan_payload(cls, mode: str, row: dict[str, object | None], sort_order: int, now: str) -> dict[str, object | None]:
        station_name = str(row.get("station_name") or "").strip()
        if not station_name:
            raise ValueError("station_name is required")
        payload = cls._payload(TRACKSIDE_PLAN_FIELDS, row)
        payload["mode"] = mode
        payload["station_id"] = str(row.get("station_id") or "").strip()
        payload["sequence_no"] = int(
            row.get("sequence_no")
            if row.get("sequence_no") not in (None, "")
            else int(row.get("sort_order") or sort_order) + 1
        )
        payload["station_name"] = station_name
        payload["ap_count"] = max(int(row.get("ap_count") or 0), 0)
        payload["mask_length"] = row.get("mask_length")
        payload["subnet_mask"] = str(
            row.get("subnet_mask")
            if row.get("subnet_mask") not in (None, "")
            else row.get("mask_length")
            if row.get("mask_length") is not None
            else ""
        ).strip()
        payload["sort_order"] = payload["sequence_no"] - 1
        raw_vlan = (
            row.get("management_vlan")
            if row.get("management_vlan") not in (None, "")
            else row.get("ap_management_vlans")
        )
        parsed_vlans = parse_vlan_set(raw_vlan)
        payload["management_vlan"] = (
            next(iter(parsed_vlans)) if len(parsed_vlans) == 1 else None
        )
        payload["ap_management_vlans"] = (
            str(payload["management_vlan"])
            if row.get("management_vlan") not in (None, "")
            else str(row.get("ap_management_vlans") or "").strip()
        )
        payload["remark"] = str(row.get("remark") or "").strip()
        payload["created_at"] = row.get("created_at") or now
        payload["updated_at"] = now
        return payload

    def _list_trackside_ap_plan_by_mode(self, mode: str) -> list[dict[str, object | None]]:
        mode = self._normalize_trackside_plan_mode(mode)
        with self.database.connect_readonly() as conn:
            rows = conn.execute(
                """
                SELECT * FROM ac_trackside_ap_plan
                WHERE mode = ?
                ORDER BY sort_order, station_name
                """,
                (mode,),
            ).fetchall()
        return [dict(row) for row in rows]

    @classmethod
    def _set_time_defaults(cls, payload: dict[str, object | None]) -> None:
        now = cls._now()
        payload["collected_at"] = payload.get("collected_at") or now
        payload["updated_at"] = payload.get("updated_at") or now

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")


def _latest_rows_by_ap_identity(rows: list[dict[str, object | None]]) -> list[dict[str, object | None]]:
    latest: dict[tuple[str, str], dict[str, object | None]] = {}
    passthrough: list[dict[str, object | None]] = []
    for row in rows:
        key = _ap_identity_key(row)
        if not key:
            passthrough.append(row)
            continue
        current = latest.get(key)
        if current is None or _latest_row_prefer_score(row) >= _latest_row_prefer_score(current):
            latest[key] = row
    return [*latest.values(), *passthrough]


def _unauthenticated_identity_index(rows: list[dict[str, object | None]]) -> dict[tuple[str, str], dict[str, object | None]]:
    index: dict[tuple[str, str], dict[str, object | None]] = {}
    for row in rows or []:
        for key in _unauthenticated_identity_keys(row):
            current = index.get(key)
            if current is None or _latest_row_score(row) >= _latest_row_score(current):
                index[key] = row
    return index


def _find_unauthenticated_match(
    resource: dict[str, object | None],
    index: dict[tuple[str, str], dict[str, object | None]],
) -> dict[str, object | None]:
    for key in _unauthenticated_identity_keys(resource):
        row = index.get(key)
        if row:
            return row
    return {}


def _unauthenticated_identity_keys(row: dict[str, object | None]) -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    serial = str(row.get("serial_number") or row.get("serial") or "").strip()
    if serial and serial not in {"-", "N/A", "n/a"}:
        keys.append(("serial", serial.casefold()))
    mac = AcRepository._mac_from_text(row.get("inferred_ap_mac") or row.get("ap_mac") or row.get("mac"))
    if mac:
        keys.append(("mac", mac.casefold()))
    ac_device_uuid = str(row.get("ac_device_uuid") or "").strip()
    apid = str(row.get("apid") or row.get("ap_id") or "").strip()
    if ac_device_uuid and apid:
        keys.append(("apid", f"{ac_device_uuid.casefold()}:{apid.casefold()}"))
    return keys


def _ap_identity_key(row: dict[str, object | None]) -> tuple[str, str] | None:
    for field in ("ap_uuid", "serial_number", "ap_mac"):
        value = str(row.get(field) or "").strip()
        if value and value not in {"-", "N/A", "n/a"}:
            return field, value.casefold()
    return None


def _fit_ap_optical_merge_key(row: dict[str, object | None]) -> tuple[str, str] | None:
    ac_uuid = str(row.get("ac_device_uuid") or "").strip()
    apid = str(row.get("apid") or row.get("ap_id") or "").strip()
    if ac_uuid and apid and apid not in {"-", "N/A", "n/a"}:
        return "apid", f"{ac_uuid.casefold()}:{apid.casefold()}"
    value = str(row.get("ap_uuid") or "").strip()
    if value and value not in {"-", "N/A", "n/a"}:
        return "ap_uuid", value.casefold()
    mac = AcRepository._mac_from_text(row.get("ap_mac"))
    if mac:
        return "ap_mac", mac.casefold()
    value = str(row.get("serial_number") or "").strip()
    if value and value not in {"-", "N/A", "n/a"}:
        return "serial_number", value.casefold()
    return None


def _merge_failed_fit_ap_optical_payload(
    old: dict[str, object | None],
    new: dict[str, object | None],
) -> dict[str, object | None]:
    merged = {**old, **new}
    for field in (
        "ap_mac",
        "ap_name",
        "neighbor_device_name",
        "neighbor_interface",
        "rx_power",
        "tx_power",
    ):
        if _is_empty_identity_value(new.get(field)) and not _is_empty_identity_value(old.get(field)):
            merged[field] = old.get(field)
    return merged


def _is_fit_ap_optical_success_payload(row: dict[str, object | None]) -> bool:
    status = str(row.get("status") or "").strip().casefold()
    if status == "success":
        return _has_fit_ap_optical_payload(row) or _has_fit_ap_lldp_payload(row)
    if status:
        return False
    return any(not _is_empty_identity_value(row.get(field)) for field in FIT_AP_OPTICAL_FIELDS if field not in {"ac_device_uuid", "ap_uuid", "collected_at", "updated_at"})


def _fit_ap_optical_prefer_score(row: dict[str, object | None]) -> tuple[int, str, str, int]:
    status = str(row.get("status") or "").strip().casefold()
    optical_status = str(row.get("optical_alarm_status") or row.get("raw_status") or "").strip().casefold()
    if status == "success" and not _is_empty_identity_value(row.get("rx_power")):
        base = 100
    elif status == "success" and _has_fit_ap_optical_payload(row):
        base = 90
    elif status == "success" and _has_fit_ap_lldp_payload(row):
        base = 80
    elif "no_light" in optical_status or "无光" in optical_status:
        base = 50
    elif status in {"failed", "timeout", "parse_failed", "unknown"}:
        base = 10
    else:
        base = 0
    return (base, str(row.get("collected_at") or ""), str(row.get("updated_at") or ""), _int_value(row.get("id")))


def _has_fit_ap_optical_payload(row: dict[str, object | None]) -> bool:
    return any(not _is_empty_identity_value(row.get(field)) for field in ("rx_power", "tx_power", "module_model", "module_serial_number", "module_vendor", "temperature", "voltage"))


def _has_fit_ap_lldp_payload(row: dict[str, object | None]) -> bool:
    return _has_lldp_payload(row)


def _has_lldp_payload(row: dict[str, object | None]) -> bool:
    return any(
        not _is_empty_identity_value(row.get(field))
        for field in (
            "neighbor_device_name",
            "neighbor_interface",
            "lldp_neighbor",
            "neighbor_mac",
            "lldp_local_interface",
            "lldp_neighbor_name",
            "lldp_neighbor_mac",
            "lldp_neighbor_interface",
        )
    )


_GENERIC_ASSOCIATION_VALUES = {"h3c", "comware", "switch", "ethernet switch", "unknown", "n/a", "na", "-"}
_INTERFACE_VALUE_RE = re.compile(
    r"(?i)^(?:ge|gigabitethernet|xge|xgigabitethernet|ten-gigabitethernet|"
    r"tengigabitethernet|sge|fortygigabitethernet|hundredgigabitethernet)\s*\d+(?:/\d+){1,3}$"
)


def _is_invalid_fit_ap_association_projection(row: dict[str, object | None]) -> bool:
    def text(field: str) -> str:
        return str(row.get(field) or "").strip()

    def is_generic(value: str) -> bool:
        return value.casefold() in _GENERIC_ASSOCIATION_VALUES

    def is_interface(value: str) -> bool:
        return bool(_INTERFACE_VALUE_RE.fullmatch(value))

    return any(
        (
            is_interface(text("neighbor_device_name")),
            is_interface(text("lldp_neighbor_name")),
            is_generic(text("neighbor_interface")),
            is_generic(text("lldp_neighbor_interface")),
        )
    )


def _is_empty_identity_value(value: object) -> bool:
    text = str(value or "").strip()
    return not text or text in {"-", "N/A", "n/a"}


def _latest_row_score(row: dict[str, object | None]) -> tuple[str, str, int]:
    return (
        str(row.get("collected_at") or ""),
        str(row.get("updated_at") or ""),
        _int_value(row.get("id")),
    )


def _latest_row_prefer_score(row: dict[str, object | None]) -> tuple[int, str, str, int]:
    if any(field in row for field in ("rx_power", "tx_power", "neighbor_device_name", "neighbor_interface", "optical_alarm_status")):
        return _fit_ap_optical_prefer_score(row)
    collected_at, updated_at, row_id = _latest_row_score(row)
    return (0, collected_at, updated_at, row_id)


def _int_value(value: object) -> int:
    try:
        return int(str(value or "0"))
    except ValueError:
        return 0


def _fit_ap_history_table(history_kind: str) -> str:
    tables = {
        "radio": "ac_fit_ap_radio_history",
        "lldp": "ac_fit_ap_lldp_history",
        "optical": "ac_fit_ap_optical_history",
    }
    try:
        return tables[str(history_kind or "").strip().casefold()]
    except KeyError as exc:
        raise ValueError(f"不支持的 FIT-AP 历史类型：{history_kind}") from exc
