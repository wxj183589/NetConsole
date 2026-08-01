from __future__ import annotations

import hashlib
import json
import os
import shutil
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from netconsole.core.interprocess_lock import interprocess_file_lock
from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)
from netconsole.services.ground_unattended.syslog_runtime import (
    WmeshRealtimeParser,
)
from netconsole.services.rail_transit.train_identity import (
    canonical_train_id_for,
)


_ACTIVE_RUN_STATES = {
    "STARTING",
    "RUNNING",
    "PAUSED",
    "STOPPING",
    "FINALIZING",
    "ARCHIVING",
    "ERROR",
}
_REWRITABLE_FILE_STATES = {"CLOSED", "RECOVERED", "PENDING"}


class GroundRawLifecycleError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class GroundSyslogDeletionPlan:
    site_id: str
    run_id: str
    run_date: str
    mode: str
    record_keys: tuple[dict[str, Any], ...]
    filters: dict[str, Any]
    include_derived_events: bool
    files: tuple[dict[str, Any], ...]
    expected_matched_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "site_id": self.site_id,
            "run_id": self.run_id,
            "run_date": self.run_date,
            "mode": self.mode,
            "record_keys": [dict(row) for row in self.record_keys],
            "filters": dict(self.filters),
            "include_derived_events": self.include_derived_events,
            "files": [dict(row) for row in self.files],
            "expected_matched_count": self.expected_matched_count,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "GroundSyslogDeletionPlan":
        return cls(
            site_id=str(value.get("site_id") or ""),
            run_id=str(value.get("run_id") or ""),
            run_date=str(value.get("run_date") or ""),
            mode=str(value.get("mode") or ""),
            record_keys=tuple(
                dict(row) for row in list(value.get("record_keys") or [])
            ),
            filters=dict(value.get("filters") or {}),
            include_derived_events=bool(
                value.get("include_derived_events", True)
            ),
            files=tuple(
                dict(row) for row in list(value.get("files") or [])
            ),
            expected_matched_count=max(
                0, int(value.get("expected_matched_count") or 0)
            ),
        )


@dataclass(frozen=True)
class GroundSyslogDeletionPreview:
    plan: GroundSyslogDeletionPlan | None
    matched_record_count: int
    affected_file_count: int
    affected_event_count: int
    affected_timeline_count: int
    total_bytes: int
    file_statuses: tuple[dict[str, Any], ...]
    archive_status: str
    blocked_reasons: tuple[str, ...]
    warnings: tuple[str, ...]


class GroundRawFileAdapter:
    """Resolve and atomically rewrite registered active NDJSON files."""

    def __init__(self, repository: GroundUnattendedRepository) -> None:
        self.repository = repository
        self.root = repository.db_path.parent.resolve()

    def registered_path(self, relative_path: str) -> Path:
        relative = Path(str(relative_path or ""))
        if (
            not relative.parts
            or relative.is_absolute()
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            raise GroundRawLifecycleError(
                "RAW_FILE_PATH_INVALID",
                "原始文件登记路径无效",
            )
        current = self.root
        for part in relative.parts:
            current = current / part
            if current.is_symlink() or _is_junction(current):
                raise GroundRawLifecycleError(
                    "RAW_FILE_PATH_INVALID",
                    "拒绝改写符号链接或目录联接中的原始文件",
                )
        resolved = current.resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise GroundRawLifecycleError(
                "RAW_FILE_PATH_INVALID",
                "拒绝改写数据根之外的原始文件",
            ) from exc
        return resolved

    @staticmethod
    def lock_path(path: Path) -> Path:
        return path.with_name(f".{path.name}.lifecycle.lock")


class GroundRawDataLifecycleService:
    """Preview and safely rewrite Ground Syslog active raw files."""

    def __init__(self, repository: GroundUnattendedRepository) -> None:
        self.repository = repository
        self.adapter = GroundRawFileAdapter(repository)

    def preview_syslog_deletion(
        self,
        *,
        run_id: str,
        mode: str,
        record_keys: Iterable[dict[str, Any]],
        filters: Mapping[str, Any],
        include_derived_events: bool,
    ) -> GroundSyslogDeletionPreview:
        run = self.repository.get_run(run_id)
        blocked: list[str] = []
        warnings: list[str] = []
        if run is None:
            blocked.append("RUN_NOT_FOUND: 指定的无人值守运行不存在")
            return self._blocked_preview(blocked)
        run_state = str(run.get("state") or "").upper()
        if run_state in _ACTIVE_RUN_STATES:
            blocked.append("RUN_ACTIVE: 当前运行仍在活动或最终化阶段")
        archive = self.repository.get_archive_by_run(run_id)
        archive_status = str((archive or {}).get("archive_status") or "")
        if archive_status in {"READY", "VERIFYING", "DOWNLOADING"}:
            blocked.append(
                "READY_ARCHIVE_IMMUTABLE: 该日志已进入不可变 READY 归档。"
                "需要清理时请删除完整归档。"
            )
        raw_files = [
            row
            for row in self.repository.list_raw_files_for_run(run_id)
            if str(row.get("data_type") or "") == "syslog"
        ]
        if any(
            str(row.get("archive_status") or "") == "ARCHIVED"
            or str(row.get("compressed_path") or "")
            for row in raw_files
        ):
            blocked.append(
                "READY_ARCHIVE_IMMUTABLE: Syslog 已登记进入不可变归档，"
                "不允许记录级改写"
            )
        file_statuses: list[dict[str, Any]] = []
        candidates: list[tuple[dict[str, Any], Path]] = []
        for row in raw_files:
            file_id = str(row.get("file_id") or "")
            status = str(row.get("status") or "").upper()
            exists = False
            try:
                path = self.adapter.registered_path(
                    str(row.get("relative_path") or "")
                )
                exists = path.is_file()
            except GroundRawLifecycleError as exc:
                blocked.append(f"{exc.code}: {exc}")
                path = Path()
            file_statuses.append(
                {
                    "file_id": file_id,
                    "status": status,
                    "archive_status": str(
                        row.get("archive_status") or ""
                    ),
                    "revision": int(row.get("revision") or 0),
                    "exists": exists,
                    "matched_record_count": 0,
                }
            )
            if status == "OPEN":
                blocked.append(
                    f"RAW_FILE_OPEN: 文件 {file_id} 仍由 Syslog Receiver 写入"
                )
            elif status not in _REWRITABLE_FILE_STATES:
                blocked.append(
                    f"RAW_FILE_STATE_BLOCKED: 文件 {file_id} 状态为 {status}"
                )
            if not exists:
                blocked.append(
                    f"RAW_FILE_MISSING: 文件 {file_id} 登记存在但物理文件缺失"
                )
            elif status in _REWRITABLE_FILE_STATES:
                candidates.append((row, path))
        blocked = list(dict.fromkeys(blocked))
        if blocked:
            return GroundSyslogDeletionPreview(
                plan=None,
                matched_record_count=0,
                affected_file_count=0,
                affected_event_count=0,
                affected_timeline_count=0,
                total_bytes=0,
                file_statuses=tuple(file_statuses),
                archive_status=archive_status,
                blocked_reasons=tuple(blocked),
                warnings=tuple(warnings),
            )

        keys = tuple(dict(row) for row in record_keys)
        filter_values = dict(filters)
        matched_refs: list[dict[str, Any]] = []
        matched_bytes = 0
        malformed_count = 0
        affected_files: list[dict[str, Any]] = []
        status_by_id = {
            str(row["file_id"]): row for row in file_statuses
        }
        for registered, path in candidates:
            scan = _scan_syslog_file(
                path,
                file_id=str(registered.get("file_id") or ""),
                mode=mode,
                record_keys=keys,
                filters=filter_values,
            )
            status_by_id[str(registered.get("file_id") or "")][
                "matched_record_count"
            ] = scan["matched_count"]
            matched_refs.extend(scan["matched_refs"])
            matched_bytes += int(scan["matched_bytes"])
            malformed_count += int(scan["malformed_count"])
            if scan["matched_count"]:
                affected_files.append(
                    {
                        "file_id": str(registered.get("file_id") or ""),
                        "relative_path": str(
                            registered.get("relative_path") or ""
                        ),
                        "status": str(registered.get("status") or ""),
                        "archive_status": str(
                            registered.get("archive_status") or ""
                        ),
                        "revision": int(registered.get("revision") or 0),
                        "size_bytes": int(registered.get("size_bytes") or 0),
                        "sha256": str(registered.get("sha256") or ""),
                    }
                )
        effects = self.repository.syslog_derived_effects(
            run_id,
            matched_refs,
            apply=False,
            include_derived_events=include_derived_events,
        )
        if not matched_refs:
            warnings.append("当前删除范围未匹配任何 Syslog 原始记录")
        if malformed_count:
            warnings.append(
                f"检测到 {malformed_count} 条损坏或非对象 NDJSON 行，"
                "为避免误删将原样保留"
            )
        plan = (
            GroundSyslogDeletionPlan(
                site_id=self.repository.site_id,
                run_id=run_id,
                run_date=str(run.get("run_date") or ""),
                mode=mode,
                record_keys=keys,
                filters=filter_values,
                include_derived_events=include_derived_events,
                files=tuple(affected_files),
                expected_matched_count=len(matched_refs),
            )
            if matched_refs
            else None
        )
        return GroundSyslogDeletionPreview(
            plan=plan,
            matched_record_count=len(matched_refs),
            affected_file_count=len(affected_files),
            affected_event_count=int(effects["wmesh"]),
            affected_timeline_count=int(effects["timeline"]),
            total_bytes=matched_bytes,
            file_statuses=tuple(file_statuses),
            archive_status=archive_status,
            blocked_reasons=(),
            warnings=tuple(warnings),
        )

    def execute_syslog_deletion(
        self,
        plan: GroundSyslogDeletionPlan,
        *,
        operation_id: str,
        progress: Callable[[str, int, int, str], None] | None = None,
        check_cancelled: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        if plan.site_id != self.repository.site_id:
            raise GroundRawLifecycleError(
                "SITE_MISMATCH",
                "删除计划局点与当前任务局点不一致",
            )
        run = self.repository.get_run(plan.run_id)
        if run is None:
            raise GroundRawLifecycleError(
                "RUN_NOT_FOUND",
                "指定的无人值守运行不存在",
            )
        if str(run.get("state") or "").upper() in _ACTIVE_RUN_STATES:
            raise GroundRawLifecycleError(
                "RUN_ACTIVE",
                "当前运行仍在活动或最终化阶段",
            )
        archive = self.repository.get_archive_by_run(plan.run_id)
        if str((archive or {}).get("archive_status") or "") in {
            "READY",
            "VERIFYING",
            "DOWNLOADING",
        }:
            raise GroundRawLifecycleError(
                "READY_ARCHIVE_IMMUTABLE",
                "该日志已进入不可变 READY 归档",
            )
        total = max(1, len(plan.files))
        if progress:
            progress("LOCKING_FILES", 0, total, "正在锁定 Syslog 原始文件")
        with ExitStack() as stack:
            file_rows: list[tuple[dict[str, Any], Path]] = []
            for index, planned in enumerate(
                sorted(plan.files, key=lambda row: str(row.get("file_id") or ""))
            ):
                if check_cancelled:
                    check_cancelled()
                current = self.repository.get_raw_file(
                    str(planned.get("file_id") or "")
                )
                if current is None:
                    raise GroundRawLifecycleError(
                        "RAW_FILE_MISSING",
                        "删除计划中的原始文件登记已不存在",
                    )
                path = self.adapter.registered_path(
                    str(current.get("relative_path") or "")
                )
                try:
                    stack.enter_context(
                        interprocess_file_lock(
                            self.adapter.lock_path(path),
                            timeout_seconds=5.0,
                        )
                    )
                except (OSError, TimeoutError) as exc:
                    raise GroundRawLifecycleError(
                        "RAW_FILE_LOCK_UNAVAILABLE",
                        "无法取得 Syslog 文件生命周期锁，请稍后重试",
                    ) from exc
                _validate_planned_file(current, planned, path)
                file_rows.append((current, path))
                if progress:
                    progress(
                        "LOCKING_FILES",
                        index + 1,
                        total,
                        f"已锁定 {index + 1}/{total} 个文件",
                    )

            staged: list[dict[str, Any]] = []
            matched_refs: list[dict[str, Any]] = []
            if progress:
                progress(
                    "REWRITING_FILES",
                    0,
                    total,
                    "正在生成受控重写文件",
                )
            try:
                for index, (registered, path) in enumerate(file_rows):
                    if check_cancelled:
                        check_cancelled()
                    rewrite = _stage_rewrite(
                        path,
                        file_id=str(registered.get("file_id") or ""),
                        operation_id=operation_id,
                        mode=plan.mode,
                        record_keys=plan.record_keys,
                        filters=plan.filters,
                    )
                    rewrite["registered"] = registered
                    staged.append(rewrite)
                    matched_refs.extend(rewrite["matched_refs"])
                    if progress:
                        progress(
                            "REWRITING_FILES",
                            index + 1,
                            total,
                            f"已校验并重写 {index + 1}/{total} 个文件",
                        )
                if len(matched_refs) != plan.expected_matched_count:
                    raise GroundRawLifecycleError(
                        "RAW_FILE_REVISION_CONFLICT",
                        "删除预览后匹配记录数量已变化，请重新预览",
                    )
                backups: list[tuple[Path, Path]] = []
                replaced: list[tuple[Path, Path]] = []
                try:
                    for rewrite in staged:
                        target = rewrite["path"]
                        backup = target.with_name(
                            f".{target.name}.{operation_id}.bak"
                        )
                        shutil.copy2(target, backup)
                        _fsync_file(backup)
                        backups.append((target, backup))
                        os.replace(rewrite["part_path"], target)
                        replaced.append((target, backup))
                        _verify_replacement(rewrite)
                    if progress:
                        progress(
                            "UPDATING_REGISTRY",
                            total,
                            total,
                            "正在更新 Registry 与派生事件",
                        )
                        progress(
                            "REMOVING_DERIVED_EVENTS",
                            total,
                            total,
                            (
                                "正在按 provenance 删除派生事件"
                                if plan.include_derived_events
                                else "正在标记派生事件的原始来源已删除"
                            ),
                        )
                    metadata = self.repository.apply_syslog_deletion_metadata(
                        plan.run_id,
                        file_updates=[
                            {
                                "file_id": str(
                                    rewrite["registered"].get("file_id") or ""
                                ),
                                "base_revision": int(
                                    rewrite["registered"].get("revision") or 0
                                ),
                                "record_count": rewrite["record_count"],
                                "size_bytes": rewrite["size_bytes"],
                                "sha256": rewrite["sha256"],
                                "start_time": rewrite["start_time"],
                                "end_time": rewrite["end_time"],
                            }
                            for rewrite in staged
                        ],
                        record_refs=matched_refs,
                        include_derived_events=plan.include_derived_events,
                    )
                except Exception:
                    rollback_errors: list[str] = []
                    for target, backup in reversed(replaced):
                        try:
                            os.replace(backup, target)
                        except OSError as exc:
                            rollback_errors.append(
                                f"{target.name}: {exc.__class__.__name__}"
                            )
                    if rollback_errors:
                        raise GroundRawLifecycleError(
                            "RAW_FILE_ROLLBACK_FAILED",
                            "原始文件回滚失败：" + "；".join(rollback_errors),
                        )
                    raise
                finally:
                    for _target, backup in backups:
                        backup.unlink(missing_ok=True)
                if progress:
                    progress(
                        "VERIFYING",
                        total,
                        total,
                        "Syslog 删除结果校验完成",
                    )
                return {
                    "deleted_record_count": len(matched_refs),
                    "affected_file_count": len(staged),
                    "deleted_event_count": int(metadata["wmesh"])
                    + int(metadata["timeline"]),
                    "deleted_wmesh_event_count": int(metadata["wmesh"]),
                    "deleted_timeline_count": int(metadata["timeline"]),
                    "revision_before": {
                        str(row.get("file_id") or ""): int(
                            row.get("revision") or 0
                        )
                        for row in plan.files
                    },
                    "revision_after": dict(metadata["revision_after"]),
                }
            finally:
                for rewrite in staged:
                    Path(rewrite["part_path"]).unlink(missing_ok=True)

    @staticmethod
    def _blocked_preview(
        blocked: list[str],
    ) -> GroundSyslogDeletionPreview:
        return GroundSyslogDeletionPreview(
            plan=None,
            matched_record_count=0,
            affected_file_count=0,
            affected_event_count=0,
            affected_timeline_count=0,
            total_bytes=0,
            file_statuses=(),
            archive_status="",
            blocked_reasons=tuple(blocked),
            warnings=(),
        )


def _validate_planned_file(
    current: Mapping[str, Any],
    planned: Mapping[str, Any],
    path: Path,
) -> None:
    if not path.is_file():
        raise GroundRawLifecycleError(
            "RAW_FILE_MISSING",
            "原始文件登记存在但物理文件缺失",
        )
    if str(current.get("data_type") or "") != "syslog":
        raise GroundRawLifecycleError(
            "RAW_FILE_TYPE_MISMATCH",
            "删除计划包含非 Syslog 原始文件",
        )
    if str(current.get("status") or "").upper() not in _REWRITABLE_FILE_STATES:
        raise GroundRawLifecycleError(
            "RAW_FILE_STATE_BLOCKED",
            "原始文件当前状态禁止记录级改写",
        )
    if (
        str(current.get("archive_status") or "") == "ARCHIVED"
        or str(current.get("compressed_path") or "")
    ):
        raise GroundRawLifecycleError(
            "READY_ARCHIVE_IMMUTABLE",
            "原始文件已进入不可变归档",
        )
    if int(current.get("revision") or 0) != int(
        planned.get("revision") or 0
    ):
        raise GroundRawLifecycleError(
            "RAW_FILE_REVISION_CONFLICT",
            "原始文件 revision 已变化，请重新预览",
        )


def _scan_syslog_file(
    path: Path,
    *,
    file_id: str,
    mode: str,
    record_keys: Iterable[dict[str, Any]],
    filters: Mapping[str, Any],
) -> dict[str, Any]:
    matched_refs: list[dict[str, Any]] = []
    matched_bytes = 0
    malformed_count = 0
    parser = WmeshRealtimeParser()
    with path.open("rb") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            record = _decode_record(raw_line)
            if record is None:
                malformed_count += 1
                continue
            if _matches_delete_scope(
                record,
                file_id=file_id,
                line_number=line_number,
                mode=mode,
                record_keys=record_keys,
                filters=filters,
                parser=parser,
            ):
                matched_refs.append(
                    _record_reference(record, file_id, line_number)
                )
                matched_bytes += len(raw_line)
    return {
        "matched_count": len(matched_refs),
        "matched_refs": matched_refs,
        "matched_bytes": matched_bytes,
        "malformed_count": malformed_count,
    }


def _stage_rewrite(
    path: Path,
    *,
    file_id: str,
    operation_id: str,
    mode: str,
    record_keys: Iterable[dict[str, Any]],
    filters: Mapping[str, Any],
) -> dict[str, Any]:
    part_path = path.with_name(f".{path.name}.{operation_id}.part")
    matched_refs: list[dict[str, Any]] = []
    record_count = 0
    timestamps: list[str] = []
    digest = hashlib.sha256()
    parser = WmeshRealtimeParser()
    with path.open("rb") as source, part_path.open("xb") as target:
        for line_number, raw_line in enumerate(source, start=1):
            record = _decode_record(raw_line)
            delete = record is not None and _matches_delete_scope(
                record,
                file_id=file_id,
                line_number=line_number,
                mode=mode,
                record_keys=record_keys,
                filters=filters,
                parser=parser,
            )
            if delete:
                matched_refs.append(
                    _record_reference(record, file_id, line_number)
                )
                continue
            target.write(raw_line)
            digest.update(raw_line)
            record_count += 1
            if record is not None:
                timestamp = str(record.get("receive_time") or "")
                if timestamp:
                    timestamps.append(timestamp)
        target.flush()
        os.fsync(target.fileno())
    return {
        "path": path,
        "part_path": part_path,
        "matched_refs": matched_refs,
        "record_count": record_count,
        "size_bytes": part_path.stat().st_size,
        "sha256": digest.hexdigest(),
        "start_time": min(timestamps, default=""),
        "end_time": max(timestamps, default=""),
    }


def _matches_delete_scope(
    record: dict[str, Any],
    *,
    file_id: str,
    line_number: int,
    mode: str,
    record_keys: Iterable[dict[str, Any]],
    filters: Mapping[str, Any],
    parser: WmeshRealtimeParser,
) -> bool:
    if mode == "RUN_ALL":
        return True
    if mode == "SELECTED":
        candidate = _record_reference(record, file_id, line_number)
        return any(
            _selected_key_matches(candidate, key) for key in record_keys
        )
    if mode != "FILTERED":
        raise GroundRawLifecycleError(
            "DELETE_MODE_INVALID",
            "Syslog 删除模式无效",
        )
    if (
        (
            filters.get("event_type")
            or filters.get("event_family")
            or filters.get("cfg_command_source")
            or filters.get("physical_state")
            or filters.get("correlation_status")
            or filters.get("correlation_confidence")
            or filters.get("peer_name")
        )
        and not record.get("event_type")
        and record.get("raw_text")
    ):
        received = _parse_time(str(record.get("receive_time") or ""))
        parsed = (
            parser.parse(str(record["raw_text"]), receive_time=received)
            if received is not None
            else None
        )
        if parsed:
            record = {**record, **parsed}
    for field in (
        "train_id",
        "mr_name",
        "source_ip",
        "system_name",
        "mr_role",
        "facility",
        "severity",
        "identity_status",
        "event_type",
        "event_family",
        "cfg_command_source",
        "physical_state",
        "correlation_status",
        "correlation_confidence",
        "peer_name",
        "data_source",
    ):
        expected = str(filters.get(field) or "").casefold()
        if not expected:
            continue
        if field == "train_id":
            actual = canonical_train_id_for(record.get(field)).casefold()
        elif field == "system_name":
            actual = str(
                record.get(field) or record.get("hostname") or ""
            ).casefold()
        elif field == "peer_name":
            actual = str(
                record.get(field) or record.get("peer_mac") or ""
            ).casefold()
        elif field == "data_source":
            actual = "active"
        else:
            actual = str(record.get(field) or "").casefold()
        if expected not in actual:
            return False
    mr_id = str(filters.get("mr_id") or "").casefold()
    if mr_id and mr_id not in str(
        record.get("device_uuid") or record.get("mr_id") or ""
    ).casefold():
        return False
    keyword = str(filters.get("keyword") or "").casefold()
    if keyword and keyword not in str(record.get("raw_text") or "").casefold():
        return False
    received = _parse_time(str(record.get("receive_time") or ""))
    start = _parse_time(str(filters.get("start_time") or ""))
    end = _parse_time(str(filters.get("end_time") or ""))
    if start is not None and (received is None or received < start):
        return False
    if end is not None and (received is None or received > end):
        return False
    return True


def _selected_key_matches(
    candidate: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> bool:
    if str(candidate.get("raw_file_id") or "") != str(
        expected.get("raw_file_id") or ""
    ):
        return False
    for field in (
        "global_receive_sequence",
        "source_receive_sequence",
        "raw_line_number",
    ):
        value = _optional_int(expected.get(field))
        if value is not None and _optional_int(candidate.get(field)) != value:
            return False
    return True


def _record_reference(
    record: Mapping[str, Any],
    file_id: str,
    line_number: int,
) -> dict[str, Any]:
    return {
        "raw_file_id": file_id,
        "global_receive_sequence": _optional_int(
            record.get("global_receive_sequence")
        ),
        "source_receive_sequence": _optional_int(
            record.get("source_receive_sequence")
        ),
        "raw_line_number": line_number,
    }


def _decode_record(raw_line: bytes) -> dict[str, Any] | None:
    try:
        value = json.loads(raw_line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _parse_time(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.astimezone()


def _optional_int(value: object) -> int | None:
    if value in {None, ""}:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_junction(path: Path) -> bool:
    checker = getattr(path, "is_junction", None)
    try:
        return bool(checker()) if callable(checker) else False
    except OSError:
        return True


def _fsync_file(path: Path) -> None:
    with path.open("r+b") as handle:
        os.fsync(handle.fileno())


def _verify_replacement(rewrite: Mapping[str, Any]) -> None:
    path = Path(rewrite["path"])
    if (
        not path.is_file()
        or path.stat().st_size != int(rewrite["size_bytes"])
        or _sha256_file(path) != str(rewrite["sha256"])
    ):
        raise GroundRawLifecycleError(
            "RAW_FILE_REWRITE_VERIFY_FAILED",
            "Syslog 原始文件原子替换后的大小或 SHA-256 校验失败",
        )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "GroundRawDataLifecycleService",
    "GroundRawFileAdapter",
    "GroundRawLifecycleError",
    "GroundSyslogDeletionPlan",
    "GroundSyslogDeletionPreview",
]
