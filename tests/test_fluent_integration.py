import json
import os
import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from netconsole.core.settings import SettingsStore
from netconsole.core.paths import PathResolver
from netconsole.core.i18n import I18n
from netconsole.ui.navigation import Navigation
from netconsole.ui.shell.fluent_bridge import fluent_available


def app():
    return QApplication.instance() or QApplication([])


def test_requirements_use_only_pyside6_fluent_widgets():
    requirements = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text(encoding="utf-8")

    assert "PySide6-Fluent-Widgets==1.11.2" in requirements
    assert "PyQt-Fluent-Widgets" not in requirements
    assert "PyQt6-Fluent-Widgets" not in requirements
    assert "PySide2-Fluent-Widgets" not in requirements


def test_default_theme_is_light_for_fluent_ui(tmp_path):
    store = SettingsStore(PathResolver(tmp_path))

    assert store.theme == "light"


def test_navigation_uses_fluent_runtime_when_available():
    app()
    navigation = Navigation(I18n("zh_CN"))

    if fluent_available():
        assert navigation.findChild(type(navigation._fluent), "fluentNavigation") is navigation._fluent
    assert navigation.count() > 0
    assert navigation.item(0).data(256) == "devices"


def test_build_window_starts_app_fluent_window():
    from PySide6.QtWidgets import QLabel

    from netconsole.app import build_window
    from netconsole.ui.app_fluent_window import AppFluentWindow

    app()
    window = build_window()

    assert isinstance(window, AppFluentWindow)
    assert window.__class__.__name__ == "AppFluentWindow"
    assert window.windowTitle() == "NetConsole v1.3.8 by WXJ - 网络设备采集工具"
    assert any(label.text() == "NetConsole v1.3.8 by WXJ" for label in window.findChildren(QLabel, "appTopBarTitle"))
    assert not any(label.text() == "网络设备采集工具" for label in window.findChildren(QLabel, "appTopBarTitle"))
    assert not window.findChildren(QLabel, "fluentTitleSub")
    assert not any(not label.isHidden() and label.text() == window.windowTitle() for label in window.findChildren(QLabel, "titleLabel"))
    labels = [window.navigation.item(index).text() for index in range(window.navigation.count())]
    assert labels == [
        "设备管理",
        "AC 管理",
        "轨道交通",
        "配置采集中心",
        "文件管理",
        "网络工具",
        "命令说明",
        "日志中心",
        "系统设置",
        "功能开关配置",
    ]
    assert window.stackedWidget.count() == len(labels)
    assert not any(label in {"ac", "rail_transit", "config_collection", "file_management", "network_tools", "logs"} for label in labels)
    assert window.current_theme in {"light", "dark"}
    assert QApplication.instance().property("netconsoleTheme") == window.current_theme
    assert "#fluentPage" in QApplication.instance().styleSheet()
    assert "#appTopBar" in QApplication.instance().styleSheet()
    assert window._window_chrome_mode() == "qfluentwidgets-custom-titlebar"
    window.close()


def test_fluent_site_bar_reserves_window_controls_and_compacts_actions():
    from PySide6.QtWidgets import QPushButton, QWidget

    from netconsole.app import build_window
    from netconsole.ui.app_fluent_window import (
        TOP_BAR_FULL_WIDTH,
        TOP_BAR_MEDIUM_WIDTH,
        TOP_BAR_MIN_HEIGHT,
        WINDOW_CONTROL_SAFE_RIGHT,
    )

    app()
    window = build_window()
    site_bar = window.pages["devices"].findChild(QWidget, "appTopBar")

    assert site_bar is not None
    assert site_bar.minimumHeight() >= TOP_BAR_MIN_HEIGHT
    assert site_bar.maximumHeight() == TOP_BAR_MIN_HEIGHT
    spacer = site_bar.layout().itemAt(site_bar.layout().count() - 1).spacerItem()
    assert spacer is not None
    assert spacer.sizeHint().width() >= WINDOW_CONTROL_SAFE_RIGHT

    actions = site_bar.findChild(QWidget, "appTopBarActions")
    assert actions is not None
    buttons = {button.text(): button for button in actions.findChildren(QPushButton) if button.text()}
    for text in ("新建局点", "切换局点", "弹出模块", "更多"):
        assert text in buttons
    assert "中/EN" not in buttons
    assert "窗口置顶" not in buttons

    window.resize(TOP_BAR_FULL_WIDTH + 200, 900)
    window._sync_site_bar_action_modes()
    assert not buttons["新建局点"].isHidden()
    assert not buttons["切换局点"].isHidden()
    assert not buttons["弹出模块"].isHidden()
    assert not buttons["更多"].isHidden()
    visible_menu_texts = [action.text() for action in buttons["更多"].menu().actions() if action.isVisible() and action.text()]
    assert visible_menu_texts == [
        "窗口置顶",
        "打开当前局点目录",
        "打开 Web 控制台",
        "磁盘清理",
        "版本更新日志",
        "开源许可",
        "关于 NetConsole",
        "退出",
    ]

    window.resize(TOP_BAR_MEDIUM_WIDTH, 900)
    window._sync_site_bar_action_modes()
    assert buttons["新建局点"].isHidden()
    assert not buttons["切换局点"].isHidden()
    assert not buttons["弹出模块"].isHidden()
    visible_menu_texts = [action.text() for action in buttons["更多"].menu().actions() if action.isVisible() and action.text()]
    assert visible_menu_texts == [
        "新建局点",
        "窗口置顶",
        "打开当前局点目录",
        "打开 Web 控制台",
        "磁盘清理",
        "版本更新日志",
        "开源许可",
        "关于 NetConsole",
        "退出",
    ]

    window.setMinimumSize(900, 600)
    window.resize(TOP_BAR_MEDIUM_WIDTH - 100, 760)
    window._sync_site_bar_action_modes()
    assert buttons["新建局点"].isHidden()
    assert buttons["切换局点"].isHidden()
    assert buttons["弹出模块"].isHidden()
    visible_menu_texts = [action.text() for action in buttons["更多"].menu().actions() if action.isVisible() and action.text()]
    assert visible_menu_texts == [
        "新建局点",
        "切换局点",
        "弹出模块",
        "窗口置顶",
        "打开当前局点目录",
        "打开 Web 控制台",
        "磁盘清理",
        "版本更新日志",
        "开源许可",
        "关于 NetConsole",
        "退出",
    ]
    window.close()


def test_fluent_detach_current_page_opens_non_focus_window(monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMainWindow, QWidget

    from netconsole.app import build_window

    app()
    window = build_window()
    monkeypatch.setattr(window, "_create_detached_page", lambda page_id: QWidget())
    monkeypatch.setattr(window, "_activate_detached_page", lambda page_id, page: None)
    monkeypatch.setattr(window, "_show_info", lambda title, content: pytest.fail("detach should open a real window"))

    window.detach_current_page()

    detached = window.detached_windows.get("devices")
    assert isinstance(detached, QMainWindow)
    assert detached.isVisible()
    assert detached.windowTitle() == "NetConsole - 设备管理"
    assert detached.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert detached.windowModality() == Qt.WindowModality.NonModal

    window.detach_current_page()
    assert window.detached_windows.get("devices") is detached

    detached.close()
    expected_titles = {
        "ac": "AC 管理",
        "rail_transit": "轨道交通",
        "network_tools": "网络工具",
        "logs": "日志中心",
        "system_settings": "系统设置",
        "file_management": "文件管理",
    }
    for page_id, title in expected_titles.items():
        window.switchTo(window.pages[page_id])
        window.detach_current_page()
        detached_window = window.detached_windows.get(page_id)
        assert isinstance(detached_window, QMainWindow)
        assert detached_window.windowTitle() == f"NetConsole - {title}"
        detached_window.close()
    window.close()


def test_ac_global_command_bar_keeps_tab_specific_actions_out():
    from PySide6.QtWidgets import QApplication, QPushButton

    from netconsole.app import build_window
    from netconsole.ui.components.nc_command_bar import NCCommandBar

    app()
    window = build_window()
    command_bar = window.pages["ac"].findChild(NCCommandBar)

    assert command_bar is not None
    buttons = [button.text() for button in command_bar.findChildren(QPushButton) if button.text()]
    expected = ["刷新", "获取 AC 信息", "打开网页", "更新 AC 信息", "一键固化新上线 AP", "一键开启 AP 远程登入"]
    assert buttons == expected
    assert "更多" not in buttons
    for button in command_bar.findChildren(QPushButton):
        if button.text() in expected:
            assert not button.icon().isNull()
    for tab_specific_text in ("连接 AC", "导出", "获取 HTTPS 端口", "获取 AP 列表", "获取 AP 地址", "获取 AP 射频", "获取 Mesh Link", "更多"):
        assert tab_specific_text not in buttons
    window.preload_page("ac")
    ac_page = window.raw_pages["ac"]
    assert ac_page.current_tab_action_labels() == ["新增行", "删除选中", "保存", "导入", "导出", "下载模板", "更新"]
    for button in (
        ac_page.trackside_plan_page.add_button,
        ac_page.trackside_plan_page.delete_button,
        ac_page.trackside_plan_page.save_button,
        ac_page.trackside_plan_page.import_button,
        ac_page.trackside_plan_page.export_button,
        ac_page.trackside_plan_page.template_button,
        ac_page.trackside_plan_page.refresh_button,
    ):
        assert not button.icon().isNull()
    raw_ac_buttons = [button.text() for button in ac_page.findChildren(QPushButton) if button.text() and not button.isHidden()]
    for moved_text in ("打开网页", "更新AC信息", "一键固化新上线AP", "一键开启AP远程登入"):
        assert moved_text not in raw_ac_buttons
    top_level_texts = [widget.text() for widget in QApplication.topLevelWidgets() if isinstance(widget, QPushButton)]
    for moved_text in ("更新AC信息", "一键固化新上线AP", "一键开启AP远程登入"):
        assert moved_text not in top_level_texts
    window.close()


def test_ac_page_loads_local_data_on_first_enter():
    from PySide6.QtWidgets import QComboBox

    from netconsole.app import build_window

    app()
    window = build_window()
    window.preload_page("ac")
    ac_page = window.raw_pages["ac"]

    assert not ac_page._device_list_loaded
    window.switchTo(window.pages["ac"])
    deadline = time.time() + 5
    while not ac_page._device_list_loaded and time.time() < deadline:
        app().processEvents()
        time.sleep(0.01)

    assert ac_page._loaded_once
    assert ac_page._last_loaded_site_name == window.site.name
    assert ac_page._device_list_loaded
    if ac_page.ac_devices:
        assert ac_page.device_combo.currentIndex() >= 0
        assert ac_page.device_combo.currentData()
        assert ac_page.device_combo.currentText()
    assert isinstance(ac_page.device_combo, QComboBox)
    window.close()


def test_file_management_command_bar_only_has_connection_actions():
    from PySide6.QtWidgets import QPushButton

    from netconsole.app import build_window
    from netconsole.ui.components.nc_command_bar import NCCommandBar

    app()
    window = build_window()
    command_bar = window.pages["file_management"].findChild(NCCommandBar)

    assert command_bar is not None
    buttons = [button.text() for button in command_bar.findChildren(QPushButton) if button.text()]
    assert buttons == ["连接", "断开", "刷新连接状态", "打开 WinSCP"]
    for removed_text in ("上传", "下载", "新建目录", "删除", "Mesh 快选", "更多", "全选", "取消选择"):
        assert removed_text not in buttons
    window.close()


def test_file_management_fluent_connect_action_clicks_raw_connect_button():
    from PySide6.QtWidgets import QPushButton

    from netconsole.app import build_window
    from netconsole.ui.components.nc_command_bar import NCCommandBar

    app()
    window = build_window()
    window.preload_page("file_management")
    file_page = window.raw_pages["file_management"]
    command_bar = window.pages["file_management"].findChild(NCCommandBar)
    calls: list[str] = []

    file_page.connect_button.clicked.disconnect()
    file_page.connect_button.clicked.connect(lambda: calls.append("connect"))
    file_page.connect_button.setEnabled(True)
    connect_button = next(button for button in command_bar.findChildren(QPushButton) if button.text() == "连接")
    connect_button.click()

    assert calls == ["connect"]
    window.close()


def test_rail_transit_uses_only_tab_local_actions():
    from PySide6.QtWidgets import QPushButton

    from netconsole.app import build_window
    from netconsole.ui.components.nc_command_bar import NCCommandBar

    app()
    window = build_window()
    rail_page = window.pages["rail_transit"]
    window.preload_page("rail_transit")
    raw_rail_page = window.raw_pages["rail_transit"]

    assert rail_page.findChild(NCCommandBar) is None
    window.switchTo(rail_page)
    raw_rail_page._ensure_feature_page("rail.train_online")
    raw_rail_page._ensure_feature_page("rail.car_network_diagnostic")
    raw_rail_page._ensure_feature_page("rail.trackside_ap_business")
    raw_rail_page._ensure_feature_page("rail.online_mr_collection")
    raw_rail_page._ensure_feature_page("rail.online_mr_analysis")

    assert raw_rail_page.trackside_page is not None
    assert raw_rail_page.online_mr_page is not None
    assert raw_rail_page.online_mr_analysis_page is not None

    train_buttons = [
        raw_rail_page.vehicle_mr_online_page.start_button,
        raw_rail_page.vehicle_mr_online_page.stop_button,
        raw_rail_page.vehicle_mr_online_page.refresh_button,
        raw_rail_page.vehicle_mr_online_page.refresh_ap_button,
        raw_rail_page.vehicle_mr_online_page.mapping_button,
    ]
    car_buttons = [
        raw_rail_page.car_network_page.start_button,
        raw_rail_page.car_network_page.refresh_button,
        raw_rail_page.car_network_page.import_button,
        raw_rail_page.car_network_page.export_button,
        raw_rail_page.car_network_page.point_table_button,
    ]
    for button in [*train_buttons, *car_buttons]:
        assert isinstance(button, QPushButton)
        assert button.text().strip()
        assert button.toolTip().strip()
        assert not button.icon().isNull()
    window.close()


def test_network_tools_uses_only_tab_local_actions():
    from PySide6.QtWidgets import QPushButton

    from netconsole.app import build_window
    from netconsole.ui.components.nc_command_bar import NCCommandBar

    app()
    window = build_window()
    page = window.pages["network_tools"]
    window.preload_page("network_tools")
    raw_page = window.raw_pages["network_tools"]

    assert page.findChild(NCCommandBar) is None

    buttons = [
        raw_page.iperf_page.server_start_button,
        raw_page.iperf_page.server_stop_button,
        raw_page.iperf_page.client_start_button,
        raw_page.iperf_page.client_stop_button,
        raw_page.wireless_scan_page.start_button,
        raw_page.wireless_scan_page.stop_button,
        raw_page.toolbox_page.single_ping_panel.export_csv_button,
        raw_page.toolbox_page.single_ping_panel.clear_button,
    ]
    for button in buttons:
        assert isinstance(button, QPushButton)
        assert button.text().strip()
        assert button.toolTip().strip()
    window.close()


def test_disabled_snmp_center_is_not_registered():
    from netconsole.app import build_window

    app()
    window = build_window()
    assert "snmp_center" not in window.pages
    assert "snmp_center" not in window.raw_pages
    window.close()


def test_visible_fluent_window_close_requires_confirmation(monkeypatch):
    from netconsole.app import build_window
    from netconsole.ui.app_fluent_window import MessageBox

    app()
    window = build_window()
    prompts = []

    def fake_question(*args, **kwargs):
        prompts.append((args, kwargs))
        return MessageBox.No

    monkeypatch.setattr(MessageBox, "question", fake_question)
    window.show()

    assert window.close() is False
    assert prompts
    window._force_close = True
    window.close()


def test_fluent_preload_does_not_create_english_placeholder_pages():
    from netconsole.app import build_window

    app()
    window = build_window()

    for page_id in ("ac", "rail_transit", "config_collection", "file_management", "network_tools", "logs"):
        window.preload_page(page_id)

    labels = [window.navigation.item(index).text() for index in range(window.navigation.count())]
    assert "ac" not in labels
    assert "rail_transit" not in labels
    assert window.stackedWidget.count() == 10
    window.close()


def test_fluent_window_applies_netconsole_theme_to_tables():
    from PySide6.QtWidgets import QTableWidget

    from netconsole.app import build_window

    app()
    window = build_window()
    table = window.findChild(QTableWidget)

    assert table is not None
    assert table.property("netconsoleTheme") == window.current_theme
    if window.current_theme == "dark":
        assert "background-color: #1f2937" in table.styleSheet()
        assert "alternate-background-color: #273549" in table.styleSheet()
    else:
        assert "background-color: #ffffff" in table.styleSheet()
        assert "alternate-background-color: #f8fafc" in table.styleSheet()
        assert "background-color: #1f2937" not in table.styleSheet()
    window.close()


def test_fluent_window_set_theme_synchronizes_fluent_and_global_stylesheet(monkeypatch):
    if os.environ.get("QT_QPA_PLATFORM", "").casefold() == "offscreen":
        pytest.skip("Qt offscreen destroys QFluentWidgets windows unstably after live theme switching")

    from PySide6.QtWidgets import QTableWidget

    from netconsole.app import build_window
    from netconsole.ui.theme import qt_theme_engine

    fluent_calls = []
    monkeypatch.setattr("netconsole.ui.app_fluent_window.apply_fluent_theme", lambda theme, color="#0078D4": fluent_calls.append((theme, color)))
    monkeypatch.setattr(qt_theme_engine, "apply_fluent_theme", lambda theme, color="#0078D4": fluent_calls.append((theme, color)))

    def fake_apply_global_theme(theme: str) -> None:
        theme_mode = "dark" if theme == "dark" else "light"
        QApplication.instance().setProperty("netconsoleTheme", theme_mode)

    monkeypatch.setattr("netconsole.ui.app_fluent_window.apply_global_theme", fake_apply_global_theme)

    app()
    window = build_window()
    table = window.findChild(QTableWidget)
    assert table is not None

    window.set_theme("dark")
    QApplication.processEvents()
    QApplication.processEvents()
    assert window.current_theme == "dark"
    assert QApplication.instance().property("netconsoleTheme") == "dark"
    if QApplication.platformName().casefold() != "offscreen":
        assert ("dark", window.settings.theme_color) in fluent_calls
    assert table.property("netconsoleTheme") == "dark"
    assert "background-color: #1f2937" in table.styleSheet()

    window.set_theme("light")
    QApplication.processEvents()
    QApplication.processEvents()
    assert window.current_theme == "light"
    assert QApplication.instance().property("netconsoleTheme") == "light"
    if QApplication.platformName().casefold() != "offscreen":
        assert ("light", window.settings.theme_color) in fluent_calls
    assert table.property("netconsoleTheme") == "light"
    assert "background-color: #ffffff" in table.styleSheet()
    window.close()


def test_fluent_command_bar_is_text_first_and_hides_device_legacy_bar():
    from PySide6.QtWidgets import QPushButton

    from netconsole.app import build_window
    from netconsole.ui.components.nc_command_bar import NCCommandBar

    app()
    window = build_window()
    command_bar = window.pages["devices"].findChild(NCCommandBar)

    assert command_bar is not None
    buttons = [button.text() for button in command_bar.findChildren(QPushButton) if button.text()]
    assert "新增" in buttons
    assert "测试连接" in buttons
    assert "批量更新详情" in buttons
    assert "诊断下载" in buttons
    assert "导入 CSV" in buttons
    assert "导出 CSV" in buttons
    assert "刷新" in buttons
    assert "更多" in buttons
    assert "外部终端配置" not in buttons
    assert "生成 CRT 会话" not in buttons
    assert all(text.strip() for text in buttons)
    more_button = next(button for button in command_bar.findChildren(QPushButton) if button.text() == "更多")
    assert more_button.menu() is not None
    assert [action.text() for action in more_button.menu().actions()] == [
        "生成 CRT 会话",
        "清空选择",
        "反选",
        "分组管理",
        "设置分组",
        "导出模板",
        "批量删除",
    ]
    assert window.raw_pages["devices"].action_scroll.isHidden()
    window.close()


def test_config_collection_command_bar_uses_single_main_action_set():
    from PySide6.QtWidgets import QPushButton

    from netconsole.app import build_window
    from netconsole.ui.components.nc_command_bar import NCCommandBar

    app()
    window = build_window()
    command_bar = window.pages["config_collection"].findChild(NCCommandBar)

    assert command_bar is not None
    buttons = [button.text() for button in command_bar.findChildren(QPushButton) if button.text()]
    assert buttons == ["保存配置", "下载配置", "配置对比", "打开目录", "刷新"]
    assert "诊断下载" not in buttons
    assert all(not button.icon().isNull() for button in command_bar.findChildren(QPushButton) if button.text() in buttons)

    window.preload_page("config_collection")
    left_buttons = [button.text() for button in window.raw_pages["config_collection"].left_panel.findChildren(QPushButton) if button.text()]
    for text in ("保存配置", "下载配置", "配置对比", "刷新", "诊断下载"):
        assert text not in left_buttons
    for text in ("打开目录", "下载快照", "导出当前批次", "导出差异", "删除快照"):
        assert text in left_buttons
    window.close()


def test_settings_page_saves_real_controls(tmp_path):
    from netconsole.core.sites import Site
    from netconsole.ui.pages.settings_page import NoWheelSettingsComboBox, NoWheelSettingsSpinBox, SettingsPage

    app()
    paths = PathResolver(tmp_path)
    paths.settings_path.parent.mkdir(parents=True, exist_ok=True)
    paths.settings_path.write_text(json.dumps({"external_terminal/type": "windows_terminal"}, ensure_ascii=False), encoding="utf-8")
    settings = SettingsStore(paths)
    site = Site("demo", paths.site_dir("demo"), paths.site_db_path("demo"))
    page = SettingsPage(settings, site, paths)

    assert settings.get_value("external_terminal/type") == "securecrt"
    assert [page.external_terminal_type_combo.itemText(index) for index in range(page.external_terminal_type_combo.count())] == ["PuTTY", "SecureCRT", "Xshell"]
    assert page.external_terminal_type_combo.currentText() == "SecureCRT"
    assert isinstance(page.external_terminal_type_combo, NoWheelSettingsComboBox)
    assert isinstance(page.theme_combo, NoWheelSettingsComboBox)
    assert isinstance(page.ssh_port_spin, NoWheelSettingsSpinBox)
    assert isinstance(page.telnet_port_spin, NoWheelSettingsSpinBox)
    assert not page.default_concurrency_spin.isEnabled()
    assert not page.command_timeout_spin.isEnabled()
    assert not page.log_retention_spin.isEnabled()
    assert not page.download_dir_edit.isEnabled()

    page.theme_combo.setCurrentText("深色")
    page.language_combo.setCurrentText("English")
    page.theme_color_combo.setCurrentText("工程蓝 #2563EB")
    page.default_concurrency_spin.setValue(32)
    page.command_timeout_spin.setValue(45)
    page.log_retention_spin.setValue(90)
    page.download_dir_edit.setText(str(tmp_path / "downloads"))
    page.external_terminal_type_combo.setCurrentText("SecureCRT")
    page.external_terminal_path_edit.setText(str(tmp_path / "SecureCRT.exe"))
    page.crt_session_dir_edit.setText(str(tmp_path / "crt_sessions"))
    page.ssh_port_spin.setValue(2222)
    page.telnet_port_spin.setValue(2323)
    page.crt_encoding_combo.setCurrentText("GBK")
    page.save_settings()

    reloaded = SettingsStore(paths)
    assert reloaded.theme == "dark"
    assert reloaded.language == "en_US"
    assert reloaded.theme_color == "#2563EB"
    assert reloaded.int_value("default_concurrency", 0) == 10
    assert reloaded.int_value("command_timeout", 0) == 30
    assert reloaded.int_value("log_retention_days", 0) == 30
    assert reloaded.get_value("download_dir") == ""
    assert reloaded.get_value("external_terminal/type") == "securecrt"
    assert reloaded.get_value("external_terminal/securecrt_path") == str(tmp_path / "SecureCRT.exe")
    assert reloaded.get_value("external_terminal/securecrt_sessions_root") == str(tmp_path / "crt_sessions")
    assert reloaded.int_value("external_terminal/default_ssh_port", 0) == 2222
    assert reloaded.int_value("external_terminal/default_telnet_port", 0) == 2323
    assert reloaded.get_value("external_terminal/crt_encoding") == "GBK"
