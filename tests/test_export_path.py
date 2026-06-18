from pathlib import Path

from netconsole.core.paths import PathResolver
from netconsole.core.settings import SettingsStore
from netconsole.ui import export_path


def test_export_path_defaults_to_qt_desktop(monkeypatch, tmp_path):
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    paths = PathResolver(tmp_path)
    monkeypatch.setattr(export_path.QStandardPaths, "writableLocation", lambda _location: str(desktop))

    assert export_path.default_export_dir(paths) == desktop
    assert export_path.make_default_export_path("report.xlsx", paths) == str(desktop / "report.xlsx")


def test_export_path_prefers_remembered_directory(monkeypatch, tmp_path):
    remembered = tmp_path / "exports"
    remembered.mkdir()
    paths = PathResolver(tmp_path)
    SettingsStore(paths).set_last_export_path(remembered)
    monkeypatch.setattr(export_path.QStandardPaths, "writableLocation", lambda _location: str(tmp_path / "Desktop"))

    assert export_path.default_export_dir(paths) == remembered


def test_select_export_path_uses_dialog_and_remembers_after_success(monkeypatch, tmp_path):
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    selected = tmp_path / "custom" / "devices.csv"
    selected.parent.mkdir()
    paths = PathResolver(tmp_path)
    captured = {}
    monkeypatch.setattr(export_path.QStandardPaths, "writableLocation", lambda _location: str(desktop))

    def fake_get_save_file_name(parent, title, default_path, file_filter):
        captured.update(parent=parent, title=title, default_path=default_path, file_filter=file_filter)
        return str(selected), file_filter

    monkeypatch.setattr(export_path.QFileDialog, "getSaveFileName", fake_get_save_file_name)

    result = export_path.select_export_path(None, "Export", "devices.csv", export_path.CSV_FILTER, paths)
    export_path.remember_export_path(result, paths)

    assert result == selected
    assert captured == {
        "parent": None,
        "title": "Export",
        "default_path": str(desktop / "devices.csv"),
        "file_filter": "CSV Files (*.csv)",
    }
    assert SettingsStore(paths).last_export_path == str(selected.parent)


def test_select_export_path_cancel_does_not_change_last_path(monkeypatch, tmp_path):
    paths = PathResolver(tmp_path)
    SettingsStore(paths).set_last_export_path(tmp_path)
    monkeypatch.setattr(export_path.QFileDialog, "getSaveFileName", lambda *_args: ("", ""))

    assert export_path.select_export_path(None, "Export", "report.xlsx", export_path.EXCEL_FILTER, paths) is None
    assert SettingsStore(paths).last_export_path == str(tmp_path)
