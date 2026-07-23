from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any
from uuid import uuid4

from netconsole.core.paths import PathResolver
from netconsole.models.task_state import TaskState
from netconsole.repositories.online_mr_task_session_repository import (
    OnlineMrTaskSessionRepository,
)
from netconsole.repositories.task_repository import TaskRepository


LOGGER = logging.getLogger(__name__)
_ACTIVE_TASK_STATES = {
    TaskState.PENDING,
    TaskState.STARTING,
    TaskState.RUNNING,
    TaskState.STOPPING,
}


class OnlineMrSessionLifecycleError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def online_mr_session_resource_key(site_id: str, session_id: str) -> str:
    return f"online_mr_session:{site_id}:{session_id}"


class OnlineMrSessionLifecycleService:
    """删除 Online MR 历史会话及其受管数据，不处理外部源文件。"""

    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths

    def delete_session(
        self,
        *,
        site_id: str,
        session_id: str,
        session_dir: str | Path,
        artifact_items: Iterable[dict[str, object]] = (),
        related_task_ids: Iterable[str] = (),
        current_task_id: str = "",
        progress: Callable[[str, int, int, str], None] | None = None,
    ) -> dict[str, object]:
        session_path, online_root = self._validated_session_dir(
            site_id, session_id, Path(session_dir)
        )
        artifacts = self._validated_artifacts(site_id, artifact_items)
        task_ids = {
            str(value).strip()
            for value in related_task_ids
            if str(value or "").strip() and str(value).strip() != current_task_id
        }
        resource_key = online_mr_session_resource_key(site_id, session_id)
        self._reject_active_work(
            site_id,
            session_id,
            resource_key,
            task_ids,
            current_task_id=current_task_id,
        )

        parsed_existed = (session_path / "parsed" / "online_diagnosis.sqlite").is_file()
        quarantine_root = (online_root / ".deleted_sessions").resolve()
        self._require_within(quarantine_root, online_root)
        quarantine_root.mkdir(parents=True, exist_ok=True)
        self._reject_link_or_junction(quarantine_root)
        quarantine = (quarantine_root / f"{session_id}-{uuid4().hex}").resolve()
        self._require_within(quarantine, quarantine_root)

        report = progress or (lambda *_args: None)
        report("validate", 1, 4, "会话删除范围与活动任务校验完成")
        os.replace(session_path, quarantine)
        report("detach", 2, 4, "会话已从历史列表安全隔离")

        failed_items: list[str] = []
        warnings: list[str] = []
        database_deleted = False
        database_result: dict[str, int] = {
            "mapping_records_deleted": 0,
            "task_records_deleted": 0,
        }
        try:
            repository = OnlineMrTaskSessionRepository(
                self.paths.site_tasks_db_path(site_id),
                site_id=site_id,
            )
            database_result = repository.delete_session_records(
                session_id,
                task_ids=task_ids,
                excluded_task_ids={current_task_id} if current_task_id else set(),
            )
            database_deleted = True
        except Exception:
            LOGGER.exception(
                "删除 Online MR 会话数据库记录失败：site=%s session=%s",
                site_id,
                session_id,
            )
            restored = False
            try:
                if quarantine.exists() and not session_path.exists():
                    os.replace(quarantine, session_path)
                    restored = True
            except OSError:
                LOGGER.exception(
                    "恢复 Online MR 会话目录失败：site=%s session=%s path=%s",
                    site_id,
                    session_id,
                    quarantine,
                )
            failed_items.append("database_records")
            warnings.append(
                "数据库记录删除失败，会话目录已恢复。"
                if restored
                else "数据库记录删除失败，且会话目录自动恢复失败，请检查日志。"
            )
            return {
                "terminal_state": "FAILED",
                "status": "FAILED",
                "session_id": session_id,
                "session_deleted": False,
                "parsed_data_deleted": False,
                "artifacts_deleted": False,
                "managed_files_deleted": False,
                "warnings": warnings,
                "failed_items": failed_items,
                **database_result,
                "error_code": "ONLINE_MR_SESSION_DELETE_DATABASE_FAILED",
                "error_message": "Online MR 会话数据库记录删除失败",
            }
        report("database", 3, 4, "会话关联数据库记录已事务清理")

        artifacts_deleted = True
        for item in artifacts:
            for kind, path in (("artifact_file", item["path"]), ("artifact_manifest", item["manifest_path"])):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    LOGGER.exception(
                        "删除 Online MR 受管 Artifact 失败：site=%s session=%s path=%s",
                        site_id,
                        session_id,
                        path,
                    )
                    artifacts_deleted = False
                    failed_items.append(kind)
        if not artifacts_deleted:
            warnings.append("部分受管报告或 Artifact 记录未能删除，请在日志中心查看详情。")

        managed_files_deleted = False
        try:
            self._safe_remove_tree(quarantine)
            managed_files_deleted = True
            try:
                quarantine_root.rmdir()
            except OSError:
                pass
        except OSError:
            LOGGER.exception(
                "清理 Online MR 隔离会话目录失败：site=%s session=%s path=%s",
                site_id,
                session_id,
                quarantine,
            )
            failed_items.append("managed_session_files")
            warnings.append("受管会话文件仅完成安全隔离，物理清理未全部完成。")
        report("files", 4, 4, "会话受管文件清理完成")

        success = database_deleted and artifacts_deleted and managed_files_deleted
        return {
            "status": "SUCCESS" if success else "PARTIAL_SUCCESS",
            "session_id": session_id,
            "session_deleted": database_deleted,
            "parsed_data_deleted": not parsed_existed or managed_files_deleted,
            "artifacts_deleted": artifacts_deleted,
            "managed_files_deleted": managed_files_deleted,
            "warnings": warnings,
            "failed_items": sorted(set(failed_items)),
            "artifact_count": len(artifacts),
            **database_result,
        }

    def _validated_session_dir(
        self,
        site_id: str,
        session_id: str,
        candidate: Path,
    ) -> tuple[Path, Path]:
        if (
            not session_id
            or Path(session_id).name != session_id
            or session_id in {".", ".."}
        ):
            raise OnlineMrSessionLifecycleError(
                "SESSION_NOT_FOUND", "Online MR 会话不存在"
            )
        online_root = self.paths.online_mr_root(site_id).resolve(strict=True)
        if not candidate.is_absolute():
            raise OnlineMrSessionLifecycleError(
                "SESSION_PATH_INVALID", "Online MR 会话路径无效"
            )
        self._reject_link_or_junction(candidate)
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise OnlineMrSessionLifecycleError(
                "SESSION_NOT_FOUND", "Online MR 会话不存在"
            ) from exc
        self._require_within(resolved, online_root)
        if (
            resolved.name != session_id
            or resolved.parent.name != "sessions"
            or len(resolved.parents) < 3
            or resolved.parents[2] != online_root
            or not resolved.is_dir()
        ):
            raise OnlineMrSessionLifecycleError(
                "SESSION_PATH_INVALID", "Online MR 会话目录结构无效"
            )
        for parent in (resolved.parent, resolved.parent.parent, online_root):
            self._reject_link_or_junction(parent)
        self._reject_tree_links(resolved)
        return resolved, online_root

    def _validated_artifacts(
        self,
        site_id: str,
        items: Iterable[dict[str, object]],
    ) -> list[dict[str, Any]]:
        report_root = (self.paths.online_mr_root(site_id) / "reports").resolve()
        manifest_root = (
            self.paths.rail_transit_root(site_id) / "web_artifacts" / "manifests"
        ).resolve()
        result: list[dict[str, Any]] = []
        for item in items:
            path = Path(str(item.get("path") or ""))
            manifest_path = Path(str(item.get("manifest_path") or ""))
            if not path.is_absolute() or not manifest_path.is_absolute():
                raise OnlineMrSessionLifecycleError(
                    "ARTIFACT_PATH_INVALID", "Online MR 报告路径无效"
                )
            output = path.resolve(strict=False)
            manifest = manifest_path.resolve(strict=False)
            self._require_within(output, report_root)
            self._require_within(manifest, manifest_root)
            if output.exists():
                self._reject_link_or_junction(output)
                if not output.is_file():
                    raise OnlineMrSessionLifecycleError(
                        "ARTIFACT_PATH_INVALID", "Online MR 报告不是普通文件"
                    )
            if manifest.exists():
                self._reject_link_or_junction(manifest)
                if not manifest.is_file():
                    raise OnlineMrSessionLifecycleError(
                        "ARTIFACT_PATH_INVALID", "Online MR 报告清单不是普通文件"
                    )
            result.append(
                {
                    "path": output,
                    "manifest_path": manifest,
                    "task_id": str(item.get("task_id") or ""),
                }
            )
        return result

    def _reject_active_work(
        self,
        site_id: str,
        session_id: str,
        resource_key: str,
        task_ids: set[str],
        *,
        current_task_id: str,
    ) -> None:
        repository = TaskRepository(self.paths.site_tasks_db_path(site_id))
        for snapshot in repository.list_filtered(
            statuses=_ACTIVE_TASK_STATES,
            site_name=site_id,
            limit=1000,
        ):
            if snapshot.task_id == current_task_id:
                continue
            if snapshot.task_id in task_ids or resource_key in snapshot.resource_keys:
                raise OnlineMrSessionLifecycleError(
                    "ONLINE_MR_SESSION_TASK_ACTIVE",
                    "当前会话仍有关联解析、导出或恢复任务正在执行，请等待任务完成。",
                )
        mapping = OnlineMrTaskSessionRepository(
            self.paths.site_tasks_db_path(site_id),
            site_id=site_id,
        ).get_by_session(session_id)
        if mapping is not None:
            snapshot = repository.get(mapping.controller_task_id)
            if snapshot is not None and snapshot.status in _ACTIVE_TASK_STATES:
                raise OnlineMrSessionLifecycleError(
                    "ONLINE_MR_SESSION_RUNNING",
                    "当前会话仍在采集或停止处理中，请先停止并等待任务完成。",
                )

    def _safe_remove_tree(self, root: Path) -> None:
        self._reject_link_or_junction(root)
        for entry in os.scandir(root):
            path = Path(entry.path)
            if entry.is_symlink() or self._is_junction(path):
                raise OSError("受管会话目录包含符号链接或 junction")
            if entry.is_dir(follow_symlinks=False):
                self._safe_remove_tree(path)
            else:
                path.unlink()
        root.rmdir()

    def _reject_tree_links(self, root: Path) -> None:
        self._reject_link_or_junction(root)
        with os.scandir(root) as entries:
            for entry in entries:
                path = Path(entry.path)
                if entry.is_symlink() or self._is_junction(path):
                    raise OnlineMrSessionLifecycleError(
                        "SESSION_PATH_UNTRUSTED",
                        "Online MR 会话目录包含不受信任的符号链接或 junction",
                    )
                if entry.is_dir(follow_symlinks=False):
                    self._reject_tree_links(path)

    @classmethod
    def _reject_link_or_junction(cls, path: Path) -> None:
        if path.is_symlink() or cls._is_junction(path):
            raise OnlineMrSessionLifecycleError(
                "SESSION_PATH_UNTRUSTED",
                "Online MR 会话目录包含不受信任的符号链接或 junction",
            )

    @staticmethod
    def _is_junction(path: Path) -> bool:
        checker = getattr(path, "is_junction", None)
        try:
            return bool(checker()) if callable(checker) else False
        except OSError:
            return True

    @staticmethod
    def _require_within(path: Path, root: Path) -> None:
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise OnlineMrSessionLifecycleError(
                "SESSION_PATH_OUTSIDE_MANAGED_ROOT",
                "Online MR 会话路径不在 NetConsole 受管目录",
            ) from exc
        if path == root:
            raise OnlineMrSessionLifecycleError(
                "SESSION_PATH_PROTECTED",
                "禁止删除 Online MR 管理根目录",
            )


__all__ = [
    "OnlineMrSessionLifecycleError",
    "OnlineMrSessionLifecycleService",
    "online_mr_session_resource_key",
]
