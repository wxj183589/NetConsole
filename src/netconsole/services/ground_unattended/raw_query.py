from __future__ import annotations

import heapq
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)


class GroundRawQueryError(ValueError):
    pass


class GroundRawStreamQueryService:
    """Bounded, read-only queries over registered unattended NDJSON files."""

    def __init__(self, repository: GroundUnattendedRepository) -> None:
        self.repository = repository
        self.root = repository.db_path.parent.resolve()

    def ping_series(
        self,
        *,
        run_id: str = "",
        train_id: str = "",
        mr_id: str = "",
        target_ip: str = "",
        start_time: str = "",
        end_time: str = "",
        include_warmup: bool = False,
        max_points: int = 3000,
    ) -> dict[str, Any]:
        start, end = _time_range(start_time, end_time)
        max_points = max(10, min(int(max_points), 10_000))
        duration = max(1.0, (end - start).total_seconds())
        bucket_seconds = max(0.001, duration / max_points)
        success_buckets: dict[tuple[str, int], dict[str, Any]] = {}
        loss_points: list[dict[str, Any]] = []
        counts = {"raw": 0, "effective": 0, "ignored": 0}
        loss_state: dict[str, dict[str, Any]] = {}
        loss_windows: list[dict[str, Any]] = []
        ap_transitions: list[dict[str, Any]] = []
        position_segments: list[dict[str, Any]] = []
        last_position: dict[str, tuple[str, str, str, str]] = {}

        for item in self._records(
            data_type="ping", run_id=run_id, start=start, end=end, time_key="ts"
        ):
            if not _matches(
                item,
                train_id=train_id,
                mr_id=mr_id,
                target_ip=target_ip,
            ):
                continue
            counts["raw"] += 1
            ignored = bool(item.get("warmup_ignored"))
            if ignored:
                counts["ignored"] += 1
            else:
                counts["effective"] += 1
            if ignored and not include_warmup:
                continue
            address = str(item.get("target_ip") or "")
            ts = _parse_time(str(item["ts"]))
            if ts is None:
                continue
            if not bool(item.get("ok")) and not ignored:
                current = loss_state.get(address)
                if current is None:
                    current = {
                        "target_ip": address,
                        "train_id": str(item.get("train_id") or ""),
                        "mr_id": str(item.get("mr_id") or ""),
                        "mr_name": str(item.get("mr_name") or ""),
                        "mr_position_code": str(
                            item.get("mr_position_code") or ""
                        ),
                        "started_at": str(item["ts"]),
                        "ended_at": str(item["ts"]),
                        "loss_count": 0,
                        "current_ap_name": str(
                            item.get("current_ap_name") or ""
                        ),
                        "station": str(item.get("station") or ""),
                        "section": str(item.get("section") or ""),
                        "ap_transition_context": str(
                            item.get("ap_transition_context") or ""
                        ),
                        "position_quality": str(
                            item.get("position_quality") or "UNKNOWN"
                        ),
                    }
                    loss_state[address] = current
                current["ended_at"] = str(item["ts"])
                current["loss_count"] = int(current["loss_count"]) + 1
                if len(loss_points) < max_points:
                    loss_points.append(item)
            else:
                current = loss_state.pop(address, None)
                if current is not None:
                    _finish_loss_window(current)
                    if len(loss_windows) < max_points:
                        loss_windows.append(current)
                bucket = int((ts - start).total_seconds() / bucket_seconds)
                success_buckets.setdefault((address, bucket), item)

            transition = str(item.get("ap_transition_context") or "")
            if transition:
                marker = {
                    "ts": str(item["ts"]),
                    "target_ip": address,
                    "context": transition,
                    "current_ap_name": str(item.get("current_ap_name") or ""),
                    "station": str(item.get("station") or ""),
                    "section": str(item.get("section") or ""),
                }
                if (
                    len(ap_transitions) < max_points
                    and (not ap_transitions or ap_transitions[-1] != marker)
                ):
                    ap_transitions.append(marker)

            position = (
                str(item.get("current_ap_identity") or ""),
                str(item.get("current_ap_name") or ""),
                str(item.get("station") or ""),
                str(item.get("section") or ""),
            )
            previous = last_position.get(address)
            if previous != position:
                if len(position_segments) < max_points:
                    position_segments.append(
                        {
                            "started_at": str(item["ts"]),
                            "target_ip": address,
                            "current_ap_identity": position[0],
                            "current_ap_name": position[1],
                            "station": position[2],
                            "section": position[3],
                            "position_quality": str(
                                item.get("position_quality") or "UNKNOWN"
                            ),
                        }
                    )
                last_position[address] = position

        for current in loss_state.values():
            _finish_loss_window(current)
            if len(loss_windows) < max_points:
                loss_windows.append(current)

        remaining = max(0, max_points - len(loss_points))
        successes = sorted(
            success_buckets.values(), key=lambda item: str(item.get("ts") or "")
        )
        if len(successes) > remaining and remaining:
            step = len(successes) / remaining
            successes = [successes[int(index * step)] for index in range(remaining)]
        elif remaining == 0:
            successes = []
        points = sorted(
            [*loss_points, *successes], key=lambda item: str(item.get("ts") or "")
        )[:max_points]
        return {
            "raw_sample_count": counts["raw"],
            "effective_sample_count": counts["effective"],
            "ignored_sample_count": counts["ignored"],
            "points": points,
            "loss_windows": loss_windows,
            "ap_transitions": ap_transitions[:max_points],
            "position_segments": position_segments[:max_points],
        }

    def ping_samples(
        self,
        *,
        run_id: str = "",
        train_id: str = "",
        mr_id: str = "",
        target_ip: str = "",
        start_time: str = "",
        end_time: str = "",
        include_warmup: bool = False,
        page: int = 1,
        page_size: int = 100,
    ) -> dict[str, Any]:
        start, end = _time_range(start_time, end_time)
        page = max(1, min(int(page), 200))
        page_size = max(1, min(int(page_size), 500))
        keep_count = page * page_size
        matched: list[tuple[float, int, dict[str, Any]]] = []
        counts = {"raw": 0, "effective": 0, "ignored": 0}
        serial = 0
        for item in self._records(
            data_type="ping", run_id=run_id, start=start, end=end, time_key="ts"
        ):
            if not _matches(
                item,
                train_id=train_id,
                mr_id=mr_id,
                target_ip=target_ip,
            ):
                continue
            counts["raw"] += 1
            ignored = bool(item.get("warmup_ignored"))
            counts["ignored" if ignored else "effective"] += 1
            if include_warmup or not ignored:
                serial += 1
                parsed = _parse_time(str(item.get("ts") or ""))
                if parsed is None:
                    continue
                entry = (parsed.timestamp(), serial, item)
                if len(matched) < keep_count:
                    heapq.heappush(matched, entry)
                elif entry[:2] > matched[0][:2]:
                    heapq.heapreplace(matched, entry)
        matched_items = [
            item
            for _timestamp, _serial, item in sorted(
                matched, key=lambda entry: (entry[0], entry[1]), reverse=True
            )
        ]
        offset = (page - 1) * page_size
        return {
            "items": matched_items[offset : offset + page_size],
            "total": counts["effective"] + counts["ignored"]
            if include_warmup
            else counts["effective"],
            "page": page,
            "page_size": page_size,
            "raw_sample_count": counts["raw"],
            "effective_sample_count": counts["effective"],
            "ignored_sample_count": counts["ignored"],
        }

    def syslog_records(
        self,
        *,
        run_id: str = "",
        train_id: str = "",
        mr_id: str = "",
        mr_name: str = "",
        source_ip: str = "",
        system_name: str = "",
        severity: str = "",
        keyword: str = "",
        start_time: str = "",
        end_time: str = "",
        page: int = 1,
        page_size: int = 100,
    ) -> dict[str, Any]:
        start, end = _time_range(start_time, end_time)
        page = max(1, min(int(page), 200))
        page_size = max(1, min(int(page_size), 500))
        keep_count = page * page_size
        rows: list[tuple[float, int, dict[str, Any]]] = []
        matched_count = 0
        serial = 0
        filters = {
            "train_id": train_id.casefold(),
            "device_uuid": mr_id.casefold(),
            "mr_name": mr_name.casefold(),
            "source_ip": source_ip.casefold(),
            "system_name": system_name.casefold(),
            "severity": severity.casefold(),
        }
        keyword_value = keyword.casefold()
        for item in self._records(
            data_type="syslog",
            run_id=run_id,
            start=start,
            end=end,
            time_key="receive_time",
        ):
            if any(
                expected
                and expected not in _syslog_filter_value(item, field)
                for field, expected in filters.items()
            ):
                continue
            if keyword_value and keyword_value not in str(
                item.get("raw_text") or ""
            ).casefold():
                continue
            matched_count += 1
            parsed = _parse_time(str(item.get("receive_time") or ""))
            if parsed is None:
                continue
            serial += 1
            entry = (parsed.timestamp(), serial, item)
            if len(rows) < keep_count:
                heapq.heappush(rows, entry)
            elif entry[:2] > rows[0][:2]:
                heapq.heapreplace(rows, entry)
        row_items = [
            item
            for _timestamp, _serial, item in sorted(
                rows, key=lambda entry: (entry[0], entry[1]), reverse=True
            )
        ]
        offset = (page - 1) * page_size
        return {
            "items": row_items[offset : offset + page_size],
            "total": matched_count,
            "page": page,
            "page_size": page_size,
        }

    def _records(
        self,
        *,
        data_type: str,
        run_id: str,
        start: datetime,
        end: datetime,
        time_key: str,
    ) -> Iterator[dict[str, Any]]:
        files = self.repository.list_raw_files_for_query(
            data_type=data_type,
            start_time=start.isoformat(),
            end_time=end.isoformat(),
            run_id=run_id,
        )
        for registered in files:
            path = self._registered_path(str(registered.get("relative_path") or ""))
            if not path.is_file():
                continue
            try:
                with path.open("r", encoding="utf-8", errors="replace") as handle:
                    for line in handle:
                        try:
                            item = json.loads(line)
                        except (TypeError, json.JSONDecodeError):
                            continue
                        if not isinstance(item, dict):
                            continue
                        ts = _parse_time(str(item.get(time_key) or ""))
                        if ts is None or ts < start or ts > end:
                            continue
                        item["raw_file_id"] = str(
                            registered.get("file_id") or ""
                        )
                        item["raw_file_status"] = str(
                            registered.get("status") or ""
                        )
                        yield item
            except OSError as exc:
                raise GroundRawQueryError(
                    f"无法读取已登记的 {data_type} 原始文件"
                ) from exc

    def _registered_path(self, relative_path: str) -> Path:
        if not relative_path:
            raise GroundRawQueryError("原始文件登记路径为空")
        relative = Path(relative_path)
        if relative.is_absolute() or any(part == ".." for part in relative.parts):
            raise GroundRawQueryError("拒绝读取数据根之外的原始文件")
        candidate = self.root.joinpath(relative)
        current = self.root
        for part in relative.parts:
            current = current / part
            if current.is_symlink() or _is_junction(current):
                raise GroundRawQueryError("拒绝读取符号链接原始文件")
        path = candidate.resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise GroundRawQueryError("拒绝读取数据根之外的原始文件") from exc
        return path


def _time_range(start_time: str, end_time: str) -> tuple[datetime, datetime]:
    now = datetime.now().astimezone()
    end = _parse_time(end_time) or now
    start = _parse_time(start_time) or end - timedelta(minutes=30)
    if start > end:
        raise GroundRawQueryError("开始时间不能晚于结束时间")
    if (end - start) > timedelta(days=7):
        raise GroundRawQueryError("单次原始数据查询最长支持 7 天")
    return start, end


def _parse_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        return None
    return result if result.tzinfo else result.astimezone()


def _matches(
    item: dict[str, Any],
    *,
    train_id: str,
    mr_id: str,
    target_ip: str,
) -> bool:
    return (
        (not train_id or str(item.get("train_id") or "") == train_id)
        and (not mr_id or str(item.get("mr_id") or "") == mr_id)
        and (not target_ip or str(item.get("target_ip") or "") == target_ip)
    )


def _syslog_filter_value(item: dict[str, Any], field: str) -> str:
    value = item.get(field)
    if field == "system_name" and not value:
        value = item.get("hostname")
    return str(value or "").casefold()


def _finish_loss_window(current: dict[str, Any]) -> None:
    started = _parse_time(str(current.get("started_at") or ""))
    ended = _parse_time(str(current.get("ended_at") or ""))
    current["duration_seconds"] = (
        max(0.0, (ended - started).total_seconds())
        if started is not None and ended is not None
        else 0.0
    )


def _is_junction(path: Path) -> bool:
    checker = getattr(path, "is_junction", None)
    return bool(checker and checker())


__all__ = ["GroundRawQueryError", "GroundRawStreamQueryService"]
