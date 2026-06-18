from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from netconsole.core.bootstrap import create_demo_context
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.core.resources import changelog_path, icon_path
from netconsole.core.settings import SettingsStore
from netconsole.core.version import APP_AUTHOR, APP_VERSION, REPOSITORY_URLS
from netconsole.ui.dialogs.about_dialog import AboutRepositoryDialog
from netconsole.ui.dialogs.changelog_dialog import ChangelogDialog
from netconsole.ui.main_window import MainWindow
from netconsole.ui.theme import stylesheet_for_theme
from netconsole.ui.dialogs.device_detail_dialog import COLLECT_LOG_NOT_FOUND, CollectLogDialog, collect_search_matches, read_collect_log_text
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


def test_settings_store_persists_theme(tmp_path):
    paths = PathResolver(tmp_path)
    store = SettingsStore(paths)

    store.set_theme("dark")

    assert paths.settings_path.exists()
    assert SettingsStore(paths).theme == "dark"


def test_stylesheet_for_theme_switches_light_and_dark():
    assert "#f7f8fa" in stylesheet_for_theme("light")
    assert "#111827" in stylesheet_for_theme("dark")


def test_main_window_system_controls_persist_theme_and_show_version(tmp_path):
    qt_app = QApplication.instance() or QApplication([])
    context = create_demo_context(PathResolver(tmp_path))
    window = MainWindow(context.site, context.repository, I18n("en_US"), context.paths)

    window.set_theme("dark")

    assert SettingsStore(context.paths).theme == "dark"
    assert qt_app.styleSheet() == stylesheet_for_theme("dark")
    assert window.dark_theme_button.isChecked()
    assert window.findChild(QPushButton, "aboutRepositoryButton") is window.about_button
    assert window.findChild(QPushButton, "versionButton") is window.version_button
    assert APP_VERSION in window.windowTitle()
    assert window.version_button.text() == APP_VERSION
    window.show_changelog_dialog()
    assert isinstance(window.changelog_dialog, ChangelogDialog)
    assert "v1.0.0" in window.changelog_dialog.text.toPlainText()
    window.close()


def test_about_repository_dialog_copies_and_opens_links(monkeypatch):
    qt_app = QApplication.instance() or QApplication([])
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))
    dialog = AboutRepositoryDialog(I18n("en_US"))

    dialog.copy_link(REPOSITORY_URLS[0])
    open_buttons = [button for button in dialog.findChildren(QPushButton) if button.text() == "Open Browser"]
    open_buttons[0].click()

    assert qt_app.clipboard().text() == REPOSITORY_URLS[0]
    assert opened == [REPOSITORY_URLS[0]]
    assert APP_AUTHOR in " ".join(label.text() for label in dialog.findChildren(QLabel))
    dialog.close()


def test_release_resources_and_build_script_are_configured():
    root = Path(__file__).resolve().parents[1]
    script = (root / "build_release.bat").read_text(encoding="utf-8")

    assert icon_path("love.ico").exists()
    assert icon_path("love.png").exists()
    assert changelog_path().exists()
    assert "clean_build_spec.py --prepare --write-spec" in script
    assert "PyInstaller --noconfirm --distpath \"%DIST_ROOT%\" --workpath \"%BUILD_ROOT%\" \"%SPEC_ROOT%\\NetConsole.spec\"" in script
    assert "clean_build_spec.py --finalize" in script
    assert "--add-data" not in script
    assert "PROJECT_ROOT=%ROOT%\\project" in script
    assert "%RELEASE_ROOT%\\NetConsole_%APP_VERSION%.zip" in script


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


def test_collect_log_search_finds_single_and_multiple_results():
    assert collect_search_matches("display interface\nRX power", "RX power") == [(18, 8)]
    assert len(collect_search_matches("ERROR error Error", "error")) == 3
    assert collect_search_matches("Description: To_信号系统", "信号") == [(16, 2)]


def test_collect_log_dialog_search_count_highlight_and_ctrl_f():
    QApplication.instance() or QApplication([])
    dialog = CollectLogDialog("Log", "raw.log", "display interface\nERROR\nerror\nGigabitEthernet2/0/13")
    dialog.show()
    dialog.activateWindow()

    dialog.search_input.setText("error")

    assert dialog.count_label.text() == "1 / 2"
    assert len(dialog.text_edit.extraSelections()) == 2
    dialog.find_next()
    assert dialog.count_label.text() == "2 / 2"
    shortcut_keys = [shortcut.key().toString() for shortcut in dialog.findChildren(QShortcut)]
    assert QKeySequence("Ctrl+F").toString() in shortcut_keys
    dialog.focus_search()
    QApplication.processEvents()
    assert dialog.search_input.selectedText() == "error"
