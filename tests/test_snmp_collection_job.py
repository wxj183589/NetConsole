from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from netconsole import background_worker
from netconsole.core.paths import PathResolver
from netconsole.models.snmp_models import (
    SnmpCollectionRequest,
    SnmpCollectionTarget,
    SnmpProfile,
    SnmpQueryResult,
    SnmpVarBind,
)
from netconsole.services.background_job import BackgroundJob
from netconsole.services.job_center.handlers import snmp_jobs
from netconsole.services.job_center.job_registry import registered_task_types
from netconsole.services.job_center.job_runner import run_job
from netconsole.services.snmp.request_builder import build_collection_request, collection_request_to_payload
from netconsole.services.snmp.snmp_collection_service import SnmpCollectionService
from netconsole.ui import snmp_collection_helper


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _collection_request(count: int, *, concurrency: int = 10, retries: int = 1) -> SnmpCollectionRequest:
    return SnmpCollectionRequest(
        devices=[
            SnmpCollectionTarget(
                device_id=f"device-{index:03d}",
                device_name=f"测试设备 {index:03d}",
                profile=SnmpProfile(host=f"192.0.2.{index + 1}", timeout_ms=100, retries=retries),
            )
            for index in range(count)
        ],
        oids=["1.3.6.1.2.1.1.5.0"],
        operation="GET",
        concurrency=concurrency,
        timeout_ms=100,
        retries=retries,
    )


def test_collection_request_builder_preserves_devices_oids_and_limits() -> None:
    request = build_collection_request(
        {
            "devices": [
                {
                    "device_id": "ac-01",
                    "name": "测试 AC",
                    "ip": "192.0.2.10",
                    "version": "v3",
                    "username": "snmp-user",
                    "auth_key": "auth-secret",
                    "priv_key": "priv-secret",
                }
            ],
            "oids": ["1.3.6.1.2.1.1.5.0", "1.3.6.1.2.1.1.5.0", "1.3.6.1.2.1.1.3.0"],
            "operation": "GETBULK",
            "concurrency": 100,
            "timeout": 3500,
            "retry": 2,
            "max_repetitions": 17,
            "non_repeaters": 1,
            "max_rows": 500,
        }
    )

    assert request.operation == "GETBULK"
    assert request.concurrency == 50
    assert request.timeout_ms == 3500
    assert request.retries == 2
    assert request.oids == ["1.3.6.1.2.1.1.5.0", "1.3.6.1.2.1.1.3.0"]
    assert request.devices[0].profile.version == "v3"
    assert request.devices[0].profile.auth_key == "auth-secret"
    assert request.devices[0].profile.priv_key == "priv-secret"


def test_collection_service_runs_100_devices_concurrently_with_independent_clients() -> None:
    lock = threading.Lock()
    active = 0
    peak_active = 0
    created = 0
    closed = 0

    class FakeClient:
        def close(self) -> None:
            nonlocal closed
            with lock:
                closed += 1

    class FakeService:
        def __init__(self) -> None:
            self.client = FakeClient()

        def run(self, request, *, cancel_checker=None):
            nonlocal active, peak_active
            del cancel_checker
            with lock:
                active += 1
                peak_active = max(peak_active, active)
            time.sleep(0.005)
            with lock:
                active -= 1
            return SnmpQueryResult(request, [SnmpVarBind(request.oid, request.device_id)])

    def factory(_target):
        nonlocal created
        with lock:
            created += 1
        return FakeService()

    progress: list[tuple[str, int, int]] = []
    started = time.perf_counter()
    result = SnmpCollectionService(factory).execute(
        _collection_request(100),
        progress_callback=lambda stage, current, total, _message: progress.append((stage, current, total)),
    )
    elapsed = time.perf_counter() - started

    assert result.success_devices == 100
    assert result.failed_devices == 0
    assert created == closed == 100
    assert 2 <= peak_active <= 10
    assert elapsed < 1.0
    assert progress[0] == ("snmp_collection", 0, 100)
    assert progress[-1] == ("snmp_collection", 100, 100)


def test_collection_service_finishes_with_partial_failures() -> None:
    class FakeService:
        def run(self, request, *, cancel_checker=None):
            del cancel_checker
            index = int(request.device_id.rsplit("-", 1)[1])
            if index % 10 == 0:
                return SnmpQueryResult(request, status="timeout", error_message="timeout")
            return SnmpQueryResult(request, [SnmpVarBind(request.oid, "ok")])

    result = SnmpCollectionService(lambda _target: FakeService()).execute(_collection_request(100, retries=0))

    assert result.cancelled is False
    assert result.success_devices == 90
    assert result.failed_devices == 10
    assert len(result.device_results) == 100


def test_collection_service_retries_timeout_then_succeeds() -> None:
    attempts = 0

    class FakeService:
        def run(self, request, *, cancel_checker=None):
            nonlocal attempts
            del cancel_checker
            attempts += 1
            if attempts == 1:
                return SnmpQueryResult(request, status="timeout", error_message="timeout")
            return SnmpQueryResult(request, [SnmpVarBind(request.oid, "ok")])

    result = SnmpCollectionService(lambda _target: FakeService()).execute(_collection_request(1, retries=2))

    item = result.device_results[0].items[0]
    assert item.status == "success"
    assert item.attempts == 2
    assert attempts == 2


def test_collection_service_stop_on_failure_stops_new_devices() -> None:
    started_devices = 0
    lock = threading.Lock()

    class FakeService:
        def run(self, request, *, cancel_checker=None):
            nonlocal started_devices
            del cancel_checker
            with lock:
                started_devices += 1
            time.sleep(0.005)
            return SnmpQueryResult(request, status="timeout", error_message="timeout")

    base = _collection_request(100, concurrency=5, retries=0)
    request = SnmpCollectionRequest(
        devices=base.devices,
        oids=base.oids,
        operation=base.operation,
        concurrency=base.concurrency,
        timeout_ms=base.timeout_ms,
        retries=base.retries,
        stop_on_failure=True,
    )

    result = SnmpCollectionService(lambda _target: FakeService()).execute(request)

    assert result.stopped_early is True
    assert result.pending_devices > 0
    assert started_devices < 100


def test_collection_service_stops_submitting_after_cancel() -> None:
    cancelled = threading.Event()
    started_devices = 0
    lock = threading.Lock()

    class FakeService:
        def run(self, request, *, cancel_checker=None):
            nonlocal started_devices
            del cancel_checker
            with lock:
                started_devices += 1
            time.sleep(0.01)
            return SnmpQueryResult(request, [SnmpVarBind(request.oid, "ok")])

    def on_progress(_stage: str, current: int, _total: int, _message: str) -> None:
        if current >= 5:
            cancelled.set()

    result = SnmpCollectionService(lambda _target: FakeService()).execute(
        _collection_request(100),
        progress_callback=on_progress,
        should_cancel=cancelled.is_set,
    )

    assert result.cancelled is True
    assert result.pending_devices > 0
    assert started_devices < 100


def test_collection_job_writes_sanitized_cache_and_keeps_partial_failure_finished(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class FakeService:
        def __init__(self, _repository) -> None:
            pass

        def run(self, request, *, cancel_checker=None):
            del cancel_checker
            if request.device_id == "device-001":
                return SnmpQueryResult(request, status="timeout", error_message="timeout")
            return SnmpQueryResult(request, [SnmpVarBind(request.oid, "demo", "OCTET STRING")])

    monkeypatch.setattr(snmp_jobs, "SnmpQueryService", FakeService)
    request = _collection_request(2, retries=0)
    request = SnmpCollectionRequest(
        devices=[
            SnmpCollectionTarget(target.device_id, target.device_name, replace(target.profile, community_ro="private-secret"))
            for target in request.devices
        ],
        oids=request.oids,
        operation=request.operation,
        concurrency=request.concurrency,
        timeout_ms=request.timeout_ms,
        retries=request.retries,
    )
    paths = PathResolver(tmp_path)
    job = BackgroundJob(
        job_id="collection-cache",
        task_type="snmp_collection_execute",
        params={
            "site_name": "demo",
            "request": collection_request_to_payload(request),
            "data_root": str(paths.data_root),
        },
    )

    job_result = run_job(job)

    assert job_result.ok is True
    assert job_result.result["collection_result"]["success_devices"] == 1
    assert job_result.result["collection_result"]["failed_devices"] == 1
    cache_text = Path(str(job_result.result["result_file"])).read_text(encoding="utf-8")
    cache = json.loads(cache_text)
    assert cache["devices"][0]["items"][0]["rows"][0]["value"] == "demo"
    assert cache["records"][0].keys() >= {"device_id", "oid", "value", "timestamp", "success", "error"}
    assert "private-secret" not in cache_text


def test_collection_worker_success_stdout_is_jsonl(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class FakeService:
        def __init__(self, _repository) -> None:
            pass

        def run(self, request, *, cancel_checker=None):
            del cancel_checker
            print("SNMP collection debug")
            return SnmpQueryResult(request, [SnmpVarBind(request.oid, "ok")])

    monkeypatch.setattr(snmp_jobs, "SnmpQueryService", FakeService)
    job_path = tmp_path / "collection-success.json"
    job_path.write_text(
        json.dumps(
            BackgroundJob(
                job_id="collection-success",
                task_type="snmp_collection_execute",
                params={
                    "site_name": "demo",
                    "request": collection_request_to_payload(_collection_request(2, retries=0)),
                    "data_root": str(tmp_path),
                },
            ).to_dict(),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "__stdout__", stdout)

    return_code = background_worker.main(["--job", str(job_path)])

    output = stdout.getvalue()
    events = [json.loads(line) for line in output.splitlines() if line.strip()]
    assert return_code == 0
    assert events[-1]["type"] == "finished"
    assert events[-1]["result"]["collection_result"]["success_devices"] == 2
    assert "collection debug" not in output


def test_collection_worker_cancel_has_one_terminal_event(tmp_path: Path) -> None:
    cancel_path = tmp_path / "collection.cancel"
    cancel_path.write_text("cancelled", encoding="utf-8")
    job_path = tmp_path / "collection-cancel.json"
    job_path.write_text(
        json.dumps(
            BackgroundJob(
                job_id="collection-cancel",
                task_type="snmp_collection_execute",
                params={"site_name": "demo", "request": collection_request_to_payload(_collection_request(100)), "data_root": str(tmp_path)},
                cancel_path=str(cancel_path),
            ).to_dict(),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, "-m", "netconsole.background_worker", "--job", str(job_path)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        check=False,
    )

    events = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
    terminal = [event for event in events if event["type"] in {"finished", "error", "cancelled"}]
    assert completed.returncode == 2
    assert [event["type"] for event in terminal] == ["cancelled"]


def test_submit_snmp_collection_builds_internal_job(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: list[tuple[object, BackgroundJob, dict[str, object]]] = []

    def fake_submit(parent, job, **kwargs):
        captured.append((parent, job, kwargs))
        return "collection-job"

    monkeypatch.setattr(snmp_collection_helper, "submit_background_job", fake_submit)
    parent = SimpleNamespace()
    paths = PathResolver(tmp_path)

    job_id = snmp_collection_helper.submit_snmp_collection(parent, _collection_request(2), site_name="demo", paths=paths)  # type: ignore[arg-type]

    assert job_id == "collection-job"
    assert captured[0][1].task_type == "snmp_collection_execute"
    assert captured[0][1].params["request"]["concurrency"] == 10
    assert int(captured[0][1].params["_cancel_grace_ms"]) >= 1500


def test_snmp_collection_execute_is_registered() -> None:
    assert "snmp_collection_execute" in registered_task_types()
