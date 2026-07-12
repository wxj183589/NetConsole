from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QFileDialog, QWidget

from netconsole.core.paths import PathResolver
from netconsole.core.settings import SettingsStore


EXCEL_FILTER = "Excel Files (*.xlsx)"
CSV_FILTER = "CSV Files (*.csv)"


def default_export_dir(paths: PathResolver | None = None) -> Path:
    settings = SettingsStore(paths or PathResolver())
    remembered = _usable_export_dir(settings.last_export_path)
    if remembered is not None:
        return remembered
    desktop = QStandardPaths.writableLocation(QStandardPaths.DesktopLocation)
    if desktop:
        return Path(desktop)
    return Path.home()


def make_default_export_path(filename: str, paths: PathResolver | None = None) -> str:
    return str(default_export_dir(paths) / filename)


def select_export_path(
    parent: QWidget,
    title: str,
    filename: str,
    file_filter: str,
    paths: PathResolver | None = None,
) -> Path | None:
    selected, _ = QFileDialog.getSaveFileName(parent, title, make_default_export_path(filename, paths), file_filter)
    return Path(selected) if selected else None


def remember_export_path(path: str | Path, paths: PathResolver | None = None) -> None:
    export_path = Path(path)
    directory = export_path if export_path.is_dir() else export_path.parent
    SettingsStore(paths or PathResolver()).set_last_export_path(directory)


def _usable_export_dir(value: str) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    if path.is_file():
        path = path.parent
    return path if path.exists() and path.is_dir() else None
