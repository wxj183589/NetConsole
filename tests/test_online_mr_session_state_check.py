from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

from netconsole.core.paths import PathResolver
from scripts.maintenance.check_online_mr_session_state import FAILED, WARNING, audit_online_mr_session, main


def _write_operation(
    paths: PathResolver,
    *,
    task_id: str,
    session_id: str,
    forced: bool = False,
    forced_fping: bool = False,
) -> tuple[Path, Path]:
    site = "site-a"
    db_path = paths.site_tasks_db_path(site)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    status = "CANCELLED" if forced else "COMPLETED"
    session_status = "FORCED_STOPPED" if forced else "STOPPED"
    stop_reason = "force_stop" if forced else "user_stop"
    result = {
        "session_id": session_id,
        "status": session_status,
        "stop_reason": "cancel_requested" if not forced else stop_reason,
        "duration_minutes": 2.0,
    }
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE task_snapshots (
                task_id TEXT PRIMARY KEY,
                task_type TEXT,
                status TEXT,
                site_name TEXT,
                result_json TEXT
            );
            CREATE TABLE online_mr_task_sessions (
                controller_task_id TEXT PRIMARY KEY,
                session_id TEXT,
                site_id TEXT,
                phase TEXT,
                mapping_state TEXT,
                duration_minutes REAL,
                stop_reason TEXT,
                force_stopped INTEGER,
                error_summary TEXT
            );
            CREATE TABLE task_events (
                sequence INTEGER PRIMARY KEY,
                task_id TEXT,
                event_type TEXT,
                event_time TEXT,
                payload_json TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO task_snapshots VALUES (?, 'online_mr_collection_start', ?, ?, ?)",
            (task_id, status, site, json.dumps(result)),
        )
        conn.execute(
            "INSERT INTO online_mr_task_sessions VALUES (?, ?, ?, 'TERMINAL', 'TERMINAL', 2.0, ?, ?, ?)",
            (task_id, session_id, site, stop_reason, int(forced), "强停后 writer flush 未确认" if forced else ""),
        )
        events = [
            (1, "progress", {"stage": "online_mr_stopping_traffic", "current": 0, "total": 0}),
        ]
        if not forced:
            events.extend(
                [
                    (2, "progress", {"stage": "online_mr_package", "current": 0, "total": 1}),
                    (3, "progress", {"stage": "online_mr_package", "current": 1, "total": 1}),
                    (4, "finished", {"result": result}),
                ]
            )
        else:
            events.append((2, "cancelled", {"error": "forced"}))
        conn.executemany(
            "INSERT INTO task_events VALUES (?, ?, ?, '2026-07-13T10:02:00Z', ?)",
            [(sequence, task_id, event_type, json.dumps(payload)) for sequence, event_type, payload in events],
        )

    session_dir = paths.online_mr_session_dir(site, "MR-07__7", session_id)
    raw_dir = session_dir / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "terminal_monitor_raw.log").write_text("raw evidence\n", encoding="utf-8")
    fping = {"enabled": not forced or forced_fping}
    if fping["enabled"]:
        (raw_dir / "fping_v5_raw.log").write_text("ping raw\n", encoding="utf-8")
        (raw_dir / "fping_v5_samples.jsonl").write_text('{"rtt_ms": 1.0}\n', encoding="utf-8")
    if not forced:
        (raw_dir / "fping_v5_final_summary.json").write_text('{"Status": "stopped"}\n', encoding="utf-8")
    meta = {
        "session_id": session_id,
        "site": site,
        "status": session_status,
        "started_at": "2026-07-13 10:00:00",
        "ended_at": "2026-07-13 10:02:00",
        "duration_minutes": 2.0,
        "stop_reason": stop_reason,
        "force_stopped": forced,
        "fping": fping,
        "iperf": {"enabled": False},
        "traffic_summary": {"flush_complete": not forced},
        "finalization_warnings": ["强停后 writer flush 未确认"] if forced else [],
        "finalization_complete": not forced,
        "package_available": not forced,
        "data_integrity": "partial" if forced else "complete",
    }
    (session_dir / "session_meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    if not forced:
        package_path = session_dir / "outputs" / f"{session_id}.zip"
        package_path.parent.mkdir(parents=True)
        with zipfile.ZipFile(package_path, "w") as archive:
            archive.writestr("session_meta.json", json.dumps(meta, ensure_ascii=False))
            archive.writestr("raw/terminal_monitor_raw.log", "raw evidence\n")
    return db_path, session_dir


def test_session_check_passes_normal_stop_without_writing_data(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    db_path, session_dir = _write_operation(paths, task_id="task-normal", session_id="session-normal")
    before_db = db_path.read_bytes()
    before_meta = (session_dir / "session_meta.json").read_bytes()

    report = audit_online_mr_session(paths, site_name="site-a", session_id="session-normal")

    assert report.status != FAILED
    assert all(item.status != FAILED for item in report.checks)
    assert db_path.read_bytes() == before_db
    assert (session_dir / "session_meta.json").read_bytes() == before_meta


def test_session_check_accepts_force_stop_as_partial_warning_without_zip(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    _write_operation(paths, task_id="task-force", session_id="session-force", forced=True)

    report = audit_online_mr_session(paths, task_id="task-force")

    assert report.status == WARNING
    assert all(item.status != FAILED for item in report.checks)
    assert next(item for item in report.checks if item.name == "Traffic flush").status == WARNING
    assert next(item for item in report.checks if item.name == "ZIP 检查").detail == "强停未发布正式 ZIP"


def test_session_check_warns_when_forced_fping_has_no_final_summary(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    _write_operation(
        paths,
        task_id="task-force-fping",
        session_id="session-force-fping",
        forced=True,
        forced_fping=True,
    )

    report = audit_online_mr_session(paths, task_id="task-force-fping")

    fping_check = next(item for item in report.checks if item.name == "fping 输出")
    assert report.status == WARNING
    assert fping_check.status == WARNING
    assert "fping_v5_final_summary.json" in fping_check.detail


def test_session_check_rejects_stop_request_inside_zip(tmp_path: Path) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    _db_path, session_dir = _write_operation(paths, task_id="task-bad-zip", session_id="session-bad-zip")
    package_path = session_dir / "outputs" / "session-bad-zip.zip"
    with zipfile.ZipFile(package_path, "a") as archive:
        archive.writestr("stop.request", "stop")

    report = audit_online_mr_session(paths, site_name="site-a", task_id="task-bad-zip")

    zip_check = next(item for item in report.checks if item.name == "ZIP 检查")
    assert zip_check.status == FAILED
    assert "stop.request" in zip_check.detail


def test_session_check_cli_prints_chinese_summary(tmp_path: Path, capsys) -> None:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path)
    _write_operation(paths, task_id="task-cli", session_id="session-cli")

    exit_code = main(["--data-root", str(tmp_path), "--task-id", "task-cli"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Online MR 会话验收结果" in output
    assert "Task 状态：PASSED" in output
    assert "总体结果：PASSED" in output
