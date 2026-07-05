import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from netconsole.core.bootstrap import create_demo_context
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.ui.main_window import MainWindow
from netconsole.ui.shell import AppFramelessMainWindow, AppTitleBar, apply_window_effect


def app():
    return QApplication.instance() or QApplication([])


def test_frameless_window_wraps_business_content():
    app()
    window = AppFramelessMainWindow()
    content = QLabel("content")

    window.setCentralWidget(content)

    assert window.contentWidget() is content
    assert window.title_bar is not None
    assert window.centralWidget().objectName() == "appShell"


def test_title_bar_updates_context_and_theme():
    app()
    title_bar = AppTitleBar()
    requested: list[str] = []
    title_bar.theme_requested.connect(requested.append)

    title_bar.set_context("默认局点", "采集中")
    title_bar.set_theme("dark")
    title_bar.theme_button.click()

    assert title_bar.site_label.text() == "当前局点：默认局点"
    assert title_bar.status_label.text() == "运行状态：采集中"
    assert requested == ["light"]


def test_window_effect_defaults_to_none():
    app()
    window = AppFramelessMainWindow()

    state = apply_window_effect(window)

    assert state.requested == "none"
    assert state.applied == "none"


def test_main_window_uses_shell_title_bar(tmp_path):
    app()
    context = create_demo_context(PathResolver(tmp_path))
    window = MainWindow(context.site, context.repository, I18n("zh_CN"), context.paths)

    assert window.contentWidget() is not None
    assert window.title_bar.site_label.text() == f"当前局点：{context.site.name}"
    assert "NetConsole" in window.title_bar.title_label.text()

    window._force_close = True
    window.close()
