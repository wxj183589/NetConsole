from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from netconsole.core.paths import PathResolver
from netconsole.core.settings import SettingsStore
from netconsole.core.sites import Site
from netconsole.ui.pages.settings_page import SettingsPage


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _page(tmp_path: Path) -> tuple[SettingsPage, SettingsStore]:
    _app()
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path / "data")
    settings = SettingsStore(paths)
    site = Site("demo", paths.site_dir("demo"), paths.site_db_path("demo"))
    page = SettingsPage(settings, site, paths)
    page._show_success = lambda *_args: None
    return page, settings


def test_unimplemented_settings_are_disabled_and_identified(tmp_path: Path) -> None:
    page, _settings = _page(tmp_path)

    for control in (
        page.mica_switch,
        page.compact_table_switch,
        page.default_concurrency_spin,
        page.command_timeout_spin,
        page.log_retention_spin,
        page.raw_echo_log_switch,
        page.download_dir_edit,
        page.backup_dir_edit,
        page.report_dir_edit,
        page.mib_dir_edit,
    ):
        assert not control.isEnabled()
        assert "尚未接入运行逻辑" in control.toolTip()


def test_settings_save_only_persists_effective_controls(tmp_path: Path) -> None:
    page, settings = _page(tmp_path)
    settings.set_value("default_concurrency", 17)
    page.default_concurrency_spin.setValue(99)
    page.iperf3_path_edit.setText(r"C:\tools\iperf3.exe")

    page.save_settings()

    reloaded = SettingsStore(settings.paths)
    assert reloaded.get_value("default_concurrency") == 17
    assert reloaded.get_value("network_tools/iperf_path") == r"C:\tools\iperf3.exe"
