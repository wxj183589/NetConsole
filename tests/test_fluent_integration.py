from pathlib import Path

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
    from netconsole.app import build_window
    from netconsole.ui.app_fluent_window import AppFluentWindow

    app()
    window = build_window()

    assert isinstance(window, AppFluentWindow)
    assert window.__class__.__name__ == "AppFluentWindow"
    assert window.stackedWidget.count() >= 3
    window.close()
