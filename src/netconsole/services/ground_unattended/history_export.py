"""Streaming history report executed exclusively by the existing Export Process."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from netconsole.services.export.common_exporters import ExportCancelled
from netconsole.services.ground_unattended.history_query import GroundHistoryQueryService


def export_ground_history_csv(
    path: Path,
    payload: Mapping[str, Any],
    progress: Callable[[str, int, int, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> int:
    query = GroundHistoryQueryService(Path(str(payload["db_path"])), site_id=str(payload["site_id"]))
    filters = dict(payload.get("filters") or {})
    fields = ("record_id", "data_type", "ts", "run_id", "train_id", "mr_id", "mr_role", "event_type", "status", "summary", "details")

    def checkpoint(count: int) -> None:
        if should_cancel and should_cancel():
            raise ExportCancelled("导出已取消")
        if progress:
            progress("write_history", count, 0, f"已导出 {count} 条历史索引")

    checkpoint(0)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("记录标识", "数据类型", "记录时间", "运行标识", "列车", "MR UUID", "CT/CW", "事件类型", "状态", "摘要", "原始索引详情"))
        for row in query.iter_export_rows(**filters):
            values = {**row, "details": json.dumps(row["details"], ensure_ascii=False, separators=(",", ":"))}
            # Treat device-origin text as text when opened in Excel/WPS.
            writer.writerow([_csv_text(values.get(field, "")) for field in fields])
            count += 1
            if count % 500 == 0:
                checkpoint(count)
    checkpoint(count)
    return count


def _csv_text(value: object) -> str:
    text = str(value)
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text
