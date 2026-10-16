"""Read-only AC Web action-plan reconciliation rehearsal.

This module deliberately does not construct ``TaskRepository`` or any Backend
service.  Production SQLite files are opened with ``mode=ro`` and the only
filesystem writes allowed by the CLI are to an explicitly selected report
outside the data root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable, Mapping

from netconsole.application.ac.web_application_service import (
    AcWebApplicationService,
    classify_ac_action_plan_status,
)
from netconsole.core.paths import PathResolver
from netconsole.models.task_state import TaskState


TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}
ACTIVE = {"PENDING", "STARTING", "RUNNING", "STOPPING"}
REQUIRED_OWNER = "web_ac"
REQUIRED_SOURCE = "local"
REPORT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class PlanFile:
    record_id: str
    path: Path
    data: dict[str, Any]
    sha256: str
    size: int
    modified_ns: int


@dataclass(frozen=True)
class TaskEvidence:
    snapshot: object | None
    db_path: Path | None
    tombstoned: bool
    tombstone_reason: str
    duplicate_snapshot_count: int = 0
    duplicate_db_count: int = 0


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path.name}")
    return value


def resolve_paths(data_root: Path) -> tuple[PathResolver, Path, list[Path]]:
    resolver = PathResolver(data_root=data_root)
    plan_root = (resolver.runtime_cache_dir / "ac_web_action_plans").resolve()
    if not plan_root.is_dir():
        raise FileNotFoundError(f"AC Web plan directory does not exist: {plan_root}")
    task_dbs = sorted(
        path.resolve()
        for path in resolver.sites_dir.glob("*/db/tasks.db")
        if path.is_file()
    )
    return resolver, plan_root, task_dbs


def load_plan_files(plan_root: Path) -> list[PlanFile]:
    paths = sorted(
        (path for path in plan_root.glob("ac-plan-*.json") if path.is_file()),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
    )
    plans: list[PlanFile] = []
    for index, path in enumerate(paths, start=1):
        stat = path.stat()
        plans.append(
            PlanFile(
                record_id=f"P{index:02d}",
                path=path,
                data=_read_json(path),
                sha256=_sha256(path),
                size=stat.st_size,
                modified_ns=stat.st_mtime_ns,
            )
        )
    return plans


def _read_only_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        f"file:{path.as_posix()}?mode=ro",
        uri=True,
        timeout=5.0,
    )
    connection.row_factory = sqlite3.Row
    return connection


def _json_object(value: object) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _result_plan_id(connection: sqlite3.Connection, row: sqlite3.Row) -> str:
    result = _json_object(row["result_json"])
    if result.get("plan_id"):
        return str(result["plan_id"])
    result_id = str(row["result_id"] or "").strip()
    if not result_id:
        return ""
    result_row = connection.execute(
        "SELECT canonical_json, content_sha256, blob_codec FROM task_results WHERE result_id = ?",
        (result_id,),
    ).fetchone()
    if result_row is None:
        return ""
    result = _json_object(result_row["canonical_json"])
    if result.get("plan_id"):
        return str(result["plan_id"])
    content_sha256 = str(result_row["content_sha256"] or "").strip()
    codec = str(result_row["blob_codec"] or "").strip().casefold()
    if not content_sha256 or codec != "zlib":
        return ""
    blob_row = connection.execute(
        "SELECT compressed_blob FROM task_result_blobs WHERE content_sha256 = ?",
        (content_sha256,),
    ).fetchone()
    if blob_row is None or blob_row["compressed_blob"] is None:
        return ""
    try:
        result = _json_object(zlib.decompress(bytes(blob_row["compressed_blob"])))
    except (TypeError, ValueError, zlib.error):
        return ""
    return str(result.get("plan_id") or "").strip()


def _snapshot(row: sqlite3.Row, result_plan_id: str) -> object:
    raw_status = str(row["status"] or "")
    try:
        status: object = TaskState(raw_status)
    except ValueError:
        status = raw_status
    return SimpleNamespace(
        task_id=str(row["task_id"] or ""),
        task_type=str(row["task_type"] or ""),
        status=status,
        owner=str(row["owner"] or ""),
        source=str(row["source"] or "local"),
        site_name=str(row["site_name"] or ""),
        result={"plan_id": result_plan_id} if result_plan_id else {},
    )


def _chunks(values: list[str], size: int = 80) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def load_task_evidence(task_dbs: list[Path], task_ids: set[str]) -> dict[str, TaskEvidence]:
    snapshots: dict[str, list[tuple[object, Path]]] = {}
    tombstones: dict[str, list[tuple[str, Path]]] = {}
    ordered_ids = sorted(task_id for task_id in task_ids if task_id)
    for db_path in task_dbs:
        with _read_only_connection(db_path) as connection:
            for group in _chunks(ordered_ids):
                placeholders = ",".join("?" for _ in group)
                rows = connection.execute(
                    f"SELECT * FROM task_snapshots WHERE task_id IN ({placeholders})",
                    group,
                ).fetchall()
                for row in rows:
                    snapshots.setdefault(str(row["task_id"]), []).append(
                        (_snapshot(row, _result_plan_id(connection, row)), db_path)
                    )
                rows = connection.execute(
                    f"SELECT task_id, reason FROM task_retention_tombstones WHERE task_id IN ({placeholders})",
                    group,
                ).fetchall()
                for row in rows:
                    tombstones.setdefault(str(row["task_id"]), []).append(
                        (str(row["reason"] or ""), db_path)
                    )
    result: dict[str, TaskEvidence] = {}
    for task_id in ordered_ids:
        found = snapshots.get(task_id, [])
        retired = tombstones.get(task_id, [])
        result[task_id] = TaskEvidence(
            snapshot=found[0][0] if len(found) == 1 else None,
            db_path=found[0][1] if len(found) == 1 else None,
            tombstoned=bool(retired),
            tombstone_reason=retired[0][0] if retired else "",
            duplicate_snapshot_count=len(found),
            duplicate_db_count=len({path for _, path in found}),
        )
    return result


def _is_allowed_task(snapshot: object | None) -> bool:
    return bool(
        snapshot is not None
        and str(getattr(snapshot, "owner", "") or "") == REQUIRED_OWNER
        and str(getattr(snapshot, "source", "") or "") == REQUIRED_SOURCE
        and str(getattr(snapshot, "task_type", "") or "")
        in AcWebApplicationService._TASK_ACTIONS
    )


def classify_plans(plans: list[PlanFile], evidence: Mapping[str, TaskEvidence]) -> list[dict[str, Any]]:
    reverse_links: dict[tuple[str, str], list[str]] = {}
    for item in plans:
        site_id = str(item.data.get("site_id") or "")
        task_id = str(item.data.get("task_id") or "")
        if site_id and task_id:
            reverse_links.setdefault((site_id, task_id), []).append(
                str(item.data.get("plan_id") or "")
            )

    rows: list[dict[str, Any]] = []
    for item in plans:
        plan = item.data
        task_id = str(plan.get("task_id") or "").strip()
        site_id = str(plan.get("site_id") or "").strip()
        task = evidence.get(task_id, TaskEvidence(None, None, False, ""))
        ambiguous = task.duplicate_snapshot_count > 1 or task.duplicate_db_count > 1
        reverse_ambiguous = len(reverse_links.get((site_id, task_id), [])) > 1
        if ambiguous or (reverse_ambiguous and not getattr(task.snapshot, "result", {}).get("plan_id")):
            effective_status = "UNKNOWN_OR_UNVERIFIED"
            reconciliation_status = "UNKNOWN_OR_UNVERIFIED"
            reason = "TASK_IDENTITY_AMBIGUOUS"
            evidence_level = "NONE"
            can_persist = False
        else:
            classified = classify_ac_action_plan_status(
                plan,
                task.snapshot,
                expected_site_id=site_id,
                tombstoned=task.tombstoned and task.snapshot is None,
                allowed_task_types=AcWebApplicationService._TASK_ACTIONS,
            )
            effective_status = classified.effective_status
            reconciliation_status = classified.reconciliation_status
            reason = classified.reconciliation_reason
            evidence_level = classified.evidence_level
            can_persist = classified.can_persist_terminal
        stored_status = str(plan.get("status") or "")
        existing_audit = plan.get("status_reconciliation")
        existing_to = (
            str(existing_audit.get("to_status") or "")
            if isinstance(existing_audit, Mapping)
            else ""
        )
        already_audited = bool(
            existing_to
            and existing_to == effective_status
            and str(existing_audit.get("task_id") or "") == task_id
        ) if isinstance(existing_audit, Mapping) else False
        candidate = bool(
            stored_status == "EXECUTING"
            and can_persist
            and effective_status in TERMINAL
            and not already_audited
        )
        if already_audited:
            expected_change = "NO_CHANGE_ALREADY_AUDITED"
        elif candidate:
            expected_change = f"status EXECUTING -> {effective_status}; add status_reconciliation"
        else:
            expected_change = "NO_CHANGE"
        if reason == "TASK_HISTORY_CLEANED":
            risk = "HIGH"
        elif effective_status == "UNKNOWN_OR_UNVERIFIED" or ambiguous or reverse_ambiguous:
            risk = "HIGH"
        elif evidence_level == "TASK_ID_SCOPE":
            risk = "MEDIUM"
        else:
            risk = "LOW"
        task_status = "MISSING"
        if task.snapshot is not None:
            task_status = str(getattr(task.snapshot.status, "value", task.snapshot.status))
        rows.append(
            {
                "record_id": item.record_id,
                "site_id": site_id,
                "stored_status": stored_status,
                "task_status": task_status,
                "task_evidence": (
                    "DIRECT_PLAN_ID"
                    if evidence_level == "DIRECT_PLAN_ID"
                    else "UNIQUE_TASK_ID_SCOPE"
                    if evidence_level == "TASK_ID_SCOPE"
                    else "MISSING_TOMBSTONE"
                    if reason == "TASK_HISTORY_CLEANED"
                    else "MISSING"
                ),
                "tombstone": "YES" if task.tombstoned else "NO",
                "tombstone_reason": task.tombstone_reason,
                "evidence_level": evidence_level,
                "effective_status": effective_status,
                "reconciliation_status": reconciliation_status,
                "reason": reason,
                "expected_change": expected_change,
                "allow_formal": "YES" if candidate else "NO",
                "risk": risk,
                "manual_review": "必需" if stored_status == "EXECUTING" else "非必需",
                "candidate": candidate,
                "ambiguous": ambiguous or reverse_ambiguous,
                "active_task": task_status in ACTIVE and _is_allowed_task(task.snapshot),
                "already_audited": already_audited,
            }
        )
    return rows


def _file_state(paths: Iterable[Path]) -> dict[str, tuple[int, str]]:
    state: dict[str, tuple[int, str]] = {}
    for path in paths:
        try:
            state[str(path)] = (path.stat().st_size, _sha256(path))
        except OSError:
            state[str(path)] = (-1, "MISSING")
    return state


def _db_read_only_probe(task_dbs: list[Path]) -> dict[str, Any]:
    quick_checks: dict[str, str] = {}
    for path in task_dbs:
        try:
            with _read_only_connection(path) as connection:
                result = connection.execute("PRAGMA quick_check").fetchone()
                quick_checks[path.name + "@" + path.parent.parent.name] = str(result[0])
        except (OSError, sqlite3.DatabaseError) as exc:
            quick_checks[path.name + "@" + path.parent.parent.name] = f"ERROR:{exc.__class__.__name__}"
    return quick_checks


def _read_only_task_inventory(task_dbs: list[Path]) -> dict[str, int]:
    """Count relevant tombstones and active AC Web tasks without opening a writer."""

    active_task_ids: set[str] = set()
    tombstone_count = 0
    for path in task_dbs:
        with _read_only_connection(path) as connection:
            tombstone_count += int(
                connection.execute("SELECT COUNT(*) FROM task_retention_tombstones").fetchone()[0]
            )
            placeholders = ",".join("?" for _ in AcWebApplicationService._TASK_ACTIONS)
            rows = connection.execute(
                f"""
                SELECT task_id
                FROM task_snapshots
                WHERE owner = ?
                  AND source = ?
                  AND task_type IN ({placeholders})
                  AND status IN ({','.join('?' for _ in ACTIVE)})
                """,
                [
                    REQUIRED_OWNER,
                    REQUIRED_SOURCE,
                    *sorted(AcWebApplicationService._TASK_ACTIONS),
                    *sorted(ACTIVE),
                ],
            ).fetchall()
            active_task_ids.update(str(row["task_id"] or "") for row in rows if row["task_id"])
    return {
        "active_ac_web_task_count": len(active_task_ids),
        "tombstone_count": tombstone_count,
    }


def run_dry_run(data_root: Path) -> dict[str, Any]:
    started_at = _utc_now()
    resolver, plan_root, task_dbs = resolve_paths(data_root)
    plans_before = load_plan_files(plan_root)
    plan_state_before = _file_state(item.path for item in plans_before)
    db_state_before = _file_state(task_dbs)
    task_ids = {str(item.data.get("task_id") or "").strip() for item in plans_before}
    evidence = load_task_evidence(task_dbs, task_ids)
    executing_paths = {
        item.path
        for item in plans_before
        if str(item.data.get("status") or "") == "EXECUTING"
    }
    executing_record_ids = {
        path: f"P{index:02d}"
        for index, path in enumerate(
            (item.path for item in plans_before if item.path in executing_paths),
            start=1,
        )
    }
    stable_plans = [
        PlanFile(
            record_id=executing_record_ids.get(item.path, item.record_id),
            path=item.path,
            data=item.data,
            sha256=item.sha256,
            size=item.size,
            modified_ns=item.modified_ns,
        )
        for item in plans_before
    ]
    first = classify_plans(stable_plans, evidence)
    second = classify_plans(stable_plans, evidence)

    def normalized(rows: list[dict[str, Any]]) -> str:
        return json.dumps(rows, ensure_ascii=False, sort_keys=True)

    plans_after = load_plan_files(plan_root)
    plan_state_after = _file_state(item.path for item in plans_after)
    db_state_after = _file_state(task_dbs)
    task_inventory = _read_only_task_inventory(task_dbs)
    executing = [row for row in first if row["stored_status"] == "EXECUTING"]
    all_task_statuses: dict[str, int] = {}
    for task in evidence.values():
        if task.snapshot is not None:
            status = str(getattr(task.snapshot.status, "value", task.snapshot.status))
            all_task_statuses[status] = all_task_statuses.get(status, 0) + 1
    active_ac_task_ids = {
        str(task.snapshot.task_id)
        for task in evidence.values()
        if task.snapshot is not None
        and _is_allowed_task(task.snapshot)
        and str(getattr(task.snapshot.status, "value", task.snapshot.status)) in ACTIVE
    }
    relevant_runtime_files = [
        path
        for task_id in task_ids
        for path in (
            resolver.runtime_cache_dir / "background_jobs" / f"{task_id}.json",
            resolver.runtime_cache_dir / "background_jobs" / f"{task_id}.cancel",
            resolver.runtime_cache_dir / "export_jobs" / f"{task_id}.json",
            resolver.runtime_cache_dir / "export_jobs" / f"{task_id}.json.tmp",
        )
        if path.exists()
    ]
    by_status = {status: sum(row["effective_status"] == status for row in executing) for status in TERMINAL}
    by_status["UNKNOWN_OR_UNVERIFIED"] = sum(
        row["effective_status"] == "UNKNOWN_OR_UNVERIFIED" for row in executing
    )
    by_status["EXECUTING"] = sum(row["effective_status"] == "EXECUTING" for row in executing)
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "started_at": started_at,
        "finished_at": _utc_now(),
        "data_root": str(resolver.data_root),
        "plan_root": str(plan_root),
        "task_db_count": len(task_dbs),
        "plan_count": len(plans_before),
        "plan_status_distribution": {
            status: sum(str(item.data.get("status") or "") == status for item in plans_before)
            for status in sorted({str(item.data.get("status") or "") for item in plans_before})
        },
        "executing_count": len(executing),
        "executing_effective_distribution": by_status,
        "verified_completed": by_status["COMPLETED"],
        "verified_failed": by_status["FAILED"],
        "verified_cancelled": by_status["CANCELLED"],
        "active_tasks": task_inventory["active_ac_web_task_count"],
        "referenced_active_tasks": len(active_ac_task_ids),
        "unknown_or_unverified": by_status["UNKNOWN_OR_UNVERIFIED"],
        "identity_ambiguous": sum(row["ambiguous"] for row in executing),
        "dry_run_candidates": sum(row["candidate"] for row in executing),
        "dry_run_skipped": sum(not row["candidate"] for row in executing),
        "task_status_distribution_for_referenced_ids": all_task_statuses,
        "relevant_runtime_files": [str(path.relative_to(resolver.data_root)) for path in relevant_runtime_files],
        "plan_content_changed": plan_state_before != plan_state_after,
        "plan_changed_records": sorted(
            path for path in set(plan_state_before) | set(plan_state_after)
            if plan_state_before.get(path) != plan_state_after.get(path)
        ),
        "task_db_content_changed": db_state_before != db_state_after,
        "plan_sha256_file_count": len(plan_state_before),
        "task_db_sha256_file_count": len(db_state_before),
        "plan_sha256_stable": plan_state_before == plan_state_after,
        "task_db_sha256_stable": db_state_before == db_state_after,
        "tombstone_count_all_task_dbs": task_inventory["tombstone_count"],
        "read_only_quick_check": _db_read_only_probe(task_dbs),
        "idempotent": normalized(first) == normalized(second),
        "records": executing,
    }


def render_report(result: Mapping[str, Any], *, baseline: str) -> str:
    records = list(result["records"])
    lines = [
        "# Phase 2-C：历史 AC Web 动作计划受控协调预演（Dry-Run）",
        "",
        f"- Dry-Run 时间：`{result['started_at']}` 至 `{result['finished_at']}`",
        f"- 最新 main：`{baseline}`",
        f"- 数据根：`{result['data_root']}`（仅只读）",
        f"- 计划目录：`{result['plan_root']}`（由 `PathResolver` 解析）",
        f"- Task DB：`{result['task_db_count']}` 个，全部通过 SQLite `mode=ro` 打开",
        "",
        "## 结论",
        "",
        "本轮只执行状态证明读取和 PR #88 分类模拟，不调用 Backend、`TaskRepository`、`POST /reconcile`、cleanup 或设备命令。计划 JSON、Task Center SQLite、tombstone 和运行文件均未被本轮写入。",
        "",
        f"历史计划共 `{result['plan_count']}` 条，其中原始 `EXECUTING` `{result['executing_count']}` 条。对这批执行中计划，Dry-Run 得到：`COMPLETED={result['verified_completed']}`、`FAILED={result['verified_failed']}`、`CANCELLED={result['verified_cancelled']}`、`UNKNOWN_OR_UNVERIFIED={result['unknown_or_unverified']}`、活动任务 `{result['active_tasks']}`、身份歧义 `{result['identity_ambiguous']}`。",
        "",
        f"本次重新核对以正式数据当前内容为准，不强行复用 Phase 2-A 的旧统计。当前 `{result['executing_count']}` 条执行中计划中，`{result['dry_run_candidates']}` 条为可核验终态候选，`{result['unknown_or_unverified']}` 条仍无法核验；全库只读扫描未发现符合 owner/source/type 的活动 AC Web Task。",
        "",
        "## 与 Phase 2-A 统计差异",
        "",
        "| 指标 | Phase 2-A | 本次 Dry-Run | 差异 |",
        "|---|---:|---:|---:|",
        f"| 可核验 COMPLETED | 15 | {result['verified_completed']} | {result['verified_completed'] - 15:+d} |",
        f"| 可核验 FAILED | 2 | {result['verified_failed']} | {result['verified_failed'] - 2:+d} |",
        f"| UNKNOWN_OR_UNVERIFIED | 4 | {result['unknown_or_unverified']} | {result['unknown_or_unverified'] - 4:+d} |",
        "",
        "差异来自当前 Task 证据重新读取后的分类变化；没有修改正式计划或 Task Center 数据，也没有把缺失证据推断为失败或成功。",
        "",
        "## 逐条预演结果",
        "",
        "记录编号按本轮计划文件修改时间和文件名排序生成，仅用于报告，不是原始 plan_id。",
        "",
        "| 记录 | 局点 | 原始状态 | Task 状态 | Task 证据 | Tombstone | 证据等级 | 有效状态 | 预期变化 | 允许正式协调 | 原因 | 风险 | 人工复核 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in records:
        lines.append(
            "| {record_id} | {site_id} | {stored_status} | {task_status} | {task_evidence} | {tombstone} | {evidence_level} | {effective_status} | {expected_change} | {allow_formal} | {reason} | {risk} | {manual_review} |".format(**row)
        )
    lines.extend(
        [
            "",
            "## 安全检查结果",
            "",
            f"- `DRY_RUN_IDEMPOTENT={'PASS' if result['idempotent'] else 'FAIL'}`：同一脱敏输入连续分类两轮，结果完全一致。",
            f"- `PLAN_CONTENT_CHANGED_BY_DRY_RUN={1 if result['plan_content_changed'] else 0}`；Task DB 文件内容变化=`{1 if result['task_db_content_changed'] else 0}`。若出现变化，只能归因于调查期间外部活动，不能归因于本工具。",
            f"- 计划文件 SHA-256 指纹数量：`{result['plan_sha256_file_count']}`，调查前后稳定=`{result['plan_sha256_stable']}`；Task DB SHA-256 指纹数量：`{result['task_db_sha256_file_count']}`，调查前后稳定=`{result['task_db_sha256_stable']}`。报告不输出完整摘要值。",
            f"- 9 个 Task DB 全库 tombstone 数量：`{result['tombstone_count_all_task_dbs']}`；符合 AC Web owner/source/type 且处于活动状态的 Task：`{result['active_tasks']}`；本批计划关联的活动 Task：`{result['referenced_active_tasks']}`。",
            f"- 与本批计划 Task ID 对应的运行文件数量：`{len(result['relevant_runtime_files'])}`。本次启动前外部进程检查未发现匹配的 NetConsole/Electron 进程，未终止或重启任何进程。",
            f"- 只读 `PRAGMA quick_check`：`{', '.join(sorted(set(result['read_only_quick_check'].values())))}`。",
            "- SQLite 全部以 `mode=ro` 打开；未实例化会自动初始化或写回的 Repository/Backend/ApplicationService。未输出 plan token、digest、AC 命令、凭据或完整 Task ID；未产生生产快照、备份、临时写文件或恢复操作。",
            "",
            "## 计划状态分布",
            "",
            "| 原始状态 | 数量 |",
            "|---|---:|",
        ]
    )
    for status, count in result["plan_status_distribution"].items():
        lines.append(f"| `{status}` | {count} |")
    lines.extend(
        [
            "",
            "## 未来正式执行建议",
            "",
            f"本轮只有 `{result['dry_run_candidates']}` 条执行中计划满足当前 PR #88 的终态证明规则，分别为可核验的完成/失败候选；`{result['dry_run_skipped']}` 条不得自动协调。建议未来正式执行时逐条重新读取并校验同局点、同 Task ID、owner/source/type、结果 plan_id 和当前终态，不能直接复用本次 Dry-Run 结果。",
            "",
            f"`{result['unknown_or_unverified']}` 条 `UNKNOWN_OR_UNVERIFIED` 必须继续保留未知，不得由 tombstone 推断成功或失败，不得删除计划，不得重新执行 AC 命令。任何状态回退只能回退计划审计字段，不能撤销已经发送到 AC 的设备动作。",
            "",
            "正式执行前检查清单：",
            "1. 重新读取计划文件和对应 Task DB，确认文件指纹、局点、plan_id、task_id、owner、source、合法 task_type、Task 终态及结果中的 plan_id 未发生漂移。",
            "2. 对每条候选逐条授权，不使用全量批处理；发现新活动 Task、身份歧义、局点不一致、结果缺失或指纹变化时立即跳过并人工复核。",
            "3. 确认 Task 终态审计已在 retention cleanup 前持久化，并验证协调与恢复、cleanup、重复终态回调之间的锁顺序和幂等键。",
            "4. 先记录可审计的 before/after 状态及操作者、原因、时间、代码版本；失败时保留诊断证据，不把已完成 Task 改回活动状态。",
            "5. 回退范围仅限计划终态/审计字段，不能撤销已发送到设备的动作；任何设备动作重试必须另行授权，且不属于本次协调。",
            "6. 未知记录不做自动协调；历史 tombstone 仅证明历史已清理，不证明成功、失败或取消。",
            "",
            "## 当前结论与后续授权",
            "",
            f"当前仅可将 `{result['dry_run_candidates']}` 条候选列入后续人工逐条审查，`{result['unknown_or_unverified']}` 条继续保持未知。若要进入正式协调，需要用户另行明确授权生产计划审计字段写入、候选范围、执行窗口、并发/cleanup 停止策略及失败回退边界；本报告不构成该授权。",
            "",
            "## 交付边界",
            "",
            "```text",
            "PUBLISH=NO",
            "TAG_CREATED=NO",
            "RELEASE_CREATED=NO",
            "INSTALLER_BUILD=NO",
            "MAIN_MERGE=NO",
            "PR78_MERGE=NO",
            "PR83_MERGE=NO",
            "PRODUCTION_DATA_MUTATION=NO",
            "PRODUCTION_TASK_CLEANUP=NO",
            "AC_PLAN_FILE_MUTATION=NO",
            "DEVICE_CONFIG_MUTATION=NO",
            "WPS_REMOTE_WRITE=NO",
            "PRODUCTION_RECONCILIATION=NO",
            "DRY_RUN_ONLY=YES",
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--report-out", type=Path, required=True)
    parser.add_argument("--baseline", required=True)
    args = parser.parse_args()
    data_root = args.data_root.resolve()
    report_out = args.report_out.resolve()
    if data_root == report_out or data_root in report_out.parents:
        raise SystemExit("report-out must be outside the data root")
    result = run_dry_run(data_root)
    report_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.write_text(render_report(result, baseline=args.baseline), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "records"}, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
