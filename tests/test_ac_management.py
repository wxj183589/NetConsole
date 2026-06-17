import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QApplication, QMessageBox, QMenu

from netconsole.core.bootstrap import create_demo_context
from netconsole.core.database import Database
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.parsers.h3c.ac.fit_ap_optical_parser import parse_fit_ap_lldp, parse_fit_ap_optical, parse_fit_ap_transceiver
from netconsole.parsers.h3c.ac.state_mapper import map_fit_ap_state
from netconsole.parsers.h3c.ac.system_usage_parser import parse_cpu_usage, parse_memory
from netconsole.parsers.h3c.ac.wlan_ap_address_parser import parse_wlan_ap_addresses
from netconsole.parsers.h3c.ac.wlan_ap_parser import parse_wlan_ap_list, parse_wlan_ap_summary
from netconsole.parsers.h3c.ac.wlan_ap_radio_parser import parse_wlan_ap_radios
from netconsole.repositories.ac_repository import AcRepository
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services.fit_ap_import_export import FitApImportExportService
from netconsole.services import h3c_ac_collect_service
from netconsole.services import command_guard
from netconsole.services.h3c_ac_collect_service import RESOURCE_COMMANDS, collect_h3c_ac_resources
from netconsole.services.netmiko_connection import normalize_command_output
from netconsole.services.neighbor_matcher import find_neighbor_optical_module, find_neighbor_rx_power, match_ap_from_device_lldp, match_neighbor_device, normalize_interface_name
from netconsole.ui.pages.ac_management_page import (
    AP_ONLINE_OVERVIEW_COLUMNS,
    AcManagementPage,
    FIT_AP_OPTICAL_COLUMNS,
    FIT_AP_RESOURCE_COLUMNS,
    build_ap_online_overview_rows,
    build_site_filter_items,
    enrich_fit_ap_optical_rows,
    evaluate_fit_ap_row_status,
    export_ap_online_overview_xlsx,
    export_fit_ap_optical_xlsx,
    filter_fit_ap_optical_rows,
    sort_fit_ap_optical_rows,
)
from netconsole.ui.ac_collect_worker import FitApOpticalCollectThread
from netconsole.ui.dialogs.ap_detail_dialog import ApDetailDialog
from netconsole.ui.dialogs.ap_history_dialog import AP_LLDP_HISTORY_COLUMNS, AP_OPTICAL_HISTORY_COLUMNS, AP_RADIO_HISTORY_COLUMNS, ApHistoryDialog, export_ap_history_xlsx
from netconsole.ui.dialogs.fit_ap_detail_dialog import FIT_AP_DETAIL_TABS, FitApDetailDialog
from netconsole.ui.dialogs.station_online_history_dialog import STATION_ONLINE_HISTORY_COLUMNS, StationOnlineHistoryDialog, export_station_online_history_xlsx
from netconsole.utils.optical_status import display_optical_status


FIXTURES = Path(__file__).parent / "fixtures" / "h3c"
AC_FIXTURES = FIXTURES / "ac"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def ac_fixture(name: str) -> str:
    return (AC_FIXTURES / name).read_text(encoding="utf-8")


class FakeConnection:
    def __init__(self):
        self.commands = []
        self.disconnected = False

    def send_command(self, command, read_timeout=None):
        self.commands.append(command)
        return {
            "screen-length disable": "",
            "display wlan ap all": fixture("display_wlan_ap_all.txt"),
            "display wlan ap all address": fixture("display_wlan_ap_all_address.txt"),
            "display wlan ap all radio": fixture("display_wlan_ap_all_radio.txt"),
            "display cpu-usage": fixture("display_cpu_usage.txt"),
            "display memory": fixture("display_memory.txt"),
            "display version": fixture("display_version.txt"),
            "display device": fixture("display_device_ac.txt"),
            "display device manuinfo": fixture("display_device_manuinfo.txt"),
        }[command]

    def disconnect(self):
        self.disconnected = True


def app():
    return QApplication.instance() or QApplication([])


def make_database(tmp_path):
    database = Database(tmp_path / "devices.db")
    database.initialize()
    return database


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


def test_station_ap_capacity_is_not_overwritten_by_new_overview_data(tmp_path):
    repository = AcRepository(make_database(tmp_path))
    repository.upsert_station_ap_capacity("Station A", 56)

    overview = build_ap_online_overview_rows([{"site": "Station A", "state": "R/M"}], capacities=repository.list_station_ap_capacities())

    assert overview[0]["total"] == 56
    assert overview[0]["online"] == 1
    assert overview[0]["offline"] == 55


def test_ac_repository_metadata_crud_batch_edit_and_delete(tmp_path):
    repository = AcRepository(make_database(tmp_path))
    repository.replace_fit_ap_resources("ac-1", [{"ap_name": "ap-a"}, {"ap_name": "ap-b"}])
    repository.replace_fit_ap_optical("ac-1", [{"ap_name": "ap-a"}, {"ap_name": "ap-b"}])

    repository.upsert_fit_ap_metadata({"ap_name": "ap-a", "site_name": "S1"})
    assert repository.get_fit_ap_metadata("ap-a")["site_name"] == "S1"
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
        "raw/ac/run-1/ac.log",
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
    assert "optical_alarm_status" in parsed


def test_fit_ap_lldp_parser_handles_fit_ap_table_format():
    parsed = parse_fit_ap_lldp(
        """
System Name          Local Interface Chassis ID      Port ID
HX_1                 GE1/0/2         903f-8645-6e00  GigabitEthernet2/0/19
"""
    )

    assert parsed["lldp_neighbor"] == "HX_1"
    assert parsed["interface_name"] == "GE1/0/2"
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


def test_h3c_ac_collect_service_uses_mock_netmiko(monkeypatch, tmp_path):
    connection = FakeConnection()
    monkeypatch.setattr(h3c_ac_collect_service.netmiko_connection, "ConnectHandler", lambda **_kwargs: connection)
    database = make_database(tmp_path)
    repository = AcRepository(database)

    result = collect_h3c_ac_resources(make_ac_device(), "demo", repository=repository, paths=PathResolver(tmp_path))

    assert result.success is True
    assert result.summary_updated is True
    assert result.fit_ap_resources_updated == 2
    assert connection.commands == ["screen-length disable", *RESOURCE_COMMANDS]
    assert connection.disconnected is True
    assert Path(result.raw_log_path).exists()
    assert repository.get_ac_ap_summary("22222222-2222-4222-8222-222222222222")["total_aps"] == 2
    assert repository.get_ac_ap_summary("22222222-2222-4222-8222-222222222222")["cpu_usage"] == "16%"
    assert repository.get_ac_ap_summary("22222222-2222-4222-8222-222222222222")["memory_usage"] == "47%"
    assert repository.list_fit_ap_resources("22222222-2222-4222-8222-222222222222")[0]["ap_ip"] == "10.0.0.61"


def test_h3c_ac_collect_service_validates_commands_before_execution(monkeypatch, tmp_path):
    calls = []
    connection = FakeConnection()
    monkeypatch.setattr(h3c_ac_collect_service.netmiko_connection, "ConnectHandler", lambda **_kwargs: connection)
    monkeypatch.setattr(h3c_ac_collect_service.command_guard, "validate_command_list", lambda commands, context: calls.append((list(commands), context)))
    database = make_database(tmp_path)
    repository = AcRepository(database)

    collect_h3c_ac_resources(make_ac_device(), "demo", repository=repository, paths=PathResolver(tmp_path))

    assert calls == [(["screen-length disable", *RESOURCE_COMMANDS], "ac_collect")]


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
        "serial_number",
        "state_display",
        "group_name",
        "online_time",
        "updated_at",
    ]
    assert [field for _key, field in FIT_AP_OPTICAL_COLUMNS] == [
        "ap_name",
        "ap_mac",
        "site",
        "neighbor_device_name",
        "neighbor_interface",
        "neighbor_rx_power",
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
        "ac.ap_side_rx_power",
        "ap.optical_alarm_status",
        "field.updated_at",
    ]
    assert "ac.ap_name_mac" not in [key for key, _field in FIT_AP_OPTICAL_COLUMNS]
    assert [page.optical_concurrency_combo.itemData(index) for index in range(page.optical_concurrency_combo.count())] == [50, 100, 200, 500, 1000]
    assert page.optical_concurrency_combo.currentData() == 500
    assert page.optical_legend_label.text()
    assert page.tabs.tabText(2) == "AP Online Overview"
    assert page.tabs.tabText(3) == "Online Vehicle MR"


def test_fit_ap_optical_table_colors_no_light_rows(tmp_path):
    app()
    context = create_demo_context(PathResolver(tmp_path))
    page = AcManagementPage(context.repository, I18n("en_US"), "demo")
    page._set_rows(page.optical_table, FIT_AP_OPTICAL_COLUMNS, [{"ap_name": "ap-a", "optical_alarm_status": "no_light"}])

    assert page.optical_table.item(0, 0).background().color().name() == "#e5e7eb"
    assert page.optical_table.item(0, 0).textAlignment() == Qt.AlignCenter


def test_fit_ap_optical_thread_accepts_concurrency():
    thread = FitApOpticalCollectThread(make_ac_device(), "demo", 200, None)

    assert thread.concurrency == 200


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
        {"ap_name": "AP-A", "ap_mac": "0011-2233-4455", "site": "S1", "lldp_neighbor": "HX_1", "neighbor_device_name": "Core-A", "optical_alarm_status": "normal"},
        {"ap_name": "AP-B", "ap_mac": "aabb-ccdd-eeff", "site": "S2", "lldp_neighbor": "HX_2", "neighbor_device_name": "Access-B", "optical_alarm_status": "warning"},
    ]

    assert [row["ap_name"] for row in filter_fit_ap_optical_rows(rows, {"ap_name": "ap-a"})] == ["AP-A"]
    assert [row["ap_name"] for row in filter_fit_ap_optical_rows(rows, {"site": "s2"})] == ["AP-B"]
    assert [row["ap_name"] for row in filter_fit_ap_optical_rows(rows, {"optical_alarm_status": "warning"})] == ["AP-B"]


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


def test_fit_ap_optical_filters_do_not_include_ap_mac(tmp_path):
    app()
    context = create_demo_context(PathResolver(tmp_path))
    page = AcManagementPage(context.repository, I18n("en_US"), "demo")

    assert not hasattr(page, "optical_ap_mac_filter")


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
    page.optical_ap_filter.setText("AP-A")
    assert page.optical_table.rowCount() == 1

    page.clear_optical_filters()

    assert page.optical_table.rowCount() == 2
    assert page.optical_ap_filter.text() == ""
    assert page.optical_site_filter.currentData() == ""
    assert page.optical_alarm_filter.currentData() == ""


def test_evaluate_fit_ap_row_status_includes_neighbor_rx_power():
    assert evaluate_fit_ap_row_status({"optical_alarm_status": "normal", "neighbor_rx_power": "-36.00"}) == "no_light"
    assert (
        evaluate_fit_ap_row_status(
            {"optical_alarm_status": "normal", "neighbor_rx_power": "-25.00"},
            {"rx_power": "-25.00", "tx_power": "-5.00", "rx_low_alarm": "-20.00", "rx_high_alarm": "0.00", "tx_low_alarm": "-20.00", "tx_high_alarm": "0.00"},
        )
        == "alarm"
    )
    assert evaluate_fit_ap_row_status({"optical_alarm_status": "warning", "neighbor_rx_power": "-10.00"}) == "warning"


def test_display_optical_status_uses_chinese_labels():
    assert display_optical_status("normal") == "正常"
    assert display_optical_status("warning") == "提示告警"
    assert display_optical_status("alarm") == "一般告警"
    assert display_optical_status("link_abnormal") == "链路异常"
    assert display_optical_status("no_light") == "无光"
    assert display_optical_status("skipped") == "未检查"
    assert display_optical_status("unknown") == "未知"


def test_fit_ap_optical_table_displays_chinese_status(tmp_path):
    app()
    context = create_demo_context(PathResolver(tmp_path))
    page = AcManagementPage(context.repository, I18n("zh_CN"), "demo")

    page._set_rows(page.optical_table, FIT_AP_OPTICAL_COLUMNS, [{"ap_name": "AP-A", "optical_alarm_status": "alarm"}])

    values = [page.optical_table.item(0, column).text() for column in range(page.optical_table.columnCount())]
    assert "一般告警" in values
    assert "alarm" not in values


def test_export_fit_ap_optical_xlsx_contains_headers_colors_and_legend(tmp_path):
    from openpyxl import load_workbook

    export_path = tmp_path / "optical.xlsx"
    rows = [
        {"ap_name": "AP-A", "ap_mac": "0011-2233-4455", "site": "S1", "optical_alarm_status": "alarm", "updated_at": "2026-01-01"},
        {"ap_name": "AP-B", "ap_mac": "0011-2233-4456", "site": "S1", "optical_alarm_status": "warning", "updated_at": "2026-01-01"},
    ]
    headers = ["AP名称", "AP_MAC", "车站", "室内交换机", "室内端口号", "室内交换机收光(dBm)", "AP侧收光(dBm)", "光告警", "更新时间"]

    export_fit_ap_optical_xlsx(export_path, rows, FIT_AP_OPTICAL_COLUMNS, headers, "Legend text")

    workbook = load_workbook(export_path)
    sheet = workbook["FIT-AP Optical"]
    assert export_path.exists()
    assert [cell.value for cell in sheet[1]] == headers
    assert "AP名称MAC" not in [cell.value for cell in sheet[1]]
    assert sheet["H2"].value == "一般告警"
    assert sheet["H3"].value == "提示告警"
    assert sheet["A2"].fill.fgColor.rgb == "00FEE2E2"
    assert sheet["A3"].fill.fgColor.rgb == "00FEF9C3"
    assert sheet["A1"].alignment.horizontal == "center"
    assert sheet["A1"].alignment.vertical == "center"
    assert sheet["A2"].alignment.horizontal == "center"
    assert sheet.column_dimensions["A"].width > len("AP名称")
    assert "说明" in workbook.sheetnames
    assert workbook["说明"]["A1"].value == "Legend text"


def test_fit_ap_optical_warning_row_uses_light_yellow(tmp_path):
    app()
    context = create_demo_context(PathResolver(tmp_path))
    page = AcManagementPage(context.repository, I18n("en_US"), "demo")

    page._set_rows(page.optical_table, FIT_AP_OPTICAL_COLUMNS, [{"ap_name": "AP-A", "optical_alarm_status": "warning"}])

    assert page.optical_table.item(0, 0).background().color().name() == "#fef9c3"


def test_optical_color_legend_mentions_rx_low_warning():
    assert "RX警告下限" in I18n("zh_CN").t("details.optical_color_legend")
    assert "RX low warning" in I18n("en_US").t("details.optical_color_legend")


def test_ap_online_overview_rows_count_states_and_total_bottom():
    rows = [
        {"site": "02云龙火车站站", "state": "R/M"},
        {"site": "02云龙火车站站", "state": "R/B"},
        {"site": "01小洋江站", "state": "I"},
        {"site": "01小洋江站", "state": "JA"},
        {"site": "01小洋江站", "state": "R"},
    ]

    overview = build_ap_online_overview_rows(rows)

    assert overview[0] == {"site": "01小洋江站", "total": 1, "online": 1, "offline": 0, "remark": "", "online_rate": "100.0%"}
    assert overview[1] == {"site": "02云龙火车站站", "total": 2, "online": 2, "offline": 0, "remark": "", "online_rate": "100.0%"}
    assert overview[-1] == {"site": "合计", "total": 3, "online": 3, "offline": 0, "remark": "", "online_rate": "100.0%"}


def test_ap_online_overview_uses_site_priority_capacity_and_unassigned():
    resources = [
        {"ap_uuid": "ap-1", "site_name": "Metadata Station", "site": "Resource Station", "state": "R/M"},
        {"ap_uuid": "ap-2", "site": "", "state": "JA"},
    ]
    optical = [{"ap_uuid": "ap-1", "site": "Optical Station"}]

    overview = build_ap_online_overview_rows(resources, optical, {"Optical Station": {"ap_total": 5, "remark": "Keep watching"}})

    assert [row["site"] for row in overview] == ["Optical Station", "未归属", "合计"]
    assert overview[0]["total"] == 5
    assert overview[0]["online"] == 1
    assert overview[0]["offline"] == 4
    assert overview[0]["remark"] == "Keep watching"
    assert overview[1]["total"] == 0
    assert overview[1]["offline"] == 0


def test_ap_online_overview_deduplicates_by_uuid_serial_and_mac():
    rows = [
        {"ap_uuid": "ap-1", "serial_number": "SN-1", "ap_mac": "mac-1", "site": "S1", "state": "R/M"},
        {"ap_uuid": "ap-1", "serial_number": "SN-1", "ap_mac": "mac-1", "site": "S1", "state": "R/M"},
        {"serial_number": "SN-2", "ap_mac": "mac-2", "site": "S1", "state": "R/B"},
        {"serial_number": "SN-2", "ap_mac": "mac-2", "site": "S1", "state": "R/B"},
        {"ap_mac": "mac-3", "site": "S1", "state": "I"},
        {"ap_mac": "mac-3", "site": "S1", "state": "I"},
    ]

    overview = build_ap_online_overview_rows(rows, capacities={"S1": 5})

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
        "车站",
        "AP总数量",
        "上线",
        "未上线",
        "上线率",
        "备注",
    ]


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
    page = AcManagementPage(device_repository, I18n("en_US"), "demo")

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
    repository.upsert_station_ap_capacity("Station A", 9)
    repository.upsert_station_ap_remark("Station A", "Persistent remark")

    page = AcManagementPage(device_repository, I18n("en_US"), "demo")
    assert page.overview_table.item(0, 1).text() == "9"
    assert page.overview_table.item(0, 5).text() == "Persistent remark"

    repository.replace_fit_ap_resources(
        ac.device_uuid,
        [
            {"ap_uuid": "ap-1", "serial_number": "SN-1", "site": "Station A", "state": "R/M"},
            {"ap_uuid": "ap-2", "serial_number": "SN-2", "site": "Station A", "state": "R/B"},
        ],
    )
    page.refresh_data()
    assert page.overview_table.item(0, 1).text() == "9"
    assert page.overview_table.item(0, 2).text() == "2"
    assert page.overview_table.item(0, 3).text() == "7"
    assert page.overview_table.item(0, 5).text() == "Persistent remark"

    reloaded = AcManagementPage(device_repository, I18n("en_US"), "demo")
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

    page = AcManagementPage(device_repository, I18n("en_US"), "demo")

    assert page.overview_table.item(0, 1).text() == "1"
    assert page.overview_table.item(0, 2).text() == "1"
    assert page.overview_table.item(0, 3).text() == "0"


def test_ap_online_overview_rejects_invalid_total_and_restores(monkeypatch, tmp_path):
    app()
    database = make_database(tmp_path)
    device_repository = DeviceRepository(database)
    ac = device_repository.create(make_ac_device())
    repository = AcRepository(database)
    repository.replace_fit_ap_resources(ac.device_uuid, [{"ap_uuid": "ap-1", "serial_number": "SN-1", "site": "Station A", "state": "R/M"}])
    repository.upsert_station_ap_capacity("Station A", 5)
    page = AcManagementPage(device_repository, I18n("en_US"), "demo")
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))

    page.overview_table.item(0, 1).setText("")

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
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args))

    page.save_overview_history_snapshot()
    history = repository.list_station_online_summary_history("Station A")

    assert messages
    assert len(history) == 1
    assert history[0]["ap_total"] == 3
    assert history[0]["remark"] == "Snapshot note"


def test_export_ap_online_overview_xlsx_contains_colors_and_alignment(tmp_path):
    from openpyxl import load_workbook

    export_path = tmp_path / "overview.xlsx"
    rows = build_ap_online_overview_rows(
        [
            {"site": "01小洋江站", "state": "R"},
            {"site": "02云龙火车站站", "state": "I"},
        ],
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


def test_station_online_history_dialog_columns_and_filter(tmp_path):
    app()
    rows = [
        {"collected_at": "2026-01-02T00:00:00", "site_name": "Station A", "ap_total": 3, "online_count": 2, "offline_count": 1, "online_rate": "66.7%", "remark": "A"},
        {"collected_at": "2026-01-01T00:00:00", "site_name": "Station B", "ap_total": 4, "online_count": 4, "offline_count": 0, "online_rate": "100.0%", "remark": "B"},
    ]

    dialog = StationOnlineHistoryDialog(I18n("en_US"), rows, "Station A")

    assert STATION_ONLINE_HISTORY_COLUMNS[-1] == ("field.remark", "remark")
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
    assert dialog.table.rowCount() == 1
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
    repository = AcRepository(make_database(tmp_path))
    service = FitApImportExportService(repository)
    import_path = tmp_path / "metadata.csv"
    import_path.write_text("AP名称,归属站点,里程,点位说明,上下行\nap-a,体育中心站,K12+450,下行区间,CW\n", encoding="utf-8-sig")

    result = service.import_metadata_csv(import_path)

    assert result.updated == 1
    assert repository.get_fit_ap_metadata("ap-a")["direction"] == "上行"

    export_path = tmp_path / "export.csv"
    service.export_ap_csv(export_path, [{"ap_name": "ap-a", "ap_ip": "10.0.0.1", "state_display": "运行(主)", "site": "体育中心站"}])
    text = export_path.read_text(encoding="utf-8-sig")
    assert "AP名称" in text
    assert "ap-a" in text


def test_ap_detail_dialog_opens_and_saves_metadata(tmp_path):
    app()
    repository = AcRepository(make_database(tmp_path))
    repository.replace_fit_ap_resources("ac-1", [{"ap_name": "ap-a", "state_display": "运行(主)", "state_raw": "R/M"}])

    dialog = FitApDetailDialog(I18n("en_US"), repository, "ac-1", "ap-a")
    dialog.site_input.setText("Station A")
    dialog.save_metadata()

    assert dialog.windowTitle() == "AP Details - ap-a"
    assert dialog.minimumWidth() == 760
    assert dialog.minimumHeight() == 520
    assert dialog.tabs.count() == 6
    assert FIT_AP_DETAIL_TABS == ("basic", "metadata", "radio", "lldp", "optical", "raw_fields")
    assert dialog.raw_fields_table.rowCount() > 0
    assert repository.get_fit_ap_metadata("ap-a")["site_name"] == "Station A"


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
    assert dialog.optical_history_button.text() == "View History"
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
    assert not history.isVisible()

    second = ApHistoryDialog(I18n("en_US"), "ap-a", "Radio", [], AP_RADIO_HISTORY_COLUMNS, parent=parent)
    second.show()
    qt_app.processEvents()
    second.close()
    qt_app.processEvents()

    assert parent.isVisible()
    assert not second.isVisible()


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
    assert dialog.history_windows
    assert dialog.history_windows[-1].isVisible()


def test_ap_history_column_sets_cover_lldp_and_optical():
    assert [field for _key, field in AP_LLDP_HISTORY_COLUMNS] == [
        "collected_at",
        "local_interface",
        "lldp_neighbor",
        "neighbor_interface",
        "neighbor_mac",
        "neighbor_device_name",
        "raw_log_path",
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
        "raw_log_path",
    ):
        assert field in optical_fields


def test_ap_detail_metadata_site_falls_back_to_optical_site(tmp_path):
    app()
    repository = AcRepository(make_database(tmp_path))
    repository.replace_fit_ap_resources("ac-1", [{"ap_name": "ap-a", "serial_number": "SN-001"}])
    ap_uuid = repository.list_fit_ap_resources("ac-1")[0]["ap_uuid"]
    repository.replace_fit_ap_optical("ac-1", [{"ap_uuid": ap_uuid, "ap_name": "ap-a", "site": "Optical Station"}])

    dialog = FitApDetailDialog(I18n("en_US"), repository, "ac-1", ap_uuid)

    assert dialog.site_input.text() == "Optical Station"


def test_ap_detail_dialog_uses_light_clear_style(tmp_path):
    app()
    repository = AcRepository(make_database(tmp_path))
    repository.replace_fit_ap_resources("ac-1", [{"ap_name": "ap-a", "serial_number": "SN-001"}])
    ap_uuid = repository.list_fit_ap_resources("ac-1")[0]["ap_uuid"]

    dialog = FitApDetailDialog(I18n("en_US"), repository, "ac-1", ap_uuid)

    assert "QComboBox" in dialog.styleSheet()
    assert "background: #ffffff" in dialog.styleSheet()
    assert dialog.raw_fields_table.item(0, 0).textAlignment() == Qt.AlignCenter


def test_legacy_ap_detail_import_aliases_fit_ap_detail():
    assert ApDetailDialog is FitApDetailDialog


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


def test_no_database_migration_code():
    root = Path(__file__).parents[1] / "netconsole"
    texts = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.py"))

    assert "ALTER TABLE" not in texts
    assert "schema_version" not in texts
    assert "upgrade_database" not in texts
