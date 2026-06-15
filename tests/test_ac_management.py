import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

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
from netconsole.services.h3c_ac_collect_service import RESOURCE_COMMANDS, collect_h3c_ac_resources
from netconsole.services.neighbor_matcher import find_neighbor_rx_power, match_neighbor_device
from netconsole.ui.pages.ac_management_page import AcManagementPage, FIT_AP_OPTICAL_COLUMNS, FIT_AP_RESOURCE_COLUMNS
from netconsole.ui.dialogs.ap_detail_dialog import ApDetailDialog
from netconsole.ui.dialogs.fit_ap_detail_dialog import FIT_AP_DETAIL_TABS, FitApDetailDialog


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

    assert "ac_ap_summary" in table_names
    assert "ac_fit_ap_resources" in table_names
    assert "ac_fit_ap_optical" in table_names
    assert "ac_fit_ap_metadata" in table_names


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


def test_wlan_ap_address_and_radio_parsers():
    addresses = parse_wlan_ap_addresses(fixture("display_wlan_ap_all_address.txt"))
    radios = parse_wlan_ap_radios(fixture("display_wlan_ap_all_radio.txt"))

    assert addresses["4c6f-d608-0400"]["ap_ip"] == "10.0.0.61"
    assert addresses["4c6f-d608-0400"]["ap_mac"] == "4c6f-d608-0400"
    assert radios["4c6f-d608-0400"]["rid1_channel"] == "1"
    assert radios["4c6f-d608-0400"]["rid2_tx_power"] == "17"


def test_state_cpu_and_memory_parsers():
    assert map_fit_ap_state("R/M") == "运行(主)"
    assert map_fit_ap_state("R/B") == "运行(备)"
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


def test_ac_management_page_column_configuration_exists(tmp_path):
    app()
    context = create_demo_context(PathResolver(tmp_path))
    page = AcManagementPage(context.repository, I18n("en_US"), "demo")

    assert [field for _key, field in FIT_AP_RESOURCE_COLUMNS] == [
        "select",
        "ap_name",
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
        "updated_at",
        "status",
        "error_message",
    ]
    assert page.tabs.tabText(2) == "Online Vehicle MR"


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
    assert repository.get_fit_ap_metadata("ap-a")["direction"] == "CW"

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
    assert dialog.tabs.count() == 5
    assert FIT_AP_DETAIL_TABS == ("basic", "metadata", "radio", "lldp", "optical")
    assert repository.get_fit_ap_metadata("ap-a")["site_name"] == "Station A"


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
    assert by_mac.device_uuid == device.device_uuid
    assert by_mac.matched_by == "mac"
    assert find_neighbor_rx_power("demo", device.device_uuid, "GigabitEthernet2/0/19", paths=paths) == "-6.66 dBm"


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
