from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from netconsole.core.paths import PathResolver
from netconsole.models.mesh_log_models import MeshMrProfile, dataclass_to_json_dict
from netconsole.repositories.mesh_catalog_repository import MeshCatalogRepository
from netconsole.repositories.mesh_mr_repository import MeshMrRepository


INVALID_FOLDER_CHARS = re.compile(r'[\\/:*?"<>|]')


def safe_mr_folder_name(display_name: str) -> str:
    value = INVALID_FOLDER_CHARS.sub("_", display_name.strip())
    value = re.sub(r"\s+", " ", value).strip()
    return value or "MR"


class MeshStorageService:
    def __init__(self, site_name: str, paths: PathResolver) -> None:
        self.site_name = site_name
        self.paths = paths
        self.paths.ensure_site_dirs(site_name)
        self.catalog = MeshCatalogRepository(self.paths.mesh_catalog_path(site_name))

    def create_mr_profile(self, display_name: str, notes: str = "") -> MeshMrProfile:
        name = display_name.strip()
        if not name:
            raise ValueError("MR name cannot be empty")
        if self.catalog.get_by_display_name(name) is not None:
            raise ValueError(f"MR already exists: {name}")
        base_safe = safe_mr_folder_name(name)
        safe = base_safe
        suffix = 1
        while self.catalog.safe_folder_exists(safe) or self.paths.mesh_mr_root(self.site_name, safe).exists():
            safe = f"{base_safe}_{suffix}"
            suffix += 1
        now = datetime.now()
        profile = MeshMrProfile(
            mr_id=str(uuid4()),
            display_name=name,
            safe_folder_name=safe,
            relative_folder_path=f"rail_transit/mesh/{safe}",
            created_at=now,
            updated_at=now,
            notes=notes,
        )
        self.ensure_mr_dirs(profile)
        self.catalog.create_profile(profile)
        self.write_mr_json(profile)
        MeshMrRepository(self.paths.mesh_mr_db_path(self.site_name, profile.safe_folder_name))
        return profile

    def ensure_mr_dirs(self, profile: MeshMrProfile) -> Path:
        root = self.paths.mesh_mr_root(self.site_name, profile.safe_folder_name)
        self.paths.mesh_mr_raw_dir(self.site_name, profile.safe_folder_name).mkdir(parents=True, exist_ok=True)
        self.paths.mesh_mr_export_dir(self.site_name, profile.safe_folder_name).mkdir(parents=True, exist_ok=True)
        return root

    def write_mr_json(self, profile: MeshMrProfile) -> None:
        root = self.ensure_mr_dirs(profile)
        data = {
            "mr_id": profile.mr_id,
            "display_name": profile.display_name,
            "safe_folder_name": profile.safe_folder_name,
            "linked_device_id": profile.linked_device_id,
            "created_at": profile.created_at,
            "updated_at": profile.updated_at,
            "notes": profile.notes,
        }
        with (root / "mr.json").open("w", encoding="utf-8") as file:
            json.dump(dataclass_to_json_dict(data), file, ensure_ascii=False, indent=2)

    def mr_repository(self, profile: MeshMrProfile) -> MeshMrRepository:
        return MeshMrRepository(self.paths.mesh_mr_db_path(self.site_name, profile.safe_folder_name))

    def archive_raw_file(self, profile: MeshMrProfile, source_path: Path, sample_time: datetime | None) -> Path:
        raw_root = self.paths.mesh_mr_raw_dir(self.site_name, profile.safe_folder_name).resolve()
        resolved_source = source_path.resolve()
        try:
            if resolved_source.is_relative_to(raw_root):
                return resolved_source
        except AttributeError:
            if str(resolved_source).startswith(str(raw_root)):
                return resolved_source
        archive_time = sample_time or datetime.fromtimestamp(source_path.stat().st_mtime)
        target_dir = raw_root / f"{archive_time.year:04d}" / f"{archive_time.month:02d}"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = _unique_path(target_dir / source_path.name)
        temp = target.with_name(target.name + ".tmp")
        shutil.copy2(source_path, temp)
        temp.replace(target)
        return target

    def refresh_catalog_summary(self, profile: MeshMrProfile) -> None:
        repo = self.mr_repository(profile)
        self.catalog.update_summary(profile.mr_id, repo.summary())


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.name
    suffix = ""
    if path.name.endswith(".log.gz"):
        stem = path.name[:-7]
        suffix = ".log.gz"
    else:
        stem = path.stem
        suffix = path.suffix
    counter = 1
    while True:
        candidate = path.with_name(f"{stem}_{counter}{suffix}")
        if not candidate.exists():
            return candidate
        counter += 1
