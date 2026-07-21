from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.models.mesh_log_models import MeshMrProfile, dataclass_to_json_dict
from netconsole.repositories.mesh_catalog_repository import MeshCatalogRepository
from netconsole.repositories.mesh_mr_repository import MeshMrRepository
from netconsole.utils.natural_sort import natural_text_key


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

    def create_mr_profile(
        self,
        display_name: str,
        notes: str = "",
        linked_device_id: int | None = None,
        linked_device_uuid: str | None = None,
    ) -> MeshMrProfile:
        profile = self._create_mr_profile_identity(
            display_name,
            notes=notes,
            linked_device_id=linked_device_id,
            linked_device_uuid=linked_device_uuid,
        )
        MeshMrRepository(self.paths.mesh_mr_db_path(self.site_name, profile.safe_folder_name))
        return profile

    def _create_mr_profile_identity(
        self,
        display_name: str,
        *,
        notes: str = "",
        linked_device_id: int | None = None,
        linked_device_uuid: str | None = None,
    ) -> MeshMrProfile:
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
            relative_folder_path=f"files/rail_transit/mr_raw_mesh/{safe}",
            linked_device_id=linked_device_id,
            linked_device_uuid=str(linked_device_uuid or "").strip() or None,
            created_at=now,
            updated_at=now,
            notes=notes,
        )
        self.ensure_mr_dirs(profile)
        self.catalog.create_profile(profile)
        self.write_mr_json(profile)
        return profile

    def ensure_mr_profile_identity_for_device(self, device: Device) -> MeshMrProfile:
        """确保车载 MR 身份、目录与 catalog，不打开可重建的派生 SQLite。"""

        if device.id is None:
            raise ValueError("device id is required for MESH MR profile")
        device_uuid = str(device.device_uuid or "").strip() or None
        existing = self.catalog.get_by_linked_device_id(int(device.id)) or self.catalog.get_by_linked_device_uuid(device_uuid or "")
        if existing is not None:
            display_name = _device_display_name(device)
            if existing.display_name != display_name or existing.linked_device_id != int(device.id) or existing.linked_device_uuid != device_uuid:
                existing = _replace_profile_identity(existing, display_name, int(device.id), device_uuid)
                self.catalog.update_profile_identity(existing)
            self.ensure_mr_dirs(existing)
            self.write_mr_json(existing)
            return existing
        display_name = _device_display_name(device)
        by_name = self.catalog.get_by_display_name(display_name)
        if by_name is not None and by_name.linked_device_id in (None, 0):
            linked = _replace_profile_identity(by_name, display_name, int(device.id), device_uuid)
            self.catalog.update_profile_identity(linked)
            self.ensure_mr_dirs(linked)
            self.write_mr_json(linked)
            return linked
        if by_name is not None:
            display_name = self._unique_auto_profile_name(display_name, int(device.id))
        return self._create_mr_profile_identity(display_name, linked_device_id=int(device.id), linked_device_uuid=device_uuid)

    def ensure_mr_profile_for_device(self, device: Device) -> MeshMrProfile:
        profile = self.ensure_mr_profile_identity_for_device(device)
        MeshMrRepository(self.paths.mesh_mr_db_path(self.site_name, profile.safe_folder_name))
        return profile

    def ensure_mr_profile_for_asset(self, *, device_id: int, device_uuid: str, display_name: str) -> MeshMrProfile:
        return self.ensure_mr_profile_for_device(Device(id=device_id, device_uuid=device_uuid, name=display_name))

    def _unique_auto_profile_name(self, base_name: str, device_id: int) -> str:
        candidate = f"{base_name}-{device_id}"
        if self.catalog.get_by_display_name(candidate) is None:
            return candidate
        counter = 1
        while True:
            candidate = f"{base_name}-{device_id}-{counter}"
            if self.catalog.get_by_display_name(candidate) is None:
                return candidate
            counter += 1

    def sync_mr_profiles_from_devices(self, devices: list[Device]) -> list[MeshMrProfile]:
        profiles: list[MeshMrProfile] = []
        for device in sorted(devices, key=_vehicle_mr_device_sort_key):
            if device.id is None:
                continue
            profiles.append(self.ensure_mr_profile_identity_for_device(device))
        return profiles

    def ensure_mr_dirs(self, profile: MeshMrProfile) -> Path:
        root = self.paths.mesh_mr_root(self.site_name, profile.safe_folder_name)
        self.paths.mesh_mr_raw_dir(self.site_name, profile.safe_folder_name).mkdir(parents=True, exist_ok=True)
        self.paths.mesh_mr_parsed_dir(self.site_name, profile.safe_folder_name).mkdir(parents=True, exist_ok=True)
        self.paths.mesh_mr_export_dir(self.site_name, profile.safe_folder_name).mkdir(parents=True, exist_ok=True)
        return root

    def write_mr_json(self, profile: MeshMrProfile) -> None:
        root = self.ensure_mr_dirs(profile)
        data = {
            "mr_id": profile.mr_id,
            "display_name": profile.display_name,
            "safe_folder_name": profile.safe_folder_name,
            "linked_device_id": profile.linked_device_id,
            "linked_device_uuid": profile.linked_device_uuid,
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


def _device_display_name(device: Device) -> str:
    value = str(device.name or device.system_name or device.primary_address or device.device_uuid or "").strip()
    return value or f"MR-{device.id}"


def _replace_profile_identity(
    profile: MeshMrProfile,
    display_name: str,
    linked_device_id: int,
    linked_device_uuid: str | None,
) -> MeshMrProfile:
    return MeshMrProfile(
        mr_id=profile.mr_id,
        display_name=display_name,
        safe_folder_name=profile.safe_folder_name,
        relative_folder_path=profile.relative_folder_path,
        linked_device_id=linked_device_id,
        linked_device_uuid=linked_device_uuid,
        earliest_sample_time=profile.earliest_sample_time,
        latest_sample_time=profile.latest_sample_time,
        source_file_count=profile.source_file_count,
        sample_count=profile.sample_count,
        link_record_count=profile.link_record_count,
        session_count=profile.session_count,
        event_count=profile.event_count,
        last_import_at=profile.last_import_at,
        created_at=profile.created_at,
        updated_at=datetime.now(),
        notes=profile.notes,
    )


def _vehicle_mr_device_sort_key(device: Device) -> tuple[tuple[object, ...], tuple[object, ...], tuple[object, ...], int]:
    return (
        natural_text_key(device.name),
        natural_text_key(device.system_name),
        natural_text_key(device.primary_address),
        int(device.id or 0),
    )
