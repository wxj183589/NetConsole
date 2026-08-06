from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from netconsole.core.paths import PathResolver
from netconsole.core.runtime_environment import data_root as default_data_root
from netconsole.repositories.mesh_mr_repository import SCHEMA_VERSION
from netconsole.services.mesh_derived_data_maintenance_service import MeshDerivedDataMaintenanceService


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
    """开发/运维 dry-run 包装；实际兼容检查由维护服务负责。"""

    maintenance = MeshDerivedDataMaintenanceService(paths)
    inspection = maintenance.inspect(site_name, profile_ids=mr_ids)
    entries: list[MeshRebuildEntry] = []
    for item in inspection["profiles"]:
        profile = dict(item)
        raw_root = paths.mesh_mr_raw_dir(site_name, str(profile["safe_folder_name"])).resolve()
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
        entries.append(
            MeshRebuildEntry(
                mr_id=str(profile["mr_id"]),
                display_name=str(profile["display_name"]),
                safe_folder_name=str(profile["safe_folder_name"]),
                source_schema=str(profile["current_version"]),
                target_schema=SCHEMA_VERSION,
                raw_file_count=len(raw_files),
                raw_sha256={path.relative_to(raw_root).as_posix(): _sha256(path) for path in raw_files},
                action=action,
                detail=detail,
            )
        )
    return entries


def apply_plan(paths: PathResolver, site_name: str, entries: list[MeshRebuildEntry]) -> list[MeshRebuildEntry]:
    """开发/运维 apply 包装；重建、归档、回滚和校验都由内部服务完成。"""

    blocked = [entry for entry in entries if entry.action == "blocked"]
    if blocked:
        raise RuntimeError(f"存在 {len(blocked)} 个无法从 raw 重建的 MR")
    maintenance = MeshDerivedDataMaintenanceService(paths)
    rebuild_ids: list[str] = []
    for entry in entries:
        if entry.action != "rebuild":
            continue
        raw_root = paths.mesh_mr_raw_dir(site_name, entry.safe_folder_name).resolve()
        hashes = {
            path.relative_to(raw_root).as_posix(): _sha256(path)
            for path in maintenance._raw_files(raw_root)
        }
        if hashes != entry.raw_sha256:
            raise RuntimeError(f"原始日志在计划后发生变化：{entry.display_name}")
        rebuild_ids.append(entry.mr_id)
    if rebuild_ids:
        maintenance.repair(site_name, profile_ids=rebuild_ids, include_missing=True)
    return [
        MeshRebuildEntry(**{**asdict(entry), "action": "rebuilt"})
        if entry.action == "rebuild"
        else entry
        for entry in entries
    ]


def manifest(entries: list[MeshRebuildEntry], *, applied: bool, site_name: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "mode": "applied" if applied else "dry-run",
        "site_name": site_name,
        "target_mesh_schema": SCHEMA_VERSION,
        "entries": [asdict(entry) for entry in entries],
    }


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
