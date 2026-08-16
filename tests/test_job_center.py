from __future__ import annotations

import io
import json
import subprocess
import sys
import threading
import time
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from netconsole.core.paths import PathResolver
from netconsole.services.background_job import BackgroundJob
from netconsole.services.background_tasks import (
    BackgroundTaskCancelled,
    run_background_task,
)
from netconsole.services.export.export_job import ExportJob
from netconsole.services.export.export_progress import error_event as export_error_event
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.job_center.job_events import (
    cancelled_event,
    error_event,
    finished_event,
    log_event,
    progress_event,
)
from netconsole.services.job_center.job_registry import (
    register_handler,
    registered_task_types,
)
from netconsole.services.job_center.handlers import legacy_tasks
from netconsole.services.job_center.job_runner import run_job
from netconsole.services.job_center.worker_protocol import (
    bind_worker_protocol_stream,
    encode_event,
    encode_event_bytes,
    feed_jsonl,
    parse_event_line,
    parse_worker_event_line,
    write_event,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _jsonl_events(result: subprocess.CompletedProcess[str]) -> list[dict[str, object]]:
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines
    return [json.loads(line) for line in lines]


def test_registry_contains_all_existing_task_types() -> None:
    tasks = set(registered_task_types())

    assert {
        "ac_command_action_execute",
        "device_csv_import",
        "device_connection_test",
        "site_retention_apply",
        "site_retention_scan",
        "file_management_download",
        "mesh_mr_profiles_refresh",
        "traffic_local_iperf_server",
        "traffic_local_iperf_client",
        "traffic_local_fping",
        "online_mr_agent_packages_sync",
        "online_mr_agent_package_import",
        "wireless_scan_history_refresh",
        "wireless_scan_result_load",
    } <= tasks


def test_legacy_wireless_scan_result_terminal_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from netconsole.repositories import wireless_scan_repository
    from netconsole.services.network_tools import wireless_scan_service

    class FakeRepository:
        def __init__(self, _path: Path) -> None:
            pass

        def list_results(self, _scan_id: str) -> list[dict[str, object]]:
            return [
                {"index": index, "ssid": "现场无线网络" * 20}
                for index in range(2_000)
            ]

    monkeypatch.setattr(wireless_scan_repository, "WirelessScanRepository", FakeRepository)
    monkeypatch.setattr(
        wireless_scan_service,
        "repository_row_to_display_row",
        lambda row: dict(row),
    )
    raw_file = tmp_path / "wireless-scan.txt"
    raw_file.write_text("无线扫描原始回显\n" * 50_000, encoding="utf-8")

    result = legacy_tasks._wireless_scan_result_load(
        {
            "db_path": str(tmp_path / "wireless.db"),
            "scan_id": "scan-large",
            "raw_file": str(raw_file),
            "limit": 2_000,
        },
        None,
        None,
    )
    frame = encode_event_bytes(finished_event("wireless-large", result))

    assert len(frame) < 64 * 1024
    assert result["total_items"] == 2_000
    assert result["rows_omitted"] > 0
    assert result["raw_text_truncated"] is True
    assert result["raw_text_original_length"] > len(str(result["raw_text"]))


def test_legacy_run_background_task_dispatches_registry(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)

    result = run_background_task(
        BackgroundJob(
            task_type="online_mr_mark_stale_sessions",
            params={
                "site_name": "demo",
                "app_root": str(paths.app_root),
                "data_root": str(paths.data_root),
            },
        )
    )

    assert result == {"changed_count": 0}


def test_job_events_use_complete_common_fields() -> None:
    events = [
        progress_event("job-1", "query", 1, 2, "查询中"),
        log_event("job-1", "日志"),
        finished_event("job-1", {"count": 2}),
        error_event("job-1", "失败", traceback_text="trace"),
        cancelled_event("job-1"),
    ]
    required = {
        "type",
        "job_id",
        "stage",
        "current",
        "total",
        "message",
        "result",
        "error",
        "traceback",
        "cancelled",
    }

    assert all(required <= event.keys() for event in events)
    assert events[-1]["type"] == "cancelled"
    assert events[-1]["cancelled"] is True


def test_worker_protocol_handles_partial_jsonl_and_diagnostics() -> None:
    first = encode_event(progress_event("job-1", "query", 1, 2, "查询中"))
    second = encode_event(finished_event("job-1", {"count": 2}))
    split_at = len(first) // 2

    events, diagnostics, remainder = feed_jsonl("", first[:split_at])
    assert not events
    assert not diagnostics
    events, diagnostics, remainder = feed_jsonl(
        remainder, first[split_at:] + "普通诊断\n" + second
    )

    assert [event["type"] for event in events] == ["progress", "finished"]
    assert diagnostics == ["普通诊断"]
    assert remainder == ""
    assert (
        parse_event_line('{"event":"cancelled","job_id":"job-1"}')["cancelled"] is True
    )


def test_worker_protocol_is_ascii_binary_and_bypasses_cp936_text_wrapper() -> None:
    event = progress_event("job-encoding", "auth", 1, 2, "正在验证设备凭据 · 宁波地铁12号线")
    direct = encode_event_bytes(event)
    raw = io.BytesIO()
    cp936_stdout = io.TextIOWrapper(raw, encoding="cp936", errors="strict", newline="")

    write_event(event, cp936_stdout)
    wrapped = raw.getvalue()

    assert direct == wrapped
    assert all(value < 128 for value in wrapped)
    assert json.loads(wrapped.decode("ascii"))["message"] == "正在验证设备凭据 · 宁波地铁12号线"


def test_worker_protocol_uses_current_stdout_instead_of_invalid_original(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = io.BytesIO()
    current_stdout = type("CurrentStdout", (), {"buffer": raw})()
    invalid_stdout = type("InvalidStdout", (), {"buffer": None})()
    monkeypatch.setattr(sys, "stdout", current_stdout)
    monkeypatch.setattr(sys, "__stdout__", invalid_stdout)

    write_event(progress_event("job-current", "query", 1, 1, "查询完成"))

    assert json.loads(raw.getvalue().decode("ascii"))["job_id"] == "job-current"


def test_worker_protocol_binding_survives_application_stdout_redirect() -> None:
    protocol = io.BytesIO()
    diagnostics = io.StringIO()

    with bind_worker_protocol_stream(protocol), redirect_stdout(diagnostics):
        print("raw device echo")
        write_event(progress_event("job-bound", "query", 1, 1, "查询完成"))

    assert diagnostics.getvalue() == "raw device echo\n"
    assert json.loads(protocol.getvalue().decode("ascii"))["job_id"] == "job-bound"


def test_worker_protocol_binding_is_visible_to_child_threads() -> None:
    protocol = io.BytesIO()
    diagnostics = io.StringIO()

    def emit_from_thread() -> None:
        write_event(progress_event("job-thread", "query", 1, 1, "查询完成"))

    with bind_worker_protocol_stream(protocol), redirect_stdout(diagnostics):
        thread = threading.Thread(target=emit_from_thread)
        thread.start()
        thread.join(timeout=2)

    assert not thread.is_alive()
    assert diagnostics.getvalue() == ""
    assert json.loads(protocol.getvalue().decode("ascii"))["job_id"] == "job-thread"


def test_worker_protocol_concurrent_frames_remain_parseable() -> None:
    class YieldingBinaryStream:
        def __init__(self) -> None:
            self._buffer = bytearray()
            self._buffer_lock = threading.Lock()

        def write(self, payload: bytes) -> int:
            midpoint = max(1, len(payload) // 2)
            with self._buffer_lock:
                self._buffer.extend(payload[:midpoint])
            time.sleep(0.001)
            with self._buffer_lock:
                self._buffer.extend(payload[midpoint:])
            return len(payload)

        def flush(self) -> None:
            return

        def getvalue(self) -> bytes:
            with self._buffer_lock:
                return bytes(self._buffer)

    worker_count = 16
    frames_per_worker = 16
    protocol = YieldingBinaryStream()
    start = threading.Barrier(worker_count)
    failures: list[BaseException] = []
    failures_lock = threading.Lock()

    def emit_frames(worker: int) -> None:
        try:
            start.wait(timeout=5)
            for frame in range(frames_per_worker):
                write_event(
                    progress_event(
                        f"job-{worker}",
                        "concurrent-write",
                        frame,
                        frames_per_worker,
                        f"frame-{worker}-{frame}",
                    )
                )
        except BaseException as exc:  # pragma: no cover - asserted in parent thread
            with failures_lock:
                failures.append(exc)

    with bind_worker_protocol_stream(protocol):
        threads = [
            threading.Thread(target=emit_frames, args=(worker,))
            for worker in range(worker_count)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

    assert all(not thread.is_alive() for thread in threads)
    assert failures == []
    raw = protocol.getvalue().decode("ascii")
    assert raw.endswith("\n")
    lines = raw.splitlines()
    assert len(lines) == worker_count * frames_per_worker

    observed: set[tuple[str, int]] = set()
    for line in lines:
        event, reason = parse_worker_event_line(line)
        assert reason == ""
        assert event is not None
        observed.add((str(event["job_id"]), int(event["current"])))
    assert observed == {
        (f"job-{worker}", frame)
        for worker in range(worker_count)
        for frame in range(frames_per_worker)
    }


def test_job_runner_returns_structured_cancelled_result() -> None:
    task_type = "test_job_center_cancelled"

    def cancel_handler(_context: JobContext) -> dict[str, object]:
        raise BackgroundTaskCancelled("测试取消")

    register_handler(task_type, cancel_handler)
    result = run_job(BackgroundJob(job_id="job-cancel", task_type=task_type))

    assert result.ok is False
    assert result.cancelled is True
    assert result.to_event()["type"] == "cancelled"


def test_job_runner_promotes_terminal_state_from_result() -> None:
    task_type = "test_job_center_terminal_state"

    def handler(_context: JobContext) -> dict[str, object]:
        return {"count": 1, "terminal_state": "FAILED"}

    register_handler(task_type, handler)
    result = run_job(BackgroundJob(job_id="job-failed-result", task_type=task_type))
    event = result.to_event()

    assert result.ok is True
    assert result.terminal_state == "FAILED"
    assert result.result == {"count": 1}
    assert event["type"] == "finished"
    assert event["terminal_state"] == "FAILED"
    assert event["result"] == {"count": 1}


def test_export_events_reuse_common_protocol() -> None:
    event = export_error_event(
        "export-1", "已取消", output_path="report.xlsx", cancelled=True
    )

    assert event["type"] == "cancelled"
    assert event["event"] == "cancelled"
    assert event["output_path"] == "report.xlsx"
    assert event["cancelled"] is True


@pytest.mark.parametrize(
    "entry",
    [
        [sys.executable, "-m", "netconsole.background_worker"],
        [sys.executable, str(PROJECT_ROOT / "main.py"), "--background-worker"],
        [
            sys.executable,
            str(PROJECT_ROOT / "src" / "netconsole" / "entrypoint.py"),
            "--background-worker",
        ],
    ],
    ids=["module", "main-entry", "frozen-entry"],
)
def test_background_worker_stdout_is_jsonl_only(
    tmp_path: Path, entry: list[str]
) -> None:
    job_path = tmp_path / "job.json"
    job_path.write_text(
        json.dumps(
            {
                "job_id": "unsupported-job",
                "task_type": "unsupported_test_task",
                "params": {},
                "cancel_path": "",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [*entry, "--job", str(job_path)],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 1
    events = _jsonl_events(result)
    assert events[-1]["type"] == "error"
    assert events[-1]["job_id"] == "unsupported-job"


def test_background_worker_emits_cancelled_jsonl(tmp_path: Path) -> None:
    paths = PathResolver(tmp_path)
    cancel_path = tmp_path / "cancel.flag"
    cancel_path.write_text("cancelled", encoding="utf-8")
    job_path = tmp_path / "cancel-job.json"
    job_path.write_text(
        json.dumps(
            BackgroundJob(
                job_id="cancelled-job",
                task_type="online_mr_mark_stale_sessions",
                cancel_path=str(cancel_path),
                params={
                    "site_name": "demo",
                    "app_root": str(paths.app_root),
                    "data_root": str(paths.data_root),
                },
            ).to_dict(),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, "-m", "netconsole.background_worker", "--job", str(job_path)],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 2
    events = _jsonl_events(result)
    assert events[-1]["type"] == "cancelled"
    assert events[-1]["cancelled"] is True


@pytest.mark.parametrize(
    "entry",
    [
        [sys.executable, "-m", "netconsole.export_worker"],
        [sys.executable, str(PROJECT_ROOT / "main.py"), "--export-worker"],
        [
            sys.executable,
            str(PROJECT_ROOT / "src" / "netconsole" / "entrypoint.py"),
            "--export-worker",
        ],
    ],
    ids=["module", "main-entry", "frozen-entry"],
)
def test_export_worker_stdout_is_jsonl_only(tmp_path: Path, entry: list[str]) -> None:
    output_path = tmp_path / "worker-output.txt"
    tmp_output = tmp_path / "worker-output.txt.tmp"
    job_path = tmp_path / "export-job.json"
    job_path.write_text(
        json.dumps(
            ExportJob(
                job_id="export-worker-job",
                job_type="markdown_text",
                output_path=str(output_path),
                tmp_path=str(tmp_output),
                params={"payload": {"text": "中文导出内容"}},
            ).to_dict(),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [*entry, "--job", str(job_path)],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 0
    events = _jsonl_events(result)
    assert events[-1]["type"] == "finished"
    assert output_path.read_text(encoding="utf-8") == "中文导出内容"
    assert not tmp_output.exists()


def test_export_worker_error_event_cleans_tmp_file(tmp_path: Path) -> None:
    output_path = tmp_path / "failed.txt"
    tmp_output = tmp_path / "failed.txt.tmp"
    tmp_output.write_text("partial", encoding="utf-8")
    job_path = tmp_path / "failed-export-job.json"
    job_path.write_text(
        json.dumps(
            ExportJob(
                job_id="failed-export-job",
                job_type="unsupported_export_task",
                output_path=str(output_path),
                tmp_path=str(tmp_output),
            ).to_dict(),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, "-m", "netconsole.export_worker", "--job", str(job_path)],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 1
    events = _jsonl_events(result)
    assert events[-1]["type"] == "error"
    assert events[-1]["job_id"] == "failed-export-job"
    assert not tmp_output.exists()
