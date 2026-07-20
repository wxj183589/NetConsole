from __future__ import annotations

import argparse
import gc
import hashlib
import json
import shutil
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from netconsole.core.paths import PathResolver
from netconsole.core.runtime_environment import data_root as default_data_root
from netconsole.models.mesh_log_models import MeshMrProfile
from netconsole.repositories.mesh_mr_repository import SCHEMA_VERSION
from netconsole.services.mesh_import_service import MeshImportService
from netconsole.services.mesh_storage_service import MeshStorageService


@dataclass(frozen=True)
class MeshRebuildEntry:
    mr_id: str
    display_name: str
    safe_folder_name: str
    source_schema: str
    target_schema: str
    raw_file_count: int
    raw_sha256: dict[str, str]
    action: str
    detail: str = ""


def build_plan(paths: PathResolver, site_name: str, mr_ids: set[str] | None = None) -> list[MeshRebuildEntry]:
    site_root = paths.site_dir(site_name).resolve()
    _require_inside(site_root, paths.sites_dir.resolve(), "site root")
    entries: list[MeshRebuildEntry] = []
    for profile in _load_profiles_readonly(paths.mesh_catalog_path(site_name)):
        if mr_ids and profile.mr_id not in mr_ids:
            continue
        profile_root = paths.mesh_mr_root(site_name, profile.safe_folder_name).resolve()
        _require_inside(profile_root, paths.site_mesh_root(site_name).resolve(), "profile root")
        raw_root = paths.mesh_mr_raw_dir(site_name, profile.safe_folder_name).resolve()
        _require_inside(raw_root, profile_root, "raw root")
        raw_files = _raw_files(raw_root)
        source_schema = _schema_version(paths.mesh_mr_db_path(site_name, profile.safe_folder_name))
        action = "current" if source_schema == SCHEMA_VERSION else "rebuild"
        detail = ""
        if action == "rebuild" and not raw_files:
            action = "blocked"
            detail = "没有可用于重建的原始 MESH 日志"
        entries.append(
            MeshRebuildEntry(
                mr_id=profile.mr_id,
                display_name=profile.display_name,
                safe_folder_name=profile.safe_folder_name,
                source_schema=source_schema,
                target_schema=SCHEMA_VERSION,
                raw_file_count=len(raw_files),
                raw_sha256={path.relative_to(raw_root).as_posix(): _sha256(path) for path in raw_files},
                action=action,
                detail=detail,
            )
        )
    return entries


def apply_plan(paths: PathResolver, site_name: str, entries: list[MeshRebuildEntry]) -> list[MeshRebuildEntry]:
    site_root = paths.site_dir(site_name).resolve()
    _require_inside(site_root, paths.sites_dir.resolve(), "site root")
    blocked = [entry for entry in entries if entry.action == "blocked"]
    if blocked:
        raise RuntimeError(f"存在 {len(blocked)} 个无法从 raw 重建的 MR")
    storage = MeshStorageService(site_name, paths)
    profiles = {profile.mr_id: profile for profile in storage.catalog.list_profiles()}
    completed: list[MeshRebuildEntry] = []
    for entry in entries:
        if entry.action != "rebuild":
            completed.append(entry)
            continue
        profile = profiles.get(entry.mr_id)
        if profile is None or profile.safe_folder_name != entry.safe_folder_name:
            raise RuntimeError(f"MR Profile 已变化：{entry.display_name}")
        profile_root = paths.mesh_mr_root(site_name, entry.safe_folder_name).resolve()
        _require_inside(profile_root, paths.site_mesh_root(site_name).resolve(), "profile root")
        raw_root = paths.mesh_mr_raw_dir(site_name, entry.safe_folder_name).resolve()
        index_path = paths.mesh_mr_db_path(site_name, entry.safe_folder_name).resolve()
        parsed_dir = paths.mesh_mr_parsed_dir(site_name, entry.safe_folder_name).resolve()
        for path, label in ((raw_root, "raw root"), (index_path, "index database"), (parsed_dir, "parsed directory")):
            _require_inside(path, profile_root, label)
        raw_files = _raw_files(raw_root)
        current_hashes = {path.relative_to(raw_root).as_posix(): _sha256(path) for path in raw_files}
        if current_hashes != entry.raw_sha256:
            raise RuntimeError(f"原始日志在计划后发生变化：{entry.display_name}")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archived_index = index_path.with_name(f"{index_path.name}.schema_archive_{timestamp}")
        archived_parsed = parsed_dir.with_name(f"{parsed_dir.name}.schema_archive_{timestamp}")
        if archived_index.exists() or archived_parsed.exists():
            raise RuntimeError(f"归档目标已存在：{entry.display_name}")
        moved_index = False
        moved_parsed = False
        rebuild_started = False
        try:
            gc.collect()
            if index_path.exists():
                index_path.replace(archived_index)
                moved_index = True
                _move_sqlite_sidecars(index_path, archived_index)
            if parsed_dir.exists():
                parsed_dir.replace(archived_parsed)
                moved_parsed = True
            rebuild_started = True
            MeshImportService(site_name, paths).import_files(profile, raw_files)
            rebuilt_hashes = {path.relative_to(raw_root).as_posix(): _sha256(path) for path in _raw_files(raw_root)}
            if rebuilt_hashes != entry.raw_sha256:
                raise RuntimeError(f"重建期间原始日志发生变化：{entry.display_name}")
            if _schema_version(index_path) != SCHEMA_VERSION:
                raise RuntimeError(f"派生库版本校验失败：{entry.display_name}")
        except Exception:
            gc.collect()
            if rebuild_started:
                _remove_derived(index_path, parsed_dir, profile_root)
            if moved_index:
                archived_index.replace(index_path)
                _move_sqlite_sidecars(archived_index, index_path)
            if moved_parsed:
                archived_parsed.replace(parsed_dir)
            raise
        completed.append(MeshRebuildEntry(**{**asdict(entry), "action": "rebuilt"}))
    return completed


def manifest(entries: list[MeshRebuildEntry], *, applied: bool, site_name: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "mode": "applied" if applied else "dry-run",
        "site_name": site_name,
        "target_mesh_schema": SCHEMA_VERSION,
        "entries": [asdict(entry) for entry in entries],
    }


def _raw_files(raw_root: Path) -> list[Path]:
    if not raw_root.is_dir():
        return []
    files: list[Path] = []
    for path in raw_root.rglob("*"):
        resolved = path.resolve()
        _require_inside(resolved, raw_root, "raw file")
        if path.is_symlink() or not path.is_file():
            continue
        name = path.name.casefold()
        if name.endswith((".log", ".txt", ".log.gz", ".txt.gz")):
            files.append(path)
    return sorted(files, key=lambda path: path.relative_to(raw_root).as_posix().casefold())


def _load_profiles_readonly(catalog_path: Path) -> list[MeshMrProfile]:
    if not catalog_path.is_file():
        return []
    uri = f"{catalog_path.resolve().as_uri()}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute("SELECT * FROM mr_profiles ORDER BY display_name COLLATE NOCASE").fetchall()
    except sqlite3.Error as exc:
        raise RuntimeError("MESH Profile catalog 无法只读加载") from exc
    return [
        MeshMrProfile(
            mr_id=str(row["mr_id"]),
            display_name=str(row["display_name"]),
            safe_folder_name=str(row["safe_folder_name"]),
            relative_folder_path=str(row["relative_folder_path"]),
            linked_device_id=int(row["linked_device_id"]) if row["linked_device_id"] is not None else None,
        )
        for row in rows
    ]


def _schema_version(path: Path) -> str:
    if not path.is_file():
        return "missing"
    try:
        uri = f"{path.as_uri()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as connection:
            row = connection.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()
            if row is None:
                row = connection.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        return str(row[0] or "unknown") if row else "unknown"
    except sqlite3.Error:
        return "unknown"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _move_sqlite_sidecars(source: Path, target: Path) -> None:
    for suffix in ("-wal", "-shm"):
        source_sidecar = source.with_name(source.name + suffix)
        if source_sidecar.exists():
            source_sidecar.replace(target.with_name(target.name + suffix))


def _remove_derived(index_path: Path, parsed_dir: Path, profile_root: Path) -> None:
    for path in (index_path, index_path.with_name(index_path.name + "-wal"), index_path.with_name(index_path.name + "-shm")):
        _require_inside(path.resolve(), profile_root, "derived database")
        path.unlink(missing_ok=True)
    if parsed_dir.exists():
        _require_inside(parsed_dir.resolve(), profile_root, "parsed directory")
        shutil.rmtree(parsed_dir)


def _require_inside(candidate: Path, root: Path, label: str) -> None:
    if candidate != root and not candidate.is_relative_to(root):
        raise RuntimeError(f"{label} 越过允许目录")


def _write_manifest(payload: dict[str, object], target: Path | None) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if target is None:
        print(text)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="从受保护 raw 日志重建 MESH 派生 SQLite")
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument("--site", required=True)
    parser.add_argument("--mr-id", action="append", default=[])
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--apply", action="store_true", help="执行重建；默认仅输出计划")
    args = parser.parse_args()
    paths = PathResolver(data_root=(args.data_root or default_data_root()).resolve())
    planned = build_plan(paths, args.site, set(args.mr_id) or None)
    if args.apply:
        completed = apply_plan(paths, args.site, planned)
        _write_manifest(manifest(completed, applied=True, site_name=args.site), args.manifest)
        return 0
    _write_manifest(manifest(planned, applied=False, site_name=args.site), args.manifest)
    return 2 if any(entry.action == "blocked" for entry in planned) else 0


if __name__ == "__main__":
    raise SystemExit(main())
