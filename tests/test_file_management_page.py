import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QHeaderView
from PySide6.QtCore import Qt

from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.services.file_transfer_service import RemoteDeviceFile
from netconsole.ui.navigation import Navigation
from netconsole.ui.pages.file_management_page import (
    FileManagementPage,
    format_speed,
    is_mesh_log_file,
    local_file_type,
    resolve_local_download_name,
    resolve_local_download_path,
)


def app():
    return QApplication.instance() or QApplication([])


def test_navigation_includes_file_management_page():
    app()
    navigation = Navigation(I18n("en_US"))

    page_ids = [navigation.item(index).data(256) for index in range(navigation.count())]
    labels = [navigation.item(index).text() for index in range(navigation.count())]

    assert page_ids == ["devices", "ac", "rail_transit", "wifi_survey", "config_collection", "file_management", "network_tools", "logs"]
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
    assert page.remote_table.columnWidth(0) == 40
    directory_item = page.remote_table.item(0, 0)
    assert directory_item.flags() & Qt.ItemIsUserCheckable == Qt.NoItemFlags
    assert page.download_button.isEnabled()
    assert page.download_button.text() == "Download Files (2)"

    page.clear_remote_selection()

    assert page.checked_remote_paths == set()
    assert not page.download_button.isEnabled()
    assert page.download_button.text() == "Download Files"


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
    assert reopened.remote_table.columnWidth(0) == 40
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
    assert page.queue_table.item(0, 2).text() == "flash:/meshlog.log"


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


def page_task(task_id, device, remote_file, local_path, status_key):
    from netconsole.ui.pages.file_management_page import TransferTask

    return TransferTask(task_id, f"batch-{task_id}", device, remote_file, local_path, int(remote_file.size or 0), status_key=status_key)
