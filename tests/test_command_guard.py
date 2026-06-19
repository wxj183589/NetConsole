from netconsole.core import app_logger
from netconsole.core.paths import PathResolver
from netconsole.services.command_guard import CommandRejected, is_command_allowed, validate_command_list


def test_command_guard_allows_whitelist_commands():
    for command in (
        "screen-length disable",
        "display current-configuration | in sysname",
        "display version",
        "display device",
        "display device manuinfo",
        "display boot-loader",
        "display interface",
        "display transceiver interface",
        "display transceiver manuinfo interface",
        "display transceiver diagnosis interface",
        "display lldp neighbor-information list",
        "display lldp neighbor-information verbose",
    ):
        assert is_command_allowed(command, "device_collect")


def test_command_guard_rejects_dangerous_commands():
    for command in (
        "save",
        "reboot",
        "reset",
        "delete flash:/startup.cfg",
        "undo lldp global enable",
        "shutdown",
        "no shutdown",
        "format flash:",
        "erase startup-config",
        "copy startup.cfg backup.cfg",
        "move a b",
        "rename a b",
        "restore factory-default",
        "install package",
        "upgrade system",
        "startup saved-configuration",
        "license activation-file install x",
        "patch install x",
        "local-user admin",
        "password cipher x",
        "acl number 3000",
        "vlan 10",
        "interface GigabitEthernet1/0/1",
        "ip route-static 0.0.0.0 0 10.0.0.1",
    ):
        assert not is_command_allowed(command, "device_collect")


def test_command_guard_rejects_semicolon_and_non_whitelist_pipe():
    assert not is_command_allowed("display version ; reboot", "device_collect")
    assert not is_command_allowed("display version | include H3C", "device_collect")
    assert is_command_allowed("display ip https | include port", "ac_collect")
    assert is_command_allowed("display ip https", "ac_collect")
    assert not is_command_allowed("display ip https | include port", "device_collect")


def test_command_guard_allows_display_boot_loader_but_rejects_config_boot_loader():
    assert is_command_allowed("display boot-loader", "device_collect")
    assert not is_command_allowed("boot-loader file flash:/bad.bin slot 1 main", "device_collect")
    assert not is_command_allowed("boot-loader update all", "device_collect")


def test_optical_refresh_context_only_allows_optical_refresh_commands():
    assert is_command_allowed("screen-length disable", "optical_refresh")
    assert is_command_allowed("display interface", "optical_refresh")
    assert is_command_allowed("display transceiver diagnosis interface", "optical_refresh")
    assert not is_command_allowed("display version", "optical_refresh")
    for command in ("system-view", "undo lldp global enable", "shutdown", "reboot"):
        assert not is_command_allowed(command, "optical_refresh")


def test_ac_enable_ap_console_allows_only_fixed_sequence_commands():
    for command in (
        "screen-length disable",
        "display wlan ap all address",
        "system-view",
        "probe",
        "wlan ap-execute all exec-console enable",
        "return",
        "quit",
    ):
        assert is_command_allowed(command, "ac_enable_ap_console")

    for context in ("device_collect", "ac_collect", "fit_ap_collect", "optical_refresh"):
        assert not is_command_allowed("system-view", context)
        assert not is_command_allowed("probe", context)

    for command in ("undo lldp global enable", "shutdown", "reboot", "save"):
        assert not is_command_allowed(command, "ac_enable_ap_console")


def test_command_guard_logs_rejected_command(tmp_path):
    app_logger.configure_path_resolver(PathResolver(tmp_path))

    try:
        validate_command_list(["save"], "device_collect")
    except CommandRejected:
        pass

    logs = app_logger.read_logs()
    assert logs[0]["event"] == "COMMAND_REJECTED"
    assert "save" in logs[0]["detail"]
