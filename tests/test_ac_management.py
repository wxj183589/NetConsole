import json
import os
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QApplication, QComboBox, QHeaderView, QMessageBox, QMenu, QScrollArea, QSplitter, QTableWidget, QWidget

from netconsole.core.bootstrap import create_demo_context
from netconsole.core.database import Database
from netconsole.core.feature_flags import FeatureGate
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.core.settings import SettingsStore
from netconsole.core.optical_severity_engine import compute_optical_severity
from netconsole.core.sources.switch_source import build_switch_data_lookup
from netconsole.core.state_engine import compute_state, STATUS_COLORS
from netconsole.models.device import Device
from netconsole.models.mesh_log_models import MeshMrProfile
from netconsole.parsers.h3c.ac.fit_ap_lldp_neighbor_parser import parse_fit_ap_lldp_neighbor
from netconsole.parsers.h3c.ac.fit_ap_optical_parser import parse_fit_ap_lldp, parse_fit_ap_optical, parse_fit_ap_transceiver, parse_fit_ap_transceiver_diagnosis_snapshots
from netconsole.parsers.h3c.ac.state_mapper import map_fit_ap_state
from netconsole.parsers.h3c.ac.system_usage_parser import parse_cpu_usage, parse_memory
from netconsole.parsers.h3c.ac.wlan_ap_address_parser import parse_wlan_ap_addresses
from netconsole.parsers.h3c.ac.wlan_ap_parser import parse_wlan_ap_list, parse_wlan_ap_summary
from netconsole.parsers.h3c.ac.wlan_ap_radio_parser import parse_wlan_ap_radios
from netconsole.repositories.ac_repository import AcRepository, TRACKSIDE_AP_PLAN_MODE
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.device_group_repository import DeviceGroupRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.fit_ap_import_export import AP_EXTENSION_TEMPLATE_FIELDS, FitApImportExportService
from netconsole.services.fit_ap_link_info import format_h3c_mac, merge_lldp_payload, normalize_interface_key, normalize_mac as normalize_link_mac, resolve_fit_ap_link_info, resolve_optical_match_status
from netconsole.services.external_terminal import ExternalTerminalConfig, ExternalTerminalLaunchResult
from netconsole.services import h3c_ac_collect_service
from netconsole.services import command_guard
from netconsole.services.device_web_service import build_https_url, effective_https_port, parse_https_port
from netconsole.parsers.h3c.ac.wlan_ap_lldp_parser import parse_wlan_ap_lldp
from netconsole.parsers.h3c.ac.wlan_ap_radio_verbose_parser import parse_wlan_ap_radio_verbose_bbssid
from netconsole.services.h3c_ac_collect_service import (
    FIT_AP_RESOURCE_COMMANDS,
    FIT_AP_RESOURCE_OPTIONAL_COMMANDS,
    HTTPS_PORT_COMMANDS,
    RESOURCE_COMMANDS,
    collect_h3c_ac_info,
    collect_h3c_ac_resources,
    collect_h3c_fit_ap_resources,
)
from netconsole.services.h3c_ac_collect_service import FitApOpticalCollectResult
from netconsole.services.rail_transit import trackside_optical_collection
from netconsole.services.rail_transit.trackside_optical_collection import (
    DEFAULT_TRACKSIDE_OPTICAL_CONCURRENCY,
    TRACKSIDE_OPTICAL_COMMANDS,
    OpticalCommandAdapter,
    UnsupportedVendor,
    build_station_switch_targets,
    build_trackside_ap_targets,
    collect_trackside_optical,
    dedupe_targets,
)
from netconsole.services.netmiko_connection import normalize_command_output
from netconsole.services.neighbor_matcher import find_neighbor_optical_module, find_neighbor_rx_power, match_ap_from_device_lldp, match_neighbor_device, normalize_interface_name
from netconsole.services.offline_ap_ledger import OFFLINE_AP_LEDGER_COLUMNS, OFFLINE_AP_STATS_COLUMNS, OFFLINE_AP_STATUS_TEXT, offline_ap_headers
from netconsole.services.trackside_ap_business import (
    AP_OPTICAL_TREATMENT_RECORD_COLUMNS,
    NEW_ONLINE_AP_OVERVIEW_COLUMNS,
    TRACKSIDE_AP_BUSINESS_COLUMNS,
    TRACKSIDE_AP_BUSINESS_EXPORT_COLUMNS,
    TRACKSIDE_AP_DEVICE_COLUMNS,
    TRACKSIDE_AP_BUSINESS_INTERNAL_FIELDS,
    TREATMENT_CLOSED_LABEL,
    TREATMENT_OPEN_LABEL,
    build_ap_optical_treatment_records,
    build_new_online_ap_overview_rows,
    build_trackside_ap_business_rows,
    description_contains_ap,
    enrich_trackside_export_rows,
    export_trackside_ap_business_xlsx,
    filter_trackside_ap_business_rows,
    format_ap_side_alarm,
    format_trackside_display_value,
    has_ap_side_optical_data,
    is_current_optical_abnormal_row,
    is_trackside_ap_interface,
    normalize_link_state,
    normalize_vlan_text,
    parse_vlan_set,
    _optical_status_from_history,
    normalize_interface_name as normalize_trackside_interface_name,
    normalize_mac,
    pvid_matches_trackside_plan,
    trackside_row_status,
)
from netconsole.ui.theme.qt_theme_engine import apply_theme
from netconsole.ui.dialogs.device_detail_dialog import DeviceDetailDialog
from netconsole.ui.pagination import paginate_rows
from netconsole.ui.widgets.pagination_widget import PaginationWidget
from netconsole.ui.pages.ac_management_page import (
    AP_ONLINE_OVERVIEW_COLUMNS,
    AcManagementPage,
    FIT_AP_OPTICAL_COLUMNS,
    FIT_AP_RESOURCE_COLUMNS,
    build_ap_online_overview_rows,
    build_site_filter_items,
    enrich_fit_ap_optical_rows,
    evaluate_fit_ap_ap_status,
    evaluate_fit_ap_row_status,
    evaluate_fit_ap_switch_status,
    export_ap_online_overview_xlsx,
    export_fit_ap_optical_xlsx,
    filter_fit_ap_optical_rows,
    sort_fit_ap_optical_rows,
)
from netconsole.ui.pages.rail_transit_page import RailTransitPage
from netconsole.ui.pages.mesh_log_analysis_page import MESH_ANALYSIS_REPORT_ENABLED, MeshLogAnalysisPage
from netconsole.ui.pages.trackside_ap_plan_page import TracksideApPlanPage, read_trackside_plan_file, _dotted_netmask_to_prefix, _parse_mask_length
from netconsole.ui.pages.trackside_ap_service_page import TracksideApServicePage
from netconsole.ui.widgets.table_check_delegate import CheckBoxOnlyDelegate, is_checked_value
from netconsole.ui.trackside_optical_worker import TracksideApBusinessLoadResult, load_trackside_ap_business_snapshot
from netconsole.ui.ac_collect_worker import AcResourceCollectThread, FitApOpticalCollectThread
from netconsole.ui.dialogs.ap_detail_dialog import ApDetailDialog
from netconsole.ui.dialogs.ap_history_dialog import AP_LLDP_HISTORY_COLUMNS, AP_OPTICAL_HISTORY_COLUMNS, AP_RADIO_HISTORY_COLUMNS, ApHistoryDialog, export_ap_history_xlsx
from netconsole.ui.dialogs.fit_ap_detail_dialog import FIT_AP_DETAIL_TABS, LLDP_COLUMNS, OPTICAL_COLUMNS, FitApDetailDialog
from netconsole.ui.dialogs.station_online_history_dialog import STATION_ONLINE_HISTORY_COLUMNS, StationOnlineHistoryDialog, export_station_online_history_xlsx
from netconsole.ui.dialogs.trackside_interface_history_dialog import TracksideInterfaceHistoryDialog
from netconsole.core.optical_severity_engine import display_optical_status


FIXTURES = Path(__file__).parent / "fixtures" / "h3c"
AC_FIXTURES = FIXTURES / "ac"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def ac_fixture(name: str) -> str:
    return (AC_FIXTURES / name).read_text(encoding="utf-8")


class FakeConnection:
    def __init__(self, outputs=None):
        self.commands = []
        self.disconnected = False
        self.outputs = outputs or {}

    def send_command(self, command, read_timeout=None):
        self.commands.append(command)
        if command in self.outputs:
            value = self.outputs[command]
            if isinstance(value, Exception):
                raise value
            return value
        return {
            "screen-length disable": "",
            "display wlan ap all": fixture("display_wlan_ap_all.txt"),
            "display wlan ap all address": fixture("display_wlan_ap_all_address.txt"),
            "display wlan ap all radio": fixture("display_wlan_ap_all_radio.txt"),
            "display wlan ap unauthenticated": "Total number of connected auto APs: 0\n\nAP information:\nAP name APID State Model Serial ID Dev-Type Work-mode\n",
            "display wlan ap all radio verbose filter bbssid": "AP name              RID bbssid\nAP1                  1   0011-2233-4455\n",
            "display wlan ap all lldp": "AP name                        Local Interface          Neighbor Name                  Neighbor MAC    Neighbor Interface\nAP1                            GE1/0/2                  N/A                            903f-8645-6e00  GigabitEthernet2/0/19\n",
            "display cpu-usage": fixture("display_cpu_usage.txt"),
            "display memory": fixture("display_memory.txt"),
            "display ip https | include port": "HTTPS port: 443\n",
            "display ip https": "HTTPS port: 443\n",
            "display version": fixture("display_version.txt"),
            "display device": fixture("display_device_ac.txt"),
            "display device manuinfo": fixture("display_device_manuinfo.txt"),
        }[command]

    def disconnect(self):
        self.disconnected = True


class FakeTimingConnection:
    def __init__(self, outputs=None):
        self.commands = []
        self.calls = []
        self.disconnected = False
        self.outputs = outputs or {}

    def send_command_timing(self, command, **kwargs):
        self.commands.append(command)
        self.calls.append(
            {
                "command": command,
                "read_timeout": kwargs.get("read_timeout"),
                "strip_prompt": kwargs.get("strip_prompt"),
                "strip_command": kwargs.get("strip_command"),
            }
        )
        if command in self.outputs:
            value = self.outputs[command]
            if isinstance(value, Exception):
                raise value
            return value
        return f"<AC>{command}\nCommand {command} Result=Success\n<AC>"

    def disconnect(self):
        self.disconnected = True


class FakeOpticalConnection:
    instances = []

    def __init__(self, **kwargs):
        self.host = kwargs.get("host")
        self.commands = []
        self.disconnected = False
        FakeOpticalConnection.instances.append(self)

    def send_command(self, command, **_kwargs):
        self.commands.append(command)
        if self.host == "10.0.0.99":
            raise RuntimeError("boom")
        if command == "screen-length disable":
            return ""
        if command == "display interface brief":
            return """
Brief information on interfaces in bridge mode:
Link: ADM - administratively down; Stby - standby
Interface            Link Speed   Duplex Type PVID Description
GE1/0/1              UP   1G      F(a)   A    921  To AP
"""
        if command == "display interface":
            return """
GigabitEthernet1/0/1 current state: UP
Line protocol current state: UP
Description: To AP
PVID: 921
Port link-type: access
Untagged VLANs: 921
"""
        if command == "display lldp neighbor-information list":
            return """
Local Interface    Chassis ID          Port ID             System Name
GE1/0/1            bc5a-3457-cbe0      GigabitEthernet1/0/2 AP-1
"""
        if command == "display transceiver diagnosis interface":
            return """
GigabitEthernet1/0/1 transceiver diagnostic information:
  Current diagnostic parameters:
    Temp.(C) Voltage(V) Bias(mA) RX power(dBm) TX power(dBm)
    32.1 3.31 6.4 -6.10 -3.20
  Alarm thresholds:
    Low  -10.00 2.90 1.00 -20.00 -8.00
    High 80.00 3.70 12.00 0.00 0.00
  Warning thresholds:
    Low  -5.00 3.00 2.00 -15.00 -6.00
    High 70.00 3.60 10.00 -1.00 -1.00
"""
        return ""

    def disconnect(self):
        self.disconnected = True


def app():
    return QApplication.instance() or QApplication([])


def process_events_until(predicate, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    qt_app = app()
    while time.monotonic() < deadline:
        qt_app.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for Qt event condition")


_BaseAcManagementPage = AcManagementPage


class AcManagementPage(_BaseAcManagementPage):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        process_events_until(lambda: not self._background_jobs)


_BaseDeviceDetailDialog = DeviceDetailDialog
_BaseFitApDetailDialog = FitApDetailDialog


def DeviceDetailDialog(*args, **kwargs):
    dialog = _BaseDeviceDetailDialog(*args, **kwargs)
    process_events_until(lambda: not dialog.detail_load_job_id)
    return dialog


def FitApDetailDialog(*args, **kwargs):
    dialog = _BaseFitApDetailDialog(*args, **kwargs)
    process_events_until(lambda: not dialog.background_job_id)
    return dialog


class FakeTracksideLoadThread(QObject):
    load_finished = Signal(object)
    load_failed = Signal(int, str)
    finished = Signal()
    instances: list["FakeTracksideLoadThread"] = []

    def __init__(self, repository, site_name, generation, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.site_name = site_name
        self.generation = generation
        self.started = False
        self.deleted = False
        FakeTracksideLoadThread.instances.append(self)

    def start(self):
        self.started = True

    def deleteLater(self):
        self.deleted = True


def install_fake_trackside_loader(monkeypatch):
    FakeTracksideLoadThread.instances = []
    import netconsole.ui.pages.trackside_ap_service_page as page_module

    monkeypatch.setattr(page_module, "TracksideApBusinessLoadThread", FakeTracksideLoadThread)
    return FakeTracksideLoadThread


def make_database(tmp_path):
    database = Database(tmp_path / "devices.db")
    database.initialize()
    return database


def make_feature_gate(root: Path, *, hidden: tuple[str, ...]) -> FeatureGate:
    runtime = root / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "build_info.json").write_text(
        json.dumps({"edition": "customer", "feature_profile": "customer"}),
        encoding="utf-8",
    )
    features = {feature_id: {"visible": False, "enabled": False} for feature_id in hidden}
    (runtime / "feature_flags.json").write_text(
        json.dumps({"schema_version": 1, "profile": "customer", "features": features}, ensure_ascii=False),
        encoding="utf-8",
    )
    return FeatureGate(root)


def create_station_switch(repository: DeviceRepository, site_name: str, **kwargs) -> Device:
    group_repository = DeviceGroupRepository(repository.database, site_name)
    station_group = group_repository.find_by_name("\u8f66\u7ad9") or group_repository.create("\u8f66\u7ad9")
    payload = {
        "group_id": station_group.id,
        "device_type": "SW",
        "device_vendor": "H3C",
        **kwargs,
    }
    return repository.create(Device(**payload))


def make_ac_device():
    return Device(
        device_uuid="22222222-2222-4222-8222-222222222222",
        name="AC",
        device_type="AC",
        ip_address="10.0.0.51",
        ssh_enabled=1,
        ssh_username="admin",
        ssh_password="Admin@123",
    )


def test_ac_tables_are_created(tmp_path):
    database = make_database(tmp_path)

    with database.connect() as conn:
        table_names = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
        optical_history_columns = [row["name"] for row in conn.execute("PRAGMA table_info(ac_fit_ap_optical_history)").fetchall()]

    assert "ac_ap_summary" in table_names
    assert "ac_fit_ap_resources" in table_names
    assert "ac_fit_ap_optical" in table_names
    assert "ac_fit_ap_metadata" in table_names
    assert "ac_fit_ap_resource_history" in table_names
    assert "ac_station_ap_capacity" in table_names
    assert "ac_trackside_ap_plan" in table_names
    assert "ac_trackside_ap_plan_settings" in table_names
    assert "ac_fit_ap_optical_history" in table_names
    assert "ac_fit_ap_radio_history" in table_names
    assert "ac_fit_ap_lldp_history" in table_names
    for column in ("voltage", "bias_current", "rx_low_alarm", "tx_high_warning", "module_vendor", "wavelength", "transmission_distance", "connector_type"):
        assert column in optical_history_columns


def test_ac_repository_summary_upsert_and_replace_lists(tmp_path):
    repository = AcRepository(make_database(tmp_path))
    repository.upsert_ac_ap_summary({"ac_device_uuid": "ac-1", "total_aps": 1})
    repository.upsert_ac_ap_summary({"ac_device_uuid": "ac-1", "total_aps": 2})

    assert repository.get_ac_ap_summary("ac-1")["total_aps"] == 2

    repository.replace_fit_ap_resources("ac-1", [{"ap_name": "ap-a"}, {"ap_name": "ap-b"}])
    assert [row["ap_name"] for row in repository.list_fit_ap_resources("ac-1")] == ["ap-a", "ap-b"]
    repository.replace_fit_ap_resources("ac-1", [{"ap_name": "ap-c"}])
    assert [row["ap_name"] for row in repository.list_fit_ap_resources("ac-1")] == ["ap-c"]

    repository.replace_fit_ap_optical("ac-1", [{"ap_name": "ap-c", "status": "success", "neighbor_interface": "GigabitEthernet1/0/1", "rx_power": "-7.55"}])
    assert repository.list_fit_ap_optical("ac-1")[0]["neighbor_interface"] == "GigabitEthernet1/0/1"
    assert repository.get_fit_ap_optical_by_ap("ac-1", "ap-c")["rx_power"] == "-7.55"
    assert repository.get_fit_ap_resource("ac-1", "ap-c")["ap_name"] == "ap-c"


def test_fit_ap_resources_match_by_serial_number_and_keep_ap_uuid(tmp_path):
    repository = AcRepository(make_database(tmp_path))
    repository.replace_fit_ap_resources(
        "ac-1",
        [
            {
                "ap_name": "old-business-name",
                "ap_ip": "10.0.0.1",
                "ap_mac": "0011-2233-4455",
                "serial_number": "SN-001",
                "state": "R/M",
            }
        ],
    )
    first = repository.list_fit_ap_resources("ac-1")[0]

    repository.replace_fit_ap_resources(
        "ac-1",
        [
            {
                "ap_name": "new-business-name",
                "ap_ip": "10.0.0.99",
                "ap_mac": "0011-2233-9999",
                "serial_number": "SN-001",
                "state": "R/B",
            }
        ],
    )
    second = repository.list_fit_ap_resources("ac-1")[0]

    assert second["ap_uuid"] == first["ap_uuid"]
    assert second["ap_name"] == "new-business-name"
    assert second["ap_ip"] == "10.0.0.99"
    assert second["ap_mac"] == "0011-2233-9999"
    assert second["state"] == "R/B"
    assert len(repository.list_fit_ap_resources("ac-1")) == 1


def test_fit_ap_resources_reuse_ap_uuid_when_apid_changes(tmp_path):
    repository = AcRepository(make_database(tmp_path))
    repository.replace_fit_ap_resources(
        "ac-1",
        [{"ap_name": "ap-a", "apid": "1346", "ap_mac": "0011-2233-4455", "serial_number": "SN-001"}],
    )
    first = repository.list_fit_ap_resources("ac-1")[0]

    repository.replace_fit_ap_resources(
        "ac-1",
        [{"ap_name": "ap-a", "apid": "2001", "ap_mac": "0011-2233-4455", "serial_number": "SN-001"}],
    )
    second = repository.list_fit_ap_resources("ac-1")[0]
    entity = repository.list_ap_entities("ac-1")[0]

    assert second["ap_uuid"] == first["ap_uuid"]
    assert second["apid"] == "2001"
    assert entity["ap_uuid"] == first["ap_uuid"]
    assert entity["ap_id"] == "2001"


def test_fit_ap_resources_do_not_merge_different_identity_with_same_apid(tmp_path):
    repository = AcRepository(make_database(tmp_path))
    repository.replace_fit_ap_resources(
        "ac-1",
        [
            {"ap_name": "ap-a", "apid": "1346", "ap_mac": "0011-2233-4455", "serial_number": "SN-001"},
            {"ap_name": "ap-b", "apid": "1346", "ap_mac": "0011-2233-5566", "serial_number": "SN-002"},
        ],
    )

    rows = repository.list_fit_ap_resources("ac-1")
    assert len(rows) == 2
    assert len({row["ap_uuid"] for row in rows}) == 2
    assert len(repository.list_ap_entities("ac-1")) == 2


def test_fit_ap_resources_same_name_hardware_replacement_inherits_business_fields(tmp_path):
    database = make_database(tmp_path)
    repository = AcRepository(database)
    repository.replace_fit_ap_resources(
        "ac-1",
        [
            {
                "ap_name": "ap-a",
                "apid": "1346",
                "ap_ip": "10.0.0.1",
                "ap_mac": "0011-2233-4455",
                "serial_number": "SN-OLD",
                "model": "old-model",
                "state": "I",
            }
        ],
    )
    first = repository.list_fit_ap_resources("ac-1")[0]
    with database.connect() as conn:
        conn.execute(
            """
            UPDATE ap_entities
            SET station = ?, milestone = ?, direction = ?, location_note = ?
            WHERE ap_uuid = ?
            """,
            ("Station A", "K1+100", "up", "old note", first["ap_uuid"]),
        )
        conn.commit()

    repository.replace_fit_ap_resources(
        "ac-1",
        [
            {
                "ap_name": "ap-a",
                "apid": "2001",
                "ap_ip": "10.0.0.99",
                "ap_mac": "0011-2233-9999",
                "serial_number": "SN-NEW",
                "model": "new-model",
                "state": "R/M",
            }
        ],
    )
    second = repository.list_fit_ap_resources("ac-1")[0]
    entity = repository.list_ap_entities("ac-1")[0]
    history = repository.list_fit_ap_resource_history("ac-1")

    assert second["ap_uuid"] == first["ap_uuid"]
    assert entity["ap_uuid"] == first["ap_uuid"]
    assert entity["ap_mac"] == "0011-2233-9999"
    assert entity["serial_number"] == "SN-NEW"
    assert entity["model"] == "new-model"
    assert entity["ap_ip"] == "10.0.0.99"
    assert entity["ap_id"] == "2001"
    assert entity["state"] == "R/M"
    assert entity["station"] == "Station A"
    assert entity["milestone"] == "K1+100"
    assert entity["direction"] == "up"
    assert entity["location_note"] == "old note"
    assert {row["serial_number"] for row in history} == {"SN-OLD", "SN-NEW"}


def test_fit_ap_resources_allow_empty_or_repeated_apid_without_unique_failure(tmp_path):
    repository = AcRepository(make_database(tmp_path))
    repository.replace_fit_ap_resources(
        "ac-1",
        [
            {"ap_name": "ap-a", "apid": "", "ap_mac": "0011-2233-4455", "serial_number": "SN-001"},
            {"ap_name": "ap-b", "apid": "", "ap_mac": "0011-2233-5566", "serial_number": "SN-002"},
            {"ap_name": "ap-c", "apid": "1346", "ap_mac": "0011-2233-6677", "serial_number": "SN-003"},
            {"ap_name": "ap-d", "apid": "1346", "ap_mac": "0011-2233-7788", "serial_number": "SN-004"},
        ],
    )

    rows = repository.list_fit_ap_resources("ac-1")
    assert len(rows) == 4
    assert len({row["ap_uuid"] for row in rows}) == 4


def test_fit_ap_resources_repeated_update_is_idempotent(tmp_path):
    repository = AcRepository(make_database(tmp_path))
    rows = [
        {"ap_name": "ap-a", "apid": "1346", "ap_mac": "0011-2233-4455", "serial_number": "SN-001"},
        {"ap_name": "ap-b", "apid": "1346", "ap_mac": "0011-2233-5566", "serial_number": "SN-002"},
    ]

    repository.replace_fit_ap_resources("ac-1", rows)
    first_uuids = [row["ap_uuid"] for row in repository.list_fit_ap_resources("ac-1")]
    repository.replace_fit_ap_resources("ac-1", rows)
    second_rows = repository.list_fit_ap_resources("ac-1")

    assert [row["ap_uuid"] for row in second_rows] == first_uuids
    assert len(second_rows) == 2
    assert len(repository.list_ap_entities("ac-1")) == 2


def test_fit_ap_optical_and_metadata_use_ap_uuid_association(tmp_path):
    repository = AcRepository(make_database(tmp_path))
    repository.replace_fit_ap_resources("ac-1", [{"ap_name": "ap-a", "serial_number": "SN-001"}])
    ap_uuid = repository.list_fit_ap_resources("ac-1")[0]["ap_uuid"]

    repository.replace_fit_ap_optical("ac-1", [{"ap_uuid": ap_uuid, "ap_name": "renamed-ap", "rx_power": "-7.55"}])
    repository.upsert_fit_ap_metadata({"ap_uuid": ap_uuid, "ap_name": "renamed-ap", "site_name": "Station A"})

    assert repository.get_fit_ap_optical_by_uuid("ac-1", ap_uuid)["rx_power"] == "-7.55"
    assert repository.get_fit_ap_metadata_by_uuid(ap_uuid)["site_name"] == "Station A"


def test_fit_ap_optical_history_is_appended_and_sorted(tmp_path):
    repository = AcRepository(make_database(tmp_path))
    repository.replace_fit_ap_resources("ac-1", [{"ap_name": "ap-a", "serial_number": "SN-001", "ap_mac": "0011"}])
    ap_uuid = repository.list_fit_ap_resources("ac-1")[0]["ap_uuid"]

    repository.replace_fit_ap_optical("ac-1", [{"ap_uuid": ap_uuid, "ap_name": "ap-a", "rx_power": "-8", "collected_at": "2026-01-01T00:00:00"}])
    repository.replace_fit_ap_optical(
        "ac-1",
        [
            {
                "ap_uuid": ap_uuid,
                "ap_name": "ap-a",
                "rx_power": "-7",
                "temperature": "31.2",
                "voltage": "3.31",
                "bias_current": "5.10",
                "tx_power": "-4.5",
                "rx_low_alarm": "-19.00",
                "rx_high_alarm": "-3.00",
                "tx_low_alarm": "-11.00",
                "tx_high_alarm": "-1.00",
                "rx_low_warning": "-16.99",
                "rx_high_warning": "-5.00",
                "tx_low_warning": "-9.00",
                "tx_high_warning": "-3.00",
                "module_model": "SFP-GE-LX-SM1310",
                "module_serial_number": "OPT-001",
                "module_vendor": "H3C",
                "wavelength": "1310 nm",
                "transmission_distance": "10 km",
                "connector_type": "LC",
                "collected_at": "2026-01-02T00:00:00",
            }
        ],
    )

    history = repository.list_fit_ap_optical_history_by_ap(ap_uuid)
    assert [row["rx_power"] for row in history[:2]] == ["-7", "-8"]
    assert history[0]["ap_mac"] == "0011"
    assert history[0]["voltage"] == "3.31"
    assert history[0]["bias_current"] == "5.10"
    assert history[0]["rx_low_alarm"] == "-19.00"
    assert history[0]["tx_high_warning"] == "-3.00"
    assert history[0]["module_vendor"] == "H3C"
    assert history[0]["wavelength"] == "1310 nm"
    assert history[0]["transmission_distance"] == "10 km"
    assert history[0]["connector_type"] == "LC"


def test_fit_ap_lldp_history_is_appended_and_sorted(tmp_path):
    repository = AcRepository(make_database(tmp_path))
    repository.replace_fit_ap_resources("ac-1", [{"ap_name": "ap-a", "serial_number": "SN-001", "ap_mac": "0011"}])
    ap_uuid = repository.list_fit_ap_resources("ac-1")[0]["ap_uuid"]

    repository.replace_fit_ap_optical(
        "ac-1",
        [
            {
                "ap_uuid": ap_uuid,
                "ap_name": "ap-a",
                "ap_mac": "0011",
                "interface_name": "GigabitEthernet1/0/1",
                "lldp_neighbor": "SW01",
                "neighbor_interface": "GE1/0/1",
                "neighbor_mac": "aaaa-bbbb-cccc",
                "neighbor_device_name": "HX_1",
                "collected_at": "2026-01-01T00:00:00",
            }
        ],
    )
    repository.replace_fit_ap_optical(
        "ac-1",
        [
            {
                "ap_uuid": ap_uuid,
                "ap_name": "ap-a",
                "ap_mac": "0011",
                "interface_name": "GigabitEthernet1/0/2",
                "lldp_neighbor": "SW02",
                "neighbor_interface": "GE1/0/2",
                "neighbor_mac": "dddd-eeee-ffff",
                "neighbor_device_name": "HX_2",
                "collected_at": "2026-01-02T00:00:00",
            }
        ],
    )

    history = repository.list_fit_ap_lldp_history_by_ap(ap_uuid)

    assert [row["lldp_neighbor"] for row in history[:2]] == ["SW02", "SW01"]
    assert history[0]["local_interface"] == "GigabitEthernet1/0/2"
    assert history[0]["neighbor_device_name"] == "HX_2"


def test_fit_ap_resource_lldp_merges_ap_direct_and_marks_history_changes(tmp_path):
    repository = AcRepository(make_database(tmp_path))
    repository.replace_fit_ap_resources(
        "ac-1",
        [
            {
                "ap_name": "ap-a",
                "serial_number": "SN-001",
                "ap_mac": "0011-2233-4455",
                "lldp_source": "ac_bulk_lldp",
                "lldp_local_interface": "GE1/0/2",
                "lldp_neighbor_name": "N/A",
                "lldp_neighbor_mac": "903f-8645-6e00",
                "lldp_neighbor_interface": "GE2/0/19",
                "collected_at": "2026-01-01T00:00:00",
            }
        ],
    )
    ap_uuid = repository.list_fit_ap_resources("ac-1")[0]["ap_uuid"]

    direct_payload = {
        "ap_uuid": ap_uuid,
        "ap_name": "ap-a",
        "ap_mac": "0011-2233-4455",
        "lldp_source": "ap_direct_lldp",
        "lldp_local_interface": "GigabitEthernet1/0/2",
        "lldp_neighbor_name": "HX_1",
        "lldp_neighbor_mac": "90:3f:86:45:6e:00",
        "lldp_neighbor_interface": "GigabitEthernet2/0/19",
        "interface_name": "GigabitEthernet1/0/2",
        "rx_power": "-7.55",
        "tx_power": "-6.09",
        "collected_at": "2026-01-02T00:00:00",
    }
    repository.replace_fit_ap_optical("ac-1", [direct_payload])
    repository.replace_fit_ap_optical("ac-1", [{**direct_payload, "collected_at": "2026-01-03T00:00:00"}])

    resource = repository.get_fit_ap_resource_by_uuid("ac-1", ap_uuid)
    history = repository.list_fit_ap_lldp_history_by_ap(ap_uuid)

    assert resource["lldp_neighbor_name"] == "HX_1"
    assert resource["lldp_source"] == "merged"
    assert resource["lldp_match_status"] == "matched"
    assert resource["optical_interface"] == "GigabitEthernet1/0/2"
    assert resource["optical_rx_power"] == -7.55
    assert resource["optical_match_status"] == "matched"
    assert [row["source"] for row in history[:3]] == ["ap_direct_lldp", "ap_direct_lldp", "ac_bulk_lldp"]
    assert history[0]["is_changed"] == 0
    assert history[1]["is_changed"] == 1


def test_fit_ap_optical_failed_row_does_not_overwrite_valid_rx(tmp_path):
    repository = AcRepository(make_database(tmp_path))
    repository.replace_fit_ap_resources("ac-1", [{"ap_name": "ap-a", "serial_number": "SN-001"}])
    ap_uuid = repository.list_fit_ap_resources("ac-1")[0]["ap_uuid"]

    repository.replace_fit_ap_optical(
        "ac-1",
        [{"ap_uuid": ap_uuid, "ap_name": "ap-a", "rx_power": "-7.34", "status": "success", "collected_at": "2026-01-01T00:00:00"}],
    )
    repository.replace_fit_ap_optical(
        "ac-1",
        [{"ap_uuid": ap_uuid, "ap_name": "ap-a", "rx_power": "", "status": "timeout", "collected_at": "2026-01-02T00:00:00"}],
    )

    row = repository.get_fit_ap_optical_by_uuid("ac-1", ap_uuid)
    assert row["rx_power"] == "-7.34"
    assert row["ap_name"] == "ap-a"


def test_fit_ap_optical_lldp_only_success_is_not_treated_as_failure(tmp_path):
    repository = AcRepository(make_database(tmp_path))
    repository.replace_fit_ap_resources("ac-1", [{"ap_name": "ap-a", "serial_number": "SN-001"}])
    ap_uuid = repository.list_fit_ap_resources("ac-1")[0]["ap_uuid"]

    repository.replace_fit_ap_optical(
        "ac-1",
        [{"ap_uuid": ap_uuid, "ap_name": "ap-a", "status": "success", "neighbor_device_name": "SW01", "neighbor_interface": "GE1/0/1"}],
    )

    row = repository.get_fit_ap_optical_by_uuid("ac-1", ap_uuid)
    assert row["neighbor_device_name"] == "SW01"
    assert h3c_ac_collect_service._is_fit_ap_optical_success_row(dict(row))


def test_fit_ap_optical_retry_targets_and_concurrency():
    resources = [
        {"ap_uuid": "ap-ok", "ap_name": "AP-OK"},
        {"ap_uuid": "ap-empty", "ap_name": "AP-EMPTY"},
        {"ap_uuid": "ap-missing", "ap_name": "AP-MISSING"},
    ]
    round_rows = [
        {"ap_uuid": "ap-ok", "status": "success", "rx_power": "-7.34"},
        {"ap_uuid": "ap-empty", "status": "success", "rx_power": ""},
    ]

    retry = h3c_ac_collect_service._retry_fit_ap_optical_targets(resources, round_rows)

    assert [row["ap_uuid"] for row in retry] == ["ap-empty", "ap-missing"]
    assert h3c_ac_collect_service.retry_fit_ap_optical_concurrency(1000, floor=100, ratio=0.5) == 500
    assert h3c_ac_collect_service.retry_fit_ap_optical_concurrency(120, floor=100, ratio=0.5) == 100


def test_fit_ap_radio_history_is_appended_from_resource_rows(tmp_path):
    repository = AcRepository(make_database(tmp_path))
    repository.replace_fit_ap_resources(
        "ac-1",
        [
            {
                "ap_name": "ap-a",
                "serial_number": "SN-001",
                "rid1_channel": "149",
                "rid1_bandwidth": "40",
                "rid1_tx_power": "24",
                "collected_at": "2026-01-01T00:00:00",
                "collect_run_uuid": "run-1",
            }
        ],
    )
    ap_uuid = repository.list_fit_ap_resources("ac-1")[0]["ap_uuid"]
    repository.replace_fit_ap_resources(
        "ac-1",
        [
            {
                "ap_uuid": ap_uuid,
                "ap_name": "ap-a",
                "serial_number": "SN-001",
                "rid1_channel": "153",
                "rid1_bandwidth": "80",
                "rid1_tx_power": "25",
                "collected_at": "2026-01-02T00:00:00",
                "collect_run_uuid": "run-2",
            }
        ],
    )

    history = repository.list_fit_ap_radio_history_by_ap(ap_uuid)

    assert history[0]["rid"] == 1
    assert [row["channel"] for row in history[:2]] == ["153", "149"]
    assert history[0]["bandwidth"] == "80"
    assert history[0]["tx_power"] == "25"


def test_fit_ap_resource_history_is_appended_from_resource_rows(tmp_path):
    repository = AcRepository(make_database(tmp_path))
    repository.replace_fit_ap_resources(
        "ac-1",
        [
            {
                "ap_name": "ap-a",
                "ap_mac": "0011-2233-4455",
                "ap_ip": "10.0.0.1",
                "serial_number": "SN-001",
                "state_raw": "R/M",
                "state_display": "运行(主)",
                "site": "Station A",
                "collected_at": "2026-01-01T00:00:00",
                "collect_run_uuid": "run-1",
                "raw_log_path": "raw.log",
            }
        ],
    )
    row = repository.list_fit_ap_resource_history("ac-1")[0]

    assert row["ap_name"] == "ap-a"
    assert row["ap_mac"] == "0011-2233-4455"
    assert row["ap_ip"] == "10.0.0.1"
    assert row["state_raw"] == "R/M"
    assert row["site_name"] == "Station A"


def test_station_ap_capacity_can_be_saved_and_loaded(tmp_path):
    repository = AcRepository(make_database(tmp_path))
    repository.upsert_station_ap_capacity("Station A", 56)

    assert repository.list_station_ap_capacities()["Station A"] == 56


def test_station_ap_capacity_remark_can_be_saved_and_loaded(tmp_path):
    repository = AcRepository(make_database(tmp_path))
    repository.upsert_station_ap_capacity("Station A", 56)
    repository.upsert_station_ap_remark("Station A", "Need field check")

    details = repository.list_station_ap_capacity_details()
    assert details["Station A"]["ap_total"] == 56
    assert details["Station A"]["remark"] == "Need field check"


def test_trackside_ap_plan_repository_unified_capacity_and_pvid_plan(tmp_path):
    repository = AcRepository(make_database(tmp_path))
    repository.upsert_station_ap_capacity("Station A", 12)
    repository.upsert_station_ap_remark("Station A", "Keep this remark")
    repository.replace_trackside_ap_plan_rows(
        TRACKSIDE_AP_PLAN_MODE,
        [
            {"station_name": "Station A", "ap_count": 10, "ap_management_vlans": "921"},
            {"station_name": "Station B", "ap_count": 56, "ap_management_vlans": "922,923"},
        ],
    )

    assert repository.get_trackside_ap_plan_mode() == TRACKSIDE_AP_PLAN_MODE
    details = repository.list_active_trackside_plan_capacity_details()
    assert details["Station A"]["ap_total"] == 10
    assert details["Station A"]["remark"] == "Keep this remark"
    assert details["Station A"]["source"] == "trackside_plan"
    active_plan = repository.get_active_trackside_pvid_plan()
    assert active_plan["station_vlans"]["Station A"] == {921}
    assert active_plan["all_vlans"] == {921, 922, 923}
    assert active_plan["station_totals"]["Station B"] == 56

    repository.upsert_trackside_ap_plan_row(TRACKSIDE_AP_PLAN_MODE, {"station_name": "Station A", "ap_count": 30, "ap_management_vlans": "921"})
    updated_details = repository.list_active_trackside_plan_capacity_details()
    assert updated_details["Station A"]["ap_total"] == 30
    assert updated_details["Station A"]["remark"] == "Keep this remark"


def test_ap_entity_station_normalizes_aliases_and_preserves_existing_station(tmp_path):
    database = make_database(tmp_path)
    repository = AcRepository(database)
    ac = make_ac_device()

    repository.replace_fit_ap_resources(
        ac.device_uuid,
        [{"ap_uuid": "ap-1", "ap_name": "AP-1", "serial_number": "SN-AP-1", "site_name": "FIT Station", "state": "R/M"}],
    )
    with database.connect() as conn:
        row = conn.execute("SELECT station FROM ap_entities WHERE ap_uuid = 'ap-1'").fetchone()
    assert row["station"] == "FIT Station"

    repository.replace_fit_ap_resources(
        ac.device_uuid,
        [
            {
                "ap_uuid": "ap-1",
                "ap_name": "AP-1",
                "serial_number": "SN-AP-1",
                "ap_station": "LLDP Station",
                "site_name": "FIT Station 2",
                "state": "I",
            }
        ],
    )
    with database.connect() as conn:
        row = conn.execute("SELECT station FROM ap_entities WHERE ap_uuid = 'ap-1'").fetchone()
    assert row["station"] == "FIT Station"


def test_ap_and_trackside_station_headers_display_ownership_station():
    i18n = I18n("zh_CN")

    assert i18n.t("ac.station") == "归属站点"
    assert i18n.t("field.station") == "归属站点"
    assert [i18n.t(key) for key, _field in TRACKSIDE_AP_BUSINESS_COLUMNS][0] == "归属站点"


def test_trackside_ap_plan_unified_listing_falls_back_to_legacy_rows(tmp_path):
    repository = AcRepository(make_database(tmp_path))
    repository.replace_trackside_ap_plan_rows(
        "single_vlan",
        [{"station_name": "Station A", "ap_count": 10, "ap_management_vlans": "921"}],
    )
    repository.replace_trackside_ap_plan_rows(
        "multi_vlan",
        [{"station_name": "Station B", "ap_count": 56, "ap_management_vlans": "922,923"}],
    )

    unified_rows = repository.list_trackside_ap_plan(TRACKSIDE_AP_PLAN_MODE)
    assert [row["station_name"] for row in unified_rows] == ["Station B"]
    assert unified_rows[0]["mode"] == TRACKSIDE_AP_PLAN_MODE
    assert unified_rows[0]["ap_count"] == 56

    repository.upsert_trackside_ap_plan_row(TRACKSIDE_AP_PLAN_MODE, {"station_name": "Station B", "ap_count": 34, "ap_management_vlans": "922"})
    refreshed_rows = repository.list_trackside_ap_plan(TRACKSIDE_AP_PLAN_MODE)
    assert refreshed_rows[0]["ap_count"] == 34


def test_trackside_ap_plan_page_saves_edited_ap_count_from_table(tmp_path):
    app()
    repository = AcRepository(make_database(tmp_path))
    repository.replace_trackside_ap_plan_rows(
        TRACKSIDE_AP_PLAN_MODE,
        [{"station_name": "Station A", "ap_count": 42, "ap_management_vlans": "921"}],
    )
    page = TracksideApPlanPage(repository, I18n("en_US"), "demo")
    process_events_until(lambda: not page._busy)

    item = page.table.item(0, 1)
    assert item is not None
    assert item.flags() & Qt.ItemFlag.ItemIsEditable
    item.setText("34")

    assert page.save_plan() is True
    process_events_until(lambda: not page._busy)
    rows = repository.list_trackside_ap_plan(TRACKSIDE_AP_PLAN_MODE)
    assert rows[0]["ap_count"] == 34
    assert page.table.item(0, 1).text() == "34"
    assert repository.list_active_trackside_plan_capacity_details()["Station A"]["ap_total"] == 34


def test_trackside_ap_plan_accepts_dotted_netmask_and_saves_prefix(tmp_path):
    app()
    repository = AcRepository(make_database(tmp_path))
    page = TracksideApPlanPage(repository, I18n("en_US"), "demo")
    process_events_until(lambda: not page._busy)
    page.add_row()
    values = ["站", "0", "192.168.104.1", "255.255.252.0", "192.168.104.254", "201"]
    for column, value in enumerate(values):
        page.table.item(0, column).setText(value)

    assert page.save_plan() is True
    process_events_until(lambda: not page._busy)

    rows = repository.list_trackside_ap_plan(TRACKSIDE_AP_PLAN_MODE)
    assert rows[0]["mask_length"] == 22
    assert page.table.item(0, 3).text() == "22"


def test_trackside_ap_plan_rejects_non_contiguous_dotted_netmask(tmp_path):
    repository = AcRepository(make_database(tmp_path))
    page = TracksideApPlanPage(repository, I18n("en_US"), "demo")
    rows = [{"station_name": "A", "ap_count": 1, "mask_length": "255.0.255.0", "ap_management_vlans": "201"}]

    with pytest.raises(ValueError, match="必须是0-32或合法连续IPv4掩码"):
        page._validate_rows(rows)


def test_trackside_ap_plan_csv_import_accepts_dotted_netmask(tmp_path):
    csv_path = tmp_path / "trackside_plan.csv"
    csv_path.write_text(
        "车站名称,AP数量,AP起始地址,掩码,AP网关,AP管理VLAN\n"
        "站,0,192.168.104.1,255.255.252.0,192.168.104.254,201\n",
        encoding="utf-8-sig",
    )
    repository = AcRepository(make_database(tmp_path))
    page = TracksideApPlanPage(repository, I18n("en_US"), "demo")
    rows = read_trackside_plan_file(csv_path)

    page._validate_rows(rows)

    assert rows[0]["mask_length"] == 22


def test_trackside_ap_plan_mask_parser_supports_prefix_and_dotted_values():
    assert _parse_mask_length("") is None
    assert _parse_mask_length("0") == 0
    assert _parse_mask_length("24") == 24
    assert _parse_mask_length(32) == 32
    assert _parse_mask_length("255.255.255.0") == 24
    assert _parse_mask_length("255.255.252.0") == 22
    assert _parse_mask_length("255.255.0.0") == 16
    assert _parse_mask_length("0.0.0.0") == 0
    assert _dotted_netmask_to_prefix("255.255.255.255") == 32
    for invalid in ("255.0.255.0", "255.255.255.1", "255.255.255.256", "abc", "33", "-1"):
        assert _parse_mask_length(invalid) is None


def test_trackside_ap_plan_column_layout_keeps_network_fields_readable(tmp_path):
    app()
    repository = AcRepository(make_database(tmp_path))
    repository.replace_trackside_ap_plan_rows(
        TRACKSIDE_AP_PLAN_MODE,
        [
            {
                "station_name": "站",
                "ap_count": 0,
                "ap_start_address": "192.168.104.1",
                "mask_length": 22,
                "ap_gateway": "192.168.104.254",
                "ap_management_vlans": "201",
            }
        ],
    )
    page = TracksideApPlanPage(repository, I18n("en_US"), "demo")
    process_events_until(lambda: not page._busy)
    page._apply_column_layout()

    assert page.table.horizontalHeader().stretchLastSection() is False
    assert page.table.columnWidth(0) >= 260
    assert page.table.columnWidth(1) >= 90
    assert page.table.columnWidth(2) >= 170
    assert page.table.columnWidth(3) >= 140
    assert page.table.columnWidth(4) >= 170
    assert page.table.columnWidth(5) >= 170


def test_ap_online_overview_with_trackside_plan_locks_total_but_allows_remark(tmp_path):
    app()
    database = make_database(tmp_path)
    device_repository = DeviceRepository(database)
    ac = device_repository.create(make_ac_device())
    repository = AcRepository(database)
    repository.replace_fit_ap_resources(ac.device_uuid, [{"ap_uuid": "ap-1", "serial_number": "SN-1", "site": "Station A", "state": "R/M"}])
    repository.replace_trackside_ap_plan_rows(
        TRACKSIDE_AP_PLAN_MODE,
        [{"station_name": "Station A", "ap_count": 34, "ap_management_vlans": "921"}],
    )

    page = AcManagementPage(device_repository, I18n("en_US"), "demo")
    page.refresh_overview_table()
    process_events_until(lambda: not page._background_jobs)
    total_item = page.overview_table.item(0, 1)
    remark_item = page.overview_table.item(0, 5)
    assert not total_item.flags() & Qt.ItemFlag.ItemIsEditable
    assert remark_item.flags() & Qt.ItemFlag.ItemIsEditable

    remark_item.setText("Keep field note")
    process_events_until(lambda: not page._background_jobs)
    details = repository.list_active_trackside_plan_capacity_details()
    assert details["Station A"]["ap_total"] == 34
    assert details["Station A"]["remark"] == "Keep field note"


def test_trackside_ap_plan_refresh_prompts_for_unsaved_changes(tmp_path, monkeypatch):
    app()
    from netconsole.ui.pages import trackside_ap_plan_page as plan_page_module

    repository = AcRepository(make_database(tmp_path))
    repository.replace_trackside_ap_plan_rows(
        TRACKSIDE_AP_PLAN_MODE,
        [{"station_name": "Station A", "ap_count": 42, "ap_management_vlans": "921"}],
    )
    page = TracksideApPlanPage(repository, I18n("en_US"), "demo")
    process_events_until(lambda: not page._busy)

    monkeypatch.setattr(plan_page_module.MessageBox, "question", lambda *_args: QMessageBox.StandardButton.Cancel)
    page.table.item(0, 1).setText("34")
    page.refresh()
    assert page.table.item(0, 1).text() == "34"
    assert repository.list_trackside_ap_plan(TRACKSIDE_AP_PLAN_MODE)[0]["ap_count"] == 42

    monkeypatch.setattr(plan_page_module.MessageBox, "question", lambda *_args: QMessageBox.StandardButton.Discard)
    page.refresh()
    process_events_until(lambda: not page._busy)
    assert page.table.item(0, 1).text() == "42"

    page.table.item(0, 1).setText("34")
    monkeypatch.setattr(plan_page_module.MessageBox, "question", lambda *_args: QMessageBox.StandardButton.Save)
    page.refresh()
    process_events_until(lambda: not page._busy)
    assert page.table.item(0, 1).text() == "34"
    assert repository.list_trackside_ap_plan(TRACKSIDE_AP_PLAN_MODE)[0]["ap_count"] == 34


def test_station_online_summary_history_table_created(tmp_path):
    database = make_database(tmp_path)
    with database.connect() as conn:
        row = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'ac_station_online_summary_history'").fetchone()

    assert row is not None


def test_station_online_summary_history_save_and_list_desc(tmp_path):
    repository = AcRepository(make_database(tmp_path))
    rows = [
        {"site": "Station A", "total": 5, "online": 4, "offline": 1, "online_rate": "80.0%", "remark": "First"},
        {"site": "合计", "total": 5, "online": 4, "offline": 1, "online_rate": "80.0%", "remark": ""},
    ]

    assert repository.save_station_online_summary_history(rows, collected_at="2026-01-01T00:00:00") == 1
    repository.save_station_online_summary_history([{**rows[0], "remark": "Second"}], collected_at="2026-01-02T00:00:00")
    history = repository.list_station_online_summary_history("Station A")

    assert [row["remark"] for row in history] == ["Second", "First"]
    assert history[0]["site_name"] == "Station A"
    assert history[0]["online_count"] == 4


def test_station_ap_capacity_overrides_incomplete_planned_total(tmp_path):
    repository = AcRepository(make_database(tmp_path))
    repository.upsert_station_ap_capacity("Station A", 56)

    rows = [{"ap_name": "AP-A", "site_name": "Station A", "state": "R/M"}]
    overview = build_ap_online_overview_rows(
        planned_aps=rows,
        fit_ap_resources=rows,
        capacities=repository.list_station_ap_capacities(),
    )

    assert overview[0]["total"] == 56
    assert overview[0]["online"] == 1
    assert overview[0]["offline"] == 55


def test_ac_repository_metadata_crud_batch_edit_and_delete(tmp_path):
    repository = AcRepository(make_database(tmp_path))
    repository.replace_fit_ap_resources("ac-1", [{"ap_name": "ap-a"}, {"ap_name": "ap-b"}])
    repository.replace_fit_ap_optical("ac-1", [{"ap_name": "ap-a"}, {"ap_name": "ap-b"}])

    repository.upsert_fit_ap_metadata(
        {
            "ap_name": "ap-a",
            "site_name": "S1",
            "belong_type": "section",
            "belong_section": "联庄-中医药大学",
            "section_start_station": "中医药大学",
            "section_end_station": "联庄",
        }
    )
    metadata = repository.get_fit_ap_metadata("ap-a")
    assert metadata["site_name"] == "S1"
    assert metadata["belong_type"] == "section"
    assert metadata["belong_section"] == "联庄-中医药大学"
    assert repository.update_fit_ap_site(["ap-a", "ap-b"], "S2") == 2
    assert repository.get_fit_ap_metadata("ap-b")["site_name"] == "S2"
    assert repository.delete_fit_aps("ac-1", ["ap-a"]) == 1
    assert [row["ap_name"] for row in repository.list_fit_ap_resources("ac-1")] == ["ap-b"]
    assert repository.get_fit_ap_metadata("ap-a") is None


def test_wlan_ap_parser_extracts_summary_and_ap_list():
    summary = parse_wlan_ap_summary(fixture("display_wlan_ap_all.txt"))
    rows = parse_wlan_ap_list(fixture("display_wlan_ap_all.txt"))

    assert summary["total_aps"] == 2
    assert summary["online_aps"] == 2
    assert summary["remaining_local_ap_licenses"] == 59998
    assert rows[0]["ap_name"] == "4c6f-d608-0400"
    assert rows[0]["model"] == "WA6320-HCL"


def test_wlan_ap_parser_skips_state_legend_and_accepts_master_state():
    rows = parse_wlan_ap_list(
        """
 State : I = Idle,      J  = Join,       JA = JoinAck,    IL = ImageLoad
         C = Config,    DC = DataCheck,  R  = Run,   M = Master,  B = Backup

AP name                        APID  State Model           Serial ID
4c6f-d608-0400                 1     R/M   WA6320-HCL      H3C_4C-6F-D6-08-04-00
"""
    )

    assert len(rows) == 1
    assert rows[0]["state"] == "R/M"
    assert rows[0]["serial_number"] == "H3C_4C-6F-D6-08-04-00"


def test_wlan_ap_parser_handles_v9_states_and_chinese_gb2312_output():
    output = """
 State : I = Idle,      J  = Join,       JA = JoinAck,    IL = ImageLoad
         C = Config,    DC = DataCheck,  R  = Run,   M = Master,  B = Backup

AP name                        APID State Model           Serial ID            Group name             Online time   Clients Mode  IP address
站厅_AP-01                     10   JA   WA6624X         SN-CN-0001           一层无线               0:00:01:02    0       Fit   10.1.1.10
4c6f-d608-0400                 11   IL   WA6320-HCL      SN-MAC-0002          default-group          12 days       0       Fit   10.1.1.11
ap_under-score                 12   DC   WA6630          SN-DC-0003           grp-01                 1:02:03:04    0       Fit   10.1.1.12
"""
    decoded = normalize_command_output(output.encode("gb2312"), "gb18030")
    rows = parse_wlan_ap_list(decoded)

    assert [row["ap_name"] for row in rows] == ["站厅_AP-01", "4c6f-d608-0400", "ap_under-score"]
    assert rows[0]["state_display"] == "JoinAck"
    assert rows[1]["state_display"] == "ImageLoad"
    assert rows[2]["state_display"] == "DataCheck"
    assert rows[0]["group_name"] == "一层无线"


def test_wlan_ap_address_and_radio_parsers():
    addresses = parse_wlan_ap_addresses(fixture("display_wlan_ap_all_address.txt"))
    radios = parse_wlan_ap_radios(fixture("display_wlan_ap_all_radio.txt"))

    assert addresses["4c6f-d608-0400"]["ap_ip"] == "10.0.0.61"
    assert addresses["4c6f-d608-0400"]["ap_mac"] == "4c6f-d608-0400"
    assert radios["4c6f-d608-0400"]["rid1_channel"] == "1"
    assert radios["4c6f-d608-0400"]["rid2_tx_power"] == "17"


def test_address_radio_merge_by_ap_name_with_chinese_names():
    _summary, resources = h3c_ac_collect_service.parse_ac_resource_outputs(
        {
            "display wlan ap all": """
AP name                        APID State Model           Serial ID            Group name             Online time   Clients Mode  IP address
站厅_AP-01                     10   R/M  WA6624X         SN-CN-0001           一层无线               1:02:03:04    0       Fit   10.1.1.10
""",
            "display wlan ap all address": """
AP name                          IP address                       MAC address
站厅_AP-01                       10.1.1.10                        10b6-5e92-d3e0
""",
            "display wlan ap all radio": """
AP name                  RID State Channel          BW    Usage TxPower Clients
站厅_AP-01               1   Up    149              40    27    24      0
站厅_AP-01               2   Up    6                20    1     17      0
""",
        },
        "ac-1",
        "run-1",
        "files/rail_transit/trackside_ap/raw/ac/run-1/ac.log",
    )

    assert resources[0]["ap_name"] == "站厅_AP-01"
    assert resources[0]["apid"] == "10"
    assert resources[0]["ap_mac"] == "10b6-5e92-d3e0"
    assert resources[0]["rid1_channel"] == "149"
    assert resources[0]["rid2_tx_power"] == "17"


def test_state_cpu_and_memory_parsers():
    assert map_fit_ap_state("R/M") == "\u8fd0\u884c(\u4e3b)"
    assert map_fit_ap_state("R/B") == "\u8fd0\u884c(\u5907)"
    assert map_fit_ap_state("JA") == "JoinAck"
    assert parse_cpu_usage(fixture("display_cpu_usage.txt")) == {"cpu_5s": 16, "cpu_1m": 18, "cpu_5m": 18, "cpu_usage": "16%"}
    memory = parse_memory(fixture("display_memory.txt"))
    assert memory["memory_total"] == 770180
    assert memory["memory_free_ratio"] == 53.0
    assert memory["memory_usage"] == "47%"
    memory_table = parse_memory("Mem:        770180    366008    404172         0      3848    156656       52.9%")
    assert memory_table["memory_total"] == 770180
    assert memory_table["memory_used"] == 366008
    assert memory_table["memory_usage"] == "47%"
def test_wlan_ap_radio_parser_handles_state_column():
    radios = parse_wlan_ap_radios(
        """
AP name                  RID State Channel          BW    Usage TxPower Clients
                                                    (MHz) (%)   (dBm)
4c6f-d608-0400           1   Down  52(auto)         80    0     20      0
"""
    )

    assert radios["4c6f-d608-0400"]["rid1_channel"] == "52(auto)"
    assert radios["4c6f-d608-0400"]["rid1_bandwidth"] == "80"
    assert radios["4c6f-d608-0400"]["rid1_tx_power"] == "20"


def test_fit_ap_optical_parser_extracts_lldp_and_power_summary():
    parsed = parse_fit_ap_optical(fixture("display_fit_ap_lldp.txt"), fixture("display_fit_ap_transceiver_diagnosis.txt"))

    assert "SW01-DEMO" in parsed["lldp_neighbor"]
    assert parsed["rx_power"] == "-3.21"
    assert parsed["tx_power"] == "-2.85"
    assert "optical_alarm_status" not in parsed


def test_fit_ap_lldp_parser_handles_fit_ap_table_format():
    parsed = parse_fit_ap_lldp(
        """
System Name          Local Interface Chassis ID      Port ID
HX_1                 GE1/0/2         903f-8645-6e00  GigabitEthernet2/0/19
"""
    )

    assert parsed["lldp_neighbor"] == "HX_1"
    assert parsed["interface_name"] == "GigabitEthernet1/0/2"
    assert parsed["neighbor_mac"] == "903f-8645-6e00"
    assert parsed["neighbor_interface"] == "GigabitEthernet2/0/19"


def test_fit_ap_transceiver_parser_extracts_diagnosis_interface_and_manuinfo():
    parsed = parse_fit_ap_transceiver(
        """
GigabitEthernet1/0/2 transceiver diagnostic information:
Current diagnostic parameters:
Temp.(C) Voltage(V) Bias(mA) RX power(dBm) TX power(dBm)
43       3.31       6.10     -7.55         -6.09
Alarm thresholds:
High     90         3.63      0.00          0.00
Low      -10        2.97      -20.00        -20.00
Warning thresholds:
High     85         3.50      -1.00         -1.00
Low      -5         3.00      -17.00        -17.00
""",
        """
GigabitEthernet1/0/2 transceiver information:
Transceiver Type           : 1000_BASE_LX_SFP
Wavelength(nm)             : 1310
Transfer Distance(km)      : 10
Connector Type             : LC
Vendor Name                : H3C
""",
        """
GigabitEthernet1/0/2 transceiver manufacture information:
Manu. Serial Number        : SN123456
Vendor Name                : H3C
""",
    )

    assert parsed["interface_name"] == "GigabitEthernet1/0/2"
    assert parsed["temperature"] == "43"
    assert parsed["rx_power"] == "-7.55"
    assert parsed["tx_power"] == "-6.09"
    assert parsed["module_model"] == "1000_BASE_LX_SFP"
    assert parsed["wavelength"] == "1310 nm"
    assert parsed["transmission_distance"] == "10 km"
    assert parsed["module_serial_number"] == "SN123456"


def test_fit_ap_optical_parser_handles_real_machine_lldp_and_transceiver():
    lldp = parse_fit_ap_lldp(ac_fixture("real_fit_ap_lldp_neighbor.txt"))
    optical = parse_fit_ap_transceiver(ac_fixture("real_fit_ap_transceiver_diagnosis.txt"))

    assert lldp["lldp_neighbor"] == "HX_1"
    assert lldp["neighbor_interface"] == "GigabitEthernet2/0/19"
    assert lldp["neighbor_mac"] == "903f-8645-6e00"
    assert optical["interface_name"] == "GigabitEthernet1/0/2"
    assert optical["temperature"] == "43"
    assert optical["rx_power"] == "-7.55"
    assert optical["tx_power"] == "-6.09"


def test_real_machine_wlan_parsers_read_large_fixture():
    rows = parse_wlan_ap_list(ac_fixture("real_display_wlan_ap_all.txt"))
    addresses = parse_wlan_ap_addresses(ac_fixture("real_display_wlan_ap_all_address.txt"))
    radios = parse_wlan_ap_radios(ac_fixture("real_display_wlan_ap_all_radio.txt"))

    assert len(rows) >= 500
    assert rows[0]["ap_name"] == "AP-CLD_01"
    assert rows[0]["serial_number"] == "219801A4588249E00063"
    assert rows[0]["group_name"] == "cld-tcc-dcc"
    assert rows[0]["online_time"] == "27:02:49:39"
    assert addresses["AP-CLD_01"]["ap_ip"] == "10.62.113.177"
    assert radios["AP-CLD_01"]["rid1_channel"] == "149"


def test_wlan_ap_radio_verbose_bbssid_parser_groups_by_ap_name():
    parsed = parse_wlan_ap_radio_verbose_bbssid(
        """
Total number of APs: 932

                             Radio Filtered Information
  bbssid = Base BSSID

AP name              RID bbssid
30f5-277a-0ea0       1   30f5-277a-0ea0
30f5-277a-0ea0       2   30f5-277a-0eb0
30f5-277a-0ee0       1   30f5-277a-0ee0
30f5-277a-0ee0       2   30f5-277a-0ef0
30f5-277a-0f00       1   30f5-277a-0f00
"""
    )

    assert parsed["30f5-277a-0ea0"]["rid1_bbssid"] == "30f5-277a-0ea0"
    assert parsed["30f5-277a-0ea0"]["rid2_bbssid"] == "30f5-277a-0eb0"
    assert parsed["30f5-277a-0ee0"]["rid2_bbssid"] == "30f5-277a-0ef0"


def test_wlan_ap_lldp_parser_keeps_neighbor_interface():
    parsed = parse_wlan_ap_lldp(
        """
AP name                        Local Interface          Neighbor Name                  Neighbor MAC    Neighbor Interface
30f5-277a-0ea0                 GE1/0/2                  N/A                            903f-8645-6e00  GigabitEthernet2/0/19
30f5-277a-0ee0                 GE1/0/2                  N/A                            903f-8645-a600  GigabitEthernet2/0/8
30f5-277a-0f00                 GE1/0/2                  N/A                            903f-8645-fa00  GigabitEthernet2/0/38
"""
    )

    assert parsed["30f5-277a-0ea0"]["lldp_local_interface"] == "GigabitEthernet1/0/2"
    assert parsed["30f5-277a-0ea0"]["lldp_neighbor_name"] == "N/A"
    assert parsed["30f5-277a-0ea0"]["lldp_neighbor_mac"] == "903f-8645-6e00"
    assert parsed["30f5-277a-0ea0"]["lldp_neighbor_interface"] == "GigabitEthernet2/0/19"
    assert parsed["30f5-277a-0ea0"]["lldp_source"] == "ac_bulk_lldp"
    assert parsed["30f5-277a-0ea0"]["lldp_local_interface_normalized"] == "ge1/0/2"
    assert parsed["30f5-277a-0ea0"]["lldp_neighbor_mac_normalized"] == "903f86456e00"


def test_fit_ap_direct_lldp_parser_normalizes_neighbor_row():
    parsed = parse_fit_ap_lldp_neighbor(
        """
System Name          Local Interface  Chassis ID       Port ID
HX_1                 GE1/0/2          903f-8645-6e00   GigabitEthernet2/0/19
"""
    )

    assert parsed["lldp_source"] == "ap_direct_lldp"
    assert parsed["lldp_neighbor_name"] == "HX_1"
    assert parsed["lldp_local_interface"] == "GigabitEthernet1/0/2"
    assert parsed["lldp_local_interface_normalized"] == "ge1/0/2"
    assert parsed["lldp_neighbor_mac"] == "903f-8645-6e00"
    assert parsed["lldp_neighbor_mac_normalized"] == "903f86456e00"
    assert parsed["lldp_neighbor_interface"] == "GigabitEthernet2/0/19"


def test_fit_ap_transceiver_snapshot_parser_marks_optical_interface():
    snapshots = parse_fit_ap_transceiver_diagnosis_snapshots(
        """
GigabitEthernet1/0/2 transceiver diagnostic information:
Current diagnostic parameters:
Temp.(C) Voltage(V) Bias(mA) RX power(dBm) TX power(dBm)
43       3.31       6.10     -7.55         -6.09
"""
    )

    assert snapshots[0]["interface_name"] == "GigabitEthernet1/0/2"
    assert snapshots[0]["optical_interface"] == "GigabitEthernet1/0/2"
    assert snapshots[0]["optical_interface_normalized"] == "ge1/0/2"
    assert snapshots[0]["rx_power"] == "-7.55"


def test_fit_ap_link_normalization_and_merge_prioritize_ap_direct_lldp():
    assert normalize_interface_key("GE1/0/2") == normalize_interface_key("GigabitEthernet1/0/2") == "ge1/0/2"
    assert normalize_link_mac("90:3f:86:45:6e:00") == "903f86456e00"
    assert format_h3c_mac("903f86456e00") == "903f-8645-6e00"

    merged = merge_lldp_payload(
        {
            "lldp_source": "ac_bulk_lldp",
            "lldp_local_interface": "GE1/0/2",
            "lldp_neighbor_name": "N/A",
            "lldp_neighbor_mac": "903f-8645-6e00",
            "lldp_neighbor_interface": "GE2/0/19",
        },
        {
            "lldp_source": "ap_direct_lldp",
            "lldp_local_interface": "GigabitEthernet1/0/2",
            "lldp_neighbor_name": "HX_1",
            "lldp_neighbor_mac": "90:3f:86:45:6e:00",
            "lldp_neighbor_interface": "GigabitEthernet2/0/19",
        },
    )

    assert merged["lldp_neighbor_name"] == "HX_1"
    assert merged["lldp_source"] == "merged"
    assert merged["lldp_confidence"] == 90
    assert merged["lldp_match_status"] == "matched"
    assert resolve_optical_match_status(merged, {"optical_interface": "GE1/0/2", "rx_power": "-7.55"}) == "matched"
    assert resolve_optical_match_status(merged, {"optical_interface": "GE1/0/3", "rx_power": "-7.55"}) == "conflict"


def test_fit_ap_link_view_model_maps_legacy_fields_to_current_fields():
    resolved = resolve_fit_ap_link_info(
        {
            "lldp_neighbor": "HX_1",
            "neighbor_interface": "GigabitEthernet2/0/19",
            "neighbor_mac": "903f-8645-6e00",
            "neighbor_device_name": "04-横溪站",
            "neighbor_rx_power": "-7.55",
            "interface_name": "GE1/0/2",
        }
    )

    assert resolved["lldp_neighbor_name"] == "HX_1"
    assert resolved["lldp_neighbor_interface"] == "GigabitEthernet2/0/19"
    assert resolved["lldp_neighbor_mac"] == "903f-8645-6e00"
    assert resolved["lldp_neighbor_mac_normalized"] == "903f86456e00"
    assert resolved["neighbor_device_name"] == "04-横溪站"
    assert resolved["lldp_source"] == "legacy_compat"
    assert resolved["lldp_match_status"] == "matched"
    assert resolved["optical_rx_power"] == "-7.55"
    assert resolved["optical_match_status"] == "matched"


def test_h3c_ac_collect_service_uses_mock_netmiko(monkeypatch, tmp_path):
    connection = FakeConnection()
    monkeypatch.setattr(h3c_ac_collect_service.netmiko_connection, "ConnectHandler", lambda **_kwargs: connection)
    database = make_database(tmp_path)
    repository = AcRepository(database)

    result = collect_h3c_fit_ap_resources(make_ac_device(), "demo", repository=repository, paths=PathResolver(tmp_path))

    assert result.success is True
    assert result.summary_updated is True
    assert result.fit_ap_resources_updated == 2
    assert connection.commands == ["screen-length disable", *RESOURCE_COMMANDS]
    assert connection.disconnected is True
    assert result.raw_log_path == ""
    assert not (PathResolver(tmp_path).site_dir("demo") / "raw").exists()
    assert repository.get_ac_ap_summary("22222222-2222-4222-8222-222222222222")["total_aps"] == 2
    assert repository.list_fit_ap_resources("22222222-2222-4222-8222-222222222222")[0]["ap_ip"] == "10.0.0.61"


def test_enable_ap_remote_login_uses_per_command_timeouts(monkeypatch, tmp_path):
    connection = FakeTimingConnection()
    monkeypatch.setattr(h3c_ac_collect_service.netmiko_connection, "ConnectHandler", lambda **_kwargs: connection)
    device = make_ac_device()
    device.device_vendor = "H3C"

    result = h3c_ac_collect_service.run_h3c_ac_action(
        device,
        "demo",
        "enable_ap_remote_login",
        repository=AcRepository(make_database(tmp_path)),
        paths=PathResolver(tmp_path),
    )

    assert result.success is True
    assert connection.commands == [
        "screen-length disable",
        "system-view",
        "probe",
        "wlan ap-execute all exec-console enable",
        "return",
        "quit",
    ]
    timeouts = {call["command"]: call["read_timeout"] for call in connection.calls}
    assert timeouts["screen-length disable"] == 15
    assert timeouts["system-view"] == 15
    assert timeouts["probe"] == 30
    assert timeouts["wlan ap-execute all exec-console enable"] == 120
    assert timeouts["return"] == 30
    assert timeouts["quit"] == 30
    assert all(call["strip_prompt"] is False and call["strip_command"] is False for call in connection.calls)


def test_enable_ap_remote_login_treats_tail_read_timeout_as_success(monkeypatch, tmp_path):
    timeout = RuntimeError(
        "return: read_channel_timing's absolute timer expired. "
        "The network device was continually outputting data for longer than 10 seconds."
    )
    connection = FakeTimingConnection({"return": timeout})
    monkeypatch.setattr(h3c_ac_collect_service.netmiko_connection, "ConnectHandler", lambda **_kwargs: connection)
    device = make_ac_device()
    device.device_vendor = "H3C"

    result = h3c_ac_collect_service.run_h3c_ac_action(
        device,
        "demo",
        "enable_ap_remote_login",
        repository=AcRepository(make_database(tmp_path)),
        paths=PathResolver(tmp_path),
    )

    assert result.success is True
    return_result = next(item for item in result.command_results if item.command == "return")
    assert return_result.success is True
    assert str(return_result.error_message).startswith("warning: read timeout")
    assert "treated as success" in return_result.output
    assert connection.commands[-1] == "quit"


def test_enable_ap_remote_login_keeps_real_command_error_failed(monkeypatch, tmp_path):
    connection = FakeTimingConnection({"wlan ap-execute all exec-console enable": "% Unrecognized command found at '^' position."})
    monkeypatch.setattr(h3c_ac_collect_service.netmiko_connection, "ConnectHandler", lambda **_kwargs: connection)
    device = make_ac_device()
    device.device_vendor = "H3C"

    result = h3c_ac_collect_service.run_h3c_ac_action(
        device,
        "demo",
        "enable_ap_remote_login",
        repository=AcRepository(make_database(tmp_path)),
        paths=PathResolver(tmp_path),
    )

    assert result.success is False
    assert "% Unrecognized command" in str(result.error_message)


def test_h3c_ac_resource_only_collect_skips_overview_commands(monkeypatch, tmp_path):
    connection = FakeConnection()
    monkeypatch.setattr(h3c_ac_collect_service.netmiko_connection, "ConnectHandler", lambda **_kwargs: connection)
    database = make_database(tmp_path)
    repository = AcRepository(database)

    result = collect_h3c_fit_ap_resources(
        make_ac_device(),
        "demo",
        repository=repository,
        paths=PathResolver(tmp_path),
    )

    assert result.success is True
    assert result.summary_updated is True
    assert result.https_port_collected is False
    assert connection.commands == ["screen-length disable", *FIT_AP_RESOURCE_COMMANDS, *FIT_AP_RESOURCE_OPTIONAL_COMMANDS]
    assert "display cpu-usage" not in connection.commands
    assert "display memory" not in connection.commands
    assert "display version" not in connection.commands
    assert "display device" not in connection.commands
    summary = repository.get_ac_ap_summary("22222222-2222-4222-8222-222222222222")
    assert summary["total_aps"] == 2
    assert summary["online_aps"] == 2
    assert summary["offline_aps"] == 0
    assert summary["cpu_usage"] is None
    assert summary["model"] is None
    assert repository.list_fit_ap_resources("22222222-2222-4222-8222-222222222222")[0]["ap_ip"] == "10.0.0.61"


def test_h3c_ac_resource_only_collect_preserves_static_summary_fields(monkeypatch, tmp_path):
    connection = FakeConnection()
    monkeypatch.setattr(h3c_ac_collect_service.netmiko_connection, "ConnectHandler", lambda **_kwargs: connection)
    database = make_database(tmp_path)
    repository = AcRepository(database)
    ac_uuid = "22222222-2222-4222-8222-222222222222"
    repository.upsert_ac_ap_summary(
        {
            "ac_device_uuid": ac_uuid,
            "total_aps": 82,
            "online_aps": 58,
            "offline_aps": 24,
            "cpu_usage": "16%",
            "memory_usage": "47%",
            "model": "WX-AC",
            "serial_number": "SN-AC",
            "software_version": "Version 7.1",
        }
    )

    collect_h3c_fit_ap_resources(
        make_ac_device(),
        "demo",
        repository=repository,
        paths=PathResolver(tmp_path),
    )

    summary = repository.get_ac_ap_summary(ac_uuid)
    assert summary["total_aps"] == 2
    assert summary["online_aps"] == 2
    assert summary["offline_aps"] == 0
    assert summary["cpu_usage"] == "16%"
    assert summary["memory_usage"] == "47%"
    assert summary["model"] == "WX-AC"
    assert summary["serial_number"] == "SN-AC"
    assert summary["software_version"] == "Version 7.1"


def test_h3c_ac_resource_only_collect_does_not_overwrite_summary_when_ap_all_fails(monkeypatch, tmp_path):
    connection = FakeConnection({"display wlan ap all": RuntimeError("command failed")})
    monkeypatch.setattr(h3c_ac_collect_service.netmiko_connection, "ConnectHandler", lambda **_kwargs: connection)
    database = make_database(tmp_path)
    repository = AcRepository(database)
    ac_uuid = "22222222-2222-4222-8222-222222222222"
    repository.upsert_ac_ap_summary({"ac_device_uuid": ac_uuid, "total_aps": 82, "online_aps": 58, "offline_aps": 24})

    result = collect_h3c_fit_ap_resources(
        make_ac_device(),
        "demo",
        repository=repository,
        paths=PathResolver(tmp_path),
    )

    summary = repository.get_ac_ap_summary(ac_uuid)
    assert result.success is False
    assert summary["total_aps"] == 82
    assert summary["online_aps"] == 58
    assert summary["offline_aps"] == 24


def test_wlan_ap_summary_derives_offline_from_total_minus_online():
    summary = parse_wlan_ap_summary(
        """
Total number of APs: 882
Total number of connected APs: 756
"""
    )

    assert summary["total_aps"] == 882
    assert summary["online_aps"] == 756
    assert summary["offline_aps"] == 126


def test_h3c_ac_collect_service_emits_progress_stages(monkeypatch, tmp_path):
    connection = FakeConnection()
    monkeypatch.setattr(h3c_ac_collect_service.netmiko_connection, "ConnectHandler", lambda **_kwargs: connection)
    messages: list[str] = []

    result = collect_h3c_fit_ap_resources(
        make_ac_device(),
        "demo",
        repository=AcRepository(make_database(tmp_path)),
        paths=PathResolver(tmp_path),
        progress=messages.append,
    )

    assert result.success is True
    assert any("正在连接AC" in message for message in messages)
    assert any("display wlan ap all" in message for message in messages)
    assert any("正在解析FIT-AP资源" in message for message in messages)
    assert any("正在写入数据库" in message for message in messages)
    assert any("更新完成" in message for message in messages)


def test_h3c_ac_collect_service_saves_https_port(monkeypatch, tmp_path):
    connection = FakeConnection()
    monkeypatch.setattr(h3c_ac_collect_service.netmiko_connection, "ConnectHandler", lambda **_kwargs: connection)
    database = make_database(tmp_path)
    device_repository = DeviceRepository(database)
    ac_device = device_repository.create(make_ac_device())

    result = collect_h3c_ac_info(ac_device, "demo", repository=AcRepository(database), paths=PathResolver(tmp_path))

    assert result.success is True
    assert result.https_port == 443
    assert result.https_port_collected is True
    assert result.https_port_persisted is True
    assert result.https_port_error is None
    assert device_repository.get(int(ac_device.id)).https_port == 443


def test_h3c_ac_collect_service_saves_non_default_https_port(monkeypatch, tmp_path):
    connection = FakeConnection({"display ip https": "<AC>display ip https\nHTTPS port: 10443\nOperation status : Enabled\n<AC>"})
    monkeypatch.setattr(h3c_ac_collect_service.netmiko_connection, "ConnectHandler", lambda **_kwargs: connection)
    database = make_database(tmp_path)
    device_repository = DeviceRepository(database)
    ac_device = device_repository.create(make_ac_device())

    result = collect_h3c_ac_info(ac_device, "demo", repository=AcRepository(database), paths=PathResolver(tmp_path))

    assert result.success is True
    assert result.https_port == 10443
    assert result.https_port_collected is True
    assert result.https_port_persisted is True
    assert device_repository.get(int(ac_device.id)).https_port == 10443


def test_h3c_ac_collect_service_reports_https_port_save_failure(monkeypatch, tmp_path):
    connection = FakeConnection({"display ip https": "HTTPS port: 10443\n"})
    monkeypatch.setattr(h3c_ac_collect_service.netmiko_connection, "ConnectHandler", lambda **_kwargs: connection)
    monkeypatch.setattr(h3c_ac_collect_service.DeviceRepository, "update_https_port", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("no such column: https_port")))
    database = make_database(tmp_path)
    device_repository = DeviceRepository(database)
    ac_device = device_repository.create(make_ac_device())

    result = collect_h3c_ac_info(ac_device, "demo", repository=AcRepository(database), paths=PathResolver(tmp_path))

    assert result.success is True
    assert result.https_port == 10443
    assert result.https_port_collected is True
    assert result.https_port_persisted is False
    assert "no such column: https_port" in str(result.https_port_error)
    assert device_repository.get(int(ac_device.id)).https_port is None


def test_https_port_parser_and_url_builder_are_strict():
    assert parse_https_port("HTTPS port: 443") == 443
    assert parse_https_port("HTTPS port: 10443") == 10443
    assert parse_https_port("<AC>display ip https | include port\r\nHTTPS port : 8443\r\n<AC>") == 8443
    assert parse_https_port("\x1b[24D HTTPS port：443") == 443
    assert parse_https_port("HTTP port: 80\nSSH server port: 22") is None
    assert parse_https_port("HTTPS port: 70000") is None
    assert build_https_url("10.122.100.10", 443) == "https://10.122.100.10:443"
    assert build_https_url("2001:db8::10", 443) == "https://[2001:db8::10]:443"
    assert build_https_url("", 443) is None


def test_h3c_ac_collect_service_falls_back_to_full_https_command(monkeypatch, tmp_path):
    connection = FakeConnection({"display ip https": "", "display ip https | include port": "<AC>display ip https | include port\nHTTPS port: 8443\n<AC>"})
    monkeypatch.setattr(h3c_ac_collect_service.netmiko_connection, "ConnectHandler", lambda **_kwargs: connection)
    database = make_database(tmp_path)
    device_repository = DeviceRepository(database)
    ac_device = device_repository.create(make_ac_device())

    result = collect_h3c_ac_info(ac_device, "demo", repository=AcRepository(database), paths=PathResolver(tmp_path))

    assert result.success is True
    assert result.https_port == 8443
    assert connection.commands[-2:] == ["display ip https", "display ip https | include port"]
    assert device_repository.get(int(ac_device.id)).https_port == 8443


def test_h3c_ac_collect_service_keeps_existing_https_port_on_collect_failure(monkeypatch, tmp_path):
    connection = FakeConnection({"display ip https | include port": RuntimeError("unsupported"), "display ip https": ""})
    monkeypatch.setattr(h3c_ac_collect_service.netmiko_connection, "ConnectHandler", lambda **_kwargs: connection)
    database = make_database(tmp_path)
    device_repository = DeviceRepository(database)
    ac_device = device_repository.create(make_ac_device())
    device_repository.update_https_port(int(ac_device.id), 443)

    result = collect_h3c_ac_info(device_repository.get(int(ac_device.id)), "demo", repository=AcRepository(database), paths=PathResolver(tmp_path))

    assert result.success is True
    assert result.https_port is None
    assert device_repository.get(int(ac_device.id)).https_port == 443


def test_ac_page_refresh_enables_open_web_button_when_https_port_exists(tmp_path):
    app()
    context = create_demo_context(PathResolver(tmp_path))
    ac_device = next(device for device in context.repository.list(vendor="H3C", device_type="AC") if device.id is not None)
    context.repository.update_https_port(int(ac_device.id), 443)

    page = AcManagementPage(context.repository, I18n("en_US"), "demo")
    page.refresh_devices()
    process_events_until(lambda: not page._background_jobs)
    process_events_until(lambda: not page._background_jobs)

    assert page.summary_labels["https_port"].text() == "443"
    assert page.open_web_button.isEnabled() is True
    assert build_https_url(page.current_device().ip_address, page.current_device().https_port).endswith(":443")


def test_ac_page_uses_default_https_port_when_db_port_is_empty(tmp_path):
    app()
    context = create_demo_context(PathResolver(tmp_path))

    page = AcManagementPage(context.repository, I18n("en_US"), "demo")
    page.refresh_devices()
    process_events_until(lambda: not page._background_jobs)

    assert page.current_device().https_port is None
    assert page.summary_labels["https_port"].text() == "443 (Default)"
    assert page.open_web_button.isEnabled() is True
    port, source = effective_https_port(page.current_device().https_port)
    assert source == "default"
    assert build_https_url(page.current_device().ip_address, port).endswith(":443")


def test_ac_page_prefers_collected_https_port_when_save_failed(tmp_path):
    app()
    context = create_demo_context(PathResolver(tmp_path))

    page = AcManagementPage(context.repository, I18n("en_US"), "demo")
    page.refresh_devices()
    process_events_until(lambda: not page._background_jobs)
    result = SimpleNamespace(
        success=True,
        error_message=None,
        https_port=10443,
        https_port_collected=True,
        https_port_persisted=False,
        https_port_error="no such column: https_port",
    )

    page._finish_resource_collect(result)
    process_events_until(lambda: not page._background_jobs)

    assert page.current_device().https_port == 10443
    assert page.summary_labels["https_port"].text() == "10443"
    assert page.open_web_button.isEnabled() is True
    assert page.status_label.text() == "Update completed. HTTPS port 10443 was collected, but could not be saved."
    assert build_https_url(page.current_device().ip_address, page.current_device().https_port).endswith(":10443")


def test_h3c_ac_collect_service_validates_commands_before_execution(monkeypatch, tmp_path):
    calls = []
    connection = FakeConnection()
    monkeypatch.setattr(h3c_ac_collect_service.netmiko_connection, "ConnectHandler", lambda **_kwargs: connection)
    monkeypatch.setattr(h3c_ac_collect_service.command_guard, "validate_command_list", lambda commands, context: calls.append((list(commands), context)))
    database = make_database(tmp_path)
    repository = AcRepository(database)

    collect_h3c_fit_ap_resources(make_ac_device(), "demo", repository=repository, paths=PathResolver(tmp_path))

    assert calls == [(["screen-length disable", *RESOURCE_COMMANDS], "ac_fit_ap_resource_collect")]


def test_ac_management_page_column_configuration_exists(tmp_path):
    app()
    context = create_demo_context(PathResolver(tmp_path))
    page = AcManagementPage(context.repository, I18n("en_US"), "demo")

    assert [field for _key, field in FIT_AP_RESOURCE_COLUMNS] == [
        "select",
        "ap_name",
        "apid",
        "ap_ip",
        "ap_mac",
        "model",
        "state_display",
        "group_name",
        "online_time",
        "rid1_channel",
        "rid1_bandwidth",
        "rid1_tx_power",
        "rid2_channel",
        "rid2_bandwidth",
        "rid2_tx_power",
        "site",
        "section_name",
        "belong_type",
        "mileage",
        "location_note",
        "direction",
        "updated_at",
    ]
    resource_fields = [field for _key, field in FIT_AP_RESOURCE_COLUMNS]
    for hidden_field in (
        "rid1_bbssid",
        "rid2_bbssid",
        "serial_number",
        "rid3_channel",
        "rid3_bandwidth",
        "rid3_tx_power",
        "rid3_bbssid",
        "lldp_local_interface",
        "lldp_neighbor_name",
        "lldp_neighbor_mac",
        "lldp_neighbor_interface",
        "lldp_source",
        "lldp_match_status",
        "optical_interface",
        "optical_rx_power",
        "optical_tx_power",
        "optical_collected_at",
        "optical_match_status",
    ):
        assert hidden_field not in resource_fields
    assert [field for _key, field in FIT_AP_OPTICAL_COLUMNS] == [
        "ap_name",
        "ap_mac",
        "site",
        "neighbor_device_name",
        "neighbor_interface",
        "neighbor_rx_power",
        "switch_optical_status",
        "rx_power",
        "optical_alarm_status",
        "updated_at",
    ]
    assert [key for key, _field in FIT_AP_OPTICAL_COLUMNS] == [
        "ac.ap_name",
        "ac.ap_mac",
        "ac.station",
        "ac.indoor_switch",
        "ac.indoor_port",
        "ac.indoor_switch_rx_power",
        "fit_ap.switch_optical_status",
        "ac.ap_side_rx_power",
        "ap.optical_alarm_status",
        "field.updated_at",
    ]
    assert "ac.ap_name_mac" not in [key for key, _field in FIT_AP_OPTICAL_COLUMNS]
    assert [page.optical_concurrency_combo.itemData(index) for index in range(page.optical_concurrency_combo.count())] == [50, 100, 200, 500, 1000]
    assert page.optical_concurrency_combo.currentData() == 1000
    assert page.optical_legend_label.text()
    resource_headers = [page.resources_table.horizontalHeaderItem(index).text() for index in range(page.resources_table.columnCount())]
    assert "field.mac_address" not in resource_headers
    assert "AP_MAC" in resource_headers
    assert "AP_IP" in resource_headers
    assert "SN" not in resource_headers
    assert isinstance(page.resources_table.itemDelegateForColumn(0), CheckBoxOnlyDelegate)
    assert page.tabs.tabText(0) == "Trackside AP Plan"
    assert page.tabs.tabText(1) == "AP Online Overview"
    assert page.tabs.tabText(2) == "FIT-AP Resources"
    assert page.tabs.tabText(3) == "FIT-AP Optical"
    assert page.tabs.tabText(4) == "FIT-AP Extensions"
    assert page.tabs.count() == 5
    assert "Online Vehicle MR" not in [page.tabs.tabText(index) for index in range(page.tabs.count())]


def test_fit_ap_optical_table_colors_no_light_rows(tmp_path):
    app()
    context = create_demo_context(PathResolver(tmp_path))
    page = AcManagementPage(context.repository, I18n("en_US"), "demo")
    page._set_rows(page.optical_table, FIT_AP_OPTICAL_COLUMNS, [{"ap_name": "ap-a", "optical_alarm_status": "no_light"}])

    assert page.optical_table.item(0, 0).background().color().name() == "#6b7280"
    assert page.optical_table.item(0, 0).foreground().color().name() == "#ffffff"
    assert page.optical_table.item(0, 0).textAlignment() == Qt.AlignCenter


def test_mesh_report_generation_button_is_available(tmp_path, monkeypatch):
    app()
    context = create_demo_context(PathResolver(tmp_path))
    messages: list[str] = []
    monkeypatch.setattr("netconsole.ui.pages.ac_management_page.MessageBox.information", lambda _parent, _title, message: messages.append(message))

    page = MeshLogAnalysisPage(context.repository, I18n("en_US"), "demo", PathResolver(tmp_path))

    assert MESH_ANALYSIS_REPORT_ENABLED is True
    assert page.generate_report_button is not None
    assert page.feature_gate.is_enabled("mesh.generate_report")
    assert messages == []
    assert page.report_worker is None


def test_mesh_profile_table_fills_large_profile_list_in_batches(tmp_path, monkeypatch):
    app()
    context = create_demo_context(PathResolver(tmp_path))
    page = MeshLogAnalysisPage(context.repository, I18n("en_US"), "demo", PathResolver(tmp_path))
    page.profiles = [
        MeshMrProfile(str(index), f"MR-{index:03d}", f"mr-{index:03d}", f"mr-{index:03d}")
        for index in range(250)
    ]
    loaded: list[str] = []
    monkeypatch.setattr(page, "_load_profile_by_id", loaded.append)

    page._apply_profiles(None)
    process_events_until(lambda: page.mr_table.item(249, 0) is not None)

    assert page.mr_table.rowCount() == 250
    assert page.mr_table.item(249, 0).text() == "MR-249"
    assert loaded == ["0"]


def test_build_new_online_ap_overview_rows_uses_current_online_without_prior_resource_history():
    current_resources = [
        {
            "collect_run_uuid": "run-2",
            "collected_at": "2026-06-30 10:00:00",
            "site": "Station A",
            "ap_name": "AP-New",
            "ap_mac": "0011-2233-4455",
            "serial_number": "SN-NEW",
            "state": "R/M",
        },
        {
            "collect_run_uuid": "run-2",
            "collected_at": "2026-06-30 10:00:00",
            "site": "Station A",
            "ap_name": "AP-Idle",
            "ap_mac": "0011-2233-4466",
            "serial_number": "SN-IDLE",
            "state": "Idle",
        },
        {
            "collect_run_uuid": "run-2",
            "collected_at": "2026-06-30 10:00:00",
            "site": "Station A",
            "ap_name": "AP-Old-Apid-Changed",
            "ap_mac": "0011-2233-4477",
            "serial_number": "SN-OLD",
            "state": "Run",
            "apid": "999",
        },
    ]
    history_rows = [
        {
            "collect_run_uuid": "run-1",
            "collected_at": "2026-06-29 10:00:00",
            "ap_name": "AP-Old",
            "ap_mac": "0011-2233-4477",
            "serial_number": "SN-OLD",
            "apid": "1",
        }
    ]
    trackside_rows = [
        {
            "site": "Station A",
            "ap_name": "AP-New",
            "ap_mac": "0011-2233-4455",
            "serial_number": "SN-NEW",
            "device_name": "SW-1",
            "interface_name": "GigabitEthernet1/0/1",
        }
    ]

    rows = build_new_online_ap_overview_rows(current_resources, history_rows, trackside_rows)

    assert [row["ap_name"] for row in rows] == ["AP-New"]
    assert rows[0]["device_name"] == "SW-1"
    assert rows[0]["interface_name"] == "GigabitEthernet1/0/1"
    assert [field for _key, field in NEW_ONLINE_AP_OVERVIEW_COLUMNS][:15] == [
        "site",
        "device_name",
        "interface_name",
        "link_status",
        "port_type",
        "description",
        "pvid",
        "vlan",
        "switch_rx_power",
        "switch_optical_status",
        "ap_mac",
        "ap_name",
        "ap_rx_power",
        "ap_optical_status",
        "updated_at",
    ]
    assert [field for _key, field in NEW_ONLINE_AP_OVERVIEW_COLUMNS][-1] == "suggestion"


def test_build_ap_optical_treatment_records_closes_and_opens_by_history():
    trackside_rows = [
        {
            "site": "Station A",
            "ap_uuid": "ap-1",
            "ap_name": "AP-1",
            "ap_mac": "0011-2233-4455",
            "serial_number": "SN-1",
            "device_uuid": "sw-1",
            "device_name": "SW-1",
            "interface_name": "GigabitEthernet1/0/1",
            "ap_rx_power": "-8.00",
            "ap_optical_status": "normal",
            "switch_rx_power": "-21.00",
            "switch_optical_status": "warning",
            "updated_at": "2026-06-30 10:00:00",
        }
    ]
    ap_history = [
        {"id": 1, "ap_uuid": "ap-1", "rx_power": "-22.00", "optical_alarm_status": "warning", "collected_at": "2026-06-30 09:00:00"},
        {"id": 2, "ap_uuid": "ap-1", "rx_power": "-8.00", "optical_alarm_status": "normal", "collected_at": "2026-06-30 09:30:00"},
        {"id": 3, "ap_uuid": "ap-2", "rx_power": "-24.00", "optical_alarm_status": "warning", "collected_at": "2026-06-30 09:00:00"},
    ]
    switch_history = [
        {
            "id": 1,
            "device_uuid": "sw-1",
            "interface_name": "GE1/0/1",
            "rx_power": "-20.00",
            "optical_alarm_status": "failed",
            "collected_at": "2026-06-30 08:00:00",
        }
    ]

    records = build_ap_optical_treatment_records(trackside_rows, ap_history, switch_history)

    assert [field for _key, field in AP_OPTICAL_TREATMENT_RECORD_COLUMNS][0] == "site"
    assert len(records) == 2
    closed = next(row for row in records if row["side"] == "AP侧")
    open_record = next(row for row in records if row["side"] == "交换机侧")
    assert closed["treatment_status"] == TREATMENT_CLOSED_LABEL
    assert closed["completed_at"] == "2026-06-30 09:30:00"
    assert open_record["treatment_status"] == TREATMENT_OPEN_LABEL
    assert open_record["first_found_at"] == "2026-06-30 10:00:00"


def test_trackside_ap_business_treatment_records_complete_ap_identity_and_normalize_interfaces():
    trackside_rows = [
        {
            "site": "Station A",
            "ap_name": "AP-GE",
            "ap_mac": "0011-2233-4455",
            "device_uuid": "sw-1",
            "device_name": "SW-1",
            "interface_name": "GigabitEthernet2/0/1",
            "switch_rx_power": "-8.00",
            "switch_optical_status": "warning",
            "updated_at": "2026-06-30 10:00:00",
        },
        {
            "site": "Station B",
            "ap_name": "AP-BAGG",
            "ap_mac": "00aa-bbcc-ddee",
            "device_uuid": "sw-2",
            "device_name": "SW-2",
            "interface_name": "Bridge-Aggregation121",
            "switch_rx_power": "-8.00",
            "switch_optical_status": "warning",
            "updated_at": "2026-06-30 10:00:00",
        },
    ]
    ap_history = [
        {
            "id": 1,
            "ap_name": "AP-GE",
            "ap_mac": "0011.2233.4455",
            "rx_power": "-24.00",
            "optical_alarm_status": "warning",
            "collected_at": "2026-06-30 09:00:00",
        }
    ]
    switch_history = [
        {
            "id": 1,
            "device_uuid": "sw-1",
            "interface_name": "GE2/0/1",
            "rx_power": "-24.00",
            "optical_alarm_status": "normal",
            "collected_at": "2026-06-30 09:00:00",
        },
        {
            "id": 2,
            "device_uuid": "sw-2",
            "interface_name": "BAGG121",
            "rx_power": "-24.00",
            "optical_alarm_status": "normal",
            "collected_at": "2026-06-30 09:00:00",
        },
    ]
    resources = [
        {"ap_name": "AP-GE", "ap_mac": "0011-2233-4455", "serial_number": "SN-GE"},
        {"ap_name": "AP-BAGG", "ap_mac": "00aa-bbcc-ddee", "serial_number": "SN-BAGG"},
    ]

    records = build_ap_optical_treatment_records(trackside_rows, ap_history, switch_history, resources)

    switch_records = [row for row in records if row["side"] == "交换机侧"]
    assert {row["interface_name"] for row in switch_records} == {"GigabitEthernet2/0/1", "Bridge-Aggregation121"}
    assert {row["serial_number"] for row in switch_records} == {"SN-GE", "SN-BAGG"}
    ap_record = next(row for row in records if row["side"] == "AP侧")
    assert ap_record["ap_name"] == "AP-GE"
    assert ap_record["ap_mac"] == "0011-2233-4455"
    assert ap_record["serial_number"] == "SN-GE"


def test_trackside_ap_business_treatment_records_complete_identity_by_serial_only():
    trackside_rows = [
        {
            "site": "Station A",
            "ap_name": "-",
            "ap_mac": "-",
            "serial_number": "SN-ONLY",
            "device_uuid": "sw-1",
            "device_name": "SW-1",
            "interface_name": "GigabitEthernet2/0/1",
            "switch_rx_power": "-24.00",
            "switch_optical_status": "warning",
            "updated_at": "2026-06-30 10:00:00",
        }
    ]
    resources = [{"serial_number": "SN-ONLY", "ap_name": "AP-SERIAL", "ap_mac": "083b.e9ec.da40"}]

    records = build_ap_optical_treatment_records(trackside_rows, [], [], resources)

    assert len(records) == 1
    assert records[0]["ap_name"] == "AP-SERIAL"
    assert records[0]["ap_mac"] == "083b-e9ec-da40"


def test_trackside_ap_business_treatment_records_use_ap_name_mac_as_fallback():
    trackside_rows = [
        {
            "site": "Station A",
            "ap_name": "30f5-277a-0ea0",
            "ap_mac": "",
            "serial_number": "SN-MAC-NAME",
            "device_uuid": "sw-1",
            "device_name": "SW-1",
            "interface_name": "GigabitEthernet2/0/1",
            "switch_rx_power": "-24.00",
            "switch_optical_status": "warning",
            "updated_at": "2026-06-30 10:00:00",
        }
    ]

    records = build_ap_optical_treatment_records(trackside_rows, [], [], [])

    assert records[0]["ap_name"] == "30f5-277a-0ea0"
    assert records[0]["ap_mac"] == "30f5-277a-0ea0"


def test_trackside_ap_business_treatment_records_use_offline_ledger_by_serial():
    trackside_rows = [
        {
            "site": "Station A",
            "ap_name": "-",
            "ap_mac": "-",
            "serial_number": "SN-OFFLINE",
            "device_uuid": "sw-1",
            "device_name": "SW-1",
            "interface_name": "GigabitEthernet2/0/1",
            "switch_rx_power": "-24.00",
            "switch_optical_status": "warning",
            "updated_at": "2026-06-30 10:00:00",
        }
    ]
    offline_ledger_rows = [
        {"site": "Station A", "ap_name": "AP-OFFLINE", "ap_mac": "083b.e9ec.da40", "serial_number": "SN-OFFLINE"}
    ]

    records = build_ap_optical_treatment_records(trackside_rows, [], [], [], [], offline_ledger_rows=offline_ledger_rows)

    assert records[0]["ap_name"] == "AP-OFFLINE"
    assert records[0]["ap_mac"] == "083b-e9ec-da40"


def test_trackside_ap_business_treatment_records_use_offline_ledger_by_switch_interface():
    trackside_rows = [
        {
            "site": "Station A",
            "ap_name": "-",
            "ap_mac": "-",
            "serial_number": "",
            "device_uuid": "sw-1",
            "device_name": "SW-1",
            "interface_name": "GigabitEthernet2/0/1",
            "switch_rx_power": "-24.00",
            "switch_optical_status": "warning",
            "updated_at": "2026-06-30 10:00:00",
        }
    ]
    offline_ledger_rows = [
        {
            "site": "Station A",
            "ap_name": "AP-PORT",
            "ap_mac": "083be9ecda40",
            "serial_number": "SN-PORT",
            "historical_switch_name": "SW-1",
            "historical_switch_interface": "GE2/0/1",
        }
    ]

    records = build_ap_optical_treatment_records(trackside_rows, [], [], [], [], offline_ledger_rows=offline_ledger_rows)

    assert records[0]["ap_name"] == "AP-PORT"
    assert records[0]["ap_mac"] == "083b-e9ec-da40"
    assert records[0]["serial_number"] == "SN-PORT"


def test_trackside_ap_business_treatment_records_ignore_unmatched_switch_history():
    records = build_ap_optical_treatment_records(
        [],
        [],
        [{"device_uuid": "sw-ordinary", "interface_name": "GE1/0/1", "rx_power": "-24", "optical_alarm_status": "warning"}],
        [],
        [],
        offline_ledger_rows=[],
    )

    assert records == []


def test_trackside_ap_business_export_includes_new_online_and_treatment_sheets(tmp_path):
    from openpyxl import load_workbook

    export_path = tmp_path / "trackside_full_export.xlsx"
    i18n = I18n("zh_CN")

    export_trackside_ap_business_xlsx(
        export_path,
        [],
        TRACKSIDE_AP_BUSINESS_COLUMNS,
        [i18n.t(key) for key, _field in TRACKSIDE_AP_BUSINESS_COLUMNS],
        ap_online_overview_rows=[],
        ap_online_overview_columns=AP_ONLINE_OVERVIEW_COLUMNS,
        ap_online_overview_headers=[i18n.t(key) for key, _field in AP_ONLINE_OVERVIEW_COLUMNS],
        new_online_ap_rows=[{"site": "Station A", "ap_name": "AP-New"}],
        new_online_ap_columns=NEW_ONLINE_AP_OVERVIEW_COLUMNS,
        new_online_ap_headers=[i18n.t(key) for key, _field in NEW_ONLINE_AP_OVERVIEW_COLUMNS],
        new_online_ap_sheet_title=i18n.t("trackside.export.sheet_new_online_ap_overview"),
        ap_optical_treatment_rows=[
            {
                "site": "Station B",
                "ap_name": "AP-3",
                "device_name": "SW-2",
                "interface_name": "GigabitEthernet2/0/1",
                "side": "AP侧",
                "treatment_status": TREATMENT_OPEN_LABEL,
            },
            {
                "site": "Station A",
                "ap_name": "AP-2",
                "device_name": "SW-1",
                "interface_name": "GigabitEthernet2/0/10",
                "side": "AP侧",
                "treatment_status": TREATMENT_OPEN_LABEL,
            },
            {
                "site": "Station A",
                "ap_name": "AP-1",
                "ap_mac": "0011-2233-4455",
                "device_name": "SW-1",
                "interface_name": "GigabitEthernet2/0/9",
                "side": "AP侧",
                "treatment_status": TREATMENT_OPEN_LABEL,
            },
        ],
        ap_optical_treatment_columns=AP_OPTICAL_TREATMENT_RECORD_COLUMNS,
        ap_optical_treatment_headers=[i18n.t(key) for key, _field in AP_OPTICAL_TREATMENT_RECORD_COLUMNS],
        ap_optical_treatment_sheet_title=i18n.t("trackside.export.sheet_ap_optical_treatment"),
        offline_ap_stats={field: 0 for _key, field in OFFLINE_AP_STATS_COLUMNS},
        offline_ap_ledger_rows=[],
        offline_ap_stats_headers=offline_ap_headers(OFFLINE_AP_STATS_COLUMNS),
        offline_ap_ledger_headers=offline_ap_headers(OFFLINE_AP_LEDGER_COLUMNS),
    )

    workbook = load_workbook(export_path)
    assert workbook.sheetnames == [
        "轨旁AP业务",
        "当前异常光衰",
        "AP上线情况概览",
        "新增上线AP概览",
        "AP光衰处理记录",
        "AP离线情况",
        "离线AP台账",
        "交换机光模块统计",
    ]
    assert workbook["新增上线AP概览"]["A2"].value == "Station A"
    treatment_sheet = workbook["AP光衰处理记录"]
    assert treatment_sheet.cell(row=1, column=treatment_sheet.max_column).value == "处理完成时间"
    assert [treatment_sheet.cell(row=row, column=1).value for row in range(2, 5)] == ["Station A", "Station A", "Station B"]
    assert [treatment_sheet.cell(row=row, column=7).value for row in range(2, 5)] == [
        "GigabitEthernet2/0/9",
        "GigabitEthernet2/0/10",
        "GigabitEthernet2/0/1",
    ]
    assert treatment_sheet["B2"].value == "AP-1"
    assert treatment_sheet["C2"].value == "0011-2233-4455"
    assert treatment_sheet["N2"].value == TREATMENT_OPEN_LABEL
    assert treatment_sheet["P2"].value is None
    assert treatment_sheet["A1"].fill.fgColor.rgb == "00DBEAFE"
    assert treatment_sheet["A2"].fill.fgColor.rgb == "00FEE2E2"


def test_trackside_export_omits_ap_port_change_columns_and_sheet(tmp_path):
    from openpyxl import load_workbook

    export_path = tmp_path / "trackside_without_ap_port_change.xlsx"
    i18n = I18n("zh_CN")
    rows = [
        {
            "site": "Station A",
            "device_name": "SW-1",
            "interface_name": "GigabitEthernet2/0/6",
            "link_status": "UP",
            "switch_rx_power": "-8",
            "switch_optical_status": "normal",
            "ap_mac": "0011-2233-4455",
            "ap_name": "AP-1",
            "ap_rx_power": "-8",
            "ap_optical_status": "normal",
            "ap_port_change": "N/A GigabitEthernet2/0/6 -> SW-1 GigabitEthernet2/0/6",
            "ap_port_change_reason": "交换机变化",
            "previous_switch": "N/A",
            "previous_interface": "GigabitEthernet2/0/6",
            "current_switch": "SW-1",
            "current_interface": "GigabitEthernet2/0/6",
            "history_compared_at": "2026-07-04T15:59:07",
        }
    ]

    export_trackside_ap_business_xlsx(
        export_path,
        rows,
        TRACKSIDE_AP_BUSINESS_EXPORT_COLUMNS,
        [i18n.t(key) for key, _field in TRACKSIDE_AP_BUSINESS_EXPORT_COLUMNS],
    )

    workbook = load_workbook(export_path)
    assert "AP端口变化" not in workbook.sheetnames
    headers = [cell.value for cell in workbook["轨旁AP业务"][1]]
    for forbidden in ("AP端口变化", "AP端口变化原因", "上次交换机", "上次端口", "本次交换机", "本次端口", "历史对比时间"):
        assert forbidden not in headers


def test_trackside_ap_business_export_adds_current_optical_abnormal_sheet(tmp_path):
    from openpyxl import load_workbook

    export_path = tmp_path / "trackside_current_abnormal.xlsx"
    i18n = I18n("zh_CN")
    rows = [
        {
            "site": "Station A",
            "device_name": "SW-1",
            "interface_name": "GigabitEthernet1/0/1",
            "link_status": "UP",
            "switch_rx_power": "-8",
            "switch_optical_status": "normal",
            "ap_name": "AP-Normal",
            "ap_rx_power": "-8",
            "ap_optical_status": "normal",
        },
        {
            "site": "Station A",
            "device_name": "SW-1",
            "interface_name": "GigabitEthernet1/0/2",
            "link_status": "UP",
            "switch_rx_power": "-24",
            "switch_optical_status": "warning",
            "ap_name": "AP-Warning",
            "ap_rx_power": "-8",
            "ap_optical_status": "normal",
        },
        {
            "site": "Station B",
            "device_name": "SW-2",
            "interface_name": "GigabitEthernet1/0/3",
            "link_status": "UP",
            "switch_rx_power": "-8",
            "switch_optical_status": "normal",
            "ap_name": "AP-NoLight",
            "ap_rx_power": "-40",
            "ap_optical_status": "no_light",
            "ap_side_has_data": True,
        },
        {
            "site": "Station C",
            "device_name": "SW-3",
            "interface_name": "GigabitEthernet1/0/4",
            "link_status": "DOWN",
            "switch_rx_power": "-36.96",
            "switch_optical_status": "no_light",
            "ap_name": "AP-Offline",
            "ap_mac": "30f5-2787-91c0",
            "ap_rx_power": "-7.99",
            "ap_optical_status": "offline",
            "is_ap_offline": True,
        },
        {
            "site": "Station D",
            "device_name": "SW-4",
            "interface_name": "GigabitEthernet1/0/5",
            "link_status": "DOWN",
            "switch_rx_power": "-36.96",
            "switch_optical_status": "no_light",
            "ap_mac": "-",
            "ap_name": "-",
            "ap_rx_power": "-",
            "ap_optical_status": "-",
        },
    ]

    export_trackside_ap_business_xlsx(
        export_path,
        rows,
        TRACKSIDE_AP_BUSINESS_COLUMNS,
        [i18n.t(key) for key, _field in TRACKSIDE_AP_BUSINESS_COLUMNS],
    )

    workbook = load_workbook(export_path)
    assert workbook.sheetnames[:2] == ["轨旁AP业务", "当前异常光衰"]
    source_sheet = workbook["轨旁AP业务"]
    abnormal_sheet = workbook["当前异常光衰"]
    source_headers = [cell.value for cell in source_sheet[1]]
    abnormal_headers = [cell.value for cell in abnormal_sheet[1]]
    assert abnormal_headers == [*source_headers, "异常原因", "异常侧", "异常等级", "异常说明"]
    assert [abnormal_sheet.cell(row=row, column=3).value for row in range(2, abnormal_sheet.max_row + 1)] == ["GigabitEthernet1/0/2", "GigabitEthernet1/0/4"]
    reason_column = abnormal_headers.index("异常原因") + 1
    assert abnormal_sheet.cell(row=3, column=reason_column).value == "AP离线"
    assert abnormal_sheet["A2"].fill.fgColor.rgb == source_sheet["A3"].fill.fgColor.rgb == "00FEF9C3"
    assert abnormal_sheet["A1"].font.bold
    assert abnormal_sheet.freeze_panes == "A2"
    assert abnormal_sheet.auto_filter.ref == abnormal_sheet.dimensions
    assert abnormal_sheet.column_dimensions["A"].width == source_sheet.column_dimensions["A"].width


def test_trackside_ap_business_export_empty_current_optical_abnormal_sheet(tmp_path):
    from openpyxl import load_workbook

    export_path = tmp_path / "trackside_no_current_abnormal.xlsx"
    i18n = I18n("zh_CN")

    export_trackside_ap_business_xlsx(
        export_path,
        [
            {
                "site": "Station A",
                "device_name": "SW-1",
                "interface_name": "GigabitEthernet1/0/1",
                "link_status": "UP",
                "switch_rx_power": "-8",
                "switch_optical_status": "normal",
                "ap_name": "AP-Normal",
                "ap_rx_power": "-8",
                "ap_optical_status": "normal",
            },
            {
                "site": "Station B",
                "device_name": "SW-2",
                "interface_name": "GigabitEthernet1/0/2",
                "link_status": "DOWN",
                "switch_rx_power": "-36.96",
                "switch_optical_status": "no_light",
                "ap_name": "-",
                "ap_rx_power": "-",
                "ap_optical_status": "-",
            }
        ],
        TRACKSIDE_AP_BUSINESS_COLUMNS,
        [i18n.t(key) for key, _field in TRACKSIDE_AP_BUSINESS_COLUMNS],
    )

    sheet = load_workbook(export_path)["当前异常光衰"]
    assert sheet.max_row == 2
    assert sheet["A2"].value == "当前无异常光衰（已排除无 AP 绑定或 AP 未离线的无光端口）"


def test_current_optical_abnormal_includes_ap_offline_but_excludes_unbound_no_light():
    assert is_current_optical_abnormal_row(
        {
            "link_status": "DOWN",
            "switch_rx_power": "-36.96",
            "switch_optical_status": "no_light",
            "ap_mac": "30f5-2787-91c0",
            "ap_name": "30f5-2787-91c0",
            "ap_rx_power": "-7.99",
            "ap_optical_status": "offline",
        }
    )
    assert not is_current_optical_abnormal_row(
        {
            "link_status": "DOWN",
            "switch_rx_power": "-36.96",
            "switch_optical_status": "no_light",
            "ap_mac": "-",
            "ap_name": "-",
            "ap_rx_power": "-",
            "ap_optical_status": "-",
        }
    )
    assert not is_current_optical_abnormal_row(
        {
            "link_status": "DOWN",
            "switch_rx_power": "-36.96",
            "switch_optical_status": "no_light",
            "ap_mac": "30f5-xxxx-yyyy",
            "ap_name": "30f5-xxxx-yyyy",
            "ap_optical_status": "normal",
        }
    )
    assert is_current_optical_abnormal_row(
        {
            "ap_mac": "30f5-2787-afc0",
            "ap_name": "30f5-2787-afc0",
            "ap_rx_power": "-22.01",
            "ap_optical_status": "alarm",
            "ap_side_has_data": True,
        }
    )


def test_fit_ap_resource_table_prioritizes_ap_name_over_ap_mac(tmp_path):
    app()
    context = create_demo_context(PathResolver(tmp_path))
    page = AcManagementPage(context.repository, I18n("en_US"), "demo")
    page._set_rows(
        page.resources_table,
        FIT_AP_RESOURCE_COLUMNS,
        [{"ap_name": "Station-Very-Long-AP-Name-001", "ap_mac": "bc5a-3457-cbe0", "ap_ip": "10.1.1.1"}],
    )
    fields = [field for _key, field in FIT_AP_RESOURCE_COLUMNS]
    ap_name_column = fields.index("ap_name")
    ap_mac_column = fields.index("ap_mac")
    select_column = fields.index("select")
    check_item = page.resources_table.item(0, 0)

    assert page.resources_table.cellWidget(0, 0) is None
    assert check_item is not None
    assert check_item.flags() & Qt.ItemIsUserCheckable
    assert check_item.text() == ""
    assert check_item.textAlignment() == Qt.AlignmentFlag.AlignCenter
    assert isinstance(page.resources_table.itemDelegateForColumn(0), CheckBoxOnlyDelegate)
    assert page.resources_table.horizontalHeader().sectionResizeMode(ap_name_column) == QHeaderView.Interactive
    assert page.resources_table.horizontalHeader().sectionResizeMode(ap_mac_column) == QHeaderView.Interactive
    assert page.resources_table.columnWidth(select_column) <= 54
    assert page.resources_table.columnWidth(ap_name_column) >= 130
    assert page.resources_table.columnWidth(ap_mac_column) >= 130
    assert page.resources_table.verticalHeader().defaultSectionSize() == 36
    assert page.resources_table.rowHeight(0) == 36


def test_fit_ap_resource_search_group_and_state_filters(tmp_path):
    app()
    database = make_database(tmp_path)
    device_repository = DeviceRepository(database)
    ac = device_repository.create(make_ac_device())
    repository = AcRepository(database)
    repository.replace_fit_ap_resources(
        ac.device_uuid,
        [
            {
                "ap_uuid": "ap-1",
                "ap_name": "Station-A-AP-01",
                "ap_mac": "30f5-277a-e520",
                "group_name": "default-group",
                "state": "Run",
                "state_display": "Run",
            },
            {
                "ap_uuid": "ap-2",
                "ap_name": "Station-B-AP-Idle",
                "ap_mac": "083b-e9e8-1000",
                "group_name": "trackside",
                "state": "I",
                "state_display": "Idle",
            },
            {
                "ap_uuid": "ap-3",
                "ap_name": "Station-C-AP-Image",
                "ap_mac": "083b-e9e8-2000",
                "group_name": "trackside",
                "state": "IL",
                "state_display": "ImageLoad",
            },
        ],
    )
    page = AcManagementPage(device_repository, I18n("en_US"), "demo")
    process_events_until(lambda: not page._background_jobs)

    assert not hasattr(page, "batch_edit_button")
    assert page.resource_search_input.placeholderText() == "Search AP name / AP_MAC"

    page.resource_search_input.setText("station-b")
    assert [row["ap_uuid"] for row in page.filtered_resource_rows()] == ["ap-2"]

    page.resource_search_input.setText("083B-E9E8")
    assert [row["ap_uuid"] for row in page.filtered_resource_rows()] == ["ap-2", "ap-3"]

    page.resource_group_filter.setCurrentIndex(page.resource_group_filter.findData("trackside"))
    assert [row["ap_uuid"] for row in page.filtered_resource_rows()] == ["ap-2", "ap-3"]

    page.resource_state_filter.setCurrentIndex(page.resource_state_filter.findData("__offline__"))
    assert [row["ap_uuid"] for row in page.filtered_resource_rows()] == ["ap-2"]

    page.resource_search_input.clear()
    assert [row["ap_uuid"] for row in page.filtered_resource_rows()] == ["ap-2"]

    page.resource_state_filter.setCurrentIndex(page.resource_state_filter.findData(""))
    page.resource_group_filter.setCurrentIndex(page.resource_group_filter.findData(""))
    assert [row["ap_uuid"] for row in page.filtered_resource_rows()] == ["ap-1", "ap-2", "ap-3"]


def test_fit_ap_resource_selection_survives_filtering(tmp_path):
    app()
    database = make_database(tmp_path)
    device_repository = DeviceRepository(database)
    ac = device_repository.create(make_ac_device())
    repository = AcRepository(database)
    repository.replace_fit_ap_resources(
        ac.device_uuid,
        [
            {"ap_uuid": "ap-1", "ap_name": "AP-A", "ap_mac": "30f5-277a-e520", "state": "Run"},
            {"ap_uuid": "ap-2", "ap_name": "AP-B", "ap_mac": "083b-e9e8-1000", "state": "I"},
        ],
    )
    page = AcManagementPage(device_repository, I18n("en_US"), "demo")
    page.resources_table.item(0, 0).setCheckState(Qt.Checked)
    page.update_selection_state()

    page.resource_search_input.setText("AP-B")
    assert page.selected_ap_names() == ["ap-1"]

    page.resource_search_input.clear()
    assert page.resources_table.item(0, 0).checkState() == Qt.Checked
    assert page.selected_ap_names() == ["ap-1"]

    page.invert_selection()
    assert not is_checked_value(page.resources_table.item(0, 0).checkState())
    assert is_checked_value(page.resources_table.item(1, 0).checkState())
    assert page.selected_ap_names() == ["ap-2"]

    page._set_all_checked(True)
    assert all(is_checked_value(page.resources_table.item(row, 0).checkState()) for row in range(page.resources_table.rowCount()))
    assert page.selected_ap_names() == ["ap-1", "ap-2"]

    page.clear_selection()
    assert all(not is_checked_value(page.resources_table.item(row, 0).checkState()) for row in range(page.resources_table.rowCount()))
    assert page.selected_ap_names() == []


def test_fit_ap_resource_table_double_click_does_not_open_detail(tmp_path, monkeypatch):
    app()
    context = create_demo_context(PathResolver(tmp_path))
    page = AcManagementPage(context.repository, I18n("en_US"), "demo")
    page._set_rows(page.resources_table, FIT_AP_RESOURCE_COLUMNS, [{"ap_uuid": "ap-1", "ap_name": "AP-A"}])
    opened: list[int] = []
    monkeypatch.setattr(page, "open_ap_detail", lambda row: opened.append(row))

    page.resources_table.doubleClicked.emit(page.resources_table.model().index(0, 0))
    page.resources_table.doubleClicked.emit(page.resources_table.model().index(0, 1))

    assert opened == []


def test_fit_ap_resource_checkbox_delegate_toggles_check_state(tmp_path):
    app()
    context = create_demo_context(PathResolver(tmp_path))
    page = AcManagementPage(context.repository, I18n("en_US"), "demo")
    page._set_rows(page.resources_table, FIT_AP_RESOURCE_COLUMNS, [{"ap_uuid": "ap-1", "ap_name": "AP-A"}])
    delegate = page.resources_table.itemDelegateForColumn(0)
    model = page.resources_table.model()
    index = model.index(0, 0)

    class EventStub:
        def __init__(self, event_type, key=None, button=Qt.MouseButton.LeftButton):
            self._event_type = event_type
            self._key = key
            self._button = button

        def type(self):
            return self._event_type

        def key(self):
            return self._key

        def button(self):
            return self._button

    assert isinstance(delegate, CheckBoxOnlyDelegate)
    assert is_checked_value(Qt.CheckState.Checked)
    assert is_checked_value(2)
    assert not is_checked_value(None)
    assert page.resources_table.item(0, 0).checkState() == Qt.CheckState.Unchecked

    assert delegate.editorEvent(EventStub(QEvent.Type.MouseButtonRelease), model, None, index)
    assert page.resources_table.item(0, 0).checkState() == Qt.CheckState.Checked

    assert delegate.editorEvent(EventStub(QEvent.Type.KeyPress, Qt.Key.Key_Space), model, None, index)
    assert page.resources_table.item(0, 0).checkState() == Qt.CheckState.Unchecked

    assert not delegate.editorEvent(EventStub(QEvent.Type.MouseButtonRelease, button=Qt.MouseButton.RightButton), model, None, index)
    assert page.resources_table.item(0, 0).checkState() == Qt.CheckState.Unchecked


def test_fit_ap_optical_table_shows_switch_status_and_ap_alarm_separately(tmp_path):
    app()
    context = create_demo_context(PathResolver(tmp_path))
    page = AcManagementPage(context.repository, I18n("en_US"), "demo")
    page._set_rows(
        page.optical_table,
        FIT_AP_OPTICAL_COLUMNS,
        [
            {
                "ap_name": "ap-a",
                "neighbor_rx_power": "-45.00",
                "rx_power": "-10.00",
                "rx_low_alarm": "-20.00",
                "rx_low_warning": "-15.00",
            }
        ],
    )

    assert page.optical_table.item(0, 6).text() == "No Light"
    assert page.optical_table.item(0, 8).text() == "Normal"
    assert page.optical_table.item(0, 0).background().color().name() == "#6b7280"
    assert page.optical_table.item(0, 0).foreground().color().name() == "#ffffff"


def test_fit_ap_optical_table_color_uses_ap_alarm_when_more_severe(tmp_path):
    app()
    context = create_demo_context(PathResolver(tmp_path))
    page = AcManagementPage(context.repository, I18n("en_US"), "demo")
    page._set_rows(
        page.optical_table,
        FIT_AP_OPTICAL_COLUMNS,
        [
            {
                "ap_name": "ap-a",
                "neighbor_rx_power": "-8.00",
                "rx_power": "-20.00",
                "rx_low_alarm": "-19.00",
                "rx_low_warning": "-16.99",
            }
        ],
    )

    assert page.optical_table.item(0, 6).text() == "Normal"
    assert page.optical_table.item(0, 8).text() == "Alarm"
    assert page.optical_table.item(0, 0).background().color().name() == "#f87171"
    assert page.optical_table.item(0, 0).foreground().color().name() == "#ffffff"


def test_fit_ap_optical_thread_accepts_concurrency():
    thread = FitApOpticalCollectThread(make_ac_device(), "demo", 200, None)

    assert thread.concurrency == 200


def test_ac_collect_threads_expose_progress_and_cancel():
    resource_thread = AcResourceCollectThread(make_ac_device(), "demo", parent=None)
    optical_thread = FitApOpticalCollectThread(make_ac_device(), "demo", 200, parent=None)

    resource_thread.cancel()
    optical_thread.cancel()

    assert resource_thread._cancel_requested is True
    assert optical_thread._cancel_requested is True
    assert hasattr(resource_thread, "progress")
    assert hasattr(optical_thread, "progress")


def test_ac_management_update_running_state_disables_mutating_buttons(tmp_path):
    app()
    database = make_database(tmp_path)
    device_repository = DeviceRepository(database)
    device_repository.create(make_ac_device())
    page = AcManagementPage(device_repository, I18n("en_US"), "demo")

    page._set_update_running(True, "Updating...")

    assert not page.update_progress.isHidden()
    assert not page.cancel_update_button.isHidden()
    assert page.status_label.text() == "Updating..."
    assert not page.refresh_button.isEnabled()
    assert not page.refresh_optical_button.isEnabled()
    assert not page.import_button.isEnabled()
    assert not page.batch_delete_button.isEnabled()

    page._set_update_running(False)

    assert page.update_progress.isHidden()
    assert page.cancel_update_button.isHidden()
    assert page.refresh_button.isEnabled()
    assert page.refresh_optical_button.isEnabled()


def test_sort_fit_ap_optical_rows_orders_neighbor_and_interface_logically():
    rows = [
        {"ap_name": "ap-z", "neighbor_device_name": "-", "neighbor_interface": "GigabitEthernet2/0/1"},
        {"ap_name": "ap-c", "neighbor_device_name": "HX_1", "neighbor_interface": "GigabitEthernet2/0/10"},
        {"ap_name": "ap-a", "neighbor_device_name": "HX_1", "neighbor_interface": "GigabitEthernet2/0/1"},
        {"ap_name": "ap-b", "neighbor_device_name": "HX_1", "neighbor_interface": "GigabitEthernet2/0/2"},
        {"ap_name": "ap-d", "neighbor_device_name": "SW01", "neighbor_interface": "GigabitEthernet1/0/1"},
    ]

    assert [row["ap_name"] for row in sort_fit_ap_optical_rows(rows)] == ["ap-a", "ap-b", "ap-c", "ap-d", "ap-z"]


def test_filter_fit_ap_optical_rows_supports_text_and_status_filters():
    rows = [
        {"ap_name": "AP-A", "ap_mac": "0011-2233-4455", "site": "S1", "lldp_neighbor": "HX_1", "neighbor_device_name": "Core-A", "rx_power": "-10.00", "rx_low_alarm": "-20.00", "rx_low_warning": "-15.00", "optical_alarm_status": "normal"},
        {"ap_name": "AP-B", "ap_mac": "aabb-ccdd-eeff", "site": "S2", "lldp_neighbor": "HX_2", "neighbor_device_name": "Access-B", "rx_power": "-14.00", "rx_low_alarm": "-20.00", "rx_low_warning": "-15.00", "optical_alarm_status": "notice"},
    ]

    assert [row["ap_name"] for row in filter_fit_ap_optical_rows(rows, {"ap_name": "ap-a"})] == ["AP-A"]
    assert [row["ap_name"] for row in filter_fit_ap_optical_rows(rows, {"site": "s2"})] == ["AP-B"]
    assert [row["ap_name"] for row in filter_fit_ap_optical_rows(rows, {"optical_alarm_status": "notice"})] == ["AP-B"]


def test_site_filter_items_are_generated_from_rows():
    items = build_site_filter_items([{"site": "03横溪站"}, {"site": "01小洋江站"}, {"site": "03横溪站"}], "全部")

    assert items == [("全部", ""), ("01小洋江站", "01小洋江站"), ("03横溪站", "03横溪站")]


def test_ac_management_site_combo_filters_optical_rows(tmp_path):
    app()
    context = create_demo_context(PathResolver(tmp_path))
    page = AcManagementPage(context.repository, I18n("zh_CN"), "demo")
    page.optical_rows = [
        {"ap_name": "AP-A", "site": "01小洋江站", "optical_alarm_status": "normal"},
        {"ap_name": "AP-B", "site": "02云龙火车站站", "optical_alarm_status": "warning"},
    ]
    page._set_site_filter_items(page.optical_rows)

    assert page.optical_site_filter.itemText(0) == "全部"
    page.optical_site_filter.setCurrentIndex(page.optical_site_filter.findData("02云龙火车站站"))

    assert [row["ap_name"] for row in page.filtered_optical_rows()] == ["AP-B"]


def test_optical_context_menu_contains_view_details_without_insert_action_error(monkeypatch, tmp_path):
    app()
    context = create_demo_context(PathResolver(tmp_path))
    page = AcManagementPage(context.repository, I18n("en_US"), "demo")
    page._set_rows(page.optical_table, FIT_AP_OPTICAL_COLUMNS, [{"ap_name": "AP-A", "optical_alarm_status": "normal"}])

    menu = page.build_optical_context_menu(0, 0)
    captured = [action.text() for action in menu.actions() if action.text()]

    assert "View Details" in captured
    assert "Copy Cell" in captured
    assert "Copy Row" in captured


def test_resource_context_menu_contains_scoped_ap_optical_refresh(tmp_path):
    app()
    context = create_demo_context(PathResolver(tmp_path))
    page = AcManagementPage(context.repository, I18n("en_US"), "demo")
    page.resource_rows = [{"ap_uuid": "ap-1", "ap_name": "AP-A", "ap_mac": "0011-2233-4455"}]
    page.apply_resource_pagination()

    menu = page.build_resource_context_menu(0, 1)
    captured = [action.text() for action in menu.actions() if action.text()]

    assert "Update This AP Optical" in captured
    assert "View Details" in captured
    assert "打开外部终端" in captured
    assert captured[:3] == ["View Details", "打开外部终端", "Update This AP Optical"]


def test_fit_ap_resource_external_terminal_uses_existing_launcher(tmp_path, monkeypatch):
    app()
    context = create_demo_context(PathResolver(tmp_path))
    page = AcManagementPage(context.repository, I18n("zh_CN"), "demo")
    page.resource_rows = [{"ap_uuid": "ap-1", "ap_name": "AP-A", "ap_ip": "10.0.0.61", "ap_mac": "0011-2233-4455"}]
    page.apply_resource_pagination()
    config = ExternalTerminalConfig(terminal_type="putty", exe_path=r"C:\Tools\putty.exe", include_password=True)
    captured: dict[str, object] = {}

    monkeypatch.setattr("netconsole.ui.pages.ac_management_page.available_external_terminal_configs", lambda _settings: [config])

    def fake_launch(device, selected_config):
        captured["device"] = device
        captured["config"] = selected_config
        return ExternalTerminalLaunchResult(True, "started", [])

    monkeypatch.setattr("netconsole.ui.pages.ac_management_page.launch_external_terminal", fake_launch)

    page.open_resource_ap_external_terminal(0)

    device = captured["device"]
    assert captured["config"] is config
    assert device.name == "AP-A"
    assert device.primary_address == "10.0.0.61"
    assert device.ssh_enabled == 0
    assert device.telnet_enabled == 1
    assert device.telnet_port == 23
    assert device.telnet_username == ""
    assert device.telnet_password == "h3capadmin"
    assert "h3capadmin" not in page.status_label.text()
    assert page.status_label.text() == "已打开外部终端：10.0.0.61"


def test_fit_ap_resource_external_terminal_requires_ap_ip(tmp_path, monkeypatch):
    app()
    context = create_demo_context(PathResolver(tmp_path))
    page = AcManagementPage(context.repository, I18n("zh_CN"), "demo")
    page.resource_rows = [{"ap_uuid": "ap-1", "ap_name": "AP-A", "ap_ip": "", "ap_mac": "0011-2233-4455"}]
    page.apply_resource_pagination()
    messages: list[str] = []
    monkeypatch.setattr("netconsole.ui.pages.ac_management_page.MessageBox.information", lambda _parent, _title, message: messages.append(message))
    monkeypatch.setattr("netconsole.ui.pages.ac_management_page.launch_external_terminal", lambda *_args, **_kwargs: pytest.fail("launcher should not be called"))

    page.open_resource_ap_external_terminal(0)

    assert messages == ["当前 AP 没有 IP，无法打开外部终端"]
    assert page.status_label.text() == "当前 AP 没有 IP，无法打开外部终端"


def test_fit_ap_optical_filters_do_not_include_ap_mac(tmp_path):
    app()
    context = create_demo_context(PathResolver(tmp_path))
    page = AcManagementPage(context.repository, I18n("en_US"), "demo")

    assert not hasattr(page, "optical_ap_mac_filter")
    assert not hasattr(page, "optical_alarm_filter")


def test_enrich_fit_ap_optical_rows_adds_ap_mac_and_station_from_resources():
    rows = [{"ap_name": "AP-A", "site": None, "optical_alarm_status": "normal"}]
    resources = [{"ap_name": "AP-A", "ap_mac": "0011-2233-4455", "site": "Station A"}]

    enriched = enrich_fit_ap_optical_rows(rows, resources)

    assert enriched[0]["ap_mac"] == "0011-2233-4455"
    assert enriched[0]["site"] == "Station A"


def test_enrich_fit_ap_optical_rows_uses_unassigned_and_filters_invalid_neighbor():
    rows = [{"ap_name": "AP-A", "neighbor_device_name": "* -- -- Nearest customer bridge"}]

    enriched = enrich_fit_ap_optical_rows(rows, [])

    assert enriched[0]["site"] == "未归属"
    assert enriched[0]["neighbor_device_name"] is None


def test_clear_optical_filters_restores_all_rows(tmp_path):
    app()
    context = create_demo_context(PathResolver(tmp_path))
    page = AcManagementPage(context.repository, I18n("en_US"), "demo")
    page.optical_rows = [
        {"ap_name": "AP-A", "optical_alarm_status": "normal"},
        {"ap_name": "AP-B", "optical_alarm_status": "warning"},
    ]
    page._set_site_filter_items(page.optical_rows)
    page.optical_ap_filter.setText("AP-A")
    assert page.optical_table.rowCount() == 1

    page.clear_optical_filters()

    assert page.optical_table.rowCount() == 2
    assert page.optical_ap_filter.text() == ""
    assert page.optical_site_filter.currentData() == ""


def test_evaluate_fit_ap_row_status_includes_neighbor_rx_power():
    assert evaluate_fit_ap_row_status({"optical_alarm_status": "normal", "neighbor_rx_power": "-45.00"}) == "no_light"
    assert (
        evaluate_fit_ap_row_status(
            {"rx_power": "-10.00", "rx_low_alarm": "-20.00", "rx_low_warning": "-15.00", "neighbor_rx_power": "-25.00"},
            {"rx_power": "-25.00", "tx_power": "-5.00", "rx_low_alarm": "-20.00", "rx_high_alarm": "0.00", "tx_low_alarm": "-20.00", "tx_high_alarm": "0.00"},
        )
        == "alarm"
    )
    assert evaluate_fit_ap_row_status({"rx_power": "-14.00", "rx_low_alarm": "-20.00", "rx_low_warning": "-15.00", "neighbor_rx_power": "-10.00"}) == "notice"


def test_fit_ap_switch_status_and_ap_alarm_are_independent():
    row = {
        "neighbor_rx_power": "-8.00",
        "switch_rx_low_alarm": "-20.00",
        "switch_rx_low_warning": "-15.00",
        "rx_power": "-20.00",
        "rx_low_alarm": "-19.00",
        "rx_low_warning": "-16.99",
    }

    assert evaluate_fit_ap_switch_status(row) == "normal"
    assert evaluate_fit_ap_ap_status(row) == "alarm"
    assert evaluate_fit_ap_row_status(row) == "alarm"


def test_fit_ap_switch_status_rules_and_missing_data():
    assert evaluate_fit_ap_switch_status({"switch_port_status": "DOWN", "neighbor_rx_power": "-8.00"}) == "link_abnormal"
    assert evaluate_fit_ap_switch_status({"neighbor_rx_power": None}) == "no_light"
    assert evaluate_fit_ap_switch_status({"neighbor_rx_power": "-45.00"}) == "no_light"
    assert evaluate_fit_ap_switch_status({"neighbor_rx_power": "-21.00", "switch_rx_low_alarm": "-20.00"}) == "alarm"
    assert evaluate_fit_ap_switch_status({"neighbor_rx_power": "-14.00", "switch_rx_low_alarm": "-20.00", "switch_rx_low_warning": "-15.00"}) == "notice"
    assert evaluate_fit_ap_switch_status({"neighbor_rx_power": "-10.00", "switch_rx_low_alarm": "-20.00", "switch_rx_low_warning": "-15.00"}) == "normal"
    assert evaluate_fit_ap_ap_status({}) == "no_light"


def test_severity_engine_unifies_fit_ap_and_device_detail_inputs():
    context = {
        "switch_rx_power": "-36.96",
        "switch_port_status": "UP",
        "alarm_low": "-19.00",
        "warning_low": "-16.99",
        "alarm_high": "0.00",
    }

    assert compute_optical_severity(context).severity == "no_light"
    assert evaluate_fit_ap_switch_status({"neighbor_rx_power": "-36.96", "switch_rx_low_alarm": "-19.00", "switch_rx_low_warning": "-16.99", "switch_rx_high_alarm": "0.00"}) == "no_light"


def test_optical_severity_engine_unifies_minus_20_32_across_modules():
    record = {"rx_power": "-20.32", "alarm_low": "-20.00", "warning_low": "-16.99", "port_status": "UP", "source_type": "optical"}

    assert compute_optical_severity(record).severity == "alarm"
    assert evaluate_fit_ap_switch_status({"neighbor_rx_power": "-20.32", "switch_rx_low_alarm": "-20.00", "switch_rx_low_warning": "-16.99"}) == "alarm"


def test_display_optical_status_uses_chinese_labels():
    assert display_optical_status("normal") == "正常"
    assert display_optical_status("warning") == "提示告警"
    assert display_optical_status("alarm") == "一般告警"
    assert display_optical_status("link_abnormal") == "链路异常"
    assert display_optical_status("link_down") == "链路断开"
    assert display_optical_status("no_light") == "无光"
    assert display_optical_status("skipped") == "未检查"
    assert display_optical_status("not_collected") == "未采集"
    assert display_optical_status("unknown") == "未知"


def test_paginate_rows_page_sizes_and_bounds():
    rows = [{"id": index} for index in range(1200)]

    visible, state = paginate_rows(rows)
    assert len(visible) == 200
    assert visible[0]["id"] == 0
    assert state.current_page == 1
    assert state.total_pages == 6

    visible, state = paginate_rows(rows, page_size=500, current_page=1)
    assert len(visible) == 500
    assert state.page_size == 500

    visible, state = paginate_rows(rows, page_size=1000, current_page=1)
    assert len(visible) == 1000

    visible, state = paginate_rows(rows, page_size=500, current_page=99)
    assert state.current_page == 3
    assert visible[0]["id"] == 1000

    visible, state = paginate_rows([])
    assert visible == []
    assert state.total_pages == 1


def test_fit_ap_optical_table_displays_chinese_status(tmp_path):
    app()
    context = create_demo_context(PathResolver(tmp_path))
    page = AcManagementPage(context.repository, I18n("zh_CN"), "demo")

    page._set_rows(
        page.optical_table,
        FIT_AP_OPTICAL_COLUMNS,
        [{"ap_name": "AP-A", "rx_power": "-20.00", "rx_low_alarm": "-19.00", "rx_low_warning": "-16.99"}],
    )

    values = [page.optical_table.item(0, column).text() for column in range(page.optical_table.columnCount())]
    assert "一般告警" in values
    assert "alarm" not in values


def test_export_fit_ap_optical_xlsx_contains_overview_and_optical_sheets(tmp_path):
    from openpyxl import load_workbook

    export_path = tmp_path / "optical.xlsx"
    rows = [
        {"ap_name": "AP-A", "ap_mac": "0011-2233-4455", "site": "S1", "rx_power": "-20.00", "rx_low_alarm": "-19.00", "rx_low_warning": "-16.99", "updated_at": "2026-01-01"},
        {"ap_name": "AP-B", "ap_mac": "0011-2233-4456", "site": "S1", "rx_power": "-14.00", "rx_low_alarm": "-20.00", "rx_low_warning": "-15.00", "updated_at": "2026-01-01"},
    ]
    headers = ["AP名称", "AP_MAC", "车站", "室内交换机", "室内端口号", "室内交换机收光(dBm)", "室内侧状态", "AP侧收光(dBm)", "光告警", "更新时间"]
    overview_rows = [
        {"site": "S1", "total": 2, "online": 1, "offline": 1, "online_rate": "50.0%", "remark": "Need check"},
        {"site": "合计", "total": 2, "online": 1, "offline": 1, "online_rate": "50.0%", "remark": ""},
    ]
    overview_headers = ["车站", "AP总数量", "上线", "未上线", "上线率", "备注"]

    export_fit_ap_optical_xlsx(export_path, rows, FIT_AP_OPTICAL_COLUMNS, headers, "Legend text", overview_rows, overview_headers)

    workbook = load_workbook(export_path)
    assert export_path.exists()
    assert workbook.sheetnames == ["AP上线情况概览", "FIT-AP光衰"]
    overview_sheet = workbook["AP上线情况概览"]
    optical_sheet = workbook["FIT-AP光衰"]
    assert [cell.value for cell in overview_sheet[1]] == overview_headers
    assert [cell.value for cell in optical_sheet[1]] == headers
    assert "AP名称MAC" not in [cell.value for cell in optical_sheet[1]]
    for forbidden_header in ("RX低告警", "RX警告下限", "RX正常线", "RX阈值来源"):
        assert forbidden_header not in [cell.value for cell in optical_sheet[1]]
    assert optical_sheet["G2"].value == "未知"
    assert optical_sheet["I2"].value == "一般告警"
    assert optical_sheet["I3"].value == "偏低关注"
    assert optical_sheet["A2"].fill.fgColor.rgb == "00FEE2E2"
    assert optical_sheet["A3"].fill.fgColor.rgb == "00FEF9C3"
    assert overview_sheet["A2"].fill.fgColor.rgb == "00FEF9C3"
    assert overview_sheet["D2"].fill.fgColor.rgb == "00FEE2E2"
    assert overview_sheet["A3"].fill.fgColor.rgb == "00DBEAFE"
    for sheet in (overview_sheet, optical_sheet):
        assert sheet.freeze_panes == "A2"
        assert sheet["A1"].font.bold
        assert sheet["A1"].alignment.horizontal == "center"
        assert sheet["A1"].alignment.vertical == "center"
        assert sheet["A2"].alignment.horizontal == "center"
        assert sheet["A1"].border.left.style == "thin"
        assert sheet.column_dimensions["A"].width > len(str(sheet["A1"].value))
        assert sheet.row_dimensions[1].height >= 24
        assert sheet.row_dimensions[2].height >= 22


def test_fit_ap_optical_warning_row_uses_light_yellow(tmp_path):
    app()
    context = create_demo_context(PathResolver(tmp_path))
    page = AcManagementPage(context.repository, I18n("en_US"), "demo")

    page._set_rows(
        page.optical_table,
        FIT_AP_OPTICAL_COLUMNS,
        [{"ap_name": "AP-A", "rx_power": "-14.00", "rx_low_alarm": "-20.00", "rx_low_warning": "-15.00", "neighbor_rx_power": "-10.00"}],
    )

    assert page.optical_table.item(0, 0).background().color().name() == "#fbbf24"
    assert page.optical_table.item(0, 0).foreground().color().name() == "#111827"


def test_fit_ap_optical_filters_before_paginating_and_export_uses_all_filtered_rows(tmp_path):
    from openpyxl import load_workbook

    app()
    context = create_demo_context(PathResolver(tmp_path))
    page = AcManagementPage(context.repository, I18n("en_US"), "demo")
    page.optical_page_size = 200
    page.optical_rows = [
        {"ap_name": f"AP-{index:03d}", "site": "S1", "optical_alarm_status": "normal", "updated_at": "2026-01-01"}
        for index in range(250)
    ] + [
        {"ap_name": f"ZZ-{index:03d}", "site": "S2", "optical_alarm_status": "alarm", "updated_at": "2026-01-01"}
        for index in range(5)
    ]

    page.optical_ap_filter.setText("ZZ")

    assert page.optical_table.rowCount() == 5
    assert page.optical_pagination.state.total_items == 5
    assert page.optical_page == 1

    export_path = tmp_path / "filtered_optical.xlsx"
    export_fit_ap_optical_xlsx(
        export_path,
        page.filtered_optical_rows(),
        FIT_AP_OPTICAL_COLUMNS,
        [page.i18n.t(key) for key, _field in FIT_AP_OPTICAL_COLUMNS],
        "",
        [],
        [page.i18n.t(key) for key, _field in AP_ONLINE_OVERVIEW_COLUMNS],
    )
    workbook = load_workbook(export_path)
    assert workbook["FIT-AP光衰"].max_row == 6


def test_optical_color_legend_does_not_expose_threshold_rules():
    assert "RX警告下限" not in I18n("zh_CN").t("details.optical_color_legend")
    assert "RX low warning" not in I18n("en_US").t("details.optical_color_legend")


def test_ap_online_overview_rows_count_states_and_total_bottom():
    rows = [
        {"ap_name": "AP-2-1", "site": "02云龙火车站站", "state": "R/M"},
        {"ap_name": "AP-2-2", "site": "02云龙火车站站", "state": "R/B"},
        {"ap_name": "AP-1-1", "site": "01小洋江站", "state": "I"},
        {"ap_name": "AP-1-2", "site": "01小洋江站", "state": "JA"},
        {"ap_name": "AP-1-3", "site": "01小洋江站", "state": "R"},
    ]

    overview = build_ap_online_overview_rows(planned_aps=rows, fit_ap_resources=rows)

    assert overview[0] == {"site": "01小洋江站", "total": 3, "online": 1, "offline": 2, "remark": "", "online_rate": "33.3%"}
    assert overview[1] == {"site": "02云龙火车站站", "total": 2, "online": 2, "offline": 0, "remark": "", "online_rate": "100.0%"}
    assert overview[-1] == {"site": "\u5408\u8ba1", "total": 5, "online": 3, "offline": 2, "remark": "", "online_rate": "60.0%"}


def test_ap_online_overview_uses_fit_ap_resource_site_capacity_and_unassigned():
    resources = [
        {"ap_uuid": "ap-1", "site_name": "Metadata Station", "state": "R/M"},
        {"ap_uuid": "ap-2", "site": "", "state": "JA"},
    ]
    overview = build_ap_online_overview_rows(
        planned_aps=[],
        fit_ap_resources=resources,
        capacity_details={"Metadata Station": {"ap_total": 5, "remark": "Keep watching"}},
    )

    assert [row["site"] for row in overview] == ["Metadata Station", "\u5408\u8ba1"]
    assert overview[0]["total"] == 5
    assert overview[0]["online"] == 1
    assert overview[0]["offline"] == 4
    assert overview[0]["remark"] == "Keep watching"
    assert overview[1]["online"] == 1


def test_ap_online_overview_matches_dirty_resource_site_back_to_plan():
    resources = [{"ap_mac": "0011-2233-4455", "ap_name": "AP-A", "site": "Demo", "state": "R"}]
    plans = [{"AP_MAC": "0011.2233.4455", "ap_name": "AP-A", "station": "01小洋江站"}]

    overview = build_ap_online_overview_rows(planned_aps=plans, fit_ap_resources=resources)

    assert [row["site"] for row in overview] == ["01小洋江站", "\u5408\u8ba1"]
    assert overview[0]["total"] == 1
    assert overview[0]["online"] == 1
    assert overview[0]["offline"] == 0


def test_ap_online_overview_unmatched_online_does_not_enter_unassigned():
    resources = [{"ap_mac": "00aa-bbcc-ddee", "ap_name": "AP-Z", "site": "Demo", "state": "R/M"}]
    plans = [{"ap_mac": "0011-2233-4455", "ap_name": "AP-A", "station": "01小洋江站"}]

    overview = build_ap_online_overview_rows(planned_aps=plans, fit_ap_resources=resources)

    assert [row["site"] for row in overview] == ["01小洋江站", "\u5408\u8ba1"]
    assert overview[0]["online"] == 0
    assert overview[-1]["online"] == 0
    assert all(row["site"] != "Demo" for row in overview)


def test_ap_online_overview_excludes_bulk_unmatched_when_plan_coverage_is_missing():
    resources = [{"ap_mac": f"00aa-bbcc-{index:04x}", "site": "Demo", "state": "R/M"} for index in range(20)]
    plans = [{"ap_mac": "0011-2233-4455", "station": "Station A"}]
    capacities = {"Station A": {"ap_total": 30, "remark": ""}, "Station B": {"ap_total": 56, "remark": ""}}

    overview = build_ap_online_overview_rows(planned_aps=plans, fit_ap_resources=resources, capacity_details=capacities)

    assert [row["site"] for row in overview] == ["Station A", "Station B", "\u5408\u8ba1"]
    assert all(row["site"] != "Demo" for row in overview)
    assert overview[-1]["total"] == 86
    assert overview[-1]["online"] == 0


def test_ap_online_overview_uses_ap_metadata_as_total_baseline():
    plan_rows = [
        *({"ap_uuid": f"s1-plan-{index}", "ap_name": f"S1-AP-{index}", "site_name": "01小洋江站"} for index in range(30)),
        *({"ap_uuid": f"s2-plan-{index}", "ap_name": f"S2-AP-{index}", "site_name": "02云龙火车站站"} for index in range(56)),
        {"ap_uuid": "unknown-plan-0", "ap_name": "UNKNOWN-AP-0", "site_name": "\u672a\u5f52\u5c5e"},
    ]
    resource_rows = [
        *({"ap_uuid": f"s1-plan-{index}", "ap_name": f"S1-AP-{index}", "site": "\u672a\u5f52\u5c5e", "state": "R/M"} for index in range(26)),
        *({"ap_uuid": f"s2-plan-{index}", "ap_name": f"S2-AP-{index}", "site": "\u672a\u5f52\u5c5e", "state": "R"} for index in range(48)),
        {"ap_uuid": "unknown-plan-0", "ap_name": "UNKNOWN-AP-0", "site": "\u672a\u5f52\u5c5e", "state": "online"},
    ]

    overview = build_ap_online_overview_rows(planned_aps=plan_rows, fit_ap_resources=resource_rows)

    assert overview[0] == {"site": "01小洋江站", "total": 30, "online": 26, "offline": 4, "remark": "", "online_rate": "86.7%"}
    assert overview[1] == {"site": "02云龙火车站站", "total": 56, "online": 48, "offline": 8, "remark": "", "online_rate": "85.7%"}
    assert overview[2] == {"site": "\u672a\u5f52\u5c5e", "total": 1, "online": 1, "offline": 0, "remark": "", "online_rate": "100.0%"}
    assert overview[-1] == {"site": "\u5408\u8ba1", "total": 87, "online": 75, "offline": 12, "remark": "", "online_rate": "86.2%"}


def test_ap_online_overview_does_not_use_fit_ap_resource_count_as_total_when_plan_exists():
    plan_rows = [{"ap_uuid": f"plan-{index}", "site_name": "Station A"} for index in range(948)]
    resource_rows = [{"ap_uuid": f"plan-{index}", "site": "\u672a\u5f52\u5c5e", "state": "R/M"} for index in range(773)]

    overview = build_ap_online_overview_rows(planned_aps=plan_rows, fit_ap_resources=resource_rows)

    assert overview[0]["site"] == "Station A"
    assert overview[0]["total"] == 948
    assert overview[0]["online"] == 773
    assert overview[0]["offline"] == 175
    assert overview[0]["online_rate"] == "81.5%"
    assert overview[-1]["total"] == 948
    assert overview[-1]["online"] == 773
    assert overview[-1]["offline"] == 175
    assert overview[-1]["online_rate"] == "81.5%"


def test_ap_online_overview_capacity_total_takes_priority_over_incomplete_plan():
    planned_aps = [
        {"ap_name": "AP-A-1", "site_name": "01小洋江站"},
        {"ap_name": "AP-B-1", "site_name": "02云龙火车站"},
    ]
    rows = build_ap_online_overview_rows(
        planned_aps=planned_aps,
        fit_ap_resources=[],
        capacity_details={
            "01小洋江站": {"ap_total": 30, "remark": ""},
            "02云龙火车站": {"ap_total": 56, "remark": ""},
            "08丹城站": {"ap_total": 78, "remark": ""},
            "10大目湾站": {"ap_total": 34, "remark": "大目湾校减-8"},
        },
    )
    by_site = {row["site"]: row for row in rows}

    assert by_site["01小洋江站"]["total"] == 30
    assert by_site["02云龙火车站"]["total"] == 56
    assert by_site["08丹城站"]["total"] == 78
    assert by_site["10大目湾站"]["total"] == 34
    assert by_site["10大目湾站"]["remark"] == "大目湾校减-8"


def test_ap_online_overview_matches_by_known_resource_station_when_metadata_key_missing():
    resources = [
        *({"ap_name": f"UNKNOWN-A-{index}", "site_name": "01小洋江站", "state": "R"} for index in range(26)),
        *({"ap_name": f"UNKNOWN-B-{index}", "site_name": "02云龙火车站", "state": "R"} for index in range(48)),
    ]
    rows = build_ap_online_overview_rows(
        planned_aps=[],
        fit_ap_resources=resources,
        capacity_details={
            "01小洋江站": {"ap_total": 30, "remark": ""},
            "02云龙火车站": {"ap_total": 56, "remark": ""},
        },
    )
    by_site = {row["site"]: row for row in rows}

    assert by_site["01小洋江站"]["online"] == 26
    assert by_site["02云龙火车站"]["online"] == 48
    assert "未归属" not in by_site
    assert rows[-1]["total"] == 86
    assert rows[-1]["online"] == 74


def test_ap_online_overview_matches_online_by_metadata_name_even_when_resource_site_is_dirty():
    metadata_rows = [
        *({"ap_name": f"STA-A-{index}", "site_name": "01小洋江站"} for index in range(26)),
        *({"ap_name": f"STA-B-{index}", "site_name": "02云龙火车站"} for index in range(48)),
    ]
    resources = [
        *({"ap_name": f" STA-A-{index} ", "site_name": "Demo", "state": "R"} for index in range(26)),
        *({"ap_name": f"STA-B-{index}", "site": "体育中心站", "state": "R"} for index in range(48)),
    ]
    rows = build_ap_online_overview_rows(
        metadata_rows=metadata_rows,
        fit_ap_resources=resources,
        capacity_details={
            "01小洋江站": {"ap_total": 30, "remark": ""},
            "02云龙火车站": {"ap_total": 56, "remark": ""},
        },
    )
    by_site = {row["site"]: row for row in rows}

    assert by_site["01小洋江站"]["online"] == 26
    assert by_site["02云龙火车站"]["online"] == 48
    assert "Demo" not in by_site
    assert "体育中心站" not in by_site
    assert "未归属" not in by_site


def test_ap_online_overview_metadata_empty_uses_optical_site_by_uuid():
    rows = build_ap_online_overview_rows(
        metadata_rows=[{"ap_uuid": "", "ap_name": "", "site_name": ""}],
        fit_ap_resources=[{"ap_uuid": "A", "ap_name": "AP001", "ap_mac": "30f5-277a-82c0", "state": "R"}],
        optical_rows=[{"ap_uuid": "A", "ap_name": "AP001", "ap_mac": "30f5-277a-82c0", "site": "01小洋江站"}],
        capacity_details={"01小洋江站": {"ap_total": 30, "remark": ""}},
    )
    by_site = {row["site"]: row for row in rows}

    assert by_site["01小洋江站"]["online"] == 1
    assert "未归属" not in by_site


def test_ap_online_overview_matches_optical_site_by_mac_without_uuid():
    rows = build_ap_online_overview_rows(
        metadata_rows=[],
        fit_ap_resources=[{"ap_name": "AP001", "ap_mac": "30:f5:27:7a:82:c0", "state": "ONLINE"}],
        optical_rows=[{"ap_name": "OTHER", "ap_mac": "30f5-277a-82c0", "site": "01小洋江站"}],
        capacity_details={"01小洋江站": {"ap_total": 30, "remark": ""}},
    )

    assert {row["site"]: row for row in rows}["01小洋江站"]["online"] == 1


def test_ap_online_overview_matches_optical_site_by_name_without_uuid_or_mac():
    rows = build_ap_online_overview_rows(
        metadata_rows=[],
        fit_ap_resources=[{"ap_name": " AP - 001 ", "state": "R/B"}],
        optical_rows=[{"ap_name": "AP-001", "site": "02云龙火车站"}],
        capacity_details={"02云龙火车站": {"ap_total": 56, "remark": ""}},
    )

    assert {row["site"]: row for row in rows}["02云龙火车站"]["online"] == 1


def test_ap_online_overview_resource_dirty_site_does_not_override_optical_site():
    rows = build_ap_online_overview_rows(
        metadata_rows=[],
        fit_ap_resources=[{"ap_mac": "30f5-277a-82c0", "site": "Demo", "state": "R"}],
        optical_rows=[{"ap_mac": "30f5-277a-82c0", "site": "01小洋江站"}],
        capacity_details={"01小洋江站": {"ap_total": 30, "remark": ""}},
    )
    by_site = {row["site"]: row for row in rows}

    assert by_site["01小洋江站"]["online"] == 1
    assert "Demo" not in by_site


def test_ap_online_overview_falls_back_to_known_resource_site_when_no_optical_match():
    rows = build_ap_online_overview_rows(
        metadata_rows=[],
        fit_ap_resources=[{"ap_name": "UNKNOWN", "site": "01小洋江站", "state": "R"}],
        optical_rows=[],
        capacity_details={"01小洋江站": {"ap_total": 30, "remark": ""}},
    )
    by_site = {row["site"]: row for row in rows}

    assert by_site["01小洋江站"]["online"] == 1
    assert "未归属" not in by_site


def test_ap_online_overview_unknown_dirty_resource_site_is_excluded_from_unassigned():
    rows = build_ap_online_overview_rows(
        metadata_rows=[],
        fit_ap_resources=[{"ap_name": "UNKNOWN", "site": "体育中心站", "state": "R"}],
        optical_rows=[],
        capacity_details={"01小洋江站": {"ap_total": 30, "remark": ""}},
    )
    by_site = {row["site"]: row for row in rows}

    assert "未归属" not in by_site
    assert "体育中心站" not in by_site


def test_ap_online_overview_dirty_unknown_station_does_not_create_station_row():
    rows = build_ap_online_overview_rows(
        planned_aps=[],
        fit_ap_resources=[{"ap_name": "UNKNOWN", "site": "Demo", "state": "R"}],
        capacity_details={"01小洋江站": {"ap_total": 30, "remark": ""}},
    )
    by_site = {row["site"]: row for row in rows}

    assert "Demo" not in by_site
    assert "未归属" not in by_site


def _make_standard_ap_online_overview_fixture():
    station_totals = {
        "01小洋江站": 30,
        "02云龙火车站": 56,
        "03横溪站": 126,
        "04横溪站": 138,
        "05鄞州咸祥": 134,
        "06象山贤庠": 134,
        "07大徐站": 94,
        "08丹城站": 78,
        "09滨海大道站": 56,
        "10大目湾站": 34,
        "11云龙车辆段": 67,
        "未归属": 1,
    }
    station_online = {
        "01小洋江站": 26,
        "02云龙火车站": 48,
        "03横溪站": 111,
        "04横溪站": 135,
        "05鄞州咸祥": 105,
        "06象山贤庠": 41,
        "07大徐站": 94,
        "08丹城站": 78,
        "09滨海大道站": 48,
        "10大目湾站": 34,
        "11云龙车辆段": 52,
        "未归属": 1,
    }
    planned_aps = []
    resources = []
    optical_rows = []
    for station, total in station_totals.items():
        for index in range(total):
            ap_name = f"{station}-AP-{index:03d}"
            mac = f"30f527{len(planned_aps):06x}"[-12:]
            planned_aps.append({"ap_name": ap_name, "ap_mac": mac, "site_name": station})
            if index < station_online[station]:
                dirty_site = "Demo" if station == "01小洋江站" and index == 0 else ("体育中心站" if station == "02云龙火车站" and index == 0 else station)
                resources.append({"ap_name": f" {ap_name} ", "ap_mac": mac.upper(), "site": dirty_site, "state": "R/M"})
                optical_rows.append({"ap_name": ap_name, "ap_mac": mac, "site": station})
    return planned_aps, resources, optical_rows


def _standard_ap_capacity_details():
    return {
        "01小洋江站": {"ap_total": 30, "remark": ""},
        "02云龙火车站": {"ap_total": 56, "remark": ""},
        "03横溪站": {"ap_total": 126, "remark": ""},
        "04横溪站": {"ap_total": 138, "remark": ""},
        "05鄞州咸祥": {"ap_total": 134, "remark": ""},
        "06象山贤庠": {"ap_total": 134, "remark": ""},
        "07大徐站": {"ap_total": 94, "remark": ""},
        "08丹城站": {"ap_total": 78, "remark": ""},
        "09滨海大道站": {"ap_total": 56, "remark": ""},
        "10大目湾站": {"ap_total": 34, "remark": "大目湾校减-8"},
        "11云龙车辆段": {"ap_total": 67, "remark": ""},
        "未归属": {"ap_total": 1, "remark": ""},
    }


def test_ap_online_overview_standard_large_sample_matches_expected_totals():
    planned_aps, resources, optical_rows = _make_standard_ap_online_overview_fixture()
    rows = build_ap_online_overview_rows(
        metadata_rows=planned_aps,
        fit_ap_resources=resources,
        optical_rows=optical_rows,
        capacity_details=_standard_ap_capacity_details(),
    )
    by_site = {row["site"]: row for row in rows}

    assert by_site["01小洋江站"]["online"] == 26
    assert by_site["08丹城站"]["total"] == 78
    assert by_site["08丹城站"]["online"] == 78
    assert by_site["10大目湾站"]["total"] == 34
    assert by_site["10大目湾站"]["remark"] == "大目湾校减-8"
    assert "Demo" not in by_site
    assert "体育中心站" not in by_site
    assert rows[-1] == {"site": "\u5408\u8ba1", "total": 948, "online": 773, "offline": 175, "remark": "", "online_rate": "81.5%"}


def test_ap_online_overview_name_match_without_mac_and_unmatched_is_excluded():
    planned_aps = [{"ap_name": " AP - 001 ", "site_name": "01小洋江站"}]
    resources = [
        {"ap_name": "AP-001", "site": "Demo", "state": "ONLINE"},
        {"ap_name": "AP-Z", "site": "体育中心站", "state": "R"},
    ]
    rows = build_ap_online_overview_rows(planned_aps=planned_aps, fit_ap_resources=resources)
    by_site = {row["site"]: row for row in rows}

    assert by_site["01小洋江站"]["online"] == 1
    assert "未归属" not in by_site
    assert "Demo" not in by_site
    assert "体育中心站" not in by_site


def test_ap_online_overview_unassigned_only_comes_from_metadata_rows():
    planned_aps = [
        {"ap_mac": "30f5-277a-11a0", "site_name": "未归属", "state": "I"},
        {"ap_mac": "30f5-277a-1e00", "site_name": "未归属", "state": "I"},
    ]
    resources = [
        {"ap_mac": f"30f5-277a-{index:04x}", "site": "", "state": "R"}
        for index in range(13)
    ]

    rows = build_ap_online_overview_rows(planned_aps=planned_aps, fit_ap_resources=resources)
    by_site = {row["site"]: row for row in rows}

    assert by_site["未归属"]["total"] == 2
    assert by_site["未归属"]["online"] == 0
    assert by_site["未归属"]["offline"] == 2
    assert rows[-1]["online"] == 0


def test_trackside_overview_export_large_sample_has_only_overview_columns(tmp_path):
    from openpyxl import load_workbook

    planned_aps, resources, optical_rows = _make_standard_ap_online_overview_fixture()
    overview_rows = build_ap_online_overview_rows(
        metadata_rows=planned_aps,
        fit_ap_resources=resources,
        optical_rows=optical_rows,
        capacity_details=_standard_ap_capacity_details(),
    )
    export_path = tmp_path / "large_trackside_overview.xlsx"
    i18n = I18n("zh_CN")

    export_trackside_ap_business_xlsx(
        export_path,
        [],
        TRACKSIDE_AP_BUSINESS_COLUMNS,
        [i18n.t(key) for key, _field in TRACKSIDE_AP_BUSINESS_COLUMNS],
        overview_rows,
        AP_ONLINE_OVERVIEW_COLUMNS,
        ["车站", "AP总数量", "上线", "未上线", "上线率", "备注"],
    )

    sheet = load_workbook(export_path)["AP上线情况概览"]
    rows = [[cell.value for cell in row] for row in sheet.iter_rows(values_only=False)]
    assert rows[0] == ["车站", "AP总数量", "上线", "未上线", "上线率", "备注"]
    assert rows[-1] == ["合计", "948", "773", "175", "81.5%", "-"]
    assert "Demo" not in {row[0] for row in rows}
    assert "体育中心站" not in {row[0] for row in rows}
    forbidden_headers = {"RX功率", "TX功率", "温度", "电压", "Bias电流", "光告警", "RX低告警", "RX警告下限", "RX正常线", "RX阈值来源"}
    assert forbidden_headers.isdisjoint(set(rows[0]))


def test_ap_online_overview_deduplicates_by_uuid_serial_and_mac():
    rows = [
        {"ap_uuid": "ap-1", "serial_number": "SN-1", "ap_mac": "mac-1", "site": "S1", "state": "R/M"},
        {"ap_uuid": "ap-1", "serial_number": "SN-1", "ap_mac": "mac-1", "site": "S1", "state": "R/M"},
        {"serial_number": "SN-2", "ap_mac": "mac-2", "site": "S1", "state": "R/B"},
        {"serial_number": "SN-2", "ap_mac": "mac-2", "site": "S1", "state": "R/B"},
        {"ap_mac": "mac-3", "site": "S1", "state": "I"},
        {"ap_mac": "mac-3", "site": "S1", "state": "I"},
    ]

    overview = build_ap_online_overview_rows(planned_aps=rows, fit_ap_resources=rows, capacities={"S1": 5})

    assert overview[0]["total"] == 5
    assert overview[0]["online"] == 2
    assert overview[0]["offline"] == 3


def test_ap_online_overview_columns_include_remark():
    assert AP_ONLINE_OVERVIEW_COLUMNS[-1] == ("field.remark", "remark")


def test_ap_online_overview_page_hides_new_online_section(tmp_path):
    app()
    database = make_database(tmp_path)
    device_repository = DeviceRepository(database)
    ac = device_repository.create(make_ac_device())
    AcRepository(database).replace_fit_ap_resources(ac.device_uuid, [{"ap_uuid": "ap-1", "serial_number": "SN-1", "site": "Station A", "state": "R/M"}])

    page = AcManagementPage(device_repository, I18n("zh_CN"), "demo")

    assert not hasattr(page, "new_online_group")
    assert not hasattr(page, "new_online_range_combo")
    assert not hasattr(page, "export_new_online_button")
    assert not hasattr(page, "new_online_summary_table")
    assert not hasattr(page, "new_online_detail_table")
    assert [page.overview_table.horizontalHeaderItem(column).text() for column in range(page.overview_table.columnCount())] == [
        "归属站点",
        "AP总数量",
        "上线",
        "未上线",
        "上线率",
        "备注",
    ]
    assert page.tabs.widget(1).findChild(PaginationWidget) is None


def test_ap_online_overview_table_edit_rules_and_save(tmp_path):
    app()
    database = make_database(tmp_path)
    device_repository = DeviceRepository(database)
    ac = device_repository.create(make_ac_device())
    repository = AcRepository(database)
    repository.replace_fit_ap_resources(
        ac.device_uuid,
        [
            {"ap_uuid": "ap-1", "ap_name": "AP-A", "serial_number": "SN-1", "site": "Station A", "state": "R/M"},
            {"ap_uuid": "ap-2", "ap_name": "AP-B", "serial_number": "SN-2", "site": "Station A", "state": "I"},
        ],
    )
    repository.upsert_fit_ap_metadata({"ap_uuid": "ap-1", "ap_name": "AP-A", "site_name": "Station A"})
    repository.upsert_fit_ap_metadata({"ap_uuid": "ap-2", "ap_name": "AP-B", "site_name": "Station A"})
    page = AcManagementPage(device_repository, I18n("en_US"), "demo")
    page.refresh_overview_table()
    process_events_until(lambda: not page._background_jobs)

    total_item = page.overview_table.item(0, 1)
    online_item = page.overview_table.item(0, 2)
    offline_item = page.overview_table.item(0, 3)
    rate_item = page.overview_table.item(0, 4)
    remark_item = page.overview_table.item(0, 5)
    total_row_total_item = page.overview_table.item(page.overview_table.rowCount() - 1, 1)
    total_row_remark_item = page.overview_table.item(page.overview_table.rowCount() - 1, 5)

    assert bool(total_item.flags() & Qt.ItemIsEditable)
    assert bool(remark_item.flags() & Qt.ItemIsEditable)
    assert not bool(online_item.flags() & Qt.ItemIsEditable)
    assert not bool(offline_item.flags() & Qt.ItemIsEditable)
    assert not bool(rate_item.flags() & Qt.ItemIsEditable)
    assert not bool(total_row_total_item.flags() & Qt.ItemIsEditable)
    assert not bool(total_row_remark_item.flags() & Qt.ItemIsEditable)

    total_item.setText("5")
    page.overview_table.item(0, 5).setText("Need field check")
    process_events_until(lambda: not page._background_jobs)

    assert repository.list_station_ap_capacities()["Station A"] == 5
    assert repository.list_station_ap_capacity_details()["Station A"]["remark"] == "Need field check"
    assert page.overview_table.item(0, 1).text() == "5"
    assert page.overview_table.item(0, 3).text() == "4"
    assert page.overview_table.item(0, 4).text() == "20.0%"
    assert page.overview_table.item(0, 5).text() == "Need field check"
    assert page.overview_table.item(page.overview_table.rowCount() - 1, 1).text() == "5"


def test_ap_online_overview_table_allows_total_edit_triggers(tmp_path):
    app()
    database = make_database(tmp_path)
    device_repository = DeviceRepository(database)
    ac = device_repository.create(make_ac_device())
    repository = AcRepository(database)
    repository.replace_fit_ap_resources(ac.device_uuid, [{"ap_uuid": "ap-1", "serial_number": "SN-1", "site": "Station A", "state": "R/M"}])

    page = AcManagementPage(device_repository, I18n("en_US"), "demo")
    triggers = page.overview_table.editTriggers()

    assert triggers & QAbstractItemView.DoubleClicked
    assert triggers & QAbstractItemView.EditKeyPressed
    assert triggers & QAbstractItemView.SelectedClicked
    assert not page._updating_online_summary


def test_ap_online_overview_saved_total_survives_refresh_and_reload(tmp_path):
    app()
    database = make_database(tmp_path)
    device_repository = DeviceRepository(database)
    ac = device_repository.create(make_ac_device())
    repository = AcRepository(database)
    repository.replace_fit_ap_resources(ac.device_uuid, [{"ap_uuid": "ap-1", "serial_number": "SN-1", "site": "Station A", "state": "R/M"}])
    repository.upsert_fit_ap_metadata({"ap_uuid": "ap-1", "ap_name": "AP-1", "site_name": "Station A"})
    repository.upsert_fit_ap_metadata({"ap_uuid": "ap-2", "ap_name": "AP-2", "site_name": "Station A"})
    repository.upsert_station_ap_capacity("Station A", 9)
    repository.upsert_station_ap_remark("Station A", "Persistent remark")

    page = AcManagementPage(device_repository, I18n("en_US"), "demo")
    page.refresh_overview_table()
    process_events_until(lambda: not page._background_jobs)
    assert page.overview_table.item(0, 1).text() == "9"
    assert page.overview_table.item(0, 5).text() == "Persistent remark"

    repository.replace_fit_ap_resources(
        ac.device_uuid,
        [
            {"ap_uuid": "ap-1", "serial_number": "SN-1", "site": "Station A", "state": "R/M"},
            {"ap_uuid": "ap-2", "serial_number": "SN-2", "site": "Station A", "state": "R/B"},
        ],
    )
    page.refresh_overview_table()
    process_events_until(lambda: not page._background_jobs)
    assert page.overview_table.item(0, 1).text() == "9"
    assert page.overview_table.item(0, 2).text() == "2"
    assert page.overview_table.item(0, 3).text() == "7"
    assert page.overview_table.item(0, 5).text() == "Persistent remark"

    reloaded = AcManagementPage(device_repository, I18n("en_US"), "demo")
    reloaded.refresh_overview_table()
    process_events_until(lambda: not reloaded._background_jobs)
    assert reloaded.overview_table.item(0, 1).text() == "9"
    assert reloaded.overview_table.item(0, 5).text() == "Persistent remark"


def test_ap_online_overview_new_station_defaults_total_to_online_count(tmp_path):
    app()
    database = make_database(tmp_path)
    device_repository = DeviceRepository(database)
    ac = device_repository.create(make_ac_device())
    repository = AcRepository(database)
    repository.replace_fit_ap_resources(
        ac.device_uuid,
        [
            {"ap_uuid": "ap-1", "serial_number": "SN-1", "site": "Station A", "state": "R/M"},
            {"ap_uuid": "ap-2", "serial_number": "SN-2", "site": "Station A", "state": "I"},
        ],
    )
    repository.upsert_fit_ap_metadata({"ap_uuid": "ap-1", "ap_name": "AP-1", "site_name": "Station A"})
    repository.upsert_fit_ap_metadata({"ap_uuid": "ap-2", "ap_name": "AP-2", "site_name": "Station A"})

    page = AcManagementPage(device_repository, I18n("en_US"), "demo")
    page.refresh_overview_table()
    process_events_until(lambda: not page._background_jobs)

    assert page.overview_table.item(0, 1).text() == "2"
    assert page.overview_table.item(0, 2).text() == "1"
    assert page.overview_table.item(0, 3).text() == "1"


def test_ap_online_overview_rejects_invalid_total_and_restores(monkeypatch, tmp_path):
    app()
    database = make_database(tmp_path)
    device_repository = DeviceRepository(database)
    ac = device_repository.create(make_ac_device())
    repository = AcRepository(database)
    repository.replace_fit_ap_resources(ac.device_uuid, [{"ap_uuid": "ap-1", "serial_number": "SN-1", "site": "Station A", "state": "R/M"}])
    repository.upsert_station_ap_capacity("Station A", 5)
    page = AcManagementPage(device_repository, I18n("en_US"), "demo")
    page.refresh_overview_table()
    process_events_until(lambda: not page._background_jobs)
    warnings = []
    monkeypatch.setattr("netconsole.ui.pages.ac_management_page.MessageBox.warning", lambda *args: warnings.append(args))

    page.overview_table.item(0, 1).setText("")
    process_events_until(lambda: not page._background_jobs)

    assert warnings
    assert repository.list_station_ap_capacities()["Station A"] == 5
    assert page.overview_table.item(0, 1).text() == "5"


def test_ap_online_overview_save_history_snapshot_from_current_rows(monkeypatch, tmp_path):
    app()
    database = make_database(tmp_path)
    device_repository = DeviceRepository(database)
    ac = device_repository.create(make_ac_device())
    repository = AcRepository(database)
    repository.replace_fit_ap_resources(ac.device_uuid, [{"ap_uuid": "ap-1", "serial_number": "SN-1", "site": "Station A", "state": "R/M"}])
    repository.upsert_station_ap_capacity("Station A", 3)
    repository.upsert_station_ap_remark("Station A", "Snapshot note")
    page = AcManagementPage(device_repository, I18n("en_US"), "demo")
    page.refresh_overview_table()
    process_events_until(lambda: not page._background_jobs)
    messages = []
    monkeypatch.setattr("netconsole.ui.pages.ac_management_page.MessageBox.information", lambda *args: messages.append(args))

    page.save_overview_history_snapshot()
    process_events_until(lambda: not page._background_jobs)
    history = repository.list_station_online_summary_history("Station A")

    assert messages
    assert len(history) == 1
    assert history[0]["ap_total"] == 3
    assert history[0]["remark"] == "Snapshot note"


def test_export_ap_online_overview_xlsx_contains_colors_and_alignment(tmp_path):
    from openpyxl import load_workbook

    export_path = tmp_path / "overview.xlsx"
    plan_rows = [
        {"ap_name": "AP-1", "site_name": "01小洋江站"},
        {"ap_name": "AP-2", "site_name": "02云龙火车站站"},
    ]
    resource_rows = [
        {"ap_name": "AP-1", "site": "01小洋江站", "state": "R"},
        {"ap_name": "AP-2", "site": "02云龙火车站站", "state": "I"},
    ]
    rows = build_ap_online_overview_rows(
        planned_aps=plan_rows,
        fit_ap_resources=resource_rows,
        capacities={"02云龙火车站站": 1},
    )
    rows[1]["remark"] = "Need check"
    headers = ["Station", "AP Total", "Online", "Offline", "Online Rate", "Remark"]

    export_ap_online_overview_xlsx(export_path, rows, headers)

    workbook = load_workbook(export_path)
    sheet = workbook["AP Online Overview"]
    assert export_path.exists()
    assert [cell.value for cell in sheet[1]] == headers
    assert sheet.freeze_panes == "A2"
    assert sheet["A1"].alignment.horizontal == "center"
    assert sheet["A2"].alignment.horizontal == "center"
    assert sheet.column_dimensions["A"].width > len("车站")
    assert sheet["A2"].fill.fgColor.rgb == "00DCFCE7"
    assert sheet["D3"].fill.fgColor.rgb == "00FEE2E2"
    assert sheet["F3"].value == "Need check"


def test_trackside_ap_description_filter_is_case_insensitive():
    assert description_contains_ap("To_AP01")
    assert description_contains_ap("ap-001")
    assert description_contains_ap("Ap uplink")
    assert description_contains_ap("aP access")
    assert not description_contains_ap("camera")


def test_trackside_ap_normalizes_mac_and_interface_names():
    assert normalize_mac("bc5a-3457-cbe0") == "bc5a-3457-cbe0"
    assert normalize_mac("bc:5a:34:57:cb:e0") == "bc5a-3457-cbe0"
    assert normalize_mac("bc5a.3457.cbe0") == "bc5a-3457-cbe0"
    assert normalize_mac("BC-5A-34-57-CB-E0") == "bc5a-3457-cbe0"
    assert normalize_trackside_interface_name("GE2/0/22") == "GigabitEthernet2/0/22"
    assert normalize_trackside_interface_name("GigabitEthernet2/0/22") == "GigabitEthernet2/0/22"
    assert normalize_trackside_interface_name("XGE1/0/49") == "Ten-GigabitEthernet1/0/49"
    assert normalize_trackside_interface_name("BAGG1") == "Bridge-Aggregation1"


def test_trackside_vlan_parser_normalizes_ranges_and_rejects_invalid_values():
    assert parse_vlan_set("21，925-927; 21 922") == {21, 922, 925, 926, 927}
    assert normalize_vlan_text("922,21,921-922") == "21,921,922"
    for value in ("0", "4095", "abc", "930-925"):
        with pytest.raises(ValueError):
            parse_vlan_set(value)


def test_trackside_ap_interface_matches_description_or_pvid_plan():
    plan = {
        "mode": TRACKSIDE_AP_PLAN_MODE,
        "station_vlans": {"Station A": {921}},
        "all_vlans": {921},
        "station_totals": {"Station A": 30},
    }
    switch = Device(name="SW", station="Station A", device_uuid="sw-1")

    base = {"interface_name": "GigabitEthernet1/0/1", "port_status": "access"}
    assert is_trackside_ap_interface(switch, {**base, "description": "", "pvid": "921"}, plan) == (True, "pvid")
    assert is_trackside_ap_interface(switch, {**base, "description": "to AP", "pvid": "1"}, plan) == (True, "description")
    assert is_trackside_ap_interface(switch, {**base, "description": "to AP", "pvid": "921"}, plan) == (True, "description+pvid")
    assert is_trackside_ap_interface(switch, {**base, "description": "", "pvid": "922"}, plan) == (False, "none")


def test_trackside_ap_interface_prefers_station_vlans_and_falls_back_global():
    plan = {
        "mode": TRACKSIDE_AP_PLAN_MODE,
        "station_vlans": {"Station A": {921}, "Station B": {922}},
        "all_vlans": {921, 922},
        "station_totals": {"Station A": 30, "Station B": 56},
    }

    assert pvid_matches_trackside_plan("Station A", "921", plan) is True
    assert pvid_matches_trackside_plan("Station A", "922", plan) is False
    assert pvid_matches_trackside_plan("", "922", plan) is True


def test_trackside_ap_business_rows_include_pvid_match_source():
    switch = Device(name="HX_1", station="Station A", device_uuid="sw-1")
    rows = build_trackside_ap_business_rows(
        [switch],
        {"sw-1": [{"interface_name": "GigabitEthernet2/0/10", "description": "", "pvid": "921"}]},
        {"sw-1": []},
        [],
        trackside_ap_plan={"mode": TRACKSIDE_AP_PLAN_MODE, "station_vlans": {"Station A": {921}}, "all_vlans": {921}},
    )

    assert len(rows) == 1
    assert rows[0]["match_source"] == "pvid"
    assert format_trackside_display_value("match_source", rows[0]) == "PVID匹配"


def test_trackside_ap_business_rows_join_interface_optical_and_fit_ap_data():
    switch = Device(name="HX_1", sysname="HX_SYS", station="Station A", device_uuid="sw-1")
    rows = build_trackside_ap_business_rows(
        [switch],
        {
            "sw-1": [
                {
                    "interface_name": "GigabitEthernet2/0/10",
                    "link_status": "UP",
                    "protocol_status": "UP",
                    "description": "To_AP10",
                    "port_status": "trunk",
                    "pvid": "1",
                    "vlan": "10",
                    "updated_at": "2026-01-01T00:00:00",
                },
                {"interface_name": "GigabitEthernet2/0/2", "description": "camera"},
                {"interface_name": "GigabitEthernet2/0/1", "description": "ap-001"},
            ]
        },
        {
            "sw-1": [
                {"interface_name": "GigabitEthernet2/0/10", "rx_power": "-6.10", "status": "normal"},
                {"interface_name": "GigabitEthernet2/0/1", "rx_power": "-7.20", "status": "warning"},
            ]
        },
        [
                {
                    "ac_device_uuid": "ac-1",
                    "ap_uuid": "ap-10",
                    "ap_mac": "bc5a-3457-cbe0",
                    "neighbor_device_name": "HX_1",
                    "neighbor_interface": "GigabitEthernet2/0/10",
                    "ap_name": "AP10",
                    "rx_power": "-14.35",
                    "rx_low_alarm": "-19.00",
                    "rx_low_warning": "-16.99",
                    "updated_at": "2026-01-02T00:00:00",
                }
        ],
    )

    assert [row["interface_name"] for row in rows] == ["GigabitEthernet2/0/1", "GigabitEthernet2/0/10"]
    assert rows[1]["switch_rx_power"] == "-6.10"
    assert rows[1]["link_status"] == "UP"
    assert format_trackside_display_value("link_status", rows[1]) == "UP"
    assert format_trackside_display_value("port_type", rows[1]) == "trunk"
    assert rows[1]["ap_rx_power"] == "-14.35"
    assert rows[1]["ap_optical_status"] == "notice"
    assert rows[1]["ap_name"] == "AP10"


def test_trackside_ap_business_link_and_port_type_are_separate():
    assert normalize_link_state("up") == "UP"
    assert normalize_link_state("Administratively DOWN") == "DOWN"
    assert normalize_link_state("") == "-"
    assert format_trackside_display_value("link_status", {"link_status": "DOWN", "port_type": "access"}) == "DOWN"
    assert format_trackside_display_value("port_type", {"link_status": "DOWN", "port_type": "access"}) == "access"
    assert format_trackside_display_value("port_type", {"port_type": "DOWN", "port_status": "UP"}) == "unknown"


def test_trackside_ap_business_offline_ap_keeps_link_state():
    rows = build_trackside_ap_business_rows(
        [],
        {
            "sw-1": [
                {
                    "interface_name": "GigabitEthernet2/0/10",
                    "link_status": "DOWN",
                    "port_status": "access",
                    "pvid": "921",
                }
            ]
        },
        {"sw-1": [{"interface_name": "GigabitEthernet2/0/10", "rx_power": "-6.10"}]},
        [],
        offline_ap_ledger_rows=[
            {
                "site": "Station A",
                "device_uuid": "sw-1",
                "historical_switch_name": "HX_1",
                "historical_switch_interface": "GigabitEthernet2/0/10",
                "ap_mac": "30f5-277a-15e0",
                "ap_name": "AP-IDLE",
                "ap_status": "Idle",
            }
        ],
    )

    assert rows[0]["is_ap_offline"] is True
    assert format_trackside_display_value("link_status", rows[0]) == "DOWN"
    assert format_trackside_display_value("port_type", rows[0]) == "access"
    assert format_trackside_display_value("ap_optical_status", rows[0]) == OFFLINE_AP_STATUS_TEXT


def test_trackside_ap_business_matches_fit_ap_by_lldp_neighbor_mac():
    switch = Device(name="HX_1", station="Station A", device_uuid="sw-1")
    rows = build_trackside_ap_business_rows(
        [switch],
        {"sw-1": [{"interface_name": "GigabitEthernet2/0/22", "description": "To_AP22"}]},
        {"sw-1": [{"interface_name": "GigabitEthernet2/0/22", "rx_power": "-6.10", "status": "normal"}]},
        [
            {
                "ac_device_uuid": "ac-1",
                "ap_uuid": "ap-22",
                "ap_mac": "bc5a-3457-cbe0",
                "ap_name": "Business-AP-22",
                "rx_power": "-14.35",
                "rx_low_alarm": "-19.00",
                "rx_low_warning": "-16.99",
            }
        ],
        {"sw-1": [{"local_interface": "GE2/0/22", "neighbor_mac": "BC:5A:34:57:CB:E0", "neighbor_interface": "GigabitEthernet1/0/2"}]},
    )

    assert rows[0]["ap_mac"] == "bc5a-3457-cbe0"
    assert rows[0]["ap_name"] == "Business-AP-22"
    assert rows[0]["ap_rx_power"] == "-14.35"
    assert rows[0]["ap_optical_status"] == "notice"


def test_trackside_ap_business_matches_fit_ap_resource_by_lldp_neighbor_mac():
    switch = Device(name="HX_1", station="Station A", device_uuid="sw-1")
    rows = build_trackside_ap_business_rows(
        [switch],
        {"sw-1": [{"interface_name": "GigabitEthernet2/0/23", "description": "AP23"}]},
        {"sw-1": [{"interface_name": "GigabitEthernet2/0/23", "rx_power": "-6.20", "status": "normal"}]},
        [],
        {"sw-1": [{"local_interface": "GE2/0/23", "neighbor_mac": "bc5a.3457.cbe1"}]},
        [{"ac_device_uuid": "ac-1", "ap_uuid": "ap-23", "ap_mac": "bc5a-3457-cbe1", "ap_name": "Renamed-AP-23"}],
    )

    assert rows[0]["ap_mac"] == "bc5a-3457-cbe1"
    assert rows[0]["ap_name"] == "Renamed-AP-23"
    assert rows[0]["ap_rx_power"] is None
    assert rows[0]["switch_optical_status"] == "unknown"
    assert rows[0]["ap_optical_status"] == ""
    assert has_ap_side_optical_data(rows[0]) is False
    assert format_ap_side_alarm(rows[0]) == "-"


def test_trackside_ap_business_keeps_neighbor_mac_when_fit_ap_not_found():
    switch = Device(name="HX_1", station="Station A", device_uuid="sw-1")
    rows = build_trackside_ap_business_rows(
        [switch],
        {"sw-1": [{"interface_name": "GigabitEthernet2/0/24", "description": "AP24"}]},
            {"sw-1": [{"interface_name": "GigabitEthernet2/0/24", "rx_power": "-6.20", "rx_low_alarm": "-20.00", "rx_low_warning": "-8.00"}]},
        [],
        {"sw-1": [{"local_interface": "GE2/0/24", "neighbor_mac": "bc5a-3457-cbe2"}]},
    )

    assert rows[0]["ap_mac"] == "bc5a-3457-cbe2"
    assert rows[0]["ap_name"] is None
    assert rows[0]["ap_rx_power"] is None
    assert rows[0]["switch_optical_status"] == "notice"
    assert rows[0]["ap_optical_status"] == ""
    assert has_ap_side_optical_data(rows[0]) is False
    assert format_ap_side_alarm(rows[0]) == "-"


def test_trackside_ap_business_keeps_switch_and_ap_status_separate():
    switch = Device(name="HX_1", station="Station A", device_uuid="sw-1")
    rows = build_trackside_ap_business_rows(
        [switch],
        {"sw-1": [{"interface_name": "GigabitEthernet2/0/25", "description": "AP25"}]},
        {"sw-1": [{"interface_name": "GigabitEthernet2/0/25", "rx_power": "-6.20", "status": "normal"}]},
        [
            {
                "ap_uuid": "ap-25",
                "ap_mac": "bc5a-3457-cbe3",
                "ap_name": "AP25",
                "rx_power": "-20.00",
                "rx_low_alarm": "-19.00",
                "rx_low_warning": "-16.99",
            }
        ],
        {"sw-1": [{"local_interface": "GE2/0/25", "neighbor_mac": "bc5a-3457-cbe3"}]},
    )

    assert rows[0]["switch_optical_status"] == "unknown"
    assert rows[0]["ap_optical_status"] == "alarm"
    assert trackside_row_status(rows[0]) == "alarm"


def test_trackside_ap_business_row_status_uses_more_severe_side():
    assert trackside_row_status({"switch_optical_status": "warning", "ap_optical_status": "normal"}) == "warning"
    assert trackside_row_status({"switch_optical_status": "normal", "ap_optical_status": "alarm", "ap_side_has_data": True}) == "alarm"


def test_trackside_ap_side_missing_data_formats_as_dash():
    row = {
        "ap_mac": "-",
        "ap_name": "-",
        "ap_rx_power": "-",
        "ap_tx_power": "",
        "ap_optical_status": "no_module",
        "ap_side_has_data": False,
    }

    assert has_ap_side_optical_data(row) is False
    assert format_ap_side_alarm(row) == "-"
    assert format_trackside_display_value("ap_mac", row) == "-"
    assert format_trackside_display_value("ap_name", row) == "-"
    assert format_trackside_display_value("ap_rx_power", row) == "-"
    assert format_trackside_display_value("ap_tx_power", row) == "-"


def test_trackside_ap_side_unmatched_optical_record_formats_as_dash():
    row = {
        "ap_mac": "bc5a-3457-cbe1",
        "ap_name": "Renamed-AP-23",
        "ap_rx_power": None,
        "ap_optical_status": "no_module",
        "ap_side_has_data": False,
    }

    assert has_ap_side_optical_data(row) is False
    assert format_ap_side_alarm(row) == "-"


def test_trackside_ap_side_explicit_no_module_keeps_no_module_label():
    row = {
        "ap_mac": "bc5a-3457-cbe1",
        "ap_name": "AP23",
        "ap_rx_power": None,
        "ap_tx_power": None,
        "ap_optical_status": "no_module",
        "raw_status": "no module",
        "ap_side_has_data": True,
    }

    assert has_ap_side_optical_data(row) is True
    assert format_ap_side_alarm(row) == "无光模块"


def test_trackside_ap_side_normal_and_notice_format_from_computed_status():
    normal = {
        "ap_mac": "bc5a-3457-cbe1",
        "ap_name": "AP23",
        "ap_rx_power": "-7.55",
        "ap_tx_power": "1.20",
        "ap_optical_status": "normal",
        "ap_side_has_data": True,
    }
    notice = {**normal, "ap_rx_power": "-14.35", "ap_optical_status": "notice"}

    assert format_ap_side_alarm(normal) == "正常"
    assert format_ap_side_alarm(notice) == "偏低关注"


def test_trackside_ap_side_unknown_with_rx_power_recomputes_for_display():
    row = {
        "ap_mac": "bc5a-3457-cbe1",
        "ap_name": "AP23",
        "ap_rx_power": "-14.41",
        "ap_optical_status": "unknown",
        "ap_side_has_data": True,
    }

    assert format_ap_side_alarm(row) == "偏低关注"
    assert format_trackside_display_value("ap_optical_status", row) == "偏低关注"


def test_trackside_history_unknown_with_rx_power_recomputes_ap_status():
    row = {
        "rx_power": "-19.07",
        "rx_low_alarm": None,
        "rx_low_warning": None,
        "optical_alarm_status": "unknown",
    }

    assert _optical_status_from_history(row, "ap") == "alarm"


def test_trackside_ap_optical_status_uses_default_profile_without_thresholds():
    switch = Device(name="HX_1", station="Station A", device_uuid="sw-1")
    rows = build_trackside_ap_business_rows(
        [switch],
        {"sw-1": [{"interface_name": "GigabitEthernet2/0/10", "description": "To_AP10"}]},
        {"sw-1": [{"interface_name": "GigabitEthernet2/0/10", "rx_power": "-6.10"}]},
        [
            {
                "ap_uuid": "ap-10",
                "ap_mac": "bc5a-3457-cbe0",
                "ap_name": "AP10",
                "neighbor_device_name": "HX_1",
                "neighbor_interface": "GigabitEthernet2/0/10",
                "rx_power": "-14.41",
            }
        ],
    )

    assert rows[0]["ap_rx_power"] == "-14.41"
    assert rows[0]["ap_optical_status"] == "notice"
    assert format_trackside_display_value("ap_optical_status", rows[0]) == "偏低关注"


def test_trackside_row_status_ignores_missing_ap_side_data():
    row = {
        "switch_optical_status": "normal",
        "ap_optical_status": "alarm",
        "ap_side_has_data": False,
    }

    assert trackside_row_status(row) == "normal"


def test_trackside_ap_business_filter_by_site_and_search():
    rows = [
        {"site": "Station A", "ap_name": "AP-A", "device_name": "HX_1", "interface_name": "GigabitEthernet1/0/1"},
        {"site": "Station B", "ap_name": "AP-B", "device_name": "HX_2", "interface_name": "GigabitEthernet1/0/2"},
        {"site": "Station C", "ap_name": "AP-C", "device_name": "HX_3", "interface_name": "GigabitEthernet1/0/3"},
    ]

    assert len(filter_trackside_ap_business_rows(rows, "", "")) == 3
    assert len(filter_trackside_ap_business_rows(rows, None, "")) == 3
    assert [row["ap_name"] for row in filter_trackside_ap_business_rows(rows, "Station A", "")] == ["AP-A"]
    assert [row["ap_name"] for row in filter_trackside_ap_business_rows(rows, "", "hx_2")] == ["AP-B"]
    assert [row["ap_name"] for row in filter_trackside_ap_business_rows(rows, "Station B", "1/0/2")] == ["AP-B"]


def test_trackside_ap_i18n_zh_cn_keys_are_translated():
    zh = I18n("zh_CN")
    assert zh.t("rail_transit.trackside_ap_service") == "\u8f68\u65c1AP\u4e1a\u52a1"
    assert zh.t("trackside_ap.update") == "\u66f4\u65b0"
    assert zh.t("trackside_ap.cancel_update") == "\u53d6\u6d88\u66f4\u65b0"
    assert zh.t("trackside_ap.not_collected") == "\u672a\u91c7\u96c6"
    assert zh.t("trackside_ap.vendor_not_supported") == "\u5f53\u524d\u5382\u5546\u6682\u672a\u9002\u914d\u5149\u8870\u91c7\u96c6\u547d\u4ee4"


def test_trackside_ap_page_does_not_render_i18n_keys(tmp_path):
    app()
    database = make_database(tmp_path)
    repository = DeviceRepository(database)
    rail_page = RailTransitPage(repository, I18n("zh_CN"), "demo", PathResolver(tmp_path))
    assert rail_page.trackside_page is None
    rail_page._ensure_feature_page("rail.trackside_ap_business")
    page = rail_page.trackside_page
    visible_text = [
        rail_page.tabs.tabText(0),
        rail_page.tabs.tabText(2),
        page.update_button.text(),
        page.cancel_update_button.text(),
        page.status_label.text(),
        page.update_button.toolTip(),
    ]
    visible_text.extend(page.trackside_table.horizontalHeaderItem(index).text() for index in range(page.trackside_table.columnCount()))

    assert all("trackside_ap." not in text and "rail_transit." not in text for text in visible_text)
    assert any("\u66f4\u65b0" in text for text in visible_text)
    assert "\u8f68\u65c1AP\u4e1a\u52a1" in visible_text


def test_trackside_ap_progress_text_has_no_mojibake_or_i18n_key():
    zh = I18n("zh_CN")
    en = I18n("en_US")
    zh_text = zh.t("trackside_ap.collecting_progress", done=0, total=1200)
    en_text = en.t("trackside_ap.collection_summary", success=26, failed=0, skipped=640)

    assert zh_text == "\u91c7\u96c6\u4e2d\uff1a0 / 1200"
    assert en_text == "Completed: 26 succeeded, 0 failed, 640 skipped"
    assert "?" not in zh_text
    assert "trackside_ap." not in zh_text
    assert "trackside_ap." not in en_text


def test_trackside_optical_command_adapter_supports_h3c_aliases_and_rejects_reserved_vendors():
    assert OpticalCommandAdapter.get_optical_diagnosis_commands("H3C", "SW") == TRACKSIDE_OPTICAL_COMMANDS
    assert OpticalCommandAdapter.get_optical_diagnosis_commands("\u65b0\u534e\u4e09", "\u4ea4\u6362\u673a") == TRACKSIDE_OPTICAL_COMMANDS
    for vendor in ("Huawei", "\u534e\u4e3a", "ZTE", "\u4e2d\u5174"):
        with pytest.raises(UnsupportedVendor):
            OpticalCommandAdapter.get_optical_diagnosis_commands(vendor, "SW")


def test_trackside_station_switch_target_filter_uses_station_group_and_switch_types(tmp_path):
    database = make_database(tmp_path)
    repository = DeviceRepository(database)
    groups = DeviceGroupRepository(database, "demo")
    station = groups.create("车站")
    onboard = groups.create("车载")
    switch_a = repository.create(Device(name="A", group_id=station.id, device_type="SW", device_vendor="H3C", ip_address="10.0.0.1", ssh_username="u", ssh_password="p"))
    repository.create(Device(name="B", group_id=station.id, device_type="FAT-AP", ip_address="10.0.0.2", ssh_username="u", ssh_password="p"))
    repository.create(Device(name="C", group_id=onboard.id, device_type="FAT-AP", ip_address="10.0.0.3", ssh_username="u", ssh_password="p"))
    switch_d = repository.create(Device(name="D", group_id=station.id, device_type="交换机", device_vendor="\u65b0\u534e\u4e09", ip_address="10.0.0.4", ssh_username="u", ssh_password="p"))

    targets, skipped = build_station_switch_targets(repository, "demo")

    assert [target.device_id for target in targets] == [switch_a.id, switch_d.id]
    assert skipped == []


def test_trackside_station_switch_target_filter_can_scope_station(tmp_path):
    database = make_database(tmp_path)
    repository = DeviceRepository(database)
    station_group = DeviceGroupRepository(database, "demo").create("车站")
    station_a = repository.create(Device(name="A", station="Station A", group_id=station_group.id, device_type="SW", device_vendor="H3C", ip_address="10.0.0.1", ssh_username="u", ssh_password="p"))
    repository.create(Device(name="B", station="Station B", group_id=station_group.id, device_type="SW", device_vendor="H3C", ip_address="10.0.0.2", ssh_username="u", ssh_password="p"))

    targets, skipped = build_station_switch_targets(repository, "demo", station="Station A")

    assert [target.device_id for target in targets] == [station_a.id]
    assert skipped == []


def test_trackside_station_switch_target_skips_unsupported_vendor(tmp_path):
    database = make_database(tmp_path)
    repository = DeviceRepository(database)
    station = DeviceGroupRepository(database, "demo").create("车站")
    repository.create(Device(name="HW", group_id=station.id, device_type="SW", device_vendor="Huawei", ip_address="10.0.0.5", ssh_username="u", ssh_password="p"))

    targets, skipped = build_station_switch_targets(repository, "demo")

    assert targets == []
    assert skipped[0].reason == "vendor_not_supported"


def test_trackside_ap_targets_skip_missing_connection_info(tmp_path):
    database = make_database(tmp_path)
    device_repository = DeviceRepository(database)
    connectable = device_repository.create(Device(name="AP-OK", device_type="FAT-AP", ip_address="10.0.0.10", ssh_username="u", ssh_password="p"))
    device_repository.create(Device(name="AP-NO-PASSWORD", device_type="FAT-AP", ip_address="10.0.0.11", ssh_username="u", ssh_password=""))
    ac_repository = AcRepository(database)
    ac_repository.replace_fit_ap_resources(
        "ac-1",
        [
            {"ap_uuid": "ap-ok", "ap_name": "AP-OK", "ap_ip": "10.0.0.10"},
            {"ap_uuid": "ap-no-ip", "ap_name": "AP-NO-IP", "ap_ip": ""},
            {"ap_uuid": "ap-no-password", "ap_name": "AP-NO-PASSWORD", "ap_ip": "10.0.0.11"},
        ],
    )

    targets, skipped = build_trackside_ap_targets(ac_repository, device_repository, [{"ap_uuid": "ap-ok"}, {"ap_uuid": "ap-no-ip"}, {"ap_uuid": "ap-no-password"}])

    assert [target.device_id for target in targets] == [connectable.id]
    assert {item.name for item in skipped} == {"AP-NO-IP", "AP-NO-PASSWORD"}


def test_trackside_collection_dedupes_by_device_id_and_uses_default_concurrency(tmp_path):
    database = make_database(tmp_path)
    repository = DeviceRepository(database)
    groups = DeviceGroupRepository(database, "demo")
    station = groups.create("车站")
    shared = repository.create(Device(name="Shared", group_id=station.id, device_type="SW", ip_address="10.0.0.10", ssh_username="u", ssh_password="p"))
    ac_repository = AcRepository(database)
    ac_repository.replace_fit_ap_resources("ac-1", [{"ap_uuid": "ap-shared", "ap_name": "Shared", "ap_ip": "10.0.0.10"}])
    switch_targets, _ = build_station_switch_targets(repository, "demo")
    ap_targets, _ = build_trackside_ap_targets(ac_repository, repository, [{"ap_uuid": "ap-shared"}])

    assert DEFAULT_TRACKSIDE_OPTICAL_CONCURRENCY == 1000
    assert len(dedupe_targets([*switch_targets, *ap_targets])) == 1
    assert switch_targets[0].device_id == shared.id


def test_trackside_optical_collection_runs_commands_writes_database_and_skips_raw_files(tmp_path, monkeypatch):
    database = make_database(tmp_path)
    repository = DeviceRepository(database)
    groups = DeviceGroupRepository(database, "demo")
    station = groups.create("车站")
    repository.create(Device(name="OK", group_id=station.id, device_type="SW", ip_address="10.0.0.10", ssh_username="u", ssh_password="p"))
    repository.create(Device(name="FAIL", group_id=station.id, device_type="SW", ip_address="10.0.0.99", ssh_username="u", ssh_password="p"))
    FakeOpticalConnection.instances = []
    monkeypatch.setattr(trackside_optical_collection.netmiko_connection, "ConnectHandler", FakeOpticalConnection)

    result = collect_trackside_optical(repository, "demo", PathResolver(tmp_path), [], concurrency=DEFAULT_TRACKSIDE_OPTICAL_CONCURRENCY)

    assert result.concurrency == 1000
    assert result.success_count == 1
    assert result.failed_count == 1
    assert any(connection.commands == list(TRACKSIDE_OPTICAL_COMMANDS) for connection in FakeOpticalConnection.instances)
    assert not (result.session_dir / "raw").exists()
    assert (result.session_dir / "session_meta.json").exists()
    parsed_dir = PathResolver(tmp_path).trackside_ap_update_parsed_session_dir("demo", result.session_id)
    with sqlite3.connect(parsed_dir / "trackside_update_results.sqlite") as conn:
        rows = conn.execute("SELECT device_name, rx_power, error_message FROM optical_results").fetchall()
    assert len(rows) >= 2
    assert any(row[1] == "-6.10" for row in rows)
    assert any(row[2] for row in rows)
    ok_device = next(device for device in repository.list() if device.name == "OK")
    interfaces = DeviceFactRepository(database).list_device_interfaces(ok_device.device_uuid)
    assert interfaces[0]["pvid"] == "921"
    assert interfaces[0]["description"] == "To AP"


def test_trackside_update_combines_fit_ap_service_and_station_switch_collection(tmp_path, monkeypatch):
    database = make_database(tmp_path)
    repository = DeviceRepository(database)
    groups = DeviceGroupRepository(database, "demo")
    station = groups.create("车站")
    switch = repository.create(Device(name="SW", group_id=station.id, device_type="SW", ip_address="10.0.0.10", ssh_username="u", ssh_password="p"))
    ac = repository.create(make_ac_device())
    ac_repo = AcRepository(database)
    ac_repo.replace_fit_ap_resources(
        ac.device_uuid,
        [
            {"ap_uuid": "ap-1", "serial_number": "SN-1", "ap_name": "AP1", "ap_ip": "10.0.0.21"},
            {"ap_uuid": "ap-2", "serial_number": "SN-2", "ap_name": "AP2", "ap_ip": "10.0.0.22"},
            {"ap_uuid": "ap-skip", "serial_number": "SN-SKIP", "ap_name": "AP-SKIP", "ap_ip": ""},
        ],
    )
    paths = PathResolver(tmp_path)
    fit_calls = []
    resource_calls = []

    def fake_resource_collect(ac_device, site_name, repository=None, paths=None, refresh_ac_overview=True):
        resource_calls.append((ac_device.device_uuid, site_name, refresh_ac_overview))
        run_dir = paths.trackside_ap_raw_dir(site_name) / "ac" / "resource-run"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "resource.log").write_text("resource raw", encoding="utf-8")
        repository.replace_fit_ap_resources(
            ac_device.device_uuid,
            [
                {"ap_uuid": "ap-1", "serial_number": "SN-1", "ap_name": "AP1", "ap_ip": "10.0.0.21"},
                {"ap_uuid": "ap-2", "serial_number": "SN-2", "ap_name": "AP2", "ap_ip": "10.0.0.22"},
                {"ap_uuid": "ap-skip", "serial_number": "SN-SKIP", "ap_name": "AP-SKIP", "ap_ip": ""},
            ],
        )
        return SimpleNamespace(success=True, collect_run_uuid="resource-run", error_message=None)

    def fake_fit_collect(
        ac_device,
        site_name,
        repository=None,
        paths=None,
        max_workers=None,
        target_ap_uuids=None,
        target_ap_macs=None,
        target_ap_names=None,
        target_stations=None,
    ):
        fit_calls.append((ac_device.device_uuid, site_name, max_workers, target_ap_uuids, target_ap_macs, target_ap_names, target_stations))
        run_dir = paths.trackside_ap_raw_dir(site_name) / "ac" / "fit-run" / "fit_ap"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "AP1.log").write_text("fit raw", encoding="utf-8")
        return FitApOpticalCollectResult(True, False, str(ac_device.device_uuid), "fit-run", 2, 0, None)

    FakeOpticalConnection.instances = []
    monkeypatch.setattr(trackside_optical_collection, "collect_h3c_ac_resources", fake_resource_collect)
    monkeypatch.setattr(trackside_optical_collection, "collect_h3c_fit_ap_optical", fake_fit_collect)
    monkeypatch.setattr(trackside_optical_collection.netmiko_connection, "ConnectHandler", FakeOpticalConnection)

    result = collect_trackside_optical(repository, "demo", paths, [], concurrency=DEFAULT_TRACKSIDE_OPTICAL_CONCURRENCY)

    assert resource_calls == [(ac.device_uuid, "demo", False)]
    assert fit_calls == [(ac.device_uuid, "demo", 1000, None, None, None, None)]
    assert result.fit_ap_total == 3
    assert result.station_switch_total == 1
    assert result.success_count == 3
    assert result.failed_count == 0
    assert result.skipped_count == 1
    assert result.target_count == 4
    assert not (result.session_dir / "raw").exists()
    assert switch.id is not None


def test_trackside_ap_update_scopes_switch_to_target_ap_and_reports_offline(tmp_path, monkeypatch):
    database = make_database(tmp_path)
    repository = DeviceRepository(database)
    target_switch = create_station_switch(repository, "demo", name="SW-A", station="Station A", ip_address="10.0.0.10", ssh_username="u", ssh_password="p")
    create_station_switch(repository, "demo", name="SW-B", station="Station A", ip_address="10.0.0.11", ssh_username="u", ssh_password="p")
    ac = repository.create(make_ac_device())
    ac_repo = AcRepository(database)
    ac_repo.replace_fit_ap_resources(
        ac.device_uuid,
        [
            {"ap_uuid": "ap-1", "ap_name": "AP1", "ap_mac": "bc5a-3457-cbe0", "ap_ip": "10.0.0.21", "site": "Station A", "state": "R"},
            {"ap_uuid": "ap-2", "ap_name": "AP2", "ap_mac": "bc5a-3457-cbe1", "ap_ip": "10.0.0.22", "site": "Station A", "state": "R"},
        ],
    )
    paths = PathResolver(tmp_path)
    fit_calls = []

    def fake_resource_collect(ac_device, site_name, repository=None, paths=None, refresh_ac_overview=True):
        repository.replace_fit_ap_resources(
            ac_device.device_uuid,
            [
                {"ap_uuid": "ap-1", "ap_name": "AP1", "ap_mac": "bc5a-3457-cbe0", "ap_ip": "10.0.0.21", "site": "Station A", "state": "I", "state_display": "Idle"},
                {"ap_uuid": "ap-2", "ap_name": "AP2", "ap_mac": "bc5a-3457-cbe1", "ap_ip": "10.0.0.22", "site": "Station A", "state": "R", "state_display": "Online"},
            ],
        )
        return SimpleNamespace(success=True, collect_run_uuid="resource-run", error_message=None)

    def fake_fit_collect(
        ac_device,
        site_name,
        repository=None,
        paths=None,
        max_workers=None,
        target_ap_uuids=None,
        target_ap_macs=None,
        target_ap_names=None,
        target_stations=None,
    ):
        fit_calls.append((target_ap_uuids, target_ap_macs, target_ap_names, target_stations))
        return FitApOpticalCollectResult(True, False, str(ac_device.device_uuid), "fit-run", 1, 0, None)

    FakeOpticalConnection.instances = []
    monkeypatch.setattr(trackside_optical_collection, "collect_h3c_ac_resources", fake_resource_collect)
    monkeypatch.setattr(trackside_optical_collection, "collect_h3c_fit_ap_optical", fake_fit_collect)
    monkeypatch.setattr(trackside_optical_collection.netmiko_connection, "ConnectHandler", FakeOpticalConnection)

    result = collect_trackside_optical(
        repository,
        "demo",
        paths,
        [{"site": "Station A", "ap_uuid": "ap-1", "ap_name": "AP1", "device_uuid": target_switch.device_uuid, "device_name": target_switch.name}],
        concurrency=DEFAULT_TRACKSIDE_OPTICAL_CONCURRENCY,
        target_ap_uuid="ap-1",
    )

    assert [connection.host for connection in FakeOpticalConnection.instances] == ["10.0.0.10"]
    assert fit_calls == [(["ap-1"], None, None, ["Station A"])]
    assert result.scope == "ap"
    assert result.target_label == "AP1"
    assert result.target_ap_offline is True
    assert result.switch_scope == "ap_switch"
    assert result.switch_scope_reason == "current_trackside_row"
    assert result.station_switch_total == 1
    with (result.session_dir / "session_meta.json").open(encoding="utf-8") as handle:
        meta = json.load(handle)
    assert meta["target_ap_offline"] is True
    assert meta["switch_scope"] == "ap_switch"


def test_device_detail_trackside_ap_business_tab_displays_joined_data(tmp_path):
    app()
    database = make_database(tmp_path)
    device_repository = DeviceRepository(database)
    switch = device_repository.create(Device(name="HX_1", station="Station A", ip_address="10.0.0.2"))
    fact_repository = DeviceFactRepository(database)
    fact_repository.replace_device_interfaces(
        switch.device_uuid,
        [{"interface_name": "GigabitEthernet2/0/10", "description": "To_AP10", "link_status": "UP", "protocol_status": "UP", "collected_at": "2026-01-01T00:00:00"}],
    )
    fact_repository.replace_optical_modules(
        switch.device_uuid,
        [{"interface_name": "GigabitEthernet2/0/10", "rx_power": "-6.10", "status": "normal", "collected_at": "2026-01-01T00:00:00"}],
    )
    fact_repository.replace_lldp_neighbors(
        switch.device_uuid,
        [{"local_interface": "GE2/0/10", "neighbor_mac": "bc5a-3457-cbe0", "neighbor_interface": "GigabitEthernet1/0/2", "collected_at": "2026-01-01T00:00:00"}],
    )
    ac = device_repository.create(make_ac_device())
    AcRepository(database).replace_fit_ap_optical(
        ac.device_uuid,
        [{"ap_uuid": "ap-10", "ap_mac": "bc5a-3457-cbe0", "ap_name": "AP10", "neighbor_device_name": "HX_1", "neighbor_interface": "GigabitEthernet2/0/10", "rx_power": "-14.35", "rx_low_alarm": "-19.00", "rx_low_warning": "-16.99"}],
    )

    dialog = DeviceDetailDialog(I18n("en_US"), fact_repository, switch)
    table = dialog.tabs.widget(4).findChild(QTableWidget)

    assert dialog.tabs.tabText(4) == "Trackside AP Business"
    fields = [field for _key, field in TRACKSIDE_AP_DEVICE_COLUMNS]
    assert table.item(0, 0).text() == "GigabitEthernet2/0/10"
    assert "switch_tx_power" not in fields
    assert table.item(0, fields.index("port_type")).text() == "unknown"
    assert table.item(0, fields.index("switch_rx_power")).text() == "-6.10"
    assert table.item(0, fields.index("switch_optical_status")).text() == "Unknown"
    assert table.item(0, fields.index("ap_mac")).text() == "bc5a-3457-cbe0"
    assert table.item(0, fields.index("ap_name")).text() == "AP10"
    assert table.item(0, fields.index("ap_rx_power")).text() == "-14.35"
    assert table.item(0, fields.index("ap_optical_status")).text() == "Notice"
    assert table.item(0, 0).background().color().name() == "#fbbf24"
    assert table.item(0, 0).foreground().color().name() == "#111827"


def test_device_detail_interface_table_supports_pagination(tmp_path):
    app()
    database = make_database(tmp_path)
    repository = DeviceFactRepository(database)
    device = Device(name="HX_1", device_uuid="sw-1", ip_address="10.0.0.2")
    repository.replace_device_interfaces(
        "sw-1",
        [
            {"interface_name": f"GigabitEthernet1/0/{index}", "description": f"Port {index}", "collected_at": "2026-01-01T00:00:00"}
            for index in range(1, 251)
        ],
    )

    dialog = DeviceDetailDialog(I18n("en_US"), repository, device)
    table = dialog.tabs.widget(1).findChild(QTableWidget)

    assert table.rowCount() == 200
    assert dialog.tabs.widget(1).findChild(PaginationWidget).state.total_items == 250


def test_trackside_ap_business_moved_to_rail_transit_first_tab_and_exports(tmp_path):
    from openpyxl import load_workbook

    app()
    database = make_database(tmp_path)
    device_repository = DeviceRepository(database)
    switch = create_station_switch(device_repository, "demo", name="HX_1", station="Station A", ip_address="10.0.0.2")
    other = create_station_switch(device_repository, "demo", name="HX_2", station="Station B", ip_address="10.0.0.3")
    fact_repository = DeviceFactRepository(database)
    fact_repository.replace_device_interfaces(
        switch.device_uuid,
        [{"interface_name": "GigabitEthernet2/0/10", "description": "To_AP10", "link_status": "UP", "port_status": "trunk", "pvid": "1", "vlan": "10", "collected_at": "2026-01-01T00:00:00"}],
    )
    fact_repository.replace_device_interfaces(
        other.device_uuid,
        [{"interface_name": "GigabitEthernet2/0/20", "description": "To_AP20", "link_status": "DOWN", "collected_at": "2026-01-01T00:00:00"}],
    )
    fact_repository.replace_optical_modules(
        switch.device_uuid,
        [{"interface_name": "GigabitEthernet2/0/10", "rx_power": "-6.10", "status": "normal", "collected_at": "2026-01-01T00:00:00"}],
    )
    fact_repository.replace_optical_modules(
        other.device_uuid,
        [{"interface_name": "GigabitEthernet2/0/20", "rx_power": "-8.50", "rx_low_alarm": "-20.00", "rx_low_warning": "-15.00", "collected_at": "2026-01-01T00:00:00"}],
    )
    fact_repository.replace_lldp_neighbors(
        switch.device_uuid,
        [{"local_interface": "GE2/0/10", "neighbor_mac": "bc5a-3457-cbe0", "neighbor_interface": "GigabitEthernet1/0/2", "collected_at": "2026-01-01T00:00:00"}],
    )
    fact_repository.replace_lldp_neighbors(
        other.device_uuid,
        [{"local_interface": "GE2/0/20", "neighbor_mac": "bc5a-3457-cbe1", "neighbor_interface": "GigabitEthernet1/0/2", "collected_at": "2026-01-01T00:00:00"}],
    )
    ac = device_repository.create(make_ac_device())
    repository = AcRepository(database)
    repository.replace_fit_ap_optical(
        ac.device_uuid,
        [
            {"ap_uuid": "ap-10", "ap_mac": "bc5a-3457-cbe0", "ap_name": "AP10", "neighbor_device_name": "HX_1", "neighbor_interface": "GigabitEthernet2/0/10", "rx_power": "-14.35", "rx_low_alarm": "-19.00", "rx_low_warning": "-16.99"},
            {"ap_uuid": "ap-20", "ap_mac": "bc5a-3457-cbe1", "ap_name": "AP20", "neighbor_device_name": "HX_2", "neighbor_interface": "GigabitEthernet2/0/20", "rx_power": "-20.00", "rx_low_alarm": "-19.00", "rx_low_warning": "-16.99"},
        ],
    )

    ac_page = AcManagementPage(device_repository, I18n("en_US"), "demo")
    assert "Trackside AP Business" not in [ac_page.tabs.tabText(index) for index in range(ac_page.tabs.count())]

    rail_page = RailTransitPage(device_repository, I18n("en_US"), "demo", PathResolver(tmp_path))
    assert rail_page.tabs.tabText(0) == "Train Online"
    assert rail_page.tabs.tabText(1) == "Car Network Diagnostic"
    assert rail_page.tabs.tabText(2) == "Trackside AP Service"
    assert rail_page.tabs.tabText(3) == "MR Raw MESH Log Analysis"
    assert rail_page.tabs.tabText(4) == "Onboard MR Realtime Collection"
    assert rail_page.tabs.tabText(5) == "Onboard MR Collection Analysis"
    assert rail_page.tabs.currentIndex() == 0
    rail_page._ensure_feature_page("rail.trackside_ap_business")
    page = rail_page.trackside_page
    assert isinstance(page, TracksideApServicePage)
    page.refresh_async(force=True)
    process_events_until(lambda: page.has_loaded and not page.is_loading)
    assert page.trackside_table.rowCount() == 2
    fields = [field for _key, field in TRACKSIDE_AP_BUSINESS_COLUMNS]
    assert "match_source" not in fields
    assert "switch_rx_power" in fields
    assert "switch_tx_power" not in fields
    assert fields[fields.index("interface_name") + 1] == "link_status"
    assert [key for key, _field in TRACKSIDE_AP_BUSINESS_COLUMNS][fields.index("link_status")] == "details.link"
    assert page.trackside_table.horizontalHeaderItem(fields.index("link_status")).text() == "Link"
    assert page.trackside_table.item(0, fields.index("link_status")).text() == "UP"
    assert page.trackside_table.item(0, fields.index("port_type")).text() == "trunk"
    assert page.trackside_table.item(0, fields.index("port_type")).text() not in {"UP", "DOWN"}
    assert page.trackside_table.item(0, fields.index("switch_rx_power")).text() == "-6.10"
    assert page.trackside_table.item(0, fields.index("switch_optical_status")).text() == "Unknown"
    assert page.trackside_table.item(0, fields.index("ap_mac")).text() == "bc5a-3457-cbe0"
    assert page.trackside_table.item(0, fields.index("ap_name")).text() == "AP10"
    assert page.trackside_table.item(0, fields.index("ap_rx_power")).text() == "-14.35"
    assert page.trackside_table.item(0, fields.index("ap_optical_status")).text() == "Notice"
    assert page.trackside_table.item(0, 0).background().color().name() == "#fbbf24"
    assert page.trackside_table.item(0, 0).foreground().color().name() == "#111827"

    page.trackside_site_filter.setCurrentIndex(page.trackside_site_filter.findData("Station B"))
    assert page.trackside_table.rowCount() == 1
    assert page.trackside_table.item(0, 0).text() == "Station B"
    assert page.trackside_table.item(0, fields.index("link_status")).text() == "DOWN"
    assert page.trackside_table.item(0, fields.index("port_type")).text() == "unknown"

    export_path = tmp_path / "trackside.xlsx"
    export_trackside_ap_business_xlsx(export_path, page.filtered_trackside_rows(), TRACKSIDE_AP_BUSINESS_COLUMNS, [page.i18n.t(key) for key, _field in TRACKSIDE_AP_BUSINESS_COLUMNS])
    workbook = load_workbook(export_path)
    sheet = workbook["轨旁AP业务"]
    headers = [cell.value for cell in sheet[1]]
    assert headers == [page.i18n.t(key) for key, _field in TRACKSIDE_AP_BUSINESS_COLUMNS]
    assert headers[headers.index("Interface Name") + 1] == "Link"
    assert "Switch Optical Status" in headers
    assert "AP Optical Alarm" in headers
    assert "Indoor Switch TX Power(dBm)" not in headers
    assert sheet.cell(2, headers.index("Link") + 1).value == "DOWN"
    assert sheet.cell(2, headers.index("Port Type") + 1).value == "unknown"
    assert sheet.cell(2, headers.index("Switch Optical Status") + 1).value == format_trackside_display_value("switch_optical_status", page.filtered_trackside_rows()[0])
    assert sheet["A1"].font.bold
    assert sheet.freeze_panes == "A2"
    assert sheet["A1"].alignment.horizontal == "center"
    assert sheet["A2"].fill.fgColor.rgb == "00FFE4E6"


def test_trackside_ap_business_visible_columns_hide_internal_fields(tmp_path):
    app()
    database = make_database(tmp_path)
    page = TracksideApServicePage(DeviceRepository(database), I18n("en_US"), "demo", PathResolver(tmp_path))
    page.trackside_rows = [
        {
            "site": "Station A",
            "device_name": "HX_1",
            "interface_name": "GigabitEthernet1/0/1",
            "ap_ip": "10.0.0.10",
            "host": "10.0.0.10",
            "source_device": "AC-1",
            "collection_status": "success",
        }
    ]
    page.apply_trackside_pagination()

    headers = [page.trackside_table.horizontalHeaderItem(index).text() for index in range(page.trackside_table.columnCount())]
    assert "IP Address" not in headers
    assert "Host" not in headers
    assert "Host Address" not in headers
    assert "Management IP" not in headers
    assert "Source Device" not in headers
    assert "Collection Status" not in headers
    assert "Match Source" not in headers
    assert "trackside.collection_status" not in headers
    assert "ap_ip" in TRACKSIDE_AP_BUSINESS_INTERNAL_FIELDS
    assert "source_device" in TRACKSIDE_AP_BUSINESS_INTERNAL_FIELDS
    assert "collection_status" in TRACKSIDE_AP_BUSINESS_INTERNAL_FIELDS
    assert all(field not in TRACKSIDE_AP_BUSINESS_INTERNAL_FIELDS for _key, field in TRACKSIDE_AP_BUSINESS_COLUMNS)
    assert page.trackside_table.columnCount() == len(TRACKSIDE_AP_BUSINESS_COLUMNS)


def test_trackside_context_menu_contains_station_and_ap_refresh(tmp_path):
    app()
    database = make_database(tmp_path)
    page = TracksideApServicePage(DeviceRepository(database), I18n("en_US"), "demo", PathResolver(tmp_path))
    page.trackside_rows = [
        {
            "site": "Station A",
            "device_name": "HX_1",
            "interface_name": "GigabitEthernet1/0/1",
            "ap_uuid": "ap-1",
            "ap_name": "AP-A",
            "ap_mac": "0011-2233-4455",
        }
    ]
    page._set_trackside_site_filter_items(page.trackside_rows)
    page.apply_trackside_pagination()

    menu = page.build_trackside_context_menu(0, 0)
    actions = {action.text(): action for action in menu.actions() if action.text()}

    assert "Update This Station" in actions
    assert "Update This AP" in actions
    assert actions["Update This Station"].isEnabled()
    assert actions["Update This AP"].isEnabled()


def test_trackside_ap_business_export_excludes_internal_fields(tmp_path):
    from openpyxl import load_workbook

    rows = [
        {
            "site": "Station A",
            "device_name": "HX_1",
            "interface_name": "GigabitEthernet1/0/1",
            "ap_ip": "10.0.0.10",
            "host": "10.0.0.10",
            "source_device": "AC-1",
            "collection_status": "success",
        }
    ]
    i18n = I18n("en_US")
    export_path = tmp_path / "trackside_hidden.xlsx"

    export_trackside_ap_business_xlsx(export_path, rows, TRACKSIDE_AP_BUSINESS_COLUMNS, [i18n.t(key) for key, _field in TRACKSIDE_AP_BUSINESS_COLUMNS])

    sheet = load_workbook(export_path).active
    headers = [cell.value for cell in sheet[1]]
    assert "TX功率" not in headers
    assert "IP Address" not in headers
    assert "Host" not in headers
    assert "Host Address" not in headers
    assert "Management IP" not in headers
    assert "Source Device" not in headers
    assert "Collection Status" not in headers
    assert "Match Source" not in headers
    assert "trackside.collection_status" not in headers
    assert "collection_status" not in headers
    assert "source_device" not in headers
    assert "host" not in headers


def test_trackside_ap_business_export_formats_missing_ap_side_as_dash(tmp_path):
    from openpyxl import load_workbook

    rows = [
        {
            "site": "Station A",
            "device_name": "HX_1",
            "interface_name": "GigabitEthernet1/0/1",
            "switch_optical_status": "normal",
            "ap_mac": None,
            "ap_name": None,
            "ap_rx_power": None,
            "ap_tx_power": None,
            "ap_optical_status": "no_module",
            "ap_side_has_data": False,
        },
        {
            "site": "Station A",
            "device_name": "HX_1",
            "interface_name": "GigabitEthernet1/0/2",
            "switch_optical_status": "normal",
            "ap_mac": "bc5a-3457-cbe1",
            "ap_name": "AP23",
            "ap_rx_power": None,
            "ap_tx_power": None,
            "ap_optical_status": "no_module",
            "raw_status": "no module",
            "ap_side_has_data": True,
        },
    ]
    i18n = I18n("zh_CN")
    export_path = tmp_path / "trackside_ap_missing.xlsx"

    export_trackside_ap_business_xlsx(export_path, rows, TRACKSIDE_AP_BUSINESS_COLUMNS, [i18n.t(key) for key, _field in TRACKSIDE_AP_BUSINESS_COLUMNS])

    sheet = load_workbook(export_path).active
    headers = [cell.value for cell in sheet[1]]
    alarm_column = headers.index("AP侧光告警") + 1
    ap_mac_column = headers.index("AP_MAC") + 1
    ap_name_column = headers.index("AP名称") + 1
    ap_rx_column = headers.index("AP侧收光(dBm)") + 1
    assert "TX功率" not in headers
    assert sheet.cell(2, alarm_column).value == "-"
    assert sheet.cell(2, ap_mac_column).value == "-"
    assert sheet.cell(2, ap_name_column).value == "-"
    assert sheet.cell(2, ap_rx_column).value == "-"
    assert sheet.cell(2, alarm_column).value != "无光模块"
    assert sheet.cell(3, alarm_column).value == "无光模块"


def test_trackside_ap_business_export_switch_optical_summary_missing_module_count(tmp_path):
    from openpyxl import load_workbook

    export_path = tmp_path / "trackside_switch_summary.xlsx"
    i18n = I18n("zh_CN")
    rows = [
        *(
            {
                "site": "01小洋江站",
                "device_name": "01-小洋江站1",
                "interface_name": f"GigabitEthernet2/0/{index}",
                "switch_optical_status": "normal",
            }
            for index in range(1, 29)
        ),
        {
            "site": "01小洋江站",
            "device_name": "01-小洋江站1",
            "interface_name": "GigabitEthernet2/0/36",
            "switch_optical_status": "no_module",
        },
        {
            "site": "01小洋江站",
            "device_name": "01-小洋江站1",
            "interface_name": "GigabitEthernet2/0/37",
            "switch_optical_status": "no_module",
        },
        {
            "site": "01小洋江站",
            "device_name": "01-小洋江站1",
            "interface_name": "GigabitEthernet2/0/38",
            "switch_optical_status": "no_module",
        },
        {
            "site": "02云龙火车站站",
            "device_name": "02-云龙火车站1",
            "interface_name": "GigabitEthernet2/0/1",
            "switch_optical_status": "normal",
        },
        {
            "site": "03横溪站",
            "device_name": "03-横溪站1",
            "switch_optical_status": "normal",
            "missing_module_ports": "GE2/0/36, GE2/0/37",
        },
    ]
    overview_headers = [i18n.t(key) for key, _field in AP_ONLINE_OVERVIEW_COLUMNS]
    trackside_headers = [i18n.t(key) for key, _field in TRACKSIDE_AP_BUSINESS_COLUMNS]

    export_trackside_ap_business_xlsx(
        export_path,
        rows,
        TRACKSIDE_AP_BUSINESS_COLUMNS,
        trackside_headers,
        [{"site": "合计", "total": 1, "online": 1, "offline": 0, "online_rate": "100.0%", "remark": ""}],
        AP_ONLINE_OVERVIEW_COLUMNS,
        overview_headers,
    )

    workbook = load_workbook(export_path)
    summary = workbook["交换机光模块统计"]
    assert [cell.value for cell in summary[1]] == ["交换机", "光模块数量", "未插光模块端口数量", "未插光模块端口"]
    rows_by_switch = {
        summary.cell(row=index, column=1).value: [summary.cell(row=index, column=column).value for column in range(2, 5)]
        for index in range(2, summary.max_row + 1)
    }
    assert rows_by_switch["01-小洋江站1"] == [28, 3, "GE2/0/36, GE2/0/37, GE2/0/38"]
    assert rows_by_switch["02-云龙火车站1"] == [1, 0, "-"]
    assert rows_by_switch["03-横溪站1"] == [1, 2, "GE2/0/36, GE2/0/37"]
    assert summary.freeze_panes == "A2"
    assert summary["A1"].font.bold
    assert summary.column_dimensions["A"].width == 22
    assert summary.column_dimensions["B"].width == 14
    assert summary.column_dimensions["C"].width == 20
    assert summary.column_dimensions["D"].width == 80
    assert [cell.value for cell in workbook["轨旁AP业务"][1]] == trackside_headers
    assert [cell.value for cell in workbook["AP上线情况概览"][1]] == overview_headers


def test_trackside_ap_page_formats_missing_ap_side_as_dash(tmp_path):
    app()
    database = make_database(tmp_path)
    page = TracksideApServicePage(DeviceRepository(database), I18n("zh_CN"), "demo", PathResolver(tmp_path))
    page.trackside_rows = [
        {
            "site": "Station A",
            "device_name": "HX_1",
            "interface_name": "GigabitEthernet1/0/1",
            "switch_optical_status": "normal",
            "ap_mac": None,
            "ap_name": None,
            "ap_rx_power": None,
            "ap_tx_power": None,
            "ap_optical_status": "no_module",
            "ap_side_has_data": False,
        }
    ]
    page.apply_trackside_pagination()
    fields = [field for _key, field in TRACKSIDE_AP_BUSINESS_COLUMNS]

    assert page.trackside_table.item(0, fields.index("ap_mac")).text() == "-"
    assert page.trackside_table.item(0, fields.index("ap_name")).text() == "-"
    assert page.trackside_table.item(0, fields.index("ap_rx_power")).text() == "-"
    assert page.trackside_table.item(0, fields.index("ap_optical_status")).text() == "-"
    assert "ap_tx_power" not in fields
    assert page.trackside_table.item(0, 0).background().color().name() != "#f87171"


def test_trackside_ap_business_export_uses_ac_online_overview_service_rows(tmp_path):
    from openpyxl import load_workbook

    export_path = tmp_path / "trackside_overview.xlsx"
    i18n = I18n("zh_CN")
    trackside_rows = [
        {"site": "Demo", "device_name": "SW-A", "interface_name": "GigabitEthernet1/0/1", "ap_uuid": "wrong-1", "ap_state": "online"},
        {"site": "\u672a\u5f52\u5c5e", "device_name": "SW-A", "interface_name": "GigabitEthernet1/0/2", "ap_uuid": "wrong-2", "ap_state": "online"},
    ]
    plan_rows = [
        *({"ap_uuid": f"p-a-{index}", "ap_name": f"AP-A-{index}", "site_name": "01小洋江站"} for index in range(30)),
        *({"ap_uuid": f"p-b-{index}", "ap_name": f"AP-B-{index}", "site_name": "02云龙火车站站"} for index in range(918)),
    ]
    resources = [
        *({"ap_uuid": f"p-a-{index}", "ap_name": f"AP-A-{index}", "site": "Demo", "state": "R/M"} for index in range(26)),
        *({"ap_uuid": f"p-b-{index}", "ap_name": f"AP-B-{index}", "site": "体育中心站", "state": "R"} for index in range(747)),
    ]
    overview_rows = build_ap_online_overview_rows(
        planned_aps=plan_rows,
        fit_ap_resources=resources,
        capacity_details={
            "01小洋江站": {"ap_total": 30, "remark": "-"},
            "02云龙火车站站": {"ap_total": 918, "remark": "-"},
        },
    )

    export_trackside_ap_business_xlsx(
        export_path,
        trackside_rows,
        TRACKSIDE_AP_BUSINESS_COLUMNS,
        [i18n.t(key) for key, _field in TRACKSIDE_AP_BUSINESS_COLUMNS],
        overview_rows,
        AP_ONLINE_OVERVIEW_COLUMNS,
        [i18n.t(key) for key, _field in AP_ONLINE_OVERVIEW_COLUMNS],
    )

    overview = load_workbook(export_path)["AP\u4e0a\u7ebf\u60c5\u51b5\u6982\u89c8"]
    rows = [[cell.value for cell in row] for row in overview.iter_rows(values_only=False)]
    assert rows[1] == ["01小洋江站", "30", "26", "4", "86.7%", "-"]
    assert rows[-1] == ["\u5408\u8ba1", "948", "773", "175", "81.5%", "-"]
    assert ["Demo", "1", "1", "0", "100.0%", "-"] not in rows


def test_ac_overview_page_rows_match_trackside_export_overview_sheet(tmp_path):
    from openpyxl import load_workbook

    app()
    database = make_database(tmp_path)
    device_repository = DeviceRepository(database)
    ac = device_repository.create(make_ac_device())
    repository = AcRepository(database)
    for index in range(3):
        repository.upsert_fit_ap_metadata({"ap_uuid": f"plan-a-{index}", "ap_name": f"AP-A-{index}", "site_name": "Station A"})
    for index in range(2):
        repository.upsert_fit_ap_metadata({"ap_uuid": f"plan-b-{index}", "ap_name": f"AP-B-{index}", "site_name": "Station B"})
    repository.replace_fit_ap_resources(
        ac.device_uuid,
        [
            {"ap_uuid": "plan-a-0", "serial_number": "SNA0", "ap_name": "AP-A-0", "state": "R/M"},
            {"ap_uuid": "plan-a-1", "serial_number": "SNA1", "ap_name": "AP-A-1", "state": "I"},
            {"ap_uuid": "plan-b-0", "serial_number": "SNB0", "ap_name": "AP-B-0", "state": "online"},
        ],
    )
    page = AcManagementPage(device_repository, I18n("en_US"), "demo")
    process_events_until(lambda: not page._background_jobs)
    overview_rows = build_ap_online_overview_rows(
        planned_aps=repository.list_fit_ap_metadata(),
        fit_ap_resources=repository.list_fit_ap_resources_with_metadata(ac.device_uuid),
    )
    export_path = tmp_path / "trackside_same_overview.xlsx"

    export_trackside_ap_business_xlsx(
        export_path,
        [],
        TRACKSIDE_AP_BUSINESS_COLUMNS,
        [page.i18n.t(key) for key, _field in TRACKSIDE_AP_BUSINESS_COLUMNS],
        overview_rows,
        AP_ONLINE_OVERVIEW_COLUMNS,
        [page.i18n.t(key) for key, _field in AP_ONLINE_OVERVIEW_COLUMNS],
    )

    overview = load_workbook(export_path)["AP\u4e0a\u7ebf\u60c5\u51b5\u6982\u89c8"]
    exported_rows = [[cell.value for cell in row] for row in overview.iter_rows(values_only=False)]
    assert exported_rows[1:] == [
        ["Station A", "3", "1", "2", "33.3%", "-"],
        ["Station B", "2", "1", "1", "50.0%", "-"],
        ["\u5408\u8ba1", "5", "2", "3", "40.0%", "-"],
    ]
    forbidden_headers = {"RX Power", "TX Power", "Optical Alarm", "Temperature", "Voltage", "Bias Current"}
    assert forbidden_headers.isdisjoint({cell.value for cell in overview[1]})


def test_trackside_ap_business_internal_fields_remain_available_for_update(tmp_path, monkeypatch):
    app()
    captured: dict[str, object] = {}

    class FakeCollectThread(QObject):
        progress_changed = Signal(int, int)
        collect_finished = Signal(object)
        collect_failed = Signal(str)
        finished = Signal()

        def __init__(self, repository, site_name, paths, trackside_rows, concurrency, parent=None):
            super().__init__(parent)
            captured["rows"] = trackside_rows
            captured["site_name"] = site_name
            captured["concurrency"] = concurrency

        def start(self):
            captured["started"] = True

        def cancel(self):
            captured["cancelled"] = True

    import netconsole.ui.pages.trackside_ap_service_page as page_module

    monkeypatch.setattr(page_module, "TracksideOpticalCollectThread", FakeCollectThread)
    database = make_database(tmp_path)
    page = TracksideApServicePage(DeviceRepository(database), I18n("en_US"), "demo", PathResolver(tmp_path))
    page.trackside_rows = [
        {
            "site": "Station A",
            "device_name": "HX_1",
            "interface_name": "GigabitEthernet1/0/1",
            "host": "10.0.0.10",
            "ap_ip": "10.0.0.10",
            "source_device": "AC-1",
            "collection_status": "success",
        }
    ]
    page.apply_trackside_pagination()

    page.start_optical_update()

    assert captured["started"] is True
    assert captured["rows"][0]["host"] == "10.0.0.10"
    assert captured["rows"][0]["ap_ip"] == "10.0.0.10"
    assert captured["rows"][0]["source_device"] == "AC-1"
    assert captured["rows"][0]["collection_status"] == "success"
    visible_values = [
        page.trackside_table.item(row, column).text()
        for row in range(page.trackside_table.rowCount())
        for column in range(page.trackside_table.columnCount())
        if page.trackside_table.item(row, column) is not None
    ]
    assert "10.0.0.10" not in visible_values
    assert "AC-1" not in visible_values
    assert "success" not in visible_values


def test_trackside_ap_business_update_shows_async_stage_state(tmp_path, monkeypatch):
    app()

    class FakeCollectThread(QObject):
        stage_changed = Signal(str)
        progress_changed = Signal(int, int)
        collect_finished = Signal(object)
        collect_failed = Signal(str)
        finished = Signal()

        def __init__(self, repository, site_name, paths, trackside_rows, concurrency, parent=None):
            super().__init__(parent)
            self.cancelled = False

        def start(self):
            self.stage_changed.emit("trackside_ap.stage_collect_lldp")

        def cancel(self):
            self.cancelled = True

    import netconsole.ui.pages.trackside_ap_service_page as page_module

    monkeypatch.setattr(page_module, "TracksideOpticalCollectThread", FakeCollectThread)
    page = TracksideApServicePage(DeviceRepository(make_database(tmp_path)), I18n("en_US"), "demo", PathResolver(tmp_path))
    page.trackside_rows = [{"site": "Station A", "device_name": "SW-1", "interface_name": "GigabitEthernet1/0/1"}]
    page.apply_trackside_pagination()
    old_row_count = page.trackside_table.rowCount()

    page.start_optical_update()

    assert page.update_button.text() == "Light Update Running..."
    assert page.full_update_button.isEnabled() is False
    assert page.update_button.isEnabled() is False
    assert page.cancel_update_button.isEnabled() is True
    assert page.update_progress.isHidden() is False
    assert page.trackside_table.rowCount() == old_row_count
    assert page.status_label.text() == "Collecting station switch LLDP..."

    page.cancel_optical_update()

    assert page.cancel_update_button.isEnabled() is False
    assert page.status_label.text() == "Cancelled"


def test_trackside_ap_business_trackside_status_i18n_exists_but_main_table_hides_it(tmp_path):
    app()
    assert I18n("zh_CN").t("trackside.collection_status") == "\u91c7\u96c6\u72b6\u6001"
    assert I18n("en_US").t("trackside.collection_status") == "Collection Status"
    assert I18n("zh_CN").t("trackside.not_collected") == "\u672a\u91c7\u96c6"
    assert I18n("en_US").t("trackside.not_collected") == "Not Collected"

    page = TracksideApServicePage(DeviceRepository(make_database(tmp_path)), I18n("zh_CN"), "demo", PathResolver(tmp_path))
    headers = [page.trackside_table.horizontalHeaderItem(index).text() for index in range(page.trackside_table.columnCount())]
    assert "\u91c7\u96c6\u72b6\u6001" not in headers
    assert "trackside.collection_status" not in headers


def test_trackside_ap_business_hidden_columns_stay_hidden_after_language_switch(tmp_path):
    app()
    i18n = I18n("zh_CN")
    page = TracksideApServicePage(DeviceRepository(make_database(tmp_path)), i18n, "demo", PathResolver(tmp_path))

    i18n.set_language("en_US")
    page.retranslate()
    en_headers = [page.trackside_table.horizontalHeaderItem(index).text() for index in range(page.trackside_table.columnCount())]
    i18n.set_language("zh_CN")
    page.retranslate()
    zh_headers = [page.trackside_table.horizontalHeaderItem(index).text() for index in range(page.trackside_table.columnCount())]

    assert "Source Device" not in en_headers
    assert "Collection Status" not in en_headers
    assert "Host Address" not in en_headers
    assert "\u6765\u6e90\u8bbe\u5907" not in zh_headers
    assert "\u91c7\u96c6\u72b6\u6001" not in zh_headers
    assert "\u4e3b\u673a\u5730\u5740" not in zh_headers
    assert "trackside.collection_status" not in en_headers + zh_headers


def test_trackside_ap_business_header_tooltips_are_readable(tmp_path):
    app()
    page = TracksideApServicePage(DeviceRepository(make_database(tmp_path)), I18n("zh_CN"), "demo", PathResolver(tmp_path))
    fields = [field for _key, field in TRACKSIDE_AP_BUSINESS_COLUMNS]

    expected = {
        "site": page.i18n.t("trackside.tooltip.station"),
        "link_status": page.i18n.t("trackside.tooltip.link"),
        "port_type": page.i18n.t("trackside.tooltip.port_type"),
        "switch_rx_power": page.i18n.t("trackside.tooltip.switch_rx_power"),
        "ap_optical_status": page.i18n.t("trackside.tooltip.ap_optical_status"),
    }
    for field, tooltip in expected.items():
        actual = page.trackside_table.horizontalHeaderItem(fields.index(field)).toolTip()
        assert actual == tooltip
        assert "???" not in actual
        assert "�" not in actual

def test_trackside_ap_business_ignores_legacy_column_width_settings(tmp_path):
    app()
    paths = PathResolver(tmp_path)
    SettingsStore(paths).set_value(
        "trackside_ap_business/table/column_widths",
        {
            "ap_ip": 300,
            "source_device": 301,
            "collection_status": 302,
            "0": 999,
        },
    )
    page = TracksideApServicePage(DeviceRepository(make_database(tmp_path)), I18n("en_US"), "demo", paths)
    page.trackside_rows = [
        {
            "site": "Station A",
            "device_name": "HX_1",
            "interface_name": "GigabitEthernet1/0/1",
            "ap_ip": "10.0.0.10",
            "source_device": "AC-1",
            "collection_status": "success",
        }
    ]

    page.apply_trackside_pagination()

    headers = [page.trackside_table.horizontalHeaderItem(index).text() for index in range(page.trackside_table.columnCount())]
    assert headers == [page.i18n.t(key) for key, _field in TRACKSIDE_AP_BUSINESS_COLUMNS]
    assert page.trackside_table.item(0, 0).text() == "Station A"
    assert "Source Device" not in headers
    assert "Collection Status" not in headers
    assert "TX Power" not in headers


def test_trackside_ap_business_default_widths_and_scrollbar_are_readable(tmp_path):
    app()
    page = TracksideApServicePage(DeviceRepository(make_database(tmp_path)), I18n("en_US"), "demo", PathResolver(tmp_path))
    fields = [field for _key, field in TRACKSIDE_AP_BUSINESS_COLUMNS]

    assert page.trackside_table.horizontalScrollBarPolicy() == Qt.ScrollBarAsNeeded
    assert page.trackside_table.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded
    assert not page.trackside_table.wordWrap()
    assert page.trackside_table.horizontalHeader().sectionResizeMode(0) == QHeaderView.Interactive
    assert page.trackside_table.horizontalHeader().stretchLastSection() is False
    assert page.trackside_table.columnWidth(fields.index("site")) >= 120
    assert page.trackside_table.columnWidth(fields.index("device_name")) >= 160
    assert page.trackside_table.columnWidth(fields.index("interface_name")) >= 190
    assert page.trackside_table.columnWidth(fields.index("ap_mac")) >= 160


def test_trackside_ap_business_column_widths_persist_by_field(tmp_path):
    app()
    paths = PathResolver(tmp_path)
    database = make_database(tmp_path)
    first = TracksideApServicePage(DeviceRepository(database), I18n("en_US"), "demo", paths)
    fields = [field for _key, field in TRACKSIDE_AP_BUSINESS_COLUMNS]
    interface_column = fields.index("interface_name")

    first.trackside_table.setColumnWidth(interface_column, 260)
    first.column_state.save_now()
    first.apply_trackside_pagination()
    first.retranslate()

    reopened = TracksideApServicePage(DeviceRepository(database), I18n("en_US"), "demo", paths)
    reopened_fields = [field for _key, field in TRACKSIDE_AP_BUSINESS_COLUMNS]
    assert reopened.trackside_table.columnWidth(reopened_fields.index("interface_name")) == 260


def test_trackside_ap_business_double_click_interface_opens_history(tmp_path):
    app()
    database = make_database(tmp_path)
    repository = DeviceRepository(database)
    device = repository.create(Device(name="HX_1", ip_address="10.0.0.1"))
    facts = DeviceFactRepository(database)
    facts.append_optical_history(
        {
            "device_uuid": device.device_uuid,
            "interface_name": "GigabitEthernet1/0/1",
            "rx_power": "-6.10",
            "tx_power": "-2.10",
            "collected_at": "2026-01-02T00:00:00",
        }
    )
    page = TracksideApServicePage(repository, I18n("en_US"), "demo", PathResolver(tmp_path))
    page.trackside_rows = [{"site": "A", "device_uuid": device.device_uuid, "device_name": "HX_1", "interface_name": "GigabitEthernet1/0/1"}]
    page.apply_trackside_pagination()

    page.open_interface_history_from_trackside(0)

    assert len(page.history_windows) == 1
    history = page.history_windows[0]
    process_events_until(lambda: history.query_job_id is None)
    assert "Interface Optical History - HX_1 GigabitEthernet1/0/1" == history.windowTitle()
    assert history.parent() is None
    assert history.windowFlags() & Qt.Window
    assert history.windowFlags() & Qt.WindowMinimizeButtonHint
    assert history.windowFlags() & Qt.WindowMaximizeButtonHint
    assert history.windowFlags() & Qt.WindowCloseButtonHint
    assert not history.isModal()
    assert history.table.rowCount() == 1
    assert history.table.item(0, 3).text() == "-6.10"


def test_trackside_ap_business_double_click_interface_without_history_opens_empty_window(tmp_path, monkeypatch):
    app()
    messages: list[str] = []
    monkeypatch.setattr(QMessageBox, "information", lambda _parent, _title, message: messages.append(message))
    database = make_database(tmp_path)
    repository = DeviceRepository(database)
    device = repository.create(Device(name="HX_1", ip_address="10.0.0.1"))
    page = TracksideApServicePage(repository, I18n("en_US"), "demo", PathResolver(tmp_path))
    page.trackside_rows = [{"site": "A", "device_uuid": device.device_uuid, "device_name": "HX_1", "interface_name": "GigabitEthernet1/0/1"}]
    page.apply_trackside_pagination()

    page.open_interface_history_from_trackside(0)

    assert messages == []
    assert len(page.history_windows) == 1
    history = page.history_windows[0]
    process_events_until(lambda: history.query_job_id is None)
    assert history.table.rowCount() == 0
    assert history.status_label.text() == "No optical history was found for this interface"


def test_trackside_ap_business_reuses_same_interface_history_window(tmp_path):
    app()
    database = make_database(tmp_path)
    repository = DeviceRepository(database)
    device = repository.create(Device(name="HX_1", ip_address="10.0.0.1"))
    page = TracksideApServicePage(repository, I18n("en_US"), "demo", PathResolver(tmp_path))
    page.trackside_rows = [{"site": "A", "device_uuid": device.device_uuid, "device_name": "HX_1", "interface_name": "GigabitEthernet1/0/1"}]
    page.apply_trackside_pagination()

    page.open_interface_history_from_trackside(0)
    first = page.history_windows[0]
    page.open_interface_history_from_trackside(0)

    assert len(page.history_windows) == 1
    assert page.history_windows[0] is first


def test_trackside_ap_business_allows_different_interface_history_windows(tmp_path):
    app()
    database = make_database(tmp_path)
    repository = DeviceRepository(database)
    device = repository.create(Device(name="HX_1", ip_address="10.0.0.1"))
    page = TracksideApServicePage(repository, I18n("en_US"), "demo", PathResolver(tmp_path))
    page.trackside_rows = [
        {"site": "A", "device_uuid": device.device_uuid, "device_name": "HX_1", "interface_name": "GigabitEthernet1/0/1"},
        {"site": "A", "device_uuid": device.device_uuid, "device_name": "HX_1", "interface_name": "GigabitEthernet1/0/2"},
    ]
    page.apply_trackside_pagination()

    page.open_interface_history_from_trackside(0)
    page.open_interface_history_from_trackside(1)

    assert len(page.history_windows) == 2
    assert {window.windowTitle() for window in page.history_windows} == {
        "Interface Optical History - HX_1 GigabitEthernet1/0/1",
        "Interface Optical History - HX_1 GigabitEthernet1/0/2",
    }


def test_trackside_interface_history_detail_updates_with_selection(tmp_path):
    app()
    rows = [
        {"collected_at": "2026-01-02T00:00:00", "source_device_name": "HX_1", "interface_name": "GE1/0/1", "rx_power": "-6.10", "raw_log_path": str(tmp_path / "a.log")},
        {"collected_at": "2026-01-03T00:00:00", "source_device_name": "HX_1", "interface_name": "GE1/0/1", "rx_power": "-7.20", "raw_log_path": str(tmp_path / "b.log")},
    ]
    dialog = TracksideInterfaceHistoryDialog(I18n("en_US"), rows, "Interface Optical History - HX_1 GE1/0/1", SettingsStore(PathResolver(tmp_path)))

    assert dialog.detail_table.item(3, 1).text() == "-6.10"
    dialog.table.selectRow(1)
    dialog.refresh_detail()

    assert dialog.detail_table.item(3, 1).text() == "-7.20"
    assert dialog.detail_table.horizontalHeaderItem(0).text() == "Name"
    assert dialog.detail_table.horizontalHeaderItem(1).text() == "Value"


def test_trackside_interface_history_window_flags_and_pin(tmp_path):
    app()
    dialog = TracksideInterfaceHistoryDialog(I18n("en_US"), [], "Interface Optical History - HX_1 GE1/0/1", SettingsStore(PathResolver(tmp_path)))

    assert dialog.parent() is None
    assert dialog.windowFlags() & Qt.Window
    assert dialog.windowFlags() & Qt.WindowMinimizeButtonHint
    assert dialog.windowFlags() & Qt.WindowMaximizeButtonHint
    assert dialog.windowFlags() & Qt.WindowCloseButtonHint
    assert not dialog.isModal()

    dialog.pin_button.setChecked(True)
    assert dialog.windowFlags() & Qt.WindowStaysOnTopHint


def test_trackside_interface_history_column_widths_persist(tmp_path):
    app()
    paths = PathResolver(tmp_path)
    settings = SettingsStore(paths)
    rows = [{"collected_at": "2026-01-02T00:00:00", "source_device_name": "HX_1", "interface_name": "GE1/0/1"}]
    first = TracksideInterfaceHistoryDialog(I18n("en_US"), rows, "Interface Optical History - HX_1 GE1/0/1", settings)
    first.table.setColumnWidth(2, 280)
    first.detail_table.setColumnWidth(1, 420)
    first._save_window_state()

    reopened = TracksideInterfaceHistoryDialog(I18n("en_US"), rows, "Interface Optical History - HX_1 GE1/0/1", SettingsStore(paths))

    assert reopened.table.columnWidth(2) == 280
    assert reopened.detail_table.columnWidth(1) == 420


def test_trackside_ap_business_ap_mac_double_click_opens_existing_ap_detail_by_mac(tmp_path, monkeypatch):
    app()
    opened: list[tuple[str, str]] = []

    class FakeDetail(QWidget):
        def __init__(self, _i18n, _repository, ac_uuid, ap_uuid, parent=None):
            super().__init__(parent)
            opened.append((ac_uuid, ap_uuid))

    import netconsole.ui.pages.trackside_ap_service_page as page_module

    monkeypatch.setattr(page_module, "FitApDetailDialog", FakeDetail)
    database = make_database(tmp_path)
    repository = DeviceRepository(database)
    ac = repository.create(make_ac_device())
    ac_repository = AcRepository(database)
    ac_repository.replace_fit_ap_resources(ac.device_uuid, [{"ap_uuid": "ap-mac", "ap_name": "NameFromMac", "ap_mac": "bc5a-3457-cbe0", "serial_number": "SN1"}])
    ac_repository.replace_fit_ap_resources("ac-other", [{"ap_uuid": "ap-name", "ap_name": "SameName", "ap_mac": "bc5a-3457-cbe1", "serial_number": "SN2"}])
    page = TracksideApServicePage(repository, I18n("en_US"), "demo", PathResolver(tmp_path))
    page.trackside_rows = [{"ap_name": "SameName", "ap_mac": "bc:5a:34:57:cb:e0"}]
    page.apply_trackside_pagination()

    page.open_ap_detail_from_trackside(0)
    process_events_until(lambda: bool(opened))

    assert opened == [(ac.device_uuid, "ap-mac")]


def test_trackside_ap_business_ap_name_double_click_opens_existing_ap_detail_by_name(tmp_path, monkeypatch):
    app()
    opened: list[tuple[str, str]] = []

    class FakeDetail(QWidget):
        def __init__(self, _i18n, _repository, ac_uuid, ap_uuid, parent=None):
            super().__init__(parent)
            opened.append((ac_uuid, ap_uuid))

    import netconsole.ui.pages.trackside_ap_service_page as page_module

    monkeypatch.setattr(page_module, "FitApDetailDialog", FakeDetail)
    database = make_database(tmp_path)
    repository = DeviceRepository(database)
    ac = repository.create(make_ac_device())
    AcRepository(database).replace_fit_ap_resources(ac.device_uuid, [{"ap_uuid": "ap-name", "ap_name": "AP-Name", "ap_mac": "bc5a-3457-cbe1", "serial_number": "SN1"}])
    page = TracksideApServicePage(repository, I18n("en_US"), "demo", PathResolver(tmp_path))
    page.trackside_rows = [{"ap_name": "AP-Name"}]
    page.apply_trackside_pagination()

    page.open_ap_detail_from_trackside(0)
    process_events_until(lambda: bool(opened))

    assert opened == [(ac.device_uuid, "ap-name")]


def test_trackside_ap_business_double_click_column_dispatches_single_action(tmp_path, monkeypatch):
    app()
    database = make_database(tmp_path)
    page = TracksideApServicePage(DeviceRepository(database), I18n("en_US"), "demo", PathResolver(tmp_path))
    page.trackside_rows = [{"interface_name": "GigabitEthernet1/0/1", "ap_mac": "bc5a-3457-cbe0"}]
    page.apply_trackside_pagination()
    calls: list[str] = []
    monkeypatch.setattr(page, "open_interface_history_from_trackside", lambda row: calls.append(f"history:{row}"))
    monkeypatch.setattr(page, "open_ap_detail_from_trackside", lambda row: calls.append(f"ap:{row}"))
    fields = [field for _key, field in TRACKSIDE_AP_BUSINESS_COLUMNS]

    page.handle_trackside_double_click(page.trackside_table.item(0, fields.index("interface_name")))
    page.handle_trackside_double_click(page.trackside_table.item(0, fields.index("ap_mac")))

    assert calls == ["history:0", "ap:0"]


def test_trackside_ap_refresh_async_uses_background_loader_and_loading_state(tmp_path, monkeypatch):
    app()
    loader = install_fake_trackside_loader(monkeypatch)
    database = make_database(tmp_path)
    page = TracksideApServicePage(DeviceRepository(database), I18n("en_US"), "demo", PathResolver(tmp_path))

    page.refresh_async()

    assert page.is_loading
    assert page.status_label.text() == "Loading trackside AP service data..."
    assert not page.update_button.isEnabled()
    assert len(loader.instances) == 1
    assert loader.instances[0].started

    result = TracksideApBusinessLoadResult(page.load_generation, "demo", [{"site": "A", "device_name": "SW", "interface_name": "GigabitEthernet1/0/1"}], 1, 2, 3)
    loader.instances[0].load_finished.emit(result)

    assert not page.is_loading
    assert page.has_loaded
    assert not page.dirty
    assert page.update_button.isEnabled()
    assert page.trackside_table.rowCount() == 1
    assert page.status_label.text().startswith("Loaded 1 rows; filtered 1; trackside UP 0; AC online AP 0; offline ledger ")


def test_trackside_ap_generation_discards_stale_load_result(tmp_path, monkeypatch):
    app()
    loader = install_fake_trackside_loader(monkeypatch)
    database = make_database(tmp_path)
    page = TracksideApServicePage(DeviceRepository(database), I18n("en_US"), "demo", PathResolver(tmp_path))
    page.refresh_async()
    stale_generation = page.load_generation
    page.load_generation += 1

    loader.instances[0].load_finished.emit(
        TracksideApBusinessLoadResult(stale_generation, "demo", [{"site": "old"}], 1, 1, 1)
    )

    assert page.trackside_rows == []
    assert not page.has_loaded
    assert page.dirty


def test_trackside_ap_set_repository_does_not_synchronously_refresh(tmp_path, monkeypatch):
    app()
    database = make_database(tmp_path)
    first_repository = DeviceRepository(database)
    page = TracksideApServicePage(first_repository, I18n("en_US"), "demo", PathResolver(tmp_path))

    def fail_refresh(*_args, **_kwargs):
        raise AssertionError("set_repository must not synchronously refresh")

    monkeypatch.setattr(page, "refresh_all", fail_refresh)
    page.set_repository(DeviceRepository(database), "next")

    assert page.dirty
    assert not page.has_loaded
    assert page.trackside_rows == []


def test_rail_transit_lazy_refreshes_only_current_tab(tmp_path, monkeypatch):
    app()
    database = make_database(tmp_path)
    page = RailTransitPage(DeviceRepository(database), I18n("en_US"), "demo", PathResolver(tmp_path))
    calls: list[str] = []
    page._ensure_feature_page("rail.train_online")
    page._ensure_feature_page("rail.trackside_ap_business")
    page._ensure_feature_page("rail.raw_mesh_log_analysis")
    monkeypatch.setattr(page.vehicle_mr_online_page, "refresh_all", lambda: calls.append("vehicle"))
    monkeypatch.setattr(page.trackside_page, "refresh_async", lambda force=False: calls.append(f"trackside:{force}"))
    monkeypatch.setattr(page.mesh_page, "first_show_refresh", lambda force=False: calls.append(f"mesh_first:{force}"))
    assert page.online_mr_page is None
    page.tabs.setCurrentIndex(0)
    calls.clear()

    page.refresh_current_async_or_lazy()
    assert calls == ["vehicle"]

    page.tabs.setCurrentIndex(2)
    assert calls == ["vehicle", "trackside:False"]

    page.tabs.setCurrentIndex(3)
    assert calls == ["vehicle", "trackside:False", "mesh_first:False"]


def test_rail_transit_reload_from_gate_reconciles_session_full_tabs(tmp_path):
    app()
    database = make_database(tmp_path)
    gate = make_feature_gate(
        tmp_path / "gate",
        hidden=(
            "rail.train_online",
            "rail.car_network_diagnostic",
            "rail.online_mr_collection",
            "rail.online_mr_analysis",
        ),
    )
    page = RailTransitPage(DeviceRepository(database), I18n("en_US"), "demo", PathResolver(tmp_path), feature_gate=gate)

    assert [page.feature_by_tab[page.tabs.widget(index)] for index in range(page.tabs.count())] == [
        "rail.trackside_ap_business",
        "rail.raw_mesh_log_analysis",
    ]

    page._ensure_feature_page("rail.trackside_ap_business")
    existing_trackside_page = page.trackside_page
    gate.enable_session_full_mode(reason="test", operator="tester")
    page.reload_from_gate(refresh_current=False)

    assert [page.feature_by_tab[page.tabs.widget(index)] for index in range(page.tabs.count())] == [
        "rail.train_online",
        "rail.car_network_diagnostic",
        "rail.trackside_ap_business",
        "rail.raw_mesh_log_analysis",
        "rail.online_mr_collection",
        "rail.online_mr_analysis",
    ]
    assert page.trackside_page is existing_trackside_page
    assert page.vehicle_mr_online_page is None

    gate.disable_session_override(reason="test")
    page.reload_from_gate(refresh_current=False)

    assert [page.feature_by_tab[page.tabs.widget(index)] for index in range(page.tabs.count())] == [
        "rail.trackside_ap_business",
        "rail.raw_mesh_log_analysis",
    ]


def test_ac_management_apply_feature_gate_readds_session_full_tabs(tmp_path):
    app()
    context = create_demo_context(PathResolver(tmp_path))
    gate = make_feature_gate(
        tmp_path / "gate",
        hidden=(
            "ac.trackside_ap_plan",
            "ac.ap_online_overview",
            "ac.fit_ap_optical",
        ),
    )
    page = AcManagementPage(context.repository, I18n("en_US"), "demo", feature_gate=gate)

    assert [page._current_feature_id() for _ in [None]][0] in {"ac.fit_ap_resources", "ac.fit_ap_extensions"}
    assert [page.tabs.tabText(index) for index in range(page.tabs.count())] == [
        "FIT-AP Resources",
        "FIT-AP Extensions",
    ]

    gate.enable_session_full_mode(reason="test", operator="tester")
    page._apply_feature_gate()

    assert [page.tabs.tabText(index) for index in range(page.tabs.count())] == [
        "Trackside AP Plan",
        "AP Online Overview",
        "FIT-AP Resources",
        "FIT-AP Optical",
        "FIT-AP Extensions",
    ]

    gate.disable_session_override(reason="test")
    page._apply_feature_gate()

    assert [page.tabs.tabText(index) for index in range(page.tabs.count())] == [
        "FIT-AP Resources",
        "FIT-AP Extensions",
    ]


def test_trackside_ap_search_filter_is_debounced(tmp_path):
    app()
    database = make_database(tmp_path)
    page = TracksideApServicePage(DeviceRepository(database), I18n("en_US"), "demo", PathResolver(tmp_path))
    page.trackside_rows = [
        {"site": "A", "ap_name": "AP-1", "device_name": "SW-1", "interface_name": "GigabitEthernet1/0/1"},
        {"site": "B", "ap_name": "BR-2", "device_name": "SW-2", "interface_name": "GigabitEthernet1/0/2"},
    ]
    page._set_trackside_site_filter_items(page.trackside_rows)
    page.apply_trackside_filters()

    page.trackside_search_input.setText("AP")
    app().processEvents()

    assert page.search_debounce_timer.isActive()
    assert page.trackside_table.rowCount() == 2
    process_events_until(lambda: not page.search_debounce_timer.isActive(), timeout=1.0)
    assert page.trackside_table.rowCount() == 1


def test_trackside_ap_site_filter_keeps_station_names_readable(tmp_path):
    app()
    database = make_database(tmp_path)
    page = TracksideApServicePage(DeviceRepository(database), I18n("zh_CN"), "demo", PathResolver(tmp_path))
    page.trackside_rows = [
        {"site": "03横溪站", "ap_name": "AP-1"},
        {"site": "04-横溪站1-超长车站名称", "ap_name": "AP-2"},
    ]

    page._set_trackside_site_filter_items(page.trackside_rows)

    assert page.trackside_site_filter.minimumWidth() >= 180
    assert page.trackside_site_filter.sizeAdjustPolicy() == QComboBox.AdjustToContents
    assert page.trackside_site_filter.view().minimumWidth() > page.trackside_site_filter.minimumWidth()


def test_trackside_ap_cache_skips_duplicate_worker(tmp_path, monkeypatch):
    app()
    loader = install_fake_trackside_loader(monkeypatch)
    database = make_database(tmp_path)
    page = TracksideApServicePage(DeviceRepository(database), I18n("en_US"), "demo", PathResolver(tmp_path))
    page.refresh_async()
    loader.instances[0].load_finished.emit(TracksideApBusinessLoadResult(page.load_generation, "demo", [], 0, 1, 1))

    page.refresh_async(force=False)

    assert len(loader.instances) == 1


def test_trackside_ap_force_refreshes_empty_cache(tmp_path, monkeypatch):
    app()
    loader = install_fake_trackside_loader(monkeypatch)
    database = make_database(tmp_path)
    page = TracksideApServicePage(DeviceRepository(database), I18n("en_US"), "demo", PathResolver(tmp_path))
    page.refresh_async()
    loader.instances[0].load_finished.emit(
        TracksideApBusinessLoadResult(
            page.load_generation,
            "demo",
            [],
            1,
            1,
            1,
            interface_count=1,
            candidate_ap_interface_count=0,
            row_count=0,
            empty_reason="trackside.empty.no_ap_interfaces",
        )
    )

    page.refresh_async(force=True)

    assert len(loader.instances) == 2
    assert page.is_loading


def test_trackside_ap_empty_result_shows_diagnostic_reason(tmp_path, monkeypatch):
    app()
    loader = install_fake_trackside_loader(monkeypatch)
    database = make_database(tmp_path)
    page = TracksideApServicePage(DeviceRepository(database), I18n("en_US"), "demo", PathResolver(tmp_path))
    page.refresh_async()
    loader.instances[0].load_finished.emit(
        TracksideApBusinessLoadResult(
            page.load_generation,
            "demo",
            [],
            1,
            1,
            1,
            interface_count=5,
            candidate_ap_interface_count=0,
            row_count=0,
            empty_reason="trackside.empty.no_ap_interfaces",
        )
    )

    assert page.has_loaded
    assert not page.dirty
    assert page.trackside_table.rowCount() == 0
    assert "No trackside AP service data is available." in page.status_label.text()
    assert "no interface description contains AP" in page.status_label.text()


def test_trackside_load_snapshot_returns_diagnostic_counts_and_empty_reason(tmp_path):
    app()
    database = make_database(tmp_path)
    repository = DeviceRepository(database)
    switch = create_station_switch(repository, "demo", name="HX_1", station="Station A", ip_address="10.0.0.2")
    fact_repository = DeviceFactRepository(database)
    fact_repository.replace_device_interfaces(
        switch.device_uuid,
        [
            {"interface_name": "GigabitEthernet2/0/10", "description": "Camera", "collected_at": "2026-01-01T00:00:00"},
            {"interface_name": "GigabitEthernet2/0/11", "description": "Access", "collected_at": "2026-01-01T00:00:00"},
        ],
    )

    result = load_trackside_ap_business_snapshot(repository, "demo", 7)

    assert result.generation == 7
    assert result.device_count == 1
    assert result.interface_count == 2
    assert result.candidate_ap_interface_count == 0
    assert result.row_count == 0
    assert result.empty_reason == "trackside.empty.no_ap_interfaces"


def test_trackside_load_snapshot_counts_successful_business_rows(tmp_path):
    app()
    database = make_database(tmp_path)
    repository = DeviceRepository(database)
    switch = create_station_switch(repository, "demo", name="HX_1", station="Station A", ip_address="10.0.0.2")
    fact_repository = DeviceFactRepository(database)
    fact_repository.replace_device_interfaces(
        switch.device_uuid,
        [{"interface_name": "GigabitEthernet2/0/10", "description": "To_AP10", "collected_at": "2026-01-01T00:00:00"}],
    )
    fact_repository.replace_optical_modules(
        switch.device_uuid,
        [{"interface_name": "GigabitEthernet2/0/10", "rx_power": "-6.10", "collected_at": "2026-01-01T00:00:00"}],
    )
    fact_repository.replace_lldp_neighbors(
        switch.device_uuid,
        [{"local_interface": "GE2/0/10", "neighbor_mac": "bc5a-3457-cbe0", "neighbor_interface": "GigabitEthernet1/0/2", "collected_at": "2026-01-01T00:00:00"}],
    )
    ac = repository.create(make_ac_device())
    AcRepository(database).replace_fit_ap_optical(
        ac.device_uuid,
        [{"ap_uuid": "ap-10", "ap_mac": "bc5a-3457-cbe0", "ap_name": "AP10", "neighbor_device_name": "HX_1", "neighbor_interface": "GigabitEthernet2/0/10", "rx_power": "-14.35"}],
    )

    result = load_trackside_ap_business_snapshot(repository, "demo", 8)

    assert result.row_count == 1
    assert result.interface_count == 1
    assert result.optical_count == 1
    assert result.lldp_count == 1
    assert result.fit_ap_optical_count == 1
    assert result.candidate_ap_interface_count == 1
    assert result.empty_reason == ""


def test_trackside_export_backfills_latest_valid_ap_rx_from_history():
    rows = [
        {
            "site": "Station A",
            "ap_uuid": "ap-10",
            "ap_mac": "bc5a-3457-cbe0",
            "ap_name": "AP10",
            "ap_rx_power": "-",
            "ap_optical_status": "no_light",
            "collection_status": "timeout",
            "updated_at": "2026-01-03T00:00:00",
        }
    ]
    history = [
        {
            "ap_uuid": "ap-10",
            "ap_mac": "bc5a-3457-cbe0",
            "ap_name": "AP10",
            "rx_power": "-7.34",
            "status": "success",
            "collected_at": "2026-01-02T00:00:00",
        }
    ]

    enriched = enrich_trackside_export_rows(rows, ap_optical_history_rows=history)

    assert enriched[0]["ap_rx_power"] == "-7.34"
    assert enriched[0]["ap_last_valid_rx_power"] == "-7.34"
    assert enriched[0]["ap_last_valid_collected_at"] == "2026-01-02T00:00:00"
    assert enriched[0]["ap_optical_missing_reason"] == "overwritten_by_failed_row"


def test_trackside_status_distinguishes_trackside_up_and_ac_online(tmp_path):
    app()
    database = make_database(tmp_path)
    page = TracksideApServicePage(DeviceRepository(database), I18n("en_US"), "demo", PathResolver(tmp_path))
    page.has_loaded = True
    page.trackside_rows = [
        {"site": "Station A", "serial_number": "SN-001", "ap_name": "AP-1", "link_status": "UP", "ap_state": "R/M"},
        {"site": "Station A", "serial_number": "SN-001", "ap_name": "AP-1", "link_status": "UP", "ap_state": "R/M"},
        {"site": "Station B", "serial_number": "SN-002", "ap_name": "AP-2", "link_status": "UP", "ap_state": "R/M"},
    ]
    page._set_trackside_site_filter_items(page.trackside_rows)
    page.trackside_site_filter.setCurrentIndex(page.trackside_site_filter.findData("Station A"))
    page._update_idle_status()

    text = page.status_label.text()
    assert "filtered 2" in text
    assert "trackside UP 1" in text
    assert "AC online AP 2" in text
    assert "online AP 1" not in text


def test_trackside_ap_load_failure_keeps_retry_state(tmp_path, monkeypatch):
    app()
    loader = install_fake_trackside_loader(monkeypatch)
    database = make_database(tmp_path)
    page = TracksideApServicePage(DeviceRepository(database), I18n("en_US"), "demo", PathResolver(tmp_path))
    page.has_loaded = True
    page.dirty = False
    page.refresh_async(force=True)

    loader.instances[0].load_failed.emit(page.load_generation, "boom")

    assert not page.has_loaded
    assert page.dirty
    assert not page.is_loading
    assert page.update_button.isEnabled()
    assert "Failed to load trackside AP service data: boom" == page.status_label.text()


def test_trackside_ap_update_completion_marks_dirty_and_reloads(tmp_path, monkeypatch):
    app()
    loader = install_fake_trackside_loader(monkeypatch)
    database = make_database(tmp_path)
    page = TracksideApServicePage(DeviceRepository(database), I18n("en_US"), "demo", PathResolver(tmp_path))
    page.has_loaded = True
    page.dirty = False

    page._finish_collect(SimpleNamespace(success_count=1, failed_count=0, skipped_count=0))

    assert page.is_loading
    assert page.dirty
    assert len(loader.instances) == 1


def test_trackside_ap_table_renders_only_current_page_rows(tmp_path):
    app()
    database = make_database(tmp_path)
    page = TracksideApServicePage(DeviceRepository(database), I18n("en_US"), "demo", PathResolver(tmp_path))
    page.trackside_rows = [
        {"site": "A", "ap_name": f"AP-{index}", "device_name": "SW", "interface_name": f"GigabitEthernet1/0/{index}"}
        for index in range(5000)
    ]
    page.trackside_page_size = 200

    page.apply_trackside_pagination()

    assert page.trackside_table.rowCount() == 200


def test_main_window_opens_rail_transit_before_lazy_refresh(tmp_path, monkeypatch):
    from netconsole.ui.main_window import MainWindow

    qt_app = app()
    context = create_demo_context(PathResolver(tmp_path))
    window = MainWindow(context.site, context.repository, I18n("en_US"), context.paths)
    events: list[str] = []
    rail_row = next(index for index in range(window.navigation.count()) if window.navigation.item(index).data(256) == "rail_transit")
    rail_page = window.get_or_create_page("rail_transit")

    monkeypatch.setattr(rail_page, "refresh_all", lambda: events.append("sync_refresh"))
    monkeypatch.setattr(rail_page, "refresh_current_async_or_lazy", lambda **kwargs: events.append(f"lazy_refresh:{kwargs.get('force_if_empty')}"))
    monkeypatch.setattr(window.stack, "setCurrentWidget", lambda widget: events.append("shown"))

    window.open_current_page(rail_row)
    qt_app.processEvents()

    assert events == ["shown", "lazy_refresh:True"]


def test_main_window_defers_ac_creation_and_uses_current_tab_refresh(tmp_path, monkeypatch):
    from netconsole.ui.main_window import MainWindow
    from netconsole.ui.pages import ac_management_page as ac_page_module

    qt_app = app()
    context = create_demo_context(PathResolver(tmp_path))
    window = MainWindow(context.site, context.repository, I18n("en_US"), context.paths)
    ac_row = next(index for index in range(window.navigation.count()) if window.navigation.item(index).data(256) == "ac")
    calls: list[bool] = []

    original_refresh_devices = ac_page_module.AcManagementPage.refresh_devices

    def refresh_devices(self, *, load_current_only=False):
        calls.append(bool(load_current_only))
        return original_refresh_devices(self, load_current_only=load_current_only)

    monkeypatch.setattr(ac_page_module.AcManagementPage, "refresh_devices", refresh_devices)

    window.open_current_page(ac_row)

    assert "ac" not in window.pages
    assert window.stack.currentWidget() is window.loading_pages["ac"]

    process_events_until(lambda: "ac" in window.pages and bool(calls), timeout=2.0)
    qt_app.processEvents()

    assert calls == [True]
    assert window.stack.currentWidget() is window.ac_page


def test_main_window_discards_stale_ac_open_when_switching_to_rail(tmp_path):
    from netconsole.ui.main_window import MainWindow

    app()
    context = create_demo_context(PathResolver(tmp_path))
    window = MainWindow(context.site, context.repository, I18n("en_US"), context.paths)
    window.current_page_id = "ac"
    window._module_switch_generation = 1
    stale_generation = 1
    window.current_page_id = "rail_transit"
    window._module_switch_generation = 2

    window._finish_deferred_page_open("ac", stale_generation)

    assert window.current_page_id == "rail_transit"
    assert "ac" not in window.pages


def test_rail_transit_force_if_empty_refreshes_empty_trackside_cache(tmp_path, monkeypatch):
    app()
    database = make_database(tmp_path)
    page = RailTransitPage(DeviceRepository(database), I18n("en_US"), "demo", PathResolver(tmp_path))
    calls: list[bool] = []
    page._ensure_feature_page("rail.trackside_ap_business")
    page.trackside_page.has_loaded = True
    page.trackside_page.dirty = False
    page.trackside_page.trackside_rows = []
    monkeypatch.setattr(page.trackside_page, "refresh_async", lambda force=False: calls.append(force))

    page.tabs.setCurrentIndex(2)
    calls.clear()
    page.refresh_current_async_or_lazy(force_if_empty=True)

    assert calls == [True]


def test_station_online_history_dialog_columns_and_filter(tmp_path):
    app()
    rows = [
        {"collected_at": "2026-01-02T00:00:00", "site_name": "Station A", "ap_total": 3, "online_count": 2, "offline_count": 1, "online_rate": "66.7%", "remark": "A"},
        {"collected_at": "2026-01-01T00:00:00", "site_name": "Station B", "ap_total": 4, "online_count": 4, "offline_count": 0, "online_rate": "100.0%", "remark": "B"},
    ]

    dialog = StationOnlineHistoryDialog(I18n("en_US"), rows, "Station A")

    assert STATION_ONLINE_HISTORY_COLUMNS[-1] == ("field.remark", "remark")
    assert dialog.scroll_area.widgetResizable() is True
    assert dialog.scroll_area.horizontalScrollBarPolicy() == Qt.ScrollBarAsNeeded
    assert dialog.scroll_area.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded
    assert dialog.table.columnCount() == 7
    assert [dialog.table.horizontalHeaderItem(column).text() for column in range(dialog.table.columnCount())] == [
        "Collected At",
        "Station",
        "AP Total",
        "Online",
        "Offline",
        "Online Rate",
        "Remark",
    ]


def test_history_windows_support_pagination(tmp_path):
    app()
    rows = [
        {"collected_at": f"2026-01-01T00:{index:02d}:00", "site_name": "Station A", "ap_total": 1, "online_count": 1, "offline_count": 0, "online_rate": "100.0%", "remark": ""}
        for index in range(250)
    ]

    dialog = StationOnlineHistoryDialog(I18n("en_US"), rows)

    assert dialog.table.rowCount() == 200
    assert dialog.pagination.state.total_items == 250
    assert dialog.table.item(0, 1).text() == "Station A"


def test_export_station_online_history_xlsx_contains_remark(tmp_path):
    from openpyxl import load_workbook

    export_path = tmp_path / "history.xlsx"
    rows = [
        {"collected_at": "2026-01-02T00:00:00", "site_name": "Station A", "ap_total": 3, "online_count": 2, "offline_count": 1, "online_rate": "66.7%", "remark": "Need check"},
    ]
    headers = ["Collected At", "Station", "AP Total", "Online", "Offline", "Online Rate", "Remark"]

    export_station_online_history_xlsx(export_path, rows, headers)

    workbook = load_workbook(export_path)
    sheet = workbook["AP Online History"]
    assert [cell.value for cell in sheet[1]] == headers
    assert sheet["G2"].value == "Need check"
    assert sheet["A1"].font.bold
    assert sheet["A1"].alignment.horizontal == "center"


def test_demo_data_contains_ac_management_rows(tmp_path):
    context = create_demo_context(PathResolver(tmp_path))
    ac = next(device for device in context.repository.list(device_type="AC") if device.ip_address == "10.0.0.51")
    repository = AcRepository(context.database)

    assert repository.get_ac_ap_summary(ac.device_uuid)["remaining_local_ap_licenses"] == 59998
    assert repository.get_ac_ap_summary(ac.device_uuid)["cpu_usage"] == "16%"
    assert [row["ap_name"] for row in repository.list_fit_ap_resources(ac.device_uuid)] == ["4c6f-d608-0400", "4c6f-de4b-0500"]
    assert len(repository.list_fit_ap_optical(ac.device_uuid)) == 2
    assert repository.get_fit_ap_metadata("4c6f-d608-0400")["site_name"] == "体育中心站"


def test_import_and_export_fit_ap_metadata(tmp_path):
    from openpyxl import Workbook

    repository = AcRepository(make_database(tmp_path))
    repository.replace_fit_ap_resources("ac-1", [{"ap_name": "ap-a", "ap_mac": "30f5-277a-1b00", "serial_number": "SN-1"}])
    service = FitApImportExportService(repository)
    import_path = tmp_path / "metadata.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(AP_EXTENSION_TEMPLATE_FIELDS)
    sheet.append(["renamed-ap", "30F5:277A:1B00", "站点", "Station X", "", "", "", "", "", "", "", "K12+450", "Platform", "上下行", ""])
    workbook.save(import_path)

    result = service.import_metadata_file(import_path)

    assert result.updated == 1
    assert result.skipped == 0
    entity = repository.list_ap_entities("ac-1")[0]
    assert entity["station"] == "Station X"
    assert entity["milestone"] == "12450"
    assert entity["location_note"] == "Platform"
    assert entity["direction"] == "上下行"

    export_path = tmp_path / "export.csv"
    service.export_ap_csv(export_path, [{"ap_name": "ap-a", "ap_ip": "10.0.0.1", "state_display": "运行(主)", "site": "体育中心站", "mileage": "1020", "direction": "上行"}])
    text = export_path.read_text(encoding="utf-8-sig")
    assert "AP名称" in text
    assert "ap-a" in text
    assert "YDK1+020" in text
    assert "LLDP" not in text
    assert "BSSID" not in text
    assert "RID1信道" in text
    assert "RID2信道" in text
    assert "RID3信道" not in text
    headers = text.splitlines()[0].split(",")
    assert headers.index("RID2功率") < headers.index("归属站点") < headers.index("更新时间")
    assert "归属区间" in headers
    assert "归属类型" in headers


def test_fit_ap_resource_table_row_formats_mileage_with_extension_line_side():
    from netconsole.ui.pages.ac_management_page import build_fit_ap_resource_table_row

    row = build_fit_ap_resource_table_row(
        {
            "ap_uuid": "ap-1",
            "ap_name": "AP-1",
            "mileage": "",
            "direction": "上行",
            "extension_line_side": "右线",
            "extension_mileage_m": 1020,
        }
    )

    assert row["mileage"] == "YDK1+020"
    assert row["_mileage_meters"] == 1020


def test_trackside_ap_plan_remark_persists_and_exports(tmp_path):
    from openpyxl import load_workbook

    from netconsole.repositories.ac_repository import TRACKSIDE_AP_PLAN_MODE
    from netconsole.ui.pages.trackside_ap_plan_page import export_trackside_plan_xlsx, read_trackside_plan_file

    repository = AcRepository(make_database(tmp_path))
    repository.replace_trackside_ap_plan_rows(
        TRACKSIDE_AP_PLAN_MODE,
        [
            {
                "station_name": "Station A",
                "ap_count": 2,
                "ap_start_address": "10.0.0.X",
                "mask_length": 24,
                "ap_gateway": "10.0.0.1",
                "ap_management_vlans": "921",
                "remark": "near tunnel",
            }
        ],
    )

    rows = repository.list_trackside_ap_plan(TRACKSIDE_AP_PLAN_MODE)
    assert rows[0]["remark"] == "near tunnel"

    export_path = tmp_path / "trackside_plan.xlsx"
    export_trackside_plan_xlsx(export_path, rows)
    sheet = load_workbook(export_path).active
    assert [cell.value for cell in sheet[1]][-1] == "备注"
    assert sheet.cell(row=2, column=7).value == "near tunnel"
    assert read_trackside_plan_file(export_path)[0]["remark"] == "near tunnel"


def test_import_ap_extension_metadata_skips_empty_or_unmatched_mac(tmp_path):
    repository = AcRepository(make_database(tmp_path))
    repository.replace_fit_ap_resources("ac-1", [{"ap_name": "ap-a", "ap_mac": "30f5-277a-1b00"}])
    service = FitApImportExportService(repository)

    result = service.import_metadata_rows(
        AP_EXTENSION_TEMPLATE_FIELDS,
        [
            ["ap-a", "", "Empty Station", "", "", ""],
            ["ap-a", "ffff-ffff-ffff", "Unknown Station", "", "", ""],
        ],
    )

    assert result.updated == 0
    assert result.skipped == 2
    assert any("AP_MAC is empty or invalid" in error for error in result.errors)
    assert any("not matched" in error for error in result.errors)
    assert repository.list_ap_entities("ac-1")[0]["station"] == ""


def test_import_ap_extension_metadata_rejects_legacy_matching_headers(tmp_path):
    repository = AcRepository(make_database(tmp_path))
    repository.replace_fit_ap_resources("ac-1", [{"ap_name": "ap-a", "ap_mac": "30f5-277a-1b00"}])
    service = FitApImportExportService(repository)

    with pytest.raises(ValueError, match="Unsupported AP metadata template header"):
        service.import_metadata_rows(["AP名称", "归属站点", "里程", "点位说明", "上下行"], [["ap-a", "Legacy Station", "", "", ""]])

    assert repository.list_ap_entities("ac-1")[0]["station"] == ""


def test_export_ap_extension_template_xlsx_contains_editable_headers_and_entity_station(tmp_path):
    from openpyxl import load_workbook

    service = FitApImportExportService(AcRepository(make_database(tmp_path)))
    export_path = tmp_path / "ap_extension_template.xlsx"

    service.export_ap_extension_template_xlsx(
        export_path,
        [
            {
                "ap_uuid": "ap-1",
                "ap_name": "AP-1",
                "apid": "101",
                "ap_ip": "10.0.0.10",
                "ap_mac": "0011-2233-4455",
                "model": "WA6338",
                "serial_number": "SN-001",
                "state_display": "Idle",
                "site": "Resource Station",
            }
        ],
        [{"ap_uuid": "ap-1", "ap_mac": "0011-2233-4455", "station": "Entity Station", "direction": "uplink", "milestone": "K12+450", "location_note": "platform"}],
    )

    sheet = load_workbook(export_path).active
    headers = [cell.value for cell in sheet[1]]

    assert headers == AP_EXTENSION_TEMPLATE_FIELDS
    assert "归属站点" in headers
    for forbidden in ("AP_IP", "APID", "SN", "型号", "状态", "AP状态", "AP组", "在线时长", "更新时间"):
        assert forbidden not in headers
    assert "站点/位置" not in headers
    assert "site" not in headers
    assert "site_name" not in headers
    assert "station" not in headers
    assert sheet.max_row == 2
    assert sheet["A2"].value == "AP-1"
    assert sheet["B2"].value == "0011-2233-4455"
    assert sheet["D2"].value == "Entity Station"
    assert sheet["L2"].value == "K12+450"
    assert sheet["M2"].value == "platform"
    assert sheet["N2"].value == "uplink"
    assert sheet["A1"].font.bold
    assert sheet.freeze_panes == "A2"
    assert sheet.auto_filter.ref == "A1:O2"


def test_export_ap_extension_template_xlsx_allows_empty_template(tmp_path):
    from openpyxl import load_workbook

    service = FitApImportExportService(AcRepository(make_database(tmp_path)))
    export_path = tmp_path / "empty_ap_extension_template.xlsx"

    service.export_ap_extension_template_xlsx(export_path, [], [])

    sheet = load_workbook(export_path).active
    assert [cell.value for cell in sheet[1]] == AP_EXTENSION_TEMPLATE_FIELDS
    assert sheet.max_row == 1


def test_ac_management_page_exports_ap_extension_template(tmp_path, monkeypatch):
    from openpyxl import load_workbook
    import netconsole.ui.pages.ac_management_page as page_module

    app()
    database = make_database(tmp_path)
    device_repository = DeviceRepository(database)
    ac = device_repository.create(make_ac_device())
    repository = AcRepository(database)
    repository.replace_fit_ap_resources(
        ac.device_uuid,
        [
            {
                "ap_uuid": "ap-1",
                "ap_name": "AP-1",
                "apid": "101",
                "ap_ip": "10.0.0.10",
                "ap_mac": "0011-2233-4455",
                "model": "WA6338",
                "serial_number": "SN-001",
                "state_display": "Idle",
                "site": "Resource Station",
            }
        ],
    )
    with database.connect() as conn:
        conn.execute("UPDATE ap_entities SET station = ? WHERE ap_uuid = ?", ("Entity Station", "ap-1"))
        conn.commit()
    export_path = tmp_path / "selected_template.xlsx"
    monkeypatch.setattr(page_module.QFileDialog, "getSaveFileName", lambda *_args, **_kwargs: (str(export_path), ""))

    page = AcManagementPage(device_repository, I18n("zh_CN"), "demo")

    assert page.export_extension_template_button.text() == "导出AP扩展信息模板"
    page.export_extension_template_button.click()
    process_events_until(lambda: not getattr(page, "_netconsole_export_controllers", []))

    sheet = load_workbook(export_path).active
    assert [cell.value for cell in sheet[1]] == AP_EXTENSION_TEMPLATE_FIELDS
    assert sheet.max_row == 2
    assert sheet["D2"].value == "Entity Station"


def test_ac_management_page_exports_empty_ap_extension_template_with_desktop_default(tmp_path, monkeypatch):
    import netconsole.ui.pages.ac_management_page as page_module

    app()
    database = make_database(tmp_path)
    device_repository = DeviceRepository(database)
    device_repository.create(make_ac_device())
    selected_defaults: list[str] = []
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    export_path = tmp_path / "empty_template.xlsx"
    monkeypatch.setattr(page_module.QStandardPaths, "writableLocation", lambda _location: str(desktop))
    monkeypatch.setattr(
        page_module.QFileDialog,
        "getSaveFileName",
        lambda _parent, _title, default_path, _filter: selected_defaults.append(default_path) or (str(export_path), ""),
    )
    page = AcManagementPage(device_repository, I18n("zh_CN"), "demo")
    page.export_ap_extension_template()
    process_events_until(lambda: not getattr(page, "_netconsole_export_controllers", []))

    assert selected_defaults
    assert Path(selected_defaults[0]).parent == desktop
    assert "AP扩展信息模板_AC_" in Path(selected_defaults[0]).name
    assert export_path.exists()


def test_ap_detail_dialog_opens_and_saves_metadata(tmp_path):
    app()
    repository = AcRepository(make_database(tmp_path))
    repository.replace_fit_ap_resources("ac-1", [{"ap_name": "ap-a", "state_display": "运行(主)", "state_raw": "R/M"}])

    dialog = FitApDetailDialog(I18n("en_US"), repository, "ac-1", "ap-a")
    dialog.site_input.setText("Station A")
    dialog.save_metadata()
    process_events_until(lambda: not dialog.background_job_id)

    assert dialog.windowTitle() == "AP Details - ap-a"
    assert dialog.minimumWidth() == 760
    assert dialog.minimumHeight() == 520
    assert dialog.scroll_area.widgetResizable() is True
    assert dialog.scroll_area.horizontalScrollBarPolicy() == Qt.ScrollBarAsNeeded
    assert dialog.scroll_area.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded
    assert dialog.tabs.count() == 6
    assert FIT_AP_DETAIL_TABS == ("basic", "metadata", "radio", "lldp", "optical", "raw_fields")
    assert dialog.tabs.currentWidget() is dialog.basic_tab
    assert dialog.raw_fields_table.columnCount() == 2
    assert not dialog.show_empty_raw_fields_checkbox.isChecked()
    assert dialog.raw_fields_table.item(0, 0).text().startswith("AP基础字段 /")
    assert not dialog.raw_fields_table.item(0, 0).text().startswith(("resource.", "metadata.", "optical."))
    assert dialog.raw_fields_table.rowCount() > 0
    assert repository.get_fit_ap_metadata("ap-a")["site_name"] == "Station A"


def test_ap_detail_main_window_shows_optical_summary_and_history_button(tmp_path):
    app()
    repository = AcRepository(make_database(tmp_path))
    repository.replace_fit_ap_resources("ac-1", [{"ap_name": "ap-a", "serial_number": "SN-001"}])
    ap_uuid = repository.list_fit_ap_resources("ac-1")[0]["ap_uuid"]
    repository.replace_fit_ap_optical("ac-1", [{"ap_uuid": ap_uuid, "ap_name": "ap-a", "interface_name": "WLAN-Radio1/0/1", "rx_power": "-10.10"}])

    dialog = FitApDetailDialog(I18n("en_US"), repository, "ac-1", ap_uuid)
    dialog.showMaximized()
    app().processEvents()

    assert not dialog.findChildren(QSplitter)
    assert dialog.optical_history_button.text() == "View Optical History"
    assert dialog.optical_table.columnCount() == len(OPTICAL_COLUMNS)
    assert dialog.optical_table.rowCount() == 1
    assert dialog.optical_table.item(0, 0).text() == "WLAN-Radio1/0/1"
    assert not hasattr(dialog, "optical_detail_table")
    assert dialog.optical_table.horizontalScrollBarPolicy() == Qt.ScrollBarAsNeeded


def test_ap_detail_lldp_and_optical_tabs_use_resolved_link_fields(tmp_path):
    app()
    repository = AcRepository(make_database(tmp_path))
    repository.replace_fit_ap_resources("ac-1", [{"ap_name": "ap-a", "serial_number": "SN-001"}])
    ap_uuid = repository.list_fit_ap_resources("ac-1")[0]["ap_uuid"]
    repository.replace_fit_ap_optical(
        "ac-1",
        [
            {
                "ap_uuid": ap_uuid,
                "ap_name": "ap-a",
                "interface_name": "GE1/0/2",
                "lldp_neighbor": "HX_1",
                "neighbor_interface": "GigabitEthernet2/0/19",
                "neighbor_mac": "903f-8645-6e00",
                "neighbor_device_name": "04-横溪站",
                "neighbor_rx_power": "-7.55",
            }
        ],
    )

    dialog = FitApDetailDialog(I18n("zh_CN"), repository, "ac-1", ap_uuid)
    lldp_fields = [field for _key, field in LLDP_COLUMNS]
    optical_fields = [field for _key, field in OPTICAL_COLUMNS]

    assert dialog.lldp_table.item(0, lldp_fields.index("lldp_neighbor_name")).text() == "HX_1"
    assert dialog.lldp_table.item(0, lldp_fields.index("lldp_neighbor_interface")).text() == "GigabitEthernet2/0/19"
    assert dialog.lldp_table.item(0, lldp_fields.index("lldp_neighbor_mac")).text() == "903f-8645-6e00"
    assert dialog.lldp_table.item(0, lldp_fields.index("neighbor_device_name")).text() == "04-横溪站"
    assert dialog.lldp_table.item(0, lldp_fields.index("lldp_source")).text() != "未知"
    assert dialog.lldp_table.item(0, lldp_fields.index("lldp_match_status")).text() == "正常"
    assert "lldp_neighbor" not in lldp_fields
    assert "neighbor_rx_power" not in lldp_fields
    assert dialog.optical_table.item(0, optical_fields.index("optical_rx_power")).text() == "-7.55"
    assert dialog.optical_table.item(0, optical_fields.index("optical_match_status")).text() == "正常"


def test_ap_detail_direction_combo_uses_uplink_downlink_and_saves_chinese(tmp_path):
    app()
    repository = AcRepository(make_database(tmp_path))
    repository.replace_fit_ap_resources("ac-1", [{"ap_name": "ap-a", "serial_number": "SN-001"}])
    ap_uuid = repository.list_fit_ap_resources("ac-1")[0]["ap_uuid"]
    repository.upsert_fit_ap_metadata({"ap_uuid": ap_uuid, "ap_name": "ap-a", "direction": "CW"})

    dialog = FitApDetailDialog(I18n("zh_CN"), repository, "ac-1", ap_uuid)

    assert [dialog.direction_combo.itemText(index) for index in range(dialog.direction_combo.count())] == ["", "上行", "下行"]
    assert dialog.direction_combo.currentData() == "上行"
    dialog.direction_combo.setCurrentIndex(dialog.direction_combo.findData("下行"))
    dialog.save_metadata()
    process_events_until(lambda: not dialog.background_job_id)
    assert repository.get_fit_ap_metadata_by_uuid(ap_uuid)["direction"] == "下行"


def test_ap_detail_direction_combo_maps_ct_to_downlink(tmp_path):
    app()
    repository = AcRepository(make_database(tmp_path))
    repository.replace_fit_ap_resources("ac-1", [{"ap_name": "ap-a", "serial_number": "SN-001"}])
    ap_uuid = repository.list_fit_ap_resources("ac-1")[0]["ap_uuid"]
    repository.upsert_fit_ap_metadata({"ap_uuid": ap_uuid, "ap_name": "ap-a", "direction": "CT"})

    dialog = FitApDetailDialog(I18n("en_US"), repository, "ac-1", ap_uuid)

    assert [dialog.direction_combo.itemText(index) for index in range(dialog.direction_combo.count())] == ["", "Uplink", "Downlink"]
    assert dialog.direction_combo.currentData() == "下行"


def test_ap_detail_history_entries_exist_for_radio_lldp_and_optical(tmp_path):
    app()
    repository = AcRepository(make_database(tmp_path))
    repository.replace_fit_ap_resources("ac-1", [{"ap_name": "ap-a", "serial_number": "SN-001"}])
    ap_uuid = repository.list_fit_ap_resources("ac-1")[0]["ap_uuid"]

    dialog = FitApDetailDialog(I18n("en_US"), repository, "ac-1", ap_uuid)

    assert dialog.radio_history_button.text() == "View History"
    assert dialog.lldp_history_button.text() == "View History"
    assert dialog.optical_history_button.text() == "View Optical History"
    assert dialog.radio_table.contextMenuPolicy() == Qt.CustomContextMenu
    assert dialog.lldp_table.contextMenuPolicy() == Qt.CustomContextMenu
    assert dialog.optical_table.contextMenuPolicy() == Qt.CustomContextMenu


def test_ap_history_dialog_columns_and_export(tmp_path):
    app()
    rows = [
        {"collected_at": "2026-01-02T00:00:00", "ap_name": "ap-a", "rid": 1, "channel": "149", "bandwidth": "80", "tx_power": "24", "raw_log_path": "raw.log"}
    ]

    dialog = ApHistoryDialog(I18n("en_US"), "ap-a", "Radio", rows, AP_RADIO_HISTORY_COLUMNS)

    assert dialog.back_button.text() == "Back"
    assert dialog.close_button.text() == "Close"
    assert dialog.export_button.text() == "Export Table"
    assert dialog.always_on_top_button.text() == "Always on Top"
    assert dialog.table.columnCount() == len(AP_RADIO_HISTORY_COLUMNS)
    assert dialog.table.horizontalHeaderItem(0).text() == "Collected At"
    export_path = tmp_path / "radio_history.xlsx"
    export_ap_history_xlsx(export_path, rows, AP_RADIO_HISTORY_COLUMNS, [dialog.i18n.t(key) for key, _field in AP_RADIO_HISTORY_COLUMNS])
    assert export_path.exists()


def test_ap_optical_history_dialog_displays_chinese_status(tmp_path):
    app()
    rows = [{"collected_at": "2026-01-01T00:00:00", "interface_name": "GE1/0/1", "optical_alarm_status": "warning"}]

    dialog = ApHistoryDialog(I18n("zh_CN"), "ap-a", "光模块", rows, AP_OPTICAL_HISTORY_COLUMNS, "optical_alarm_status")

    values = [dialog.table.item(0, column).text() for column in range(dialog.table.columnCount())]
    assert "提示告警" in values
    assert "warning" not in values


def test_ap_history_back_and_close_keep_parent_dialog_open(tmp_path):
    qt_app = app()
    repository = AcRepository(make_database(tmp_path))
    repository.replace_fit_ap_resources("ac-1", [{"ap_name": "ap-a", "serial_number": "SN-001"}])
    ap_uuid = repository.list_fit_ap_resources("ac-1")[0]["ap_uuid"]
    parent = FitApDetailDialog(I18n("en_US"), repository, "ac-1", ap_uuid)
    parent.show()
    history = ApHistoryDialog(I18n("en_US"), "ap-a", "Radio", [], AP_RADIO_HISTORY_COLUMNS, parent=parent)
    history.show()
    qt_app.processEvents()

    history.return_to_parent()
    qt_app.processEvents()

    assert parent.isVisible()

    second = ApHistoryDialog(I18n("en_US"), "ap-a", "Radio", [], AP_RADIO_HISTORY_COLUMNS, parent=parent)
    second.show()
    qt_app.processEvents()
    second.close()
    qt_app.processEvents()

    assert parent.isVisible()


def test_opening_ap_history_does_not_hide_or_close_ap_detail(tmp_path):
    qt_app = app()
    repository = AcRepository(make_database(tmp_path))
    repository.replace_fit_ap_resources("ac-1", [{"ap_name": "ap-a", "serial_number": "SN-001"}])
    ap_uuid = repository.list_fit_ap_resources("ac-1")[0]["ap_uuid"]
    repository.replace_fit_ap_optical("ac-1", [{"ap_uuid": ap_uuid, "ap_name": "ap-a", "optical_alarm_status": "warning", "collected_at": "2026-01-01T00:00:00"}])
    dialog = FitApDetailDialog(I18n("en_US"), repository, "ac-1", ap_uuid)
    dialog.show()
    qt_app.processEvents()

    dialog.open_history("optical")
    qt_app.processEvents()

    assert dialog.isVisible()
    assert dialog.optical_history_window is not None
    assert dialog.optical_history_window.isVisible()
    assert dialog.optical_history_window.windowTitle() == "AP Optical History - ap-a"
    assert dialog.optical_history_window.parentWidget() is None
    assert dialog.optical_history_window.windowFlags() & Qt.Window
    assert dialog.optical_history_window.windowFlags() & Qt.WindowMaximizeButtonHint


def test_ap_optical_history_dialog_empty_state_and_splitter(tmp_path):
    qt_app = app()
    repository = AcRepository(make_database(tmp_path))
    repository.replace_fit_ap_resources("ac-1", [{"ap_name": "ap-a", "serial_number": "SN-001"}])
    ap_uuid = repository.list_fit_ap_resources("ac-1")[0]["ap_uuid"]
    dialog = FitApDetailDialog(I18n("en_US"), repository, "ac-1", ap_uuid)

    dialog.open_optical_history()
    qt_app.processEvents()

    history = dialog.optical_history_window
    assert history is not None
    assert history.parentWidget() is None
    assert history.windowFlags() & Qt.Window
    assert history.windowFlags() & Qt.WindowMinimizeButtonHint
    assert history.windowFlags() & Qt.WindowMaximizeButtonHint
    assert history.empty_label.text() == "No optical history data available"
    assert not history.empty_label.isHidden()
    assert history.table.rowCount() == 0
    assert history.detail_table.columnCount() == 2
    assert history.splitter.sizes()[0] > 0
    assert history.splitter.sizes()[1] > 0
    assert not history.pagination.isHidden()


def test_ap_optical_history_window_reuses_same_ap_window(tmp_path):
    qt_app = app()
    repository = AcRepository(make_database(tmp_path))
    repository.replace_fit_ap_resources("ac-1", [{"ap_name": "ap-a", "serial_number": "SN-001"}])
    ap_uuid = repository.list_fit_ap_resources("ac-1")[0]["ap_uuid"]
    dialog = FitApDetailDialog(I18n("en_US"), repository, "ac-1", ap_uuid)

    dialog.open_optical_history()
    first = dialog.optical_history_window
    dialog.open_optical_history()
    qt_app.processEvents()

    assert dialog.optical_history_window is first


def test_ap_optical_history_detail_and_column_width_persist(tmp_path):
    qt_app = app()
    paths = PathResolver(tmp_path)
    settings = SettingsStore(paths)
    repository = AcRepository(make_database(tmp_path))
    rows = [
        {
            "collected_at": "2026-01-02T00:00:00",
            "ap_name": "ap-a",
            "interface_name": "WLAN-Radio1/0/1",
            "rx_power": "-10.10",
            "raw_log_path": str(tmp_path / "raw.log"),
        }
    ]
    from netconsole.ui.dialogs.ap_optical_history_dialog import ApOpticalHistoryDialog

    dialog = ApOpticalHistoryDialog(I18n("en_US"), "ap-a", rows, settings)
    dialog.showMaximized()
    qt_app.processEvents()
    interface_column = [field for _key, field in AP_OPTICAL_HISTORY_COLUMNS].index("interface_name")
    dialog.table.setColumnWidth(interface_column, 280)
    dialog.table_state.save_now()
    dialog.close()

    reopened = ApOpticalHistoryDialog(I18n("en_US"), "ap-a", rows, settings)

    assert reopened.table.columnWidth(interface_column) == 280
    assert reopened.detail_table.rowCount() == len(AP_OPTICAL_HISTORY_COLUMNS)
    assert reopened.detail_table.item(1, 1).text() == "WLAN-Radio1/0/1"
    assert reopened.findChild(QScrollArea) is not None
    assert reopened.table.horizontalScrollBarPolicy() == Qt.ScrollBarAsNeeded
    assert reopened.detail_table.horizontalScrollBarPolicy() == Qt.ScrollBarAsNeeded
    reopened.splitter.setSizes([700, 300])
    reopened.close()
    split_reopened = ApOpticalHistoryDialog(I18n("en_US"), "ap-a", rows, settings)
    assert split_reopened.splitter.sizes()[0] > split_reopened.splitter.sizes()[1]


def test_ap_optical_history_dialog_hides_raw_log_actions(tmp_path):
    from netconsole.ui.dialogs.ap_optical_history_dialog import ApOpticalHistoryDialog

    rows = [{"collected_at": "2026-01-02T00:00:00", "interface_name": "GE1/0/1", "raw_log_path": "raw/ap.log"}]
    dialog = ApOpticalHistoryDialog(I18n("en_US"), "ap-a", rows, SettingsStore(PathResolver(tmp_path)))

    assert not hasattr(dialog, "open_raw_button")
    assert "raw_log_path" not in [field for _key, field in AP_OPTICAL_HISTORY_COLUMNS]


def test_ap_optical_history_export_contains_full_history(tmp_path, monkeypatch):
    qt_app = app()
    from openpyxl import load_workbook
    from netconsole.ui.dialogs.ap_optical_history_dialog import ApOpticalHistoryDialog
    import netconsole.ui.dialogs.ap_optical_history_dialog as dialog_module

    export_path = tmp_path / "ap_history.xlsx"
    monkeypatch.setattr(dialog_module, "select_export_path", lambda *_args, **_kwargs: export_path)
    repository = AcRepository(make_database(tmp_path))
    repository.replace_fit_ap_resources("ac-1", [{"ap_name": "ap-a", "serial_number": "SN-001"}])
    ap_uuid = str(repository.list_fit_ap_resources("ac-1")[0]["ap_uuid"])
    repository.replace_fit_ap_optical(
        "ac-1",
        [
            {"ap_uuid": ap_uuid, "collected_at": "2026-01-02T00:00:00", "ap_name": "ap-a", "interface_name": "GE1/0/1", "rx_power": "-10.10"},
            {"ap_uuid": ap_uuid, "collected_at": "2026-01-01T00:00:00", "ap_name": "ap-a", "interface_name": "GE1/0/2", "rx_power": "-11.10"},
        ],
    )
    dialog = ApOpticalHistoryDialog(
        I18n("en_US"),
        "ap-a",
        None,
        SettingsStore(PathResolver(tmp_path)),
        db_path=repository.database.path,
        ap_uuid=ap_uuid,
    )
    process_events_until(lambda: dialog.query_job_id is None)

    dialog.export_history()
    process_events_until(lambda: not getattr(dialog, "_netconsole_export_controllers", []))

    sheet = load_workbook(export_path).active
    assert sheet.max_row == 4
    assert sheet["B3"].value == "GE1/0/1"


def test_ap_history_column_sets_cover_lldp_and_optical():
    assert [field for _key, field in AP_LLDP_HISTORY_COLUMNS] == [
        "collected_at",
        "source",
        "is_changed",
        "conflict_flag",
        "local_interface",
        "lldp_neighbor",
        "neighbor_interface",
        "neighbor_mac",
        "neighbor_device_name",
    ]
    optical_fields = [field for _key, field in AP_OPTICAL_HISTORY_COLUMNS]
    for field in (
        "optical_alarm_status",
        "voltage",
        "bias_current",
        "rx_low_alarm",
        "rx_high_alarm",
        "tx_low_alarm",
        "tx_high_alarm",
        "rx_low_warning",
        "rx_high_warning",
        "tx_low_warning",
        "tx_high_warning",
        "module_vendor",
        "wavelength",
        "transmission_distance",
        "connector_type",
    ):
        assert field in optical_fields
    assert "raw_log_path" not in optical_fields


def test_ap_detail_metadata_site_falls_back_to_optical_site(tmp_path):
    app()
    repository = AcRepository(make_database(tmp_path))
    repository.replace_fit_ap_resources("ac-1", [{"ap_name": "ap-a", "serial_number": "SN-001"}])
    ap_uuid = repository.list_fit_ap_resources("ac-1")[0]["ap_uuid"]
    repository.replace_fit_ap_optical("ac-1", [{"ap_uuid": ap_uuid, "ap_name": "ap-a", "site": "Optical Station"}])

    dialog = FitApDetailDialog(I18n("en_US"), repository, "ac-1", ap_uuid)

    assert dialog.site_input.text() == "Optical Station"


def test_ap_detail_dialog_uses_global_theme_without_local_light_style(tmp_path):
    qt_app = app()
    apply_theme("light")
    repository = AcRepository(make_database(tmp_path))
    repository.replace_fit_ap_resources("ac-1", [{"ap_name": "ap-a", "serial_number": "SN-001"}])
    ap_uuid = repository.list_fit_ap_resources("ac-1")[0]["ap_uuid"]

    dialog = FitApDetailDialog(I18n("en_US"), repository, "ac-1", ap_uuid)

    assert dialog.styleSheet() == ""
    assert "QComboBox" in qt_app.styleSheet()
    assert "QTabWidget::pane" in qt_app.styleSheet()
    assert dialog.raw_fields_table.item(0, 0).textAlignment() == Qt.AlignCenter


def test_legacy_ap_detail_import_aliases_fit_ap_detail():
    assert ApDetailDialog is _BaseFitApDetailDialog


def test_neighbor_matcher_matches_sysname_mac_and_rx_power(tmp_path):
    database = make_database(tmp_path / "data" / "sites" / "demo" / "db")
    device_repository = DeviceRepository(database)
    device = device_repository.create(Device(name="HX Device", sysname="HX_1", ip_address="10.0.0.2"))
    fact_repository = DeviceFactRepository(database)
    fact_repository.replace_device_interfaces(
        device.device_uuid,
        [
            {
                "interface_name": "GigabitEthernet2/0/19",
                "mac_address": "903f-8645-6e00",
                "collected_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-01T00:00:00",
            }
        ],
    )
    fact_repository.replace_optical_modules(
        device.device_uuid,
        [
            {
                "interface_name": "GigabitEthernet2/0/19",
                "rx_power": "-6.66 dBm",
                "collected_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-01T00:00:00",
            }
        ],
    )

    paths = PathResolver(tmp_path)
    by_sysname = match_neighbor_device("demo", neighbor_sysname="HX_1", paths=paths)
    by_mac = match_neighbor_device("demo", neighbor_mac="903f-8645-6e00", paths=paths)

    assert by_sysname.device_uuid == device.device_uuid
    assert by_sysname.matched_by == "sysname"
    assert by_sysname.station is None
    assert by_mac.device_uuid == device.device_uuid
    assert by_mac.matched_by == "mac"
    assert find_neighbor_rx_power("demo", device.device_uuid, "GigabitEthernet2/0/19", paths=paths) == "-6.66 dBm"


def test_neighbor_matcher_reverse_matches_ap_mac_from_device_lldp(tmp_path):
    database = make_database(tmp_path / "data" / "sites" / "demo" / "db")
    device_repository = DeviceRepository(database)
    device = device_repository.create(Device(name="HX Switch", station="Station A", ip_address="10.0.0.2"))
    fact_repository = DeviceFactRepository(database)
    fact_repository.replace_lldp_neighbors(
        device.device_uuid,
        [
            {
                "local_interface": "GE2/0/22",
                "neighbor_sysname": "bc5a-3457-cbe0",
                "neighbor_mac": "bc5a-3457-cbe0",
                "neighbor_interface": "GigabitEthernet1/0/2",
                "collected_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-01T00:00:00",
            }
        ],
    )

    match = match_ap_from_device_lldp("demo", ap_mac="bc5a-3457-cbe0", paths=PathResolver(tmp_path))

    assert match.device_uuid == device.device_uuid
    assert match.device_name == "HX Switch"
    assert match.station == "Station A"
    assert match.local_interface == "GE2/0/22"
    assert match.ap_interface == "GigabitEthernet1/0/2"


def test_neighbor_matcher_reverse_matches_ap_sysname_from_device_lldp(tmp_path):
    database = make_database(tmp_path / "data" / "sites" / "demo" / "db")
    device_repository = DeviceRepository(database)
    device = device_repository.create(Device(name="HX Switch", station="Station B", ip_address="10.0.0.2"))
    DeviceFactRepository(database).replace_lldp_neighbors(
        device.device_uuid,
        [
            {
                "local_interface": "GE2/0/23",
                "neighbor_sysname": "bc5a-3457-cbe1",
                "neighbor_mac": "",
                "neighbor_interface": "GigabitEthernet1/0/2",
                "collected_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-01T00:00:00",
            }
        ],
    )

    match = match_ap_from_device_lldp("demo", ap_name="bc5a-3457-cbe1", paths=PathResolver(tmp_path))

    assert match.device_uuid == device.device_uuid
    assert match.local_interface == "GE2/0/23"


def test_neighbor_optical_module_matches_interface_alias(tmp_path):
    database = make_database(tmp_path / "data" / "sites" / "demo" / "db")
    device_repository = DeviceRepository(database)
    device = device_repository.create(Device(name="HX Switch", station="Station A", ip_address="10.0.0.2"))
    DeviceFactRepository(database).replace_optical_modules(
        device.device_uuid,
        [
            {
                "interface_name": "GigabitEthernet2/0/22",
                "rx_power": "-4.44 dBm",
                "collected_at": "2026-01-01T00:00:00",
                "updated_at": "2026-01-01T00:00:00",
            }
        ],
    )

    module = find_neighbor_optical_module("demo", device.device_uuid, "GE2/0/22", paths=PathResolver(tmp_path))

    assert normalize_interface_name("GE2/0/22") == "GigabitEthernet2/0/22"
    assert normalize_interface_name("XGE1/0/49") == "Ten-GigabitEthernet1/0/49"
    assert module["rx_power"] == "-4.44 dBm"


def test_neighbor_matcher_prefers_fact_sysname_and_returns_station(tmp_path):
    database = make_database(tmp_path / "data" / "sites" / "demo" / "db")
    device_repository = DeviceRepository(database)
    device = device_repository.create(Device(name="HX Device", sysname="HX_DEVICE", station="Station A", ip_address="10.0.0.2"))
    fact_repository = DeviceFactRepository(database)
    fact_repository.upsert_device_fact(
        {
            "device_uuid": device.device_uuid,
            "sysname": "HX_1",
            "collected_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        }
    )

    match = match_neighbor_device("demo", neighbor_sysname="HX_1", paths=PathResolver(tmp_path))

    assert match.device_uuid == device.device_uuid
    assert match.device_name == "HX Device"
    assert match.station == "Station A"


def test_fit_ap_optical_command_guard_allows_only_expected_commands():
    allowed = {
        "screen-length disable",
        "display lldp neighbor-information list",
        "display transceiver diagnosis interface",
        "display transceiver interface",
        "display transceiver manuinfo interface",
    }

    assert all(command_guard.is_command_allowed(command, "fit_ap_collect") for command in allowed)
    assert command_guard.is_command_allowed("display interface", "fit_ap_collect") is False
    assert command_guard.is_command_allowed("reboot", "fit_ap_collect") is False


def test_ac_log_event_names_do_not_contain_password():
    event_names = (
        "AC_COLLECT_STARTED",
        "AC_COLLECT_SUCCESS",
        "AC_COLLECT_FAILED",
        "FIT_AP_RESOURCE_UPDATED",
        "FIT_AP_OPTICAL_STARTED",
        "FIT_AP_OPTICAL_SUCCESS",
        "FIT_AP_OPTICAL_PARTIAL_SUCCESS",
        "FIT_AP_OPTICAL_FAILED",
        "FIT_AP_TELNET_FAILED",
    )

    assert all("PASSWORD" not in event for event in event_names)


def test_database_runtime_has_no_legacy_migration_chain():
    text = (Path(__file__).parents[1] / "netconsole" / "core" / "database.py").read_text(encoding="utf-8")

    assert text.count("ALTER TABLE") == 1
    assert "ALTER TABLE ac_trackside_ap_plan ADD COLUMN remark TEXT" in text
    assert "DROP TABLE" not in text
    assert "migrate_old_" not in text
    assert "legacy_table_adapter" not in text


def test_three_module_status_consistency_same_device_same_result(tmp_path):
    """Verify that the same device shows identical optical status across all three modules:
    device detail, FIT-AP optical, and trackside AP business."""
    database = make_database(tmp_path / "data" / "sites" / "demo" / "db")
    device_repository = DeviceRepository(database)
    switch = device_repository.create(Device(name="HX_1", station="Station A", ip_address="10.0.0.2"))
    fact_repository = DeviceFactRepository(database)
    fact_repository.replace_device_interfaces(
        switch.device_uuid,
        [{"interface_name": "GigabitEthernet2/0/10", "description": "To_AP10", "link_status": "UP", "collected_at": "2026-01-01T00:00:00"}],
    )
    fact_repository.replace_optical_modules(
        switch.device_uuid,
        [{"interface_name": "GigabitEthernet2/0/10", "rx_power": "-6.10", "status": "normal", "collected_at": "2026-01-01T00:00:00"}],
    )
    fact_repository.replace_lldp_neighbors(
        switch.device_uuid,
        [{"local_interface": "GE2/0/10", "neighbor_mac": "bc5a-3457-cbe0", "neighbor_interface": "GigabitEthernet1/0/2", "collected_at": "2026-01-01T00:00:00"}],
    )
    ac = device_repository.create(make_ac_device())
    ac_repository = AcRepository(database)
    ac_repository.replace_fit_ap_optical(
        ac.device_uuid,
        [{"ap_uuid": "ap-10", "ap_mac": "bc5a-3457-cbe0", "ap_name": "AP10", "neighbor_device_name": "HX_1", "neighbor_interface": "GigabitEthernet2/0/10", "rx_power": "-14.35", "rx_low_alarm": "-19.00", "rx_low_warning": "-16.99", "optical_alarm_status": "warning"}],
    )

    # Device detail: compute switch status real-time from raw optical module data
    optical_modules = fact_repository.list_optical_modules(switch.device_uuid)
    from netconsole.core.sources.switch_source import compute_switch_status
    device_detail_switch_status = compute_switch_status(
        switch_rx_power=optical_modules[0].get("rx_power"),
    )
    assert device_detail_switch_status == "unknown"

    # FIT-AP optical: switch_optical_status must reference device detail
    devices = device_repository.list()
    optical_by_device = {str(d.device_uuid or ""): fact_repository.list_optical_modules(str(d.device_uuid or "")) for d in devices}
    lookup = build_switch_data_lookup(devices, optical_by_device)
    fit_ap_rows = enrich_fit_ap_optical_rows(
        ac_repository.list_fit_ap_optical(ac.device_uuid),
        ac_repository.list_fit_ap_resources_with_metadata(ac.device_uuid),
        lookup,
    )
    fit_ap_switch_status = fit_ap_rows[0]["switch_optical_status"]
    assert fit_ap_switch_status == device_detail_switch_status, (
        f"FIT-AP switch_optical_status ({fit_ap_switch_status}) != device detail ({device_detail_switch_status})"
    )

    # Trackside AP business: switch_optical_status must also reference device detail
    trackside_rows = build_trackside_ap_business_rows(
        [switch],
        {switch.device_uuid: fact_repository.list_device_interfaces(switch.device_uuid)},
        {switch.device_uuid: optical_modules},
        ac_repository.list_all_fit_ap_optical(),
        {switch.device_uuid: fact_repository.list_lldp_neighbors(switch.device_uuid)},
        ac_repository.list_all_fit_ap_resources_with_metadata(),
        lookup,
    )
    trackside_switch_status = trackside_rows[0]["switch_optical_status"]
    assert trackside_switch_status == device_detail_switch_status, (
        f"Trackside switch_optical_status ({trackside_switch_status}) != device detail ({device_detail_switch_status})"
    )

    # Trackside ap_optical_status must match FIT-AP optical_alarm_status
    fit_ap_ap_status = evaluate_fit_ap_ap_status(fit_ap_rows[0])
    trackside_ap_status = trackside_rows[0]["ap_optical_status"]
    assert trackside_ap_status == fit_ap_ap_status, (
        f"Trackside ap_optical_status ({trackside_ap_status}) != FIT-AP ({fit_ap_ap_status})"
    )


def test_build_device_optical_status_lookup_indexes_by_name_and_sysname(tmp_path):
    """The lookup must resolve both device.name and device.sysname."""
    database = make_database(tmp_path / "data" / "sites" / "demo" / "db")
    device_repository = DeviceRepository(database)
    device = device_repository.create(Device(name="HX Switch", sysname="HX_1", ip_address="10.0.0.2"))
    fact_repository = DeviceFactRepository(database)
    fact_repository.replace_optical_modules(
        device.device_uuid,
        [{"interface_name": "GigabitEthernet2/0/10", "status": "warning", "collected_at": "2026-01-01T00:00:00"}],
    )

    devices = device_repository.list()
    optical_by_device = {str(device.device_uuid): fact_repository.list_optical_modules(device.device_uuid)}
    lookup = build_switch_data_lookup(devices, optical_by_device)

    # Both name and sysname should resolve to the raw optical module row
    name_result = lookup.get(("hx switch", "gigabitethernet2/0/10"))
    assert name_result is not None
    assert name_result.get("collected_at") == "2026-01-01T00:00:00"
    sysname_result = lookup.get(("hx_1", "gigabitethernet2/0/10"))
    assert sysname_result is not None
    # Non-existent name should not resolve
    assert lookup.get(("nonexistent", "gigabitethernet2/0/10")) is None


def test_fit_ap_switch_status_computes_from_raw_data():
    """evaluate_fit_ap_switch_status must compute from raw data, not read cached fields."""
    # With raw rx_power data, status is computed real-time
    assert evaluate_fit_ap_switch_status({"neighbor_rx_power": "-10.00"}) == "unknown"
    assert evaluate_fit_ap_switch_status({"neighbor_rx_power": "-20.00", "rx_low_alarm": "-19.00", "warning_low": "-16.99"}) == "alarm"
    assert evaluate_fit_ap_switch_status({"neighbor_rx_power": "-14.35", "rx_low_alarm": "-19.00", "warning_low": "-16.99"}) == "notice"


def test_trackside_ap_optical_status_computes_from_raw_data():
    """Trackside ap_optical_status must be computed real-time from raw FIT-AP rx_power."""
    switch = Device(name="HX_1", station="Station A", device_uuid="sw-1")
    rows = build_trackside_ap_business_rows(
        [switch],
        {"sw-1": [{"interface_name": "GigabitEthernet2/0/10", "description": "To_AP10"}]},
        {"sw-1": [{"interface_name": "GigabitEthernet2/0/10", "rx_power": "-6.10"}]},
        [
            {
                "ap_uuid": "ap-10",
                "ap_mac": "bc5a-3457-cbe0",
                "ap_name": "AP10",
                "neighbor_device_name": "HX_1",
                "neighbor_interface": "GigabitEthernet2/0/10",
                "rx_power": "-20.32",
                "rx_low_alarm": "-20.00",
                "rx_low_warning": "-17.00",
            }
        ],
    )
    # ap_optical_status is computed real-time: -20.32 < -20.00 → alarm
    assert rows[0]["ap_optical_status"] == "alarm"
    # switch_optical_status is computed real-time: -6.10 → normal
    assert rows[0]["switch_optical_status"] == "unknown"


# ── Unified State Architecture tests ──────────────────────────────────────────


def test_state_engine_compute_state_returns_unified_result():
    """compute_state must return a StateResult with all status fields populated."""
    from netconsole.core.state_engine import StateResult

    result = compute_state({
        "switch_rx_power": "-14.35",
        "switch_alarm_low": "-19.00",
        "switch_warning_low": "-16.99",
        "fit_ap_row": {"rx_power": "-20.32", "rx_low_alarm": "-20.00", "rx_low_warning": "-17.00"},
    })
    assert isinstance(result, StateResult)
    assert result.switch_status == "notice"
    assert result.ap_status == "alarm"
    assert result.optical_status == "alarm"   # worse of notice/alarm
    assert result.severity > 0
    assert result.color == STATUS_COLORS["alarm"]


def test_state_engine_minus_36_96_no_light_unified():
    """rx_power = -36.96 must produce no_light with unified gray colour."""
    from netconsole.core.state_engine import StateResult

    fit_ap_row = {
        "rx_power": "-36.96",
        "rx_low_alarm": "-20.00",
        "rx_low_warning": "-17.00",
        "optical_alarm_status": "no_light",
    }
    result = compute_state({"fit_ap_row": fit_ap_row})
    assert result.ap_status == "no_light"
    assert result.color == STATUS_COLORS["no_light"]
    assert result.color == "E5E7EB"


def test_state_engine_minus_20_32_alarm_unified():
    """rx_power = -20.32 with alarm_low = -20.00 must produce alarm (below threshold)."""
    fit_ap_row = {
        "rx_power": "-20.32",
        "rx_low_alarm": "-20.00",
        "rx_low_warning": "-17.00",
    }
    result = compute_state({"fit_ap_row": fit_ap_row})
    assert result.ap_status == "alarm"
    assert result.color == STATUS_COLORS["alarm"]
    assert result.color == "FEE2E2"


def test_state_engine_link_down_unified_pink():
    """link_down / link_abnormal must produce unified pink colour."""
    for status in ("link_down", "link_abnormal"):
        result = compute_state({
            "switch_rx_power": "-10.00",
            "switch_port_status": "DOWN",
            "fit_ap_row": {"rx_power": "-10.00", "ap_port_status": "DOWN"},
        })
        assert result.optical_status in ("link_abnormal",)
        assert result.color == STATUS_COLORS["link_abnormal"]


def test_state_engine_three_pages_same_input_same_output():
    """Given the same input, FIT-AP / Trackside / DeviceDetail must produce identical statuses."""
    from netconsole.core.view_models import (
        FITAPViewModel,
        TracksideViewModel,
        DeviceDetailViewModel,
    )

    # Raw optical module data for switch side — computes to "alarm"
    switch_data_lookup = {
        ("hx_1", "gigabitethernet2/0/10"): {
            "rx_power": "-20.00",
            "rx_low_alarm": "-19.00",
            "rx_low_warning": "-16.99",
            "port_status": "access",
        }
    }

    fit_ap_vm = FITAPViewModel(switch_data_lookup=switch_data_lookup)
    trackside_vm = TracksideViewModel(switch_data_lookup=switch_data_lookup)
    device_vm = DeviceDetailViewModel(switch_data_lookup=switch_data_lookup)

    fit_ap_row = {
        "device_name": "HX_1",
        "local_interface": "GigabitEthernet2/0/10",
        "neighbor_device_name": "HX_1",
        "neighbor_interface": "GigabitEthernet2/0/10",
        "rx_power": "-14.35",
        "rx_low_alarm": "-19.00",
        "rx_low_warning": "-16.99",
    }

    # FIT-AP ViewModel
    fit_ap_result = fit_ap_vm.populate_row(fit_ap_row)
    assert fit_ap_result.switch_status == "alarm"
    assert fit_ap_result.ap_status == "notice"

    # Trackside ViewModel (using same FIT-AP row)
    trackside_row = {
        "device_name": "HX_1",
        "interface_name": "GigabitEthernet2/0/10",
    }
    trackside_result = trackside_vm.populate_row(trackside_row, fit_ap_row)
    assert trackside_result.switch_status == fit_ap_result.switch_status
    assert trackside_result.ap_status == fit_ap_result.ap_status
    assert trackside_result.color == fit_ap_result.color

    # DeviceDetail ViewModel (switch only)
    device_color = device_vm.get_color(
        device_name="HX_1",
        interface_name="GigabitEthernet2/0/10",
    )
    assert device_color == STATUS_COLORS["alarm"]


def test_state_engine_no_ui_computes_status():
    """UI-layer evaluate functions must compute from raw data, not read cached fields."""
    # evaluate_fit_ap_ap_status must compute from raw rx_power
    assert evaluate_fit_ap_ap_status({"rx_power": "-36.96"}) == "no_light"
    # evaluate_fit_ap_switch_status must compute from raw neighbor_rx_power
    assert evaluate_fit_ap_switch_status({"neighbor_rx_power": "-14.35", "rx_low_alarm": "-19.00", "warning_low": "-16.99"}) == "notice"
    # evaluate_fit_ap_row_status must go through compute_state with raw data
    row = {"neighbor_rx_power": "-10.00", "rx_power": "-20.32", "rx_low_alarm": "-20.00", "rx_low_warning": "-17.00"}
    assert evaluate_fit_ap_row_status(row) == "alarm"
