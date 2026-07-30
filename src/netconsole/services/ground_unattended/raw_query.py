from __future__ import annotations

import hashlib
import heapq
import json
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)
from netconsole.services.ground_unattended.archive_reader import (
    GroundArchiveInspection,
    GroundArchiveReadError,
    GroundArchiveReader,
)
from netconsole.services.ground_unattended.syslog_runtime import (
    WmeshRealtimeParser,
)
from netconsole.services.rail_transit.train_identity import (
    canonical_train_id_for,
    train_identity_matches,
)


MAX_QUERY_FILES = 256
MAX_QUERY_RECORDS = 1_000_000
MAX_QUERY_BYTES = 256 * 1024**2
MAX_QUERY_SECONDS = 12.0
MAX_SYSLOG_QUERY_FILES = 128
MAX_SYSLOG_QUERY_RECORDS = 250_000
MAX_SYSLOG_QUERY_BYTES = 128 * 1024**2
MAX_SYSLOG_QUERY_SECONDS = 8.0
MAX_MIXED_DEDUP_KEYS = 250_000


class GroundRawQueryError(ValueError):
    def __init__(self, message: str, *, code: str = "RAW_QUERY_REJECTED") -> None:
        super().__init__(message)
        self.code = code


class GroundRawStreamQueryService:
    """对 active/READY ZIP 中已登记 NDJSON 执行有界、只读查询。"""

    def __init__(self, repository: GroundUnattendedRepository) -> None:
        self.repository = repository
        self.root = repository.db_path.parent.resolve()
        self.archive_reader = GroundArchiveReader(repository)

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
        start, end = self._time_range(
            run_id,
            start_time,
            end_time,
            data_type="ping",
            train_id=train_id,
            mr_id=mr_id,
        )
        diagnostics = _new_diagnostics(run_id, start, end)
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
            data_type="ping",
            run_id=run_id,
            train_id=train_id,
            mr_id=mr_id,
            start=start,
            end=end,
            time_key="ts",
            diagnostics=diagnostics,
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
        self._finish_diagnostics(
            diagnostics,
            matched_count=counts["raw"],
            run_id=run_id,
            data_type="ping",
        )
        if counts["raw"] == 0 and diagnostics["files_scanned"]:
            diagnostics["no_data_reason"] = (
                "TARGET_NOT_FOUND" if target_ip else "NO_SAMPLES"
            )
        return {
            "raw_sample_count": counts["raw"],
            "effective_sample_count": counts["effective"],
            "ignored_sample_count": counts["ignored"],
            "points": points,
            "loss_windows": loss_windows,
            "ap_transitions": ap_transitions[:max_points],
            "position_segments": position_segments[:max_points],
            "diagnostics": diagnostics,
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
        start, end = self._time_range(
            run_id,
            start_time,
            end_time,
            data_type="ping",
            train_id=train_id,
            mr_id=mr_id,
        )
        diagnostics = _new_diagnostics(run_id, start, end)
        page = max(1, min(int(page), 200))
        page_size = max(1, min(int(page_size), 500))
        keep_count = page * page_size
        matched: list[tuple[float, int, dict[str, Any]]] = []
        counts = {"raw": 0, "effective": 0, "ignored": 0}
        serial = 0
        for item in self._records(
            data_type="ping",
            run_id=run_id,
            train_id=train_id,
            mr_id=mr_id,
            start=start,
            end=end,
            time_key="ts",
            diagnostics=diagnostics,
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
        total = (
            counts["effective"] + counts["ignored"]
            if include_warmup
            else counts["effective"]
        )
        self._finish_diagnostics(
            diagnostics,
            matched_count=counts["raw"],
            run_id=run_id,
            data_type="ping",
        )
        return {
            "items": matched_items[offset : offset + page_size],
            "total": total,
            "page": page,
            "page_size": page_size,
            "raw_sample_count": counts["raw"],
            "effective_sample_count": counts["effective"],
            "ignored_sample_count": counts["ignored"],
            "diagnostics": diagnostics,
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
        mr_role: str = "",
        facility: str = "",
        severity: str = "",
        identity_status: str = "",
        event_type: str = "",
        peer_name: str = "",
        data_source: str = "",
        keyword: str = "",
        start_time: str = "",
        end_time: str = "",
        page: int = 1,
        page_size: int = 100,
    ) -> dict[str, Any]:
        registered_train_id = self._registered_train_id(
            run_id,
            train_id,
            data_type="syslog",
        )
        start, end = self._time_range(
            run_id,
            start_time,
            end_time,
            data_type="syslog",
            train_id=registered_train_id,
            mr_id=mr_id,
            mr_role=mr_role,
        )
        diagnostics = _new_diagnostics(run_id, start, end)
        page = max(1, min(int(page), 200))
        page_size = max(1, min(int(page_size), 500))
        keep_count = page * page_size
        rows: list[tuple[float, int, dict[str, Any]]] = []
        matched_count = 0
        serial = 0
        filters = {
            "train_id": canonical_train_id_for(train_id).casefold(),
            "device_uuid": mr_id.casefold(),
            "mr_name": mr_name.casefold(),
            "source_ip": source_ip.casefold(),
            "system_name": system_name.casefold(),
            "mr_role": mr_role.casefold(),
            "facility": facility.casefold(),
            "severity": severity.casefold(),
            "identity_status": identity_status.casefold(),
            "event_type": event_type.casefold(),
            "peer_name": peer_name.casefold(),
            "data_source": data_source.casefold(),
        }
        keyword_value = keyword.casefold()
        parser = WmeshRealtimeParser()
        requires_parsed_fields = bool(filters["event_type"] or filters["peer_name"])
        record_level_filters = (
            mr_name,
            source_ip,
            system_name,
            facility,
            severity,
            identity_status,
            event_type,
            peer_name,
            data_source,
            keyword,
        )
        latest_page_fast_path = not any(record_level_filters) and not (
            train_id and not registered_train_id
        )

        def stop_before_older_file(registered: dict[str, Any]) -> bool:
            if not latest_page_fast_path or len(rows) < keep_count:
                return False
            registered_end = _parse_time(
                str(
                    registered.get("end_time")
                    or registered.get("start_time")
                    or ""
                )
            )
            return (
                registered_end is not None
                and registered_end.timestamp() < rows[0][0]
            )

        for item in self._records(
            data_type="syslog",
            run_id=run_id,
            train_id=registered_train_id,
            mr_id=mr_id,
            mr_role=mr_role,
            start=start,
            end=end,
            time_key="receive_time",
            diagnostics=diagnostics,
            newest_first=latest_page_fast_path,
            stop_before_file=stop_before_older_file,
        ):
            if requires_parsed_fields:
                _enrich_legacy_syslog(item, parser)
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
        self._finish_diagnostics(
            diagnostics,
            matched_count=matched_count,
            run_id=run_id,
            data_type="syslog",
        )
        total_exact = not (
            diagnostics["truncated"] or diagnostics["optimized_latest_page"]
        )
        total = (
            max(
                matched_count,
                int(diagnostics.get("registered_record_count") or 0),
            )
            if diagnostics["optimized_latest_page"]
            else matched_count
        )
        return {
            "items": row_items[offset : offset + page_size],
            "total": total,
            "total_exact": total_exact,
            "page": page,
            "page_size": page_size,
            "diagnostics": diagnostics,
        }

    def _registered_train_id(
        self,
        run_id: str,
        train_id: str,
        *,
        data_type: str,
    ) -> str:
        if not run_id or not train_id:
            return train_id
        registered_ids = {
            str(row.get("train_id") or "")
            for row in self.repository.list_raw_files_for_run(run_id)
            if str(row.get("data_type") or "") == data_type
            and str(row.get("train_id") or "")
        }
        matches = [
            registered_id
            for registered_id in registered_ids
            if train_identity_matches((train_id,), (registered_id,))
        ]
        if len(matches) == 1:
            return matches[0]
        return "" if matches else train_id

    def _finish_diagnostics(
        self,
        diagnostics: dict[str, Any],
        *,
        matched_count: int,
        run_id: str,
        data_type: str,
    ) -> None:
        _finish_diagnostics(diagnostics, matched_count=matched_count)
        if (
            diagnostics["data_availability"] == "MISSING"
            and run_id
            and self._has_summary(run_id, data_type)
        ):
            diagnostics["data_availability"] = "SUMMARY_ONLY"
            diagnostics["no_data_reason"] = "SUMMARY_ONLY"

    def _has_summary(self, run_id: str, data_type: str) -> bool:
        if data_type == "ping" and self.repository.list_ping_summaries(run_id):
            return True
        run = self.repository.get_run(run_id) or {}
        raw_summary = run.get("summary")
        summary = raw_summary if isinstance(raw_summary, Mapping) else {}
        key = "ping_sample_count" if data_type == "ping" else "syslog_record_count"
        return bool(int(summary.get(key) or 0))

    def _records(
        self,
        *,
        data_type: str,
        run_id: str,
        train_id: str,
        mr_id: str,
        start: datetime,
        end: datetime,
        time_key: str,
        diagnostics: dict[str, Any],
        mr_role: str = "",
        newest_first: bool = False,
        stop_before_file: Callable[[dict[str, Any]], bool] | None = None,
    ) -> Iterator[dict[str, Any]]:
        max_query_files = (
            MAX_SYSLOG_QUERY_FILES
            if data_type == "syslog"
            else MAX_QUERY_FILES
        )
        files = self.repository.list_raw_files_for_query(
            data_type=data_type,
            start_time=start.isoformat(),
            end_time=end.isoformat(),
            run_id=run_id,
            train_id=train_id,
            device_uuid=mr_id,
            mr_role=mr_role,
            limit=max_query_files + 1,
            newest_first=newest_first,
        )
        diagnostics["files_considered"] = len(files)
        if len(files) > max_query_files:
            diagnostics["truncated"] = True
            files = files[:max_query_files]
        diagnostics["registered_record_count"] = sum(
            max(0, int(row.get("record_count") or 0)) for row in files
        )

        inspection: GroundArchiveInspection | None = None
        archive_checked = False
        registered_paths = [
            self._registered_path(str(row.get("relative_path") or ""))
            for row in files
        ]
        mixed_sources_possible = any(path.is_file() for path in registered_paths) and any(
            not path.is_file() for path in registered_paths
        )
        seen: set[str] | None = set() if mixed_sources_possible else None
        started = time.monotonic()
        unavailable_files = 0

        for registered, path in zip(files, registered_paths, strict=True):
            if _budget_exhausted(
                diagnostics,
                started,
                data_type=data_type,
            ):
                diagnostics["truncated"] = True
                break
            if stop_before_file is not None and stop_before_file(registered):
                diagnostics["optimized_latest_page"] = True
                break
            source = "ACTIVE"
            archive_entry = ""
            lines: Iterator[tuple[bytes, str]]
            if path.is_file():
                lines = _active_lines(path)
            else:
                if not archive_checked:
                    archive_checked = True
                    try:
                        inspection = (
                            self.archive_reader.inspect_run(
                                run_id, full_integrity=False
                            )
                            if run_id
                            else None
                        )
                    except GroundArchiveReadError as exc:
                        diagnostics["data_availability"] = "CORRUPT"
                        diagnostics["no_data_reason"] = "ARCHIVE_INTEGRITY_FAILED"
                        raise GroundRawQueryError(
                            f"历史归档损坏或完整性校验失败：{exc}",
                            code="RAW_ARCHIVE_CORRUPT",
                        ) from exc
                if inspection is None:
                    unavailable_files += 1
                    diagnostics["_archive_unavailable"] = True
                    continue
                source = "ARCHIVE"
                diagnostics["legacy_archive"] = (
                    diagnostics["legacy_archive"] or inspection.legacy_manifest
                )
                try:
                    lines = self.archive_reader.iter_registered_lines(
                        inspection, registered
                    )
                except GroundArchiveReadError as exc:
                    diagnostics["data_availability"] = "CORRUPT"
                    diagnostics["no_data_reason"] = "ARCHIVE_MEMBER_MISSING"
                    raise GroundRawQueryError(
                        f"历史归档缺少已登记的原始文件：{exc}",
                        code="RAW_ARCHIVE_CORRUPT",
                    ) from exc
            diagnostics["files_scanned"] += 1
            sources = set(diagnostics.pop("_sources", []))
            sources.add(source)
            diagnostics["_sources"] = sorted(sources)

            try:
                for line_number, (line, entry) in enumerate(lines, start=1):
                    diagnostics["bytes_scanned"] += len(line)
                    diagnostics["records_scanned"] += 1
                    archive_entry = entry
                    if _budget_exhausted(
                        diagnostics,
                        started,
                        data_type=data_type,
                    ):
                        diagnostics["truncated"] = True
                        break
                    try:
                        item = json.loads(line.decode("utf-8"))
                    except (
                        TypeError,
                        UnicodeDecodeError,
                        json.JSONDecodeError,
                    ):
                        diagnostics["malformed_record_count"] += 1
                        continue
                    if not isinstance(item, dict):
                        diagnostics["malformed_record_count"] += 1
                        continue
                    ts = _parse_time(str(item.get(time_key) or ""))
                    if ts is None or ts < start or ts > end:
                        continue
                    if seen is not None:
                        dedup_key = _record_key(data_type, item, line)
                        if dedup_key in seen:
                            diagnostics["duplicate_record_count"] += 1
                            continue
                        if len(seen) >= MAX_MIXED_DEDUP_KEYS:
                            diagnostics["truncated"] = True
                            break
                        seen.add(dedup_key)
                    item["raw_file_id"] = str(registered.get("file_id") or "")
                    item["raw_line_number"] = line_number
                    item["raw_file_status"] = str(
                        registered.get("status") or ""
                    )
                    item["data_source"] = source
                    item["archive_entry"] = archive_entry if source == "ARCHIVE" else ""
                    yield item
                if diagnostics["truncated"]:
                    break
            except OSError as exc:
                raise GroundRawQueryError(
                    f"无法读取已登记的 {data_type} 原始文件"
                ) from exc
            except GroundArchiveReadError as exc:
                diagnostics["data_availability"] = "CORRUPT"
                diagnostics["no_data_reason"] = "ARCHIVE_READ_FAILED"
                raise GroundRawQueryError(
                    f"无法读取历史归档：{exc}",
                    code="RAW_ARCHIVE_CORRUPT",
                ) from exc

        if unavailable_files:
            diagnostics["_unavailable_files"] = unavailable_files

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

    def _time_range(
        self,
        run_id: str,
        start_time: str,
        end_time: str,
        *,
        data_type: str = "",
        train_id: str = "",
        mr_id: str = "",
        mr_role: str = "",
    ) -> tuple[datetime, datetime]:
        now = datetime.now().astimezone()
        start = _parse_time(start_time)
        end = _parse_time(end_time)
        run: dict[str, Any] | None = None
        raw_start: datetime | None = None
        raw_end: datetime | None = None
        if run_id:
            run = self.repository.get_run(run_id)
            raw_files = self.repository.list_raw_files_for_run(run_id)
            if run is None and not raw_files:
                raise GroundRawQueryError("指定的无人值守运行不存在")
            raw_times = [
                row
                for row in raw_files
                if (not data_type or str(row.get("data_type") or "") == data_type)
                and (not train_id or str(row.get("train_id") or "") == train_id)
                and (
                    not mr_id
                    or str(row.get("device_uuid") or "") == mr_id
                )
                and (not mr_role or str(row.get("mr_role") or "") == mr_role)
            ]
            starts = [
                parsed
                for row in raw_times
                if (
                    parsed := _parse_time(str(row.get("start_time") or ""))
                )
                is not None
            ]
            ends = [
                parsed
                for row in raw_times
                if (
                    parsed := _parse_time(
                        str(row.get("end_time") or row.get("start_time") or "")
                    )
                )
                is not None
            ]
            raw_start = min(starts, default=None)
            raw_end = max(ends, default=None)
        if run is not None:
            if start is None:
                start = _first_time(
                    run.get("actual_started_at"),
                    raw_start,
                    run.get("scheduled_start_at"),
                    run.get("created_at"),
                )
            if end is None:
                end = _first_time(
                    run.get("actual_ended_at"),
                    raw_end,
                    run.get("scheduled_end_at")
                    if str(run.get("state") or "")
                    in {"COMPLETED", "ERROR"}
                    else None,
                    run.get("updated_at")
                    if str(run.get("state") or "")
                    in {"COMPLETED", "ERROR"}
                    else None,
                )
                if end is None:
                    end = now
        end = end or now
        start = start or end - timedelta(minutes=30)
        if start > end:
            raise GroundRawQueryError("开始时间不能晚于结束时间")
        if (end - start) > timedelta(days=7):
            raise GroundRawQueryError("单次原始数据查询最长支持 7 天")
        return start, end


def _new_diagnostics(
    run_id: str, start: datetime, end: datetime
) -> dict[str, Any]:
    return {
        "requested_run_id": run_id,
        "resolved_start_time": start.isoformat(timespec="milliseconds"),
        "resolved_end_time": end.isoformat(timespec="milliseconds"),
        "source_kind": "NONE",
        "data_availability": "MISSING",
        "files_considered": 0,
        "files_scanned": 0,
        "registered_record_count": 0,
        "records_scanned": 0,
        "bytes_scanned": 0,
        "malformed_record_count": 0,
        "duplicate_record_count": 0,
        "truncated": False,
        "optimized_latest_page": False,
        "legacy_archive": False,
        "no_data_reason": "",
    }


def _finish_diagnostics(
    diagnostics: dict[str, Any], *, matched_count: int
) -> None:
    sources = set(diagnostics.pop("_sources", []))
    unavailable = int(diagnostics.pop("_unavailable_files", 0))
    archive_unavailable = bool(diagnostics.pop("_archive_unavailable", False))
    if sources == {"ACTIVE", "ARCHIVE"}:
        diagnostics["source_kind"] = "MIXED"
    elif sources:
        diagnostics["source_kind"] = next(iter(sources))
    if diagnostics.get("data_availability") == "CORRUPT":
        return
    if not diagnostics["files_considered"]:
        diagnostics["data_availability"] = "MISSING"
        diagnostics["no_data_reason"] = "NO_REGISTERED_FILES"
    elif not diagnostics["files_scanned"]:
        diagnostics["data_availability"] = "MISSING"
        diagnostics["no_data_reason"] = (
            "ARCHIVE_NOT_READY" if archive_unavailable else "RAW_FILE_MISSING"
        )
    else:
        diagnostics["data_availability"] = (
            "MIXED"
            if sources == {"ACTIVE", "ARCHIVE"}
            else "ACTIVE_RAW"
            if sources == {"ACTIVE"}
            else "ARCHIVED_RAW"
            if sources == {"ARCHIVE"}
            else "MISSING"
        )
    if (
        diagnostics["truncated"]
        or unavailable
        or diagnostics["malformed_record_count"]
    ):
        diagnostics["no_data_reason"] = (
            "QUERY_BUDGET_REACHED"
            if diagnostics["truncated"]
            else "SOME_RAW_FILES_MISSING"
            if unavailable
            else "MALFORMED_RECORDS_SKIPPED"
        )
    elif matched_count == 0 and diagnostics["files_scanned"]:
        diagnostics["no_data_reason"] = "FILTER_NO_MATCH"


def _budget_exhausted(
    diagnostics: dict[str, Any],
    started: float,
    *,
    data_type: str,
) -> bool:
    max_records = (
        MAX_SYSLOG_QUERY_RECORDS
        if data_type == "syslog"
        else MAX_QUERY_RECORDS
    )
    max_bytes = (
        MAX_SYSLOG_QUERY_BYTES
        if data_type == "syslog"
        else MAX_QUERY_BYTES
    )
    max_seconds = (
        MAX_SYSLOG_QUERY_SECONDS
        if data_type == "syslog"
        else MAX_QUERY_SECONDS
    )
    return (
        int(diagnostics["records_scanned"]) >= max_records
        or int(diagnostics["bytes_scanned"]) >= max_bytes
        or time.monotonic() - started >= max_seconds
    )


def _active_lines(path: Path) -> Iterator[tuple[bytes, str]]:
    with path.open("rb") as handle:
        for line in handle:
            yield line, ""


def _record_key(data_type: str, item: dict[str, Any], raw: bytes) -> str:
    if data_type == "ping":
        stable = item.get("sample_id") or (
            str(item.get("target_ip") or ""),
            str(item.get("ts") or ""),
            item.get("seq"),
        )
    else:
        stable = item.get("global_receive_sequence") or (
            str(item.get("source_ip") or ""),
            item.get("source_receive_sequence"),
            str(item.get("receive_time") or ""),
        )
    if stable in {"", None, ("", None, "")}:
        return hashlib.sha256(raw).hexdigest()
    return f"{data_type}:{stable!r}"


def _parse_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return result if result.tzinfo else result.astimezone()


def _first_time(*values: object) -> datetime | None:
    for value in values:
        parsed = _parse_time(str(value or ""))
        if parsed is not None:
            return parsed
    return None


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
    if field == "train_id":
        return canonical_train_id_for(value).casefold()
    if field == "system_name" and not value:
        value = item.get("hostname")
    if field == "peer_name" and not value:
        value = item.get("peer_mac")
    return str(value or "").casefold()


def _enrich_legacy_syslog(
    item: dict[str, Any], parser: WmeshRealtimeParser
) -> None:
    if item.get("event_type") or not item.get("raw_text"):
        return
    receive_time = _parse_time(str(item.get("receive_time") or ""))
    if receive_time is None:
        return
    parsed = parser.parse(str(item["raw_text"]), receive_time=receive_time)
    if not parsed:
        return
    details = parsed.get("details") or {}
    item.update(
        {
            "display_enriched": True,
            "event_type": parsed.get("event_type", ""),
            "peer_name": parsed.get("peer_name", ""),
            "peer_mac": parsed.get("peer_mac", ""),
            "previous_peer_name": parsed.get("previous_peer_name", ""),
            "previous_peer_mac": parsed.get("previous_peer_mac", ""),
            "peer_radio_mac": details.get("new_peer_radio_mac", ""),
            "previous_peer_radio_mac": details.get("old_peer_radio_mac", ""),
            "rssi": details.get("rssi", details.get("new_rssi")),
            "previous_rssi": details.get("old_rssi"),
            "reason_code": details.get("reason_code", ""),
            "reason_text": details.get("reason_raw", ""),
            "parsed_details": details,
        }
    )


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
    try:
        return bool(checker()) if callable(checker) else False
    except OSError:
        return True


__all__ = ["GroundRawQueryError", "GroundRawStreamQueryService"]
