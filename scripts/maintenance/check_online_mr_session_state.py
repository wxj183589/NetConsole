from __future__ import annotations

import argparse
import json
import sqlite3
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from netconsole.core.paths import PathResolver


PASSED = "PASSED"
WARNING = "WARNING"
FAILED = "FAILED"
TERMINAL_TASK_STATES = {"COMPLETED", "FAILED", "CANCELLED"}
TERMINAL_SESSION_STATES = {"STOPPED", "STOPPED_WITH_WARNINGS", "FORCED_STOPPED", "FAILED", "ABORTED"}


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class AuditReport:
    site_name: str
    task_id: str
    session_id: str
    session_dir: Path
    checks: tuple[CheckResult, ...]

    @property
    def status(self) -> str:
        if any(item.status == FAILED for item in self.checks):
            return FAILED
        if any(item.status == WARNING for item in self.checks):
            return WARNING
        return PASSED


def audit_online_mr_session(
    paths: PathResolver,
    *,
    site_name: str = "",
    task_id: str = "",
    session_id: str = "",
) -> AuditReport:
    if bool(task_id) == bool(session_id):
        raise ValueError("task_id 和 session_id 必须且只能提供一个")
    selected_site, mapping, task, events = _find_operation(
        paths,
        site_name=site_name,
        task_id=task_id,
        session_id=session_id,
    )
    selected_task_id = str(mapping["controller_task_id"])
    selected_session_id = str(mapping["session_id"] or "")
    if not selected_session_id:
        raise LookupError("任务尚未关联 Online MR session_id")
    session_dir = _find_session_dir(paths, selected_site, selected_session_id)
    meta = _read_json_object(session_dir / "session_meta.json")

    checks = [
        _check_task(task),
        _check_session(meta),
        _check_mapping(mapping),
        _check_identity(selected_site, selected_task_id, selected_session_id, mapping, task, meta),
        _check_duration(mapping, task, meta),
        _check_stop_reason(mapping, task, meta),
        _check_error_summary(mapping, task, meta),
        _check_raw(session_dir),
        _check_fping(session_dir, meta),
        _check_iperf(session_dir, meta),
        _check_traffic_flush(meta, mapping),
        _check_zip(session_dir, selected_session_id, meta, mapping),
        _check_event_order(events, meta, mapping),
    ]
    return AuditReport(
        site_name=selected_site,
        task_id=selected_task_id,
        session_id=selected_session_id,
        session_dir=session_dir,
        checks=tuple(checks),
    )


def _find_operation(
    paths: PathResolver,
    *,
    site_name: str,
    task_id: str,
    session_id: str,
) -> tuple[str, dict[str, Any], dict[str, Any] | None, list[dict[str, Any]]]:
    sites = [_safe_component(site_name)] if site_name else _site_names(paths)
    matches: list[tuple[str, dict[str, Any], dict[str, Any] | None, list[dict[str, Any]]]] = []
    for site in sites:
        db_path = paths.site_tasks_db_path(site)
        if not db_path.is_file():
            continue
        with _open_read_only(db_path) as conn:
            if not _table_exists(conn, "online_mr_task_sessions"):
                continue
            column = "controller_task_id" if task_id else "session_id"
            value = task_id or session_id
            row = conn.execute(
                f"SELECT * FROM online_mr_task_sessions WHERE site_id = ? AND {column} = ?",
                (site, value),
            ).fetchone()
            if row is None:
                continue
            mapping = dict(row)
            selected_task_id = str(mapping["controller_task_id"])
            task = None
            if _table_exists(conn, "task_snapshots"):
                task_row = conn.execute(
                    "SELECT * FROM task_snapshots WHERE task_id = ?",
                    (selected_task_id,),
                ).fetchone()
                task = dict(task_row) if task_row is not None else None
            events: list[dict[str, Any]] = []
            if _table_exists(conn, "task_events"):
                event_rows = conn.execute(
                    "SELECT sequence, event_type, event_time, payload_json "
                    "FROM task_events WHERE task_id = ? ORDER BY sequence",
                    (selected_task_id,),
                ).fetchall()
                events = [
                    {
                        "sequence": int(item["sequence"]),
                        "type": str(item["event_type"]),
                        "time": str(item["event_time"]),
                        "payload": _json_object(item["payload_json"]),
                    }
                    for item in event_rows
                ]
            matches.append((site, mapping, task, events))
    if not matches:
        identifier = task_id or session_id
        raise LookupError(f"未找到 Online MR 任务/会话映射：{identifier}")
    if len(matches) > 1:
        raise LookupError("多个局点存在同名标识，请使用 --site 指定局点")
    return matches[0]


def _check_task(task: dict[str, Any] | None) -> CheckResult:
    if task is None:
        return CheckResult("Task 状态", FAILED, "tasks.db 中缺少 task_snapshots 记录")
    status = str(task.get("status") or "")
    if status not in TERMINAL_TASK_STATES:
        return CheckResult("Task 状态", FAILED, f"仍为非终态 {status or '<empty>'}")
    task_type = str(task.get("task_type") or "")
    if task_type != "online_mr_collection_start":
        return CheckResult("Task 状态", FAILED, f"任务类型不符：{task_type or '<empty>'}")
    return CheckResult("Task 状态", PASSED, status)


def _check_session(meta: dict[str, Any]) -> CheckResult:
    status = str(meta.get("status") or "").upper()
    if status not in TERMINAL_SESSION_STATES:
        return CheckResult("Session 状态", FAILED, f"仍为非终态 {status or '<empty>'}")
    return CheckResult("Session 状态", PASSED, status)


def _check_mapping(mapping: dict[str, Any]) -> CheckResult:
    state = str(mapping.get("mapping_state") or "")
    phase = str(mapping.get("phase") or "")
    if state != "TERMINAL" or phase != "TERMINAL":
        return CheckResult("Mapping 状态", FAILED, f"mapping_state={state or '<empty>'}, phase={phase or '<empty>'}")
    return CheckResult("Mapping 状态", PASSED, "TERMINAL")


def _check_identity(
    site_name: str,
    task_id: str,
    session_id: str,
    mapping: dict[str, Any],
    task: dict[str, Any] | None,
    meta: dict[str, Any],
) -> CheckResult:
    mismatches: list[str] = []
    if str(mapping.get("site_id") or "") != site_name:
        mismatches.append("mapping.site_id")
    if str(mapping.get("controller_task_id") or "") != task_id:
        mismatches.append("mapping.controller_task_id")
    if str(mapping.get("session_id") or "") != session_id:
        mismatches.append("mapping.session_id")
    if str(meta.get("site") or "") != site_name:
        mismatches.append("session_meta.site")
    if str(meta.get("session_id") or "") != session_id:
        mismatches.append("session_meta.session_id")
    if task is not None and str(task.get("site_name") or "") != site_name:
        mismatches.append("task.site_name")
    task_result = _json_object((task or {}).get("result_json"))
    if task_result.get("session_id") and str(task_result["session_id"]) != session_id:
        mismatches.append("task.result.session_id")
    task_status = str((task or {}).get("status") or "")
    session_status = str(meta.get("status") or "").upper()
    mapping_forced = bool(mapping.get("force_stopped"))
    meta_forced = bool(meta.get("force_stopped"))
    if mapping_forced != meta_forced:
        mismatches.append("force_stopped")
    if mapping_forced and session_status != "FORCED_STOPPED":
        mismatches.append("强停 Session 状态")
    expected_sessions = {
        "COMPLETED": {"STOPPED", "STOPPED_WITH_WARNINGS"},
        "FAILED": {"FAILED"},
        "CANCELLED": {"FORCED_STOPPED", "ABORTED"},
    }
    if not mapping_forced and session_status not in expected_sessions.get(task_status, set()):
        mismatches.append("Task/Session 终态组合")
    if mismatches:
        return CheckResult("Task/Session/Mapping 一致性", FAILED, "不一致字段：" + ", ".join(mismatches))
    return CheckResult("Task/Session/Mapping 一致性", PASSED, "局点、Task ID、Session ID 一致")


def _check_duration(mapping: dict[str, Any], task: dict[str, Any] | None, meta: dict[str, Any]) -> CheckResult:
    mapping_duration = _number(mapping.get("duration_minutes"))
    meta_duration = _number(meta.get("duration_minutes"))
    task_duration = _number(_json_object((task or {}).get("result_json")).get("duration_minutes"))
    if mapping_duration is None or meta_duration is None:
        return CheckResult("duration_minutes", FAILED, "mapping 或 session_meta 缺少实际时长")
    if mapping_duration <= 0 or meta_duration <= 0:
        return CheckResult("duration_minutes", FAILED, f"实际时长不合理：mapping={mapping_duration}, meta={meta_duration}")
    values = [mapping_duration, meta_duration, *([task_duration] if task_duration is not None else [])]
    if max(values) - min(values) > 0.02:
        return CheckResult("duration_minutes", FAILED, f"时长不一致：mapping={mapping_duration}, meta={meta_duration}, task={task_duration}")
    return CheckResult("duration_minutes", PASSED, f"{meta_duration:.3f} 分钟")


def _check_stop_reason(mapping: dict[str, Any], task: dict[str, Any] | None, meta: dict[str, Any]) -> CheckResult:
    mapping_reason = str(mapping.get("stop_reason") or "")
    meta_reason = str(meta.get("stop_reason") or "")
    task_reason = str(_json_object((task or {}).get("result_json")).get("stop_reason") or "")
    if not mapping_reason or not meta_reason:
        return CheckResult("停止原因", FAILED, "mapping 或 session_meta 缺少 stop_reason")
    if mapping_reason != meta_reason:
        return CheckResult("停止原因", FAILED, f"mapping={mapping_reason}, meta={meta_reason}")
    forced = bool(mapping.get("force_stopped")) or bool(meta.get("force_stopped"))
    if forced and "force" not in mapping_reason.casefold():
        return CheckResult("停止原因", FAILED, f"强停会话的原因未体现 force_stop：{mapping_reason}")
    if not forced and task_reason and task_reason != mapping_reason:
        if task_reason == "cancel_requested" and mapping_reason in {"user_stop", "web_user_stop"}:
            return CheckResult("停止原因", PASSED, f"入口 {mapping_reason}，Worker cancel_requested")
        return CheckResult("停止原因", WARNING, f"task={task_reason}, mapping/meta={mapping_reason}")
    return CheckResult("停止原因", PASSED, mapping_reason)


def _check_error_summary(mapping: dict[str, Any], task: dict[str, Any] | None, meta: dict[str, Any]) -> CheckResult:
    summary = str(mapping.get("error_summary") or "")
    task_error = str((task or {}).get("error_message") or "")
    warnings = [str(item) for item in list(meta.get("finalization_warnings") or []) if str(item)]
    forced = bool(mapping.get("force_stopped")) or bool(meta.get("force_stopped"))
    if forced:
        if not summary and not task_error and not warnings:
            return CheckResult("error_summary", FAILED, "强停未记录错误摘要或最终化警告")
        return CheckResult("error_summary", PASSED, summary or task_error or "；".join(warnings))
    if summary or task_error or warnings:
        return CheckResult("error_summary", WARNING, summary or task_error or "；".join(warnings))
    return CheckResult("error_summary", PASSED, "无异常摘要")


def _check_raw(session_dir: Path) -> CheckResult:
    raw_dir = session_dir / "raw"
    if not raw_dir.is_dir():
        return CheckResult("raw 保留", FAILED, "raw 目录不存在")
    evidence = [path.name for path in raw_dir.iterdir() if path.is_file() and path.stat().st_size > 0]
    if not evidence:
        return CheckResult("raw 保留", WARNING, "raw 目录存在，但当前文件均为空")
    return CheckResult("raw 保留", PASSED, f"{len(evidence)} 个非空文件")


def _check_fping(session_dir: Path, meta: dict[str, Any]) -> CheckResult:
    if not bool(_json_object(meta.get("fping")).get("enabled")):
        return CheckResult("fping 输出", PASSED, "未启用")
    raw_dir = session_dir / "raw"
    evidence = ("fping_v5_raw.log", "fping_v5_samples.jsonl")
    missing_evidence = [name for name in evidence if not _non_empty(raw_dir / name)]
    if missing_evidence:
        return CheckResult("fping 输出", FAILED, "缺少或为空：" + ", ".join(missing_evidence))
    if not _non_empty(raw_dir / "fping_v5_final_summary.json"):
        forced_partial = (
            bool(meta.get("force_stopped"))
            and meta.get("finalization_complete") is False
            and str(meta.get("data_integrity") or "").casefold() == "partial"
        )
        status = WARNING if forced_partial else FAILED
        return CheckResult(status=status, name="fping 输出", detail="缺少或为空：fping_v5_final_summary.json")
    return CheckResult("fping 输出", PASSED, "raw、samples、final summary 均非空")


def _check_iperf(session_dir: Path, meta: dict[str, Any]) -> CheckResult:
    if not bool(_json_object(meta.get("iperf")).get("enabled")):
        return CheckResult("iPerf 输出", PASSED, "未启用")
    if not _non_empty(session_dir / "raw" / "iperf_client_raw.log"):
        return CheckResult("iPerf 输出", FAILED, "已启用，但 iperf_client_raw.log 缺少或为空")
    return CheckResult("iPerf 输出", PASSED, "iperf_client_raw.log 非空")


def _check_traffic_flush(meta: dict[str, Any], mapping: dict[str, Any]) -> CheckResult:
    if str(mapping.get("executor_kind") or "").upper() == "AGENT":
        integrity = str(meta.get("data_integrity") or "").casefold()
        if integrity == "complete":
            return CheckResult("Traffic flush", PASSED, "Agent 导入包已完成校验，不套用 LOCAL flush 事件顺序")
        if integrity == "partial":
            return CheckResult("Traffic flush", WARNING, "Agent 导入包为 partial，不套用 LOCAL flush 事件顺序")
        return CheckResult("Traffic flush", FAILED, f"Agent 导入包 data_integrity={integrity or '<empty>'}")
    summary = _json_object(meta.get("traffic_summary"))
    flush_complete = summary.get("flush_complete")
    finalization_complete = meta.get("finalization_complete")
    data_integrity = str(meta.get("data_integrity") or "")
    forced = bool(meta.get("force_stopped"))
    warnings = [str(item) for item in list(meta.get("finalization_warnings") or []) if str(item)]
    if flush_complete is True and finalization_complete is True and data_integrity == "complete" and not warnings:
        return CheckResult("Traffic flush", PASSED, "fping/iPerf writer 已完成 flush")
    detail = (
        f"flush_complete={flush_complete}, finalization_complete={finalization_complete}, "
        f"data_integrity={data_integrity or '<empty>'}"
    )
    if warnings:
        detail += "；" + "；".join(warnings)
    if forced and (flush_complete is not True or finalization_complete is not True) and data_integrity == "partial":
        return CheckResult("Traffic flush", WARNING, detail + "；强停按部分完整处理")
    return CheckResult("Traffic flush", FAILED, detail)


def _check_zip(
    session_dir: Path,
    session_id: str,
    meta: dict[str, Any],
    mapping: dict[str, Any],
) -> CheckResult:
    outputs_dir = session_dir / "outputs"
    archives = sorted(outputs_dir.glob("*.zip")) if outputs_dir.is_dir() else []
    if str(mapping.get("executor_kind") or "").upper() == "AGENT":
        try:
            manifest = _read_json_object(session_dir / "import_manifest.json")
        except LookupError as exc:
            return CheckResult("ZIP 检查", FAILED, str(exc))
        relative = str(manifest.get("package_relative_path") or "")
        package = (session_dir / relative).resolve()
        try:
            package.relative_to(session_dir.resolve())
        except ValueError:
            return CheckResult("ZIP 检查", FAILED, "Agent 导入包路径越界")
        if not relative or package.suffix.casefold() != ".zip" or not package.is_file():
            return CheckResult("ZIP 检查", FAILED, "Agent 导入包或 import_manifest 不完整")
        if not zipfile.is_zipfile(package):
            return CheckResult("ZIP 检查", FAILED, f"Agent ZIP 无法读取：{package.name}")
        with zipfile.ZipFile(package) as archive:
            names = archive.namelist()
        if any(Path(name).name.casefold() == "stop.request" for name in names):
            return CheckResult("ZIP 检查", FAILED, "Agent ZIP 内误包含 stop.request")
        if not any(Path(name).name.casefold() == "session_meta.json" for name in names):
            return CheckResult("ZIP 检查", FAILED, "Agent ZIP 内缺少 session_meta.json")
        return CheckResult("ZIP 检查", PASSED, f"{package.name} 可读且不含 stop.request")

    forced = bool(meta.get("force_stopped"))
    package_available = meta.get("package_available")
    if forced:
        if archives or package_available is True:
            names = ", ".join(path.name for path in archives) or "package_available=true"
            return CheckResult("ZIP 检查", FAILED, f"强停会话不应发布正式 ZIP：{names}")
        return CheckResult("ZIP 检查", PASSED, "强停未发布正式 ZIP")

    expected = outputs_dir / f"{session_id}.zip"
    if not expected.is_file() or package_available is not True:
        return CheckResult("ZIP 检查", FAILED, "正常终态缺少正式 ZIP 或 package_available 未置为 true")
    if not zipfile.is_zipfile(expected):
        return CheckResult("ZIP 检查", FAILED, f"ZIP 无法读取：{expected.name}")
    with zipfile.ZipFile(expected) as archive:
        names = archive.namelist()
    if any(Path(name).name.casefold() == "stop.request" for name in names):
        return CheckResult("ZIP 检查", FAILED, "ZIP 内误包含 stop.request")
    if "session_meta.json" not in names:
        return CheckResult("ZIP 检查", FAILED, "ZIP 内缺少 session_meta.json")
    return CheckResult("ZIP 检查", PASSED, f"{expected.name} 可读且不含 stop.request")


def _check_event_order(
    events: list[dict[str, Any]],
    meta: dict[str, Any],
    mapping: dict[str, Any],
) -> CheckResult:
    terminal = [item["sequence"] for item in events if item["type"] in {"finished", "error", "cancelled"}]
    if str(mapping.get("executor_kind") or "").upper() == "AGENT":
        if not terminal:
            return CheckResult("最终化事件顺序", FAILED, "缺少 Agent 导入 Task 终态事件")
        return CheckResult("最终化事件顺序", PASSED, "Agent 导入包不套用 LOCAL Traffic/ZIP 事件顺序")
    traffic = [
        item["sequence"]
        for item in events
        if item["type"] == "progress" and str(item["payload"].get("stage") or "") == "online_mr_stopping_traffic"
    ]
    package_done = [
        item["sequence"]
        for item in events
        if item["type"] == "progress"
        and str(item["payload"].get("stage") or "") == "online_mr_package"
        and int(item["payload"].get("current") or 0) == int(item["payload"].get("total") or 0) == 1
    ]
    if not terminal:
        return CheckResult("最终化事件顺序", FAILED, "缺少 Task 终态事件")
    if bool(meta.get("force_stopped")):
        if package_done:
            return CheckResult("最终化事件顺序", FAILED, "强停前出现正式打包完成事件")
        return CheckResult("最终化事件顺序", PASSED, "Task 已终态，未出现正式打包完成事件")
    if not traffic or not package_done:
        return CheckResult("最终化事件顺序", FAILED, "缺少 Traffic 停止或打包完成事件")
    if max(traffic) < max(package_done) < max(terminal):
        return CheckResult("最终化事件顺序", PASSED, "Traffic 停止 < ZIP 完成 < Task 终态")
    return CheckResult("最终化事件顺序", FAILED, "事件序号未满足 Traffic 停止 < ZIP 完成 < Task 终态")


def _find_session_dir(paths: PathResolver, site_name: str, session_id: str) -> Path:
    selected_id = _safe_component(session_id)
    matches = [
        sessions_dir / selected_id
        for sessions_dir in paths.online_mr_root(site_name).glob("*/sessions")
        if (sessions_dir / selected_id).is_dir()
    ]
    if not matches:
        raise LookupError(f"未找到会话目录：{selected_id}")
    if len(matches) > 1:
        raise LookupError(f"局点内存在多个同名会话目录：{selected_id}")
    return matches[0]


def _site_names(paths: PathResolver) -> list[str]:
    if not paths.sites_dir.is_dir():
        return []
    return sorted(path.name for path in paths.sites_dir.iterdir() if path.is_dir())


def _open_read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=1.0)
    connection.row_factory = sqlite3.Row
    return connection


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone() is not None


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise LookupError(f"缺少会话元数据：{path}") from exc
    except json.JSONDecodeError as exc:
        raise LookupError(f"会话元数据不是有效 JSON：{path}") from exc
    if not isinstance(value, dict):
        raise LookupError(f"会话元数据根对象必须是 JSON object：{path}")
    return value


def _json_object(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _safe_component(value: str) -> str:
    text = str(value or "").strip()
    if not text or Path(text).name != text or text in {".", ".."}:
        raise ValueError(f"不安全的路径标识：{value!r}")
    return text


def _number(value: object) -> float | None:
    try:
        return float(value) if value not in {None, ""} else None
    except (TypeError, ValueError):
        return None


def _non_empty(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def _print_report(report: AuditReport) -> None:
    print("Online MR 会话验收结果")
    print(f"- 局点：{report.site_name}")
    print(f"- Task ID：{report.task_id}")
    print(f"- Session ID：{report.session_id}")
    print(f"- 会话目录：{report.session_dir}")
    for item in report.checks:
        print(f"- {item.name}：{item.status} - {item.detail}")
    print(f"- 总体结果：{report.status}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="只读核验 Online MR Task、Session、Traffic 与 ZIP 终态")
    identity = parser.add_mutually_exclusive_group(required=True)
    identity.add_argument("--task-id", default="", help="Controller Task ID")
    identity.add_argument("--session-id", default="", help="Online MR Session ID")
    parser.add_argument("--site", default="", help="局点名；省略时扫描现有局点")
    parser.add_argument("--data-root", type=Path, default=None, help="可选数据根，默认使用 PathResolver 运行数据根")
    args = parser.parse_args(argv)
    try:
        report = audit_online_mr_session(
            PathResolver(data_root=args.data_root),
            site_name=args.site,
            task_id=args.task_id,
            session_id=args.session_id,
        )
    except (LookupError, OSError, sqlite3.Error, ValueError) as exc:
        print(f"Online MR 会话验收失败：{exc}")
        return 2
    _print_report(report)
    return 1 if report.status == FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
