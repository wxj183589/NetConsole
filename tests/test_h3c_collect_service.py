from pathlib import Path

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.services import h3c_collect_service
from netconsole.services import h3c_optical_refresh_service
from netconsole.services.device_command_profile_service import default_device_inventory_profile
from netconsole.services.h3c_collect_service import collect_h3c_device_details
from netconsole.services.h3c_optical_refresh_service import OPTICAL_REFRESH_COMMANDS, refresh_h3c_device_optical


FIXTURES = Path(__file__).parent / "fixtures" / "h3c"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
COLLECT_COMMANDS = default_device_inventory_profile().commands[1:]


def make_paths(tmp_path: Path) -> PathResolver:
    return PathResolver(app_root=PROJECT_ROOT, data_root=tmp_path)


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


OUTPUTS = {
    "screen-length disable": "",
    "display current-configuration | include sysname": fixture("display_current_configuration_sysname.txt"),
    "display version": fixture("display_version.txt"),
    "display device": fixture("display_device.txt"),
    "display device manuinfo": fixture("display_device_manuinfo.txt"),
    "display boot-loader": fixture("display_boot_loader_sw.txt"),
    "display interface": fixture("display_interface.txt"),
    "display transceiver interface": fixture("display_transceiver_interface.txt"),
    "display transceiver manuinfo interface": """
GigabitEthernet1/0/1 transceiver manufacture information:
  Manu. Serial Number : OPT-MANU-0001
  Manufacturing Date  : 2025-03-23
  Vendor Name         : H3C
""",
    "display transceiver diagnosis interface": fixture("display_transceiver_diagnosis_interface.txt"),
    "display lldp neighbor-information list": fixture("display_lldp_neighbor_information_list.txt"),
    "display lldp neighbor-information verbose": fixture("display_lldp_neighbor_information_verbose.txt"),
}


class FakeConnection:
    def __init__(self, fail_commands=None):
        self.fail_commands = set(fail_commands or [])
        self.commands = []
        self.disconnected = False

    def send_command(self, command, read_timeout=None):
        self.commands.append(command)
        if command in self.fail_commands:
            raise RuntimeError(f"{command} failed")
        return OUTPUTS[command]

    def disconnect(self):
        self.disconnected = True


def make_repository(tmp_path):
    database = Database(tmp_path / "data" / "sites" / "demo" / "db" / "devices.db")
    database.initialize()
    return DeviceFactRepository(database)


def make_device():
    return Device(
        device_uuid="11111111-1111-4111-8111-111111111111",
        name="SW01",
        ip_address="10.0.0.52",
        ssh_enabled=1,
        ssh_username="admin",
        ssh_password="Admin@123",
    )


def test_collect_service_skips_raw_log_by_default_and_writes_repository_data(monkeypatch, tmp_path):
    connection = FakeConnection()
    monkeypatch.setattr(h3c_collect_service.netmiko_connection, "ConnectHandler", lambda **_kwargs: connection)
    repository = make_repository(tmp_path)

    result = collect_h3c_device_details(make_device(), "demo", repository=repository, paths=make_paths(tmp_path))

    assert result.success is True
    assert result.facts_updated is True
    assert result.interfaces_updated == 2
    assert result.optical_modules_updated == 1
    assert result.lldp_neighbors_updated == 1
    assert connection.commands == ["screen-length disable", *COLLECT_COMMANDS]
    assert connection.disconnected is True
    assert result.raw_log_path == ""
    assert not (tmp_path / "data" / "sites" / "demo" / "raw" / "collect" / result.collect_run_uuid).exists()
    assert repository.get_collect_run(result.collect_run_uuid)["status"] == "success"
    fact = repository.get_device_fact("11111111-1111-4111-8111-111111111111")
    assert fact["sysname"] == "SW01"
    assert fact["model"] == "S6850"
    assert fact["mac_address"] == "105e-ae3e-0700"
    assert "当前:" in fact["bootrom_version"]
    assert "主用:" in fact["bootrom_version"]
    assert "备用:" in fact["bootrom_version"]
    assert repository.list_device_interfaces("11111111-1111-4111-8111-111111111111")[0]["interface_name"] == "GigabitEthernet1/0/1"
    optical = repository.list_optical_modules("11111111-1111-4111-8111-111111111111")[0]
    assert optical["rx_power"] == "-3.21 dBm"
    assert optical["module_serial_number"] == "OPT-MANU-0001"
    assert repository.list_lldp_neighbors("11111111-1111-4111-8111-111111111111")[0]["neighbor_sysname"] == "AC-DEMO"
    assert len(repository.list_fact_history("11111111-1111-4111-8111-111111111111")) == 1
    assert len(repository.list_interface_history("11111111-1111-4111-8111-111111111111", "GigabitEthernet1/0/1")) == 1
    assert len(repository.list_optical_history("11111111-1111-4111-8111-111111111111", "GigabitEthernet1/0/1")) == 1
    assert len(repository.list_lldp_history("11111111-1111-4111-8111-111111111111", "GigabitEthernet1/0/1")) == 1


def test_collect_service_persists_explicitly_absent_transceiver(monkeypatch, tmp_path):
    monkeypatch.setitem(
        OUTPUTS,
        "display transceiver diagnosis interface",
        fixture("display_transceiver_diagnosis_interface.txt")
        + """

GigabitEthernet1/0/2 transceiver diagnostic information:
The transceiver is absent.
""",
    )
    connection = FakeConnection()
    monkeypatch.setattr(
        h3c_collect_service.netmiko_connection,
        "ConnectHandler",
        lambda **_kwargs: connection,
    )
    repository = make_repository(tmp_path)

    result = collect_h3c_device_details(
        make_device(), "demo", repository=repository, paths=make_paths(tmp_path)
    )

    assert result.success is True
    by_name = {
        item["interface_name"]: item
        for item in repository.list_optical_modules(str(make_device().device_uuid))
    }
    assert by_name["GigabitEthernet1/0/2"]["status"] == "no_module"


def test_collect_service_writes_sysname_back_to_device_table(monkeypatch, tmp_path):
    connection = FakeConnection()
    monkeypatch.setattr(h3c_collect_service.netmiko_connection, "ConnectHandler", lambda **_kwargs: connection)
    database = Database(tmp_path / "data" / "sites" / "demo" / "db" / "devices.db")
    database.initialize()
    device_repository = DeviceRepository(database)
    device = device_repository.create(make_device())
    repository = DeviceFactRepository(database)

    result = collect_h3c_device_details(device, "demo", repository=repository, paths=make_paths(tmp_path))

    assert result.success is True
    assert device_repository.get(device.id).sysname == "SW01"
    assert device_repository.get(device.id).mac_address == "105e-ae3e-0700"


def test_collect_service_persists_raw_log_when_debug_enabled(monkeypatch, tmp_path):
    connection = FakeConnection()
    monkeypatch.setenv("NETCONSOLE_PERSIST_RAW_LOGS", "1")
    monkeypatch.setattr(h3c_collect_service.netmiko_connection, "ConnectHandler", lambda **_kwargs: connection)
    repository = make_repository(tmp_path)

    result = collect_h3c_device_details(make_device(), "demo", repository=repository, paths=make_paths(tmp_path))

    assert result.raw_log_path
    raw_path = tmp_path / "data" / "sites" / "demo" / result.raw_log_path
    assert raw_path.exists()
    assert raw_path.with_name("11111111-1111-4111-8111-111111111111_commands.jsonl").exists()


def test_collect_service_continues_when_one_command_fails(monkeypatch, tmp_path):
    connection = FakeConnection(fail_commands={"display transceiver interface"})
    monkeypatch.setattr(h3c_collect_service.netmiko_connection, "ConnectHandler", lambda **_kwargs: connection)
    repository = make_repository(tmp_path)

    result = collect_h3c_device_details(make_device(), "demo", repository=repository, paths=make_paths(tmp_path))

    assert result.success is True
    assert "display lldp neighbor-information verbose" in connection.commands
    assert repository.get_collect_run(result.collect_run_uuid)["status"] == "partial_success"
    assert any(item.command == "display transceiver interface" and not item.success for item in result.command_results)


def test_collect_service_marks_h3c_cli_error_output_as_partial(monkeypatch, tmp_path):
    connection = FakeConnection()
    monkeypatch.setitem(
        OUTPUTS,
        "display boot-loader",
        "% Unrecognized command found at '^' position.",
    )
    monkeypatch.setattr(
        h3c_collect_service.netmiko_connection,
        "ConnectHandler",
        lambda **_kwargs: connection,
    )
    repository = make_repository(tmp_path)

    result = collect_h3c_device_details(
        make_device(),
        "demo",
        repository=repository,
        paths=make_paths(tmp_path),
    )

    boot_loader = next(
        item for item in result.command_results if item.command == "display boot-loader"
    )
    assert result.success is True
    assert boot_loader.success is False
    assert "% Unrecognized command" in str(boot_loader.error_message)
    assert repository.get_collect_run(result.collect_run_uuid)["status"] == "partial_success"


def test_collect_service_does_not_connect_when_no_protocol_enabled(tmp_path):
    repository = make_repository(tmp_path)
    device = make_device()
    device.ssh_enabled = 0
    device.telnet_enabled = 0
    progress = []

    result = collect_h3c_device_details(
        device,
        "demo",
        repository=repository,
        paths=make_paths(tmp_path),
        progress_callback=lambda percent, stage, command="", message="": progress.append((percent, stage, command, message)),
    )

    assert result.success is False
    assert result.error_message == "未启用连接方式"
    assert repository.get_collect_run(result.collect_run_uuid)["status"] == "failed"
    assert progress[-1] == (100, "batch_collect.stage.failed", "", "未启用连接方式")


def test_update_collect_run_status(tmp_path):
    repository = make_repository(tmp_path)
    run = repository.create_collect_run({"collect_type": "device_details", "status": "running"})

    updated = repository.update_collect_run_status(run["collect_run_uuid"], "success", error_message="")

    assert updated["status"] == "success"
    assert updated["ended_at"]


def test_collect_service_validates_commands_before_execution(monkeypatch, tmp_path):
    calls = []
    connection = FakeConnection()
    monkeypatch.setattr(h3c_collect_service.netmiko_connection, "ConnectHandler", lambda **_kwargs: connection)
    monkeypatch.setattr(
        h3c_collect_service.command_guard,
        "validate_operation_commands",
        lambda commands, *, context, operation_id: calls.append((list(commands), context, operation_id)),
    )
    repository = make_repository(tmp_path)

    collect_h3c_device_details(make_device(), "demo", repository=repository, paths=make_paths(tmp_path))

    assert calls == [
        (["screen-length disable", *COLLECT_COMMANDS], "device_collect", "device.inventory.collect")
    ]


def test_collect_service_rejects_non_h3c_before_connection(monkeypatch, tmp_path):
    def unexpected_connect(**_kwargs):
        raise AssertionError("unsupported vendor must not connect")

    monkeypatch.setattr(
        h3c_collect_service.netmiko_connection,
        "ConnectHandler",
        unexpected_connect,
    )
    repository = make_repository(tmp_path)
    device = make_device()
    device.device_vendor = "Huawei"

    result = collect_h3c_device_details(
        device,
        "demo",
        repository=repository,
        paths=make_paths(tmp_path),
    )

    assert result.success is False
    assert "仅支持 H3C" in str(result.error_message)
    assert result.command_results == []
    assert repository.get_collect_run(result.collect_run_uuid)["status"] == "failed"


def test_profile_rejection_writes_declared_raw_failure_artifact(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("NETCONSOLE_PERSIST_RAW_LOGS", "1")
    repository = make_repository(tmp_path)
    device = make_device()
    device.device_vendor = "Huawei"

    result = collect_h3c_device_details(
        device,
        "demo",
        repository=repository,
        paths=make_paths(tmp_path),
    )

    assert result.success is False
    assert Path(result.raw_log_path).is_file()
    assert "FATAL ERROR" in Path(result.raw_log_path).read_text(encoding="utf-8")


def test_collect_service_reports_connection_command_parse_and_write_progress(monkeypatch, tmp_path):
    connection = FakeConnection()
    monkeypatch.setattr(h3c_collect_service.netmiko_connection, "ConnectHandler", lambda **_kwargs: connection)
    repository = make_repository(tmp_path)
    progress = []

    result = collect_h3c_device_details(
        make_device(),
        "demo",
        repository=repository,
        paths=make_paths(tmp_path),
        progress_callback=lambda percent, stage, command="", message="": progress.append((percent, stage, command, message)),
    )

    assert result.success is True
    assert (5, "batch_collect.stage.connecting", "", "") in progress
    assert (10, "batch_collect.stage.login_success", "", "") in progress
    assert (15, "batch_collect.stage.init_terminal", "screen-length disable", "") in progress
    command_updates = [item for item in progress if item[1].startswith("batch_collect.stage.collecting_command")]
    assert len(command_updates) == len(COLLECT_COMMANDS)
    assert command_updates[-1][0] == 80
    assert command_updates[-1][2] == COLLECT_COMMANDS[-1]
    assert any(item[1] == "batch_collect.stage.parsing" and item[0] == 85 for item in progress)
    assert any(item[1] == "batch_collect.stage.saving" and item[0] == 95 for item in progress)
    assert progress[-1][0:2] == (100, "batch_collect.stage.completed")


def test_optical_refresh_service_runs_three_commands_and_writes_interfaces_optical(monkeypatch, tmp_path):
    connection = FakeConnection()
    monkeypatch.setattr(h3c_optical_refresh_service.netmiko_connection, "ConnectHandler", lambda **_kwargs: connection)
    repository = make_repository(tmp_path)
    device = make_device()
    repository.upsert_device_fact(
        {
            "device_uuid": device.device_uuid,
            "sysname": "SW01",
            "model": "S6850",
            "collected_at": "2026-06-16T00:00:00",
            "updated_at": "2026-06-16T00:00:00",
            "raw_log_path": "files/config_center/raw_logs/collect/old/device.log",
        }
    )
    repository.replace_optical_modules(
        str(device.device_uuid),
        [
            {
                "interface_name": "GigabitEthernet1/0/1",
                "module_model": "SFP-GE-LX-SM1310",
                "module_serial_number": "KEEP-SN-001",
                "module_vendor": "H3C",
                "wavelength": "1310 nm",
                "transmission_distance": "10 km",
                "collected_at": "2026-06-16T00:00:00",
            }
        ],
    )

    result = refresh_h3c_device_optical(device, "demo", repository=repository, paths=PathResolver(tmp_path))

    assert result.success is True
    assert connection.commands == list(OPTICAL_REFRESH_COMMANDS)
    assert connection.disconnected is True
    assert result.raw_log_path == ""
    assert result.interfaces_updated == 2
    assert result.optical_modules_updated == 1
    assert repository.list_device_interfaces(str(device.device_uuid))[0]["interface_name"] == "GigabitEthernet1/0/1"
    optical = repository.list_optical_modules(str(device.device_uuid))[0]
    assert optical["rx_power"] == "-3.21 dBm"
    assert optical["module_serial_number"] == "KEEP-SN-001"
    assert optical["module_model"] == "SFP-GE-LX-SM1310"
    assert repository.get_latest_raw_log_path(str(device.device_uuid)) is None


def test_optical_refresh_clears_stale_module_identity_when_module_is_absent():
    merged = h3c_optical_refresh_service.merge_existing_optical_modules(
        [
            {
                "interface_name": "GigabitEthernet2/0/3",
                "module_model": "SFP-GE-LX-SM1310",
                "module_serial_number": "STALE-SN",
            }
        ],
        [
            {
                "interface_name": "GigabitEthernet2/0/3",
                "status": "success",
                "optical_alarm_status": "no_module",
            }
        ],
        [],
        {"collected_at": "2026-07-19T00:00:00"},
    )

    assert merged == [
        {
            "interface_name": "GigabitEthernet2/0/3",
            "status": "no_module",
            "optical_alarm_status": "no_module",
            "collected_at": "2026-07-19T00:00:00",
        }
    ]


def test_optical_refresh_service_validates_optical_context(monkeypatch, tmp_path):
    calls = []
    connection = FakeConnection()
    monkeypatch.setattr(h3c_optical_refresh_service.netmiko_connection, "ConnectHandler", lambda **_kwargs: connection)
    monkeypatch.setattr(h3c_optical_refresh_service.command_guard, "validate_command_list", lambda commands, context: calls.append((list(commands), context)))
    repository = make_repository(tmp_path)

    refresh_h3c_device_optical(make_device(), "demo", repository=repository, paths=PathResolver(tmp_path))

    assert calls == [(list(OPTICAL_REFRESH_COMMANDS), "optical_refresh")]
