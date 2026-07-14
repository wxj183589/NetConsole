from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from netconsole.core.paths import PathResolver
from netconsole.models.api.rail_transit_base_data import MergePlanDTO


class BaseDataPreviewStoreError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class BaseDataPreviewStore:
    """运行时预览 JSON；不保存上传原文件，不进入正式业务数据库。"""

    def __init__(self, paths: PathResolver) -> None:
        self.root = paths.rail_transit_base_data_preview_root()

    def save(self, plan: MergePlanDTO) -> str:
        preview_id = _uuid(plan.plan_id)
        directory = self._directory(preview_id)
        directory.mkdir(parents=True, exist_ok=False)
        meta = {
            "preview_id": preview_id,
            "site_id": plan.site_id,
            "source_file_name": Path(plan.source_file_name).name,
            "source_file_sha256": plan.source_file_sha256,
            "database_sha256": plan.database_hash,
            "created_at": plan.created_at,
            "expires_at": plan.preview_expires_at,
            "row_count": len(plan.items),
            **plan.summary.model_dump(),
        }
        issues = [issue.model_dump(mode="json") for item in plan.items for issue in item.issues]
        self._write_json(directory / "preview_meta.json", meta)
        self._write_json(directory / "merge_plan.json", plan.model_dump(mode="json"))
        self._write_json(directory / "issues.json", issues)
        self.cleanup_expired(exclude={preview_id})
        return preview_id

    def load(self, preview_id: str) -> MergePlanDTO:
        preview_id = _uuid(preview_id)
        path = self._directory(preview_id) / "merge_plan.json"
        try:
            plan = MergePlanDTO.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise BaseDataPreviewStoreError("BASE_DATA_PREVIEW_NOT_FOUND", "导入预览不存在或不可读") from exc
        if _expired(plan.preview_expires_at):
            raise BaseDataPreviewStoreError("BASE_DATA_PREVIEW_EXPIRED", "合并预览已过期，请重新预览")
        return plan

    def cleanup_expired(self, *, exclude: set[str] | None = None) -> int:
        if not self.root.is_dir():
            return 0
        removed = 0
        for directory in self.root.iterdir():
            if not directory.is_dir() or directory.name in (exclude or set()):
                continue
            try:
                preview_id = _uuid(directory.name)
                meta = json.loads((directory / "preview_meta.json").read_text(encoding="utf-8"))
                if not _expired(str(meta.get("expires_at") or "")):
                    continue
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            for name in ("preview_meta.json", "merge_plan.json", "issues.json"):
                path = self._directory(preview_id) / name
                if path.is_file():
                    path.unlink()
            try:
                directory.rmdir()
                removed += 1
            except OSError:
                continue
        return removed

    def _directory(self, preview_id: str) -> Path:
        directory = (self.root / _uuid(preview_id)).resolve()
        root = self.root.resolve()
        if root not in directory.parents:
            raise BaseDataPreviewStoreError("BASE_DATA_SOURCE_INVALID", "导入预览路径无效")
        return directory

    @staticmethod
    def _write_json(path: Path, payload: object) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)


def _uuid(value: str) -> str:
    try:
        return str(UUID(str(value)))
    except ValueError as exc:
        raise BaseDataPreviewStoreError("BASE_DATA_SOURCE_INVALID", "导入预览标识无效") from exc


def _expired(value: str) -> bool:
    try:
        expires_at = datetime.fromisoformat(value)
        return expires_at.tzinfo is None or expires_at <= datetime.now(timezone.utc)
    except (TypeError, ValueError):
        return True


__all__ = ["BaseDataPreviewStore", "BaseDataPreviewStoreError"]
