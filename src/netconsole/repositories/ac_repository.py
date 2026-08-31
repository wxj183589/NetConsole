from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from netconsole.core import app_logger
from netconsole.core.database import Database
from netconsole.core.fit_ap_serial_identity import (
    clean_fit_ap_serial,
    fit_ap_serial_identity_key,
)
from netconsole.parsers.h3c.ac.state_mapper import classify_fit_ap_state
from netconsole.parsers.h3c.ac.wlan_ap_unauthenticated_parser import (
    WLAN_AP_UNAUTHENTICATED_SOURCE,
)
from netconsole.services.ap_extension_import import normalize_ap_mac
from netconsole.services.fit_ap_link_info import (
    merge_lldp_payload,
    normalize_interface_key,
    normalize_lldp_payload,
    optical_payload_from_row,
    resolve_fit_ap_link_info,
    resolve_optical_match_status,
)
from netconsole.services.current_history_retention import (
    count_station_online_summary_recent,
    list_fit_ap_resource_recent,
    list_fit_ap_unauthenticated_recent,
    list_station_online_summary_recent,
    record_fit_ap_resource_change,
    record_fit_ap_unauthenticated_change,
    unauthenticated_identity_key,
    upsert_station_online_summary,
)
from netconsole.services.radio_retention import (
    upsert_radio_current_and_history,
)
from netconsole.services.lldp_retention import (
    upsert_lldp_current_and_history,
)
from netconsole.services.optical_retention import (
    update_ap_optical_treatment,
    upsert_optical_current_and_history,
)
from netconsole.services.trackside_ap_business import parse_vlan_set
from netconsole.utils.mileage import parse_mileage_to_meters
from netconsole.utils.station_normalize import normalize_station_value

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
    "site_key",
    "connection_record_raw_time",
    "connection_record_resolved_time",
    "connection_record_collected_at",
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
    "ac_device_uuid",
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
    "ap_mac",
    "site_key",
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
    "snapshot_status",
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
    "site_key",
    "connection_record_raw_time",
    "connection_record_resolved_time",
    "connection_record_collected_at",
    *(f"rid{rid}_{field}" for rid in (1, 2, 3) for field in ("status", "mode", "band", "usage", "clients", "bbssid")),
)

FIT_AP_STABLE_IDENTITY_FIELDS = (
    "ap_name",
    "ap_mac",
    "serial_number",
    "model",
)

class FitApIdentityConflict(RuntimeError):
    """A FIT-AP row contains incompatible strong-identity evidence."""

    code = "IDENTITY_CONFLICT"

    def __init__(
        self,
        *,
        ac_device_uuid: str,
        serial_number: str,
        reason: str,
        canonical_uuid: str = "",
        incoming_uuid: str = "",
        canonical_mac: str = "",
        incoming_mac: str = "",
    ) -> None:
        self.ac_device_uuid = ac_device_uuid
        self.serial_number = serial_number
        self.reason = reason
        self.canonical_uuid = canonical_uuid
        self.incoming_uuid = incoming_uuid
        self.canonical_mac = canonical_mac
        self.incoming_mac = incoming_mac
        super().__init__(
            "IDENTITY_CONFLICT: "
            f"ac_device_uuid={ac_device_uuid}, serial_number={serial_number}, "
            f"reason={reason}, canonical_ap_uuid={canonical_uuid}, "
            f"incoming_ap_uuid={incoming_uuid}"
        )


@dataclass(frozen=True)
class FitApResourcePersistenceResult:
    batch_serial_duplicates: int = 0
    batch_serial_merged: int = 0
    serial_identity_conflicts: int = 0
    duplicate_ap_entity_created: int = 0

    def to_payload(self) -> dict[str, int]:
        return {
            "batch_serial_duplicates": self.batch_serial_duplicates,
            "batch_serial_merged": self.batch_serial_merged,
            "serial_identity_conflicts": self.serial_identity_conflicts,
            "duplicate_ap_entity_created": self.duplicate_ap_entity_created,
        }

AP_ENTITY_FIELDS = (
    "ap_uuid",
    "site_id",
    "site_key",
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
    "connection_state",
    "connection_record_raw_time",
    "connection_record_resolved_time",
    "connection_record_collected_at",
    "last_online_time",
    "offline_time",
    "last_state_change_at",
    "last_connection_record_seen_at",
    "connection_reonline_count",
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

    @property
    def site_id(self) -> str:
        return self.database.path.parent.parent.name or self.database.path.parent.name

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

    def replace_fit_ap_resources(
        self,
        ac_device_uuid: str,
        rows: list[dict[str, object | None]],
    ) -> FitApResourcePersistenceResult:
        now = self._now()
        rows, batch_metrics = self._prepare_fit_ap_resource_rows(rows)
        self._warn_duplicate_apid_identities(ac_device_uuid, rows)
        with self.database.connect() as conn:
            continuity_resources = [
                dict(item)
                for item in conn.execute(
                    "SELECT * FROM ac_fit_ap_resources WHERE ac_device_uuid = ? ORDER BY id DESC",
                    (ac_device_uuid,),
                ).fetchall()
            ]
            # ap_entities is a physical identity authority.  It is deliberately
            # not used as an AC ownership list; current resources provide the
            # only AC-scoped continuity candidates.
            continuity_entities: list[dict[str, object | None]] = []
            incoming_name_counts = Counter(
                name.casefold()
                for row in rows
                if (name := self._clean_identity_value(row.get("ap_name")))
            )
            identity_cache = self._build_fit_ap_identity_cache(conn)
            current_uuids: list[str] = []
            for row in rows:
                try:
                    payload = self._upsert_fit_ap_resource(
                        conn,
                        ac_device_uuid,
                        row,
                        now,
                        continuity_resources=continuity_resources,
                        continuity_entities=continuity_entities,
                        incoming_name_counts=incoming_name_counts,
                        identity_cache=identity_cache,
                    )
                except FitApIdentityConflict as exc:
                    batch_metrics["serial_identity_conflicts"] += 1
                    if exc.canonical_uuid:
                        current_uuids.append(exc.canonical_uuid)
                    continue
                current_uuids.append(str(payload["ap_uuid"]))
                self._register_fit_ap_identity_cache(identity_cache, payload)
                duplicate_count = int(row.get("_batch_serial_duplicate_count") or 0)
                if duplicate_count:
                    self._log_fit_ap_identity_event(
                        "SERIAL_IDENTITY_MERGED",
                        ac_device_uuid=ac_device_uuid,
                        canonical_uuid=str(payload["ap_uuid"]),
                        incoming_uuid=self._clean_identity_value(row.get("ap_uuid")),
                        serial_number=self._clean_identity_value(row.get("serial_number")),
                        incoming_mac=self._normalized_explicit_ap_mac(row),
                    )
            if batch_metrics["serial_identity_conflicts"]:
                # A partial snapshot with unresolved identity evidence must not
                # delete previously known APs that were not safely reconciled.
                pass
            elif current_uuids:
                placeholders = ", ".join("?" for _ in current_uuids)
                conn.execute(f"DELETE FROM ac_fit_ap_resources WHERE ac_device_uuid = ? AND ap_uuid NOT IN ({placeholders})", [ac_device_uuid, *current_uuids])
            else:
                conn.execute("DELETE FROM ac_fit_ap_resources WHERE ac_device_uuid = ?", (ac_device_uuid,))
            conn.commit()
        result = FitApResourcePersistenceResult(**batch_metrics)
        app_logger.log_info(
            "FIT_AP_BATCH_IDENTITY_RECONCILED",
            (
                f"ac_device_uuid={ac_device_uuid}, "
                f"BATCH_SERIAL_DUPLICATES={result.batch_serial_duplicates}, "
                f"BATCH_SERIAL_MERGED={result.batch_serial_merged}, "
                f"SERIAL_IDENTITY_CONFLICT={result.serial_identity_conflicts}, "
                f"DUPLICATE_AP_ENTITY_CREATED={result.duplicate_ap_entity_created}"
            ),
        )
        return result

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
        *,
        continuity_resources: list[dict[str, object | None]] | None = None,
        continuity_entities: list[dict[str, object | None]] | None = None,
        incoming_name_counts: Counter[str] | None = None,
        identity_cache: dict[str, dict[str, list[dict[str, object | None]]]] | None = None,
    ) -> dict[str, object | None]:
        ap_uuid = self._resolve_fit_ap_entity_uuid(
            conn,
            ac_device_uuid,
            row,
            continuity_resources=continuity_resources,
            continuity_entities=continuity_entities,
            incoming_name_counts=incoming_name_counts,
            identity_cache=identity_cache,
        )
        resource_data = {**row, "ac_device_uuid": ac_device_uuid, "ap_uuid": ap_uuid}
        resource_data, preserved_fields = self._merge_fit_ap_resource_identity(
            conn,
            resource_data,
            ap_uuid,
        )
        resource_data["site_key"] = resource_data.get("site_key") or self.site_id
        station = normalize_station_value(resource_data)
        if station and not str(resource_data.get("site") or "").strip():
            resource_data["site"] = station
        existing_resource = conn.execute(
            "SELECT * FROM ac_fit_ap_resources "
            "WHERE ac_device_uuid = ? AND ap_uuid = ? ORDER BY id DESC LIMIT 1",
            (ac_device_uuid, ap_uuid),
        ).fetchone()
        is_offline = self._is_ap_offline(
            resource_data.get("state")
            or resource_data.get("state_raw")
            or resource_data.get("state_display")
        )
        if existing_resource is not None and not is_offline:
            existing_data = dict(existing_resource)
            for field in FIT_AP_OPTIONAL_DETAIL_FIELDS:
                if resource_data.get(field) in (None, "") and existing_data.get(field) not in (None, ""):
                    resource_data[field] = existing_data[field]
        elif existing_resource is not None and is_offline:
            existing_data = dict(existing_resource)
            for rid in (1, 2, 3):
                status_field = f"rid{rid}_status"
                radio_fields = tuple(
                    field for field in FIT_AP_RESOURCE_FIELDS if field.startswith(f"rid{rid}_")
                )
                if (
                    self._clean_identity_value(resource_data.get(status_field)) == ""
                    and any(existing_data.get(field) not in (None, "") for field in radio_fields)
                ):
                    resource_data[status_field] = "Down"
        if _has_lldp_payload(resource_data):
            source = resource_data.get("lldp_source") or resource_data.get("source") or "ac_bulk_lldp"
            lldp_data = normalize_lldp_payload({**resource_data, "lldp_source": source}, str(source))
            resource_data.update(
                merge_lldp_payload(dict(existing_resource) if existing_resource is not None else {}, lldp_data)
            )
            resource_data["lldp_neighbor"] = resource_data.get("lldp_neighbor_name")
        payload = self._payload(FIT_AP_RESOURCE_FIELDS, resource_data)
        payload["connection_record_observed"] = bool(
            row.get("connection_record_observed")
        )
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
            ON CONFLICT(ac_device_uuid, ap_uuid) DO UPDATE SET {updates}
            """,
            [payload[field] for field in FIT_AP_RESOURCE_FIELDS],
        )
        self._append_resource_history(
            conn,
            payload,
            previous=dict(existing_resource) if existing_resource is not None else None,
        )
        self._upsert_ap_entity(conn, payload)
        self._append_radio_history(conn, payload)
        self._append_resource_lldp_history(
            conn,
            payload,
        )
        if preserved_fields:
            app_logger.log_info(
                "FIT_AP_STATIC_IDENTITY_PRESERVED",
                (
                    f"ac_device_uuid={ac_device_uuid}, ap_uuid={ap_uuid}, "
                    f"ap_name={payload.get('ap_name') or ''}, "
                    f"preserved_fields={','.join(preserved_fields)}, "
                    f"collect_run_uuid={payload.get('collect_run_uuid') or ''}"
                ),
            )
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
                       e.station AS entity_station,
                       e.connection_state,
                       e.last_online_time,
                       e.offline_time,
                       e.last_state_change_at,
                       e.last_connection_record_seen_at,
                       e.connection_reonline_count,
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
                LEFT JOIN ap_entities e ON e.ap_uuid = r.ap_uuid
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
                       e.station AS entity_station,
                       e.connection_state,
                       e.last_online_time,
                       e.offline_time,
                       e.last_state_change_at,
                       e.last_connection_record_seen_at,
                       e.connection_reonline_count,
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
                LEFT JOIN ap_entities e ON e.ap_uuid = r.ap_uuid
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
            summary_payload = self._payload(
                FIT_AP_UNAUTHENTICATED_SUMMARY_FIELDS,
                {
                    **summary,
                    "ac_device_uuid": ac_device_uuid,
                    "snapshot_status": summary.get("snapshot_status")
                    or ("SUCCESS_WITH_ROWS" if rows else "SUCCESS_EMPTY"),
                },
            )
            summary_payload["collected_at"] = summary_payload.get("collected_at") or now
            summary_payload["updated_at"] = summary_payload.get("updated_at") or now
            previous_rows_by_identity = {
                unauthenticated_identity_key(dict(item)): dict(item)
                for item in conn.execute(
                    "SELECT * FROM ac_fit_ap_unauthenticated WHERE ac_device_uuid = ?",
                    (ac_device_uuid,),
                ).fetchall()
            }
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
                payload = self._payload(
                    FIT_AP_UNAUTHENTICATED_FIELDS,
                    {
                        **row,
                        "ac_device_uuid": ac_device_uuid,
                        "ap_mac": self._mac_from_text(
                            row.get("ap_mac")
                            or row.get("inferred_ap_mac")
                            or row.get("ap_name")
                        )
                        or None,
                        "site_key": row.get("site_key") or self.site_id,
                    },
                )
                payload["inferred_ap_mac"] = self._mac_from_text(payload.get("inferred_ap_mac")) or None
                payload["collected_at"] = payload.get("collected_at") or summary_payload["collected_at"] or now
                payload["updated_at"] = payload.get("updated_at") or now
                identity_key = unauthenticated_identity_key(payload)
                previous = previous_rows_by_identity.get(identity_key)
                self._insert(conn, "ac_fit_ap_unauthenticated", FIT_AP_UNAUTHENTICATED_FIELDS, payload)
                record_fit_ap_unauthenticated_change(
                    conn,
                    payload,
                    previous=previous,
                    identity_key=identity_key,
                    now=now,
                )
            conn.commit()

    def list_fit_ap_unauthenticated(self, ac_device_uuid: str) -> list[dict[str, object | None]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM ac_fit_ap_unauthenticated WHERE ac_device_uuid = ? ORDER BY ap_name, id",
                (ac_device_uuid,),
            ).fetchall()
        result = [dict(row) for row in rows]
        for row in result:
            row["site_key"] = row.get("site_key") or self.site_id
            row["station"] = row.get("entity_station") or ""
            row["source"] = WLAN_AP_UNAUTHENTICATED_SOURCE
        return result

    def list_all_fit_ap_unauthenticated(self) -> list[dict[str, object | None]]:
        with self.database.connect() as conn:
            rows = conn.execute("SELECT * FROM ac_fit_ap_unauthenticated ORDER BY ac_device_uuid, ap_name, id").fetchall()
        result = [dict(row) for row in rows]
        for row in result:
            row["site_key"] = row.get("site_key") or self.site_id
            row["source"] = WLAN_AP_UNAUTHENTICATED_SOURCE
        return result

    def list_fit_ap_unauthenticated_history(self, ac_device_uuid: str | None = None, limit: int = 100000) -> list[dict[str, object | None]]:
        with self.database.connect_readonly() as conn:
            result = list_fit_ap_unauthenticated_recent(
                conn, ac_device_uuid, limit=min(max(int(limit), 1), 100_000)
            )
        for row in result:
            row["source"] = WLAN_AP_UNAUTHENTICATED_SOURCE
        return result

    def get_fit_ap_unauthenticated_summary(self, ac_device_uuid: str) -> dict[str, object | None] | None:
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT * FROM ac_fit_ap_unauthenticated_summary WHERE ac_device_uuid = ?",
                (ac_device_uuid,),
            ).fetchone()
        return dict(row) if row is not None else None

    def list_fit_ap_resource_history(
        self, ac_device_uuid: str, limit: int = 10000
    ) -> list[dict[str, object | None]]:
        with self.database.connect_readonly() as conn:
            return list_fit_ap_resource_recent(
                conn, ac_device_uuid, limit=min(max(int(limit), 1), 10)
            )

    def list_all_fit_ap_resource_history(
        self, limit: int = 100000
    ) -> list[dict[str, object | None]]:
        with self.database.connect_readonly() as conn:
            return list_fit_ap_resource_recent(
                conn, limit=min(max(int(limit), 1), 100_000)
            )

    def list_ap_entities(self, ac_device_uuid: str | None = None) -> list[dict[str, object | None]]:
        params: list[object] = []
        where = ""
        if ac_device_uuid:
            where = (
                "WHERE EXISTS ("
                "SELECT 1 FROM ac_fit_ap_resources r "
                "WHERE r.ac_device_uuid = ? AND r.ap_uuid = e.ap_uuid)"
            )
            params.append(ac_device_uuid)
        with self.database.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT e.* FROM ap_entities e
                {where}
                ORDER BY e.ap_name, e.id
                """,
                params,
            ).fetchall()
        result = [dict(row) for row in rows]
        for row in result:
            row.pop("serial_identity_key", None)
        return result

    def list_offline_ap_entities(self, ac_device_uuid: str | None = None) -> list[dict[str, object | None]]:
        params: list[object] = []
        where = "WHERE (LOWER(TRIM(COALESCE(connection_state, ''))) = 'offline' OR (TRIM(COALESCE(connection_state, '')) = '' AND is_offline = 1))"
        if ac_device_uuid:
            where += (
                " AND EXISTS ("
                "SELECT 1 FROM ac_fit_ap_resources r "
                "WHERE r.ac_device_uuid = ? AND r.ap_uuid = e.ap_uuid)"
            )
            params.append(ac_device_uuid)
        with self.database.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT e.* FROM ap_entities e
                {where}
                ORDER BY e.ap_name, e.id
                """,
                params,
            ).fetchall()
        result = [dict(row) for row in rows]
        for row in result:
            row.pop("serial_identity_key", None)
        return result

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
                SELECT r.id, r.ac_device_uuid, r.ap_uuid, r.apid, r.ap_name, r.ap_mac,
                       r.serial_number, r.model, r.state, r.state_raw, r.state_display, r.site,
                       r.collected_at, r.site_key,
                       r.lldp_neighbor_name, r.lldp_neighbor_mac,
                       r.lldp_neighbor_mac_normalized, r.lldp_neighbor_interface,
                       r.lldp_local_interface, r.lldp_collected_at,
                       r.lldp_match_status,
                       r.updated_at,
                       e.station AS entity_station,
                       e.connection_state,
                       e.last_online_time,
                       e.offline_time,
                       e.last_state_change_at,
                       e.last_connection_record_seen_at,
                       e.connection_reonline_count
                FROM ac_fit_ap_resources r
                LEFT JOIN ap_entities e ON e.ap_uuid = r.ap_uuid
                ORDER BY r.id
                """
            ).fetchall()
        result = [dict(row) for row in rows]
        for row in result:
            row["site_key"] = row.get("site_key") or self.site_id
        return result

    def apply_fit_ap_connection_records(
        self,
        ac_device_uuid: str,
        rows: list[dict[str, object | None]],
    ) -> int:
        """Persist one successful connection-record snapshot independently.

        The connection-record command is optional to the FIT-AP resource
        command family, but authoritative for AP connection state and time.
        It therefore updates matching resources/entities without deleting or
        replacing the FIT-AP Current projection.
        """

        if not rows:
            return 0
        with self.database.connect() as conn:
            resources = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT * FROM ac_fit_ap_resources
                    WHERE ac_device_uuid = ?
                      AND (site_key = ? OR site_key IS NULL OR site_key = '')
                    """,
                    (ac_device_uuid, self.site_id),
                ).fetchall()
            ]
            entities = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT * FROM ap_entities
                    WHERE ac_device_uuid = ? AND site_id = ?
                    """,
                    (ac_device_uuid, self.site_id),
                ).fetchall()
            ]
            updated = 0
            for source in rows:
                target = _find_connection_identity_target(source, resources, entities)
                ap_uuid = str((target or {}).get("ap_uuid") or uuid4())
                payload = {
                    **(target or {}),
                    **source,
                    "ac_device_uuid": ac_device_uuid,
                    "ap_uuid": ap_uuid,
                    "site_key": source.get("site_key") or self.site_id,
                    "connection_ip": source.get("connection_ip") or source.get("ip_address"),
                    "connection_state": source.get("connection_state") or source.get("state"),
                    "connection_time": source.get("connection_time") or source.get("raw_time"),
                    "connection_record_raw_time": source.get("raw_time") or source.get("connection_time"),
                    "connection_record_resolved_time": source.get("resolved_time"),
                    "connection_record_collected_at": source.get("collected_at"),
                    "connection_record_observed": True,
                }
                if target and any(
                    str(item.get("ap_uuid") or "") == ap_uuid for item in resources
                ):
                    conn.execute(
                        """
                        UPDATE ac_fit_ap_resources
                        SET connection_ip = ?, connection_state = ?, connection_time = ?,
                            site_key = ?, connection_record_raw_time = ?,
                            connection_record_resolved_time = ?,
                            connection_record_collected_at = ?, updated_at = ?
                        WHERE ac_device_uuid = ? AND ap_uuid = ?
                        """,
                        (
                            source.get("connection_ip") or source.get("ip_address"),
                            source.get("connection_state") or source.get("state"),
                            source.get("connection_time") or source.get("raw_time"),
                            payload["site_key"],
                            source.get("raw_time") or source.get("connection_time"),
                            source.get("resolved_time"),
                            source.get("collected_at"),
                            self._now(),
                            ac_device_uuid,
                            ap_uuid,
                        ),
                    )
                self._upsert_ap_entity(conn, payload)
                updated += 1
            conn.commit()
        return updated

    def list_trackside_switch_identity_rows(
        self,
    ) -> list[dict[str, object | None]]:
        """Return current-site switch identities for deterministic LLDP matching."""

        with self.database.connect_readonly() as conn:
            rows = conn.execute(
                """
                SELECT d.device_uuid,
                       d.name,
                       d.system_name,
                       d.primary_address,
                       d.normalized_primary_address,
                       d.mac_address,
                       d.station_id,
                       d.station,
                       d.device_type,
                       d.device_vendor,
                       d.work_scope_status,
                       f.sysname AS fact_sysname,
                       f.mac_address AS fact_mac_address,
                       i.mac_address AS interface_mac_address
                FROM devices d
                LEFT JOIN device_facts f ON f.device_uuid = d.device_uuid
                LEFT JOIN device_interfaces i ON i.device_uuid = d.device_uuid
                WHERE LOWER(TRIM(d.device_type)) IN ('sw', 'switch', '交换机')
                ORDER BY d.device_uuid, i.interface_name
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
                       d.station AS device_station,
                       station.station_name AS formal_station_name,
                       d.device_uuid AS switch_device_uuid,
                       d.name AS switch_name,
                       l.local_interface AS switch_interface,
                       l.neighbor_mac AS observed_ap_mac,
                       l.collected_at AS observed_at,
                       l.collect_run_uuid,
                       l.updated_at,
                       l.neighbor_interface,
                       l.neighbor_sysname,
                       d.device_type,
                       g.name AS group_name,
                       d.work_scope_status,
                       d.project_phase
                FROM normalized_lldp l
                JOIN devices d ON d.device_uuid = l.device_uuid
                JOIN device_groups g ON g.id = d.group_id
                LEFT JOIN ap_extension_points station
                  ON station.belong_type = '__base_station__'
                 AND station.station_id = d.station_id
                WHERE LENGTH(l.ap_mac_key) = 12
                  AND l.ap_mac_key NOT GLOB '*[^0-9a-f]*'
                  AND LOWER(TRIM(d.device_type)) IN ('sw', 'switch', '交换机')
                  AND TRIM(g.name) = '车站'
                  AND d.work_scope_status = 'included'
                ORDER BY l.ap_mac_key, d.station_id, d.station,
                         d.device_uuid, l.local_interface
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
            unauthenticated = conn.execute(
                """
                SELECT COUNT(*) AS row_count, COALESCE(MAX(updated_at), '') AS updated_at
                FROM ac_fit_ap_unauthenticated
                """
            ).fetchone()
            entities = conn.execute(
                """
                SELECT COUNT(*) AS row_count, COALESCE(MAX(updated_at), '') AS updated_at
                FROM ap_entities
                WHERE site_id = ?
                """,
                (self.site_id,),
            ).fetchone()
            optical_treatments = conn.execute(
                """
                SELECT COUNT(*) AS row_count, COALESCE(MAX(updated_at), '') AS updated_at
                FROM ap_optical_treatment
                WHERE site_id = ?
                """,
                (self.site_id,),
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
            switch_identities = conn.execute(
                """
                SELECT COUNT(*) AS row_count,
                       COALESCE(MAX(d.updated_at), '') AS updated_at
                FROM devices d
                WHERE LOWER(TRIM(d.device_type)) IN ('sw', 'switch', '交换机')
                """
            ).fetchone()
            switch_facts = conn.execute(
                """
                SELECT COUNT(*) AS row_count,
                       COALESCE(MAX(f.updated_at), '') AS updated_at
                FROM device_facts f
                JOIN devices d ON d.device_uuid = f.device_uuid
                WHERE LOWER(TRIM(d.device_type)) IN ('sw', 'switch', '交换机')
                """
            ).fetchone()
            switch_interfaces = conn.execute(
                """
                SELECT COUNT(*) AS row_count,
                       COALESCE(MAX(i.updated_at), '') AS updated_at
                FROM device_interfaces i
                JOIN devices d ON d.device_uuid = i.device_uuid
                WHERE LOWER(TRIM(d.device_type)) IN ('sw', 'switch', '交换机')
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
            "unauthenticated_count": int(unauthenticated["row_count"] or 0),
            "unauthenticated_updated_at": str(unauthenticated["updated_at"] or ""),
            "ap_entity_count": int(entities["row_count"] or 0),
            "ap_entity_updated_at": str(entities["updated_at"] or ""),
            "optical_treatment_count": int(optical_treatments["row_count"] or 0),
            "optical_treatment_updated_at": str(optical_treatments["updated_at"] or ""),
            "station_switch_count": int(station_switches["row_count"] or 0),
            "station_switch_updated_at": str(station_switches["updated_at"] or ""),
            "switch_identity_count": int(switch_identities["row_count"] or 0),
            "switch_identity_updated_at": str(
                switch_identities["updated_at"] or ""
            ),
            "station_switch_fact_count": int(switch_facts["row_count"] or 0),
            "station_switch_fact_updated_at": str(
                switch_facts["updated_at"] or ""
            ),
            "station_switch_interface_count": int(
                switch_interfaces["row_count"] or 0
            ),
            "station_switch_interface_updated_at": str(
                switch_interfaces["updated_at"] or ""
            ),
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
                f"UPDATE ap_entities SET {assignments} WHERE site_id = ? AND lower(ap_mac) = ?",
                [*values.values(), self.site_id, normalized_mac.casefold()],
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
            previous_by_key = dict(merged)

            current_payloads: list[dict[str, object | None]] = []
            success_count = 0
            for row in rows:
                resource = self._resource_for_payload(conn, ac_device_uuid, row)
                payload = self._payload(FIT_AP_OPTICAL_FIELDS, {**row, "ac_device_uuid": ac_device_uuid})
                payload["ap_uuid"] = payload.get("ap_uuid") or resource.get("ap_uuid") or str(uuid4())
                payload["ap_name"] = payload.get("ap_name") or resource.get("ap_name")
                payload["ap_mac"] = payload.get("ap_mac") or resource.get("ap_mac")
                payload["serial_number"] = payload.get("serial_number") or resource.get("serial_number")
                payload["ap_id"] = payload.get("ap_id") or resource.get("apid") or resource.get("ap_id")
                payload["station_id"] = payload.get("station_id") or resource.get("metadata_station_id")
                payload["station_name"] = (
                    payload.get("station_name")
                    or resource.get("entity_station")
                    or resource.get("metadata_station_name")
                    or resource.get("site_name")
                )
                payload["section_name"] = payload.get("section_name") or resource.get("metadata_section_name")
                payload["direction"] = payload.get("direction") or resource.get("metadata_direction")
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
                if current is not None and _fit_ap_optical_prefer_score(current)[0] > _fit_ap_optical_prefer_score(payload)[0]:
                    merged[key] = _merge_failed_fit_ap_optical_payload(current, payload)
                    continue
                if _is_fit_ap_optical_success_payload(payload):
                    success_count += 1
                    if key:
                        if key in merged and merged[key].get("id") is not None:
                            payload["id"] = merged[key]["id"]
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
                    "FIT_AP_OPTICAL_DB_SAVE_PARTIAL",
                    f"ac_device_uuid={ac_device_uuid}, error=no successful AP optical rows; preserving valid telemetry and recording failure metadata",
                )

            columns = ", ".join(FIT_AP_OPTICAL_FIELDS)
            placeholders = ", ".join("?" for _ in FIT_AP_OPTICAL_FIELDS)
            for payload in [*merged.values(), *passthrough]:
                key = _fit_ap_optical_merge_key(payload)
                current = previous_by_key.get(key) if key else None
                current_id = _int_value(current.get("id")) if current else 0
                if current_id:
                    conn.execute(
                        f"UPDATE ac_fit_ap_optical SET {', '.join(f'{field} = ?' for field in FIT_AP_OPTICAL_FIELDS if field != 'ac_device_uuid')} WHERE id = ? AND ac_device_uuid = ?",
                        [payload[field] for field in FIT_AP_OPTICAL_FIELDS if field != "ac_device_uuid"] + [current_id, ac_device_uuid],
                    )
                else:
                    conn.execute(f"INSERT INTO ac_fit_ap_optical ({columns}) VALUES ({placeholders})", [payload[field] for field in FIT_AP_OPTICAL_FIELDS])
                self._update_fit_ap_resource_link_info(conn, ac_device_uuid, payload)
            for payload in current_payloads:
                key = _fit_ap_optical_merge_key(payload)
                previous = previous_by_key.get(key) if key else None
                self._record_fit_ap_optical_history(conn, payload)
                if previous is None or _fit_ap_lldp_changed(previous, payload):
                    self._append_resource_lldp_history(conn, payload)
            conn.commit()

    def list_fit_ap_optical(self, ac_device_uuid: str) -> list[dict[str, object | None]]:
        with self.database.connect_readonly() as conn:
            rows = conn.execute(
                "SELECT * FROM ac_fit_ap_optical WHERE ac_device_uuid = ? ORDER BY ap_name, id",
                (str(ac_device_uuid),),
            ).fetchall()
        return _latest_rows_by_ac_ap_identity([dict(row) for row in rows])

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

            bounded_optical = self._bounded_optical_authority_enabled(conn)
            if bounded_optical and candidate_ap_uuids:
                placeholders = ", ".join("?" for _ in candidate_ap_uuids)
                conn.execute(
                    f"DELETE FROM optical_current WHERE site_id = ? AND ap_uuid IN ({placeholders})",
                    [self.site_id, *candidate_ap_uuids],
                )
                conn.execute(
                    f"DELETE FROM ap_optical_treatment WHERE site_id = ? AND ap_uuid IN ({placeholders})",
                    [self.site_id, *candidate_ap_uuids],
                )

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
        with self.database.connect_readonly() as conn:
            rows = conn.execute(
                "SELECT * FROM ac_fit_ap_optical ORDER BY ac_device_uuid, ap_name, id"
            ).fetchall()
        return _latest_rows_by_ac_ap_identity([dict(row) for row in rows])

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
        return _latest_rows_by_ac_ap_identity([dict(row) for row in rows])

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

    def list_fit_ap_optical_history(
        self, ap_uuid: str | None = None, ap_name: str | None = None, limit: int = 100
    ) -> list[dict[str, object | None]]:
        bounded_limit = max(1, min(10, int(limit)))
        with self.database.connect_readonly() as conn:
            clauses = ["site_id = ?"]
            params: list[object] = [self.site_id]
            if ap_uuid:
                clauses.append("ap_identity = ?")
                params.append(str(ap_uuid))
            elif ap_name:
                clauses.append("ap_name = ?")
                params.append(str(ap_name))
            rows = conn.execute(
                "SELECT * FROM optical_history WHERE "
                + " AND ".join(clauses)
                + " ORDER BY changed_at DESC, id DESC LIMIT ?",
                [*params, bounded_limit],
            ).fetchall()
        return [self._bounded_optical_history_row(row) for row in rows]

    def list_fit_ap_optical_history_by_ap(self, ap_uuid: str, limit: int = 100) -> list[dict[str, object | None]]:
        return self.list_fit_ap_optical_history(ap_uuid=ap_uuid, limit=limit)

    def list_optical_current(self, ap_uuid: str | None = None) -> list[dict[str, object | None]]:
        with self.database.connect_readonly() as conn:
            if not self._bounded_optical_authority_enabled(conn):
                return []
            clauses = ["site_id = ?"]
            params: list[object] = [self.site_id]
            if ap_uuid:
                clauses.append("ap_identity = ?")
                params.append(str(ap_uuid))
            rows = conn.execute(
                "SELECT * FROM optical_current WHERE " + " AND ".join(clauses)
                + " ORDER BY ap_name, ap_identity, side",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def list_ap_optical_treatments(self) -> list[dict[str, object | None]]:
        with self.database.connect_readonly() as conn:
            if not self._bounded_optical_authority_enabled(conn):
                return []
            rows = conn.execute(
                "SELECT * FROM ap_optical_treatment WHERE site_id = ? ORDER BY ap_name, ap_identity",
                (self.site_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_current_optical_problem_counts_by_station(self) -> dict[str, int]:
        """Return one batch count from the current abnormal optical projection."""

        with self.database.connect_readonly() as conn:
            rows = conn.execute(
                """
                SELECT station_id, station_name, ap_identity
                FROM ap_optical_treatment
                WHERE site_id = ?
                  AND UPPER(TRIM(COALESCE(current_status, ''))) = 'ABNORMAL'
                """,
                (self.site_id,),
            ).fetchall()
        grouped: dict[str, set[str]] = {}
        for row in rows:
            station = str(row["station_name"] or row["station_id"] or "未归属").strip() or "未归属"
            identity = str(row["ap_identity"] or "").strip()
            if identity:
                grouped.setdefault(station, set()).add(identity)
        return {station: len(identities) for station, identities in grouped.items()}

    def is_bounded_optical_authority_enabled(self) -> bool:
        with self.database.connect_readonly() as conn:
            return self._bounded_optical_authority_enabled(conn)

    def list_fit_ap_radio_history_by_ap(
        self, ap_uuid: str, limit: int = 100
    ) -> list[dict[str, object | None]]:
        bounded_limit = max(1, min(10, int(limit)))
        with self.database.connect_readonly() as conn:
            rows = conn.execute(
                "SELECT * FROM fit_ap_radio_history "
                "WHERE site_id=? AND ap_identity=? "
                "ORDER BY changed_at DESC, id DESC LIMIT ?",
                (self.site_id, str(ap_uuid), bounded_limit),
            ).fetchall()
        return [self._bounded_radio_history_row(row) for row in rows]

    @staticmethod
    def _bounded_radio_history_row(row) -> dict[str, object | None]:
        result = dict(row)
        result["rid"] = result.get("radio_id")
        result["collected_at"] = result.get("changed_at") or result.get("collected_at")
        return result

    def list_fit_ap_lldp_history_by_ap(
        self,
        ap_uuid: str,
        limit: int = 100,
        ac_device_uuid: str | None = None,
    ) -> list[dict[str, object | None]]:
        bounded_limit = max(1, min(10, int(limit)))
        with self.database.connect_readonly() as conn:
            if str(ac_device_uuid or "").strip():
                rows = conn.execute(
                    """
                    SELECT * FROM fit_ap_lldp_history
                    WHERE ac_device_uuid = ? AND resource_key = ?
                    ORDER BY changed_at DESC, id DESC
                    LIMIT ?
                    """,
                    (str(ac_device_uuid), str(ap_uuid), bounded_limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM fit_ap_lldp_history
                    WHERE resource_key = ?
                    ORDER BY changed_at DESC, id DESC
                    LIMIT ?
                    """,
                    (str(ap_uuid), bounded_limit),
                ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _bounded_lldp_authority_enabled(conn) -> bool:
        try:
            row = conn.execute(
                "SELECT value FROM fit_ap_lldp_retention_meta WHERE key='authority'"
            ).fetchone()
        except Exception:
            return False
        return str(row[0] if row is not None else "") == "bounded_v1"

    @staticmethod
    def _bounded_optical_authority_enabled(conn) -> bool:
        try:
            row = conn.execute(
                "SELECT value FROM optical_retention_meta WHERE key='authority'"
            ).fetchone()
        except Exception:
            return False
        return str(row[0] if row is not None else "") == "bounded_v1"

    @staticmethod
    def _bounded_radio_authority_enabled(conn) -> bool:
        try:
            row = conn.execute(
                "SELECT value FROM fit_ap_radio_retention_meta WHERE key='authority'"
            ).fetchone()
        except Exception:
            return False
        return str(row[0] if row is not None else "") == "bounded_v1"

    @staticmethod
    def _bounded_optical_history_row(row) -> dict[str, object | None]:
        result = dict(row)
        try:
            payload = json.loads(str(result.get("payload_json") or "{}"))
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict):
            result = {**payload, **result}
        side = str(result.get("side") or "").upper()
        result["rx_power"] = result.get("rx_dbm")
        result["tx_power"] = result.get("tx_dbm")
        result["optical_alarm_status"] = result.get("status")
        result["collected_at"] = result.get("changed_at") or result.get("collected_at")
        result["side"] = side.casefold()
        return result

    def list_current_ap_lldp_states(
        self, ap_uuids: list[str] | None = None
    ) -> list[dict[str, object | None]]:
        """Read the bounded LLDP current authority without touching history."""

        with self.database.connect_readonly() as conn:
            if ap_uuids:
                keys = sorted({str(value).strip() for value in ap_uuids if str(value).strip()})
                if not keys:
                    return []
                placeholders = ", ".join("?" for _ in keys)
                rows = conn.execute(
                    f"""
                    SELECT * FROM fit_ap_lldp_current
                    WHERE resource_key IN ({placeholders})
                    ORDER BY ap_name, resource_key
                    """,
                    keys,
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM fit_ap_lldp_current ORDER BY ap_name, resource_key"
                ).fetchall()
        return [dict(row) for row in rows]

    def list_current_fit_ap_lldp_by_ap(
        self,
        ap_uuid: str,
        limit: int = 10,
        ac_device_uuid: str | None = None,
    ) -> list[dict[str, object | None]]:
        """Return the latest valid LLDP relation for each AP/link identity.

        This is a read-time projection only.  The complete history remains
        available through ``list_fit_ap_lldp_history_by_ap`` and the history
        page APIs.  A relation is valid for the current view only when all
        four identity fields are present: AP MAC, local interface, neighbor
        MAC, and neighbor interface.
        """
        bounded_rows: list[dict[str, object | None]] = []
        bounded_authority = False
        with self.database.connect_readonly() as conn:
            bounded_authority = self._bounded_lldp_authority_enabled(conn)
            if bounded_authority:
                scope_sql = (
                    " AND ac_device_uuid = ?"
                    if str(ac_device_uuid or "").strip()
                    else ""
                )
                params: tuple[object, ...] = (str(ap_uuid),)
                if scope_sql:
                    params += (str(ac_device_uuid),)
                bounded_rows = [
                    dict(row)
                    for row in conn.execute(
                        "SELECT * FROM fit_ap_lldp_current "
                        "WHERE ap_uuid = ?" + scope_sql,
                        params,
                    ).fetchall()
                ]

        # Once bounded current is authoritative, an empty/invalid current row
        # must not resurrect stale history in the detail view.  The fallback
        # keeps legacy fixtures and pre-cutover databases readable.
        if bounded_authority:
            rows = bounded_rows
        elif str(ac_device_uuid or "").strip():
            rows = self.list_fit_ap_lldp_history_by_ap(
                ap_uuid,
                limit=100_000,
                ac_device_uuid=ac_device_uuid,
            )
        else:
            rows = self.list_fit_ap_lldp_history_by_ap(ap_uuid, limit=100_000)
        latest: dict[tuple[str, str, str, str], dict[str, object | None]] = {}
        for source in rows:
            row = dict(source)
            ap_mac = normalize_ap_mac(row.get("ap_mac")).normalized
            local_interface = normalize_interface_key(
                row.get("local_interface") or row.get("lldp_local_interface")
            )
            neighbor_mac = normalize_ap_mac(
                row.get("neighbor_mac") or row.get("lldp_neighbor_mac")
            ).normalized
            neighbor_interface = normalize_interface_key(
                row.get("neighbor_interface") or row.get("lldp_neighbor_interface")
            )
            if not all((ap_mac, local_interface, neighbor_mac, neighbor_interface)):
                continue
            key = (ap_mac, local_interface, neighbor_mac, neighbor_interface)
            row["ap_mac"] = row.get("ap_mac") or ap_mac
            row["local_interface"] = row.get("local_interface") or row.get(
                "lldp_local_interface"
            )
            row["neighbor_mac"] = row.get("neighbor_mac") or row.get(
                "lldp_neighbor_mac"
            )
            row["neighbor_interface"] = row.get("neighbor_interface") or row.get(
                "lldp_neighbor_interface"
            )
            current = latest.get(key)
            if current is None or _current_lldp_row_score(row) > _current_lldp_row_score(current):
                latest[key] = row
        return sorted(
            latest.values(), key=_current_lldp_row_score, reverse=True
        )[: max(1, min(int(limit), 10))]

    def list_fit_ap_history_page(
        self,
        history_kind: str,
        ap_uuid: str,
        *,
        limit: int = 100,
        offset: int = 0,
        ac_device_uuid: str | None = None,
    ) -> list[dict[str, object | None]]:
        normalized_kind = str(history_kind or "").strip().casefold()
        table, identity_column = {
            "radio": ("fit_ap_radio_history", "ap_identity"),
            "lldp": ("fit_ap_lldp_history", "resource_key"),
            "optical": ("optical_history", "ap_identity"),
        }.get(normalized_kind, ("", ""))
        if not table:
            _fit_ap_history_table(history_kind)
            raise ValueError(f"不支持的 FIT-AP 历史类型：{history_kind}")
        with self.database.connect_readonly() as conn:
            if normalized_kind == "lldp":
                scope_sql = " AND ac_device_uuid=?" if str(ac_device_uuid or "").strip() else ""
                scope_params = (str(ac_device_uuid),) if scope_sql else ()
                rows = conn.execute(
                    f"SELECT * FROM {table} WHERE {identity_column}=?{scope_sql} "
                    "ORDER BY changed_at DESC, id DESC LIMIT ? OFFSET ?",
                    (str(ap_uuid), *scope_params, max(1, int(limit)), max(0, int(offset))),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT * FROM {table} WHERE site_id=? AND {identity_column}=? "
                    "ORDER BY changed_at DESC, id DESC LIMIT ? OFFSET ?",
                    (self.site_id, str(ap_uuid), max(1, int(limit)), max(0, int(offset))),
                ).fetchall()
        mapped = [dict(row) for row in rows]
        if normalized_kind == "radio":
            return [self._bounded_radio_history_row(row) for row in rows]
        if normalized_kind == "optical":
            return [self._bounded_optical_history_row(row) for row in rows]
        return mapped

    def count_fit_ap_history(
        self,
        history_kind: str,
        ap_uuid: str,
        ac_device_uuid: str | None = None,
    ) -> int:
        normalized_kind = str(history_kind or "").strip().casefold()
        table, identity_column = {
            "radio": ("fit_ap_radio_history", "ap_identity"),
            "lldp": ("fit_ap_lldp_history", "resource_key"),
            "optical": ("optical_history", "ap_identity"),
        }.get(normalized_kind, ("", ""))
        if not table:
            _fit_ap_history_table(history_kind)
            raise ValueError(f"不支持的 FIT-AP 历史类型：{history_kind}")
        with self.database.connect_readonly() as conn:
            if normalized_kind == "lldp":
                scope_sql = " AND ac_device_uuid=?" if str(ac_device_uuid or "").strip() else ""
                scope_params = (str(ac_device_uuid),) if scope_sql else ()
                row = conn.execute(
                    f"SELECT COUNT(*) AS total FROM {table} WHERE {identity_column}=?{scope_sql}",
                    (str(ap_uuid), *scope_params),
                ).fetchone()
            else:
                row = conn.execute(
                    f"SELECT COUNT(*) AS total FROM {table} WHERE site_id=? AND {identity_column}=?",
                    (self.site_id, str(ap_uuid)),
                ).fetchone()
        # The detail contract is Current + Recent10.  The list query already
        # bounds each page, so keep its reported total aligned with the rows
        # that the UI can actually expose.
        return min(10, int(row["total"] if row is not None else 0))

    def get_fit_ap_recent_change_counts(self, ap_uuid: str) -> dict[str, int]:
        counts = {"radio": 0, "lldp": 0, "optical": 0}
        if not str(ap_uuid or "").strip():
            return counts
        queries = {
            "radio": (
                "SELECT COUNT(*) AS total FROM fit_ap_radio_history "
                "WHERE site_id=? AND ap_identity=?",
                (self.site_id, str(ap_uuid)),
            ),
            "lldp": (
                "SELECT COUNT(*) AS total FROM fit_ap_lldp_history "
                "WHERE resource_key=?",
                (str(ap_uuid),),
            ),
            "optical": (
                "SELECT COUNT(*) AS total FROM optical_history "
                "WHERE site_id=? AND ap_identity=?",
                (self.site_id, str(ap_uuid)),
            ),
        }
        with self.database.connect_readonly() as conn:
            for kind, (sql, params) in queries.items():
                row = conn.execute(sql, params).fetchone()
                counts[kind] = min(10, int(row["total"] if row is not None else 0))
        return counts

    def get_previous_ap_lldp_history(
        self,
        identity: dict[str, str],
        before_collected_at: str | None = None,
    ) -> dict[str, object | None] | None:
        ap_uuid = str(identity.get("ap_uuid") or "").strip()
        ac_device_uuid = str(identity.get("ac_device_uuid") or "").strip()
        if not ap_uuid:
            return None
        with self.database.connect_readonly() as conn:
            if before_collected_at:
                scope_sql = " AND ac_device_uuid = ?" if ac_device_uuid else ""
                row = conn.execute(
                    f"""
                    SELECT * FROM fit_ap_lldp_history
                    WHERE resource_key = ?{scope_sql} AND changed_at < ?
                    ORDER BY changed_at DESC, id DESC
                    LIMIT 1
                    """,
                    (ap_uuid, *((ac_device_uuid,) if ac_device_uuid else ()), before_collected_at),
                ).fetchone()
            else:
                scope_sql = " AND ac_device_uuid = ?" if ac_device_uuid else ""
                row = conn.execute(
                    f"""
                    SELECT * FROM fit_ap_lldp_history
                    WHERE resource_key = ?{scope_sql}
                    ORDER BY changed_at DESC, id DESC
                    LIMIT 1
                    """,
                    (ap_uuid, *((ac_device_uuid,) if ac_device_uuid else ())),
                ).fetchone()
        return dict(row) if row is not None else None

    def list_latest_ap_lldp_history(
        self, ap_uuid: str
    ) -> dict[str, object | None] | None:
        rows = self.list_current_ap_lldp_states([str(ap_uuid)])
        return rows[0] if rows else None

    def list_latest_ap_lldp_histories(
        self, limit: int = 100000
    ) -> list[dict[str, object | None]]:
        return self.list_current_ap_lldp_states()[: max(1, int(limit))]

    def list_all_ap_lldp_history(
        self, limit: int = 100000
    ) -> list[dict[str, object | None]]:
        with self.database.connect_readonly() as conn:
            rows = conn.execute(
                """
                SELECT * FROM fit_ap_lldp_history
                ORDER BY changed_at DESC, id DESC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
        return [dict(row) for row in rows]

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
        if row is None:
            return None
        result = dict(row)
        result.pop("serial_identity_key", None)
        return result

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
                ON CONFLICT(ac_device_uuid, ap_uuid) DO UPDATE SET {updates}
                """,
                [payload[field] for field in FIT_AP_DETAIL_FIELDS],
            )
            conn.commit()
        return self.get_fit_ap_detail(
            str(payload["ap_uuid"]), str(payload["ac_device_uuid"])
        ) or payload

    def get_fit_ap_detail(
        self, ap_uuid: str, ac_device_uuid: str | None = None
    ) -> dict[str, object | None] | None:
        with self.database.connect() as conn:
            if ac_device_uuid:
                row = conn.execute(
                    "SELECT * FROM ac_fit_ap_details "
                    "WHERE ac_device_uuid = ? AND ap_uuid = ?",
                    (str(ac_device_uuid), str(ap_uuid)),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM ac_fit_ap_details WHERE ap_uuid = ? "
                    "ORDER BY updated_at DESC, ac_device_uuid LIMIT 1",
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

    def list_fit_ap_details_for_macs(
        self, macs: list[str], ac_device_uuid: str | None = None
    ) -> list[dict[str, object | None]]:
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
        ac_scope = " AND d.ac_device_uuid = ?" if ac_device_uuid else ""
        query_params = [*normalized, str(ac_device_uuid)] if ac_device_uuid else normalized
        with self.database.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT d.*
                FROM ac_fit_ap_details d
                JOIN ac_fit_ap_resources r
                  ON r.ac_device_uuid = d.ac_device_uuid AND r.ap_uuid = d.ap_uuid
                WHERE {expression} IN ({placeholders}){ac_scope}
                """,
                query_params,
            ).fetchall()
        return [dict(row) for row in rows]

    def replace_fit_ap_radio_details(
        self,
        ac_device_uuid: str,
        ap_uuid: str,
        rows: list[dict[str, object | None]],
    ) -> None:
        now = self._now()
        with self.database.connect() as conn:
            conn.execute(
                "DELETE FROM ac_fit_ap_radio_details "
                "WHERE ac_device_uuid = ? AND ap_uuid = ?",
                (str(ac_device_uuid), str(ap_uuid)),
            )
            for row in rows:
                payload = self._payload(
                    FIT_AP_RADIO_DETAIL_FIELDS,
                    {**row, "ac_device_uuid": str(ac_device_uuid), "ap_uuid": str(ap_uuid)},
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

    def list_fit_ap_radio_details(
        self, ap_uuid: str, ac_device_uuid: str | None = None
    ) -> list[dict[str, object | None]]:
        with self.database.connect() as conn:
            if ac_device_uuid:
                rows = conn.execute(
                    "SELECT * FROM ac_fit_ap_radio_details "
                    "WHERE ac_device_uuid = ? AND ap_uuid = ? ORDER BY radio_id",
                    (str(ac_device_uuid), str(ap_uuid)),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM ac_fit_ap_radio_details "
                    "WHERE ap_uuid = ? ORDER BY ac_device_uuid, radio_id",
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
            conn.execute(
                f"DELETE FROM ac_fit_ap_details WHERE ac_device_uuid = ? "
                f"AND ap_uuid IN ({placeholders})",
                [ac_device_uuid, *ap_uuids],
            )
            conn.execute(
                f"DELETE FROM ac_fit_ap_radio_details WHERE ac_device_uuid = ? "
                f"AND ap_uuid IN ({placeholders})",
                [ac_device_uuid, *ap_uuids],
            )
            conn.execute(f"DELETE FROM ac_fit_ap_metadata WHERE ap_uuid IN ({placeholders})", ap_uuids)
            conn.commit()
        return int(count or 0)

    def get_fit_ap_resource_by_uuid_any_ac(self, ap_uuid: str) -> dict[str, object | None] | None:
        with self.database.connect() as conn:
            row = conn.execute("SELECT * FROM ac_fit_ap_resources WHERE ap_uuid = ? ORDER BY id DESC LIMIT 1", (ap_uuid,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result.pop("serial_identity_key", None)
        return result

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
        payload_rows = [row for row in rows if str(row.get("site") or "") != "合计"]
        with self.database.connect() as conn:
            for row in payload_rows:
                upsert_station_online_summary(
                    conn, row, collected_at=collected_at, now=self._now()
                )
            conn.commit()
        return len(payload_rows)

    def list_station_online_summary_history(self, site_name: str | None = None, limit: int = 500, offset: int = 0) -> list[dict[str, object | None]]:
        with self.database.connect_readonly() as conn:
            return list_station_online_summary_recent(
                conn, site_name, limit=max(int(limit), 1), offset=max(int(offset), 0)
            )

    def count_station_online_summary_history(self, site_name: str | None = None) -> int:
        with self.database.connect_readonly() as conn:
            return count_station_online_summary_recent(conn, site_name)

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

    def _append_radio_history(self, conn, payload: dict[str, object | None]) -> None:
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
            normalized_bbssid = normalize_ap_mac(bbssid)
            if normalized_bbssid.normalized:
                bbssid = normalized_bbssid.display
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
            }
            ap_uuid = str(row.get("ap_uuid") or "")
            if not ap_uuid:
                continue
            upsert_radio_current_and_history(
                conn,
                {
                    **row,
                    "ap_mac": payload.get("ap_mac"),
                    "source": "fit_ap_resource",
                    "source_revision": payload.get("collect_run_uuid"),
                },
                site_id=self.site_id,
                radio_id=rid,
                now=str(row.get("collected_at") or self._now()),
            )
            if not normalized_bbssid.normalized:
                continue
            existing = conn.execute(
                """
                SELECT bbssid
                FROM ap_identity_radio_evidence
                WHERE ap_uuid = ? AND rid = ?
                """,
                (ap_uuid, rid),
            ).fetchone()
            if (
                existing is not None
                and normalize_ap_mac(existing["bbssid"]).normalized
                == normalized_bbssid.normalized
            ):
                continue
            conn.execute(
                """
                INSERT INTO ap_identity_radio_evidence (
                    ap_uuid, rid, bbssid, collected_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(ap_uuid, rid) DO UPDATE SET
                    bbssid = excluded.bbssid,
                    collected_at = excluded.collected_at,
                    updated_at = excluded.updated_at
                """,
                (
                    ap_uuid,
                    rid,
                    normalized_bbssid.display,
                    row.get("collected_at"),
                    self._now(),
                ),
            )

    def _record_fit_ap_optical_history(self, conn, payload: dict[str, object | None]) -> None:
        ap_uuid = str(payload.get("ap_uuid") or "")
        if not ap_uuid:
            return
        now = self._now()
        for side in ("AP", "SWITCH"):
            projection = upsert_optical_current_and_history(
                conn,
                payload,
                site_id=self.site_id,
                side=side,
                now=now,
            )
            if projection is not None:
                update_ap_optical_treatment(
                    conn,
                    site_id=self.site_id,
                    ap_identity=str(projection["ap_identity"]),
                    source_row=payload,
                    now=now,
                )

    def _append_resource_lldp_history(
        self,
        conn,
        payload: dict[str, object | None],
        *,
        previous_history: list[dict[str, object | None]] | None = None,
    ) -> None:
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
        upsert_lldp_current_and_history(
            conn,
            {
                **payload,
                "source": payload.get("_history_lldp_source")
                or payload.get("lldp_source")
                or "ac_bulk_lldp",
            },
            now=self._now(),
        )

    def _append_resource_history(
        self,
        conn,
        payload: dict[str, object | None],
        *,
        previous: dict[str, object | None] | None,
    ) -> None:
        history_payload = {
            key: value
            for key, value in payload.items()
            if key != "connection_record_observed"
        }
        record_fit_ap_resource_change(
            conn,
            {
                **history_payload,
                "site_name": history_payload.get("site_name") or history_payload.get("site"),
            },
            previous=(
                {
                    key: value
                    for key, value in (previous or {}).items()
                    if key != "serial_identity_key"
                }
                if previous is not None
                else None
            ),
            now=str(payload.get("collected_at") or self._now()),
        )

    def _resolve_fit_ap_entity_uuid(
        self,
        conn,
        ac_device_uuid: str,
        row: dict[str, object | None],
        *,
        continuity_resources: list[dict[str, object | None]] | None = None,
        continuity_entities: list[dict[str, object | None]] | None = None,
        incoming_name_counts: Counter[str] | None = None,
        identity_cache: dict[str, dict[str, list[dict[str, object | None]]]] | None = None,
    ) -> str:
        requested_uuid = str(row.get("ap_uuid") or "").strip()
        serial_number = self._clean_identity_value(row.get("serial_number"))
        normalized_mac = self._normalized_explicit_ap_mac(row)
        if serial_number:
            serial_matches = self._fit_ap_identity_matches_by_serial(
                conn, serial_number, identity_cache=identity_cache
            )
            serial_uuids = sorted({str(item["ap_uuid"]) for item in serial_matches})
            if len(serial_uuids) > 1:
                self._raise_fit_ap_identity_conflict(
                    ac_device_uuid=ac_device_uuid,
                    serial_number=serial_number,
                    reason="serial_maps_to_multiple_entities",
                    incoming_uuid=requested_uuid,
                    incoming_mac=normalized_mac,
                )
            if row.get("_batch_serial_identity_conflict"):
                self._raise_fit_ap_identity_conflict(
                    ac_device_uuid=ac_device_uuid,
                    serial_number=serial_number,
                    reason="batch_serial_has_multiple_macs",
                    canonical_uuid=serial_uuids[0] if serial_uuids else "",
                    incoming_uuid=requested_uuid,
                    incoming_mac=normalized_mac,
                )
            if serial_uuids:
                canonical_uuid = serial_uuids[0]
                mac_matches = (
                    self._fit_ap_identity_matches_by_mac(
                        conn, normalized_mac, identity_cache=identity_cache
                    )
                    if normalized_mac
                    else []
                )
                mac_uuids = {str(item["ap_uuid"]) for item in mac_matches}
                if mac_uuids - {canonical_uuid}:
                    self._raise_fit_ap_identity_conflict(
                        ac_device_uuid=ac_device_uuid,
                        serial_number=serial_number,
                        reason="serial_and_mac_map_to_different_entities",
                        canonical_uuid=canonical_uuid,
                        incoming_uuid=requested_uuid,
                        incoming_mac=normalized_mac,
                    )
                canonical_macs = {
                    self._normalized_explicit_ap_mac(item)
                    for item in serial_matches
                    if self._normalized_explicit_ap_mac(item)
                }
                identity_merged = (
                    requested_uuid != canonical_uuid
                    or bool(normalized_mac and normalized_mac not in canonical_macs)
                )
                if identity_merged and requested_uuid != canonical_uuid:
                    self._log_fit_ap_identity_event(
                        "SERIAL_IDENTITY_RESOLVED",
                        ac_device_uuid=ac_device_uuid,
                        canonical_uuid=canonical_uuid,
                        incoming_uuid=requested_uuid,
                        serial_number=serial_number,
                        incoming_mac=normalized_mac,
                    )
                if identity_merged:
                    self._log_fit_ap_identity_event(
                        "SERIAL_IDENTITY_MERGED",
                        ac_device_uuid=ac_device_uuid,
                        canonical_uuid=canonical_uuid,
                        incoming_uuid=requested_uuid,
                        serial_number=serial_number,
                        incoming_mac=normalized_mac,
                    )
                return canonical_uuid

        requested_found = self._fit_ap_identity_exists(
            conn, requested_uuid, identity_cache=identity_cache
        )
        if requested_uuid and requested_found:
            existing_serials = {
                self._serial_identity_key(item.get("serial_number"))
                for item in self._fit_ap_identity_rows_by_uuid(
                    conn, requested_uuid, identity_cache=identity_cache
                )
                if self._serial_identity_key(item.get("serial_number"))
            }
            if serial_number and existing_serials and self._serial_identity_key(serial_number) not in existing_serials:
                self._raise_fit_ap_identity_conflict(
                    ac_device_uuid=ac_device_uuid,
                    serial_number=serial_number,
                    reason="requested_uuid_has_different_serial",
                    canonical_uuid=requested_uuid,
                    incoming_uuid=requested_uuid,
                    incoming_mac=normalized_mac,
                )
            return requested_uuid

        if normalized_mac:
            mac_matches = self._fit_ap_identity_matches_by_mac(
                conn, normalized_mac, identity_cache=identity_cache
            )
            mac_uuids = sorted({str(item["ap_uuid"]) for item in mac_matches})
            if len(mac_uuids) > 1:
                self._raise_fit_ap_identity_conflict(
                    ac_device_uuid=ac_device_uuid,
                    serial_number=serial_number,
                    reason="mac_maps_to_multiple_entities",
                    canonical_uuid="",
                    incoming_uuid=requested_uuid,
                    incoming_mac=normalized_mac,
                )
            if mac_uuids:
                mac_uuid = mac_uuids[0]
                existing_serials = {
                    self._serial_identity_key(item.get("serial_number"))
                    for item in self._fit_ap_identity_rows_by_uuid(
                        conn, mac_uuid, identity_cache=identity_cache
                    )
                    if self._serial_identity_key(item.get("serial_number"))
                }
                if serial_number and existing_serials:
                    self._raise_fit_ap_identity_conflict(
                        ac_device_uuid=ac_device_uuid,
                        serial_number=serial_number,
                        reason="new_serial_reuses_existing_mac",
                        canonical_uuid=mac_uuid,
                        incoming_uuid=requested_uuid,
                        incoming_mac=normalized_mac,
                    )
                return mac_uuid

        continuity_uuid = self._resolve_fit_ap_resource_continuity_uuid(
            conn,
            ac_device_uuid,
            row,
            continuity_resources=continuity_resources,
            continuity_entities=continuity_entities,
            incoming_name_counts=incoming_name_counts,
        )
        if continuity_uuid:
            return continuity_uuid
        if requested_uuid:
            return requested_uuid
        return str(uuid4())

    def _fit_ap_identity_matches_by_serial(
        self,
        conn,
        serial_number: str,
        *,
        identity_cache: dict[str, dict[str, list[dict[str, object | None]]]] | None = None,
    ) -> list[dict[str, object | None]]:
        serial_key = self._serial_identity_key(serial_number)
        if identity_cache is not None:
            return list(identity_cache["serial"].get(serial_key, []))
        matches: list[dict[str, object | None]] = []
        for table in ("ac_fit_ap_resources", "ap_entities"):
            rows = conn.execute(
                f"SELECT * FROM {table} WHERE serial_number IS NOT NULL"
            ).fetchall()
            for raw_row in rows:
                row = dict(raw_row)
                if (
                    self._serial_identity_key(row.get("serial_number")) == serial_key
                    and self._clean_identity_value(row.get("ap_uuid"))
                ):
                    matches.append(row)
        return matches

    def _fit_ap_identity_matches_by_mac(
        self,
        conn,
        normalized_mac: str,
        *,
        identity_cache: dict[str, dict[str, list[dict[str, object | None]]]] | None = None,
    ) -> list[dict[str, object | None]]:
        if not normalized_mac:
            return []
        if identity_cache is not None:
            return list(identity_cache["mac"].get(normalized_mac, []))
        matches: list[dict[str, object | None]] = []
        for table in ("ac_fit_ap_resources", "ap_entities"):
            rows = conn.execute(
                f"SELECT * FROM {table} WHERE ap_mac IS NOT NULL"
            ).fetchall()
            for raw_row in rows:
                row = dict(raw_row)
                if (
                    self._normalized_explicit_ap_mac(row) == normalized_mac
                    and self._clean_identity_value(row.get("ap_uuid"))
                ):
                    matches.append(row)
        return matches

    def _fit_ap_identity_rows_by_uuid(
        self,
        conn,
        ap_uuid: str,
        *,
        identity_cache: dict[str, dict[str, list[dict[str, object | None]]]] | None = None,
    ) -> list[dict[str, object | None]]:
        if not ap_uuid:
            return []
        if identity_cache is not None:
            return list(identity_cache["uuid"].get(ap_uuid, []))
        rows: list[dict[str, object | None]] = []
        for table in ("ac_fit_ap_resources", "ap_entities"):
            rows.extend(
                dict(row)
                for row in conn.execute(
                    f"SELECT * FROM {table} WHERE ap_uuid = ?",
                    (ap_uuid,),
                ).fetchall()
            )
        return rows

    def _fit_ap_identity_exists(
        self,
        conn,
        ap_uuid: str,
        *,
        identity_cache: dict[str, dict[str, list[dict[str, object | None]]]] | None = None,
    ) -> bool:
        return bool(
            ap_uuid
            and self._fit_ap_identity_rows_by_uuid(
                conn, ap_uuid, identity_cache=identity_cache
            )
        )

    def _build_fit_ap_identity_cache(
        self,
        conn,
    ) -> dict[str, dict[str, list[dict[str, object | None]]]]:
        cache: dict[str, dict[str, list[dict[str, object | None]]]] = {
            "serial": {},
            "mac": {},
            "uuid": {},
        }
        for table in ("ac_fit_ap_resources", "ap_entities"):
            for raw_row in conn.execute(
                f"SELECT ap_uuid, serial_number, ap_mac, ac_device_uuid{', site_id' if table == 'ap_entities' else ''} FROM {table}"
            ).fetchall():
                row = dict(raw_row)
                ap_uuid = self._clean_identity_value(row.get("ap_uuid"))
                if not ap_uuid:
                    continue
                cache["uuid"].setdefault(ap_uuid, []).append(row)
                serial_key = self._serial_identity_key(row.get("serial_number"))
                if serial_key:
                    cache["serial"].setdefault(serial_key, []).append(row)
                normalized_mac = self._normalized_explicit_ap_mac(row)
                if normalized_mac:
                    cache["mac"].setdefault(normalized_mac, []).append(row)
        return cache

    def _register_fit_ap_identity_cache(
        self,
        cache: dict[str, dict[str, list[dict[str, object | None]]]],
        payload: dict[str, object | None],
    ) -> None:
        row = {
            "ap_uuid": payload.get("ap_uuid"),
            "serial_number": payload.get("serial_number"),
            "ap_mac": payload.get("ap_mac"),
            "ac_device_uuid": payload.get("ac_device_uuid"),
            "site_id": payload.get("site_id") or self.site_id,
        }
        ap_uuid = self._clean_identity_value(row.get("ap_uuid"))
        if not ap_uuid:
            return
        cache["uuid"].setdefault(ap_uuid, []).append(row)
        serial_key = self._serial_identity_key(row.get("serial_number"))
        if serial_key:
            cache["serial"].setdefault(serial_key, []).append(row)
        normalized_mac = self._normalized_explicit_ap_mac(row)
        if normalized_mac:
            cache["mac"].setdefault(normalized_mac, []).append(row)

    def _raise_fit_ap_identity_conflict(self, **kwargs: object) -> None:
        conflict = FitApIdentityConflict(**kwargs)
        self._log_fit_ap_identity_conflict(conflict)
        raise conflict

    def _log_fit_ap_identity_event(
        self,
        event: str,
        *,
        ac_device_uuid: str,
        canonical_uuid: str,
        incoming_uuid: str,
        serial_number: str,
        incoming_mac: str,
    ) -> None:
        app_logger.log_info(
            event,
            (
                f"site_id={self.site_id}, ac_device_uuid={ac_device_uuid}, "
                f"canonical_ap_uuid={canonical_uuid}, "
                f"incoming_ap_uuid={incoming_uuid}, serial_number={serial_number}, "
                f"incoming_mac={incoming_mac}"
            ),
        )

    def _log_fit_ap_identity_conflict(self, conflict: FitApIdentityConflict) -> None:
        app_logger.log_warning(
            "SERIAL_IDENTITY_CONFLICT",
            (
                f"site_id={self.site_id}, ac_device_uuid={conflict.ac_device_uuid}, "
                f"canonical_ap_uuid={conflict.canonical_uuid}, "
                f"incoming_ap_uuid={conflict.incoming_uuid}, serial_number={conflict.serial_number}, "
                f"canonical_mac={conflict.canonical_mac}, incoming_mac={conflict.incoming_mac}, "
                f"reason={conflict.reason}"
            ),
        )

    def _resolve_fit_ap_resource_continuity_uuid(
        self,
        conn,
        ac_device_uuid: str,
        row: dict[str, object | None],
        *,
        continuity_resources: list[dict[str, object | None]] | None,
        continuity_entities: list[dict[str, object | None]] | None,
        incoming_name_counts: Counter[str] | None,
    ) -> str:
        if self._clean_identity_value(row.get("serial_number")) or self._normalized_explicit_ap_mac(row):
            return ""
        ap_name = self._clean_identity_value(row.get("ap_name"))
        if not ap_name:
            return ""
        name_key = ap_name.casefold()
        if incoming_name_counts is not None and incoming_name_counts.get(name_key, 0) != 1:
            app_logger.log_warning(
                "FIT_AP_RESOURCE_CONTINUITY_AMBIGUOUS",
                f"ac_device_uuid={ac_device_uuid}, ap_name={ap_name}, reason=incoming_name_not_unique",
            )
            return ""

        resources = continuity_resources
        if resources is None:
            resources = [
                dict(item)
                for item in conn.execute(
                    "SELECT * FROM ac_fit_ap_resources WHERE ac_device_uuid = ? ORDER BY id DESC",
                    (ac_device_uuid,),
                ).fetchall()
            ]
        resource_candidates = [
            item
            for item in resources
            if self._clean_identity_value(item.get("ap_name")).casefold() == name_key
        ]
        # The entity's legacy ac_device_uuid is only last-seen metadata and
        # cannot establish current resource ownership.
        entities = continuity_entities or []
        entity_candidates = [
            item
            for item in entities
            if self._clean_identity_value(item.get("ap_name")).casefold() == name_key
        ]
        incoming_apid = self._clean_identity_value(row.get("apid") or row.get("ap_id"))

        def compatible(candidate: dict[str, object | None]) -> bool:
            candidate_apid = self._clean_identity_value(candidate.get("apid") or candidate.get("ap_id"))
            return not (incoming_apid and candidate_apid and incoming_apid != candidate_apid)

        candidates = [
            item
            for item in (*resource_candidates, *entity_candidates)
            if compatible(item) and self._clean_identity_value(item.get("ap_uuid"))
        ]
        if not candidates:
            if resource_candidates or entity_candidates:
                app_logger.log_warning(
                    "FIT_AP_RESOURCE_CONTINUITY_CONFLICT",
                    (
                        f"ac_device_uuid={ac_device_uuid}, ap_name={ap_name}, "
                        f"apid={incoming_apid}, reason=apid_mismatch"
                    ),
                )
            return ""

        stable_uuids = {
            str(item["ap_uuid"])
            for item in candidates
            if self._normalized_explicit_ap_mac(item)
            or self._clean_identity_value(item.get("serial_number"))
        }
        candidate_uuids = stable_uuids or {str(item["ap_uuid"]) for item in candidates}
        if len(candidate_uuids) == 1:
            return next(iter(candidate_uuids))
        app_logger.log_warning(
            "FIT_AP_RESOURCE_CONTINUITY_AMBIGUOUS",
            (
                f"ac_device_uuid={ac_device_uuid}, ap_name={ap_name}, "
                f"apid={incoming_apid}, candidate_count={len(candidate_uuids)}"
            ),
        )
        return ""

    def _merge_fit_ap_resource_identity(
        self,
        conn,
        incoming: dict[str, object | None],
        ap_uuid: str,
    ) -> tuple[dict[str, object | None], list[str]]:
        merged = dict(incoming)
        resource_sources: list[dict[str, object | None]] = []
        resource = conn.execute(
            "SELECT * FROM ac_fit_ap_resources "
            "WHERE ac_device_uuid = ? AND ap_uuid = ? ORDER BY id DESC LIMIT 1",
            (incoming.get("ac_device_uuid"), ap_uuid),
        ).fetchone()
        if resource is not None:
            resource_sources.append(dict(resource))
        entity = conn.execute(
            "SELECT * FROM ap_entities WHERE ap_uuid = ? ORDER BY id DESC LIMIT 1",
            (ap_uuid,),
        ).fetchone()
        entity_sources = [dict(entity)] if entity is not None else []
        sources = [*resource_sources, *entity_sources]

        preserved_fields: list[str] = []
        for field in FIT_AP_STABLE_IDENTITY_FIELDS:
            if field == "ap_mac":
                incoming_value = self._normalized_explicit_ap_mac(merged)
                fallback = next(
                    (self._normalized_explicit_ap_mac(source) for source in sources if self._normalized_explicit_ap_mac(source)),
                    "",
                )
            else:
                incoming_value = self._clean_identity_value(merged.get(field))
                fallback = next(
                    (
                        self._clean_identity_value(source.get(field))
                        for source in (
                            resource_sources if field == "ap_name" else sources
                        )
                        if self._clean_identity_value(source.get(field))
                    ),
                    "",
                )
            if incoming_value:
                merged[field] = incoming_value
            elif fallback:
                merged[field] = fallback
                preserved_fields.append(field)
            else:
                merged[field] = None
        return merged, preserved_fields

    def _upsert_ap_entity(self, conn, payload: dict[str, object | None]) -> None:
        now = self._now()
        ap_uuid = str(payload.get("ap_uuid") or uuid4())
        existing = conn.execute("SELECT * FROM ap_entities WHERE ap_uuid = ?", (ap_uuid,)).fetchone()
        existing_data = dict(existing) if existing is not None else {}
        state_display = payload.get("state_display") or self._state_display(payload.get("state") or payload.get("state_raw"))
        is_offline = 1 if self._is_ap_offline(payload.get("state") or payload.get("state_raw") or state_display) else 0
        connection_observed = bool(
            payload.get("connection_record_observed")
            or payload.get("connection_record_collected_at")
            or payload.get("connection_record_resolved_time")
        )
        previous_connection_state = _normalize_connection_state(
            existing_data.get("connection_state")
        )
        incoming_connection_state = _normalize_connection_state(
            payload.get("connection_state")
        )
        connection_state = (
            incoming_connection_state
            if connection_observed and incoming_connection_state
            else previous_connection_state
        )
        observation_at = self._clean_identity_value(
            payload.get("connection_record_collected_at")
        ) or self._clean_identity_value(payload.get("collected_at")) or now
        resolved_time = self._clean_identity_value(
            payload.get("connection_record_resolved_time")
        )
        previous_last_online = self._clean_identity_value(
            existing_data.get("last_online_time")
            or existing_data.get("last_online_at")
        )
        last_online_time = previous_last_online
        offline_time = self._clean_identity_value(existing_data.get("offline_time"))
        last_state_change_at = self._clean_identity_value(
            existing_data.get("last_state_change_at")
        )
        last_connection_record_seen_at = self._clean_identity_value(
            existing_data.get("last_connection_record_seen_at")
        )
        reonline_count = int(existing_data.get("connection_reonline_count") or 0)
        if connection_observed:
            last_connection_record_seen_at = observation_at
            if resolved_time and connection_state == "Run":
                last_online_time = resolved_time
            if connection_state and connection_state != previous_connection_state:
                last_state_change_at = observation_at
                if connection_state == "Offline":
                    offline_time = observation_at
                elif previous_connection_state == "Offline":
                    offline_time = ""
                    reonline_count += 1
            elif connection_state == "Offline" and not offline_time:
                offline_time = observation_at
        effective_offline = (
            connection_state == "Offline"
            if connection_state
            else bool(is_offline)
        )
        station = self._clean_identity_value(existing_data.get("station")) or _station_from_ap_payload(payload)
        row = self._payload(
            AP_ENTITY_FIELDS,
            {
                **existing_data,
                "ap_uuid": ap_uuid,
                "site_id": existing_data.get("site_id") or payload.get("site_id") or self.site_id,
                "site_key": existing_data.get("site_key") or payload.get("site_key") or self.site_id,
                "ac_device_uuid": payload.get("ac_device_uuid") or existing_data.get("ac_device_uuid"),
                "ap_name": self._non_empty(payload.get("ap_name"), existing_data.get("ap_name")),
                "ap_mac": self._non_empty(self._normalized_ap_mac(payload), existing_data.get("ap_mac")),
                "ap_id": self._non_empty(payload.get("apid") or payload.get("ap_id"), existing_data.get("ap_id")),
                "ap_ip": self._clean_identity_value(payload.get("ap_ip")) or None,
                "serial_number": self._non_empty(payload.get("serial_number"), existing_data.get("serial_number")),
                "model": self._non_empty(payload.get("model"), existing_data.get("model")),
                "group_name": self._non_empty(payload.get("group_name"), existing_data.get("group_name")),
                "mode": self._non_empty(payload.get("mode"), existing_data.get("mode")),
                "state": payload.get("state") or existing_data.get("state"),
                "state_raw": payload.get("state_raw") or payload.get("state") or existing_data.get("state_raw"),
                "state_display": state_display or existing_data.get("state_display"),
                "station": station,
                "milestone": self._non_empty(existing_data.get("milestone"), payload.get("mileage")),
                "direction": self._non_empty(existing_data.get("direction"), payload.get("direction")),
                "location_note": self._non_empty(existing_data.get("location_note"), payload.get("location_note")),
                "first_seen_at": existing_data.get("first_seen_at") or payload.get("collected_at") or now,
                "last_seen_at": payload.get("collected_at") or now,
                "last_online_at": last_online_time or existing_data.get("last_online_at"),
                "last_resource_update_at": payload.get("collected_at") or now,
                "connection_state": connection_state or existing_data.get("connection_state"),
                "connection_record_raw_time": (
                    self._clean_identity_value(payload.get("connection_record_raw_time"))
                    if connection_observed
                    else existing_data.get("connection_record_raw_time")
                ),
                "connection_record_resolved_time": (
                    resolved_time
                    if connection_observed and resolved_time
                    else existing_data.get("connection_record_resolved_time")
                ),
                "connection_record_collected_at": (
                    observation_at
                    if connection_observed
                    else existing_data.get("connection_record_collected_at")
                ),
                "last_online_time": last_online_time,
                "offline_time": offline_time,
                "last_state_change_at": last_state_change_at,
                "last_connection_record_seen_at": last_connection_record_seen_at,
                "connection_reonline_count": reonline_count,
                "is_offline": 1 if effective_offline else 0,
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

    def _prepare_fit_ap_resource_rows(
        self,
        rows: list[dict[str, object | None]],
    ) -> tuple[list[dict[str, object | None]], dict[str, int]]:
        """Normalize and reconcile one full-collection batch before SQL writes.

        Serial numbers are the only batch-level strong identity. MAC is used to
        merge complementary rows, but a serial group containing multiple MACs
        is retained as an explicit conflict instead of selecting one silently.
        """

        metrics = {
            "batch_serial_duplicates": 0,
            "batch_serial_merged": 0,
            "serial_identity_conflicts": 0,
            "duplicate_ap_entity_created": 0,
        }
        normalized_rows: list[dict[str, object | None]] = []
        for row in rows:
            normalized = dict(row)
            normalized["serial_number"] = self._clean_identity_value(
                row.get("serial_number")
            ) or None
            normalized_mac = self._normalized_explicit_ap_mac(row)
            if normalized_mac:
                normalized["ap_mac"] = normalized_mac
            normalized_rows.append(normalized)

        ordered_groups: list[tuple[str, str] | dict[str, object | None]] = []
        serial_groups: dict[str, list[dict[str, object | None]]] = {}
        mac_groups: dict[str, list[dict[str, object | None]]] = {}
        for row in normalized_rows:
            serial_key = self._serial_identity_key(row.get("serial_number"))
            if serial_key:
                group_key = ("serial", serial_key)
                if serial_key not in serial_groups:
                    serial_groups[serial_key] = []
                    ordered_groups.append(group_key)
                serial_groups[serial_key].append(row)
                continue
            normalized_mac = self._normalized_explicit_ap_mac(row)
            if normalized_mac:
                group_key = ("mac", normalized_mac)
                if normalized_mac not in mac_groups:
                    mac_groups[normalized_mac] = []
                    ordered_groups.append(group_key)
                mac_groups[normalized_mac].append(row)
                continue
            ordered_groups.append(row)

        prepared: list[dict[str, object | None]] = []
        for group in ordered_groups:
            if isinstance(group, dict):
                prepared.append(group)
                continue
            kind, identity_key = group
            source_rows = (
                serial_groups[identity_key]
                if kind == "serial"
                else mac_groups[identity_key]
            )
            if len(source_rows) == 1:
                prepared.append(source_rows[0])
                continue
            if kind != "serial":
                prepared.append(self._merge_fit_ap_batch_rows(source_rows))
                continue

            metrics["batch_serial_duplicates"] += len(source_rows) - 1
            valid_macs = {
                self._normalized_explicit_ap_mac(item)
                for item in source_rows
                if self._normalized_explicit_ap_mac(item)
            }
            explicit_uuids = {
                self._clean_identity_value(item.get("ap_uuid"))
                for item in source_rows
                if self._clean_identity_value(item.get("ap_uuid"))
            }
            merged = self._merge_fit_ap_batch_rows(source_rows)
            merged["_batch_serial_duplicate_count"] = len(source_rows) - 1
            if len(valid_macs) > 1 and len(explicit_uuids) > 1:
                merged["_batch_serial_identity_conflict"] = True
            elif len(valid_macs) > 1 and not explicit_uuids:
                merged["_batch_serial_identity_conflict"] = True
            if not merged.get("_batch_serial_identity_conflict"):
                metrics["batch_serial_merged"] += len(source_rows) - 1
            prepared.append(merged)
        return prepared, metrics

    @staticmethod
    def _merge_fit_ap_batch_rows(
        rows: list[dict[str, object | None]],
    ) -> dict[str, object | None]:
        merged = dict(rows[0])
        for row in rows[1:]:
            for key, value in row.items():
                if key.startswith("_") or value in (None, ""):
                    continue
                if merged.get(key) in (None, ""):
                    merged[key] = value
        return merged

    def _dedupe_fit_ap_resource_rows(
        self,
        rows: list[dict[str, object | None]],
    ) -> list[dict[str, object | None]]:
        """Compatibility wrapper for callers that only need prepared rows."""

        prepared, _metrics = self._prepare_fit_ap_resource_rows(rows)
        return prepared

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

    def _resource_for_payload(self, conn, ac_device_uuid: str, row: dict[str, object | None]) -> dict[str, object | None]:
        resource_select = (
            "SELECT r.*, m.site_name, m.station_id AS metadata_station_id, "
            "m.belong_section AS metadata_section_name, m.direction AS metadata_direction, "
            "e.station AS entity_station FROM ac_fit_ap_resources r "
            "LEFT JOIN ac_fit_ap_metadata m ON m.ap_uuid = r.ap_uuid "
            "LEFT JOIN ap_entities e ON e.ap_uuid = r.ap_uuid "
        )
        if row.get("ap_uuid"):
            found = conn.execute(
                resource_select
                + "WHERE r.ac_device_uuid = ? AND r.ap_uuid = ? "
                "ORDER BY r.id DESC LIMIT 1",
                (ac_device_uuid, row.get("ap_uuid")),
            ).fetchone()
            if found:
                return dict(found)
        serial_key = self._serial_identity_key(row.get("serial_number"))
        if serial_key:
            found = conn.execute(
                resource_select
                + "WHERE r.ac_device_uuid = ? AND r.serial_identity_key = ? "
                "ORDER BY r.id DESC LIMIT 1",
                (ac_device_uuid, serial_key),
            ).fetchone()
            if found:
                return dict(found)
        mac = self._mac_from_text(row.get("ap_mac"))
        if mac:
            matches = [
                dict(candidate)
                for candidate in conn.execute(
                    resource_select + "WHERE r.ac_device_uuid = ?",
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
        result = [dict(row) for row in rows]
        for item in result:
            item.pop("serial_identity_key", None)
        return result

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

    def _resource_with_metadata(self, item: dict[str, object | None]) -> dict[str, object | None]:
        item.pop("serial_identity_key", None)
        item["resource_station_text"] = item.get("site")
        item["site_key"] = item.get("site_key") or self.site_id
        item["station"] = item.get("entity_station") or item.get("station") or ""
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
        text = clean_fit_ap_serial(primary)
        if text:
            return text
        return fallback

    @staticmethod
    def _clean_identity_value(value: object) -> str:
        return clean_fit_ap_serial(value)

    @classmethod
    def _serial_identity_key(cls, value: object) -> str:
        return fit_ap_serial_identity_key(value)

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
        return classify_fit_ap_state(value) == "offline"

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


def _latest_rows_by_ac_ap_identity(rows: list[dict[str, object | None]]) -> list[dict[str, object | None]]:
    latest: dict[tuple[str, str, str], dict[str, object | None]] = {}
    passthrough: list[dict[str, object | None]] = []
    for row in rows:
        identity = _ap_identity_key(row)
        if not identity:
            passthrough.append(row)
            continue
        ac_device_uuid = str(row.get("ac_device_uuid") or "").strip().casefold()
        key = (ac_device_uuid, identity[0], identity[1])
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


def _normalize_connection_state(value: object) -> str:
    normalized = str(value or "").strip().casefold()
    return {
        "discovery": "Discovery",
        "join": "Join",
        "offline": "Offline",
        "run": "Run",
    }.get(normalized, str(value or "").strip())


def _station_from_ap_payload(row: dict[str, object | None]) -> str:
    """Return an AP station, never the project/line display name fallback."""

    site_key = str(row.get("site_key") or "").strip().casefold()
    for field in ("station_name", "station", "ap_station", "ownership_station", "site"):
        value = str(row.get(field) or "").strip()
        if not value or value.casefold() in {"-", "n/a", "none", "未归属"}:
            continue
        if site_key and value.casefold() == site_key:
            continue
        return value
    return ""


def _find_connection_identity_target(
    source: dict[str, object | None],
    resources: list[dict[str, object | None]],
    entities: list[dict[str, object | None]],
) -> dict[str, object | None]:
    candidates_by_uuid: dict[str, dict[str, object | None]] = {}
    for item in [*resources, *entities]:
        item_uuid = str(item.get("ap_uuid") or "").strip()
        if item_uuid:
            candidates_by_uuid.setdefault(item_uuid, item)
    candidates = list(candidates_by_uuid.values())
    requested_uuid = str(source.get("ap_uuid") or "").strip()
    if requested_uuid:
        for item in candidates:
            if str(item.get("ap_uuid") or "").strip() == requested_uuid:
                return item
    source_site = str(source.get("site_key") or "").strip().casefold()
    source_mac = AcRepository._mac_from_text(source.get("ap_mac") or source.get("ap_name"))
    if source_mac:
        matches = [
            item
            for item in candidates
            if (not source_site or str(item.get("site_key") or "").strip().casefold() in {"", source_site})
            and AcRepository._mac_from_text(item.get("ap_mac")) == source_mac
        ]
        if len(matches) == 1:
            return matches[0]
    source_serial = str(source.get("serial_number") or "").strip().casefold()
    if source_serial and source_serial not in {"-", "n/a"}:
        matches = [
            item
            for item in candidates
            if (not source_site or str(item.get("site_key") or "").strip().casefold() in {"", source_site})
            and str(item.get("serial_number") or "").strip().casefold() == source_serial
        ]
        if len(matches) == 1:
            return matches[0]
    source_apid = str(source.get("apid") or source.get("ap_id") or "").strip().casefold()
    source_ac = str(source.get("ac_device_uuid") or "").strip().casefold()
    if source_apid and source_ac:
        matches = [
            item for item in candidates
            if str(item.get("ac_device_uuid") or "").strip().casefold() == source_ac
            and str(item.get("apid") or item.get("ap_id") or "").strip().casefold() == source_apid
        ]
        if len(matches) == 1:
            return matches[0]
    source_name = str(source.get("ap_name") or "").strip().casefold()
    if source_name:
        matches = [
            item for item in candidates
            if str(item.get("ap_name") or "").strip().casefold() == source_name
            and (
                not source_site
                or str(item.get("site_key") or "").strip().casefold() in {"", source_site}
            )
        ]
        if len(matches) == 1:
            return matches[0]
    return {}


def _unauthenticated_identity_keys(row: dict[str, object | None]) -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    site_key = str(row.get("site_key") or row.get("site_id") or "").strip().casefold()
    mac = AcRepository._mac_from_text(row.get("ap_mac") or row.get("inferred_ap_mac") or row.get("mac"))
    if mac and site_key:
        keys.append(("site_mac", f"{site_key}:{mac.casefold()}"))
    serial = str(row.get("serial_number") or row.get("serial") or "").strip()
    if serial and serial not in {"-", "N/A", "n/a"} and site_key:
        keys.append(("site_serial", f"{site_key}:{serial.casefold()}"))
    ac_device_uuid = str(row.get("ac_device_uuid") or "").strip()
    apid = str(row.get("apid") or row.get("ap_id") or "").strip()
    if ac_device_uuid and apid and site_key:
        keys.append(("site_apid", f"{site_key}:{ac_device_uuid.casefold()}:{apid.casefold()}"))
    return keys


def _ap_identity_key(row: dict[str, object | None]) -> tuple[str, str] | None:
    for field in ("ap_uuid", "serial_number", "ap_mac"):
        value = str(row.get(field) or "").strip()
        if value and value not in {"-", "N/A", "n/a"}:
            return field, value.casefold()
    return None


def _fit_ap_optical_merge_key(row: dict[str, object | None]) -> tuple[str, str] | None:
    ac_uuid = str(row.get("ac_device_uuid") or "").strip()
    value = str(row.get("ap_uuid") or "").strip()
    if value and value not in {"-", "N/A", "n/a"}:
        return "ap_uuid", value.casefold()
    apid = str(row.get("apid") or row.get("ap_id") or "").strip()
    if ac_uuid and apid and apid not in {"-", "N/A", "n/a"}:
        return "apid", f"{ac_uuid.casefold()}:{apid.casefold()}"
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
    for field in FIT_AP_OPTICAL_FIELDS:
        if field in {"ac_device_uuid", "ap_uuid", "collected_at", "updated_at", "collect_run_uuid", "raw_log_path"}:
            continue
        if _is_empty_identity_value(new.get(field)) and not _is_empty_identity_value(old.get(field)):
            merged[field] = old.get(field)
    return merged


def _fit_ap_lldp_changed(previous: dict[str, object | None], current: dict[str, object | None]) -> bool:
    fields = (
        "lldp_neighbor", "lldp_local_interface", "lldp_local_interface_normalized",
        "lldp_neighbor_name", "lldp_neighbor_mac", "lldp_neighbor_mac_normalized",
        "lldp_neighbor_interface", "neighbor_interface", "neighbor_mac",
        "neighbor_device_name", "link_match_status", "lldp_match_status",
    )
    return any(str(previous.get(field) or "") != str(current.get(field) or "") for field in fields)


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


def _current_lldp_row_score(row: dict[str, object | None]) -> tuple[str, str, int, str]:
    return (
        str(row.get("collected_at") or row.get("collected_time") or ""),
        str(row.get("updated_at") or ""),
        _int_value(row.get("id")),
        str(row.get("event_id") or ""),
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
