from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import shutil
from pathlib import Path

from netconsole.core.paths import PathResolver
from netconsole.core.sites import SiteManager
from netconsole.services.rail_transit.base_data_import_service import (
    BaseDataImportError,
    RailTransitBaseDataImportService,
)
from netconsole.services.rail_transit.base_data_query_service import RailTransitBaseDataQueryService
from netconsole.services.rail_transit.base_data_write_guard import BaseDataWriteGuard
from netconsole.services.rail_transit.import_preview_service import RailTransitImportPreviewService


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="仅在 devices.db 副本上验收轨道交通基础资料写入")
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--copy-dir", type=Path, required=True)
    parser.add_argument("--preview-file", type=Path, required=True)
    parser.add_argument("--site", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rollback", action="store_true")
    return parser


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_paths(source: Path, copy_root: Path, preview_file: Path) -> tuple[Path, Path, Path]:
    source = source.resolve(strict=True)
    preview_file = preview_file.resolve(strict=True)
    copy_root = copy_root.resolve()
    if not source.is_file() or source.name.casefold() != "devices.db":
        raise ValueError("--source-db 必须指向现有 devices.db")
    if not preview_file.is_file():
        raise ValueError("--preview-file 不存在")
    if copy_root == source.parent or copy_root in source.parents or source.parent in copy_root.parents:
        raise ValueError("--copy-dir 必须与源数据库目录完全隔离")
    source_site_root = source.parent.parent if source.parent.name.casefold() == "db" else None
    if source_site_root is not None and (copy_root == source_site_root or source_site_root in copy_root.parents):
        raise ValueError("--copy-dir 不能位于源正式局点目录内")
    return source, copy_root, preview_file


def _prepare_copy(source: Path, copy_root: Path, site: str, source_hash: str) -> tuple[PathResolver, Path]:
    paths = PathResolver(app_root=copy_root, data_root=copy_root)
    site = SiteManager(paths).validate_site_name(site)
    target = paths.site_db_path(site)
    if target.resolve() == source:
        raise ValueError("禁止直接操作源数据库")
    if target.exists():
        raise ValueError("副本目标已存在；请使用新的 --copy-dir，避免覆盖历史验收结果")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    metadata = {
        "name": site,
        "base_data_write_scope": "copy_validation",
        "base_data_source_sha256": source_hash,
    }
    (paths.site_dir(site) / "site_meta.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return paths, target


def run(args: argparse.Namespace) -> dict[str, object]:
    if args.rollback and not args.apply:
        raise ValueError("--rollback 必须与 --apply 一起使用")
    source, copy_root, preview_file = _validate_paths(args.source_db, args.copy_dir, args.preview_file)
    source_hash = _sha256(source)
    source_mtime_ns = source.stat().st_mtime_ns
    paths, copied_database = _prepare_copy(source, copy_root, args.site, source_hash)
    guard = BaseDataWriteGuard(paths, feature_enabled=True)
    import_service = RailTransitBaseDataImportService(paths, guard=guard)
    query_service = RailTransitBaseDataQueryService(paths)
    preview_service = RailTransitImportPreviewService(query_service, import_service=import_service)
    content = preview_file.read_bytes()
    preview = preview_service.preview(
        site_id=args.site,
        file_name=preview_file.name,
        content=content,
        content_type=mimetypes.guess_type(preview_file.name)[0] or "application/octet-stream",
    )
    output: dict[str, object] = {
        "source_db": str(source),
        "copy_db": str(copied_database),
        "source_sha256": source_hash,
        "copy_sha256_before": _sha256(copied_database),
        "preview_id": preview.preview_id,
        "summary": preview.merge_plan.summary.model_dump() if preview.merge_plan else {},
        "status": "PREVIEWED",
    }
    if args.apply:
        audit = import_service.apply_preview(
            preview_id=preview.preview_id,
            site_id=args.site,
            expected_database_sha256=preview.database_hash,
            explicit_confirmation=True,
            owner="maintenance_copy_validation",
        )
        output.update(
            status=audit["status"],
            operation_id=audit["operation_id"],
            copy_sha256_after=audit.get("database_hash_after") or _sha256(copied_database),
            record_count=len(import_service.repository.list_ap_records(args.site)),
        )
        if args.rollback:
            rolled_back = import_service.rollback_import(
                site_id=args.site,
                operation_id=str(audit["operation_id"]),
                explicit_confirmation=True,
            )
            output.update(
                status=rolled_back["status"],
                rollback_sha256=rolled_back.get("database_hash_rollback") or _sha256(copied_database),
            )
    output["source_unchanged"] = _sha256(source) == source_hash and source.stat().st_mtime_ns == source_mtime_ns
    if not output["source_unchanged"]:
        raise RuntimeError("源数据库 hash 或 mtime 发生变化，验收失败")
    return output


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        print(json.dumps(run(args), ensure_ascii=False, indent=2))
        return 0
    except (BaseDataImportError, OSError, RuntimeError, ValueError) as exc:
        print(f"基础资料副本验收失败：{exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
