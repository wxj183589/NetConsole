from netconsole.core import app_logger
from netconsole.core.paths import PathResolver
from netconsole.services.command_guard import (
    CommandRejected,
    command_reject_reason,
    is_command_allowed,
    validate_command_list,
)


def test_command_guard_allows_whitelist_commands():
    for command in (
        "screen-length disable",
        "display current-configuration | include sysname",
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


def test_ground_unattended_syslog_read_context_is_fixed_and_read_only():
    validate_command_list(
        (
            "screen-length disable",
            "display version",
            "display info-center",
            "display current-configuration | include info-center",
            "display current-configuration",
        ),
        "ground_unattended_syslog_read",
    )
    assert not is_command_allowed("save force", "ground_unattended_syslog_read")
    assert not is_command_allowed("system-view", "ground_unattended_syslog_read")


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
    assert (
        command_reject_reason(
            "show running-config | include hostname",
            "device.inventory.collect",
        )
        == "pipe is not allowed for this command"
    )
    assert "dangerous command keyword matched" in str(
        command_reject_reason("show startup-config", "device.inventory.collect")
    )
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
    assert is_command_allowed("display interface brief", "optical_refresh")
    assert is_command_allowed("display transceiver diagnosis interface", "optical_refresh")
    assert not is_command_allowed("display version", "optical_refresh")
    for command in ("system-view", "undo lldp global enable", "shutdown", "reboot"):
        assert not is_command_allowed(command, "optical_refresh")


def test_trackside_switch_context_allows_only_fixed_read_only_vendor_commands():
    for command in (
        "screen-length disable",
        "display interface brief",
        "display transceiver diagnosis interface",
        "display lldp neighbor-information list",
        "show version",
        "show interface brief",
        "show running-config switchvlan",
        "show vlan",
        "show interface xgei-0/1/1/2",
        "show opticalinfo brief",
        "show opticalinfo gei-0/3/0/6",
        "show opticalinfo xgei-0/1/1/2",
        "show lldp neighbor brief",
        "show lldp entry",
    ):
        assert is_command_allowed(command, "trackside_switch_collect")

    for command in (
        "show lldp neighbor",
        "show lldp neighbors",
        "show lldp entry interface xgei-0/1/1/2",
        "show lldp neighbor interface xgei-0/1/1/2",
        "show lldp config",
        "show lldp config interface xgei-0/1/1/2",
        "terminal length 0",
        "configure terminal",
        "optical-inform monitor enable",
        "show running-config",
        "show interface xgei-0/1/1/2; reload",
        "show interface ../../etc/passwd",
        "shutdown",
        "write",
        "copy running-config startup-config",
        "reload",
    ):
        assert not is_command_allowed(command, "trackside_switch_collect")


def test_switch_vendor_sample_context_allows_only_profile_lldp_candidates():
    for command in (
        "show version",
        "show interface brief",
        "show running-config switchvlan",
        "show vlan",
        "show interface xgei-0/1/1/2",
        "show opticalinfo brief",
        "show opticalinfo xgei-0/1/1/2",
        "show lldp neighbor brief",
        "show lldp entry",
    ):
        assert is_command_allowed(command, "switch_vendor_sample_collect")

    for command in (
        "show lldp statistic interface xgei-0/1/1/2",
        "show lldp neighbor",
        "show lldp neighbors",
        "show lldp entry interface xgei-0/1/1/2",
        "show lldp neighbor interface xgei-0/1/1/2",
        "show lldp config",
        "show lldp config interface xgei-0/1/1/2",
        "show lldp entry interface xgei-0/1/1/2; reload",
        "configure terminal",
        "shutdown",
        "write",
        "reload",
    ):
        assert not is_command_allowed(command, "switch_vendor_sample_collect")


def test_zte_inventory_context_only_allows_exact_production_subset():
    for command in (
        "show version",
        "show interface brief",
        "show running-config switchvlan",
        "show vlan",
        "show opticalinfo brief",
        "show opticalinfo gei-0/3/0/6",
        "show lldp neighbor brief",
        "show lldp entry",
    ):
        assert is_command_allowed(command, "device.inventory.collect")

    for command in (
        "terminal length 0",
        "show running-config | include hostname",
        "show hardware",
        "show serial-number",
        "show interface",
        "show optical-inform brief",
        "show optical-inform detail",
        "show opticalinfo ../../etc/passwd",
        "show running-config",
        "show running-config interface gei-0/3/0/1",
        "show vlan 71",
        "show startup-config",
        "show system-info",
    ):
        assert not is_command_allowed(command, "device.inventory.collect")


def test_fit_ap_optical_collect_context_only_allows_ap_link_commands():
    for command in (
        "screen-length disable",
        "display lldp neighbor-information list",
        "display transceiver diagnosis interface",
    ):
        assert is_command_allowed(command, "fit_ap_optical_collect")

    for command in (
        "display interface brief",
        "display interface",
        "display version",
        "display wlan ap all lldp",
        "system-view",
        "shutdown",
    ):
        assert not is_command_allowed(command, "fit_ap_optical_collect")


def test_ac_enable_ap_console_allows_only_fixed_sequence_commands():
    for command in (
        "screen-length disable",
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


def test_ac_collect_contexts_are_split_by_purpose():
    for command in (
        "screen-length disable",
        "display wlan ap all",
        "display wlan ap all address",
        "display wlan ap all radio",
        "display wlan ap all radio verbose filter bbssid",
        "display wlan ap all connection-record",
        "display wlan ap all radio type",
        "display wlan ap unauthenticated",
        "display wlan ap all lldp",
    ):
        assert is_command_allowed(command, "ac_fit_ap_resource_collect")
        assert not is_command_allowed(command, "ac_info_collect") if command.startswith("display wlan") else True
    assert is_command_allowed("display wlan ap all radio verbose filter bbssid", "ac_fit_ap_resource_collect")
    assert is_command_allowed("display wlan ap all radio verbose filter bbssid", "ac_fit_ap_detail_collect")
    assert not is_command_allowed("display wlan ap unauthenticated", "ac_fit_ap_detail_collect")

    for command in (
        "screen-length disable",
        "display cpu-usage",
        "display memory",
        "display version",
        "display device",
        "display device manuinfo",
        "display ip https",
        "display ip https | include port",
    ):
        assert is_command_allowed(command, "ac_info_collect")
        assert not is_command_allowed(command, "ac_fit_ap_resource_collect") if command != "screen-length disable" else True

    for command in ("system-view", "wlan auto-ap persistent all", "probe", "wlan ap-execute all exec-console enable"):
        assert not is_command_allowed(command, "ac_fit_ap_resource_collect")
        assert not is_command_allowed(command, "ac_info_collect")


def test_ac_persist_auto_ap_context_allows_only_fixed_sequence_commands():
    for command in ("system-view", "wlan auto-ap persistent all", "save force", "return", "quit"):
        assert is_command_allowed(command, "ac_persist_auto_ap")

    for command in ("probe", "wlan ap-execute all exec-console enable", "display wlan ap all"):
        assert not is_command_allowed(command, "ac_persist_auto_ap")

    assert not is_command_allowed("save force", "ac_fit_ap_resource_collect")
    assert not is_command_allowed("save force", "ac_enable_ap_remote_login")


def test_command_guard_logs_rejected_command(tmp_path):
    app_logger.configure_path_resolver(PathResolver(tmp_path))

    try:
        validate_command_list(["save"], "device_collect")
    except CommandRejected:
        pass

    logs = app_logger.read_logs()
    assert logs[0]["event"] == "COMMAND_REJECTED"
    assert "save" in logs[0]["detail"]
