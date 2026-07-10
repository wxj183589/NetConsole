import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

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


def process_qt_until(predicate, *, timeout: float = 5.0) -> None:
    qt_app = app()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qt_app.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("等待 Qt 异步任务超时")


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
    assert isinstance(page.snapshot_table.itemDelegateForColumn(0), CheckBoxOnlyDelegate)

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
    process_qt_until(lambda: page.background_job_id is None)

    assert "运行中 ↔ 已保存" in page.diff_viewer.summary_label.text()
    rows = page.diff_viewer.table.rowCount()
    left_values = [page.diff_viewer.table.item(row, 1).text() for row in range(rows)]
    right_values = [page.diff_viewer.table.item(row, 4).text() for row in range(rows)]
    assert "sysname RUNNING" in left_values
    assert "sysname SAVED" in right_values


def test_config_diff_export_uses_text_file_source(tmp_path, monkeypatch):
    app()
    paths = PathResolver(tmp_path)
    db = Database(paths.site_db_path("demo"))
    db.initialize()
    repository = DeviceRepository(db)
    page = ConfigCollectionCenterPage(repository, I18n("zh_CN"), "demo", paths)
    diff_file = paths.runtime_cache_dir / "config_diff" / "diff.txt"
    diff_file.parent.mkdir(parents=True, exist_ok=True)
    diff_file.write_text("--- saved\n+++ running\n", encoding="utf-8")
    selected = tmp_path / "diff.diff"
    captured = {}

    page._set_current_diff(diff_file.read_text(encoding="utf-8"), diff_file)
    monkeypatch.setattr("netconsole.ui.pages.config_collection_center_page.QFileDialog.getSaveFileName", lambda *_args, **_kwargs: (str(selected), "Diff (*.diff)"))
    monkeypatch.setattr("netconsole.ui.pages.config_collection_center_page.submit_export_task", lambda _parent, spec, **_kwargs: captured.setdefault("spec", spec))

    page.export_current_diff()

    spec = captured["spec"]
    assert spec.task_type == "markdown_text"
    assert spec.payload["text_file"] == str(diff_file)
    assert "text" not in spec.payload


def test_snapshot_table_supports_checkbox_multi_select_without_device_selection_side_effects(tmp_path):
    app()
    paths = PathResolver(tmp_path)
    db = Database(paths.site_db_path("demo"))
    db.initialize()
    repository = DeviceRepository(db)
    device = repository.create(Device(name="SW01", primary_address="192.0.2.10", device_vendor="H3C"))
    page = ConfigCollectionCenterPage(repository, I18n("zh_CN"), "demo", paths)
    page.service._write_snapshot(device, "running", "20260618_101200", "#\nsysname RUNNING\n#\nreturn")
    page.service._write_snapshot(device, "saved", "20260618_101200", "#\nsysname SAVED\n#\nreturn")
    page.service._write_snapshot(device, "diff", "20260618_101200", "--- saved\n+++ running\n")

    page.refresh()

    assert page.snapshot_table.columnCount() == 4
    assert isinstance(page.snapshot_table.itemDelegateForColumn(0), CheckBoxOnlyDelegate)
    assert page.checked_device_ids == set()

    page._set_all_snapshots_checked(True)

    assert len(page.checked_snapshot_ids) == 3
    assert all(is_checked_value(page.snapshot_table.item(row, 0).checkState()) for row in range(page.snapshot_table.rowCount()))
    assert page.checked_device_ids == set()
    assert page.download_button.isEnabled()
    assert page.export_batch_button.isEnabled()
    assert not page.export_diff_button.isEnabled()
    assert page.delete_button.isEnabled()

    page._set_all_snapshots_checked(False)

    assert page.checked_snapshot_ids == set()
    assert not page.download_button.isEnabled()
    assert not page.export_batch_button.isEnabled()
    assert not page.export_diff_button.isEnabled()
    assert not page.delete_button.isEnabled()


def test_config_collection_left_panel_does_not_duplicate_main_actions(tmp_path):
    app()
    paths = PathResolver(tmp_path)
    db = Database(paths.site_db_path("demo"))
    db.initialize()
    repository = DeviceRepository(db)
    page = ConfigCollectionCenterPage(repository, I18n("zh_CN"), "demo", paths)

    left_buttons = [button.text() for button in page.left_panel.findChildren(QPushButton) if button.text()]

    for text in ("保存配置", "下载配置", "配置对比", "刷新"):
        assert text not in left_buttons
    for text in ("打开目录", "下载快照", "导出当前批次", "导出差异", "删除快照"):
        assert text in left_buttons
