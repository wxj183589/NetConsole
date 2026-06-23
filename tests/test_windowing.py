from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QSystemTrayIcon, QTextEdit, QWidget

from netconsole.core.bootstrap import create_demo_context
from netconsole.core import app_logger
from netconsole.core import version as version_info
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.core.resources import changelog_path, icon_path
from netconsole.core.settings import SettingsStore
from netconsole.core.version import APP_AUTHOR, APP_VERSION, REPOSITORY_URLS
from netconsole.ui.dialogs.about_dialog import AboutRepositoryDialog
from netconsole.ui.dialogs.changelog_dialog import ChangelogDialog
from netconsole.ui.main_window import MainWindow
from netconsole.ui.navigation import Navigation
from netconsole.ui.theme import stylesheet_for_theme
from netconsole.ui.dialogs.device_detail_dialog import COLLECT_LOG_NOT_FOUND, CollectLogDialog, collect_search_matches, read_collect_log_text
from netconsole.ui.table_utils import make_text_selectable
from netconsole.ui.widgets.loading_overlay import LoadingOverlay
from netconsole.ui.widgets.startup_splash import StartupSplash
from netconsole.ui.windowing import DeviceDialogRegistry, fit_default_window_size
from netconsole.utils.text_encoding import FILE_ENCODING_ERROR, clean_device_text, clean_h3c_device_text, decode_text_auto, fix_mojibake_text, read_text_auto


class FakeSignal:
    def __init__(self) -> None:
        self.callbacks = []

    def connect(self, callback) -> None:
        self.callbacks.append(callback)


class FakeTrayIcon:
    DoubleClick = QSystemTrayIcon.DoubleClick
    Information = QSystemTrayIcon.Information
    available = True
    instances = []

    def __init__(self, icon, parent=None) -> None:
        self.icon = icon
        self.parent = parent
        self.activated = FakeSignal()
        self.menu = None
        self.tooltip = ""
        self.visible = False
        self.messages = []
        FakeTrayIcon.instances.append(self)

    @staticmethod
    def isSystemTrayAvailable() -> bool:
        return FakeTrayIcon.available

    def setContextMenu(self, menu) -> None:
        self.menu = menu

    def setToolTip(self, tooltip: str) -> None:
        self.tooltip = tooltip

    def show(self) -> None:
        self.visible = True

    def showMessage(self, title, message, icon=None, msecs=0) -> None:
        self.messages.append((title, message, icon, msecs))


def install_fake_tray(monkeypatch, available: bool = True) -> type[FakeTrayIcon]:
    FakeTrayIcon.available = available
    FakeTrayIcon.instances = []
    monkeypatch.setattr("netconsole.ui.main_window.QSystemTrayIcon", FakeTrayIcon)
    return FakeTrayIcon


@pytest.fixture(autouse=True)
def fake_tray_by_default(monkeypatch):
    install_fake_tray(monkeypatch, False)


def test_main_window_size_uses_default_on_large_screen():
    size = fit_default_window_size(1920, 1080, 1600, 900)

    assert size.width == 1600
    assert size.height == 900


def test_window_size_does_not_exceed_ninety_percent_on_small_screen():
    size = fit_default_window_size(1366, 768, 1600, 900)

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

    assert store.theme == "dark"

    store.set_theme("light")

    assert paths.settings_path.exists()
    assert SettingsStore(paths).theme == "light"


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
    window.app_is_exiting = True
    window.close()


def test_main_window_sidebar_collapses_expands_and_preserves_selection(tmp_path):
    QApplication.instance() or QApplication([])
    context = create_demo_context(PathResolver(tmp_path))
    window = MainWindow(context.site, context.repository, I18n("en_US"), context.paths)
    ac_row = next(index for index in range(window.navigation.count()) if window.navigation.item(index).data(256) == "ac")
    window.navigation.setCurrentRow(ac_row)
    before_page = window.stack.currentWidget()

    assert not window.sidebar_collapsed
    assert window.left_panel.width() == Navigation.EXPANDED_WIDTH
    assert window.navigation.item(ac_row).textAlignment() == Qt.AlignCenter

    window.sidebar_toggle_button.click()

    assert window.sidebar_collapsed
    assert window.left_panel.width() == Navigation.COLLAPSED_WIDTH
    assert window.navigation.currentRow() == ac_row
    assert window.stack.currentWidget() is before_page
    assert window.navigation.item(ac_row).toolTip() == "AC Management"
    assert window.navigation.item(ac_row).text() == "AC"
    assert window.navigation.item(ac_row).textAlignment() == Qt.AlignCenter

    window.sidebar_toggle_button.click()

    assert not window.sidebar_collapsed
    assert window.left_panel.width() == Navigation.EXPANDED_WIDTH
    assert window.navigation.currentRow() == ac_row
    assert window.navigation.item(ac_row).text() == "AC Management"


def test_main_window_sidebar_state_persists_and_survives_theme_switch(tmp_path):
    QApplication.instance() or QApplication([])
    context = create_demo_context(PathResolver(tmp_path))
    first = MainWindow(context.site, context.repository, I18n("en_US"), context.paths)

    first.set_sidebar_collapsed(True)
    first.app_is_exiting = True
    first.close()

    reopened = MainWindow(context.site, context.repository, I18n("en_US"), context.paths)

    assert reopened.sidebar_collapsed
    assert reopened.left_panel.width() == Navigation.COLLAPSED_WIDTH
    reopened.set_theme("light")
    assert reopened.sidebar_collapsed
    assert reopened.left_panel.width() == Navigation.COLLAPSED_WIDTH


def test_main_window_collapsed_sidebar_keeps_data_disk_entry_clickable(tmp_path):
    QApplication.instance() or QApplication([])
    i18n = I18n("en_US")
    context = create_demo_context(PathResolver(tmp_path))
    window = MainWindow(context.site, context.repository, i18n, context.paths)
    clicked: list[bool] = []

    window.set_sidebar_collapsed(True)
    window.data_disk_button.clicked.disconnect()
    window.data_disk_button.clicked.connect(lambda: clicked.append(True))
    window.data_disk_button.click()

    assert window.data_disk_button.isEnabled()
    assert window.data_disk_button.toolTip() == i18n.t("data_disk.title")
    assert clicked == [True]


def test_main_window_starts_with_only_default_page(tmp_path):
    QApplication.instance() or QApplication([])
    context = create_demo_context(PathResolver(tmp_path))
    window = MainWindow(context.site, context.repository, I18n("en_US"), context.paths)

    assert set(window.pages) == {"devices"}
    assert window.rail_transit_page is None
    assert window.network_tools_page is None
    assert window.ac_page is None
    assert window.file_management_page is None
    assert window.config_collection_page is None
    assert window.log_page is None
    assert window.stack.count() == 1


def test_lazy_page_activation_runs_after_page_is_shown(tmp_path, monkeypatch):
    qt_app = QApplication.instance() or QApplication([])
    context = create_demo_context(PathResolver(tmp_path))
    window = MainWindow(context.site, context.repository, I18n("en_US"), context.paths)
    events: list[str] = []
    network_row = next(
        index for index in range(window.navigation.count()) if window.navigation.item(index).data(256) == "network_tools"
    )

    from netconsole.ui.pages.network_tools_page import NetworkToolsPage

    monkeypatch.setattr(NetworkToolsPage, "refresh_all", lambda self: events.append("refresh"))
    monkeypatch.setattr(window.stack, "setCurrentWidget", lambda widget: events.append("shown"))

    window.open_current_page(network_row)

    assert events == ["shown"]
    qt_app.processEvents()
    assert events == ["shown", "refresh"]


def test_loading_overlay_shows_and_hides():
    QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.resize(320, 200)
    overlay = LoadingOverlay(parent)

    overlay.show_loading("Loading rail transit data...")

    assert not overlay.isHidden()
    assert overlay.spinner.timer.isActive()
    assert overlay.message_label.text() == "Loading rail transit data..."

    overlay.hide_loading()

    assert not overlay.isVisible()
    assert not overlay.spinner.timer.isActive()


def test_startup_splash_updates_message_and_progress():
    QApplication.instance() or QApplication([])
    splash = StartupSplash(I18n("en_US"))

    splash.show_message("Opening main window...")
    splash.set_progress(80)

    assert splash.message_label.text() == "Opening main window..."
    assert splash.progress.value() == 80
    splash.close()


def test_startup_splash_uses_product_name_without_net_tools():
    QApplication.instance() or QApplication([])
    splash = StartupSplash(I18n("en_US"))
    texts = [label.text() for label in splash.findChildren(QLabel)]

    assert "NetConsole" in texts
    assert "Net Tools" not in texts
    assert all("Net Tools" not in text for text in texts)
    splash.close()


def test_startup_splash_version_label_is_localized():
    QApplication.instance() or QApplication([])
    zh_splash = StartupSplash(I18n("zh_CN"))
    en_splash = StartupSplash(I18n("en_US"))

    assert zh_splash.version_label.text() == f"版本：{version_info.APP_VERSION_DISPLAY}"
    assert en_splash.version_label.text() == f"Version: {version_info.APP_VERSION_DISPLAY}"
    zh_splash.close()
    en_splash.close()


def test_changelog_dialog_zh_uses_chinese_title_button_and_content():
    QApplication.instance() or QApplication([])
    dialog = ChangelogDialog(I18n("zh_CN"))

    assert dialog.windowTitle() == f"更新日志 {version_info.APP_VERSION_DISPLAY}"
    assert any(button.text() == "关闭" for button in dialog.findChildren(QPushButton))
    text_widgets = dialog.findChildren(QTextEdit)
    assert text_widgets
    content = text_widgets[0].toPlainText()
    assert "无线扫描" in content
    assert "车载MR在线收集" in content
    for forbidden in ("Onboard MR Online Collection", "Packaging", "Rail Transit", "Tests", "command construction", "output parsing"):
        assert forbidden not in content
    dialog.close()


def test_ui_version_text_uses_shared_version_source(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(version_info, "APP_NAME", "NetConsole")
    monkeypatch.setattr(version_info, "APP_VERSION", "v9.9.9")
    monkeypatch.setattr(version_info, "APP_VERSION_DISPLAY", "v9.9.9")
    context = create_demo_context(PathResolver(tmp_path))

    splash = StartupSplash(I18n("en_US"))
    window = MainWindow(context.site, context.repository, I18n("en_US"), context.paths)
    changelog = ChangelogDialog(I18n("en_US"))

    assert splash.version_label.text() == "Version: v9.9.9"
    assert window.windowTitle() == "NetConsole v9.9.9"
    assert window.version_button.text() == "v9.9.9"
    assert window.version_button.toolTip() == "NetConsole v9.9.9"
    assert changelog.windowTitle() == "Changelog v9.9.9"
    splash.close()
    changelog.close()
    window.app_is_exiting = True
    window.close()


def test_changelog_title_uses_localized_version():
    QApplication.instance() or QApplication([])
    zh_dialog = ChangelogDialog(I18n("zh_CN"))
    en_dialog = ChangelogDialog(I18n("en_US"))

    assert zh_dialog.windowTitle() == f"更新日志 {version_info.APP_VERSION_DISPLAY}"
    assert en_dialog.windowTitle() == f"Changelog {version_info.APP_VERSION_DISPLAY}"
    zh_dialog.close()
    en_dialog.close()


def test_ui_files_do_not_hardcode_release_version_or_net_tools():
    root = Path(__file__).resolve().parents[1]
    checked_files = [
        root / "netconsole" / "ui" / "widgets" / "startup_splash.py",
        root / "netconsole" / "ui" / "main_window.py",
        root / "netconsole" / "ui" / "dialogs" / "changelog_dialog.py",
        root / "netconsole" / "ui" / "dialogs" / "about_dialog.py",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in checked_files)

    assert "Net Tools" not in combined
    assert "v1.1.0" not in combined


def test_lazy_page_activation_errors_are_logged_not_raised(tmp_path, monkeypatch):
    qt_app = QApplication.instance() or QApplication([])
    context = create_demo_context(PathResolver(tmp_path))
    app_logger.configure_path_resolver(context.paths)
    app_logger.clear_logs()
    window = MainWindow(context.site, context.repository, I18n("en_US"), context.paths)
    log_row = next(index for index in range(window.navigation.count()) if window.navigation.item(index).data(256) == "logs")

    from netconsole.ui.pages.app_log_page import AppLogPage

    def fail_refresh(self) -> None:
        raise RuntimeError("background failed")

    monkeypatch.setattr(AppLogPage, "refresh", fail_refresh)

    window.open_current_page(log_row)
    qt_app.processEvents()

    assert any(item["event"] == "PAGE_ACTIVATE_FAILED:LOGS" for item in app_logger.read_logs())


def test_app_run_writes_startup_performance_logs(tmp_path, monkeypatch):
    import netconsole.app as app_module

    paths = PathResolver(tmp_path)
    paths.ensure_project_dirs()
    app_logger.configure_path_resolver(paths)
    app_logger.clear_logs()
    shown: list[bool] = []

    class FakeApplication:
        def __init__(self, argv):
            self.argv = argv

        def setApplicationName(self, name):
            pass

        def setApplicationVersion(self, version):
            pass

        def setWindowIcon(self, icon):
            pass

        def exec(self):
            return 0

    class FakeWindow:
        def show(self):
            shown.append(True)

    class FakeSplash:
        def __init__(self, i18n):
            self.messages = []

        def show_centered(self):
            pass

        def show_message(self, message):
            self.messages.append(message)

        def set_progress(self, value):
            pass

        def close_after_main_window_shown(self):
            pass

    class FakeSettingsStore:
        def __init__(self, paths):
            self.startup_mode = "preload_all"

    class FakePreloadManager:
        def __init__(self, i18n, splash, started_at):
            self.i18n = i18n
            self.splash = splash
            self.started_at = started_at

        def run(self, mode):
            assert mode == "preload_all"
            return FakeWindow()

    monkeypatch.setattr(app_module, "QApplication", FakeApplication)
    monkeypatch.setattr(app_module, "QIcon", lambda path: object())
    monkeypatch.setattr(app_module, "icon_path", lambda name: tmp_path / name)
    monkeypatch.setattr(app_module, "SettingsStore", FakeSettingsStore)
    monkeypatch.setattr(app_module, "StartupPreloadManager", FakePreloadManager)
    monkeypatch.setattr(app_module, "StartupSplash", FakeSplash)

    assert app_module.run() == 0

    logs = app_logger.read_logs()
    events = [item["event"] for item in reversed(logs)]
    assert events == ["APP_START", "STARTUP", "MAIN_WINDOW_CREATED", "MAIN_WINDOW_SHOWN"]
    assert shown == [True]
    assert all("elapsed_ms=" in item["detail"] for item in logs if item["event"] != "STARTUP")


def test_app_run_fast_start_uses_build_window(tmp_path, monkeypatch):
    import netconsole.app as app_module

    shown: list[str] = []

    class FakeApplication:
        def __init__(self, argv):
            pass

        def setApplicationName(self, name):
            pass

        def setApplicationVersion(self, version):
            pass

        def setWindowIcon(self, icon):
            pass

        def exec(self):
            return 0

    class FakeWindow:
        def show(self):
            shown.append("show")

    class FakeSplash:
        def __init__(self, i18n):
            pass

        def show_centered(self):
            pass

        def show_message(self, message):
            pass

        def set_progress(self, value):
            pass

        def close_after_main_window_shown(self):
            pass

    class FakeSettingsStore:
        def __init__(self, paths):
            self.startup_mode = "fast_start"

    built: list[bool] = []
    monkeypatch.setattr(app_module, "QApplication", FakeApplication)
    monkeypatch.setattr(app_module, "QIcon", lambda path: object())
    monkeypatch.setattr(app_module, "icon_path", lambda name: tmp_path / name)
    monkeypatch.setattr(app_module, "SettingsStore", FakeSettingsStore)
    monkeypatch.setattr(app_module, "build_window", lambda started_at: built.append(True) or FakeWindow())
    monkeypatch.setattr(app_module, "StartupSplash", FakeSplash)

    assert app_module.run() == 0

    assert built == [True]
    assert shown == ["show"]


def test_startup_preload_manager_preloads_main_pages(tmp_path, monkeypatch):
    from netconsole.ui import startup_preload as preload_module

    QApplication.instance() or QApplication([])
    context_path = PathResolver(tmp_path)

    class FakeSplash:
        def __init__(self):
            self.progress = []
            self.messages = []

        def show_message(self, message):
            self.messages.append(message)

        def set_progress(self, value):
            self.progress.append(value)

    monkeypatch.setattr(preload_module, "create_demo_context", lambda: create_demo_context(context_path))
    splash = FakeSplash()
    manager = preload_module.StartupPreloadManager(I18n("en_US"), splash)

    window = manager.run("preload_all")

    assert {"devices", "ac", "rail_transit", "config_collection", "file_management", "network_tools", "logs"}.issubset(window.pages)
    assert {"devices", "ac", "rail_transit", "config_collection", "file_management", "network_tools", "logs"}.issubset(window.preloaded_pages)
    assert splash.progress[-1] == 100

    rail_page = window.pages["rail_transit"]
    activated: list[tuple[str, bool]] = []
    monkeypatch.setattr(window, "activate_page", lambda page_id, **kwargs: activated.append((page_id, bool(kwargs.get("force_if_empty")))))
    rail_row = next(index for index in range(window.navigation.count()) if window.navigation.item(index).data(256) == "rail_transit")

    window.open_current_page(rail_row)
    QApplication.processEvents()

    assert window.pages["rail_transit"] is rail_page
    assert activated == [("rail_transit", True)]


def test_startup_preload_manager_continues_after_module_failure(monkeypatch):
    from netconsole.ui import startup_preload as preload_module

    class FakeSplash:
        def __init__(self):
            self.progress = []

        def show_message(self, message):
            pass

        def set_progress(self, value):
            self.progress.append(value)

    class FakeWindow:
        def __init__(self, *args, **kwargs):
            self.failures = {}

        def preload_page(self, page_id):
            if page_id == "rail_transit":
                raise RuntimeError("rail failed")

        def mark_preload_failures(self, failures):
            self.failures = failures

    monkeypatch.setattr(preload_module, "create_demo_context", lambda: create_demo_context(PathResolver()))
    monkeypatch.setattr(preload_module, "MainWindow", FakeWindow)
    splash = FakeSplash()
    manager = preload_module.StartupPreloadManager(I18n("en_US"), splash)

    window = manager.run("preload_all")

    assert window.failures["preload_rail_transit"] == "rail failed"
    assert splash.progress[-1] == 100


def test_close_event_cancel_keeps_window_open(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    context = create_demo_context(PathResolver(tmp_path))
    window = MainWindow(context.site, context.repository, I18n("en_US"), context.paths)
    monkeypatch.setattr(window, "ask_close_behavior", lambda has_tasks: "cancel")
    event = QCloseEvent()

    window.closeEvent(event)

    assert not event.isAccepted()


def test_close_event_minimizes_to_tray(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    fake_tray = install_fake_tray(monkeypatch, True)
    context = create_demo_context(PathResolver(tmp_path))
    window = MainWindow(context.site, context.repository, I18n("en_US"), context.paths)
    window.show()
    monkeypatch.setattr(window, "ask_close_behavior", lambda has_tasks: "minimize_to_tray")
    event = QCloseEvent()

    window.closeEvent(event)

    assert not event.isAccepted()
    assert not window.isVisible()
    assert window.tray_icon is not None
    assert fake_tray.instances[-1].messages


def test_close_event_exit_stops_background_tasks(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    context = create_demo_context(PathResolver(tmp_path))
    window = MainWindow(context.site, context.repository, I18n("en_US"), context.paths)
    stopped: list[bool] = []
    monkeypatch.setattr(window, "ask_close_behavior", lambda has_tasks: "exit")
    monkeypatch.setattr("netconsole.ui.main_window.background_task_manager.stop_all", lambda: stopped.append(True))
    event = QCloseEvent()

    window.closeEvent(event)

    assert event.isAccepted()
    assert stopped == [True]


def test_tray_double_click_shows_window(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    install_fake_tray(monkeypatch, True)
    context = create_demo_context(PathResolver(tmp_path))
    window = MainWindow(context.site, context.repository, I18n("en_US"), context.paths)
    shown: list[str] = []
    monkeypatch.setattr(window, "show_main_window", lambda: shown.append("show"))

    window.on_tray_activated(FakeTrayIcon.DoubleClick)

    assert shown == ["show"]


def test_tray_menu_contains_expected_actions(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    install_fake_tray(monkeypatch, True)
    context = create_demo_context(PathResolver(tmp_path))
    window = MainWindow(context.site, context.repository, I18n("en_US"), context.paths)

    action_texts = [action.text() for action in window.tray_menu.actions() if action.text()]

    assert action_texts == ["Show Window", "Hide to Tray", "Open Log Folder", "Stop All Background Tasks", "Exit"]


def test_tray_unavailable_close_dialog_has_no_minimize_option(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    install_fake_tray(monkeypatch, False)
    context = create_demo_context(PathResolver(tmp_path))
    window = MainWindow(context.site, context.repository, I18n("en_US"), context.paths)

    assert not window.tray_available
    assert window.tray_icon is None


def test_close_behavior_remember_choice_minimizes_next_time(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    install_fake_tray(monkeypatch, True)
    context = create_demo_context(PathResolver(tmp_path))
    window = MainWindow(context.site, context.repository, I18n("en_US"), context.paths)
    window.settings.set_close_behavior("minimize_to_tray")
    asked: list[bool] = []
    monkeypatch.setattr(window, "ask_close_behavior", lambda has_tasks: asked.append(True) or "cancel")
    event = QCloseEvent()

    window.closeEvent(event)

    assert asked == []
    assert not event.isAccepted()
    assert not window.isVisible()


def test_close_event_background_task_prompt_receives_task_state(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    context = create_demo_context(PathResolver(tmp_path))
    window = MainWindow(context.site, context.repository, I18n("en_US"), context.paths)
    seen: list[bool] = []
    monkeypatch.setattr(window, "has_background_tasks", lambda: True)
    monkeypatch.setattr(window, "ask_close_behavior", lambda has_tasks: seen.append(has_tasks) or "cancel")
    event = QCloseEvent()

    window.closeEvent(event)

    assert seen == [True]


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
    assert "PyInstaller --noconfirm --clean --distpath \"%DIST_ROOT%\" --workpath \"%BUILD_ROOT%\" \"%SPEC_ROOT%\\NetConsole.spec\"" in script
    assert "clean_build_spec.py --validate" in script
    assert "--finalize" not in script
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
