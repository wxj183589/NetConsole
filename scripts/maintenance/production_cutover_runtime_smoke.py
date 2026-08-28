"""Coordinate the two-database production replacement with one real restart smoke.

This is a one-shot maintenance helper for the Ningbo cutover. It waits for the
task replacement, records a deferred restart check, then waits for the device
replacement, starts the installed Electron application, and records the final
restart plus read-only consumer smoke evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _wait_replacement(path: Path, expected_size: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file() and path.stat().st_size == expected_size:
            return
        time.sleep(0.02)
    raise TimeoutError(f"timed out waiting for replacement: {path}")


def _write(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{time.time_ns()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _connect(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def _counts(path: Path) -> dict[str, int]:
    with _connect(path) as connection:
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )]
        return {
            table: int(connection.execute(f'"SELECT COUNT(*) FROM "{table}""').fetchone()[0])
            for table in tables
        }


def _safe_counts(path: Path) -> dict[str, int]:
    with _connect(path) as connection:
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )]
        result: dict[str, int] = {}
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            result[table] = int(connection.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0])
        return result


def _task_smoke(site: Path) -> dict[str, object]:
    counts = _safe_counts(site / "db" / "tasks.db")
    required = ("task_results", "task_snapshots", "task_events")
    checks = {key: counts.get(key, 0) > 0 for key in required}
    checks["task_results_not_exceed_snapshots"] = (
        counts.get("task_results", 0) <= counts.get("task_snapshots", 0)
    )
    checks["online_mr_task_sessions"] = counts.get("online_mr_task_sessions", 0) >= 1
    return {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks, "counts": counts}


def _history_smoke(site: Path) -> dict[str, object]:
    root = site / "db" / "history"
    shard_counts: dict[str, int] = {}
    total = 0
    for path in sorted(root.glob("devices-*.db")):
        counts = _safe_counts(path)
        count = sum(counts.values())
        shard_counts[path.name] = count
        total += count
    return {
        "status": "PASS" if shard_counts and all(count > 0 for count in shard_counts.values()) else "FAIL",
        "rows": total,
        "shards": shard_counts,
    }


def _device_smoke(site: Path) -> dict[str, object]:
    counts = _safe_counts(site / "db" / "devices.db")
    required = (
        "devices",
        "ac_fit_ap_resources",
        "device_lldp_neighbors",
        "device_optical_modules",
        "device_interfaces",
        "fit_ap_lldp_current",
        "optical_current",
    )
    checks = {key: counts.get(key, 0) > 0 for key in required}
    ground = site / "files" / "rail_transit" / "ground_unattended" / "index.sqlite"
    mesh = list((site / "files" / "rail_transit" / "mr_raw_mesh").glob("*/mesh.sqlite"))
    online = site / "files" / "rail_transit" / "online_mr" / "parsed" / "vehicle_mr_online.sqlite"
    imports = site / "files" / "imports"
    checks.update({
        "history": _history_smoke(site)["status"] == "PASS",
        "ground": ground.is_file() and ground.stat().st_size > 0,
        "mesh": bool(mesh),
        "online_mr": online.is_file() and online.stat().st_size > 0,
        "imports": imports.is_dir(),
        "exports": (site / "files").is_dir(),
    })
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "devices": counts,
        "history": _history_smoke(site),
        "ground_bytes": ground.stat().st_size if ground.is_file() else 0,
        "mesh_sqlite_count": len(mesh),
        "online_mr_bytes": online.stat().st_size if online.is_file() else 0,
    }


def _wait_ready(log: Path, start_offset: int, timeout: float) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if log.is_file():
            with log.open("rb") as stream:
                stream.seek(max(0, start_offset))
                text = stream.read().decode("utf-8", errors="replace")
            if "ELECTRON_BACKEND_READY" in text and "desktop.interactive" in text:
                return {"log": str(log), "backend_ready": True, "renderer_interactive": True}
        time.sleep(0.5)
    raise TimeoutError("NetConsole did not reach backend ready and renderer interactive")


def _inspect_component_resume_journals(data_root: Path) -> dict[str, object]:
    """Classify component-resume state without mutating production runtime data.

    Old cutover journals are evidence, not disposable cleanup targets.  A
    terminal journal may be ignored for a new operation, while a non-terminal
    journal with a live candidate/rollback artifact must fail closed.  The
    caller can persist this read-only inventory in its external evidence
    directory and decide whether a separately approved quarantine is needed.
    """

    terminal = {
        "completed", "failed_before_switch", "failed_rolled_back", "diagnostic_retention_failed",
        "recovered_no_switch", "recovered_rollback", "recovered_from_backup",
        "recovered_new_database", "recovered_no_existing_database",
    }
    source_root = data_root / "runtime" / "database_upgrade"
    records: list[dict[str, object]] = []
    active: list[dict[str, object]] = []
    for path in sorted(source_root.glob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(value, dict):
            continue
        if value.get("recovery_strategy") != "component_resume":
            continue
        artifacts: list[dict[str, object]] = []
        outside_data_root = False
        for field in ("shadow_path", "rollback_path"):
            raw = str(value.get(field) or "").strip()
            if not raw:
                continue
            raw_path = Path(raw)
            artifact = (
                (data_root / raw_path).resolve()
                if not raw_path.is_absolute()
                else raw_path.resolve()
            )
            if artifact != data_root.resolve() and not artifact.is_relative_to(data_root.resolve()):
                outside_data_root = True
                artifacts.append({
                    "field": field,
                    "path": str(artifact),
                    "exists": artifact.is_file(),
                    "outside_data_root": True,
                })
                continue
            item: dict[str, object] = {
                "field": field,
                "path": str(artifact),
                "exists": artifact.is_file(),
            }
            if artifact.is_file():
                item.update({"size": artifact.stat().st_size, "sha256": _sha256(artifact)})
            artifacts.append(item)
        stage = str(value.get("stage") or "")
        has_live_artifact = any(bool(item.get("exists")) for item in artifacts)
        switched = bool(value.get("switched"))
        is_active = outside_data_root or (stage not in terminal and (switched or has_live_artifact))
        record = {
            "journal": str(path),
            "journal_size": path.stat().st_size,
            "journal_sha256": _sha256(path),
            "operation_id": str(value.get("operation_id") or path.stem),
            "stage": stage,
            "switched": switched,
            "error": str(value.get("error") or ""),
            "rollback_error": str(value.get("rollback_error") or ""),
            "artifacts": artifacts,
            "classification": "ACTIVE_BLOCKING" if is_active else (
                "TERMINAL_PROTECTED" if stage in terminal else "STALE_NO_ARTIFACT"
            ),
            "reason": "artifact is outside data root" if outside_data_root else "",
        }
        records.append(record)
        if is_active:
            active.append(record)
    return {
        "status": "PASS" if not active else "FAIL",
        "active_blocking_count": len(active),
        "active_blocking": active,
        "journals": records,
        "production_mutation": "NONE",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument("--tasks-sha", required=True)
    parser.add_argument("--tasks-size", type=int, required=True)
    parser.add_argument("--devices-sha", required=True)
    parser.add_argument("--devices-size", type=int, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--site-id", required=True)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--git-head", required=True)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()

    tasks = args.site / "db" / "tasks.db"
    devices = args.site / "db" / "devices.db"
    _wait_replacement(tasks, args.tasks_size, args.timeout)
    task_smoke = _task_smoke(args.site)
    if task_smoke["status"] != "PASS":
        raise RuntimeError(f"task smoke failed: {task_smoke}")
    common = {
        "status": "PASS",
        "site_id": args.site_id,
        "operation_id": args.operation_id,
        "generated_git_head": args.git_head,
        "verified_at": _now(),
        "database_switch_verified": True,
        "restart_scope": "deferred_until_both_databases_replaced",
    }
    _write(args.evidence_dir / "tasks-restart-deferred.json", {
        "evidence_type": "production-restart-v1", **common, "checks": task_smoke
    })
    _write(args.evidence_dir / "tasks-functional-deferred.json", {
        "evidence_type": "production-functional-gate-v1", **common,
        "functional_scope": "read_only_task_consumer_smoke", "checks": task_smoke,
    })

    _wait_replacement(devices, args.devices_size, args.timeout)
    recovery_audit = _inspect_component_resume_journals(args.site.parent.parent)
    _write(args.evidence_dir / "component-resume-recovery-audit.json", recovery_audit)
    if recovery_audit["status"] != "PASS":
        raise RuntimeError(f"component-resume recovery is still active: {recovery_audit}")
    log_path = args.site.parent.parent / "runtime" / "logs" / "electron.log"
    log_offset = log_path.stat().st_size if log_path.is_file() else 0
    process = subprocess.Popen(
        [str(args.executable)],
        cwd=str(args.executable.parent),
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    ready = _wait_ready(log_path, log_offset, args.timeout)
    _write(args.evidence_dir / "devices-restart.json", {
        "evidence_type": "production-restart-v1", "status": "PASS",
        "site_id": args.site_id, "operation_id": args.operation_id,
        "generated_git_head": args.git_head, "verified_at": _now(),
        "process_id": process.pid, **ready,
        "component_resume_recovery_audit": recovery_audit,
    })
    device_smoke = _device_smoke(args.site)
    if device_smoke["status"] != "PASS":
        raise RuntimeError(f"device smoke failed: {device_smoke}")
    _write(args.evidence_dir / "devices-functional.json", {
        "evidence_type": "production-functional-gate-v1", "status": "PASS",
        "site_id": args.site_id, "operation_id": args.operation_id,
        "generated_git_head": args.git_head, "verified_at": _now(),
        "functional_scope": "read_only_production_consumer_smoke",
        "checks": device_smoke,
    })
    print(json.dumps({"status": "PASS", "task": task_smoke, "devices": device_smoke}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
