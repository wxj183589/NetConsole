import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QHeaderView
from PySide6.QtCore import Qt

from netconsole.core.database import Database
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.repositories.device_group_repository import DeviceGroupRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.repositories.mesh_mr_repository import MeshMrRepository
from netconsole.services.mesh_storage_service import MeshStorageService
from netconsole.services.rail_transit.constants import VEHICLE_MR_GROUP_NAME
from netconsole.services.file_transfer_service import (
    FileTransferService,
    RemoteDeviceFile,
    build_sftp_enable_commands,
)
from netconsole.ui.navigation import Navigation
from netconsole.ui.pages.file_management_page import (
    FileManagementPage,
    format_speed,
    is_mesh_log_file,
    local_file_type,
    resolve_local_download_name,
    resolve_local_download_path,
)
from netconsole.ui.widgets.table_check_delegate import CheckBoxOnlyDelegate, is_checked_value


def app():
    return QApplication.instance() or QApplication([])


def test_navigation_includes_file_management_page():
    app()
    navigation = Navigation(I18n("en_US"))

    page_ids = [navigation.item(index).data(256) for index in range(navigation.count())]
    labels = [navigation.item(index).text() for index in range(navigation.count())]

    assert page_ids == [
        "devices",
        "ac",
        "rail_transit",
        "wifi_survey",
        "config_collection",
        "file_management",
        "snmp_center",
        "network_tools",
        "logs",
        "system_settings",
        "feature_flags",
    ]
    assert "file_management" in page_ids
    assert "File Management" in labels


def test_file_management_helpers_format_speed_and_types(tmp_path):
    archive = tmp_path / "diag.tar.gz"
    plain = tmp_path / "startup.cfg"

    assert local_file_type(archive) == "tar.gz"
    assert local_file_type(plain) == "cfg"
    assert format_speed(2048) == "2.0 KB/s"


def test_remote_table_checkboxes_only_select_files(tmp_path):
    app()
    page = FileManagementPage(FakeRepository(), I18n("en_US"), "demo", PathResolver(tmp_path))
    page.remote_files = [
        RemoteDeviceFile("diagfile", "flash:/diagfile/", None, "", "dir", is_dir=True, file_type="directory"),
        RemoteDeviceFile("a.bin", "flash:/a.bin", 10, "", "bin"),
        RemoteDeviceFile("b.zip", "flash:/b.zip", 20, "", "zip"),
    ]

    page.populate_remote_table()
    page.select_all_remote_files()

    assert page.checked_remote_paths == {"flash:/a.bin", "flash:/b.zip"}
    assert page.remote_table.horizontalHeaderItem(0).text() == ""
    assert page.remote_table.horizontalHeader().sectionResizeMode(0) == QHeaderView.Fixed
    assert page.remote_table.columnWidth(0) == 48
    assert isinstance(page.remote_table.itemDelegateForColumn(0), CheckBoxOnlyDelegate)
    directory_item = page.remote_table.item(0, 0)
    assert directory_item.flags() & Qt.ItemIsUserCheckable == Qt.NoItemFlags
    assert is_checked_value(page.remote_table.item(1, 0).checkState())
    assert is_checked_value(page.remote_table.item(2, 0).checkState())
    assert not page.download_button.isEnabled()
    assert page.download_button.text() == "Download Files (2)"
    page.sftp_service = FakeConnectedSftpService()
    page._sync_file_operation_buttons()
    assert page.download_button.isEnabled()

    page.clear_remote_selection()

    assert page.checked_remote_paths == set()
    assert not is_checked_value(page.remote_table.item(1, 0).checkState())
    assert not is_checked_value(page.remote_table.item(2, 0).checkState())
    assert not page.download_button.isEnabled()
    assert page.download_button.text() == "Download Files"


def test_file_management_panel_actions_are_contextual_and_textual(tmp_path):
    app()
    page = FileManagementPage(FakeRepository(), I18n("en_US"), "demo", PathResolver(tmp_path))

    assert not hasattr(page, "upload_button")
    assert [
        page.local_up_button.text(),
        page.local_refresh_button.text(),
        page.new_folder_button.text(),
        page.open_local_button.text(),
    ] == ["Up", "Refresh File List", "New Local Folder", "Open Local Folder"]
    assert [
        page.remote_up_button.text(),
        page.remote_refresh_button.text(),
        page.remote_select_all_button.text(),
        page.remote_clear_selection_button.text(),
        page.remote_mesh_logs_button.text(),
        page.download_button.text(),
        page.remote_new_folder_button.text(),
        page.remote_delete_button.text(),
    ] == [
        "Up",
        "Refresh File List",
        "Select All",
        "Clear Selection",
        "MESH Logs",
        "Download Files",
        "New Device Directory",
        "Delete Device Files",
    ]
    assert [
        page.open_download_dir_button.text(),
        page.clear_completed_button.text(),
        page.clear_failed_button.text(),
        page.cancel_selected_task_button.text(),
    ] == ["Open Download Directory", "Clear Completed", "Clear Failed", "Cancel Selected Task"]
    for button in (
        page.local_up_button,
        page.local_refresh_button,
        page.new_folder_button,
        page.open_local_button,
        page.remote_up_button,
        page.remote_refresh_button,
        page.remote_select_all_button,
        page.remote_clear_selection_button,
        page.remote_mesh_logs_button,
        page.download_button,
        page.remote_new_folder_button,
        page.remote_delete_button,
        page.open_download_dir_button,
        page.clear_completed_button,
        page.clear_failed_button,
        page.cancel_selected_task_button,
    ):
        assert button.text()
        assert button.toolTip() == button.text() or button.toolTip()


def test_file_management_remote_buttons_require_connection(tmp_path):
    app()
    page = FileManagementPage(FakeRepository(), I18n("en_US"), "demo", PathResolver(tmp_path))
    page.remote_files = [RemoteDeviceFile("a.bin", "flash:/a.bin", 10, "", "bin")]
    page.populate_remote_table()
    page.select_all_remote_files()

    assert not page.download_button.isEnabled()
    assert not page.remote_delete_button.isEnabled()
    assert not page.remote_new_folder_button.isEnabled()

    page.sftp_service = FakeConnectedSftpService()
    page._sync_file_operation_buttons()

    assert page.download_button.isEnabled()
    assert page.remote_delete_button.isEnabled()
    assert page.remote_new_folder_button.isEnabled()


def test_multi_file_download_uses_visible_table_order_and_skips_duplicates(tmp_path, monkeypatch):
    app()
    page = FileManagementPage(FakeRepository(), I18n("en_US"), "demo", PathResolver(tmp_path))
    monkeypatch.setattr(page, "start_next_download", lambda: None)
    page.connected_device = page.current_device()
    page.remote_files = [
        RemoteDeviceFile("b.zip", "flash:/b.zip", 20, "", "zip"),
        RemoteDeviceFile("a.bin", "flash:/a.bin", 10, "", "bin"),
    ]
    page.populate_remote_table()
    page.checked_remote_paths = {"flash:/a.bin", "flash:/b.zip"}
    page.remote_table.sortItems(1, Qt.AscendingOrder)

    page.download_selected()
    page.download_selected()

    assert [task.remote_file.name for task in page.tasks] == ["a.bin", "b.zip"]
    assert all(task.status_key == "file_management.status.queued" for task in page.tasks)


def test_select_column_header_does_not_toggle_or_sort(tmp_path):
    app()
    page = FileManagementPage(FakeRepository(), I18n("en_US"), "demo", PathResolver(tmp_path))
    page.remote_files = [
        RemoteDeviceFile("b.zip", "flash:/b.zip", 20, "", "zip"),
        RemoteDeviceFile("a.bin", "flash:/a.bin", 10, "", "bin"),
    ]
    page.populate_remote_table()

    page.remote_header_clicked(0)

    assert page.checked_remote_paths == set()
    assert [page.remote_file_for_table_row(row).name for row in range(page.remote_table.rowCount())] == ["b.zip", "a.bin"]


def test_file_table_column_widths_are_persisted(tmp_path):
    app()
    paths = PathResolver(tmp_path)
    page = FileManagementPage(FakeRepository(), I18n("en_US"), "demo", paths)
    page.local_table.setColumnWidth(0, 333)
    page.remote_table.setColumnWidth(1, 444)
    page.save_table_column_widths(page.local_table, "file_manager/local_table/column_widths")
    page.save_table_column_widths(page.remote_table, "file_manager/remote_table/column_widths")

    reopened = FileManagementPage(FakeRepository(), I18n("en_US"), "demo", paths)

    assert reopened.local_table.columnWidth(0) == 333
    assert reopened.remote_table.columnWidth(0) == 48
    assert reopened.remote_table.columnWidth(1) == 444


def test_remote_double_click_file_only_toggles_checkbox(tmp_path, monkeypatch):
    app()
    page = FileManagementPage(FakeRepository(), I18n("en_US"), "demo", PathResolver(tmp_path))
    called = []
    monkeypatch.setattr(page, "enqueue_downloads", lambda _files: called.append(True))
    page.remote_files = [RemoteDeviceFile("a.bin", "flash:/a.bin", 10, "", "bin")]
    page.populate_remote_table()

    page.remote_double_clicked(0, 1)

    assert page.checked_remote_paths == {"flash:/a.bin"}
    assert called == []


def test_local_double_click_file_uses_default_application(tmp_path, monkeypatch):
    import netconsole.ui.pages.file_management_page as page_module

    app()
    page = FileManagementPage(FakeRepository(), I18n("en_US"), "demo", PathResolver(tmp_path))
    local_file = page.local_path / "startup.cfg"
    local_file.parent.mkdir(parents=True, exist_ok=True)
    local_file.write_text("config", encoding="utf-8")
    opened = []
    monkeypatch.setattr(page_module.QDesktopServices, "openUrl", lambda url: opened.append(url.toLocalFile()) or True)

    page.refresh_local()
    page.local_double_clicked(0, 0)

    assert [Path(value) for value in opened] == [local_file.resolve()]


def test_retry_moves_failed_task_to_queue_tail(tmp_path, monkeypatch):
    app()
    page = FileManagementPage(FakeRepository(), I18n("en_US"), "demo", PathResolver(tmp_path))
    monkeypatch.setattr(page, "start_next_download", lambda: None)
    device = page.current_device()
    first = RemoteDeviceFile("a.bin", "flash:/a.bin", 10, "", "bin")
    second = RemoteDeviceFile("b.bin", "flash:/b.bin", 20, "", "bin")
    page.tasks = [
        page_task(1, device, first, page.local_path / "a.bin", "file_management.status.failed"),
        page_task(2, device, second, page.local_path / "b.bin", "file_management.status.queued"),
    ]

    page.retry_task(page.tasks[0])

    assert [task.remote_file.name for task in page.tasks] == ["a.bin", "b.bin", "a.bin"]
    assert page.tasks[-1].status_key == "file_management.status.queued"
    assert page.tasks[-1].batch_id != page.tasks[0].batch_id


def test_mesh_log_quick_select_only_selects_matching_files(tmp_path):
    app()
    page = FileManagementPage(FakeRepository(), I18n("en_US"), "demo", PathResolver(tmp_path))
    page.remote_files = [
        RemoteDeviceFile("2026_02_01_1meshlog.log.gz", "flash:/2026_02_01_1meshlog.log.gz", 1, "", "zip"),
        RemoteDeviceFile("2026_02_02_2meshlog.log.gz", "flash:/2026_02_02_2meshlog.log.gz", 1, "", "zip"),
        RemoteDeviceFile("meshlog.log", "flash:/meshlog.log", 1, "2026-02-03 15:51:49", "zip"),
        RemoteDeviceFile("othermeshlog.log.gz", "flash:/othermeshlog.log.gz", 1, "", "zip"),
        RemoteDeviceFile("defaultfile.zip", "flash:/defaultfile.zip", 1, "", "zip"),
        RemoteDeviceFile("diagfile", "flash:/diagfile/", None, "", "dir", is_dir=True),
    ]
    page.checked_remote_paths = {"flash:/defaultfile.zip"}
    page.populate_remote_table()

    page.select_mesh_logs()

    assert page.checked_remote_paths == {
        "flash:/2026_02_01_1meshlog.log.gz",
        "flash:/2026_02_02_2meshlog.log.gz",
        "flash:/meshlog.log",
    }
    assert page.download_button.text() == "Download Files (3)"


def test_mesh_log_matcher_is_basename_exact_for_activity_log():
    assert is_mesh_log_file("2026_02_01_1meshlog.log.gz")
    assert is_mesh_log_file("MESHLOG.LOG")
    assert not is_mesh_log_file("othermeshlog.log.gz")
    assert not is_mesh_log_file("2026_02_02_meshlog.log.gz")
    assert not is_mesh_log_file("meshlog.log.gz")
    assert not is_mesh_log_file("test_meshlog.log")


def test_meshlog_local_download_name_uses_modified_date():
    remote = RemoteDeviceFile("meshlog.log", "flash:/meshlog.log", 1, "2026-02-03 15:51:49", "zip")
    history = RemoteDeviceFile("2026_02_01_1meshlog.log.gz", "flash:/2026_02_01_1meshlog.log.gz", 1, "2026-02-03 15:51:49", "zip")
    ordinary = RemoteDeviceFile("startup.cfg", "flash:/startup.cfg", 1, "2026-02-03 15:51:49", "zip")

    assert resolve_local_download_name(remote, "无线控制器") == "无线控制器-2026_02_03-meshlog.log"
    assert resolve_local_download_name(history, "无线控制器") == "无线控制器-2026_02_01_1meshlog.log.gz"
    assert resolve_local_download_name(ordinary, "无线控制器") == "startup.cfg"
    assert resolve_local_download_name(remote, "控制中心/无线控制器") == "控制中心_无线控制器-2026_02_03-meshlog.log"


def test_meshlog_local_download_path_avoids_overwrite_with_expected_suffix(tmp_path):
    activity = RemoteDeviceFile("meshlog.log", "flash:/meshlog.log", 1, "2026-02-03 15:51:49", "zip")
    history = RemoteDeviceFile("2026_02_01_1meshlog.log.gz", "flash:/2026_02_01_1meshlog.log.gz", 1, "", "zip")
    (tmp_path / "无线控制器-2026_02_03-meshlog.log").write_text("old", encoding="utf-8")
    (tmp_path / "无线控制器-2026_02_01_1meshlog.log.gz").write_text("old", encoding="utf-8")

    assert resolve_local_download_path(tmp_path, activity, "无线控制器").name == "无线控制器-2026_02_03-meshlog_1.log"
    assert resolve_local_download_path(tmp_path, history, "无线控制器").name == "无线控制器-2026_02_01_1meshlog_1.log.gz"


def test_meshlog_queue_displays_final_local_filename(tmp_path, monkeypatch):
    app()
    page = FileManagementPage(FakeRepository(), I18n("en_US"), "demo", PathResolver(tmp_path))
    monkeypatch.setattr(page, "start_next_download", lambda: None)
    page.connected_device = page.current_device()
    remote = RemoteDeviceFile("meshlog.log", "flash:/meshlog.log", 1, "2026-02-03 15:51:49", "zip")
    page.remote_files = [remote]
    page.checked_remote_paths = {"flash:/meshlog.log"}
    page.populate_remote_table()

    page.download_selected()

    assert page.tasks[0].local_path.name == "AC-1-2026_02_03-meshlog.log"
    assert page.queue_table.item(0, 0).text() == "AC-1-2026_02_03-meshlog.log"


def test_file_management_device_search_combines_with_group_filter(tmp_path):
    app()
    database = Database(tmp_path / "devices.db")
    database.initialize()
    repository = DeviceRepository(database)
    groups = DeviceGroupRepository(database, "demo")
    onboard = groups.create(VEHICLE_MR_GROUP_NAME)
    station = groups.create("车站")
    first = repository.create(Device(name="MR2", primary_address="192.0.2.10", station="上行站", group_id=onboard.id, device_type="AC"))
    repository.create(Device(name="MR10", primary_address="192.0.2.11", station="下行站", group_id=onboard.id, device_type="AC"))
    repository.create(Device(name="SW1", primary_address="198.51.100.10", station="上行站", group_id=station.id, device_type="SW"))
    page = FileManagementPage(repository, I18n("zh_CN"), "demo", PathResolver(tmp_path))

    page.group_combo.setCurrentIndex(page.group_combo.findData(onboard.id))
    page.device_search_edit.setText("192.0.2.10")

    assert page.device_combo.count() == 1
    assert page.device_combo.currentData() == first.id


def test_file_management_mesh_logs_for_vehicle_mr_use_mesh_raw_dir(tmp_path):
    app()
    database = Database(tmp_path / "devices.db")
    database.initialize()
    repository = DeviceRepository(database)
    group = DeviceGroupRepository(database, "demo").create(VEHICLE_MR_GROUP_NAME)
    device = repository.create(Device(name="MR2", primary_address="192.0.2.10", group_id=group.id, device_type="MR"))
    paths = PathResolver(tmp_path)
    page = FileManagementPage(repository, I18n("zh_CN"), "demo", paths)
    remote = RemoteDeviceFile("meshlog.log", "flash:/meshlog.log", 1, "2026-06-29 12:00:00", "meshlog")

    target = page.download_directory_for_remote_file(remote, device)

    assert target == paths.mesh_mr_raw_dir("demo", "MR2")
    assert target.exists()


def test_file_management_downloaded_mesh_log_auto_imports_to_raw_mesh_analysis(tmp_path):
    qt_app = app()
    database = Database(tmp_path / "devices.db")
    database.initialize()
    repository = DeviceRepository(database)
    group = DeviceGroupRepository(database, "demo").create(VEHICLE_MR_GROUP_NAME)
    device = repository.create(Device(name="MR2", group_id=group.id, device_type="FAT-AP", ip_address="192.0.2.10"))
    paths = PathResolver(tmp_path)
    page = FileManagementPage(repository, I18n("zh_CN"), "demo", paths)
    profile = MeshStorageService("demo", paths).ensure_mr_profile_for_device(device)
    remote = RemoteDeviceFile("meshlog.log", "flash:/meshlog.log", 1, "2026-06-29 12:00:00", "meshlog")
    local_path = paths.mesh_mr_raw_dir("demo", profile.safe_folder_name) / "meshlog.log"
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_text("[1] 2025/12/03 10:12:33.000\n" + "[1] Active 30f5-277a-5a2f 2025/12/03 10:12:30 0d 00h 00m 03s 1 36/43 2%/4% 45%/47% 3/1 15/27 60/72060 88/105 0/5000 2/297 314/0 0/93 0/0 0/0 0/0" + "\n", encoding="utf-8")
    task = page_task(1, device, remote, local_path, "file_management.status.downloading")
    page.tasks = [task]

    page.on_download_completed(task)
    for _ in range(200):
        qt_app.processEvents()
        if not page.mesh_import_workers:
            break
        QTest.qWait(10)

    repo = MeshMrRepository(paths.mesh_mr_db_path("demo", profile.safe_folder_name))
    assert repo.list_source_files()
    assert repo.query_links(10, 0)[0] == 1
    assert task.status_key == "file_management.mesh_auto_import_done"


def test_file_management_non_vehicle_mr_keeps_normal_download_dir(tmp_path):
    app()
    database = Database(tmp_path / "devices.db")
    database.initialize()
    repository = DeviceRepository(database)
    group = DeviceGroupRepository(database, "demo").create("车站")
    device = repository.create(Device(name="SW1", primary_address="192.0.2.20", group_id=group.id, device_type="SW"))
    paths = PathResolver(tmp_path)
    page = FileManagementPage(repository, I18n("zh_CN"), "demo", paths)
    page.local_path = paths.device_file_download_dir("demo", "SW1")
    remote = RemoteDeviceFile("meshlog.log", "flash:/meshlog.log", 1, "2026-06-29 12:00:00", "meshlog")

    target = page.download_directory_for_remote_file(remote, device)

    assert target == paths.device_file_download_dir("demo", "SW1")


def test_meshlog_retry_does_not_duplicate_device_prefix(tmp_path, monkeypatch):
    app()
    page = FileManagementPage(FakeRepository(), I18n("en_US"), "demo", PathResolver(tmp_path))
    monkeypatch.setattr(page, "start_next_download", lambda: None)
    device = page.current_device()
    remote = RemoteDeviceFile("meshlog.log", "flash:/meshlog.log", 1, "2026-02-03 15:51:49", "zip")
    task = page_task(1, device, remote, page.local_path / "AC-1-2026_02_03-meshlog.log", "file_management.status.failed")
    page.tasks = [task]

    page.retry_task(task)

    assert page.tasks[-1].local_path.name == "AC-1-2026_02_03-meshlog.log"


def test_file_management_default_local_dir_uses_downloads_not_raw(tmp_path):
    app()
    page = FileManagementPage(FakeRepository(), I18n("en_US"), "demo", PathResolver(tmp_path))
    device = page.current_device()

    relative_path = page.default_local_dir(device).relative_to(page.paths.site_dir("demo")).as_posix()

    assert relative_path.startswith("files/file_manager/downloads/")
    assert "/raw/" not in f"/{relative_path}/"


def test_file_transfer_connect_falls_back_to_tunnel_and_enables_h3c_sftp(tmp_path, monkeypatch):
    import netconsole.services.file_transfer_service as service_module

    connect_hosts: list[str] = []
    shell_commands: list[str] = []
    closed: list[str] = []

    class FakeShell:
        def send(self, command):
            shell_commands.append(command.strip())

        def recv_ready(self):
            return False

        def close(self):
            closed.append("shell")

    class FakeSftp:
        def listdir_attr(self, path):
            if path == "flash:/":
                return []
            raise RuntimeError("missing root")

        def close(self):
            closed.append("sftp")

    class FakeSSHClient:
        open_count = 0

        def set_missing_host_key_policy(self, _policy):
            pass

        def connect(self, **kwargs):
            connect_hosts.append(str(kwargs["hostname"]))
            if kwargs["hostname"] != "127.0.0.1":
                raise RuntimeError("direct failed")

        def open_sftp(self):
            FakeSSHClient.open_count += 1
            if FakeSSHClient.open_count == 1:
                raise RuntimeError("sftp disabled")
            return FakeSftp()

        def invoke_shell(self):
            return FakeShell()

        def close(self):
            closed.append("client")

    class FakeTunnelSession:
        local_host = "127.0.0.1"
        local_port = 10022

        def close(self):
            closed.append("tunnel")

    monkeypatch.setitem(sys.modules, "paramiko", SimpleNamespace(SSHClient=FakeSSHClient, AutoAddPolicy=lambda: object()))
    monkeypatch.setattr(service_module.TunnelManager, "open_tunnel", lambda *_args: FakeTunnelSession())
    monkeypatch.setattr(service_module, "sleep", lambda _seconds: None)

    device = Device(
        id=1,
        name="MR",
        primary_address="10.0.0.1",
        backup_address="10.0.1.1",
        ssh_enabled=1,
        ssh_username="admin",
        ssh_password="secret",
        tunnel_enabled=1,
        tunnel1_enabled=1,
        tunnel1_host="jump1",
        tunnel1_username="jump",
    )
    service = FileTransferService("demo", PathResolver(tmp_path))

    root = service.connect(device)
    service.disconnect()

    assert root == "flash:/"
    assert connect_hosts == ["10.0.0.1", "10.0.1.1", "127.0.0.1", "127.0.0.1"]
    assert shell_commands == [
        "system-view",
        "sftp server enable",
        "ssh user admin service-type all authentication-type any",
        "return",
        "quit",
    ]
    assert "tunnel" in closed


def test_sftp_enable_command_builder_uses_vendor_and_username():
    assert build_sftp_enable_commands("H3C", "ops") == [
        "system-view",
        "sftp server enable",
        "ssh user ops service-type all authentication-type any",
        "return",
        "quit",
    ]
    assert build_sftp_enable_commands("Cisco", "ops") == []


def test_file_transfer_does_not_run_h3c_commands_for_unsupported_vendor_and_continues(tmp_path, monkeypatch):
    import netconsole.services.file_transfer_service as service_module

    connect_hosts: list[str] = []
    shell_commands: list[str] = []

    class FakeShell:
        def send(self, command):
            shell_commands.append(command.strip())

        def close(self):
            pass

    class FakeSftp:
        def listdir_attr(self, path):
            if path == "flash:/":
                return []
            raise RuntimeError("missing root")

        def close(self):
            pass

    class FakeSSHClient:
        def __init__(self):
            self.hostname = ""

        def set_missing_host_key_policy(self, _policy):
            pass

        def connect(self, **kwargs):
            self.hostname = str(kwargs["hostname"])
            connect_hosts.append(self.hostname)

        def open_sftp(self):
            if self.hostname == "10.0.0.1":
                raise RuntimeError("sftp subsystem disabled")
            return FakeSftp()

        def invoke_shell(self):
            return FakeShell()

        def close(self):
            pass

    monkeypatch.setitem(sys.modules, "paramiko", SimpleNamespace(SSHClient=FakeSSHClient, AutoAddPolicy=lambda: object()))

    device = Device(
        id=1,
        name="Cisco-SW",
        device_vendor="Cisco",
        primary_address="10.0.0.1",
        backup_address="10.0.1.1",
        ssh_enabled=1,
        ssh_username="ops",
        ssh_password="secret",
    )
    service = FileTransferService("demo", PathResolver(tmp_path))

    root = service.connect(device)
    service.disconnect()

    assert root == "flash:/"
    assert connect_hosts == ["10.0.0.1", "10.0.1.1"]
    assert shell_commands == []


def test_file_transfer_reconnects_before_enable_when_transport_is_inactive(tmp_path, monkeypatch):
    import netconsole.services.file_transfer_service as service_module

    connect_hosts: list[str] = []
    shell_commands: list[str] = []
    closed: list[str] = []
    invoked_on_clients: list[int] = []
    client_index = 0

    class FakeTransport:
        def __init__(self, active: bool):
            self.active = active

        def is_active(self):
            return self.active

    class FakeShell:
        def send(self, command):
            shell_commands.append(command.strip())

        def recv_ready(self):
            return False

        def close(self):
            closed.append("shell")

    class FakeSftp:
        def listdir_attr(self, path):
            if path == "flash:/":
                return []
            raise RuntimeError("missing root")

        def close(self):
            closed.append("sftp")

    class FakeSSHClient:
        def __init__(self):
            nonlocal client_index
            client_index += 1
            self.index = client_index

        def set_missing_host_key_policy(self, _policy):
            pass

        def connect(self, **kwargs):
            connect_hosts.append(str(kwargs["hostname"]))

        def get_transport(self):
            return FakeTransport(self.index != 1)

        def open_sftp(self):
            if self.index == 1:
                raise RuntimeError("SSH session not active")
            if self.index == 2:
                raise RuntimeError("sftp disabled")
            return FakeSftp()

        def invoke_shell(self):
            invoked_on_clients.append(self.index)
            return FakeShell()

        def close(self):
            closed.append(f"client-{self.index}")

    monkeypatch.setitem(sys.modules, "paramiko", SimpleNamespace(SSHClient=FakeSSHClient, AutoAddPolicy=lambda: object()))
    monkeypatch.setattr(service_module, "sleep", lambda _seconds: None)

    device = Device(
        id=1,
        name="H3C-SW",
        device_vendor="H3C",
        primary_address="10.0.0.1",
        ssh_enabled=1,
        ssh_username="admin",
        ssh_password="secret",
    )
    service = FileTransferService("demo", PathResolver(tmp_path))

    root = service.connect(device)
    service.disconnect()

    assert root == "flash:/"
    assert connect_hosts == ["10.0.0.1", "10.0.0.1", "10.0.0.1"]
    assert invoked_on_clients == [2]
    assert shell_commands == [
        "system-view",
        "sftp server enable",
        "ssh user admin service-type all authentication-type any",
        "return",
        "quit",
    ]


def test_file_transfer_reports_huawei_as_unsupported_without_session_not_active(tmp_path, monkeypatch):
    class FakeSSHClient:
        def set_missing_host_key_policy(self, _policy):
            pass

        def connect(self, **_kwargs):
            pass

        def get_transport(self):
            return SimpleNamespace(is_active=lambda: True)

        def open_sftp(self):
            raise RuntimeError("SSH session not active")

        def invoke_shell(self):
            raise AssertionError("unsupported vendor should not run shell commands")

        def close(self):
            pass

    monkeypatch.setitem(sys.modules, "paramiko", SimpleNamespace(SSHClient=FakeSSHClient, AutoAddPolicy=lambda: object()))
    device = Device(
        id=1,
        name="Huawei-SW",
        device_vendor="Huawei",
        primary_address="10.0.0.1",
        ssh_enabled=1,
        ssh_username="admin",
        ssh_password="secret",
    )
    service = FileTransferService("demo", PathResolver(tmp_path))

    with pytest.raises(RuntimeError) as excinfo:
        service.connect(device)

    message = str(excinfo.value)
    assert "vendor Huawei is not adapted" in message
    assert "SSH session not active" not in message


def test_file_transfer_service_creates_and_deletes_remote_entries(tmp_path):
    calls: list[tuple[str, str]] = []

    class FakeSftp:
        def mkdir(self, path):
            calls.append(("mkdir", path))

        def remove(self, path):
            calls.append(("remove", path))

        def rmdir(self, path):
            calls.append(("rmdir", path))

    service = FileTransferService("demo", PathResolver(tmp_path))
    service._sftp = FakeSftp()
    service._root_path = "flash:/"
    service._current_path = "flash:/diagfile"

    assert service.mkdir("logs") == "flash:/diagfile/logs"
    service.delete(RemoteDeviceFile("a.log", "a.log", 1, "", "log"))
    service.delete(RemoteDeviceFile("old", "old", None, "", "dir", is_dir=True))

    assert calls == [
        ("mkdir", "flash:/diagfile/logs"),
        ("remove", "flash:/diagfile/a.log"),
        ("rmdir", "flash:/diagfile/old"),
    ]


def test_sftp_connect_worker_emits_auto_enable_statuses(tmp_path, monkeypatch):
    import netconsole.ui.pages.file_management_page as page_module

    app()
    statuses: list[str] = []
    connected: list[tuple[object, str]] = []

    class FakeService:
        def __init__(self, site_name, paths):
            self.site_name = site_name
            self.paths = paths
            self.disconnected = False

        def connect(self, _device, progress_callback=None):
            for key in (
                "file_management.status.sftp_trying",
                "file_management.status.ssh_login_success",
                "file_management.status.sftp_enabling",
                "file_management.status.sftp_reconnecting",
            ):
                progress_callback(key)
            return "flash:/"

        def disconnect(self):
            self.disconnected = True

    monkeypatch.setattr(page_module, "FileTransferService", FakeService)
    worker = page_module.SftpConnectWorker("demo", Device(id=1, name="SW-A"), PathResolver(tmp_path))
    worker.status_changed.connect(statuses.append)
    worker.connected.connect(lambda service, root: connected.append((service, root)))

    worker.run()

    assert statuses == [
        "file_management.status.sftp_trying",
        "file_management.status.ssh_login_success",
        "file_management.status.sftp_enabling",
        "file_management.status.sftp_reconnecting",
    ]
    assert connected[0][1] == "flash:/"


def test_download_summary_counts_only_current_batch(tmp_path, monkeypatch):
    messages = []
    app()
    page = FileManagementPage(FakeRepository(), I18n("en_US"), "demo", PathResolver(tmp_path))
    monkeypatch.setattr(page, "start_next_download", lambda: None)
    monkeypatch.setattr("netconsole.ui.pages.file_management_page.QMessageBox.information", lambda _parent, title, message: messages.append((title, message)))
    page.connected_device = page.current_device()
    first_batch = [
        RemoteDeviceFile("a.bin", "flash:/a.bin", 10, "", "bin"),
        RemoteDeviceFile("b.bin", "flash:/b.bin", 10, "", "bin"),
        RemoteDeviceFile("c.bin", "flash:/c.bin", 10, "", "bin"),
    ]
    page.enqueue_downloads(first_batch)
    for task in page.tasks:
        page.on_download_completed(task)

    second_batch = [
        RemoteDeviceFile("d.bin", "flash:/d.bin", 10, "", "bin"),
        RemoteDeviceFile("e.bin", "flash:/e.bin", 10, "", "bin"),
        RemoteDeviceFile("f.bin", "flash:/f.bin", 10, "", "bin"),
    ]
    page.enqueue_downloads(second_batch)
    for task in page.tasks[-3:]:
        page.on_download_completed(task)

    assert len(page.tasks) == 6
    assert messages[-1] == ("Download Completed", "Downloads finished: 3 succeeded, 0 failed, 0 cancelled")


def test_download_summary_counts_failed_and_cancelled_in_batch(tmp_path, monkeypatch):
    messages = []
    app()
    page = FileManagementPage(FakeRepository(), I18n("en_US"), "demo", PathResolver(tmp_path))
    monkeypatch.setattr(page, "start_next_download", lambda: None)
    monkeypatch.setattr("netconsole.ui.pages.file_management_page.QMessageBox.information", lambda _parent, title, message: messages.append(message))
    page.connected_device = page.current_device()
    files = [
        RemoteDeviceFile("a.bin", "flash:/a.bin", 10, "", "bin"),
        RemoteDeviceFile("b.bin", "flash:/b.bin", 10, "", "bin"),
        RemoteDeviceFile("c.bin", "flash:/c.bin", 10, "", "bin"),
    ]
    page.enqueue_downloads(files)
    page.on_download_completed(page.tasks[0])
    page.on_download_failed(page.tasks[1], "boom")
    page.on_download_cancelled(page.tasks[2])

    assert messages == ["Downloads finished: 1 succeeded, 1 failed, 1 cancelled"]


def test_download_summary_is_shown_once_per_batch(tmp_path, monkeypatch):
    messages = []
    app()
    page = FileManagementPage(FakeRepository(), I18n("en_US"), "demo", PathResolver(tmp_path))
    monkeypatch.setattr(page, "start_next_download", lambda: None)
    monkeypatch.setattr("netconsole.ui.pages.file_management_page.QMessageBox.information", lambda _parent, _title, message: messages.append(message))
    page.connected_device = page.current_device()
    page.enqueue_downloads([RemoteDeviceFile("a.bin", "flash:/a.bin", 10, "", "bin")])

    page.on_download_completed(page.tasks[0])
    page.maybe_show_batch_summary(page.tasks[0].batch_id)
    page.refresh_queue()

    assert messages == ["Downloads finished: 1 succeeded, 0 failed, 0 cancelled"]


def test_retry_creates_new_single_task_batch_summary(tmp_path, monkeypatch):
    messages = []
    app()
    page = FileManagementPage(FakeRepository(), I18n("en_US"), "demo", PathResolver(tmp_path))
    monkeypatch.setattr(page, "start_next_download", lambda: None)
    monkeypatch.setattr("netconsole.ui.pages.file_management_page.QMessageBox.information", lambda _parent, _title, message: messages.append(message))
    device = page.current_device()
    old = page_task(1, device, RemoteDeviceFile("a.bin", "flash:/a.bin", 10, "", "bin"), page.local_path / "a.bin", "file_management.status.failed")
    page.tasks = [old]

    page.retry_task(old)
    page.on_download_completed(page.tasks[-1])

    assert messages == ["Downloads finished: 1 succeeded, 0 failed, 0 cancelled"]


class FakeRepository:
    def __init__(self) -> None:
        self.device = Device(id=1, device_uuid=Device.new_uuid(), name="AC-1", ip_address="192.0.2.1", device_type="AC")

    def list(self):
        return [self.device]

    def get(self, device_id):
        assert int(device_id) == 1
        return self.device


class FakeConnectedSftpService:
    root_path = "flash:/"
    current_path = "flash:/"

    def is_connected(self):
        return True


def page_task(task_id, device, remote_file, local_path, status_key):
    from netconsole.ui.pages.file_management_page import TransferTask

    return TransferTask(task_id, f"batch-{task_id}", device, remote_file, local_path, int(remote_file.size or 0), status_key=status_key)
