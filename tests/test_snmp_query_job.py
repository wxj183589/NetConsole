from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from netconsole.core.paths import PathResolver
from netconsole.models.snmp_models import SnmpProfile, SnmpQueryRequest, SnmpQueryResult, SnmpSetRequest, SnmpSetResult, SnmpVarBind
from netconsole.repositories.site_snmp_repository import SiteSnmpRepository
from netconsole.services.background_job import BackgroundJob
from netconsole.services.job_center.handlers import snmp_jobs
from netconsole.services.job_center.job_registry import registered_task_types
from netconsole.services.job_center.job_runner import run_job
from netconsole.services.snmp.request_builder import build_query_request, build_set_request, query_request_to_payload, set_request_to_payload
from netconsole.services.snmp.result_formatter import format_browser_rows, query_result_to_payload
from netconsole.services import snmp_client as snmp_client_module
from netconsole import background_worker
from netconsole.services.snmp_client import SnmpClient, _WireResponse, _WireVarBind
from netconsole.services.snmp_query_service import SnmpQueryService
from netconsole.ui.pages.snmp_center_page import MibBrowserPage, TEMPORARY_TARGET_KEY

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("operation", "method"),
    [
        ("GET", "Get"),
        ("GETNEXT", "GetNext"),
        ("GETBULK", "GetBulk"),
        ("WALK", "Walk"),
    ],
)
def test_snmp_query_request_builder_preserves_v2c_and_advanced_parameters(operation: str, method: str) -> None:
    request = build_query_request(
        {
            "operation": operation,
            "request": {
                "target_host": "192.0.2.10",
                "target_port": 1161,
                "snmp_version": "v2c",
                "community": "public-test",
                "oid": "1.3.6.1.2.1.1.5.0",
                "timeout": 3500,
                "retry": 2,
                "max_repetitions": 17,
                "non_repeaters": 1,
                "max_rows": 321,
                "source": "temporary",
            },
        }
    )

    assert request.method == method
    assert request.profile.host == "192.0.2.10"
    assert request.profile.port == 1161
    assert request.profile.version == "v2c"
    assert request.profile.community_ro == "public-test"
    assert request.profile.timeout_ms == 3500
    assert request.profile.retries == 2
    assert request.max_repetitions == 17
    assert request.non_repeaters == 1
    assert request.max_rows == 321
    assert request.source == "temporary"


def test_snmp_request_builder_preserves_v3_and_set_parameters() -> None:
    request = build_set_request(
        {
            "request": {
                "profile": {
                    "host": "192.0.2.20",
                    "version": "v3",
                    "username": "snmp-user",
                    "security_level": "authPriv",
                    "auth_protocol": "SHA",
                    "auth_key": "auth-secret",
                    "priv_protocol": "AES128",
                    "priv_key": "priv-secret",
                    "context_name": "ctx",
                    "timeout_ms": 5000,
                    "retries": 3,
                },
                "oid": "1.3.6.1.2.1.1.5.0",
                "set_type": "DisplayString",
                "set_value": "new-name",
                "access": "read-write",
            }
        }
    )

    assert request.profile.version == "v3"
    assert request.profile.username == "snmp-user"
    assert request.profile.security_level == "authPriv"
    assert request.profile.auth_key == "auth-secret"
    assert request.profile.priv_key == "priv-secret"
    assert request.profile.context_name == "ctx"
    assert request.data_type == "DisplayString"
    assert request.value == "new-name"


def test_snmp_query_service_reports_walk_progress_with_fake_client(tmp_path: Path) -> None:
    class FakeClient:
        def walk(self, profile, oid, *, max_rows=200, cancel_checker=None, progress_callback=None):
            del profile, cancel_checker
            if progress_callback is not None:
                progress_callback(1, max_rows)
                progress_callback(2, max_rows)
            request = SnmpQueryRequest(SnmpProfile(host="192.0.2.30"), "Walk", oid, max_rows=max_rows, save_history=False)
            return SnmpQueryResult(
                request,
                rows=[SnmpVarBind(f"{oid}.2", "b"), SnmpVarBind(f"{oid}.1", "a")],
            )

    repository = SiteSnmpRepository(tmp_path / "snmp.db")
    repository.initialize()
    service = SnmpQueryService(repository, client=FakeClient())  # type: ignore[arg-type]
    progress: list[tuple[str, int, int]] = []
    request = SnmpQueryRequest(SnmpProfile(host="192.0.2.30"), "Walk", "1.3.6.1.2.1", max_rows=20, save_history=False)

    result = service.run(request, progress_callback=lambda stage, current, total, _message: progress.append((stage, current, total)))

    assert result.status == "success"
    assert ("snmp_walk", 2, 20) in progress
    assert progress[-1] == ("snmp_query", 2, 20)


def test_snmp_getbulk_passes_non_repeaters_to_wire_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[tuple[int, int]] = []

    class FakeWireClient:
        def __init__(self, _profile) -> None:
            pass

        def request(self, _oids, *, pdu_type: int, max_repetitions: int = 10, non_repeaters: int = 0):
            captured.append((max_repetitions, non_repeaters))
            return _WireResponse("success", "", [_WireVarBind("1.3.6.1.2.1.1.5.0", "demo", "OCTET STRING")])

    monkeypatch.setattr(snmp_client_module, "_SnmpWireClient", FakeWireClient)

    result = SnmpClient().get_bulk(
        SnmpProfile(host="192.0.2.35"),
        "1.3.6.1.2.1.1",
        max_repetitions=18,
        non_repeaters=2,
    )

    assert result.status == "success"
    assert captured == [(18, 2)]


def test_snmp_query_job_formats_multirow_result_and_set(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class FakeService:
        def __init__(self, _repository) -> None:
            pass

        def run(self, request, *, cancel_checker=None, progress_callback=None):
            del cancel_checker
            if progress_callback is not None:
                progress_callback("snmp_query", 1, 2, "正在查询")
            return SnmpQueryResult(
                request,
                rows=[
                    SnmpVarBind(f"{request.oid}.2", "b", "OCTET STRING", decoded_value="乙"),
                    SnmpVarBind(f"{request.oid}.1", "a", "OCTET STRING", decoded_value="甲"),
                ],
                elapsed_ms=12,
            )

        def set_value(self, request, *, cancel_checker=None, progress_callback=None):
            del cancel_checker, progress_callback
            return SnmpSetResult(request, old_value="old", new_value=request.value, result_value=request.value, elapsed_ms=8)

    monkeypatch.setattr(snmp_jobs, "SnmpQueryService", FakeService)
    paths = PathResolver(tmp_path)
    query = SnmpQueryRequest(
        SnmpProfile(host="192.0.2.40"),
        "GetBulk",
        "1.3.6.1.2.1.2.2.1.2",
        max_repetitions=10,
        save_history=False,
        object_name="ifDescr",
        module_name="IF-MIB",
        base_oid="1.3.6.1.2.1.2.2.1.2",
    )
    progress: list[str] = []
    query_job = BackgroundJob(
        task_type="snmp_query_execute",
        params={
            "site_name": "demo",
            "operation": "GETBULK",
            "request": query_request_to_payload(query),
            "cache_result": True,
            "app_root": str(paths.app_root),
            "data_root": str(paths.data_root),
        },
    )

    query_result = run_job(query_job, progress_callback=lambda stage, *_args: progress.append(stage))

    assert query_result.ok is True
    assert query_result.result["operation"] == "GETBULK"
    assert [row[7] for row in query_result.result["browser_rows"]] == [f"{query.oid}.1", f"{query.oid}.2"]
    cached = json.loads(Path(str(query_result.result["result_file"])).read_text(encoding="utf-8"))
    assert cached["rows"][0]["value_type"] == "OCTET STRING"
    assert progress

    set_request = SnmpSetRequest(query.profile, "1.3.6.1.2.1.1.5.0", "DisplayString", "new-name", access="read-write")
    set_result = run_job(
        BackgroundJob(
            task_type="snmp_query_execute",
            params={
                "site_name": "demo",
                "operation": "SET",
                "request": set_request_to_payload(set_request),
                "app_root": str(paths.app_root),
                "data_root": str(paths.data_root),
            },
        )
    )
    assert set_result.ok is True
    assert set_result.result["set_result"]["new_value"] == "new-name"


@pytest.mark.parametrize(
    ("operation", "method"),
    [("GET", "Get"), ("GETNEXT", "GetNext"), ("GETBULK", "GetBulk"), ("WALK", "Walk")],
)
def test_snmp_query_job_executes_supported_operation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, operation: str, method: str) -> None:
    class FakeService:
        def __init__(self, _repository) -> None:
            pass

        def run(self, request, *, cancel_checker=None, progress_callback=None):
            del cancel_checker
            if progress_callback is not None:
                progress_callback("snmp_walk" if request.method == "Walk" else "snmp_query", 1, 1, "done")
            return SnmpQueryResult(request, [SnmpVarBind(request.oid, "ok")])

    monkeypatch.setattr(snmp_jobs, "SnmpQueryService", FakeService)
    paths = PathResolver(tmp_path)
    request = SnmpQueryRequest(SnmpProfile(host="192.0.2.41"), method, "1.3.6.1.2.1.1.5.0", save_history=False)
    progress: list[str] = []

    result = run_job(
        BackgroundJob(
            task_type="snmp_query_execute",
            params={
                "site_name": "demo",
                "operation": operation,
                "request": query_request_to_payload(request),
                "data_root": str(paths.data_root),
            },
        ),
        progress_callback=lambda stage, *_args: progress.append(stage),
    )

    assert result.ok is True
    assert result.result["operation"] == operation
    assert result.result["query_result"]["rows"][0]["value"] == "ok"
    assert progress


def test_snmp_query_job_exception_is_structured(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class FailingService:
        def __init__(self, _repository) -> None:
            pass

        def run(self, *_args, **_kwargs):
            raise RuntimeError("SNMP adapter failed")

    monkeypatch.setattr(snmp_jobs, "SnmpQueryService", FailingService)
    paths = PathResolver(tmp_path)
    request = SnmpQueryRequest(SnmpProfile(host="192.0.2.50"), "Get", "1.3.6.1.2.1.1.5.0", save_history=False)
    result = run_job(
        BackgroundJob(
            task_type="snmp_query_execute",
            params={
                "site_name": "demo",
                "operation": "GET",
                "request": query_request_to_payload(request),
                "data_root": str(paths.data_root),
            },
        )
    )

    assert result.ok is False
    assert result.error == "SNMP adapter failed"
    assert "RuntimeError" in result.traceback


def test_snmp_query_worker_cancel_has_one_jsonl_terminal_event(tmp_path: Path) -> None:
    cancel_path = tmp_path / "snmp.cancel"
    cancel_path.write_text("cancelled", encoding="utf-8")
    request = SnmpQueryRequest(SnmpProfile(host="192.0.2.60"), "Walk", "1.3.6.1.2.1", save_history=False)
    job_path = tmp_path / "snmp-job.json"
    job_path.write_text(
        json.dumps(
            BackgroundJob(
                job_id="snmp-cancelled",
                task_type="snmp_query_execute",
                params={"site_name": "demo", "operation": "WALK", "request": query_request_to_payload(request), "data_root": str(tmp_path)},
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


def test_snmp_query_worker_success_stdout_is_clean_jsonl(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class FakeService:
        def __init__(self, _repository) -> None:
            pass

        def run(self, request, *, cancel_checker=None, progress_callback=None):
            del cancel_checker
            print("SNMP raw debug must stay out of stdout")
            if progress_callback is not None:
                progress_callback("snmp_query", 1, 1, "GET 完成")
            return SnmpQueryResult(request, [SnmpVarBind(request.oid, "NetConsole")])

    monkeypatch.setattr(snmp_jobs, "SnmpQueryService", FakeService)
    request = SnmpQueryRequest(SnmpProfile(host="192.0.2.61"), "Get", "1.3.6.1.2.1.1.5.0", save_history=False)
    job_path = tmp_path / "snmp-success.json"
    job_path.write_text(
        json.dumps(
            BackgroundJob(
                job_id="snmp-success",
                task_type="snmp_query_execute",
                params={"site_name": "demo", "operation": "GET", "request": query_request_to_payload(request), "data_root": str(tmp_path)},
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
    assert [event["type"] for event in events] == ["progress", "finished"]
    assert events[-1]["result"]["query_result"]["rows"][0]["value"] == "NetConsole"
    assert "raw debug" not in output


def test_snmp_query_worker_stdout_is_jsonl_and_exception_is_structured(tmp_path: Path) -> None:
    request = SnmpQueryRequest(SnmpProfile(host="127.0.0.1", timeout_ms=100, retries=0), "Get", "invalid-oid", save_history=False)
    job_path = tmp_path / "snmp-error.json"
    job_path.write_text(
        json.dumps(
            BackgroundJob(
                job_id="snmp-error",
                task_type="snmp_query_execute",
                params={"site_name": "demo", "operation": "GET", "request": query_request_to_payload(request), "data_root": str(tmp_path)},
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
    assert completed.returncode == 1
    assert events[-1]["type"] == "error"
    assert events[-1]["traceback"]
    assert "SNMP adapter" not in completed.stdout


def test_snmp_query_execute_is_registered() -> None:
    task_types = registered_task_types()
    assert {
        "snmp_query_execute",
        "snmp_center_data_refresh",
        "snmp_center_data_action",
        "snmp_mib_resource_refresh",
        "snmp_product_references_refresh",
    }.issubset(task_types)


def test_mib_browser_submits_snmp_jobs_and_restores_terminal_states(tmp_path: Path, qt_application, monkeypatch: pytest.MonkeyPatch) -> None:
    del qt_application
    paths = PathResolver(tmp_path)
    center = SimpleNamespace(paths=paths, site_name="demo", snmp_set_enabled=True)
    browser = MibBrowserPage(center)
    profile = SnmpProfile(host="192.0.2.70", timeout_ms=4200, retries=2, community_rw="private")
    browser.temporary_profile = profile
    browser.temporary_name = "临时测试"
    browser.device_combo.addItem("临时测试", TEMPORARY_TARGET_KEY)
    browser.device_combo.setCurrentIndex(browser.device_combo.findData(TEMPORARY_TARGET_KEY))
    browser.oid_input.setText("1.3.6.1.2.1.1.5.0")
    submitted: list[BackgroundJob] = []
    monkeypatch.setattr(browser.query_manager, "start_job", lambda job: submitted.append(job) or job.job_id)

    browser.run_browser_query()

    assert submitted[-1].task_type == "snmp_query_execute"
    assert submitted[-1].params["operation"] == "Get"
    assert submitted[-1].params["request"]["profile"]["host"] == "192.0.2.70"
    assert submitted[-1].params["request"]["profile"]["timeout_ms"] == 4200
    assert int(submitted[-1].params["_cancel_grace_ms"]) > 0
    assert browser.go_button.isEnabled() is False
    assert browser.cancel_button.isEnabled() is True

    query = build_query_request(dict(submitted[-1].params))
    query_result = SnmpQueryResult(query, [SnmpVarBind(query.oid, "MR-01", "OCTET STRING", decoded_value="MR-01")], elapsed_ms=9)
    browser._query_job_finished(
        {
            "job_id": browser.worker,
            "result": {
                "query_result": query_result_to_payload(query_result),
                "browser_rows": format_browser_rows(query_result),
            },
        }
    )
    assert browser.result_model.rowCount() == 1
    assert browser.go_button.isEnabled() is True
    assert browser.cancel_button.isEnabled() is False

    browser.operation_combo.setCurrentIndex(browser.operation_combo.findText("Walk"))
    browser.run_browser_query()
    assert submitted[-1].params["operation"] == "Walk"
    walk_job_id = browser.worker
    browser._query_job_cancelled({"job_id": walk_job_id})
    assert browser.go_button.isEnabled() is True
    assert browser.cancel_button.isEnabled() is False
    assert "已取消" in browser.operation_label.text()

    browser.worker = "failed-job"
    browser.go_button.setEnabled(False)
    browser._query_job_failed({"job_id": "failed-job", "message": "timeout"})
    assert browser.go_button.isEnabled() is True
    assert "查询失败" in browser.operation_label.text()

    set_request = SnmpSetRequest(profile, query.oid, "DisplayString", "new-name", access="read-write")
    browser._submit_set_request(set_request)
    assert submitted[-1].params["operation"] == "SET"
    assert submitted[-1].params["request"]["data_type"] == "DisplayString"
    assert submitted[-1].params["request"]["value"] == "new-name"
    browser.close()


def test_snmp_center_page_has_no_direct_query_client_or_query_qthread() -> None:
    source = (PROJECT_ROOT / "netconsole" / "ui" / "pages" / "snmp_center_page.py").read_text(encoding="utf-8")
    assert "from netconsole.services.snmp_client import SnmpClient" not in source
    assert "SnmpClient()." not in source
    assert "SnmpQueryWorker(" not in source
    assert "SnmpSetWorker(" not in source
    assert 'task_type="snmp_query_execute"' in source
