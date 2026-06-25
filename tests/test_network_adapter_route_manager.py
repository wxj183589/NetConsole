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
    VlanCapability,
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


def test_development_admin_launch_uses_python_and_absolute_main(monkeypatch, tmp_path: Path) -> None:
    calls = []
    main_py = tmp_path / "main.py"
    main_py.write_text("from netconsole.app import run\n", encoding="utf-8")
    python_exe = tmp_path / ".venv" / "Scripts" / "python.exe"
    python_exe.parent.mkdir(parents=True)
    python_exe.write_text("", encoding="utf-8")
    pythonw_exe = python_exe.with_name("pythonw.exe")
    pythonw_exe.write_text("", encoding="utf-8")

    def shell_execute(hwnd, verb, file, parameters, working_dir, show):
        calls.append((hwnd, verb, file, parameters, working_dir, show))
        return 33

    monkeypatch.setattr(admin_module.sys, "platform", "win32")
    monkeypatch.setattr(admin_module.sys, "executable", str(python_exe))
    monkeypatch.setattr(admin_module.sys, "frozen", False, raising=False)

    result = admin_module.open_network_manager_as_admin(app_root=tmp_path, shell_execute=shell_execute)
    assert result.success is True
    assert calls[0][1] == "runas"
    assert calls[0][2] == str(pythonw_exe.resolve())
    assert calls[0][3] == f'"{main_py.resolve()}" --admin-network-manager'
    assert calls[0][4] == str(tmp_path.resolve())


def test_development_admin_launch_falls_back_to_python_when_pythonw_missing(monkeypatch, tmp_path: Path) -> None:
    main_py = tmp_path / "main.py"
    main_py.write_text("from netconsole.app import run\n", encoding="utf-8")
    python_exe = tmp_path / ".venv" / "Scripts" / "python.exe"
    python_exe.parent.mkdir(parents=True)
    python_exe.write_text("", encoding="utf-8")

    monkeypatch.setattr(admin_module.sys, "platform", "win32")
    monkeypatch.setattr(admin_module.sys, "executable", str(python_exe))
    monkeypatch.setattr(admin_module.sys, "frozen", False, raising=False)

    plan = admin_module.build_network_manager_admin_launch_plan(app_root=tmp_path)
    assert plan.executable == str(python_exe.resolve())
    assert plan.parameters == f'"{main_py.resolve()}" --admin-network-manager'


def test_frozen_admin_launch_uses_exe_and_admin_argument(monkeypatch, tmp_path: Path) -> None:
    calls = []
    exe = tmp_path / "NetConsole.exe"
    exe.write_text("", encoding="utf-8")

    def shell_execute(hwnd, verb, file, parameters, working_dir, show):
        calls.append((hwnd, verb, file, parameters, working_dir, show))
        return 33

    monkeypatch.setattr(admin_module.sys, "platform", "win32")
    monkeypatch.setattr(admin_module.sys, "executable", str(exe))
    monkeypatch.setattr(admin_module.sys, "frozen", True, raising=False)

    result = admin_module.open_network_manager_as_admin(shell_execute=shell_execute)
    assert result.success is True
    assert calls[0][1] == "runas"
    assert calls[0][2] == str(exe.resolve())
    assert calls[0][3] == "--admin-network-manager"
    assert calls[0][4] == str(tmp_path.resolve())


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


def test_admin_network_manager_arg_switches_to_network_manager_tab() -> None:
    from netconsole.app import open_admin_network_manager

    class FakeNavigation:
        current_row = None

        def find_page(self, page_id):
            assert page_id == "network_tools"
            return 6

        def setCurrentRow(self, row):
            self.current_row = row

    class FakeStack:
        current = None

        def setCurrentWidget(self, page):
            self.current = page

    class FakeTabs:
        current_index = None

        def count(self):
            return 3

        def setCurrentIndex(self, index):
            self.current_index = index

    class FakeWindow:
        def __init__(self):
            self.navigation = FakeNavigation()
            self.stack = FakeStack()
            self.page = type("FakePage", (), {"tabs": FakeTabs()})()

        def get_or_create_page(self, page_id):
            assert page_id == "network_tools"
            return self.page

    window = FakeWindow()
    open_admin_network_manager(window)
    assert window.navigation.current_row == 6
    assert window.stack.current is window.page
    assert window.page.tabs.current_index == 2


def test_admin_launch_success_updates_log_without_success_modal(monkeypatch, tmp_path: Path) -> None:
    import os
    from PySide6.QtWidgets import QApplication, QMessageBox
    from netconsole.core.admin import AdminLaunchResult
    from netconsole.core.i18n import I18n
    from netconsole.ui.pages import network_adapter_route_page as page_module

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    assert app is not None

    monkeypatch.setattr(page_module, "is_admin", lambda: False)
    monkeypatch.setattr(
        page_module,
        "open_network_manager_as_admin",
        lambda **kwargs: AdminLaunchResult(True, 33, "已请求管理员权限，请在弹出的 UAC 窗口中确认。"),
    )
    info_calls = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: info_calls.append(args))

    page = page_module.NetworkAdapterRoutePage(I18n("en_US"), PathResolver(tmp_path))
    page.request_admin_network_manager()
    assert info_calls == []
    assert page.admin_launch_pending is True
    assert page.admin_button.isEnabled() is False
    assert "关闭" in page.log_text.toPlainText()


def test_admin_launch_success_quits_normal_app_without_close_confirm(monkeypatch, tmp_path: Path) -> None:
    import os
    from PySide6.QtWidgets import QApplication, QHeaderView, QSplitter
    from netconsole.core.admin import AdminLaunchResult
    from netconsole.core.i18n import I18n
    from netconsole.ui.pages import network_adapter_route_page as page_module

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    qt_app = QApplication.instance() or QApplication([])
    assert qt_app is not None

    class FakeWindow:
        app_is_exiting = False

    class FakeApp:
        def __init__(self):
            self.quit_called = False
            self.window = FakeWindow()

        def topLevelWidgets(self):
            return [self.window]

        def quit(self):
            self.quit_called = True

    fake_app = FakeApp()
    monkeypatch.setattr(page_module, "is_admin", lambda: False)
    monkeypatch.setattr(page_module, "open_network_manager_as_admin", lambda **kwargs: AdminLaunchResult(True, 33, "ok"))
    monkeypatch.setattr(page_module.QTimer, "singleShot", lambda _ms, callback: callback())
    monkeypatch.setattr(page_module.QApplication, "instance", lambda: fake_app)

    page = page_module.NetworkAdapterRoutePage(I18n("en_US"), PathResolver(tmp_path))
    page.request_admin_network_manager()
    assert fake_app.quit_called is True
    assert fake_app.window.app_is_exiting is True


def test_admin_launch_cancel_does_not_quit_normal_app(monkeypatch, tmp_path: Path) -> None:
    import os
    from PySide6.QtWidgets import QApplication, QMessageBox
    from netconsole.core.admin import AdminLaunchResult
    from netconsole.core.i18n import I18n
    from netconsole.ui.pages import network_adapter_route_page as page_module

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    qt_app = QApplication.instance() or QApplication([])
    assert qt_app is not None

    class FakeApp:
        quit_called = False

        def topLevelWidgets(self):
            return []

        def quit(self):
            self.quit_called = True

    fake_app = FakeApp()
    monkeypatch.setattr(page_module, "is_admin", lambda: False)
    monkeypatch.setattr(page_module, "open_network_manager_as_admin", lambda **kwargs: AdminLaunchResult(False, 5, "cancelled"))
    monkeypatch.setattr(page_module.QApplication, "instance", lambda: fake_app)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: None)

    page = page_module.NetworkAdapterRoutePage(I18n("en_US"), PathResolver(tmp_path))
    page.request_admin_network_manager()
    assert fake_app.quit_called is False
    assert page.admin_launch_pending is False


def test_network_manager_page_chinese_headers_and_no_dns_field(monkeypatch, tmp_path: Path) -> None:
    import os
    from PySide6.QtWidgets import QApplication, QHeaderView, QSplitter
    from netconsole.core.i18n import I18n
    from netconsole.ui.pages import network_adapter_route_page as page_module

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    assert app is not None
    monkeypatch.setattr(page_module, "is_admin", lambda: False)

    page = page_module.NetworkAdapterRoutePage(I18n("zh_CN"), PathResolver(tmp_path))
    adapter_headers = [page.adapter_table.horizontalHeaderItem(index).text() for index in range(page.adapter_table.columnCount())]
    route_headers = [page.route_table.horizontalHeaderItem(index).text() for index in range(page.route_table.columnCount())]
    edit_route_headers = [page.route_edit_table.horizontalHeaderItem(index).text() for index in range(page.route_edit_table.columnCount())]
    assert adapter_headers == ["名称", "描述", "MAC", "状态", "速率", "IPv4", "网关", "标签"]
    assert route_headers == ["序号", "目标网络", "下一跳", "接口", "跃点数", "策略存储", "持久", "来源"]
    assert page.adapter_table.columnWidth(1) >= 280
    assert edit_route_headers == ["目标网络", "掩码", "下一跳", "出接口", "跃点数", "持久", "备注"]
    assert len(page.findChildren(QSplitter)) >= 2
    assert page.adapter_table.horizontalHeader().sectionResizeMode(1) == QHeaderView.Stretch
    assert page.adapter_table.horizontalHeader().sectionResizeMode(5) == QHeaderView.Stretch
    assert page.route_table.horizontalHeader().sectionResizeMode(1) == QHeaderView.Stretch
    visible_text = " ".join(
        [
            page.prefix_edit.placeholderText(),
            page.secondary_edit.placeholderText(),
            page.tabs.tabText(0),
            page.tabs.tabText(1),
        ]
    )
    assert "DNS" not in visible_text
    assert not hasattr(page, "dns_edit")


def test_adapter_page_uses_left_status_and_right_config_with_switch_vlan_disabled(monkeypatch, tmp_path: Path) -> None:
    import os
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QSplitter
    from netconsole.core.i18n import I18n
    from netconsole.ui.pages import network_adapter_route_page as page_module

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    assert app is not None
    monkeypatch.setattr(page_module, "is_admin", lambda: False)

    class FakeManager(WindowsNetworkManager):
        def get_vlan_capability(self, adapter_name: str) -> VlanCapability:
            return VlanCapability(
                supported=True,
                can_set_vlan_id=False,
                vlan_switch_property="VLAN标识",
                priority_vlan_property_name="VLAN标识",
                mode="priority_vlan_enum",
                message="当前网卡仅支持 VLAN 开关，不支持 VLAN ID 设置",
            )

    page = page_module.NetworkAdapterRoutePage(I18n("zh_CN"), PathResolver(tmp_path), manager=FakeManager())
    adapter = NetworkAdapterInfo(
        name="USB Ethernet",
        interface_index=12,
        description="USB Ethernet",
        mac_address="aa-bb",
        status="Up",
        link_speed="1 Gbps",
        ipv4_addresses=["192.168.105.200/24"],
        gateways=["192.168.105.1"],
    )
    page.adapters = [adapter]
    page.adapter_combo.addItem("USB Ethernet", adapter)
    page._adapter_changed()

    horizontal_splitters = [splitter for splitter in page.findChildren(QSplitter) if splitter.orientation() == Qt.Horizontal]
    assert horizontal_splitters
    assert page.adapter_status_fields["ipv4"].text() == "192.168.105.200/24"
    assert page.adapter_status_fields["gateway"].text() == "192.168.105.1"
    assert page.adapter_status_fields["mac"].text() == "aa-bb"
    assert page.vlan_spin.value() == 0
    assert page.vlan_spin.isEnabled() is False
    assert "不支持 VLAN ID" in page.vlan_hint_label.text()


def test_dhcp_mode_clears_and_disables_static_fields(monkeypatch, tmp_path: Path) -> None:
    import os
    from PySide6.QtWidgets import QApplication
    from netconsole.core.i18n import I18n
    from netconsole.ui.pages import network_adapter_route_page as page_module

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    assert app is not None
    monkeypatch.setattr(page_module, "is_admin", lambda: False)

    page = page_module.NetworkAdapterRoutePage(I18n("en_US"), PathResolver(tmp_path))
    page.mode_combo.setCurrentText("静态IP")
    page.ip_edit.setText("192.168.0.240")
    page.prefix_edit.setText("24")
    page.gateway_edit.setText("192.168.0.1")
    page.secondary_edit.setPlainText("10.122.100.200/24")
    page.mode_combo.setCurrentText("DHCP")
    assert page.ip_edit.text() == ""
    assert page.prefix_edit.text() == ""
    assert page.gateway_edit.text() == ""
    assert page.secondary_edit.toPlainText() == ""
    assert page.ip_edit.isEnabled() is False
    assert page.prefix_edit.isEnabled() is False
    assert page.gateway_edit.isEnabled() is False
    assert page.secondary_edit.isEnabled() is False

    page.mode_combo.setCurrentText("静态IP")
    assert page.ip_edit.isEnabled() is True
    assert page.prefix_edit.isEnabled() is True
    assert page.gateway_edit.isEnabled() is True
    assert page.secondary_edit.isEnabled() is True


def test_dhcp_config_ignores_stale_static_fields(monkeypatch, tmp_path: Path) -> None:
    import os
    from PySide6.QtWidgets import QApplication
    from netconsole.core.i18n import I18n
    from netconsole.ui.pages import network_adapter_route_page as page_module

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    assert app is not None
    monkeypatch.setattr(page_module, "is_admin", lambda: False)

    page = page_module.NetworkAdapterRoutePage(I18n("en_US"), PathResolver(tmp_path))
    page.mode_combo.setCurrentText("DHCP")
    page.ip_edit.setText("192.168.0.240")
    page.prefix_edit.setText("24")
    page.gateway_edit.setText("192.168.0.1")
    page.secondary_edit.setPlainText("10.122.100.200/24")
    config = page._ip_config_from_form(NetworkAdapterInfo(name="Ethernet", interface_index=12))
    assert config.mode == "dhcp"
    assert config.ip_address == ""
    assert config.gateway == ""
    assert config.secondary_ips == []
    assert config.dns_servers == []


def test_route_filters_and_original_order(monkeypatch, tmp_path: Path) -> None:
    import os
    from PySide6.QtWidgets import QApplication
    from netconsole.core.i18n import I18n
    from netconsole.ui.pages import network_adapter_route_page as page_module
    from netconsole.services.windows_network_manager import RouteInfo

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    assert app is not None
    monkeypatch.setattr(page_module, "is_admin", lambda: False)

    page = page_module.NetworkAdapterRoutePage(I18n("en_US"), PathResolver(tmp_path))
    page.routes = [
        RouteInfo("255.255.255.255/32", order_index=0, next_hop="0.0.0.0", interface_alias="Ethernet", route_metric=10, policy_store="ActiveStore", persistent=False, source="powershell"),
        RouteInfo("10.0.0.0/8", order_index=0, next_hop="0.0.0.0", interface_alias="Ethernet", route_metric=10, policy_store="ActiveStore", persistent=False, source="powershell"),
        RouteInfo("127.0.0.0/8", order_index=1, next_hop="0.0.0.0", interface_alias="Ethernet", route_metric=1, policy_store="ActiveStore", persistent=False, source="powershell"),
        RouteInfo("0.0.0.0/0", order_index=2, next_hop="192.168.1.1", interface_alias="Ethernet", route_metric=10, policy_store="ActiveStore", persistent=False, source="powershell"),
        RouteInfo("10.122.0.0/16", order_index=2, next_hop="192.168.105.1", interface_alias="ASIX", route_metric=10, policy_store="ActiveStore", persistent=False, source="manual"),
        RouteInfo("192.168.105.0/24", order_index=4, next_hop="192.168.105.1", interface_alias="ASIX", route_metric=10, policy_store="PersistentStore", persistent=True, source="powershell"),
    ]
    page._fill_route_table()
    assert [page.route_table.item(row, 1).text() for row in range(page.route_table.rowCount())] == [
        "0.0.0.0/0",
        "10.0.0.0/8",
        "10.122.0.0/16",
        "127.0.0.0/8",
        "192.168.105.0/24",
        "255.255.255.255/32",
    ]

    page.manual_static_only_check.setChecked(True)
    assert [page.route_table.item(row, 1).text() for row in range(page.route_table.rowCount())] == ["10.122.0.0/16", "192.168.105.0/24"]

    page.persistent_only_check.setChecked(True)
    assert [page.route_table.item(row, 1).text() for row in range(page.route_table.rowCount())] == ["192.168.105.0/24"]


def test_route_edit_table_uses_interface_combo_and_persistent_checkbox(monkeypatch, tmp_path: Path) -> None:
    import os
    from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox
    from netconsole.core.i18n import I18n
    from netconsole.ui.pages import network_adapter_route_page as page_module

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    assert app is not None
    monkeypatch.setattr(page_module, "is_admin", lambda: False)

    page = page_module.NetworkAdapterRoutePage(I18n("en_US"), PathResolver(tmp_path))
    page.adapters = [NetworkAdapterInfo(name="ASIX", interface_index=12, description="ASIX USB", ipv4_addresses=["192.168.105.200/24"])]
    page.add_route_row()

    combo = page.route_edit_table.cellWidget(0, 3)
    checkbox = page.route_edit_table.cellWidget(0, 5)
    assert isinstance(combo, QComboBox)
    assert isinstance(checkbox, QCheckBox)
    assert combo.currentData() == ("ASIX", 12)
    assert checkbox.isChecked() is True

    page.route_edit_table.item(0, 0).setText("192.168.105.0")
    page.route_edit_table.item(0, 2).setText("192.168.105.1")
    routes = page._selected_or_edited_routes()
    assert routes[0].destination_prefix == "192.168.105.0/24"
    assert routes[0].interface_index == 12
    assert routes[0].persistent is True


def test_route_profile_selection_loads_editor_and_apply_uses_latest_editor_data(monkeypatch, tmp_path: Path) -> None:
    import os
    from PySide6.QtWidgets import QApplication
    from netconsole.core.i18n import I18n
    from netconsole.ui.pages import network_adapter_route_page as page_module

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    assert app is not None
    monkeypatch.setattr(page_module, "is_admin", lambda: False)

    applied: list[RouteConfig] = []

    class FakeManager(WindowsNetworkManager):
        def apply_route(self, route: RouteConfig, *, require_admin: bool = True) -> None:
            applied.append(route)

    route_store = RouteProfileStore(tmp_path / "routes.json")
    route_store.upsert(
        RouteProfile(
            "MR-route",
            [RouteProfileEntry("192.168.105.0/24", "192.168.105.1", "ASIX", 10, True, "old", "255.255.255.0", 12)],
        )
    )
    page = page_module.NetworkAdapterRoutePage(I18n("en_US"), PathResolver(tmp_path), manager=FakeManager(), route_store=route_store)
    page.adapters = [NetworkAdapterInfo(name="ASIX", interface_index=12, description="ASIX USB", ipv4_addresses=["192.168.105.200/24"])]
    monkeypatch.setattr(page, "_confirm_write", lambda _preview: True)

    page.load_route_profile_into_editor(route_store.load()[0])
    assert page.route_profile_name_edit.text() == "MR-route"
    assert page.route_edit_table.item(0, 0).text() == "192.168.105.0"
    page.route_edit_table.item(0, 0).setText("192.168.106.0")
    page.apply_route_profile()
    assert applied[0].destination_prefix == "192.168.106.0/24"
    assert applied[0].interface_index == 12


def test_add_route_row_inherits_previous_next_hop_and_interface(monkeypatch, tmp_path: Path) -> None:
    import os
    from PySide6.QtWidgets import QApplication
    from netconsole.core.i18n import I18n
    from netconsole.ui.pages import network_adapter_route_page as page_module

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    assert app is not None
    monkeypatch.setattr(page_module, "is_admin", lambda: False)

    page = page_module.NetworkAdapterRoutePage(I18n("en_US"), PathResolver(tmp_path))
    page.adapters = [NetworkAdapterInfo(name="ASIX", interface_index=12, description="ASIX USB", ipv4_addresses=["192.168.105.200/24"])]
    page.add_route_row()
    page.route_edit_table.item(0, 2).setText("192.168.105.1")
    page.add_route_row()
    assert page.route_edit_table.item(1, 0).text() == ""
    assert page.route_edit_table.item(1, 1).text() == "255.255.255.0"
    assert page.route_edit_table.item(1, 2).text() == "192.168.105.1"
    assert page.route_edit_table.cellWidget(1, 3).currentData() == ("ASIX", 12)


def test_selecting_adapter_profile_loads_form_without_writing(monkeypatch, tmp_path: Path) -> None:
    import os
    from PySide6.QtWidgets import QApplication
    from netconsole.core.i18n import I18n
    from netconsole.ui.pages import network_adapter_route_page as page_module

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    assert app is not None
    monkeypatch.setattr(page_module, "is_admin", lambda: False)

    calls = []

    class FakeManager(WindowsNetworkManager):
        def get_vlan_capability(self, adapter_name: str) -> VlanCapability:
            return VlanCapability(supported=True, can_set_vlan_id=True, vlan_id_property="VLAN ID", vlan_id_property_name="VLAN ID", mode="vlan_id_numeric")

        def apply_ip_config(self, config: AdapterIpConfig, *, require_admin: bool = True) -> None:
            calls.append(config)

    profile_store = NetworkProfileStore(tmp_path / "profiles.json")
    profile_store.upsert(
        AdapterProfile(
            profile_name="static-usb",
            adapter_match=AdapterMatch(name="ASIX", mac="aa-bb", description_keyword="ASIX"),
            mode="static",
            ip_address="192.168.105.200",
            prefix_length=24,
            gateway="192.168.105.1",
            secondary_ips=[SecondaryIp("10.122.100.200", 24)],
            vlan_id=201,
        )
    )
    page = page_module.NetworkAdapterRoutePage(I18n("en_US"), PathResolver(tmp_path), manager=FakeManager(), profile_store=profile_store)
    page.adapters = [NetworkAdapterInfo(name="ASIX", interface_index=12, description="ASIX USB", mac_address="aa-bb")]
    page.adapter_combo.addItem("ASIX", page.adapters[0])
    page.load_adapter_profile_into_form(profile_store.load()[0])
    assert calls == []
    assert page.ip_edit.text() == "192.168.105.200"
    assert page.gateway_edit.text() == "192.168.105.1"
    assert page.secondary_edit.toPlainText() == "10.122.100.200/24"
    assert page.vlan_spin.value() == 201


def test_debug_real_write_guard_allows_only_asix_and_never_realtek() -> None:
    assert _allow_real_write_debug(SAFE_DEBUG_ADAPTER) is True
    assert _allow_real_write_debug(FORBIDDEN_DEBUG_ADAPTER) is False
    assert _allow_real_write_debug("Other Ethernet") is False


def test_production_network_manager_has_no_debug_adapter_hardcoding() -> None:
    source = inspect.getsource(manager_module)
    assert SAFE_DEBUG_ADAPTER not in source
    assert FORBIDDEN_DEBUG_ADAPTER not in source
