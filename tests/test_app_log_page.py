import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from netconsole.core import app_logger
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.ui.pages.app_log_page import AppLogPage


def app():
    return QApplication.instance() or QApplication([])


def write_logs(paths: PathResolver, count: int) -> None:
    paths.app_log_path.parent.mkdir(parents=True, exist_ok=True)
    with paths.app_log_path.open("w", encoding="utf-8") as file:
        for index in range(count):
            file.write(f"2026-06-18 10:00:00 | INFO | EVENT_{index:04d} | detail {index}\n")


def test_app_log_page_loads_first_page_only_by_default(tmp_path):
    app()
    paths = PathResolver(tmp_path)
    app_logger.configure_path_resolver(paths)
    write_logs(paths, 1000)

    page = AppLogPage(I18n("en_US"))

    assert page.page == 1
    assert page.page_size == 200
    assert page.table.rowCount() == 200
    assert page.pagination.state.total_items == 1000
    assert page.pagination.state.total_pages == 5
    assert page.table.item(0, 2).text() == "EVENT_0999"


def test_app_log_page_changes_page_and_page_size(tmp_path):
    app()
    paths = PathResolver(tmp_path)
    app_logger.configure_path_resolver(paths)
    write_logs(paths, 1200)
    page = AppLogPage(I18n("en_US"))

    page.set_page(2)
    assert page.page == 2
    assert page.table.rowCount() == 200
    assert page.table.item(0, 2).text() == "EVENT_0999"

    page.set_page_size(500)
    assert page.page == 1
    assert page.page_size == 500
    assert page.table.rowCount() == 500
    assert page.pagination.state.total_pages == 3


def test_app_log_page_filter_resets_to_first_page(tmp_path):
    app()
    paths = PathResolver(tmp_path)
    app_logger.configure_path_resolver(paths)
    write_logs(paths, 300)
    page = AppLogPage(I18n("en_US"))

    page.set_page(2)
    page.search_input.setText("EVENT_0001")

    assert page.page == 1
    assert page.table.rowCount() == 1
    assert page.table.item(0, 2).text() == "EVENT_0001"


def test_app_log_page_exports_current_page_only(tmp_path, monkeypatch):
    app()
    paths = PathResolver(tmp_path)
    app_logger.configure_path_resolver(paths)
    write_logs(paths, 300)
    export_path = tmp_path / "current_page.txt"
    monkeypatch.setattr(
        "netconsole.ui.export_path.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(export_path), "Text Files (*.txt)"),
    )
    page = AppLogPage(I18n("en_US"))

    page.set_page(2)
    page.export_current_page()

    exported_lines = export_path.read_text(encoding="utf-8").splitlines()
    assert len(exported_lines) == 100
    assert "EVENT_0099" in exported_lines[0]
    assert "EVENT_0299" not in "\n".join(exported_lines)
