"""Validate captured History migration HDD evidence without touching a source database."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


OUTPUT_NAME = "SERVER_HDD_HISTORY_MIGRATION_VALIDATION.json"


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.resolve().read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"evidence must be a JSON object: {path}")
    return value


def _under_development_root(path: Path) -> bool:
    resolved = path.resolve()
    root = Path("D:/study").resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return False
    return True


def validate_evidence(
    migration: dict[str, Any],
    host: dict[str, Any],
    observation: dict[str, Any],
) -> dict[str, Any]:
    database = dict(host.get("database") or {})
    disk = dict(host.get("disk_performance") or host.get("disk") or {})
    startup = dict(host.get("startup") or host.get("startup_log") or {})
    required_observations = {
        "target_media_is_hdd": True,
        "migration_pause_verified": True,
        "backend_ready_verified": True,
        "outbox_recovered": True,
        "ground_unattended_healthy": True,
        "syslog_receive_healthy": True,
        "mr_ping_task_persistence_healthy": True,
        "disk_not_sustained_saturated": True,
    }
    failures = [
        field
        for field, expected in required_observations.items()
        if observation.get(field) is not expected
    ]
    benchmark_ready = (
        str(migration.get("result") or "") == "COPY_ONLY_READY"
        and int(migration.get("error_count") or 0) == 0
        and float(migration.get("active_rows_per_second") or 0) > 0
    )
    if not benchmark_ready:
        failures.append("migration_benchmark")
    disk_active = disk.get("active_time_percent", "unknown")
    disk_queue = disk.get("queue_length", "unknown")
    if disk_active == "unknown" or disk_queue == "unknown":
        failures.append("disk_performance_counter")
    if not database.get("exists", True):
        failures.append("database_evidence")
    status = "PASS" if not failures else "PENDING"
    return {
        "format": "netconsole-server-hdd-history-migration-validation",
        "version": 1,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "status": status,
        "server_hdd_storage_v2_test": status,
        "metrics": {
            "migration_rows_per_second": migration.get("active_rows_per_second"),
            "chunk_latency_ms": migration.get("chunk_latency_ms", {}),
            "disk_active_time_percent": disk_active,
            "disk_queue_length": disk_queue,
            "backend_readiness": startup.get(
                "status", observation.get("backend_ready_verified")
            ),
            "history_outbox_pending": database.get("history_pending"),
            "oldest_outbox_age": observation.get("oldest_outbox_age"),
            "ground_unattended": observation.get("ground_unattended_healthy"),
            "syslog_receive": observation.get("syslog_receive_healthy"),
            "mr_ping_task_persistence": observation.get(
                "mr_ping_task_persistence_healthy"
            ),
        },
        "unmet_or_missing_gates": sorted(set(failures)),
        "source_database_opened": False,
        "migration_executed_by_validator": False,
        "destructive_operations": {"DELETE": "NO", "DROP": "NO", "VACUUM": "NO"},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--migration-benchmark", type=Path, required=True)
    parser.add_argument("--host-diagnostic", type=Path, required=True)
    parser.add_argument("--operational-observation", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output_dir.resolve()
    if not _under_development_root(output):
        raise SystemExit("output directory must remain under D:/study")
    report = validate_evidence(
        _read_object(args.migration_benchmark),
        _read_object(args.host_diagnostic),
        _read_object(args.operational_observation),
    )
    output.mkdir(parents=True, exist_ok=True)
    target = output / OUTPUT_NAME
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
