import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from netconsole.core.database import Database
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.repositories.config_snapshot_repository import ConfigSnapshot
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.ui.pages.config_collection_center_page import ConfigCollectionCenterPage
from netconsole.ui.widgets.table_check_delegate import CheckBoxOnlyDelegate, is_checked_value


def app():
    return QApplication.instance() or QApplication([])


def test_snapshot_download_default_filename_includes_device_name(tmp_path):
    app()
    paths = PathResolver(tmp_path)
    db = Database(paths.site_db_path("demo"))
    db.initialize()
    repository = DeviceRepository(db)
    device = repository.create(Device(name="SW/01", system_name="SYS01", primary_address="192.0.2.10", device_vendor="H3C"))
    page = ConfigCollectionCenterPage(repository, I18n("en_US"), "demo", paths)
    snapshot = ConfigSnapshot(
        None,
        device.id,
        str(device.device_uuid),
        "20260618_101200",
        "running",
        "files/config_center/snapshots/x/running/20260618_101200.txt",
        "",
    )

    assert page._snapshot_download_filename(snapshot, ".txt") == "SW_01_running_20260618_101200.txt"
    assert isinstance(page.device_table.itemDelegateForColumn(0), CheckBoxOnlyDelegate)

    page._set_all_checked(True)
    assert is_checked_value(page.device_table.item(0, 0).checkState())
    assert int(device.id) in page.checked_device_ids

    page._set_all_checked(False)
    assert not is_checked_value(page.device_table.item(0, 0).checkState())
    assert int(device.id) not in page.checked_device_ids


def test_config_collection_sidebar_can_collapse_and_expand(tmp_path):
    app()
    paths = PathResolver(tmp_path)
    db = Database(paths.site_db_path("demo"))
    db.initialize()
    repository = DeviceRepository(db)
    page = ConfigCollectionCenterPage(repository, I18n("zh_CN"), "demo", paths)
    page.splitter.setSizes([320, 680])

    page.toggle_sidebar()

    assert page._left_collapsed is True
    assert page.splitter.sizes()[0] == 0
    assert page.toggle_sidebar_button.text() == "展开左侧"

    page.toggle_sidebar()

    assert page._left_collapsed is False
    assert page.splitter.sizes()[0] >= 240
    assert page.toggle_sidebar_button.text() == "收起左侧"


def test_config_compare_tab_shows_running_on_left_and_saved_on_right(tmp_path):
    app()
    paths = PathResolver(tmp_path)
    db = Database(paths.site_db_path("demo"))
    db.initialize()
    repository = DeviceRepository(db)
    device = repository.create(Device(name="SW01", primary_address="192.0.2.10", device_vendor="H3C"))
    page = ConfigCollectionCenterPage(repository, I18n("zh_CN"), "demo", paths)
    page.service._write_snapshot(device, "running", "20260618_101200", "#\nsysname RUNNING\n#\nreturn")
    page.service._write_snapshot(device, "saved", "20260618_101200", "#\nsysname SAVED\n#\nreturn")

    page.compare_latest_snapshots()

    assert "运行中 ↔ 已保存" in page.diff_viewer.summary_label.text()
    rows = page.diff_viewer.table.rowCount()
    left_values = [page.diff_viewer.table.item(row, 1).text() for row in range(rows)]
    right_values = [page.diff_viewer.table.item(row, 4).text() for row in range(rows)]
    assert "sysname RUNNING" in left_values
    assert "sysname SAVED" in right_values
