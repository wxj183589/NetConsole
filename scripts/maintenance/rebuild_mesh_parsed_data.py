from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

from netconsole.core.paths import PathResolver
from netconsole.core.runtime_environment import (
    data_root as default_data_root,
)
from netconsole.repositories.mesh_mr_repository import PARSER_VERSION, SCHEMA_VERSION
from netconsole.services.mesh_derived_data_maintenance_service import MeshDerivedDataMaintenanceService
from netconsole.services.mesh_write_authority import (
    MESH_DERIVED_REBUILD_AUTHORIZED,
    MESH_DERIVED_REBUILD_OPERATION,
    MeshProductionSiteScope,
    mesh_operation_lock,
    require_mesh_profile_scope,
    require_mesh_write_authority,
    resolve_mesh_production_scope,
)


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
    canonical_site_id: str = ""
    site_directory_name: str = ""
    index_sha256: str = ""
    index_schema: str = ""
    parsed_sha256: dict[str, str] | None = None
    parsed_schema: dict[str, str] | None = None
    source_revision: str = ""
    parser_schema: str = PARSER_VERSION
    operation: str = MESH_DERIVED_REBUILD_OPERATION
    plan_digest: str = ""


def build_plan(paths: PathResolver, site_name: str, mr_ids: set[str] | None = None) -> list[MeshRebuildEntry]:
    """开发/运维 dry-run 包装；实际兼容检查由维护服务负责。"""

    scope = resolve_mesh_production_scope(paths, site_name)
    site_directory_name = scope.directory_name
    _preflight_catalog_profiles(paths, scope, mr_ids)
    maintenance = MeshDerivedDataMaintenanceService(paths)
    inspection = maintenance.inspect(site_directory_name, profile_ids=mr_ids)
    entries: list[MeshRebuildEntry] = []
    for item in inspection["profiles"]:
        profile = dict(item)
        safe_folder_name = str(profile["safe_folder_name"])
        raw_root = paths.mesh_mr_raw_dir(site_directory_name, safe_folder_name).resolve()
        raw_files = maintenance._raw_files(raw_root)
        status = str(profile["status"])
        if status == "compatible":
            action = "current"
        elif status == "blocked":
            action = "blocked"
        elif status in {"incompatible", "missing"}:
            action = "rebuild" if raw_files else "blocked"
        else:
            action = "blocked"
        detail = str(profile.get("detail") or "")
        if action == "blocked" and not detail:
            detail = "没有可用于重建的原始 MESH 日志"
        index_path = paths.mesh_mr_db_path(site_directory_name, safe_folder_name).resolve()
        parsed_root = paths.mesh_mr_parsed_dir(site_directory_name, safe_folder_name).resolve()
        entry = MeshRebuildEntry(
                mr_id=str(profile["mr_id"]),
                display_name=str(profile["display_name"]),
                safe_folder_name=safe_folder_name,
                source_schema=str(profile["current_version"]),
                target_schema=SCHEMA_VERSION,
                raw_file_count=len(raw_files),
                raw_sha256=_tree_sha256(raw_root, raw_files),
                action=action,
                detail=detail,
                canonical_site_id=scope.canonical_site_id,
                site_directory_name=site_directory_name,
                index_sha256=_sha256(index_path) if index_path.is_file() else "",
                index_schema=_sqlite_schema(index_path),
                parsed_sha256=_parsed_sha256(parsed_root),
                parsed_schema=_tree_schema(parsed_root),
                source_revision=_source_revision(index_path),
                parser_schema=PARSER_VERSION,
                operation=MESH_DERIVED_REBUILD_OPERATION,
            )
        entries.append(_with_plan_digest(entry))
    return entries


def apply_plan(
    paths: PathResolver,
    site_name: str,
    entries: list[MeshRebuildEntry],
    *,
    allow_production_write: bool = False,
    authorization_token: str = "",
) -> list[MeshRebuildEntry]:
    """开发/运维 apply 包装；重建、归档、回滚和校验都由内部服务完成。"""

    scope = require_mesh_write_authority(
        paths,
        site_name,
        operation=MESH_DERIVED_REBUILD_OPERATION,
        allow_production_write=allow_production_write,
        authorization_token=authorization_token,
    )
    blocked = [entry for entry in entries if entry.action == "blocked"]
    if blocked:
        raise RuntimeError(f"存在 {len(blocked)} 个无法从 raw 重建的 MR")
    maintenance = MeshDerivedDataMaintenanceService(paths)
    rebuild_ids = [entry.mr_id for entry in entries if entry.action == "rebuild"]
    if rebuild_ids:
        with mesh_operation_lock(
            paths,
            scope,
            MESH_DERIVED_REBUILD_OPERATION,
        ):
            _validate_plan(paths, scope, entries)
            maintenance.repair(
                scope.directory_name,
                profile_ids=rebuild_ids,
                include_missing=True,
            )
    return [
        MeshRebuildEntry(**{**asdict(entry), "action": "rebuilt"})
        if entry.action == "rebuild"
        else entry
        for entry in entries
    ]


def manifest(entries: list[MeshRebuildEntry], *, applied: bool, site_name: str) -> dict[str, object]:
    canonical_site_id = next(
        (entry.canonical_site_id for entry in entries if entry.canonical_site_id),
        site_name,
    )
    return {
        "schema_version": 2,
        "mode": "applied" if applied else "dry-run",
        "site_name": site_name,
        "canonical_site_id": canonical_site_id,
        "operation": MESH_DERIVED_REBUILD_OPERATION,
        "target_mesh_schema": SCHEMA_VERSION,
        "entries": [asdict(entry) for entry in entries],
    }


def _validate_plan(
    paths: PathResolver,
    scope: MeshProductionSiteScope,
    entries: list[MeshRebuildEntry],
) -> None:
    """Re-resolve every plan identity before constructing the maintenance service."""

    for entry in entries:
        if entry.operation != MESH_DERIVED_REBUILD_OPERATION:
            raise RuntimeError("MESH 计划操作类型不匹配")
        if entry.target_schema != SCHEMA_VERSION or entry.parser_schema != PARSER_VERSION:
            raise RuntimeError("MESH 计划 parser/schema 已变化")
        if entry.canonical_site_id != scope.canonical_site_id:
            raise RuntimeError("MESH 计划局点 canonical identity 已变化")
        if entry.site_directory_name != scope.directory_name:
            raise RuntimeError("MESH 计划局点目录已变化")
        if not entry.plan_digest or _plan_digest(entry) != entry.plan_digest:
            raise RuntimeError("MESH 计划 digest 无效或已变化")
        profile_root = paths.mesh_mr_root(scope.directory_name, entry.safe_folder_name).resolve()
        raw_root = paths.mesh_mr_raw_dir(scope.directory_name, entry.safe_folder_name).resolve()
        index_path = paths.mesh_mr_db_path(scope.directory_name, entry.safe_folder_name).resolve()
        parsed_root = paths.mesh_mr_parsed_dir(scope.directory_name, entry.safe_folder_name).resolve()
        if not profile_root.is_relative_to(scope.site_root):
            raise RuntimeError("MESH Profile 路径越过 canonical Production Site")
        raw_files = MeshDerivedDataMaintenanceService._raw_files(raw_root)
        if _tree_sha256(raw_root, raw_files) != entry.raw_sha256:
            raise RuntimeError(f"原始日志在计划后发生变化：{entry.display_name}")
        current_index_sha = _sha256(index_path) if index_path.is_file() else ""
        current_index_schema = _sqlite_schema(index_path)
        current_parsed_sha = _parsed_sha256(parsed_root)
        current_parsed_schema = _tree_schema(parsed_root)
        if (
            current_index_sha != entry.index_sha256
            or current_index_schema != entry.index_schema
            or current_parsed_sha != (entry.parsed_sha256 or {})
            or current_parsed_schema != (entry.parsed_schema or {})
            or _source_revision(index_path) != entry.source_revision
        ):
            raise RuntimeError(f"MESH 计划来源/index/parsed identity 已变化：{entry.display_name}")


def _tree_sha256(root: Path, files: list[Path] | None = None) -> dict[str, str]:
    selected = files if files is not None else (
        sorted(path for path in root.rglob("*") if path.is_file() and not path.is_symlink())
        if root.is_dir()
        else []
    )
    return {
        path.relative_to(root).as_posix(): _sha256(path)
        for path in sorted(selected)
    }


def _preflight_catalog_profiles(
    paths: PathResolver,
    scope: MeshProductionSiteScope,
    mr_ids: set[str] | None,
) -> None:
    catalog = paths.mesh_catalog_path(scope.directory_name).resolve()
    if not catalog.is_file():
        return
    with sqlite3.connect(f"{catalog.as_uri()}?mode=ro", uri=True) as connection:
        rows = connection.execute(
            "SELECT mr_id, safe_folder_name FROM mr_profiles"
        ).fetchall()
    for mr_id, safe_folder_name in rows:
        if mr_ids and str(mr_id) not in mr_ids:
            continue
        require_mesh_profile_scope(paths, scope, str(safe_folder_name or ""))


def _parsed_sha256(root: Path) -> dict[str, str]:
    if not root.is_dir():
        return {}
    files = [
        path
        for path in root.rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and not path.name.endswith(("-wal", "-shm"))
        and ".rebuild." not in path.name
        and ".backup." not in path.name
    ]
    return _tree_sha256(root, files)


def _tree_schema(root: Path) -> dict[str, str]:
    if not root.is_dir():
        return {}
    return {
        path.relative_to(root).as_posix(): _sqlite_schema(path)
        for path in sorted(root.rglob("*.sqlite"))
        if path.is_file() and not path.is_symlink()
    }


def _sqlite_schema(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True) as connection:
            rows = connection.execute(
                "SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type, name"
            ).fetchall()
            return hashlib.sha256(
                json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str).encode()
            ).hexdigest()
    except sqlite3.Error:
        return "invalid"


def _source_revision(index_path: Path) -> str:
    return _sha256(index_path) if index_path.is_file() else ""


def _plan_digest(entry: MeshRebuildEntry) -> str:
    payload = asdict(entry)
    payload["plan_digest"] = ""
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _with_plan_digest(entry: MeshRebuildEntry) -> MeshRebuildEntry:
    from dataclasses import replace

    return replace(entry, plan_digest=_plan_digest(entry))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    parser.add_argument(
        "--allow-production-write",
        action="store_true",
        help="明确授权对 production 数据根执行重建",
    )
    parser.add_argument(
        "--authorization-token",
        default="",
        help=(
            "MESH operation-specific production capability token "
            f"(expected: {MESH_DERIVED_REBUILD_AUTHORIZED})"
        ),
    )
    args = parser.parse_args()
    paths = PathResolver(data_root=(args.data_root or default_data_root()).resolve())
    if args.apply:
        scope = require_mesh_write_authority(
            paths,
            args.site,
            operation=MESH_DERIVED_REBUILD_OPERATION,
            allow_production_write=args.allow_production_write,
            authorization_token=args.authorization_token,
        )
    else:
        scope = resolve_mesh_production_scope(paths, args.site)
    planned = build_plan(paths, args.site, set(args.mr_id) or None)
    if args.apply:
        completed = apply_plan(
            paths,
            args.site,
            planned,
            allow_production_write=args.allow_production_write,
            authorization_token=args.authorization_token,
        )
        _write_manifest(
            manifest(completed, applied=True, site_name=scope.canonical_site_id),
            args.manifest,
        )
        return 0
    _write_manifest(
        manifest(planned, applied=False, site_name=scope.canonical_site_id),
        args.manifest,
    )
    return 2 if any(entry.action == "blocked" for entry in planned) else 0


if __name__ == "__main__":
    raise SystemExit(main())
