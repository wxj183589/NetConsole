import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from netconsole.core.database import Database
from netconsole.core.i18n import I18n
from netconsole.core.paths import PathResolver
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.ui.pages.trackside_ap_service_page import TracksideApServicePage


def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def make_database(tmp_path):
    database = Database(tmp_path / "devices.db")
    database.initialize()
    return database


def test_trackside_ap_update_buttons_keep_original_update_as_light_update(tmp_path, monkeypatch):
    app()
    captured: dict[str, object] = {}

    class FakeCollectThread(QObject):
        stage_changed = Signal(str)
        progress_changed = Signal(int, int)
        collect_finished = Signal(object)
        collect_failed = Signal(str)
        finished = Signal()

        def __init__(self, repository, site_name, paths, trackside_rows, concurrency, parent=None):
            super().__init__(parent)
            captured["light_started_with_rows"] = trackside_rows

        def start(self):
            captured["light_started"] = True

        def cancel(self):
            captured["light_cancelled"] = True

    import netconsole.ui.pages.trackside_ap_service_page as page_module

    monkeypatch.setattr(page_module, "TracksideOpticalCollectThread", FakeCollectThread)
    page = TracksideApServicePage(DeviceRepository(make_database(tmp_path)), I18n("zh_CN"), "demo", PathResolver(tmp_path))
    page.trackside_rows = [{"site": "Station A", "device_name": "SW-1", "interface_name": "GigabitEthernet1/0/1"}]

    assert page.full_update_button.text() == "全量更新"
    assert page.update_button.text() == "轻量更新"
    assert "原轨旁AP业务更新逻辑" in page.update_button.toolTip()
    assert "仅刷新页面" not in page.update_button.toolTip()

    page.start_trackside_ap_light_update()

    assert captured["light_started"] is True
    assert captured["light_started_with_rows"] == page.trackside_rows


def test_trackside_ap_full_update_finishes_by_calling_light_update(tmp_path, monkeypatch):
    app()
    calls: list[str] = []

    class FakeFullResult:
        has_failures = False

        def summary_text(self):
            return "ok"

    class FakeFullUpdateThread(QObject):
        stage_changed = Signal(str)
        progress_changed = Signal(str)
        full_update_finished = Signal(object)
        full_update_failed = Signal(str)
        finished = Signal()

        def __init__(self, repository, site_name, paths, parent=None):
            super().__init__(parent)

        def start(self):
            calls.append("full")
            self.full_update_finished.emit(FakeFullResult())
            self.finished.emit()

        def cancel(self):
            calls.append("cancel_full")

    class FakeCollectThread(QObject):
        stage_changed = Signal(str)
        progress_changed = Signal(int, int)
        collect_finished = Signal(object)
        collect_failed = Signal(str)
        finished = Signal()

        def __init__(self, repository, site_name, paths, trackside_rows, concurrency, parent=None):
            super().__init__(parent)

        def start(self):
            calls.append("light")

        def cancel(self):
            calls.append("cancel_light")

    import netconsole.ui.pages.trackside_ap_service_page as page_module

    monkeypatch.setattr(page_module, "TracksideApFullUpdateThread", FakeFullUpdateThread)
    monkeypatch.setattr(page_module, "TracksideOpticalCollectThread", FakeCollectThread)
    page = TracksideApServicePage(DeviceRepository(make_database(tmp_path)), I18n("zh_CN"), "demo", PathResolver(tmp_path))
    monkeypatch.setattr(page, "refresh_async", lambda force=False: calls.append("refresh"))

    page.start_trackside_ap_full_update()

    assert calls == ["full", "light"]
