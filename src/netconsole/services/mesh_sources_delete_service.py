from __future__ import annotations

from collections.abc import Callable, Iterable

from netconsole.core.paths import PathResolver
from netconsole.services.mesh_source_delete_service import MeshSourceDeleteService


ProgressCallback = Callable[[str, int, int, str], None]
CancelCallback = Callable[[], bool]


class MeshSourcesDeleteCancelled(RuntimeError):
    pass


class MeshSourcesDeleteService:
    """Delete multiple MESH sources sequentially inside one background job."""

    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths
        self.single = MeshSourceDeleteService(paths)

    def delete_sources(
        self,
        site_id: str,
        session_ids: Iterable[str],
        *,
        delete_raw_archive: bool,
        delete_parsed_data: bool,
        delete_generated_reports: bool,
        progress: ProgressCallback | None = None,
        should_cancel: CancelCallback | None = None,
    ) -> dict[str, object]:
        selected = tuple(dict.fromkeys(str(item or "").strip() for item in session_ids))
        selected = tuple(item for item in selected if item)
        if not selected:
            raise ValueError("至少选择一个 MESH 来源")
        if not delete_parsed_data:
            raise ValueError("来源删除必须同时选择解析结果范围")

        items: list[dict[str, object]] = []
        total = len(selected)
        for index, session_id in enumerate(selected, start=1):
            if should_cancel and should_cancel():
                raise MeshSourcesDeleteCancelled("MESH 批量删除已取消")
            if progress:
                progress(
                    "mesh_analysis_sources_delete",
                    index - 1,
                    total,
                    f"正在删除 MESH 来源 {index}/{total}",
                )
            try:
                result = self.single.delete_source(
                    site_id,
                    session_id,
                    delete_raw_archive=delete_raw_archive,
                    delete_parsed_data=True,
                    delete_generated_reports=delete_generated_reports,
                )
                already_missing = bool(result.get("already_deleted"))
                status = (
                    "already_missing"
                    if already_missing
                    else "deleted"
                    if delete_raw_archive
                    else "parsed_deleted"
                )
                message = (
                    "来源已不存在，已跳过"
                    if already_missing
                    else "来源归档及分析结果已删除"
                    if delete_raw_archive
                    else "来源解析结果已删除"
                )
                items.append(
                    {
                        "session_id": session_id,
                        "status": status,
                        "success": True,
                        "message": message,
                        "delete_raw_archive": bool(delete_raw_archive),
                    }
                )
            except Exception as exc:
                items.append(
                    {
                        "session_id": session_id,
                        "status": "failed",
                        "success": False,
                        "message": str(exc)[:500],
                        "delete_raw_archive": bool(delete_raw_archive),
                    }
                )

        success_count = sum(
            item["status"] in {"deleted", "parsed_deleted"} for item in items
        )
        failed_count = sum(item["status"] == "failed" for item in items)
        skipped_count = sum(item["status"] == "already_missing" for item in items)
        if progress:
            progress(
                "mesh_analysis_sources_delete",
                total,
                total,
                "MESH 来源批量删除完成",
            )
        return {
            "requested_count": total,
            "success_count": success_count,
            "failed_count": failed_count,
            "skipped_count": skipped_count,
            "delete_raw_archive": bool(delete_raw_archive),
            "items": items,
        }


__all__ = ["MeshSourcesDeleteCancelled", "MeshSourcesDeleteService"]
