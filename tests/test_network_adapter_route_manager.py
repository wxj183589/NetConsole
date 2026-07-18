from __future__ import annotations

import inspect
import base64
import subprocess
import sys
from pathlib import Path

import pytest

from netconsole.core import admin as admin_module
from netconsole.core.paths import PathResolver
from netconsole.services.network_profile_store import AdapterMatch, AdapterProfile, NetworkProfileStore, SecondaryIp
from netconsole.services.route_profile_store import RouteProfile, RouteProfileEntry, RouteProfileStore
from netconsole.services import windows_network_manager as manager_module
from netconsole.services.windows_network_manager import (
    AdapterIpConfig,
    NetworkAdapterInfo,
    RouteConfig,
    SecondaryIpConfig,
    VlanProperty,
    WindowsNetworkManager,
    build_apply_ip_config_script,
    build_destination_prefix,
    build_new_route_script,
    build_remove_route_script,
    build_reset_adapter_defaults_script,
    build_set_vlan_script,
    detect_vlan_capability,
    detect_vlan_property,
    parse_prefix_or_netmask,
    recommend_physical_adapters,
)




SAFE_DEBUG_ADAPTER = "ASIX USB to Gigabit Ethernet Family Adapter"
FORBIDDEN_DEBUG_ADAPTER = "Realtek PCIe GbE Family Controller"


def _allow_real_write_debug(adapter_name: str) -> bool:
    if adapter_name == FORBIDDEN_DEBUG_ADAPTER:
        return False
    return adapter_name == SAFE_DEBUG_ADAPTER


def test_adapter_recommendation_excludes_virtual_wireless_and_prefers_pci_then_usb() -> None:
    adapters = [
        NetworkAdapterInfo(name="WireGuard Tunnel", description="WireGuard Tunnel", hardware_interface=False),
        NetworkAdapterInfo(name="Wi-Fi", description="Intel Wireless", hardware_interface=True),
        NetworkAdapterInfo(name="USB Ethernet", description="ASIX USB to Gigabit Ethernet", pnp_device_id="USB\\VID", status="Up"),
        NetworkAdapterInfo(name="Ethernet", description="Realtek PCIe GbE", pnp_device_id="PCI\\VEN", status="Up", ipv4_addresses=["192.168.1.2/24"]),
    ]
    recommended = recommend_physical_adapters(adapters)
    assert [item.name for item in recommended] == ["USB Ethernet", "Ethernet"]
    assert recommended[0].score > recommended[1].score


def test_vlan_property_detection_uses_driver_property_names() -> None:
    capability = detect_vlan_capability(
        [
            {"DisplayName": "Packet Priority & VLAN", "RegistryKeyword": "*PriorityVLANTag", "DisplayValue": "Disabled"},
            {"DisplayName": "Flow Control", "RegistryKeyword": "*FlowControl"},
        ]
    )
    assert capability.mode == "priority_vlan_enum"
    assert capability.vlan_id_property_name is None
    assert capability.priority_vlan_property_name == "Packet Priority & VLAN"
    assert detect_vlan_property([{"DisplayName": "Packet Priority & VLAN", "RegistryKeyword": "*PriorityVLANTag"}]) is None

    prop = detect_vlan_property([{"DisplayName": "VLAN ID", "RegistryKeyword": "*VlanID"}])
    assert prop is not None
    assert prop.display_name == "VLAN ID"
    assert prop.registry_keyword == "*VlanID"


def test_vlan_switch_values_are_not_treated_as_numeric_vlan_id() -> None:
    capability = detect_vlan_capability(
        [
            {
                "DisplayName": "VLAN标识",
                "RegistryKeyword": "VLAN_ID",
                "DisplayValue": "Packet Priority & VLAN Enable",
                "ValidDisplayValues": ["Packet Priority & VLAN Disable", "Packet Priority & VLAN Enable"],
            }
        ]
    )
    assert capability.supported is True
    assert capability.can_set_vlan_id is False
    assert capability.mode == "priority_vlan_enum"
    assert capability.vlan_switch_property == "VLAN标识"
    assert detect_vlan_property(
        [
            {
                "DisplayName": "VLAN标识",
                "RegistryKeyword": "VLAN_ID",
                "DisplayValue": "Packet Priority & VLAN Enable",
                "ValidDisplayValues": ["Packet Priority & VLAN Disable", "Packet Priority & VLAN Enable"],
            }
        ]
    ) is None


def test_ip_config_builders_generate_structured_powershell_without_ipv6_delete() -> None:
    script = build_apply_ip_config_script(
        AdapterIpConfig(
            interface_index=12,
            mode="static",
            ip_address="192.168.105.200",
            prefix_length=24,
            gateway="192.168.105.1",
            dns_servers=["8.8.8.8", "1.1.1.1"],
            secondary_ips=[SecondaryIpConfig("10.122.100.200", 24)],
        )
    )
    assert "Set-NetIPInterface -InterfaceIndex $ifIndex -AddressFamily IPv4 -Dhcp Disabled -ErrorAction Stop" in script
    assert "Where-Object { $_.PrefixOrigin -eq 'Manual' }" in script
    assert "New-NetIPAddress -InterfaceIndex $ifIndex -IPAddress '192.168.105.200' -PrefixLength 24 -DefaultGateway '192.168.105.1' -ErrorAction Stop" in script
    assert "New-NetIPAddress -InterfaceIndex $ifIndex -IPAddress '10.122.100.200' -PrefixLength 24 -ErrorAction Stop" in script
    assert "Set-DnsClientServerAddress" not in script
    assert "AddressFamily IPv6" not in script

    dhcp_script = build_apply_ip_config_script(AdapterIpConfig(interface_index=12, mode="dhcp"))
    assert "Set-NetIPInterface -InterfaceIndex $ifIndex -AddressFamily IPv4 -Dhcp Enabled -ErrorAction Stop" in dhcp_script
    assert "Remove-NetIPAddress -Confirm:$false" in dhcp_script
    assert "Where-Object { $_.PrefixOrigin -eq 'Manual' }" in dhcp_script
    assert dhcp_script.index("Remove-NetIPAddress") < dhcp_script.index("Set-NetIPInterface")
    assert "New-NetIPAddress" not in dhcp_script
    assert "Set-DnsClientServerAddress" not in dhcp_script


def test_vlan_and_reset_builders_validate_ranges_and_reset_to_zero() -> None:
    prop = VlanProperty("VLAN ID", "*VlanID")
    vlan_script = build_set_vlan_script("Ethernet", prop, 100)
    assert "$expectedDisplayName = 'VLAN ID'" in vlan_script
    assert "$expectedRegistryKeyword = '*VlanID'" in vlan_script
    assert "Set-NetAdapterAdvancedProperty -Name $adapterName -DisplayName $property.DisplayName -DisplayValue $targetValue" in vlan_script
    assert "Set-NetAdapterAdvancedProperty -Name $adapterName -RegistryKeyword $property.RegistryKeyword -RegistryValue $targetValue" in vlan_script
    assert "RegistryKeyword 'VLAN_ID'" not in vlan_script
    reset_script = build_reset_adapter_defaults_script(5, adapter_name="Ethernet", vlan_property=prop)
    assert reset_script.index("Remove-NetIPAddress") < reset_script.index("Set-NetIPInterface")
    assert "Where-Object { $_.PrefixOrigin -eq 'Manual' }" in reset_script
    assert "Set-DnsClientServerAddress" not in reset_script
    assert "Reset-NetAdapterAdvancedProperty" in reset_script
    with pytest.raises(ValueError):
        build_set_vlan_script("Ethernet", prop, 4095)
    with pytest.raises(ValueError):
        build_set_vlan_script("Ethernet", VlanProperty("Packet Priority & VLAN", "*PriorityVLANTag", mode="priority_vlan_enum"), 201)


@pytest.mark.parametrize("gateway", [None, "", "-", "None"])
def test_static_ip_builder_omits_empty_gateway_values(gateway) -> None:
    script = build_apply_ip_config_script(
        AdapterIpConfig(
            interface_index=12,
            mode="static",
            ip_address="192.168.105.200",
            prefix_length=24,
            gateway=gateway,
        )
    )
    assert "-DefaultGateway" not in script
    assert "None" not in script


def test_prefix_or_netmask_parser_accepts_prefix_and_contiguous_masks() -> None:
    assert parse_prefix_or_netmask("24") == 24
    assert parse_prefix_or_netmask("255.255.255.0") == 24
    assert parse_prefix_or_netmask("255.255.0.0") == 16
    assert parse_prefix_or_netmask("255.255.255.128") == 25
    for value in ("255.0.255.0", "255.255.255.1", "33", "abc"):
        with pytest.raises(ValueError):
            parse_prefix_or_netmask(value)


def test_route_command_builders_use_profile_route_parameters() -> None:
    route = RouteConfig("192.168.105.0/24", "192.168.105.1", "Ethernet", metric=10, persistent=True, interface_index=12)
    assert build_new_route_script(route) == "route.exe -p add 192.168.105.0 mask 255.255.255.0 192.168.105.1 metric 10 if 12"
    assert build_remove_route_script(route) == "route.exe delete 192.168.105.0 mask 255.255.255.0 192.168.105.1"
    assert "PolicyStore" not in build_new_route_script(route)
    assert build_new_route_script(RouteConfig("192.168.105.0/24", "192.168.105.1", "", metric=10, persistent=False)) == (
        "route.exe add 192.168.105.0 mask 255.255.255.0 192.168.105.1 metric 10"
    )


def test_destination_prefix_builder_accepts_destination_and_netmask() -> None:
    assert build_destination_prefix("192.168.105.0", "255.255.255.0") == "192.168.105.0/24"
    assert build_destination_prefix("192.168.105.0", "24") == "192.168.105.0/24"
    assert build_destination_prefix("192.168.105.0/24", "") == "192.168.105.0/24"
    with pytest.raises(ValueError):
        build_destination_prefix("192.168.105.0/24", "255.255.255.0")


def test_profile_stores_round_trip_and_reset_does_not_delete_profiles(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    network_store = NetworkProfileStore(paths.network_profiles_path)
    route_store = RouteProfileStore(paths.route_profiles_path)
    network_store.upsert(
        AdapterProfile(
            profile_name="MR-105",
            adapter_match=AdapterMatch(name="Ethernet", mac="aa-bb", description_keyword="PCIe"),
            mode="static",
            ip_address="192.168.105.200",
            secondary_ips=[SecondaryIp("10.122.100.200", 24)],
            vlan_id=105,
        )
    )
    route_store.upsert(
        RouteProfile(
            profile_name="MR-route",
            routes=[RouteProfileEntry("192.168.105.0/24", "192.168.105.1", "Ethernet")],
        )
    )

    assert network_store.load()[0].secondary_ips[0].ip_address == "10.122.100.200"
    assert route_store.load()[0].routes[0].destination_prefix == "192.168.105.0/24"
    build_reset_adapter_defaults_script(3)
    assert paths.network_profiles_path.exists()
    assert network_store.load()[0].profile_name == "MR-105"


def test_manager_write_requires_admin_and_uses_runner(monkeypatch) -> None:
    calls: list[list[str]] = []

    def runner(args):
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(manager_module, "is_admin", lambda: False)
    service = WindowsNetworkManager(runner=runner)
    with pytest.raises(PermissionError):
        service.apply_route(RouteConfig("10.0.0.0/24", "10.0.0.1", "Ethernet"))
    assert calls == []

    monkeypatch.setattr(manager_module, "is_admin", lambda: True)
    service.apply_route(RouteConfig("10.0.0.0/24", "10.0.0.1", "Ethernet"))
    decoded = base64.b64decode(calls[0][-1]).decode("utf-16le")
    assert "route.exe" in decoded
    assert "New-NetRoute" not in decoded


def test_is_admin_returns_bool_without_requiring_real_admin() -> None:
    assert isinstance(admin_module.is_admin(), bool)


def test_shell_execute_failure_returns_user_facing_message(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(admin_module.sys, "platform", "win32")
    monkeypatch.setattr(admin_module.sys, "executable", sys.executable)
    monkeypatch.setattr(admin_module.sys, "frozen", False, raising=False)

    result = admin_module.open_network_manager_as_admin(app_root=tmp_path, shell_execute=lambda *args: 5)
    assert result.success is False
    assert result.code == 5
    assert "拒绝" in result.message or "取消" in result.message


def test_powershell_uses_encoded_command_and_complete_json_blocks() -> None:
    args = manager_module._powershell_args(manager_module._list_adapters_script())
    assert "-NoLogo" in args
    assert "-NoProfile" in args
    assert "-NonInteractive" in args
    assert "-ExecutionPolicy" in args
    assert "Bypass" in args
    assert "-EncodedCommand" in args
    assert "-Command" not in args
    decoded = base64.b64decode(args[-1]).decode("utf-16le")
    assert "$ProgressPreference = 'SilentlyContinue'" in decoded
    assert "$InformationPreference = 'SilentlyContinue'" in decoded
    assert "$WarningPreference = 'Continue'" in decoded
    adapter_script = manager_module._list_adapters_script().lstrip()
    route_script = manager_module._list_routes_script().lstrip()
    assert not adapter_script.startswith("|")
    assert not route_script.startswith("|")
    assert "@($items) | ConvertTo-Json -Depth 6" in adapter_script
    assert "@($items) | ConvertTo-Json -Depth 6" in route_script


def test_clixml_progress_stderr_does_not_fail_successful_powershell() -> None:
    stderr = '#< CLIXML\r\n<Objs><Obj S="progress"><T>Completed</T></Obj></Objs>'
    service = WindowsNetworkManager(runner=lambda args: subprocess.CompletedProcess(args, 0, "[]", stderr))
    assert service._run_json(manager_module._list_adapters_script()) == []
    assert manager_module.is_only_powershell_progress_clixml(stderr) is True
    assert manager_module.clean_powershell_error_output(stderr) == ""


def test_clixml_error_output_is_summarized_without_full_xml() -> None:
    stderr = (
        '#< CLIXML\r\n<Objs><S S="Error">Set-NetIPInterface failed</S>'
        '<S>CategoryInfo : PermissionDenied</S><S>FullyQualifiedErrorId : AccessDenied</S></Objs>'
    )
    service = WindowsNetworkManager(runner=lambda args: subprocess.CompletedProcess(args, 1, "", stderr))
    with pytest.raises(manager_module.NetworkManagerError) as exc:
        service._run_script(manager_module._list_adapters_script())
    message = str(exc.value)
    assert "Set-NetIPInterface failed" in message
    assert "CategoryInfo" in message
    assert "<Objs>" not in message


def test_hidden_subprocess_kwargs_use_no_window_on_windows(monkeypatch) -> None:
    monkeypatch.setattr(manager_module.sys, "platform", "win32")
    kwargs = manager_module._hidden_subprocess_kwargs()
    assert kwargs["creationflags"] == subprocess.CREATE_NO_WINDOW
    assert kwargs["startupinfo"].dwFlags & subprocess.STARTF_USESHOWWINDOW
    assert kwargs["startupinfo"].wShowWindow == subprocess.SW_HIDE


def test_powershell_empty_and_single_object_json_results(monkeypatch) -> None:
    service = WindowsNetworkManager(runner=lambda args: subprocess.CompletedProcess(args, 0, "", ""))
    assert service._run_json(manager_module._list_adapters_script()) == []

    single = '{"Name":"Ethernet","InterfaceIndex":12,"HardwareInterface":true}'
    service = WindowsNetworkManager(runner=lambda args: subprocess.CompletedProcess(args, 0, single, ""))
    rows = service._run_json(manager_module._list_adapters_script())
    assert manager_module._ensure_list(rows)[0]["Name"] == "Ethernet"


def test_route_print_parser_assigns_stable_order_indexes() -> None:
    rows = manager_module._parse_route_print(
        """
IPv4 Route Table
===========================================================================
Active Routes:
Network Destination        Netmask          Gateway       Interface  Metric
          0.0.0.0          0.0.0.0       10.0.0.1        10.0.0.2     25
       10.122.0.0      255.255.0.0         On-link      10.122.0.2    281
===========================================================================
"""
    )

    assert [row.order_index for row in rows] == [0, 1]
    assert [row.destination_prefix for row in rows] == ["0.0.0.0/0", "10.122.0.0/16"]


























def test_debug_real_write_guard_allows_only_asix_and_never_realtek() -> None:
    assert _allow_real_write_debug(SAFE_DEBUG_ADAPTER) is True
    assert _allow_real_write_debug(FORBIDDEN_DEBUG_ADAPTER) is False
    assert _allow_real_write_debug("Other Ethernet") is False


def test_production_network_manager_has_no_debug_adapter_hardcoding() -> None:
    source = inspect.getsource(manager_module)
    assert SAFE_DEBUG_ADAPTER not in source
    assert FORBIDDEN_DEBUG_ADAPTER not in source
