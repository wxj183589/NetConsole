from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel

from netconsole.ui.dialogs.device_detail_dialog import COLLECT_LOG_NOT_FOUND, read_collect_log_text
from netconsole.ui.table_utils import make_text_selectable
from netconsole.ui.windowing import DeviceDialogRegistry, fit_default_window_size
from netconsole.utils.text_encoding import FILE_ENCODING_ERROR, clean_device_text, clean_h3c_device_text, decode_text_auto, fix_mojibake_text, read_text_auto


def test_main_window_size_uses_default_on_large_screen():
    size = fit_default_window_size(1920, 1080, 1440, 900)

    assert size.width == 1440
    assert size.height == 900


def test_window_size_does_not_exceed_ninety_percent_on_small_screen():
    size = fit_default_window_size(1366, 768, 1440, 900)

    assert size.width == int(1366 * 0.9)
    assert size.height == int(768 * 0.9)


def test_device_dialog_registry_prevents_duplicate_keys_and_removes_on_close():
    registry = DeviceDialogRegistry()
    add_window = object()
    edit_window = object()
    replacement = object()

    registry.set_add_window(add_window)
    registry.set_edit_window("device-1", edit_window)
    registry.set_edit_window("device-1", replacement)

    assert registry.get_add_window() is add_window
    assert registry.get_edit_window("device-1") is replacement

    registry.remove_add_window(object())
    registry.remove_edit_window("device-1", edit_window)
    assert registry.get_add_window() is add_window
    assert registry.get_edit_window("device-1") is replacement

    registry.remove_add_window(add_window)
    registry.remove_edit_window("device-1", replacement)
    assert registry.get_add_window() is None
    assert registry.get_edit_window("device-1") is None


def test_device_dialog_and_page_do_not_use_exec_for_add_edit_windows():
    root = Path(__file__).resolve().parents[1]

    for relative_path in (
        "netconsole/ui/pages/device_management_page.py",
        "netconsole/ui/dialogs/device_dialog.py",
    ):
        source = (root / relative_path).read_text(encoding="utf-8")
        assert ".exec(" not in source
        assert ".exec()" not in source


def test_make_text_selectable_sets_mouse_selection_flag():
    QApplication.instance() or QApplication([])
    label = make_text_selectable(QLabel("copy me"))

    assert label.textInteractionFlags() & Qt.TextSelectableByMouse


def test_read_collect_log_text_reads_existing_file(tmp_path):
    raw_log = tmp_path / "collect.log"
    raw_log.write_text("display version\noutput", encoding="utf-8")

    path, text = read_collect_log_text(str(raw_log))

    assert path == raw_log
    assert text == "display version\noutput"


def test_read_collect_log_text_resolves_relative_path_from_site_root(tmp_path):
    raw_log = tmp_path / "raw" / "collect" / "run-1" / "device.log"
    raw_log.parent.mkdir(parents=True)
    raw_log.write_text("raw output", encoding="utf-8")

    path, text = read_collect_log_text("raw/collect/run-1/device.log", tmp_path)

    assert path == raw_log
    assert text == "raw output"


def test_read_collect_log_text_supports_gbk_and_gb2312(tmp_path):
    gbk_log = tmp_path / "gbk.log"
    gb2312_log = tmp_path / "gb2312.log"
    gbk_log.write_bytes("中文采集日志".encode("gbk"))
    gb2312_log.write_bytes("中文日志".encode("gb2312"))

    assert read_collect_log_text(str(gbk_log))[1] == "中文采集日志"
    assert read_collect_log_text(str(gb2312_log))[1] == "中文日志"
    assert decode_text_auto("端口描述".encode("gbk")) == "端口描述"
    assert read_text_auto(gb2312_log) == "中文日志"
    assert fix_mojibake_text("正常中文端口描述") == "正常中文端口描述"
    assert "悴" not in clean_device_text("To_悴ハ低?")
    assert clean_h3c_device_text("正常中文端口描述") == "正常中文端口描述"
    assert "悴" not in clean_h3c_device_text("To_悴ハ低?")


def test_read_collect_log_text_encoding_failure_uses_friendly_error(tmp_path):
    raw_log = tmp_path / "bad.log"
    raw_log.write_bytes(b"\xff\xff\xff")

    with pytest.raises(ValueError) as exc_info:
        read_collect_log_text(str(raw_log))

    assert str(exc_info.value) == FILE_ENCODING_ERROR
    assert "codec" not in str(exc_info.value).lower()


def test_read_collect_log_text_missing_file_uses_friendly_error(tmp_path):
    with pytest.raises(FileNotFoundError) as exc_info:
        read_collect_log_text(str(tmp_path / "missing.log"))

    assert str(exc_info.value) == COLLECT_LOG_NOT_FOUND
