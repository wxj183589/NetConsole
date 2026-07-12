from __future__ import annotations

from pathlib import Path

from netconsole.core.paths import PathResolver
from netconsole.core.settings import SettingsStore


LAST_VEHICLE_MR_DOWNLOAD_DIR = "last_vehicle_mr_download_dir"
LAST_VEHICLE_MR_DOWNLOAD_PARENT_DIR = "last_vehicle_mr_download_parent_dir"
LAST_MESH_IMPORT_DIR = "last_mesh_import_dir"


class PathPreferenceService:
    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths
        self.settings = SettingsStore(paths)

    def set_last_vehicle_mr_download_dir(self, path: str | Path) -> None:
        directory = Path(path)
        if directory.is_file() or directory.suffix:
            directory = directory.parent
        directory = directory.resolve()
        parent = directory.parent if directory.name else directory
        self.settings.set_value(LAST_VEHICLE_MR_DOWNLOAD_DIR, str(directory))
        self.settings.set_value(LAST_VEHICLE_MR_DOWNLOAD_PARENT_DIR, str(parent))

    def remember_last_mesh_import_dir(self, path: str | Path) -> None:
        directory = Path(path)
        if directory.is_file() or directory.suffix:
            directory = directory.parent
        try:
            directory = directory.expanduser().resolve()
        except OSError:
            return
        if directory.exists() and directory.is_dir():
            self.settings.set_value(LAST_MESH_IMPORT_DIR, str(directory))

    def record_download_if_vehicle_mr(self, local_path: str | Path, remote_name: str = "") -> bool:
        path = Path(local_path)
        text = f"{path} {remote_name}".casefold()
        suffixes = "".join(path.suffixes).casefold()
        is_candidate = (
            "online_mr" in text
            or "车载mr" in text
            or "mr" in text
            or "meshlog" in text
            or "mesh" in text
            or suffixes in {".log", ".gz", ".tar.gz"}
        )
        if not is_candidate:
            return False
        self.set_last_vehicle_mr_download_dir(path.parent if path.suffix else path)
        return True

    def get_last_vehicle_mr_import_start_dir(self, site_name: str) -> Path:
        return self.get_default_mesh_import_dir(site_name)

    def get_default_mesh_import_dir(self, site_name: str) -> Path:
        site_downloads = self.paths.file_downloads_root(site_name)
        site_downloads.mkdir(parents=True, exist_ok=True)
        candidates: list[Path] = []
        candidates.append(site_downloads)
        last_import = self.settings.get_value(LAST_MESH_IMPORT_DIR, "")
        parent = self.settings.get_value(LAST_VEHICLE_MR_DOWNLOAD_PARENT_DIR, "")
        last = self.settings.get_value(LAST_VEHICLE_MR_DOWNLOAD_DIR, "")
        if last_import:
            candidates.append(Path(str(last_import)))
        if parent:
            candidates.append(Path(str(parent)))
        if last:
            candidates.append(Path(str(last)).parent)
        candidates.extend(
            [
                self.paths.site_dir(site_name),
                Path.home() / "Desktop",
                self.paths.app_root,
            ]
        )
        for candidate in candidates:
            try:
                resolved = candidate.expanduser().resolve()
            except OSError:
                continue
            if resolved.exists() and resolved.is_dir():
                return resolved
        return self.paths.app_root
