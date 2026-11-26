from __future__ import annotations


import json
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from netconsole.services.terminal_controls import (
    BatchCommandDispatcher,
    QuickButtonStore,
    send_segments,
)
from netconsole.backend.api.terminal_router import router
from test_terminal_workspace import _FakeTransport, _manager_fixture, _wait_until


def test_send_string_exact_escapes_and_pause():
    assert list(send_segments(r"a\r\n\e\t\b\\\pb")) == [
        ("a\r\n\x1b\t\b\\", 0),
        ("", 1),
        ("b", 0),
    ]
    with pytest.raises(ValueError):
        list(send_segments(r"unsafe\q"))


def test_button_store_roundtrip_five_buttons_and_validation(tmp_path, monkeypatch):
    manager, _, _ = _manager_fixture(tmp_path, monkeypatch)
    try:
        store = manager.dispatcher.buttons
        document = store.read()
        buttons = document["groups"][4]["buttons"]
        for index in range(5):
            buttons.append(
                {
                    "id": f"custom-{index}",
                    "name": f"按钮{index}",
                    "action": "SEND_STRING",
                    "text": rf"display {index}\r",
                    "color": "#123abc",
                    "tooltip": "提示",
                    "disable_tooltip": False,
                    "order": index,
                    "enabled": True,
                }
            )
        store.save(document)
        assert QuickButtonStore(manager.paths).read() == document
        document["groups"][4]["buttons"].append(
            {
                "id": "clear-screen",
                "name": "清屏",
                "action": "MENU_FUNCTION",
                "text": "clear-screen",
                "color": "#123abc",
                "tooltip": "清除终端屏幕",
                "disable_tooltip": False,
                "order": 5,
                "enabled": True,
            }
        )
        store.save(document)
        assert QuickButtonStore(manager.paths).read() == document
        document["groups"][4]["buttons"].pop()
        document["groups"][4]["buttons"].append(
            {
                "id": "run-readonly",
                "name": "只读采集",
                "action": "RUN_SCRIPT",
                "text": json.dumps(
                    {"version": 1, "steps": [{"type": "SEND_STRING", "text": r"display version\r"}]}
                ),
                "color": "#123abc",
                "tooltip": "执行受限脚本",
                "disable_tooltip": False,
                "order": 6,
                "enabled": True,
            }
        )
        store.save(document)
        assert QuickButtonStore(manager.paths).read() == document
        document["groups"][4]["buttons"].pop()
        document["groups"][4]["buttons"].append(
            {
                "id": "launch-tool",
                "name": "外部终端",
                "action": "LAUNCH_APPLICATION",
                "text": "7c890030-3a3f-4d6b-b58e-7624d21daff9",
                "color": "#123abc",
                "tooltip": "启动已登记外部工具",
                "disable_tooltip": False,
                "order": 7,
                "enabled": True,
            }
        )
        store.save(document)
        assert QuickButtonStore(manager.paths).read() == document
        document["groups"][4]["buttons"].pop()
        document["groups"][4]["buttons"][0]["action"] = "SHELL"
        with pytest.raises(ValueError):
            store.save(document)
        assert (
            QuickButtonStore(manager.paths).read()["groups"][4]["buttons"][0]["action"]
            == "SEND_STRING"
        )
    finally:
        manager.close()


def test_batch_selects_two_of_three_and_audits_existing_stream(tmp_path, monkeypatch):
    manager, device, _ = _manager_fixture(tmp_path, monkeypatch)
    transports = []

    def create(*args, **kwargs):
        transport = _FakeTransport()
        transports.append(transport)
        return transport

    monkeypatch.setattr(
        "netconsole.services.terminal_workspace.create_terminal_transport", create
    )
    ids = [
        manager.create_session(device.device_uuid)[0]["session_id"] for _ in range(3)
    ]
    try:
        for key in ids:
            _wait_until(lambda: manager.get_runtime(key).snapshot.state == "RUNNING")
        job = manager.dispatcher.submit(
            ids[:2], "display a\n\ndisplay b", "lines", 0, "selected"
        )
        _wait_until(
            lambda: all(
                row["state"] == "SENT"
                for row in manager.dispatcher.get(job["id"])["rows"]
            )
        )
        assert (
            transports[0].writes
            == transports[1].writes
            == ["display a\r", "\r", "display b\r"]
        )
        assert transports[2].writes == []
        for key in ids[:2]:
            _wait_until(
                lambda: any(
                    event["event_type"] == "BATCH_SEND"
                    for event in manager.recording_events(key)
                )
            )
            assert all(
                event.get("scope") == "selected"
                for event in manager.recording_events(key)
                if event["event_type"] == "BATCH_SEND"
            )
    finally:
        manager.close()


def test_batch_cancel_preserves_sent_prefix_and_stops_delay(tmp_path, monkeypatch):
    manager, device, transport = _manager_fixture(tmp_path, monkeypatch)
    item, _ = manager.create_session(device.device_uuid)
    try:
        _wait_until(
            lambda: manager.get_runtime(item["session_id"]).snapshot.state == "RUNNING"
        )
        job = manager.dispatcher.submit(
            [item["session_id"]], r"display first\r\pdisplay second\r", "escaped"
        )
        _wait_until(lambda: bool(transport.writes))
        manager.dispatcher.cancel(job["id"])
        _wait_until(
            lambda: (
                manager.dispatcher.get(job["id"])["rows"][0]["state"]
                == "CANCELLED_PENDING"
            )
        )
        assert transport.writes == ["display first\r"]
        assert manager.dispatcher.get(job["id"])["rows"][0]["sent_segments"] == 1
    finally:
        manager.close()


def test_batch_pause_resume_and_per_device_output_export(tmp_path, monkeypatch):
    manager, device, transport = _manager_fixture(tmp_path, monkeypatch)
    item, _ = manager.create_session(device.device_uuid)
    try:
        _wait_until(
            lambda: manager.get_runtime(item["session_id"]).snapshot.state == "RUNNING"
        )
        job = manager.dispatcher.submit(
            [item["session_id"]],
            r"display first\pdisplay second\r",
            mode="escaped",
            max_concurrency=1,
            device_timeout=5,
            total_timeout=10,
            output_wait_timeout=0,
        )
        _wait_until(lambda: transport.writes == ["display first"])
        paused = manager.dispatcher.set_paused(job["id"], True)
        assert paused["state"] == "PAUSED"
        time.sleep(0.15)
        assert transport.writes == ["display first"]
        manager.dispatcher.set_paused(job["id"], False)
        _wait_until(
            lambda: manager.dispatcher.get(job["id"])["rows"][0]["state"] == "SENT"
        )
        row = manager.dispatcher.get(job["id"])["rows"][0]
        assert row["started_at_ms"] <= row["ended_at_ms"]
        assert row["duration_ms"] >= 0
        manager.dispatcher.jobs[job["id"]]["rows"][0]["output"] = "first output\nsecond output"
        csv_text = manager.dispatcher.export(job["id"], "csv")
        text_export = manager.dispatcher.export(job["id"], "txt")
        assert "address" in csv_text and "first output" in csv_text
        assert "second output" in text_export
    finally:
        manager.close()


def test_batch_http_controls_and_export(tmp_path, monkeypatch):
    manager, device, _ = _manager_fixture(tmp_path, monkeypatch)
    app = FastAPI()
    app.state.terminal_session_manager = manager
    app.include_router(router, prefix="/api")
    client = TestClient(app)
    item, _ = manager.create_session(device.device_uuid)
    try:
        _wait_until(
            lambda: manager.get_runtime(item["session_id"]).snapshot.state == "RUNNING"
        )
        response = client.post(
            "/api/terminal/batch-sends",
            json={
                "session_ids": [item["session_id"]],
                "text": r"display version\r\pdisplay version\r",
                "mode": "escaped",
                "execution_mode": "sequential",
                "max_concurrency": 1,
                "device_timeout": 5,
                "total_timeout": 10,
            },
        )
        assert response.status_code == 200
        job_id = response.json()["id"]
        paused = client.post(f"/api/terminal/batch-sends/{job_id}/pause")
        assert paused.status_code == 200
        resumed = client.post(f"/api/terminal/batch-sends/{job_id}/resume")
        assert resumed.status_code == 200
        export = client.get(f"/api/terminal/batch-sends/{job_id}/export?format=csv")
        assert export.status_code == 200
        assert "address" in export.text and "command" in export.text
    finally:
        manager.close()


def test_dispatch_failed_session_retry_does_not_modify_other_session(
    tmp_path, monkeypatch
):
    manager, device, _ = _manager_fixture(tmp_path, monkeypatch)
    item, _ = manager.create_session(device.device_uuid)
    try:
        _wait_until(
            lambda: manager.get_runtime(item["session_id"]).snapshot.state == "RUNNING"
        )
        job = manager.dispatcher.submit(
            [item["session_id"], "missing-session"], "display version\r"
        )
        _wait_until(
            lambda: all(
                row["state"] in {"SENT", "FAILED"}
                for row in manager.dispatcher.get(job["id"])["rows"]
            )
        )
        rows = manager.dispatcher.get(job["id"])["rows"]
        assert [row["state"] for row in rows] == ["SENT", "FAILED"]
        retried = manager.dispatcher.retry(job["id"], "missing-session")
        assert retried["id"] != job["id"]
        _wait_until(
            lambda: (
                manager.dispatcher.get(retried["id"])["rows"][0]["state"] == "FAILED"
            )
        )
        assert manager.dispatcher.get(job["id"])["rows"][0]["state"] == "SENT"
    finally:
        manager.close()


def test_dispatch_retry_rejects_failed_row_with_confirmed_sent_prefix(
    tmp_path, monkeypatch
):
    manager, device, _ = _manager_fixture(tmp_path, monkeypatch)
    try:
        job = manager.dispatcher.submit(["missing-session"], "display version\\r")
        _wait_until(
            lambda: manager.dispatcher.get(job["id"])["rows"][0]["state"] == "FAILED"
        )
        row = manager.dispatcher.jobs[job["id"]]["rows"][0]
        row.update(sent_segments=1, state="FAILED")
        with pytest.raises(ValueError, match="尚未发送任何数据"):
            manager.dispatcher.retry(job["id"], "missing-session")
    finally:
        manager.close()


def test_batch_retry_limit_never_retries_unconfirmed_writes(tmp_path, monkeypatch):
    manager, device, _ = _manager_fixture(tmp_path, monkeypatch)
    item, _ = manager.create_session(device.device_uuid)
    try:
        _wait_until(
            lambda: manager.get_runtime(item["session_id"]).snapshot.state == "RUNNING"
        )

        def uncertain_write(_session_id, _data, *, receipt=None):
            receipt["error"] = "transport write outcome is unknown"
            receipt["done"].set()

        monkeypatch.setattr(manager, "input", uncertain_write)
        job = manager.dispatcher.submit(
            [item["session_id"]],
            "display version\\r",
            max_retries=2,
        )
        _wait_until(
            lambda: manager.dispatcher.get(job["id"])["rows"][0]["state"]
            == "UNCONFIRMED"
        )
        row = manager.dispatcher.get(job["id"])["rows"][0]
        assert row["retry_count"] == 0
        assert row["error"].startswith("设备写入未确认")
    finally:
        manager.close()


def test_batch_output_capture_caps_retained_data_and_isolates_decode_error(tmp_path):
    events_path = tmp_path / "events.jsonl"
    events_path.write_text(
        json.dumps({"event_type": "OUTPUT", "data": "x" * 2_100_000}),
        encoding="utf-8",
    )
    runtime = SimpleNamespace(recording=SimpleNamespace(events_path=events_path))
    row = {"state": "RUNNING", "output": ""}
    job = {"deadline": time.monotonic() + 1, "cancel": threading.Event()}
    BatchCommandDispatcher._capture_output(
        None, job, runtime, row, 0, 0.05, time.monotonic() + 1
    )
    assert len(row["output"]) == 2_000_000
    assert row["output"] == "x" * 2_000_000
    assert row["state"] == "RUNNING"

    events_path.write_bytes(b"\xff\xfe")
    row = {"state": "SENT", "output": ""}
    BatchCommandDispatcher._capture_output(
        None, job, runtime, row, 0, 0.05, time.monotonic() + 1
    )
    assert row["state"] == "SENT"
    assert row["output_error"] == "无法读取该会话的输出记录"


def test_no_fixed_ssh_session_limit(tmp_path, monkeypatch):
    manager, device, _ = _manager_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "netconsole.services.terminal_workspace.create_terminal_transport",
        lambda *args, **kwargs: _FakeTransport(),
    )
    try:
        ids = [
            manager.create_session(device.device_uuid)[0]["session_id"]
            for _ in range(12)
        ]
        for key in ids:
            _wait_until(lambda: manager.get_runtime(key).snapshot.state == "RUNNING")
        assert len(set(ids)) == 12
    finally:
        manager.close()
