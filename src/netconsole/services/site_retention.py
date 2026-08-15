from __future__ import annotations

import binascii
import hashlib
import json
import os
import re
import sqlite3
import zipfile
import zlib
from collections import Counter, defaultdict
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from netconsole.core.atomic_file import atomic_write_bytes
from netconsole.core.paths import PathResolver
from netconsole.services.database_upgrade.coordinator import (
    database_maintenance_lock,
    site_database_maintenance_key,
)
from netconsole.services.database_upgrade.sqlite_consistency import sha256_file
from netconsole.services.database_footprint_maintenance import (
    DEVELOPMENT_ROOT,
    assert_development_path,
)
from netconsole.services.site_storage import (
    SiteRegistryRepository,
    SiteStorageError,
    storage_lock,
)


BACKUP_ARCHIVE_DAYS = 30
BACKUP_DELETE_DAYS = 90
ONLINE_MR_RAW_ARCHIVE_DAYS = 30
TASK_EVENT_RETENTION_DAYS = 90
ROLLBACK_KEEP_COUNT = 2

_DATABASE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}
_RAW_SUFFIXES = {".cap", ".log", ".meshlog", ".pcap", ".pcapng"}
_ACTIVE_TASK_STATES = {"PENDING", "STARTING", "RUNNING", "STOPPING"}
_SCHEMA_DATE_RE = re.compile(r"^(\d{4})\.(\d{2})\.(\d{2})(?:\.|$)")
_RETAIN_MARKERS = {".retain", "keep.json", "retain.json"}


class SiteRetentionService:
    """Scan and apply explicit, evidence-based retention for one site."""

    def __init__(
        self,
        paths: PathResolver,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.paths = paths
        self.registry = SiteRegistryRepository(paths)
        self._now = now or (lambda: datetime.now(UTC))

    def scan(
        self,
        site_id: str,
        *,
        persist: bool = True,
        check_cancel: Callable[[], None] | None = None,
        progress: Callable[[int, int, str], None] | None = None,
    ) -> dict[str, object]:
        record = self.registry.get(site_id)
        with database_maintenance_lock(
            self.paths, site_database_maintenance_key(record.site_id)
        ):
            return self._scan_unlocked(
                record.site_id,
                persist=persist,
                check_cancel=check_cancel,
                progress=progress,
            )

    def _scan_unlocked(
        self,
        site_id: str,
        *,
        persist: bool,
        check_cancel: Callable[[], None] | None,
        progress: Callable[[int, int, str], None] | None,
    ) -> dict[str, object]:
        record = self.registry.get(site_id)
        root = record.root_path.resolve()
        self._assert_site_root(root)
        now = self._normalized_now()

        candidates: list[dict[str, object]] = []
        if progress:
            progress(0, 4, "正在统计局点文件")
        totals = self._storage_totals(root, check_cancel=check_cancel)
        if check_cancel:
            check_cancel()

        if progress:
            progress(1, 4, "正在分类数据库和历史备份")
        candidates.extend(self._scan_databases(root, now))
        if check_cancel:
            check_cancel()

        if progress:
            progress(2, 4, "正在核验 Online MR 原始数据归档")
        candidates.extend(self._scan_online_mr_raw(root, now, check_cancel))
        if check_cancel:
            check_cancel()

        if progress:
            progress(3, 4, "正在统计任务历史")
        task_candidate = self._scan_task_history(root, now)
        if task_candidate is not None:
            candidates.append(task_candidate)

        candidates.sort(
            key=lambda item: (
                str(item.get("category") or ""),
                not bool(item.get("safe")),
                -int(item.get("size_bytes") or 0),
                str(item.get("relative_path") or ""),
            )
        )
        actionable = [
            item
            for item in candidates
            if bool(item.get("safe"))
            and str(item.get("recommended_action") or "")
            in {"archive", "delete", "purge"}
        ]
        token = self._scan_token(record.site_id, actionable)
        report: dict[str, object] = {
            "scan_token": token,
            "site_id": record.site_id,
            "display_name": record.display_name,
            "generated_at": now.isoformat(timespec="seconds"),
            "policy": {
                "backup_archive_days": BACKUP_ARCHIVE_DAYS,
                "backup_delete_days": BACKUP_DELETE_DAYS,
                "online_mr_raw_archive_days": ONLINE_MR_RAW_ARCHIVE_DAYS,
                "task_event_retention_days": TASK_EVENT_RETENTION_DAYS,
                "task_retention_status": "USER_POLICY_REQUIRED",
                "typed_task_retention_apply_enabled": False,
                "typed_task_retention_proposal": {
                    "progress_event_days": 14,
                    "ordinary_event_days": 30,
                    "terminal_metadata_days": 90,
                    "terminal_snapshot_days": 90,
                    "terminal_result_days": 90,
                },
                "rollback_keep_count": ROLLBACK_KEEP_COUNT,
            },
            "summary": {
                **totals,
                "safe_cleanup_bytes": sum(
                    int(item.get("estimated_release_bytes") or 0)
                    for item in actionable
                    if item.get("recommended_action") in {"delete", "purge"}
                ),
                "compressible_bytes": sum(
                    int(item.get("estimated_release_bytes") or 0)
                    for item in actionable
                    if item.get("recommended_action") == "archive"
                ),
                "actionable_count": len(actionable),
            },
            "candidates": candidates,
        }
        if persist:
            self._persist_report(report)
        if progress:
            progress(4, 4, "数据清理扫描完成")
        return report

    def latest(self, site_id: str) -> dict[str, object] | None:
        record = self.registry.get(site_id)
        path = self._report_root(record.site_id) / "latest.json"
        return self._read_report(path)

    def validate_scan(self, site_id: str, scan_token: str) -> dict[str, object]:
        self.registry.get(site_id)
        return self._load_report(site_id, scan_token)

    def apply(
        self,
        site_id: str,
        *,
        scan_token: str,
        candidate_ids: list[str],
        current_job_id: str = "",
        check_cancel: Callable[[], None] | None = None,
        progress: Callable[[int, int, str], None] | None = None,
    ) -> dict[str, object]:
        record = self.registry.get(site_id)
        root = record.root_path.resolve()
        self._assert_site_root(root)
        selected_ids = {str(value or "").strip() for value in candidate_ids}
        selected_ids.discard("")
        if not selected_ids:
            raise SiteStorageError(
                "SITE_RETENTION_SELECTION_REQUIRED", "请至少选择一项可清理数据"
            )

        stored = self._load_report(record.site_id, scan_token)
        fresh = self.scan(record.site_id, persist=False, check_cancel=check_cancel)
        fresh_items = {
            str(item.get("candidate_id") or ""): item
            for item in fresh.get("candidates", [])
            if isinstance(item, dict)
        }
        stored_items = {
            str(item.get("candidate_id") or ""): item
            for item in stored.get("candidates", [])
            if isinstance(item, dict)
        }
        if str(fresh.get("scan_token") or "") != scan_token:
            raise SiteStorageError(
                "SITE_RETENTION_SCAN_STALE", "局点数据已变化，请重新扫描后再清理"
            )
        if not selected_ids.issubset(stored_items) or not selected_ids.issubset(
            fresh_items
        ):
            raise SiteStorageError(
                "SITE_RETENTION_CANDIDATE_INVALID", "清理候选不存在或已经变化"
            )

        selected = [fresh_items[item_id] for item_id in sorted(selected_ids)]
        for item in selected:
            if not bool(item.get("safe")) or item.get("recommended_action") not in {
                "archive",
                "delete",
                "purge",
            }:
                raise SiteStorageError(
                    "SITE_RETENTION_CANDIDATE_BLOCKED",
                    f"候选当前不可自动清理：{item.get('display_name') or item.get('candidate_id')}",
                )

        results: list[dict[str, object]] = []
        total = len(selected)
        lock_key = site_database_maintenance_key(record.site_id)
        with database_maintenance_lock(self.paths, lock_key):
            self._ensure_no_other_active_tasks(
                root, current_job_id=str(current_job_id or "")
            )
            with storage_lock(self.paths, f"site-retention-{record.site_id}"):
                for index, item in enumerate(selected, start=1):
                    if check_cancel:
                        check_cancel()
                    if progress:
                        progress(
                            index - 1,
                            total,
                            f"正在处理：{item.get('display_name')}",
                        )
                    category = str(item.get("category") or "")
                    if category in {"history_backup", "outdated_database"}:
                        result = self._apply_backup(root, item)
                    elif category == "expired_raw":
                        result = self._apply_online_mr_raw(root, item)
                    elif category == "task_history":
                        raise SiteStorageError(
                            "USER_POLICY_REQUIRED",
                            "任务存储 retention 仅支持预览，尚未启用 apply",
                        )
                    else:
                        raise SiteStorageError(
                            "SITE_RETENTION_CANDIDATE_INVALID",
                            "不支持的清理候选类型",
                        )
                    results.append(result)
                    if progress:
                        progress(index, total, f"已完成：{item.get('display_name')}")

        released = sum(int(item.get("released_bytes") or 0) for item in results)
        completed_at = self._normalized_now().isoformat(timespec="seconds")
        return {
            "site_id": record.site_id,
            "scan_token": scan_token,
            "completed_at": completed_at,
            "selected_count": total,
            "success_count": len(results),
            "failed_count": 0,
            "warning_count": 0,
            "released_bytes": released,
            "results": results,
        }

    def preview_typed_task_retention(
        self,
        site_id: str,
        *,
        tasks_database: str | Path,
        development_root: str | Path = DEVELOPMENT_ROOT,
    ) -> dict[str, Any]:
        """Build an exact rehearsal-only task retention plan without mutations."""

        database = assert_development_path(
            tasks_database, development_root=development_root
        )
        if database.is_symlink() or not database.is_file():
            raise ValueError("tasks retention database is missing or untrusted")
        now = self._normalized_now()
        with closing(self._connect_readonly(database)) as connection:
            connection.row_factory = sqlite3.Row
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_schema WHERE type='table'"
                ).fetchall()
            }
            required = {"task_snapshots", "task_events"}
            if not required.issubset(tables):
                raise ValueError("tasks retention database schema is incomplete")
            database_identity = self._task_retention_database_identity(
                connection, tables
            )
            snapshots = [
                dict(row)
                for row in connection.execute(
                    "SELECT task_id, task_type, status, finished_time, updated_time, "
                    "result_path, result_json, result_id FROM task_snapshots "
                    "ORDER BY task_id"
                ).fetchall()
            ]
            online_mr_ids: set[str] = set()
            if "online_mr_task_sessions" in tables:
                columns = {
                    str(row[1])
                    for row in connection.execute(
                        "PRAGMA table_info(online_mr_task_sessions)"
                    ).fetchall()
                }
                task_column = next(
                    (
                        name
                        for name in ("controller_task_id", "task_id")
                        if name in columns
                    ),
                    "",
                )
                if task_column:
                    online_mr_ids = {
                        str(row[0])
                        for row in connection.execute(
                            f'SELECT "{task_column}" FROM online_mr_task_sessions '
                            f'WHERE "{task_column}" IS NOT NULL'
                        ).fetchall()
                        if str(row[0] or "")
                    }

            protected: dict[str, str] = {}
            snapshot_delete_ids: list[str] = []
            snapshot_bytes = 0
            snapshot_by_id = {str(row["task_id"]): row for row in snapshots}
            for row in snapshots:
                task_id = str(row["task_id"])
                reason = self._task_retention_protection(row, online_mr_ids)
                if reason:
                    protected[task_id] = reason
                    continue
                status = str(row.get("status") or "").upper()
                timestamp = self._parse_datetime(
                    row.get("finished_time") or row.get("updated_time")
                )
                if (
                    status in {"COMPLETED", "FAILED", "CANCELLED"}
                    and timestamp is not None
                    and now - timestamp >= timedelta(days=90)
                ):
                    snapshot_delete_ids.append(task_id)
                    snapshot_bytes += len(str(row.get("result_json") or "").encode("utf-8"))

            event_rows = [
                dict(row)
                for row in connection.execute(
                    "SELECT sequence, event_id, task_id, event_type, event_time, "
                    "payload_json FROM task_events ORDER BY sequence"
                ).fetchall()
            ]
            snapshot_delete_set = set(snapshot_delete_ids)
            event_delete_sequences: list[int] = []
            event_bytes = 0
            event_breakdown: Counter[str] = Counter()
            kept_result_ids: set[str] = {
                str(row.get("result_id") or "")
                for row in snapshots
                if str(row["task_id"]) not in snapshot_delete_set
                and str(row.get("result_id") or "")
            }
            for row in event_rows:
                task_id = str(row.get("task_id") or "")
                event_type = str(row.get("event_type") or "")
                delete = task_id in snapshot_delete_set
                if not delete and task_id not in protected:
                    timestamp = self._parse_datetime(row.get("event_time"))
                    days = (
                        14
                        if event_type == "progress"
                        else 90
                        if event_type in {"finished", "error", "cancelled"}
                        else 30
                    )
                    delete = bool(
                        timestamp is not None
                        and now - timestamp >= timedelta(days=days)
                    )
                payload = self._retention_json_object(row.get("payload_json"))
                if delete:
                    event_delete_sequences.append(int(row["sequence"]))
                    event_bytes += len(str(row.get("payload_json") or "").encode("utf-8"))
                    event_breakdown[event_type] += 1
                else:
                    result_id = str(payload.get("result_id") or "")
                    if result_id:
                        kept_result_ids.add(result_id)

            result_delete_ids: list[str] = []
            result_bytes = 0
            if "task_results" in tables:
                for row in connection.execute(
                    "SELECT result_id, task_id, byte_size, created_time "
                    "FROM task_results ORDER BY result_id"
                ).fetchall():
                    result_id = str(row[0])
                    task_id = str(row[1])
                    created = self._parse_datetime(row[3])
                    if (
                        result_id not in kept_result_ids
                        and task_id not in protected
                        and created is not None
                        and now - created >= timedelta(days=90)
                    ):
                        result_delete_ids.append(result_id)
                        result_bytes += int(row[2] or 0)

        semantic: dict[str, Any] = {
            "format": "netconsole-typed-task-retention-plan",
            "version": 1,
            "site_id": str(site_id),
            "database": str(database),
            "database_sha256": sha256_file(database),
            "database_identity": database_identity,
            "policy": {
                "status": "REHEARSAL_POLICY_ONLY",
                "production_approved": False,
                "active": "NEVER_DELETE",
                "terminal_snapshot_days": 90,
                "progress_event_days": 14,
                "ordinary_event_days": 30,
                "log_event_days": 30,
                "terminal_event_days": 90,
                "task_result_days": 90,
                "online_mr_session": "PRESERVE",
                "artifact_files": "PRESERVE",
            },
            "event_sequence_ranges": self._compress_integer_keys(
                event_delete_sequences
            ),
            "event_sequence_digest": self._stable_json_digest(
                event_delete_sequences
            ),
            "snapshot_task_ids": sorted(snapshot_delete_ids),
            "snapshot_task_digest": self._stable_json_digest(
                sorted(snapshot_delete_ids)
            ),
            "result_ids": sorted(result_delete_ids),
            "result_digest": self._stable_json_digest(sorted(result_delete_ids)),
            "expected_counts": {
                "events": len(event_delete_sequences),
                "snapshots": len(snapshot_delete_ids),
                "results": len(result_delete_ids),
            },
        }
        digest = self._stable_json_digest(semantic)
        return {
            **semantic,
            "generated_at": now.isoformat(timespec="seconds"),
            "plan_digest": digest,
            "estimated_bytes": {
                "event_payload": event_bytes,
                "snapshot_result": snapshot_bytes,
                "task_results": result_bytes,
                "total": event_bytes + snapshot_bytes + result_bytes,
            },
            "event_type_counts": dict(sorted(event_breakdown.items())),
            "protected": {
                "total": len(protected),
                "active": sum(value == "ACTIVE" for value in protected.values()),
                "online_mr": sum(
                    value == "ONLINE_MR" for value in protected.values()
                ),
                "ground": sum(value == "GROUND" for value in protected.values()),
                "artifact": sum(
                    value == "ARTIFACT" for value in protected.values()
                ),
                "task_ids": sorted(protected),
            },
            "snapshot_status_counts": dict(
                sorted(
                    Counter(
                        str(snapshot_by_id[task_id].get("status") or "")
                        for task_id in snapshot_delete_ids
                    ).items()
                )
            ),
            "apply_enabled": True,
            "development_root_only": True,
            "implicit_vacuum": False,
            "artifact_files_deleted": 0,
        }

    def apply_typed_task_retention(
        self,
        plan: dict[str, Any],
        *,
        expected_plan_digest: str,
        apply: bool = False,
        allow_development_root_only: bool = False,
        development_root: str | Path = DEVELOPMENT_ROOT,
    ) -> dict[str, Any]:
        """Apply one exact typed retention plan without compacting or deleting files."""

        if not apply or not allow_development_root_only:
            raise ValueError(
                "typed retention requires --apply and --allow-development-root-only"
            )
        semantic_keys = (
            "format",
            "version",
            "site_id",
            "database",
            "database_sha256",
            "database_identity",
            "policy",
            "event_sequence_ranges",
            "event_sequence_digest",
            "snapshot_task_ids",
            "snapshot_task_digest",
            "result_ids",
            "result_digest",
            "expected_counts",
        )
        if str(plan.get("format") or "") != "netconsole-typed-task-retention-plan":
            raise ValueError("invalid typed retention plan format")
        semantic = {key: plan[key] for key in semantic_keys}
        digest = self._stable_json_digest(semantic)
        if digest != str(plan.get("plan_digest") or ""):
            raise ValueError("typed retention plan digest mismatch")
        if digest != str(expected_plan_digest or ""):
            raise ValueError("expected typed retention plan digest mismatch")
        database = assert_development_path(
            str(plan["database"]), development_root=development_root
        )
        self._assert_task_retention_database_identity(database, plan)
        if self._stable_json_digest(list(plan["snapshot_task_ids"])) != str(
            plan["snapshot_task_digest"]
        ):
            raise ValueError("typed retention snapshot key digest mismatch")
        if self._stable_json_digest(list(plan["result_ids"])) != str(
            plan["result_digest"]
        ):
            raise ValueError("typed retention result key digest mismatch")
        event_keys = self._expand_integer_ranges(plan["event_sequence_ranges"])
        if self._stable_json_digest(event_keys) != str(plan["event_sequence_digest"]):
            raise ValueError("typed retention event key digest mismatch")

        lock_key = site_database_maintenance_key(str(plan["site_id"]))
        with database_maintenance_lock(self.paths, lock_key):
            self._assert_task_retention_database_identity(database, plan)
            deleted = {"events": 0, "snapshots": 0, "results": 0}
            connection = sqlite3.connect(database, timeout=60)
            try:
                connection.execute("PRAGMA busy_timeout = 60000")
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute("BEGIN IMMEDIATE")
                for keys in self._chunks(event_keys, 500):
                    cursor = connection.execute(
                        "DELETE FROM task_events WHERE sequence IN "
                        f"({','.join('?' for _ in keys)})",
                        keys,
                    )
                    deleted["events"] += int(cursor.rowcount or 0)
                for keys in self._chunks(list(plan["snapshot_task_ids"]), 500):
                    cursor = connection.execute(
                        "DELETE FROM task_snapshots WHERE task_id IN "
                        f"({','.join('?' for _ in keys)})",
                        keys,
                    )
                    deleted["snapshots"] += int(cursor.rowcount or 0)
                for keys in self._chunks(list(plan["result_ids"]), 500):
                    cursor = connection.execute(
                        "DELETE FROM task_results WHERE result_id IN "
                        f"({','.join('?' for _ in keys)})",
                        keys,
                    )
                    deleted["results"] += int(cursor.rowcount or 0)
                expected = {
                    key: int(value)
                    for key, value in dict(plan["expected_counts"]).items()
                }
                if deleted != expected:
                    connection.rollback()
                    raise RuntimeError(
                        f"typed retention exact count mismatch: {deleted} != {expected}"
                    )
                active = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM task_snapshots WHERE status IN "
                        "('PENDING','STARTING','RUNNING','STOPPING')"
                    ).fetchone()[0]
                )
                online_mr = (
                    int(
                        connection.execute(
                            "SELECT COUNT(*) FROM online_mr_task_sessions"
                        ).fetchone()[0]
                    )
                    if connection.execute(
                        "SELECT 1 FROM sqlite_schema WHERE type='table' "
                        "AND name='online_mr_task_sessions'"
                    ).fetchone()
                    else 0
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()
        return {
            "plan_digest": digest,
            "deleted": deleted,
            "active_tasks_remaining": active,
            "online_mr_mappings_remaining": online_mr,
            "active_tasks_deleted": 0,
            "artifacts_deleted": 0,
            "implicit_vacuum": False,
        }

    def _storage_totals(
        self, root: Path, *, check_cancel: Callable[[], None] | None
    ) -> dict[str, int]:
        totals = {
            "total_bytes": 0,
            "current_database_bytes": 0,
            "raw_bytes": 0,
            "parsed_bytes": 0,
            "backup_bytes": 0,
            "other_bytes": 0,
        }
        for index, path in enumerate(root.rglob("*")):
            if check_cancel and index % 500 == 0:
                check_cancel()
            if path.is_symlink() or not path.is_file():
                continue
            try:
                size = path.stat().st_size
                relative = path.relative_to(root)
            except OSError:
                continue
            totals["total_bytes"] += size
            parts = {part.casefold() for part in relative.parts}
            if len(relative.parts) >= 2 and relative.parts[0].casefold() == "db":
                totals["current_database_bytes"] += size
            elif len(relative.parts) >= 2 and relative.parts[:2] == (
                "files",
                "backups",
            ):
                totals["backup_bytes"] += size
            elif "parsed" in parts or path.name.casefold() in {
                "catalog.sqlite",
                "index.sqlite",
                "mesh.sqlite",
                "vehicle_mr_online.sqlite",
            }:
                totals["parsed_bytes"] += size
            elif "raw" in parts or path.suffix.casefold() in _RAW_SUFFIXES:
                totals["raw_bytes"] += size
            else:
                totals["other_bytes"] += size
        return totals

    def _scan_databases(
        self, root: Path, now: datetime
    ) -> list[dict[str, object]]:
        candidates: list[dict[str, object]] = []
        current_paths = [
            path
            for path in (root / "db").glob("*")
            if path.is_file() and not path.is_symlink() and path.suffix.casefold() in _DATABASE_SUFFIXES
        ]
        ground_index = root / "files" / "rail_transit" / "ground_unattended" / "index.sqlite"
        if ground_index.is_file() and not ground_index.is_symlink():
            current_paths.append(ground_index)

        current_profiles: dict[str, dict[str, object]] = {}
        for path in current_paths:
            profile = self._sqlite_profile(path)
            kind = str(profile.get("database_kind") or "unknown")
            runtime_referenced = path.name.casefold() in {
                "agents.db",
                "devices.db",
                "tasks.db",
            } or path == ground_index
            if kind != "unknown" and runtime_referenced:
                current_profiles[kind] = {**profile, "path": path}
            stat = path.stat()
            relative = path.relative_to(root).as_posix()
            candidates.append(
                self._candidate(
                    category="current_database",
                    relative_path=relative,
                    display_name=path.name,
                    size_bytes=stat.st_size,
                    modified_ns=stat.st_mtime_ns,
                    age_days=self._age_days(stat.st_mtime, now),
                    status="current_use",
                    action="keep",
                    safe=False,
                    reason="当前生产数据库，绝不自动删除",
                    details={
                        **profile,
                        "code_reference": (
                            "current" if runtime_referenced else "protected_unverified"
                        ),
                        "last_accessed_at": self._timestamp(stat.st_atime),
                    },
                )
            )

        backup_root = root / "files" / "backups"
        if not backup_root.is_dir() or backup_root.is_symlink():
            return candidates
        backup_rows: list[dict[str, object]] = []
        for path in backup_root.rglob("*"):
            if (
                path.is_symlink()
                or not path.is_file()
                or path.suffix.casefold() not in _DATABASE_SUFFIXES
                or "archives" in {part.casefold() for part in path.relative_to(backup_root).parts}
            ):
                continue
            stat = path.stat()
            profile = self._sqlite_profile(path)
            backup_rows.append(
                {
                    "path": path,
                    "relative_path": path.relative_to(root).as_posix(),
                    "stat": stat,
                    "profile": profile,
                    "database_kind": str(profile.get("database_kind") or "unknown"),
                }
            )

        duplicate_map: dict[Path, Path] = {}
        size_groups: dict[int, list[dict[str, object]]] = defaultdict(list)
        for row in backup_rows:
            size_groups[int(row["stat"].st_size)].append(row)  # type: ignore[union-attr]
        for rows in size_groups.values():
            if len(rows) < 2:
                continue
            digest_groups: dict[str, list[dict[str, object]]] = defaultdict(list)
            for row in rows:
                digest_groups[self._sha256(row["path"])].append(row)  # type: ignore[arg-type]
            for duplicates in digest_groups.values():
                if len(duplicates) < 2:
                    continue
                duplicates.sort(
                    key=lambda row: row["stat"].st_mtime, reverse=True  # type: ignore[union-attr]
                )
                retained = duplicates[0]["path"]
                for duplicate in duplicates[1:]:
                    duplicate_map[duplicate["path"]] = retained  # type: ignore[index]

        by_kind: dict[str, list[dict[str, object]]] = defaultdict(list)
        for row in backup_rows:
            by_kind[str(row["database_kind"])].append(row)
        for rows in by_kind.values():
            rows.sort(key=lambda row: row["stat"].st_mtime, reverse=True)  # type: ignore[union-attr]

        for kind, rows in by_kind.items():
            current = current_profiles.get(kind)
            for index, row in enumerate(rows):
                path: Path = row["path"]  # type: ignore[assignment]
                stat = row["stat"]
                profile = row["profile"]
                relative = str(row["relative_path"])
                age = self._age_days(stat.st_mtime, now)
                current_version = str((current or {}).get("schema_version") or "unknown")
                backup_version = str(profile.get("schema_version") or "unknown")
                current_higher = self._version_is_higher(current_version, backup_version)
                retained_path = rows[0]["path"] if rows else None
                duplicate_of = duplicate_map.get(path)
                sidecar_bytes, wal_safe = self._backup_sidecar_state(path)
                action = "keep"
                safe = False
                status = "unknown_database" if kind == "unknown" else "historical_migration_version"
                reason = "数据库类型或 schema 无法确认，只能人工复核"
                estimated_release = 0
                if kind == "unknown":
                    pass
                elif duplicate_of is not None and wal_safe:
                    action = "delete"
                    safe = True
                    status = "duplicate_backup"
                    reason = "存在内容哈希完全相同的保留副本"
                    retained_path = duplicate_of
                elif index == 0:
                    status = "recent_rollback"
                    reason = "同类数据库最近一次回滚版本，按策略保留"
                elif index < ROLLBACK_KEEP_COUNT:
                    status = "recent_stable"
                    reason = "同类数据库最近稳定版本，按策略保留"
                elif not current_higher:
                    reason = "当前 schema 未能证明高于该备份，禁止自动处理"
                elif not wal_safe:
                    reason = "备份存在非空 WAL，禁止自动压缩或删除"
                elif age >= BACKUP_DELETE_DAYS and retained_path is not None:
                    action = "delete"
                    safe = True
                    reason = "已超过 90 天，当前 schema 更高且存在更新回滚副本"
                elif age >= BACKUP_ARCHIVE_DAYS and retained_path is not None:
                    action = "archive"
                    safe = True
                    reason = "已超过 30 天，当前 schema 更高且存在更新回滚副本"
                else:
                    reason = "尚未达到 30 天归档保留期"

                if safe:
                    estimated_release = (
                        stat.st_size + sidecar_bytes
                        if action == "delete"
                        else self._estimate_archive_release(path)
                    )

                current_relative = (
                    Path(current["path"]).relative_to(root).as_posix()
                    if current and isinstance(current.get("path"), Path)
                    else ""
                )
                retained_relative = (
                    Path(retained_path).relative_to(root).as_posix()
                    if isinstance(retained_path, Path)
                    else ""
                )
                candidates.append(
                    self._candidate(
                        category=(
                            "outdated_database"
                            if status
                            in {
                                "historical_migration_version",
                                "duplicate_backup",
                            }
                            else "history_backup"
                        ),
                        relative_path=relative,
                        display_name=path.name,
                        size_bytes=stat.st_size + sidecar_bytes,
                        modified_ns=stat.st_mtime_ns,
                        age_days=age,
                        status=status,
                        action=action,
                        safe=safe,
                        reason=reason,
                        estimated_release_bytes=estimated_release,
                        details={
                            **profile,
                            "current_schema_version": current_version,
                            "current_schema_higher": current_higher,
                            "current_database": current_relative,
                            "retained_backup": retained_relative,
                            "code_reference": "not_runtime_referenced"
                            if kind != "unknown"
                            else "unknown",
                            "last_accessed_at": self._timestamp(stat.st_atime),
                            "sidecar_bytes": sidecar_bytes,
                            "estimate_basis": (
                                "sampled_deflate_v1" if action == "archive" else "exact_delete"
                            ),
                        },
                    )
                )
        return candidates

    def _scan_online_mr_raw(
        self,
        root: Path,
        now: datetime,
        check_cancel: Callable[[], None] | None,
    ) -> list[dict[str, object]]:
        online_root = root / "files" / "rail_transit" / "online_mr"
        if not online_root.is_dir() or online_root.is_symlink():
            return []
        result: list[dict[str, object]] = []
        for index, meta_path in enumerate(online_root.glob("*/sessions/*/session_meta.json")):
            if check_cancel and index % 20 == 0:
                check_cancel()
            session_dir = meta_path.parent
            raw_dir = session_dir / "raw"
            if not raw_dir.is_dir() or raw_dir.is_symlink():
                continue
            raw_files = [
                path
                for path in raw_dir.rglob("*")
                if path.is_file() and not path.is_symlink()
            ]
            if not raw_files:
                continue
            raw_size = sum(path.stat().st_size for path in raw_files)
            newest_ns = max(path.stat().st_mtime_ns for path in raw_files)
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                meta = {}
            ended_at = self._parse_datetime(meta.get("ended_at"))
            age = self._age_days(
                ended_at.timestamp() if ended_at else newest_ns / 1_000_000_000,
                now,
            )
            evidence = self._online_mr_raw_evidence(session_dir, meta, raw_files)
            manual_retain = any((session_dir / marker).exists() for marker in _RETAIN_MARKERS)
            safe = bool(evidence.get("safe")) and not manual_retain and age >= ONLINE_MR_RAW_ARCHIVE_DAYS
            if manual_retain:
                status = "manual_retain"
                reason = "会话存在人工保留标记，禁止自动清理"
            elif age < ONLINE_MR_RAW_ARCHIVE_DAYS:
                status = "recent_raw"
                reason = "原始数据未满 30 天，按策略原样保留"
            elif safe:
                status = "archived_raw_copy"
                reason = "解析库存在，完整会话包已通过 CRC 与逐文件校验"
            else:
                status = "protected_raw"
                reason = str(evidence.get("reason") or "解析或归档证据不足")
            relative = raw_dir.relative_to(root).as_posix()
            result.append(
                self._candidate(
                    category="expired_raw",
                    relative_path=relative,
                    display_name=f"Online MR {session_dir.name} 原始数据",
                    size_bytes=raw_size,
                    modified_ns=newest_ns,
                    age_days=age,
                    status=status,
                    action="archive" if safe else "keep",
                    safe=safe,
                    reason=reason,
                    details={
                        "domain": "online_mr",
                        "session_id": session_dir.name,
                        "package_path": str(evidence.get("package_path") or ""),
                        "parsed_database": str(evidence.get("parsed_database") or ""),
                        "raw_file_count": len(raw_files),
                        "manual_retain": manual_retain,
                        "parse_status": str(evidence.get("parse_status") or ""),
                        "archive_verified": bool(evidence.get("archive_verified")),
                    },
                )
            )
        return result

    def _scan_task_history(self, root: Path, now: datetime) -> dict[str, object] | None:
        path = root / "db" / "tasks.db"
        if not path.is_file() or path.is_symlink():
            return None
        cutoffs = {
            days: (now - timedelta(days=days)).isoformat(timespec="seconds")
            for days in (14, 30, 90)
        }
        snapshot_breakdown: list[dict[str, object]] = []
        event_breakdown: list[dict[str, object]] = []
        result_breakdown: list[dict[str, object]] = []
        would_delete_rows = 0
        would_delete_bytes = 0
        try:
            with closing(self._connect_readonly(path)) as connection:
                tables = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                if not tables.intersection(
                    {"task_snapshots", "task_events", "task_results"}
                ):
                    return None
                if "task_snapshots" in tables:
                    groups = connection.execute(
                        """
                        SELECT task_type, status, COUNT(*) AS total_rows
                        FROM task_snapshots
                        GROUP BY task_type, status
                        ORDER BY task_type, status
                        """
                    ).fetchall()
                    for task_type, status, total_rows in groups:
                        normalized_status = str(status or "").upper()
                        retention_days = (
                            90
                            if normalized_status in {"COMPLETED", "FAILED", "CANCELLED"}
                            else None
                        )
                        eligible_rows = 0
                        eligible_bytes = 0
                        cutoff = cutoffs[90] if retention_days else ""
                        if retention_days:
                            eligible = connection.execute(
                                """
                                SELECT COUNT(*),
                                       COALESCE(SUM(
                                           LENGTH(task_id) + LENGTH(task_type) +
                                           LENGTH(task_name) + LENGTH(status) +
                                           LENGTH(updated_time) + LENGTH(result_json) + 128
                                       ), 0)
                                FROM task_snapshots
                                WHERE task_type = ? AND status = ?
                                  AND COALESCE(NULLIF(finished_time, ''), updated_time) < ?
                                """,
                                (task_type, status, cutoff),
                            ).fetchone()
                            eligible_rows = int(eligible[0] if eligible else 0)
                            eligible_bytes = int(eligible[1] if eligible else 0)
                        would_delete_rows += eligible_rows
                        would_delete_bytes += eligible_bytes
                        snapshot_breakdown.append(
                            {
                                "task_type": str(task_type or ""),
                                "status": normalized_status,
                                "total_rows": int(total_rows or 0),
                                "retention_days": retention_days,
                                "cutoff": cutoff,
                                "would_delete_rows": eligible_rows,
                                "would_delete_bytes_estimate": eligible_bytes,
                                "policy": (
                                    "PROPOSAL_90_DAYS"
                                    if retention_days
                                    else "NEVER_WHILE_ACTIVE"
                                ),
                            }
                        )

                if "task_events" in tables:
                    event_types = connection.execute(
                        """
                        SELECT event_type, COUNT(*) AS total_rows
                        FROM task_events
                        GROUP BY event_type
                        ORDER BY event_type
                        """
                    ).fetchall()
                    for event_type, total_rows in event_types:
                        normalized_type = str(event_type or "")
                        retention_days = (
                            14
                            if normalized_type == "progress"
                            else 90
                            if normalized_type in {"finished", "error", "cancelled"}
                            else 30
                        )
                        cutoff = cutoffs[retention_days]
                        eligible = connection.execute(
                            """
                            SELECT COUNT(*),
                                   COALESCE(SUM(
                                       LENGTH(event_id) + LENGTH(task_id) +
                                       LENGTH(event_type) + LENGTH(event_time) +
                                       LENGTH(source) + LENGTH(payload_json) + 64
                                   ), 0)
                            FROM task_events
                            WHERE event_type = ? AND event_time < ?
                            """,
                            (event_type, cutoff),
                        ).fetchone()
                        eligible_rows = int(eligible[0] if eligible else 0)
                        eligible_bytes = int(eligible[1] if eligible else 0)
                        would_delete_rows += eligible_rows
                        would_delete_bytes += eligible_bytes
                        event_breakdown.append(
                            {
                                "event_type": normalized_type,
                                "total_rows": int(total_rows or 0),
                                "retention_days": retention_days,
                                "cutoff": cutoff,
                                "would_delete_rows": eligible_rows,
                                "would_delete_bytes_estimate": eligible_bytes,
                            }
                        )

                if "task_results" in tables:
                    result_types = connection.execute(
                        """
                        SELECT terminal_event_type, COUNT(*) AS total_rows
                        FROM task_results
                        GROUP BY terminal_event_type
                        ORDER BY terminal_event_type
                        """
                    ).fetchall()
                    for terminal_event_type, total_rows in result_types:
                        eligible = connection.execute(
                            """
                            SELECT COUNT(*), COALESCE(SUM(byte_size + 256), 0)
                            FROM task_results
                            WHERE terminal_event_type = ? AND created_time < ?
                            """,
                            (terminal_event_type, cutoffs[90]),
                        ).fetchone()
                        eligible_rows = int(eligible[0] if eligible else 0)
                        eligible_bytes = int(eligible[1] if eligible else 0)
                        would_delete_rows += eligible_rows
                        would_delete_bytes += eligible_bytes
                        result_breakdown.append(
                            {
                                "terminal_event_type": str(terminal_event_type or ""),
                                "total_rows": int(total_rows or 0),
                                "retention_days": 90,
                                "cutoff": cutoffs[90],
                                "would_delete_rows": eligible_rows,
                                "would_delete_bytes_estimate": eligible_bytes,
                                "authority_copies_after_retention": 1,
                            }
                        )
        except sqlite3.Error:
            return None
        stat = path.stat()
        return self._candidate(
            category="task_history",
            relative_path="db/tasks.db#typed-retention-preview",
            display_name=f"任务存储 typed retention 预览（{would_delete_rows} 行）",
            size_bytes=would_delete_bytes,
            modified_ns=0,
            age_days=90 if would_delete_rows else 0,
            status="USER_POLICY_REQUIRED",
            action="preview",
            safe=False,
            reason="USER_POLICY_REQUIRED：当前仅提供 typed retention 估算，apply 未启用",
            details={
                "policy_status": "USER_POLICY_REQUIRED",
                "proposal_only": True,
                "apply_enabled": False,
                "would_delete_rows": would_delete_rows,
                "would_delete_bytes_estimate": would_delete_bytes,
                "task_snapshot_breakdown": snapshot_breakdown,
                "task_event_breakdown": event_breakdown,
                "task_result_breakdown": result_breakdown,
                "vacuum": False,
                "database_size_bytes": stat.st_size,
            },
        )

    def _online_mr_raw_evidence(
        self,
        session_dir: Path,
        meta: dict[str, object],
        raw_files: list[Path],
    ) -> dict[str, object]:
        if str(meta.get("status") or "").upper() not in {
            "STOPPED",
            "COMPLETED",
        }:
            return {"safe": False, "reason": "会话未处于正常结束状态"}
        if not bool(meta.get("finalization_complete")):
            return {"safe": False, "reason": "会话最终化未完成"}
        if str(meta.get("data_integrity") or "").casefold() != "complete":
            return {"safe": False, "reason": "会话完整性不是 complete"}
        if not bool(meta.get("package_available")):
            return {"safe": False, "reason": "会话包不可用"}
        parsed = session_dir / "parsed" / "online_diagnosis.sqlite"
        if not self._sqlite_quick_check(parsed):
            return {"safe": False, "reason": "解析结果库不存在或完整性校验失败"}
        package = session_dir / "outputs" / f"{session_dir.name}.zip"
        if not package.is_file() or package.is_symlink():
            return {"safe": False, "reason": "完整会话包不存在"}
        try:
            with zipfile.ZipFile(package) as archive:
                if archive.testzip() is not None:
                    return {"safe": False, "reason": "会话包 CRC 校验失败"}
                infos = {info.filename: info for info in archive.infolist() if not info.is_dir()}
                for raw_path in raw_files:
                    relative = raw_path.relative_to(session_dir).as_posix()
                    info = infos.get(relative)
                    if info is None or info.file_size != raw_path.stat().st_size:
                        return {"safe": False, "reason": f"会话包缺少原始文件：{relative}"}
                    if self._crc32(raw_path) != info.CRC:
                        return {"safe": False, "reason": f"会话包内容不一致：{relative}"}
        except (OSError, zipfile.BadZipFile):
            return {"safe": False, "reason": "会话包无法读取"}
        return {
            "safe": True,
            "reason": "",
            "archive_verified": True,
            "package_path": package.relative_to(session_dir.parent.parent.parent.parent).as_posix(),
            "parsed_database": parsed.relative_to(session_dir.parent.parent.parent.parent).as_posix(),
            "parse_status": "parsed_database_verified",
        }

    def _apply_backup(
        self, root: Path, candidate: dict[str, object]
    ) -> dict[str, object]:
        relative = str(candidate.get("relative_path") or "")
        path = self._controlled_file(root, relative, root / "files" / "backups")
        details = candidate.get("details") if isinstance(candidate.get("details"), dict) else {}
        current_relative = str(details.get("current_database") or "")
        retained_relative = str(details.get("retained_backup") or "")
        if current_relative:
            current = self._controlled_file(root, current_relative, root)
            if not self._sqlite_quick_check(current):
                raise SiteStorageError(
                    "SITE_RETENTION_CURRENT_DATABASE_INVALID",
                    "当前数据库完整性校验失败，已停止清理",
                )
        if retained_relative:
            retained = self._controlled_file(
                root, retained_relative, root / "files" / "backups"
            )
            if retained != path and not self._sqlite_quick_check(retained):
                raise SiteStorageError(
                    "SITE_RETENTION_ROLLBACK_INVALID",
                    "保留的回滚数据库完整性校验失败，已停止清理",
                )
        sidecar_bytes, wal_safe = self._backup_sidecar_state(path)
        if not wal_safe:
            raise SiteStorageError(
                "SITE_RETENTION_BACKUP_WAL_PRESENT", "备份存在非空 WAL，不能自动清理"
            )
        before = path.stat().st_size + sidecar_bytes
        action = str(candidate.get("recommended_action") or "")
        archive_relative = ""
        if action == "archive":
            archive_path = self._archive_backup(root, path, candidate)
            archive_relative = archive_path.relative_to(root).as_posix()
            after = archive_path.stat().st_size
        elif action == "delete":
            after = 0
        else:
            raise SiteStorageError(
                "SITE_RETENTION_CANDIDATE_INVALID", "数据库备份动作无效"
            )
        self._unlink_backup_with_sidecars(path)
        return {
            "candidate_id": candidate.get("candidate_id"),
            "category": candidate.get("category"),
            "action": action,
            "relative_path": relative,
            "archive_path": archive_relative,
            "released_bytes": max(0, before - after),
        }

    def _archive_backup(
        self, root: Path, path: Path, candidate: dict[str, object]
    ) -> Path:
        kind = str(
            (candidate.get("details") or {}).get("database_kind")
            if isinstance(candidate.get("details"), dict)
            else "unknown"
        )
        digest = self._sha256(path)
        archive_dir = root / "files" / "backups" / "archives" / self._safe_name(kind)
        archive_dir.mkdir(parents=True, exist_ok=True)
        destination = archive_dir / f"{path.stem}-{digest[:12]}.zip"
        temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
        manifest = {
            "schema_version": 1,
            "source_name": path.name,
            "source_sha256": digest,
            "source_size": path.stat().st_size,
            "archived_at": self._normalized_now().isoformat(timespec="seconds"),
            "candidate_id": candidate.get("candidate_id"),
        }
        try:
            with zipfile.ZipFile(
                temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
            ) as archive:
                archive.write(path, arcname=path.name)
                archive.writestr(
                    "retention_manifest.json",
                    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                )
            with zipfile.ZipFile(temporary) as archive:
                if archive.testzip() is not None:
                    raise SiteStorageError(
                        "SITE_RETENTION_ARCHIVE_INVALID", "数据库归档 CRC 校验失败"
                    )
                info = archive.getinfo(path.name)
                if info.file_size != path.stat().st_size:
                    raise SiteStorageError(
                        "SITE_RETENTION_ARCHIVE_INVALID", "数据库归档大小校验失败"
                    )
            os.replace(temporary, destination)
            return destination
        finally:
            temporary.unlink(missing_ok=True)

    def _apply_online_mr_raw(
        self, root: Path, candidate: dict[str, object]
    ) -> dict[str, object]:
        relative = str(candidate.get("relative_path") or "")
        raw_dir = self._controlled_directory(
            root, relative, root / "files" / "rail_transit" / "online_mr"
        )
        session_dir = raw_dir.parent
        meta_path = session_dir / "session_meta.json"
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SiteStorageError(
                "SITE_RETENTION_RAW_METADATA_INVALID", "Online MR 会话 metadata 无效"
            ) from exc
        raw_files = [
            path for path in raw_dir.rglob("*") if path.is_file() and not path.is_symlink()
        ]
        evidence = self._online_mr_raw_evidence(session_dir, meta, raw_files)
        if not bool(evidence.get("safe")):
            raise SiteStorageError(
                "SITE_RETENTION_RAW_EVIDENCE_CHANGED",
                str(evidence.get("reason") or "Online MR 原始数据证据已变化"),
            )
        before = sum(path.stat().st_size for path in raw_files)
        for path in raw_files:
            path.unlink()
        for directory in sorted(
            (path for path in raw_dir.rglob("*") if path.is_dir()),
            key=lambda value: len(value.parts),
            reverse=True,
        ):
            directory.rmdir()
        raw_dir.rmdir()
        meta["raw_retention"] = {
            "status": "archived",
            "archived_at": self._normalized_now().isoformat(timespec="seconds"),
            "package_path": str(evidence.get("package_path") or ""),
            "released_bytes": before,
            "policy": "online_mr_complete_package_v1",
        }
        self._atomic_json(meta_path, meta)
        return {
            "candidate_id": candidate.get("candidate_id"),
            "category": candidate.get("category"),
            "action": "archive",
            "relative_path": relative,
            "released_bytes": before,
        }

    def _apply_task_history(
        self, root: Path, candidate: dict[str, object]
    ) -> dict[str, object]:
        del root, candidate
        raise SiteStorageError(
            "USER_POLICY_REQUIRED",
            "宽泛任务历史清理已禁用；仅允许精确 typed retention 计划",
        )

    def _ensure_no_other_active_tasks(
        self, root: Path, *, current_job_id: str
    ) -> None:
        path = root / "db" / "tasks.db"
        if not path.is_file() or path.is_symlink():
            return
        try:
            with closing(self._connect_readonly(path)) as connection:
                tables = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                if "task_snapshots" not in tables:
                    return
                placeholders = ",".join("?" for _ in _ACTIVE_TASK_STATES)
                rows = connection.execute(
                    f"""
                    SELECT task_id, task_name, status
                    FROM task_snapshots
                    WHERE status IN ({placeholders}) AND task_id <> ?
                    ORDER BY updated_time DESC
                    LIMIT 20
                    """,
                    (*sorted(_ACTIVE_TASK_STATES), current_job_id),
                ).fetchall()
        except sqlite3.Error as exc:
            raise SiteStorageError(
                "SITE_RETENTION_TASK_STATE_UNAVAILABLE", "无法确认局点活动任务状态"
            ) from exc
        if rows:
            raise SiteStorageError(
                "SITE_HAS_ACTIVE_TASKS",
                "局点存在其他活动任务，不能执行数据清理",
                details={
                    "blocking_tasks": [
                        {
                            "task_id": str(row[0]),
                            "task_name": str(row[1]),
                            "status": str(row[2]),
                        }
                        for row in rows
                    ]
                },
            )

    @classmethod
    def _task_retention_protection(
        cls, row: dict[str, Any], online_mr_ids: set[str]
    ) -> str:
        task_id = str(row.get("task_id") or "")
        status = str(row.get("status") or "").upper()
        task_type = str(row.get("task_type") or "").casefold()
        if status in _ACTIVE_TASK_STATES:
            return "ACTIVE"
        if task_id in online_mr_ids or "online_mr" in task_type:
            return "ONLINE_MR"
        if task_type.startswith("ground_") or "ground_unattended" in task_type:
            return "GROUND"
        result_text = str(row.get("result_json") or "")
        if (
            str(row.get("result_path") or "").strip()
            or '"artifact_id"' in result_text
            or '"artifact_path"' in result_text
            or '"artifact_name"' in result_text
        ):
            return "ARTIFACT"
        return ""

    @staticmethod
    def _retention_json_object(value: object) -> dict[str, Any]:
        try:
            parsed = json.loads(str(value or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}

    def _assert_task_retention_database_identity(
        self, database: Path, plan: dict[str, Any]
    ) -> None:
        with closing(self._connect_readonly(database)) as connection:
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_schema WHERE type='table'"
                ).fetchall()
            }
            current = self._task_retention_database_identity(connection, tables)
        if current != str(plan.get("database_identity") or ""):
            raise ValueError("typed retention source database changed")

    @staticmethod
    def _task_retention_database_identity(
        connection: sqlite3.Connection, tables: set[str]
    ) -> str:
        digest = hashlib.sha256()
        selected_tables = (
            "task_result_storage_rollout",
            "task_snapshots",
            "task_events",
            "task_results",
            "online_mr_task_sessions",
        )
        for table in selected_tables:
            if table not in tables:
                continue
            columns = [
                str(row[1])
                for row in connection.execute(f'PRAGMA table_info("{table}")')
            ]
            primary = [
                str(row[1])
                for row in connection.execute(f'PRAGMA table_info("{table}")')
                if int(row[5] or 0)
            ]
            order = primary or (["rowid"] if table != "task_result_storage_rollout" else columns[:1])
            digest.update(f"{table}\0{','.join(columns)}\0".encode("utf-8"))
            cursor = connection.execute(
                f'SELECT * FROM "{table}" ORDER BY '
                + ", ".join(f'"{column}"' for column in order)
            )
            while True:
                rows = cursor.fetchmany(500)
                if not rows:
                    break
                for row in rows:
                    payload = json.dumps(
                        list(row),
                        ensure_ascii=False,
                        separators=(",", ":"),
                        default=str,
                    ).encode("utf-8")
                    digest.update(len(payload).to_bytes(8, "big"))
                    digest.update(payload)
        return digest.hexdigest()

    @staticmethod
    def _stable_json_digest(value: object) -> str:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _compress_integer_keys(values: list[int]) -> list[dict[str, int]]:
        keys = sorted(set(int(value) for value in values))
        if not keys:
            return []
        ranges: list[dict[str, int]] = []
        start = previous = keys[0]
        for value in keys[1:]:
            if value == previous + 1:
                previous = value
                continue
            ranges.append({"start": start, "end": previous})
            start = previous = value
        ranges.append({"start": start, "end": previous})
        return ranges

    @staticmethod
    def _expand_integer_ranges(values: object) -> list[int]:
        if not isinstance(values, list):
            raise ValueError("typed retention event ranges are invalid")
        keys: list[int] = []
        for item in values:
            if not isinstance(item, dict):
                raise ValueError("typed retention event range is invalid")
            start = int(item.get("start") or 0)
            end = int(item.get("end") or 0)
            if start <= 0 or end < start:
                raise ValueError("typed retention event range is invalid")
            keys.extend(range(start, end + 1))
        return keys

    @staticmethod
    def _chunks(values: list[Any], size: int) -> list[list[Any]]:
        return [values[index : index + size] for index in range(0, len(values), size)]

    def _candidate(
        self,
        *,
        category: str,
        relative_path: str,
        display_name: str,
        size_bytes: int,
        modified_ns: int,
        age_days: int,
        status: str,
        action: str,
        safe: bool,
        reason: str,
        estimated_release_bytes: int | None = None,
        details: dict[str, object],
    ) -> dict[str, object]:
        identity = {
            "category": category,
            "relative_path": relative_path,
            "size_bytes": int(size_bytes),
            "modified_ns": int(modified_ns),
            "status": status,
            "action": action,
            "details": {
                key: details[key]
                for key in sorted(details)
                if key
                in {
                    "cutoff",
                    "database_kind",
                    "event_count",
                    "package_path",
                    "parsed_database",
                    "retained_backup",
                    "schema_version",
                    "session_id",
                }
            },
        }
        candidate_id = hashlib.sha256(
            json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:32]
        return {
            "candidate_id": candidate_id,
            "category": category,
            "relative_path": relative_path,
            "display_name": display_name,
            "size_bytes": int(size_bytes),
            "estimated_release_bytes": (
                max(0, int(estimated_release_bytes))
                if safe and estimated_release_bytes is not None
                else int(size_bytes)
                if safe
                else 0
            ),
            "age_days": int(age_days),
            "status": status,
            "recommended_action": action,
            "safe": bool(safe),
            "reason": reason,
            "details": details,
        }

    def _scan_token(
        self, site_id: str, actionable: list[dict[str, object]]
    ) -> str:
        value = {
            "site_id": site_id,
            "policy": [
                BACKUP_ARCHIVE_DAYS,
                BACKUP_DELETE_DAYS,
                ONLINE_MR_RAW_ARCHIVE_DAYS,
                TASK_EVENT_RETENTION_DAYS,
                ROLLBACK_KEEP_COUNT,
            ],
            "candidates": [
                {
                    "candidate_id": item.get("candidate_id"),
                    "action": item.get("recommended_action"),
                    "size_bytes": item.get("size_bytes"),
                }
                for item in actionable
            ],
        }
        return hashlib.sha256(
            json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

    def _persist_report(self, report: dict[str, object]) -> None:
        root = self._report_root(str(report["site_id"]))
        root.mkdir(parents=True, exist_ok=True)
        payload = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode(
            "utf-8"
        )
        atomic_write_bytes(root / f"{report['scan_token']}.json", payload)
        atomic_write_bytes(root / "latest.json", payload)

    def _load_report(self, site_id: str, token: str) -> dict[str, object]:
        if not re.fullmatch(r"[0-9a-f]{64}", str(token or "")):
            raise SiteStorageError(
                "SITE_RETENTION_SCAN_INVALID", "数据清理扫描令牌无效"
            )
        report = self._read_report(self._report_root(site_id) / f"{token}.json")
        if report is None or report.get("scan_token") != token:
            raise SiteStorageError(
                "SITE_RETENTION_SCAN_NOT_FOUND", "未找到对应的数据清理扫描"
            )
        return report

    @staticmethod
    def _estimate_archive_release(path: Path) -> int:
        size = path.stat().st_size
        if size <= 0:
            return 0
        chunk_size = 1024 * 1024
        sample_count = min(16, max(1, (size + chunk_size - 1) // chunk_size))
        compressed = 0
        sampled = 0
        with path.open("rb") as handle:
            for index in range(sample_count):
                offset = 0 if sample_count == 1 else ((size - 1) * index) // (sample_count - 1)
                offset = min(max(0, offset - chunk_size // 2), max(0, size - chunk_size))
                handle.seek(offset)
                payload = handle.read(chunk_size)
                if not payload:
                    continue
                sampled += len(payload)
                compressed += len(zlib.compress(payload, level=6))
        if sampled <= 0:
            return 0
        estimated_archive = min(size, int(size * compressed / sampled) + 4096)
        return max(0, size - estimated_archive)

    def _read_report(self, path: Path) -> dict[str, object] | None:
        if not path.is_file() or path.is_symlink():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def _report_root(self, site_id: str) -> Path:
        return self.paths.runtime_dir / "site_retention" / site_id

    def _assert_site_root(self, root: Path) -> None:
        sites = self.paths.sites_dir.resolve()
        if root.parent != sites or root.is_symlink():
            raise SiteStorageError(
                "SITE_RETENTION_PATH_INVALID", "局点数据清理目标路径不受信任"
            )

    def _controlled_file(self, root: Path, relative: str, allowed: Path) -> Path:
        relative_path = Path(relative)
        if (
            not relative
            or relative_path.is_absolute()
            or any(part in {"", ".", ".."} for part in relative_path.parts)
        ):
            raise SiteStorageError(
                "SITE_RETENTION_PATH_INVALID", "数据清理候选路径无效"
            )
        candidate = (root / relative_path).resolve(strict=True)
        allowed_root = allowed.resolve(strict=True)
        try:
            candidate.relative_to(allowed_root)
        except ValueError as exc:
            raise SiteStorageError(
                "SITE_RETENTION_PATH_INVALID", "数据清理候选路径越界"
            ) from exc
        if not candidate.is_file() or candidate.is_symlink():
            raise SiteStorageError(
                "SITE_RETENTION_PATH_INVALID", "数据清理候选文件不存在或不受信任"
            )
        return candidate

    def _controlled_directory(self, root: Path, relative: str, allowed: Path) -> Path:
        relative_path = Path(relative)
        if (
            not relative
            or relative_path.is_absolute()
            or any(part in {"", ".", ".."} for part in relative_path.parts)
        ):
            raise SiteStorageError(
                "SITE_RETENTION_PATH_INVALID", "数据清理候选路径无效"
            )
        candidate = (root / relative_path).resolve(strict=True)
        allowed_root = allowed.resolve(strict=True)
        try:
            candidate.relative_to(allowed_root)
        except ValueError as exc:
            raise SiteStorageError(
                "SITE_RETENTION_PATH_INVALID", "数据清理候选路径越界"
            ) from exc
        if not candidate.is_dir() or candidate.is_symlink():
            raise SiteStorageError(
                "SITE_RETENTION_PATH_INVALID", "数据清理候选目录不存在或不受信任"
            )
        return candidate

    @staticmethod
    def _sqlite_profile(path: Path) -> dict[str, object]:
        result: dict[str, object] = {
            "database_kind": "unknown",
            "schema_version": "unknown",
        }
        try:
            with closing(SiteRetentionService._connect_readonly(path)) as connection:
                tables = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                if "devices" in tables:
                    result["database_kind"] = "devices"
                elif "task_events" in tables and "task_snapshots" in tables:
                    result["database_kind"] = "tasks"
                elif "ground_unattended_schema" in tables:
                    result["database_kind"] = "ground_unattended"
                for table in (
                    "schema_metadata",
                    "schema_meta",
                    "meta",
                    "ground_unattended_schema",
                ):
                    if table not in tables:
                        continue
                    row = connection.execute(
                        f"SELECT value FROM {table} WHERE key = 'schema_version' LIMIT 1"
                    ).fetchone()
                    if row and row[0] not in (None, ""):
                        result["schema_version"] = str(row[0])
                        break
        except (OSError, sqlite3.Error):
            result["readable"] = False
        else:
            result["readable"] = True
        return result

    @staticmethod
    def _connect_readonly(path: Path) -> sqlite3.Connection:
        connection = sqlite3.connect(
            f"file:{path.resolve().as_posix()}?mode=ro",
            uri=True,
            timeout=10,
        )
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @staticmethod
    def _sqlite_quick_check(path: Path) -> bool:
        if not path.is_file() or path.is_symlink() or path.stat().st_size <= 0:
            return False
        try:
            with closing(SiteRetentionService._connect_readonly(path)) as connection:
                row = connection.execute("PRAGMA quick_check").fetchone()
                return bool(row and str(row[0]).casefold() == "ok")
        except (OSError, sqlite3.Error):
            return False

    @staticmethod
    def _version_is_higher(current: str, backup: str) -> bool:
        current_match = _SCHEMA_DATE_RE.match(current)
        backup_match = _SCHEMA_DATE_RE.match(backup)
        if current_match and backup_match:
            return tuple(map(int, current_match.groups())) > tuple(
                map(int, backup_match.groups())
            )
        if current.isdigit() and backup.isdigit():
            return int(current) > int(backup)
        return False

    @staticmethod
    def _backup_sidecar_state(path: Path) -> tuple[int, bool]:
        size = 0
        wal_safe = True
        for suffix in ("-wal", "-shm"):
            sidecar = path.with_name(path.name + suffix)
            if not sidecar.exists():
                continue
            if not sidecar.is_file() or sidecar.is_symlink():
                wal_safe = False
                continue
            sidecar_size = sidecar.stat().st_size
            size += sidecar_size
            if suffix == "-wal" and sidecar_size > 0:
                wal_safe = False
        return size, wal_safe

    @staticmethod
    def _unlink_backup_with_sidecars(path: Path) -> None:
        sidecars: list[Path] = []
        for suffix in ("-wal", "-shm"):
            sidecar = path.with_name(path.name + suffix)
            if sidecar.is_file() and not sidecar.is_symlink():
                if suffix == "-wal" and sidecar.stat().st_size > 0:
                    raise SiteStorageError(
                        "SITE_RETENTION_BACKUP_WAL_PRESENT",
                        "备份 WAL 在执行期间发生变化，已停止清理",
                    )
                sidecars.append(sidecar)
        path.unlink()
        for sidecar in sidecars:
            sidecar.unlink(missing_ok=True)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _crc32(path: Path) -> int:
        value = 0
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                value = binascii.crc32(block, value)
        return value & 0xFFFFFFFF

    @staticmethod
    def _safe_name(value: str) -> str:
        safe = "".join(
            character if character.isalnum() or character in "._-" else "_"
            for character in str(value or "unknown")
        )
        return safe.strip(".") or "unknown"

    def _normalized_now(self) -> datetime:
        value = self._now()
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)

    @staticmethod
    def _parse_datetime(value: object) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.astimezone()
        return parsed.astimezone(UTC)

    @staticmethod
    def _age_days(timestamp: float, now: datetime) -> int:
        modified = datetime.fromtimestamp(timestamp, UTC)
        return max(0, int((now - modified).total_seconds() // 86400))

    @staticmethod
    def _task_cutoff(now: datetime) -> str:
        cutoff_date = (now - timedelta(days=TASK_EVENT_RETENTION_DAYS)).date()
        return f"{cutoff_date.isoformat()}T00:00:00Z"

    @staticmethod
    def _timestamp(value: float) -> str:
        return datetime.fromtimestamp(value, UTC).isoformat(timespec="seconds")

    @staticmethod
    def _atomic_json(path: Path, value: dict[str, object]) -> None:
        atomic_write_bytes(
            path,
            (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode(
                "utf-8"
            ),
        )


__all__ = [
    "BACKUP_ARCHIVE_DAYS",
    "BACKUP_DELETE_DAYS",
    "ONLINE_MR_RAW_ARCHIVE_DAYS",
    "ROLLBACK_KEEP_COUNT",
    "SiteRetentionService",
    "TASK_EVENT_RETENTION_DAYS",
]
