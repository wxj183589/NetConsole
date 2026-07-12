import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.ui.pages.app_log_page import AppLogPage


_PAGE_REFS: list[AppLogPage] = []


def app():
    return QApplication.instance() or QApplication([])


def write_logs(paths: PathResolver, count: int) -> None:
    paths.app_log_path.parent.mkdir(parents=True, exist_ok=True)
    with paths.app_log_path.open("w", encoding="utf-8") as file:
        for index in range(count):
            file.write(f"2026-06-18 10:00:00 | INFO | EVENT_{index:04d} | detail {index}\n")


def wait_until(predicate, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while not predicate() and time.time() < deadline:
        app().processEvents()
        time.sleep(0.01)
    assert predicate(), "异步日志加载未在超时前完成"


def test_app_log_page_loads_first_page_only_by_default(tmp_path):
    app()
    paths = PathResolver(tmp_path)
    write_logs(paths, 1000)

    page = AppLogPage(I18n("en_US"), paths=paths)
    _PAGE_REFS.append(page)
    wait_until(lambda: page.load_worker is None and page.table.rowCount() == 200)

    assert page.page == 1
    assert page.page_size == 200
    assert page.table.rowCount() == 200
    assert page.pagination.state.total_items == 1000
    assert page.pagination.state.total_pages == 5
    assert page.table.item(0, 2).text() == "未知事件：EVENT_0999"
    assert page.table.item(0, 2).toolTip() == "原始事件：EVENT_0999"


def test_app_log_page_changes_page_and_page_size(tmp_path):
    app()
    paths = PathResolver(tmp_path)
    write_logs(paths, 1200)
    page = AppLogPage(I18n("en_US"), paths=paths)
    _PAGE_REFS.append(page)
    wait_until(lambda: page.load_worker is None and page.table.rowCount() == 200)

    page.set_page(2)
    wait_until(lambda: page.load_worker is None and page.page == 2 and page.table.rowCount() == 200)
    assert page.page == 2
    assert page.table.rowCount() == 200
    assert page.table.item(0, 2).text() == "未知事件：EVENT_0999"

    page.set_page_size(500)
    wait_until(lambda: page.load_worker is None and page.page_size == 500 and page.table.rowCount() == 500)
    assert page.page == 1
    assert page.page_size == 500
    assert page.table.rowCount() == 500
    assert page.pagination.state.total_pages == 3


def test_app_log_page_filter_resets_to_first_page(tmp_path):
    app()
    paths = PathResolver(tmp_path)
    write_logs(paths, 300)
    page = AppLogPage(I18n("en_US"), paths=paths)
    _PAGE_REFS.append(page)
    wait_until(lambda: page.load_worker is None and page.table.rowCount() == 200)

    page.set_page(2)
    page.search_input.setText("EVENT_0001")
    wait_until(lambda: page.load_worker is None and page.table.rowCount() == 1)

    assert page.page == 1
    assert page.table.rowCount() == 1
    assert page.table.item(0, 2).text() == "未知事件：EVENT_0001"


def test_app_log_page_exports_current_page_only(tmp_path, monkeypatch):
    app()
    paths = PathResolver(tmp_path)
    write_logs(paths, 300)
    export_path = tmp_path / "current_page.txt"
    monkeypatch.setattr(
        "netconsole.ui.export_path.QFileDialog.getSaveFileName",
        lambda *args, **kwargs: (str(export_path), "Text Files (*.txt)"),
    )
    page = AppLogPage(I18n("en_US"), paths=paths)
    _PAGE_REFS.append(page)
    wait_until(lambda: page.load_worker is None and page.table.rowCount() == 200)

    page.set_page(2)
    wait_until(lambda: page.load_worker is None and page.page == 2 and page.table.rowCount() > 0)
    page.export_current_page()

    deadline = time.time() + 5
    while not export_path.exists() and time.time() < deadline:
        app().processEvents()
        time.sleep(0.01)
    wait_until(lambda: page.load_worker is None)

    assert export_path.exists(), "异步导出进程未在超时前生成文件"
    exported_lines = export_path.read_text(encoding="utf-8-sig").splitlines()
    assert 1 < len(exported_lines) <= page.page_size + 1
    assert exported_lines[0] == "时间,级别,事件,详情,原始事件,原始详情"
    assert "EVENT_0299" not in "\n".join(exported_lines)


def test_app_log_page_displays_chinese_event_level_and_detail(tmp_path):
    app()
    paths = PathResolver(tmp_path)
    paths.app_log_path.parent.mkdir(parents=True, exist_ok=True)
    paths.app_log_path.write_text(
        "2026-06-18 10:00:00 | INFO | ONLINE_MR_UI_STATE_RECONCILED | page=rail.raw_mesh_log_analysis phase=first_show.end elapsed_ms=48\n",
        encoding="utf-8",
    )

    page = AppLogPage(I18n("zh_CN"), paths=paths)
    _PAGE_REFS.append(page)
    wait_until(lambda: page.load_worker is None and page.table.rowCount() >= 1)
    target_row = next(
        row
        for row in range(page.table.rowCount())
        if page.table.item(row, 2).toolTip() == "原始事件：ONLINE_MR_UI_STATE_RECONCILED"
    )

    assert page.table.item(target_row, 1).text() == "信息"
    assert page.table.item(target_row, 2).text() == "车载MR在线采集状态同步"
    assert page.table.item(target_row, 3).text() == "页面=MR原始MESH日志分析 阶段=首次显示结束 耗时(ms)=48"
    assert "原始详情：page=rail.raw_mesh_log_analysis" in page.table.item(target_row, 3).toolTip()
