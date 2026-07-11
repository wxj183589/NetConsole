import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QHeaderView, QLabel, QMessageBox, QPushButton, QScrollArea, QTableWidget

from netconsole.core import app_logger
from netconsole.core.database import Database
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.repositories.device_fact_repository import DeviceFactRepository
from netconsole.services.diagnostic_download_service import DiagnosticDownloadResult
from netconsole.services.external_terminal import (
    ExternalTerminalConfig,
    TERMINAL_LABELS,
    TERMINAL_SETTING_KEYS,
    _safe_command,
    available_external_terminal_configs,
    build_external_terminal_command,
    build_winscp_command,
    launch_external_terminal,
)
from netconsole.services.netmiko_connection import ConnectionTarget, choose_connection_target
from netconsole.services.securecrt_session_export import export_securecrt_sessions, sanitize_path_part
from netconsole.ui.theme.qt_theme_engine import apply_theme
from netconsole.ui.dialogs.device_detail_dialog import DeviceDetailDialog, INTERFACE_COLUMNS, LLDP_COLUMNS, OPTICAL_MODULE_COLUMNS, OVERVIEW_FIELDS, _column_min_widths
from netconsole.ui.dialogs.external_terminal_settings_dialog import ExternalTerminalSettingsDialog
from netconsole.ui.pages.device_management_page import DeviceManagementPage, choose_devices_for_export, open_diagnostic_folder_for_results, select_device_id_for_connection
from netconsole.ui.batch_connection_worker import BATCH_CONNECTION_DEFAULT_CONCURRENCY, BatchConnectionTestWorker
from netconsole.ui.batch_collect_worker import BATCH_COLLECT_DEFAULT_CONCURRENCY, BatchCollectWorker
from netconsole.ui.widgets.device_table import CHECK_COLUMN, COLUMNS, DEVICE_TABLE_DIRECT_FILL_LIMIT, DEVICE_COLUMN_WIDTHS, DeviceTable, protocol_label
from netconsole.ui.widgets.table_check_delegate import CheckBoxOnlyDelegate, is_checked_value


def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _stub_device_management_background_jobs(monkeypatch):
    monkeypatch.setattr("netconsole.ui.pages.device_management_page.DeviceManagementPage.refresh", lambda *_args, **_kwargs: None)
    yield
    application = QApplication.instance()
    if application is None:
        return
    for widget in list(application.topLevelWidgets()):
        widget.close()
        widget.deleteLater()
    application.processEvents()


_BaseDeviceDetailDialog = DeviceDetailDialog


def DeviceDetailDialog(*args, **kwargs):
    dialog = _BaseDeviceDetailDialog(*args, **kwargs)
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        app().processEvents()
        if not dialog.detail_load_job_id:
            break
        time.sleep(0.01)
    return dialog


def test_protocol_display_rules():
    assert protocol_label(1, 0) == "SSH"
    assert protocol_label(0, 1) == "Telnet"
    assert protocol_label(1, 1) == "SSH/Telnet"
    assert protocol_label(0, 0) == "-"


def test_securecrt_command_uses_ssh_without_password_by_default():
    device = Device(name="SW1", ip_address="10.0.0.1", ssh_enabled=1, ssh_username="admin", ssh_password="secret", telnet_enabled=0)
    target = choose_connection_target(device)
    args = build_external_terminal_command(device, target, "securecrt", r"C:\Tools\SecureCRT.exe")

    assert args == [r"C:\Tools\SecureCRT.exe", "/SSH2", "/P", "22", "/L", "admin", "10.0.0.1"]
    assert "secret" not in args


def test_securecrt_command_includes_password_only_when_enabled():
    # Updated behavior: SecureCRT can receive the password when explicitly enabled.
    device = Device(name="SW1", ip_address="10.0.0.1", ssh_enabled=1, ssh_username="admin", ssh_password="secret", telnet_enabled=0)
    target = choose_connection_target(device)
    args = build_external_terminal_command(device, target, "securecrt", r"C:\Tools\SecureCRT.exe", include_password=True)

    assert "/PASSWORD" in args
    assert "secret" in args
    assert "secret" not in _safe_command(args, device)


def test_external_terminal_missing_exe_returns_failure():
    device = Device(name="SW1", ip_address="10.0.0.1", ssh_enabled=1, ssh_username="admin", ssh_password="secret", telnet_enabled=0)

    result = launch_external_terminal(device, ExternalTerminalConfig(exe_path=r"Z:\missing\SecureCRT.exe"))

    assert result.success is False
    assert "SecureCRT" in result.message


def test_external_terminal_launch_registers_as_ignored_external_tool(monkeypatch):
    device = Device(name="SW1", ip_address="10.0.0.1", ssh_enabled=1, ssh_username="admin", ssh_password="secret", telnet_enabled=0)
    calls: list[dict[str, object]] = []

    class FakeProcess:
        pid = 1234

    monkeypatch.setattr("netconsole.services.external_terminal.Path.is_file", lambda _self: True)
    monkeypatch.setattr("netconsole.services.external_terminal.subprocess.Popen", lambda *args, **kwargs: FakeProcess())
    monkeypatch.setattr(
        "netconsole.services.external_terminal.shutdown_manager.register_process",
        lambda process, name="", **kwargs: calls.append({"process": process, "name": name, **kwargs}),
    )

    result = launch_external_terminal(device, ExternalTerminalConfig(exe_path=r"C:\Tools\SecureCRT.exe"))

    assert result.success is True
    assert calls == [
        {
            "process": calls[0]["process"],
            "name": "SecureCRT",
            "kind": "external_tool",
            "shutdown_policy": "ignore",
        }
    ]


def test_securecrt_command_passes_password_and_masks_safe_command():
    device = Device(name="SW1", ip_address="10.0.0.1", ssh_enabled=1, ssh_username="admin", ssh_password="secret", telnet_enabled=0)
    target = choose_connection_target(device)

    args = build_external_terminal_command(device, target, "securecrt", r"C:\Tools\SecureCRT.exe", include_password=True)

    assert args == [r"C:\Tools\SecureCRT.exe", "/SSH2", "/P", "22", "/L", "admin", "10.0.0.1", "/PASSWORD", "secret"]
    assert "secret" not in _safe_command(args, device)


def test_putty_command_passes_password_and_masks_safe_command():
    device = Device(name="SW1", ip_address="10.0.0.1", ssh_enabled=1, ssh_username="admin", ssh_password="secret", telnet_enabled=0)
    target = choose_connection_target(device)

    args = build_external_terminal_command(device, target, "putty", r"C:\Tools\putty.exe", include_password=True)

    assert args == [r"C:\Tools\putty.exe", "-ssh", "admin@10.0.0.1", "-P", "22", "-pw", "secret"]
    assert "secret" not in _safe_command(args, device)


def test_winscp_command_uses_sftp_and_masks_password():
    device = Device(name="SW1", ip_address="10.0.0.1", ssh_enabled=1, ssh_username="admin", ssh_password="sec ret", telnet_enabled=0)
    target = choose_connection_target(device)

    args = build_winscp_command(device, target, r"C:\Tools\WinSCP.exe")

    assert args == [r"C:\Tools\WinSCP.exe", "sftp://admin:sec%20ret@10.0.0.1:22/", "/newinstance"]
    assert "sec ret" not in _safe_command(args, device)
    assert "sec%20ret" not in _safe_command(args, device)


def test_winscp_tunnel_target_uses_localhost_port():
    device = Device(name="SW1", ssh_password="secret")
    target = ConnectionTarget("SSH", "hp_comware", "127.0.0.1", 32022, "admin", "secret", via_tunnel=True)

    args = build_winscp_command(device, target, r"C:\Tools\WinSCP.exe")

    assert args[1] == "sftp://admin:secret@127.0.0.1:32022/"


def test_external_terminal_configs_ignore_mobaxterm_and_cmd_paths(monkeypatch):
    settings = FakeSettings()
    settings.values.update(
        {
            "external_terminal/securecrt_path": r"C:\Tools\SecureCRT.exe",
            "external_terminal/mobaxterm_path": r"C:\Tools\MobaXterm.exe",
            "external_terminal/cmd_path": r"C:\Windows\System32\cmd.exe",
            "external_terminal/powershell_path": r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
            "external_terminal/legacy_ssh_compatibility": True,
            "external_terminal/legacy_ssh_extended_compatibility": True,
        }
    )
    monkeypatch.setattr("netconsole.services.external_terminal.Path.is_file", lambda self: str(self).endswith("SecureCRT.exe"))

    configs = available_external_terminal_configs(settings)

    assert [config.terminal_type for config in configs] == ["securecrt"]
    assert "mobaxterm" not in TERMINAL_LABELS
    assert "cmd" not in TERMINAL_LABELS
    assert "powershell" not in TERMINAL_LABELS
    assert "mobaxterm" not in TERMINAL_SETTING_KEYS
    assert "cmd" not in TERMINAL_SETTING_KEYS
    assert "powershell" not in TERMINAL_SETTING_KEYS


class FakeSettings:
    def __init__(self):
        self.values = {}

    def get_value(self, key, default=None):
        return self.values.get(key, default)

    def set_value(self, key, value):
        self.values[key] = value


def test_external_terminal_settings_dialog_saves_only_paths():
    app()
    settings = FakeSettings()
    dialog = ExternalTerminalSettingsDialog(I18n("en_US"), settings)
    dialog.securecrt_path.setText(r"C:\Tools\SecureCRT.exe")
    dialog.xshell_path.setText(r"C:\Tools\Xshell.exe")
    dialog.putty_path.setText(r"C:\Tools\putty.exe")

    dialog._save()

    assert not hasattr(dialog, "powershell_path")
    assert not hasattr(dialog, "legacy_ssh_compatibility")
    assert settings.values == {
        "external_terminal/securecrt_path": r"C:\Tools\SecureCRT.exe",
        "external_terminal/xshell_path": r"C:\Tools\Xshell.exe",
        "external_terminal/putty_path": r"C:\Tools\putty.exe",
        "external_terminal/pass_password": False,
    }


def test_securecrt_session_export_creates_group_station_tree(tmp_path):
    device = Device(
        name='SW:1',
        ip_address="10.0.0.1",
        station="Station/A",
        group_id=7,
        ssh_enabled=1,
        ssh_username="admin",
        ssh_password="secret",
        telnet_enabled=0,
    )

    result = export_securecrt_sessions([device], "Site:Demo", tmp_path, group_names={7: "Group*One"})

    assert result.generated == 1
    assert result.skipped == 0
    ini_files = list(result.output_dir.rglob("*.ini"))
    assert len(ini_files) == 1
    assert "Site_Demo" in str(ini_files[0])
    assert "Group_One" in str(ini_files[0])
    assert "Station_A" in str(ini_files[0])
    text = ini_files[0].read_text(encoding="utf-8")
    assert 'S:"Hostname"=10.0.0.1' in text
    assert 'S:"Protocol Name"=SSH2' in text
    assert "secret" not in text


def test_external_terminal_settings_dialog_saves_paths_and_options():
    app()
    settings = FakeSettings()
    dialog = ExternalTerminalSettingsDialog(I18n("en_US"), settings)
    dialog.securecrt_path.setText(r"C:\Tools\SecureCRT.exe")
    dialog.xshell_path.setText(r"C:\Tools\Xshell.exe")
    dialog.putty_path.setText(r"C:\Tools\putty.exe")
    dialog.pass_password.setChecked(True)

    dialog._save()

    assert settings.values == {
        "external_terminal/securecrt_path": r"C:\Tools\SecureCRT.exe",
        "external_terminal/xshell_path": r"C:\Tools\Xshell.exe",
        "external_terminal/putty_path": r"C:\Tools\putty.exe",
        "external_terminal/pass_password": True,
    }
    assert sanitize_path_part('a:b*c?') == "a_b_c_"


def test_main_table_columns_only_include_core_fields():
    assert [field for field, _key in COLUMNS] == [
        "select",
        "name",
        "group",
        "system_name",
        "station",
        "primary_address",
        "backup_address",
        "protocols",
        "updated_at",
    ]


def test_user_visible_i18n_and_ui_text_do_not_contain_question_mark_mojibake():
    root = Path(__file__).parents[1] / "netconsole"
    checked_files = [
        path
        for path in root.rglob("*.py")
        if path.relative_to(root).parts[:1] in {("core",), ("ui",), ("services",)}
        and path.name not in {"text_encoding.py"}
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in checked_files)

    assert "?????" not in text
    assert "�" not in text
    assert "站点/位置" not in text


def test_device_table_header_tooltips_are_readable():
    app()
    table = DeviceTable(I18n("zh_CN"))
    fields = [field for field, _key in COLUMNS]

    expected = {
        "station": "归属站点：来自设备管理的站点归属字段，用于设备和AP归属匹配。",
        "primary_address": "主用地址：设备优先使用的管理地址。",
        "backup_address": "备用地址：主用地址不可用时使用的管理地址。",
        "system_name": "系统名称：设备 sysname，由批量更新详情采集回填。",
    }
    for field, tooltip in expected.items():
        actual = table.horizontalHeaderItem(fields.index(field)).toolTip()
        assert actual == tooltip
        assert "???" not in actual
        assert "�" not in actual


def test_choose_devices_for_export_uses_all_when_selection_is_empty():
    all_devices = [Device(id=1, name="A"), Device(id=2, name="B")]

    assert choose_devices_for_export(all_devices, []) == all_devices


def test_choose_devices_for_export_uses_selected_when_available():
    all_devices = [Device(id=1, name="A"), Device(id=2, name="B")]
    selected = [all_devices[1]]

    assert choose_devices_for_export(all_devices, selected) == selected


def test_open_diagnostic_folder_for_successful_results_opens_once(tmp_path, monkeypatch):
    paths = PathResolver(tmp_path)
    paths.ensure_site_dirs("demo")
    diagnostic_dir = paths.config_center_raw_logs_dir("demo", "20260618", "diagnostic")
    diagnostic_dir.mkdir(parents=True, exist_ok=True)
    first = diagnostic_dir / "SW01_diag_20260618_101200.txt"
    second = diagnostic_dir / "SW02_diag_20260618_101300.txt"
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")
    opened = []

    monkeypatch.setattr(
        "netconsole.ui.pages.device_management_page.QDesktopServices.openUrl",
        lambda url: opened.append(url.toLocalFile()) or True,
    )

    result = open_diagnostic_folder_for_results(
        [
            DiagnosticDownloadResult(
                1,
                "SW01",
                "20260618_101200",
                "files/config_center/raw_logs/20260618/diagnostic/SW01_diag_20260618_101200.txt",
                "success",
            ),
            DiagnosticDownloadResult(
                2,
                "SW02",
                "20260618_101300",
                "files/config_center/raw_logs/20260618/diagnostic/SW02_diag_20260618_101300.txt",
                "success",
            ),
        ],
        "demo",
        paths,
    )

    assert result is True
    assert [Path(path) for path in opened] == [diagnostic_dir]


def test_open_diagnostic_folder_failure_is_logged(tmp_path, monkeypatch):
    paths = PathResolver(tmp_path)
    app_logger.configure_path_resolver(paths)
    paths.ensure_site_dirs("demo")
    diagnostic_dir = paths.config_center_raw_logs_dir("demo", "20260618", "diagnostic")
    diagnostic_dir.mkdir(parents=True, exist_ok=True)
    diagnostic_file = diagnostic_dir / "SW01_diag_20260618_101200.txt"
    diagnostic_file.write_text("first", encoding="utf-8")

    def fail_open(_url):
        raise OSError("cannot open")

    monkeypatch.setattr("netconsole.ui.pages.device_management_page.QDesktopServices.openUrl", fail_open)

    result = open_diagnostic_folder_for_results(
        [
            DiagnosticDownloadResult(
                1,
                "SW01",
                "20260618_101200",
                "files/config_center/raw_logs/20260618/diagnostic/SW01_diag_20260618_101200.txt",
                "success",
            )
        ],
        "demo",
        paths,
    )

    assert result is False
    assert app_logger.read_logs()[0]["event"] == "DIAGNOSTIC_FOLDER_OPEN_FAILED"


def test_test_connection_selection_requires_a_device():
    assert select_device_id_for_connection([], None) == (None, "devices.select_first_test")


def test_test_connection_selection_rejects_multiple_checked_devices():
    assert select_device_id_for_connection([1, 2], 1) == (None, "devices.select_one_for_test")


def test_test_connection_selection_uses_single_checked_or_current_device():
    assert select_device_id_for_connection([2], 1) == (2, None)
    assert select_device_id_for_connection([], 1) == (1, None)


def make_table():
    app()
    table = DeviceTable(I18n("en_US"))
    table.set_devices([Device(id=1, name="A"), Device(id=2, name="B")])
    return table


def test_double_click_row_does_not_call_edit_callback():
    table = make_table()
    edited = []
    table.edit_requested.connect(lambda device_id: edited.append(device_id))

    table.doubleClicked.emit(table.model().index(0, 2))

    assert edited == []


def test_row_edit_menu_action_calls_edit_callback():
    table = make_table()
    edited = []
    table.edit_requested.connect(lambda device_id: edited.append(device_id))

    menu = table.context_menu_for_device(1, 0, table._column_index("name"))
    menu.actions()[3].trigger()

    assert edited == [1]


def test_row_duplicate_menu_action_calls_duplicate_callback():
    table = make_table()
    duplicated = []
    table.duplicate_requested.connect(lambda device_id: duplicated.append(device_id))

    menu = table.context_menu_for_device(1, 0, table._column_index("name"))
    menu.actions()[1].trigger()

    assert duplicated == [1]


def test_row_action_menu_includes_connection_edit_and_delete():
    table = make_table()
    menu = table.context_menu_for_device(1, 0, table._column_index("name"))

    assert [action.text() for action in menu.actions() if not action.isSeparator()] == ["Details", "Duplicate Device", "External Terminal", "Edit", "Delete", "Copy Text"]
    assert table.contextMenuPolicy() == Qt.CustomContextMenu


def test_row_context_menu_keeps_text_copy_actions_in_submenu():
    table = make_table()
    menu = table.context_menu_for_device(1, 0, table._column_index("name"))
    copy_menu = menu.actions()[-1].menu()

    assert copy_menu is not None
    assert [action.text() for action in copy_menu.actions()] == [
        "Copy Current Cell",
        "Copy Name",
        "Copy Primary Address",
        "Copy Backup Address",
        "Copy System Name",
        "Copy Station",
        "Copy Row",
        "Copy Device Information",
    ]
    copy_menu.actions()[1].trigger()
    assert QApplication.clipboard().text() == "A"


def test_row_external_terminal_menu_action_calls_single_device_callback():
    table = make_table()
    requested = []
    table.external_terminal_requested.connect(lambda device_id: requested.append(device_id))

    menu = table.context_menu_for_device(1, 0, table._column_index("name"))
    menu.actions()[2].trigger()

    assert requested == [1]


def test_row_action_menu_includes_chinese_detail_text():
    app()
    table = DeviceTable(I18n("zh_CN"))
    table.set_devices([Device(id=1, name="A")])
    menu = table.context_menu_for_device(1, 0, table._column_index("name"))

    assert menu.actions()[0].text() == "\u8be6\u60c5"



def test_device_table_columns_keep_readable_widths_without_cell_widgets():
    table = make_table()

    assert table.horizontalHeader().stretchLastSection() is False
    assert table.horizontalScrollBarPolicy() == Qt.ScrollBarAsNeeded
    assert table.columnWidth(table._column_index("select")) == DEVICE_COLUMN_WIDTHS["select"]
    assert table.columnWidth(table._column_index("name")) == DEVICE_COLUMN_WIDTHS["name"]
    assert table.columnWidth(table._column_index("primary_address")) == DEVICE_COLUMN_WIDTHS["primary_address"]
    assert isinstance(table.itemDelegateForColumn(CHECK_COLUMN), CheckBoxOnlyDelegate)
    assert table.verticalHeader().defaultSectionSize() == 36
    assert table.rowHeight(0) == 36


def test_device_table_batches_large_device_rendering():
    application = app()
    table = DeviceTable(I18n("en_US"))
    devices = [Device(id=index + 1, name=f"Device {index + 1}") for index in range(DEVICE_TABLE_DIRECT_FILL_LIMIT + 50)]

    table.set_devices(devices)

    assert table.rowCount() == 0
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and table.item(len(devices) - 1, table._column_index("name")) is None:
        application.processEvents()
        QTest.qWait(1)

    assert table.rowCount() == len(devices)
    assert table.item(len(devices) - 1, table._column_index("name")).text() == f"Device {len(devices)}"


def test_checkbox_click_adds_and_removes_selected_device_id():
    table = make_table()
    item = table.item(0, CHECK_COLUMN)

    item.setCheckState(Qt.Checked)
    assert table.checked_device_ids() == [1]
    assert table.selected_device_ids == {1}

    item.setCheckState(Qt.Unchecked)
    assert table.checked_device_ids() == []
    assert table.selected_device_ids == set()


def test_header_checkbox_selects_and_clears_current_devices():
    table = make_table()

    table._header_clicked(CHECK_COLUMN)
    assert table.checked_device_ids() == [1, 2]
    assert table.horizontalHeaderItem(CHECK_COLUMN).checkState() == Qt.Checked
    assert all(is_checked_value(table.item(row, CHECK_COLUMN).checkState()) for row in range(table.rowCount()))

    table._header_clicked(CHECK_COLUMN)
    assert table.checked_device_ids() == []
    assert table.horizontalHeaderItem(CHECK_COLUMN).checkState() == Qt.Unchecked
    assert all(not is_checked_value(table.item(row, CHECK_COLUMN).checkState()) for row in range(table.rowCount()))


class PageRepository:
    def __init__(self):
        self.database = Database(":memory:")
        self.devices = [Device(id=1, name="A", primary_address="10.0.0.1"), Device(id=2, name="B", primary_address="10.0.0.2")]

    def list(self, **_kwargs):
        return list(self.devices)

    def get(self, device_id):
        return next(device for device in self.devices if device.id == device_id)

    def delete(self, device_id):
        self.devices = [device for device in self.devices if device.id != device_id]


def test_duplicate_template_clears_identity_and_keeps_device_configuration():
    source = Device(
        id=8,
        device_uuid="120b39cf-bb77-4789-a3a5-76a8630f7c65",
        name="MR-A",
        group_id=2,
        station="车库",
        primary_address="172.20.28.253",
        ssh_username="operator",
        ssh_password="secret",
        snmp_ro_community="readonly",
        tunnel1_host="10.1.1.1",
        remark="现场设备",
        created_at="2026-07-11T10:00:00",
        updated_at="2026-07-11T10:01:00",
    )

    duplicate = DeviceManagementPage._build_device_duplicate_template(source)

    assert duplicate.id is None
    assert duplicate.device_uuid is None
    assert duplicate.created_at is None
    assert duplicate.updated_at is None
    assert duplicate.name == "MR-A-副本"
    assert duplicate.group_id == 2
    assert duplicate.primary_address == "172.20.28.253"
    assert duplicate.ssh_username == "operator"
    assert duplicate.ssh_password == "secret"
    assert duplicate.snmp_ro_community == "readonly"
    assert duplicate.tunnel1_host == "10.1.1.1"
    assert duplicate.remark == "现场设备"


def test_duplicate_device_opens_add_dialog_with_template_values(monkeypatch):
    app()
    page = DeviceManagementPage(PageRepository(), I18n("en_US"))
    source = Device(
        id=1,
        device_uuid="120b39cf-bb77-4789-a3a5-76a8630f7c65",
        name="MR-A",
        group_id=None,
        station="Depot",
        primary_address="172.20.28.253",
        ssh_username="operator",
        ssh_password="secret",
        snmp_ro_community="readonly",
        tunnel1_host="10.1.1.1",
        remark="现场设备",
    )
    page.table.set_devices([source])
    monkeypatch.setattr(page, "_show_window", lambda _dialog: None)

    page.duplicate_device_by_id(1)

    dialog = page.dialog_registry.get_add_window()
    assert dialog is not None
    assert dialog.original is None
    assert dialog.windowTitle() == "Duplicate Device"
    duplicate = dialog.device()
    assert duplicate.id is None
    assert duplicate.device_uuid is None
    assert duplicate.name == "MR-A-副本"
    assert duplicate.station == "Depot"
    assert duplicate.primary_address == "172.20.28.253"
    assert duplicate.ssh_username == "operator"
    assert duplicate.ssh_password == "secret"
    assert duplicate.snmp_ro_community == "readonly"
    assert duplicate.tunnel1_host == "10.1.1.1"
    assert duplicate.remark == "现场设备"
    dialog.close()


def test_batch_delete_button_tracks_selected_device_ids(monkeypatch):
    app()
    monkeypatch.setattr(
        "netconsole.ui.pages.device_management_page.BackgroundProcessManager.start_job",
        lambda _manager, _job: "test-device-refresh",
    )
    repository = PageRepository()
    page = DeviceManagementPage(repository, I18n("en_US"))
    page.table.set_devices(repository.devices)

    assert page.batch_delete_button.isEnabled() is False

    page.table.item(0, CHECK_COLUMN).setCheckState(Qt.Checked)
    assert page.batch_delete_button.isEnabled() is True

    page.table.item(0, CHECK_COLUMN).setCheckState(Qt.Unchecked)
    assert page.batch_delete_button.isEnabled() is False


def test_toolbar_contains_device_details_button():
    app()
    page = DeviceManagementPage(PageRepository(), I18n("en_US"))

    assert page.detail_button.text() == "Device Details"


def test_toolbar_contains_test_connection_button():
    app()
    page = DeviceManagementPage(PageRepository(), I18n("en_US"))

    assert page.test_connection_button.text() == "Test Connection"


def test_toolbar_test_connection_without_selection_shows_select_first(monkeypatch):
    app()
    page = DeviceManagementPage(PageRepository(), I18n("en_US"))
    messages = []
    monkeypatch.setattr(
        "netconsole.ui.pages.device_management_page.MessageBox.information",
        lambda _parent, _title, text: messages.append(text),
    )

    page.test_selected_device_connection()

    assert messages == ["Select a device first."]


def test_toolbar_test_connection_with_multiple_devices_uses_batch(monkeypatch):
    app()
    page = DeviceManagementPage(PageRepository(), I18n("en_US"))
    captured = []
    monkeypatch.setattr(page, "batch_test_connections", lambda devices: captured.extend(devices))

    page.table.set_devices(page.repository.devices)
    page.table._set_all_checked(True)
    page.test_selected_device_connection()

    assert [device.name for device in captured] == ["A", "B"]


def test_batch_connection_dialog_removes_bottom_controls_and_uses_default_concurrency(monkeypatch):
    app()
    page = DeviceManagementPage(PageRepository(), I18n("en_US"))
    monkeypatch.setattr("netconsole.ui.pages.device_management_page.show_non_focus_window", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(BatchConnectionTestWorker, "start", lambda _worker: None)

    page.table.set_devices(page.repository.devices)
    page.table._set_all_checked(True)
    page.batch_test_connections(page.table.checked_devices())

    assert page.batch_connection_test_worker.max_workers == BATCH_CONNECTION_DEFAULT_CONCURRENCY
    assert not hasattr(page.batch_connection_test_dialog, "concurrency_combo")
    assert not hasattr(page.batch_connection_test_dialog, "copy_button")
    assert not hasattr(page.batch_connection_test_dialog, "close_button")
    page.batch_connection_test_dialog.close()


def test_top_toolbar_omits_edit_delete_and_contains_batch_refresh_details():
    app()
    page = DeviceManagementPage(PageRepository(), I18n("en_US"))
    top_buttons = [page.action_content.layout().itemAt(index).widget().text() for index in range(page.action_content.layout().count() - 1)]

    assert "Edit" not in top_buttons
    assert "Delete" not in top_buttons
    assert page.batch_refresh_details_button.text() == "Batch Refresh Details"
    assert page.external_terminal_button.text() == "External Terminal Config"
    assert top_buttons[:7] == [
        "Add",
        "Test Connection",
        "External Terminal Config",
        "Generate CRT Sessions",
        "Clear Selection",
        "Invert Selection",
        "Batch Delete",
    ]
    assert "Device Details" not in top_buttons
    assert "Refresh" not in top_buttons
    assert page.action_scroll.horizontalScrollBarPolicy() == Qt.ScrollBarAsNeeded
    assert page.selection_label.parent() is page


def test_external_terminal_settings_does_not_open_until_toolbar_button_clicked():
    application = app()
    page = DeviceManagementPage(PageRepository(), I18n("en_US"))
    application.processEvents()

    assert page.external_terminal_settings_dialog is None
    assert page.external_terminal_button.parent() is page.action_content
    assert page.external_terminal_button.isWindow() is False
    assert "External Terminal" not in [
        widget.windowTitle()
        for widget in application.topLevelWidgets()
        if widget is not page and widget.isVisible()
    ]

    page.external_terminal_button.click()

    assert page.external_terminal_settings_dialog is not None
    assert page.external_terminal_settings_dialog.parent() is page
    page.external_terminal_settings_dialog.close()


def test_row_external_terminal_without_config_only_prompts(monkeypatch):
    app()
    page = DeviceManagementPage(PageRepository(), I18n("en_US"))
    messages = []
    monkeypatch.setattr("netconsole.ui.pages.device_management_page.available_external_terminal_configs", lambda _settings: [])
    monkeypatch.setattr(
        "netconsole.ui.pages.device_management_page.MessageBox.information",
        lambda _parent, _title, text: messages.append(text),
    )

    page.table.set_devices(page.repository.devices)
    page.launch_external_terminal_for_device_id(1)

    assert messages == ["No external terminal path is configured. Click External Terminal Config first."]
    assert page.external_terminal_settings_dialog is None


def test_same_device_detail_window_is_created_once(monkeypatch):
    app()
    page = DeviceManagementPage(PageRepository(), I18n("en_US"))
    created = []

    class FakeDetail:
        def __init__(self, *args):
            created.append(self)

        def show(self):
            pass

        def raise_(self):
            pass

        def activateWindow(self):
            pass

        @property
        def destroyed(self):
            class Signal:
                def connect(self, _callback):
                    pass

            return Signal()

    monkeypatch.setattr("netconsole.ui.pages.device_management_page.DeviceDetailDialog", FakeDetail)
    monkeypatch.setattr("netconsole.ui.pages.device_management_page.window_manager.register_child_window", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("netconsole.ui.pages.device_management_page.show_non_focus_window", lambda *_args, **_kwargs: None)

    page.table.set_devices(page.repository.devices)
    page.show_device_detail(1)
    page.show_device_detail(1)

    assert len(created) == 1


def test_detail_window_removed_after_close_allows_recreate(monkeypatch):
    app()
    page = DeviceManagementPage(PageRepository(), I18n("en_US"))
    removed = []
    monkeypatch.setattr("netconsole.ui.pages.device_management_page.window_manager.unregister_child_window", lambda window: removed.append(window))
    dialog = object()
    page.detail_dialogs["device-1"] = dialog

    page._remove_detail_dialog("device-1", dialog)

    assert page.detail_dialogs == {}
    assert removed == [dialog]


def test_toolbar_detail_without_selection_shows_select_first(monkeypatch):
    app()
    page = DeviceManagementPage(PageRepository(), I18n("en_US"))
    messages = []
    monkeypatch.setattr(
        "netconsole.ui.pages.device_management_page.MessageBox.information",
        lambda _parent, _title, text: messages.append(text),
    )

    page.show_selected_device_detail()

    assert messages == ["Select a device first."]


def test_batch_refresh_details_without_selection_shows_select_first(monkeypatch):
    app()
    page = DeviceManagementPage(PageRepository(), I18n("en_US"))
    messages = []
    monkeypatch.setattr(
        "netconsole.ui.pages.device_management_page.MessageBox.information",
        lambda _parent, _title, text: messages.append(text),
    )

    page.batch_refresh_details()

    assert messages == ["Select a device first."]


def test_batch_refresh_details_uses_fixed_safe_concurrency_and_progress_dialog(monkeypatch):
    app()
    page = DeviceManagementPage(PageRepository(), I18n("en_US"))
    page.table.set_devices(page.repository.devices)
    page.table._set_all_checked(True)
    monkeypatch.setattr("netconsole.ui.pages.device_management_page.MessageBox.question", lambda *_args: QMessageBox.Yes)
    monkeypatch.setattr("netconsole.ui.pages.device_management_page.show_non_focus_window", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(BatchCollectWorker, "start", lambda _worker: None)

    page.batch_refresh_details()

    assert page.batch_collect_worker is not None
    assert page.batch_collect_worker.max_workers == BATCH_COLLECT_DEFAULT_CONCURRENCY == 20
    assert page.batch_collect_dialog is not None
    assert not hasattr(page.batch_collect_dialog, "concurrency_combo")
    assert page.batch_collect_dialog.table.columnCount() == 8
    assert page.batch_collect_dialog.table.cellWidget(0, 3) is not None


def test_device_detail_dialog_title_includes_device_name_and_empty_hint(tmp_path):
    app()
    database = Database(tmp_path / "devices.db")
    database.initialize()
    dialog = DeviceDetailDialog(
        I18n("en_US"),
        DeviceFactRepository(database),
        Device(name="Core", device_uuid="device-1"),
    )

    labels = [label.text() for label in dialog.findChildren(QLabel)]
    assert dialog.windowTitle() == "Device Details - Core"
    assert [dialog.tabs.tabText(index) for index in range(dialog.tabs.count())] == [
        "Overview",
        "Interfaces",
        "Optical Modules",
        "LLDP Neighbors",
        "Trackside AP Business",
    ]
    assert dialog.findChild(QScrollArea) is not None
    assert any("Demo data is generated only when the demo database is first created" in text for text in labels)


def test_device_detail_dialog_has_refresh_button(tmp_path):
    app()
    database = Database(tmp_path / "devices.db")
    database.initialize()
    dialog = DeviceDetailDialog(
        I18n("en_US"),
        DeviceFactRepository(database),
        Device(name="Core", device_uuid="device-1"),
    )

    assert dialog.refresh_button.text() == "Refresh"
    assert dialog.refresh_optical_button.text() == "Refresh Optical"
    assert "Copy Collect Log" not in [button.text() for button in dialog.findChildren(QPushButton)]
    assert "Export Collect Log" not in [button.text() for button in dialog.findChildren(QPushButton)]


def test_device_detail_dialog_inherits_dark_theme_without_local_white_background(tmp_path):
    qt_app = app()
    database = Database(tmp_path / "devices.db")
    database.initialize()

    apply_theme("dark")
    dialog = DeviceDetailDialog(
        I18n("en_US"),
        DeviceFactRepository(database),
        Device(name="Core", device_uuid="device-1"),
    )

    assert "QDialog" in qt_app.styleSheet()
    assert "background-color: #111827" in qt_app.styleSheet()
    assert dialog.styleSheet() == ""


def test_device_detail_overview_shows_device_mac_or_placeholder(tmp_path):
    app()
    database = Database(tmp_path / "devices.db")
    database.initialize()
    repository = DeviceFactRepository(database)

    with_mac = DeviceDetailDialog(I18n("en_US"), repository, Device(name="MR", device_uuid="device-1", mac_address="105e-ae3e-0700"))
    labels = [label.text() for label in with_mac.findChildren(QLabel)]
    assert "MAC" in labels
    assert "105e-ae3e-0700" in labels

    without_mac = DeviceDetailDialog(I18n("en_US"), repository, Device(name="MR", device_uuid="device-2"))
    labels = [label.text() for label in without_mac.findChildren(QLabel)]
    assert "MAC" in labels
    assert "-" in labels


def test_checkbox_global_style_removes_widget_focus_frame():
    qt_app = app()
    apply_theme("dark")
    stylesheet = qt_app.styleSheet()

    assert "QCheckBox {\n    background-color: transparent;\n    color: #e5e7eb;\n    border: none;\n    spacing: 0px;" in stylesheet
    assert "QCheckBox:focus {\n    border: none;\n    outline: none;" in stylesheet
    assert "QCheckBox::indicator {\n    width: 18px;" in stylesheet


def test_optical_status_labels_and_colors_are_mapped():
    i18n = I18n("zh_CN")

    assert i18n.t("optical.status.link_abnormal") == "\u94fe\u8def\u5f02\u5e38"
    assert i18n.t("optical.status.no_light") == "\u65e0\u5149"
    assert _BaseDeviceDetailDialog.optical_status_color("normal") == "#22c55e"
    assert _BaseDeviceDetailDialog.optical_status_color("warning") == "#fbbf24"
    assert _BaseDeviceDetailDialog.optical_status_color("alarm") == "#f87171"
    assert _BaseDeviceDetailDialog.optical_status_color("link_abnormal") == "#fb7185"
    assert _BaseDeviceDetailDialog.optical_status_color("no_light") == "#6b7280"
    assert _BaseDeviceDetailDialog.interface_row_status_color("link_abnormal") == "#fb7185"
    assert _BaseDeviceDetailDialog.interface_row_status_color("no_light") == "#6b7280"


def test_device_detail_tabs_include_color_notes_and_interface_color_follows_optical_status(tmp_path):
    app()
    database = Database(tmp_path / "devices.db")
    database.initialize()
    repository = DeviceFactRepository(database)
    device = Device(name="Core", device_uuid="device-1")
    repository.replace_device_interfaces(
        "device-1",
        [
            {
                "interface_name": "GigabitEthernet1/0/1",
                "link_status": "DOWN",
                "collected_at": "2026-06-16T00:00:00",
            }
        ],
    )
    repository.replace_optical_modules(
        "device-1",
        [
            {
                "interface_name": "GigabitEthernet1/0/1",
                "rx_power": "-9.71",
                "status": "link_abnormal",
                "collected_at": "2026-06-16T00:00:00",
            }
        ],
    )
    dialog = DeviceDetailDialog(I18n("en_US"), repository, device)

    labels = [label.text() for label in dialog.findChildren(QLabel)]
    assert any("Interface row color follows optical module status." in text for text in labels)
    assert any("Legend:" in text and "No light" in text for text in labels)
    interface_table = dialog.tabs.widget(1).findChild(QTableWidget)
    optical_table = dialog.tabs.widget(2).findChild(QTableWidget)
    assert interface_table.item(0, 0).background().color().name() == "#fb7185"
    assert interface_table.item(0, 0).foreground().color().name() == "#ffffff"
    assert optical_table.item(0, 0).text() == "GigabitEthernet1/0/1"
    assert optical_table.item(0, 1).text() == "Link Abnormal"


def test_device_detail_overview_fields_are_complete():
    assert [field for _label_key, field in OVERVIEW_FIELDS] == [
        "sysname",
        "model",
        "serial_number",
        "software_version",
        "bootrom_version",
        "vendor",
        "uptime",
        "collected_at",
    ]


def test_device_detail_interface_columns_are_complete():
    assert [field for _label_key, field in INTERFACE_COLUMNS] == [
        "interface_name",
        "link_status",
        "protocol_status",
        "speed",
        "duplex",
        "interface_type",
        "port_status",
        "pvid",
        "description",
        "ip_address",
        "mac_address",
        "vlan",
        "collected_at",
    ]


def test_device_detail_optical_module_columns_are_complete():
    assert [field for _label_key, field in OPTICAL_MODULE_COLUMNS] == [
        "interface_name",
        "status",
        "rx_power",
        "tx_power",
        "temperature",
        "voltage",
        "bias_current",
        "module_model",
        "module_serial_number",
        "module_vendor",
        "wavelength",
        "transmission_distance",
        "connector_type",
        "collected_at",
    ]
    assert "rx_low_alarm" not in [field for _label_key, field in OPTICAL_MODULE_COLUMNS]
    assert "rx_low_warning" not in [field for _label_key, field in OPTICAL_MODULE_COLUMNS]
    assert "rx_normal_line" not in [field for _label_key, field in OPTICAL_MODULE_COLUMNS]
    assert "rx_threshold_source" not in [field for _label_key, field in OPTICAL_MODULE_COLUMNS]


def test_device_detail_lldp_columns_are_complete():
    assert [field for _label_key, field in LLDP_COLUMNS] == [
        "local_interface",
        "neighbor_sysname",
        "neighbor_mac",
        "neighbor_interface",
        "collected_at",
    ]


def test_device_detail_long_interface_columns_have_minimum_widths():
    interface_widths = _column_min_widths(INTERFACE_COLUMNS)
    optical_widths = _column_min_widths(OPTICAL_MODULE_COLUMNS)
    lldp_widths = _column_min_widths(LLDP_COLUMNS)

    assert interface_widths[0] >= 180
    assert optical_widths[0] >= 180
    assert lldp_widths[0] >= 180
    assert lldp_widths[3] >= 180


def test_toolbar_edit_without_selection_shows_select_first(monkeypatch):
    app()
    page = DeviceManagementPage(PageRepository(), I18n("en_US"))
    messages = []
    monkeypatch.setattr(
        "netconsole.ui.pages.device_management_page.MessageBox.information",
        lambda _parent, _title, text: messages.append(text),
    )

    page.edit_device()

    assert messages == ["Select a device first."]


def test_toolbar_edit_with_multiple_checked_devices_shows_single_edit_message(monkeypatch):
    app()
    page = DeviceManagementPage(PageRepository(), I18n("en_US"))
    messages = []
    monkeypatch.setattr(
        "netconsole.ui.pages.device_management_page.MessageBox.information",
        lambda _parent, _title, text: messages.append(text),
    )

    page.table.set_devices(page.repository.devices)
    page.table._set_all_checked(True)
    page.edit_device()

    assert messages == ["Select one device to edit."]
