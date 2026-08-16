from __future__ import annotations

import json
from pathlib import Path

import scripts.maintenance.benchmark_database_functional_queries as benchmark


def _file(path: Path, value: str = "evidence") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return path


def test_benchmark_pair_requires_semantic_parity() -> None:
    passed = benchmark._benchmark_pair(
        "case", lambda: [{"id": 1}], lambda: [{"id": 1}], iterations=10
    )
    failed = benchmark._benchmark_pair(
        "case", lambda: [{"id": 1}], lambda: [{"id": 2}], iterations=10
    )

    assert passed["status"] == "PASS"
    assert passed["semantic_match"] is True
    assert failed["status"] == "FAIL"
    assert failed["semantic_match"] is False


def test_benchmark_emits_all_required_cases_and_readonly_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    before_devices = _file(tmp_path / "before" / "devices.db")
    after_devices = _file(tmp_path / "after" / "devices.db")
    before_tasks = _file(tmp_path / "before" / "tasks.db")
    after_tasks = _file(tmp_path / "after" / "tasks.db")
    history = tmp_path / "after" / "history"
    history.mkdir()
    source_site = tmp_path / "package-source" / "sites" / "line-12"
    imported_site = tmp_path / "package-imported" / "sites" / "line-12"
    source_site.mkdir(parents=True)
    imported_site.mkdir(parents=True)
    package = _file(
        tmp_path / "SITE_PACKAGE.json",
        json.dumps(
            {
                "format": "netconsole-integrated-site-package-validation-v1",
                "status": "PASS",
            }
        ),
    )

    monkeypatch.setattr(
        benchmark, "_package_sites", lambda _report, _development: (source_site, imported_site)
    )
    monkeypatch.setattr(
        benchmark, "_table_rows", lambda database, table, order: [{"table": table, "id": 1}]
    )
    monkeypatch.setattr(
        benchmark,
        "_history_case",
        lambda _database: {
            "table": "device_interfaces_history",
            "kind": "device_interface",
            "entity_fields": ["device_uuid", "interface_name"],
            "entity_values": ["device-1", "GE1/0/1"],
            "entity_key": "device-1:GE1/0/1",
            "collected_from": "2026-08-01T00:00:00",
            "collected_to": "2026-08-01T01:00:00",
        },
    )
    history_rows = [{"event_id": "a" * 64, "collected_at": "2026-08-01T00:00:00"}]
    monkeypatch.setattr(
        benchmark,
        "_legacy_history_rows",
        lambda database, case, entity_only: history_rows,
    )
    monkeypatch.setattr(
        benchmark,
        "_history_store_rows",
        lambda root, case, entity_only: history_rows,
    )
    monkeypatch.setattr(benchmark, "_ReadonlyTaskRepository", lambda *args, **kwargs: object())
    monkeypatch.setattr(benchmark, "_task_list", lambda repository: [{"task_id": "task-1"}])
    monkeypatch.setattr(benchmark, "_representative_task_id", lambda repository: "task-1")
    monkeypatch.setattr(
        benchmark,
        "_task_detail",
        lambda repository, task_id: {"task_id": task_id, "result": {"ok": True}},
    )
    monkeypatch.setattr(
        benchmark,
        "_largest_relative_database",
        lambda site, pattern: site / "files" / "mesh.sqlite",
    )

    output = tmp_path / "reports" / "DATABASE_PERFORMANCE.json"
    report = benchmark.benchmark_database_functional_queries(
        before_devices=before_devices,
        after_devices=after_devices,
        before_tasks=before_tasks,
        after_tasks=after_tasks,
        after_history_root=history,
        site_package_report=package,
        output_path=output,
        iterations=10,
        development_root=tmp_path.parent.parent,
    )

    assert report["status"] == "PASS"
    assert [item["id"] for item in report["cases"]] == list(benchmark.REQUIRED_CASES)
    assert all(item["status"] == "PASS" for item in report["cases"])
    assert report["safety"]["sqlite_mode"] == "mode=ro&immutable=1"
    assert json.loads(output.read_text(encoding="utf-8"))["git_head"] == report["git_head"]
