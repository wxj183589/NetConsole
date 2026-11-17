"""Isolated orchestration of existing SQL profilers; never starts probes.

SQL timing/templates use performance_profiling. The scoped factory adds
connection/category/fetched-row counters, without logging SQL parameters.
"""
from __future__ import annotations

import argparse
import contextvars
import json
import os
import sqlite3
import time
from collections import Counter
from contextlib import contextmanager
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from netconsole.core.performance_profiling import (
    ProfilingConnection, ProfilingCursor, begin_request_profile, end_request_profile,
)
from scripts.dev.ground_sql_profile_20261115 import _explain, _percentile


_COUNTERS = contextvars.ContextVar("sql_audit_counters", default=None)


class _AuditCursor(ProfilingCursor):
    def execute(self, sql, parameters=(), /):
        counters = _COUNTERS.get()
        self._is_read = str(sql).lstrip().split(None, 1)[0].upper() in {"SELECT", "WITH"}
        if counters is not None:
            word = str(sql).lstrip().split(None, 1)[0].upper()
            category = ("select_with" if word in {"SELECT", "WITH"} else
                        "write" if word in {"INSERT", "UPDATE", "DELETE", "REPLACE"} else
                        "transaction" if word in {"BEGIN", "COMMIT", "ROLLBACK", "END"} else
                        "pragma" if word == "PRAGMA" else "other")
            counters[category] += 1
        return super().execute(sql, parameters)

    def _rows(self, count):
        counters = _COUNTERS.get()
        if counters is not None and getattr(self, "_is_read", False):
            counters["rows"] += count

    def fetchone(self):
        row = super().fetchone()
        self._rows(int(row is not None))
        return row

    def fetchmany(self, size=None):
        rows = super().fetchmany() if size is None else super().fetchmany(size)
        self._rows(len(rows))
        return rows

    def fetchall(self):
        rows = super().fetchall()
        self._rows(len(rows))
        return rows

    def __next__(self):
        row = super().__next__()
        self._rows(1)
        return row


class _AuditConnection(ProfilingConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        counters = _COUNTERS.get()
        if counters is not None:
            counters["connections"] += 1

    def cursor(self, factory=_AuditCursor):
        return super().cursor(factory)

    def execute(self, sql, parameters=(), /):
        return self.cursor().execute(sql, parameters)


@contextmanager
def _audit_connections():
    original = sqlite3.connect

    def connect(*args, **kwargs):
        # All databases used by this process were freshly made in fixture_root.
        kwargs["factory"] = _AuditConnection
        return original(*args, **kwargs)

    with patch.object(sqlite3, "connect", connect):
        yield


def _json_default(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if is_dataclass(value):
        return {field.name: getattr(value, field.name) for field in fields(value)}
    if isinstance(value, Mapping):
        return dict(value)
    return str(value)


def _measure(name, function, iterations, *, before_each=None):
    samples = []
    slowest = []
    for index in range(iterations):
        if before_each is not None:
            before_each()
        counters = Counter()
        counter_token = _COUNTERS.set(counters)
        profile, token = begin_request_profile(f"sharing-{name}-{index}", "PROFILE", name)
        start = time.perf_counter()
        try:
            result = function()
            encoded = json.dumps(result, ensure_ascii=False, default=_json_default).encode("utf-8")
            samples.append({**{key: counters[key] for key in (
                "connections", "select_with", "write", "transaction", "pragma", "other", "rows",
            )}, "sql_count": profile.sql_count, "sql_ms": profile.sql_ms,
                "wall_ms": (time.perf_counter() - start) * 1000, "response_bytes": len(encoded)})
            slowest.extend(profile.slowest_sql)
        finally:
            end_request_profile(token)
            _COUNTERS.reset(counter_token)
    slowest.sort(reverse=True)
    return {
        "iterations": iterations,
        "metrics": {key: {f"p{p}": _percentile([row[key] for row in samples], p)
                          for p in (50, 95, 99)} for key in samples[0]},
        "samples": samples,
        "slowest_sql": [{"ms": ms, "sql": sql} for ms, sql in slowest[:5]],
    }


def _site_fixture(root, trains):
    from netconsole.backend.api.main import create_app
    from netconsole.core.database import Database
    from netconsole.core.paths import PathResolver
    from netconsole.models.api.ground_unattended import HeartbeatConfigDTO
    from netconsole.models.device import Device
    from netconsole.repositories.device_repository import DeviceRepository
    from netconsole.repositories.device_group_repository import DeviceGroupRepository
    from netconsole.services.site_manager import SiteManager

    paths = PathResolver(root / "app", root / "data")
    SiteManager(paths).create_site("profile-site")
    app = create_app(paths=paths)
    service = app.state.ground_unattended_application_service
    assets = DeviceRepository(Database(paths.site_db_path(service.site_id)))
    group = DeviceGroupRepository(assets.database, service.site_id).find_by_name("车载-MR")
    assert group is not None
    for index in range(trains * 2):
        role = "CT" if index % 2 == 0 else "CW"
        assets.create(Device(
            device_uuid=str(UUID(int=index + 1, version=4)),
            name=f"LC{index // 2 + 1:03d}-MR-{role}", device_type="MR", group_id=group.id,
            primary_address=f"198.18.{index // 250}.{1 + index % 250}",
            backup_address=f"198.19.{index // 250}.{1 + index % 250}",
            ssh_enabled=True, ssh_username="synthetic", ssh_password="fixture-only",
        ))
    service.repository.save_heartbeat_config(HeartbeatConfigDTO(enabled=False))
    collection = service.inventory_sync.collect()
    # Keep the harness runnable against both the baseline tuple and new value.
    endpoints = collection.endpoints if hasattr(collection, "endpoints") else collection[1]
    assert len(endpoints) == trains * 2, (len(endpoints), trains)
    service.inventory_sync.synchronize()
    return service, endpoints


def _site_cases(service, endpoints):
    from netconsole.models.api.ground_unattended import GroundQuickPingStartRequestDTO

    def refresh():
        preview = service.inventory_sync.preview()
        summary = service.inventory_sync.synchronize()
        return {"devices": preview["device_count"], "summary": summary}

    def targets_and_syslog():
        targets = service.supervisor.heartbeat._configure_heartbeat_targets("heartbeat-resident")
        service.supervisor.syslog_receiver.refresh_inventory()
        return {"mr": len(targets), "ip": sum(len(item.management_ips) for item in targets)}

    def quick_validate():
        payload = GroundQuickPingStartRequestDTO(targets=[{
            "mr_id": row["device_uuid"], "target_ip": row["management_ip"], "address_role": "PRIMARY",
        } for row in endpoints[:16]])
        # Stop exactly at the probe boundary. Real IP reservation/start is
        # covered by tests, never by this offline SQL profile.
        class Validated(Exception):
            pass

        def validated(**kwargs):
            raise Validated(len(kwargs["targets"]))

        with patch.object(service.quick_ping, "start", validated):
            try:
                service.quick_ping_start(service.site_id, payload)
            except Validated as exc:
                return {"validated": exc.args[0]}
        raise AssertionError("probe boundary not reached")

    return {
        "inventory_collect": service.inventory_sync.collect,
        "preview_synchronize": refresh,
        "heartbeat_targets_syslog": targets_and_syslog,
        "heartbeat_api_empty": lambda: service.heartbeat(service.site_id, page_size=200),
        "quick_ping_validate": quick_validate,
        "quick_ping_history": lambda: service.repository.query_quick_ping_runs(limit=20),
    }


def _shared_inventory_plans(site_db_path, ground_db_path, site_id):
    """Explain the added batch read and the actual all-inventory snapshot query."""
    statements = {
        "device_uuid_batch": (site_db_path,
            "SELECT * FROM devices WHERE device_uuid IN (?, ?)", ("synthetic-a", "synthetic-b")),
        "credential_uuid_batch": (site_db_path,
            "SELECT device_uuid, credential_field, status, source, error_code "
            "FROM device_credential_states WHERE device_uuid IN (?, ?)",
            ("synthetic-a", "synthetic-b")),
        "shared_inventory_all": (ground_db_path,
            "SELECT i.*, p.enabled, p.priority, p.scheduling_priority, "
            "p.deep_collection_enabled, p.monitor_only, p.remark "
            "FROM ground_unattended_train_inventory i "
            "LEFT JOIN ground_unattended_train_policies p "
            "ON p.site_id=i.site_id AND p.train_id=i.train_id WHERE i.site_id=? "
            "ORDER BY COALESCE(p.priority, 0) DESC, COALESCE(p.scheduling_priority, 0) DESC, "
            "i.train_no, i.train_id", (site_id,)),
        "shared_endpoints_all": (ground_db_path,
            "SELECT * FROM ground_unattended_train_endpoints WHERE site_id=? "
            "ORDER BY train_id, mr_role", (site_id,)),
        "shared_selection_state": (ground_db_path,
            "SELECT * FROM ground_unattended_heartbeat_inventory_state WHERE site_id=?", (site_id,)),
    }
    result = {}
    for name, (path, sql, params) in statements.items():
        connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
        try:
            result[name] = {"sql": sql, "plan": [str(row[3]) for row in connection.execute(
                "EXPLAIN QUERY PLAN " + sql, params,
            )]}
        finally:
            connection.close()
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--trains", type=int, nargs="+", default=[25, 50, 100])
    parser.add_argument("--cold-reads", action="store_true",
                        help="Also measure each static read after expiring the Site caches")
    args = parser.parse_args()
    from netconsole.core.runtime_environment import test_data_root_base

    base = test_data_root_base(repository_root=Path(__file__).resolve().parents[2]).resolve()
    fixture_root = args.fixture_root.resolve()
    if not fixture_root.is_relative_to(base) or fixture_root == base:
        parser.error(f"fixture root must be a new child of {base}")
    if args.iterations < 5 or min(args.trains) < 1:
        parser.error("iterations >= 5 and trains >= 1 required")
    fixture_root.mkdir(parents=True, exist_ok=False)
    os.environ["NETCONSOLE_RUNTIME_MODE"] = "test"
    os.environ["NETCONSOLE_DATA_ROOT"] = str(fixture_root / "session")
    result = {"harness": str(Path(__file__).name), "scales": {}, "query_plans": {},
              "notes": ["Offline synthetic data only; no lifespan/probes/devices started.",
                        "SQL count uses existing execute timing; PRAGMA/explicit transactions separated.",
                        "Rows counts fetched SELECT/WITH rows, including metadata; bytes are JSON projection bytes.",
                        "executemany/executescript remain one profiler call; not per expanded statement.",
                        "Wall time includes JSON serialization; samples include cold and warm reads."]}
    with _audit_connections():
        for trains in args.trains:
            service, endpoints = _site_fixture(fixture_root / f"trains-{trains}", trains)
            cases = _site_cases(service, endpoints)
            result["scales"][str(trains)] = {
                "trains": trains, "mr": trains * 2, "ip": trains * 4,
                "cases": {name: _measure(name, function, args.iterations)
                          for name, function in cases.items()},
            }
            if args.cold_reads:
                def expire_static_caches():
                    service.inventory_sync._collection_loaded_at = 0.0
                    service.repository._inventory_loaded_at = 0.0

                result["scales"][str(trains)]["cold_cases"] = {
                    name: _measure(name, function, args.iterations,
                                   before_each=expire_static_caches)
                    for name, function in cases.items() if name != "quick_ping_history"
                }
            result["query_plans"][str(trains)] = _explain(service.repository.db_path)
            result["query_plans"][str(trains)]["shared_reads"] = _shared_inventory_plans(
                service.paths.site_db_path(service.site_id), service.repository.db_path, service.site_id,
            )
        from scripts.dev.job_center_sql_profile_20261116 import _fixture, SITE_ID
        _, _, query = _fixture(fixture_root / "jobs", 120)
        result["job_center"] = {
            name: _measure(name, function, args.iterations) for name, function in {
                "list": lambda: query.list_tasks(SITE_ID, limit=500),
                "summary": lambda: query.get_summary(SITE_ID),
                "detail": lambda: query.get_task(SITE_ID, "closeout-task-0000"),
                "logs": lambda: query.get_logs(SITE_ID, "closeout-task-0000", tail=300),
            }.items()
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "scales": list(result["scales"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
