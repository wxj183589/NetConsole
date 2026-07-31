from __future__ import annotations

import gc
import shutil
import time
from pathlib import Path
from uuid import uuid4

from netconsole.core.paths import PathResolver
from netconsole.repositories.mesh_catalog_repository import MeshCatalogRepository
from netconsole.repositories.mesh_source_index_repository import MeshSourceIndexRepository
from netconsole.services.mesh_source_locator import MeshSourceLocator
from netconsole.services.mesh_source_rebuild_service import MeshSourceRebuildService


class MeshSourceDeleteService:
    """在 MESH profile 数据根内可回滚地删除一个来源及其派生物。"""

    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths

    def delete_source(
        self,
        site_id: str,
        session_id: str,
        *,
        delete_raw_archive: bool,
        delete_parsed_data: bool,
        delete_generated_reports: bool,
    ) -> dict[str, object]:
        if not delete_parsed_data:
            raise ValueError("来源删除必须同时选择解析结果范围")
        delete_generated_reports = bool(
            delete_generated_reports or delete_raw_archive
        )
        try:
            profile, source, index = MeshSourceRebuildService(self.paths)._source(site_id, session_id)
        except ValueError as exc:
            if "不存在" in str(exc):
                return {"session_id": session_id, "already_deleted": True, "deleted_files": 0}
            raise

        profile_root = self._inside(
            self.paths.mesh_mr_root(site_id, profile.safe_folder_name).resolve(),
            self.paths.site_mesh_root(site_id).resolve(),
        )
        raw_root = self._inside(
            self.paths.mesh_mr_raw_dir(site_id, profile.safe_folder_name).resolve(),
            profile_root,
        )
        parsed_root = self._inside(
            self.paths.mesh_mr_parsed_dir(site_id, profile.safe_folder_name).resolve(),
            profile_root,
        )
        source_id = int(source["id"])
        raw_path = MeshSourceLocator(self.paths).locate(site_id, profile, source).raw_path
        parsed_value = str(source.get("parsed_db_path") or "").strip().strip("'\"")
        parsed_path = Path(parsed_value).resolve() if parsed_value else None
        if parsed_path is not None and parsed_path.exists():
            self._inside(parsed_path, parsed_root)

        report_paths, report_count = (
            self._report_paths(site_id, session_id, profile_root)
            if delete_generated_reports
            else ([], 0)
        )
        targets: list[Path] = []
        if delete_raw_archive and raw_path is not None and raw_path.exists():
            targets.append(self._inside(raw_path.resolve(), raw_root))
        if parsed_path is not None and parsed_path.exists():
            targets.append(parsed_path)
            targets.extend(
                sidecar for sidecar in (
                    parsed_path.with_name(parsed_path.name + "-wal"),
                    parsed_path.with_name(parsed_path.name + "-shm"),
                )
                if sidecar.exists()
            )
        targets.extend(report_paths)
        targets = list(dict.fromkeys(targets))
        counts = self._parsed_counts(index, source_id)
        quarantine = profile_root / ".quarantine" / uuid4().hex
        quarantine.mkdir(parents=True, exist_ok=False)
        moved: list[tuple[Path, Path]] = []
        deleted_index: dict[str, object] | None = None
        source_metadata_changed = False
        catalog = MeshCatalogRepository(self.paths.mesh_catalog_path(site_id))
        catalog_snapshot: dict[str, list[dict[str, object]]] = {"session_index": [], "fingerprints": []}
        try:
            gc.collect()
            for number, target in enumerate(targets):
                quarantined = quarantine / f"{number:04d}-{target.name}"
                if self._move_with_retry(target, quarantined):
                    moved.append((target, quarantined))
            if delete_raw_archive:
                # Only the resolved archived copy is eligible; original_path is
                # intentionally never read or deleted.
                pass
            if delete_raw_archive:
                deleted_index = index.delete_source_file(source_id)
                if deleted_index is None:
                    raise ValueError("MESH 来源不存在")
            else:
                index.mark_parsed_deleted(source_id)
                source_metadata_changed = True
            if delete_raw_archive:
                catalog_snapshot = catalog.delete_source_index(
                    session_id=session_id,
                    mr_id=profile.mr_id,
                    source_file_id=source_id,
                )
            else:
                catalog_snapshot = catalog.mark_session_parsed_deleted(
                    session_id,
                    reports_deleted=delete_generated_reports,
                )
            catalog.update_summary(profile.mr_id, index.aggregate_summary())
        except Exception as exc:
            rollback_errors: list[str] = []
            try:
                if deleted_index is not None:
                    index.restore_source_file(deleted_index)
                elif source_metadata_changed and index.get_source_file(source_id) is not None:
                    index.restore_source_metadata(source_id, source)
            except Exception as rollback_exc:
                rollback_errors.append(f"source_index:{type(rollback_exc).__name__}")
            try:
                catalog.restore_source_index(catalog_snapshot)
            except Exception as rollback_exc:
                rollback_errors.append(f"catalog:{type(rollback_exc).__name__}")
            for original, quarantined in reversed(moved):
                try:
                    if quarantined.exists():
                        original.parent.mkdir(parents=True, exist_ok=True)
                        quarantined.replace(original)
                except Exception as rollback_exc:
                    rollback_errors.append(
                        f"file:{original.name}:{type(rollback_exc).__name__}"
                    )
            try:
                shutil.rmtree(quarantine, ignore_errors=False)
            except FileNotFoundError:
                pass
            except Exception as rollback_exc:
                rollback_errors.append(f"quarantine:{type(rollback_exc).__name__}")
            try:
                catalog.update_summary(profile.mr_id, index.aggregate_summary())
            except Exception as rollback_exc:
                rollback_errors.append(f"summary:{type(rollback_exc).__name__}")
            if rollback_errors:
                raise RuntimeError(
                    "MESH 来源删除失败且补偿未完全完成："
                    + ", ".join(rollback_errors)
                ) from exc
            raise

        cleanup_pending = False
        cleanup_warning = ""
        try:
            shutil.rmtree(quarantine, ignore_errors=False)
        except FileNotFoundError:
            pass
        except OSError as exc:
            cleanup_pending = True
            cleanup_warning = f"隔离目录清理待重试：{type(exc).__name__}"

        return {
            "session_id": session_id,
            "already_deleted": False,
            "delete_raw_archive": bool(delete_raw_archive),
            "delete_parsed_data": True,
            "delete_generated_reports": delete_generated_reports,
            "deleted_files": len(moved),
            "deleted_reports": report_count,
            "parsed_links": counts["links"],
            "parsed_events": counts["events"],
            "parsed_issues": counts["issues"],
            "source_file_id": source_id,
            "cleanup_pending": cleanup_pending,
            "cleanup_warning": cleanup_warning,
        }

    @staticmethod
    def _parsed_counts(index: MeshSourceIndexRepository, source_id: int) -> dict[str, int]:
        # The index repository delegates count queries to the compact detail DB.
        from netconsole.repositories.mesh_mr_repository import MeshMrRepository

        return MeshMrRepository(index.path).count_parsed_data_by_source_file(source_id)

    def _report_paths(
        self,
        site_id: str,
        session_id: str,
        profile_root: Path,
    ) -> tuple[list[Path], int]:
        from netconsole.services.rail_transit.mesh_analysis_query_service import MeshAnalysisQueryService

        service = MeshAnalysisQueryService(self.paths, schedule_catalog_index=False)
        targets, report_count = service.session_report_delete_targets(
            site_id,
            session_id,
        )
        export_root = self.paths.mesh_mr_export_dir(
            site_id,
            profile_root.name,
        ).resolve()
        manifest_root = (
            self.paths.rail_transit_root(site_id)
            / "web_artifacts"
            / "manifests"
        ).resolve()
        paths: list[Path] = []
        for target in targets:
            resolved = target.resolve()
            if resolved.is_relative_to(export_root):
                paths.append(self._inside(resolved, export_root))
            elif resolved.is_relative_to(manifest_root):
                paths.append(self._inside(resolved, manifest_root))
            else:
                raise ValueError("MESH 报告路径越过允许目录")
        return list(dict.fromkeys(paths)), report_count

    @staticmethod
    def _inside(candidate: Path, root: Path) -> Path:
        if candidate != root and not candidate.is_relative_to(root):
            raise ValueError("MESH 来源路径越过允许目录")
        return candidate

    @staticmethod
    def _move_with_retry(source: Path, target: Path) -> bool:
        for attempt in range(5):
            try:
                source.replace(target)
                return True
            except FileNotFoundError:
                return False
            except PermissionError:
                if attempt == 4:
                    raise
                gc.collect()
                time.sleep(0.1)
        return False


__all__ = ["MeshSourceDeleteService"]
