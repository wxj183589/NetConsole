from __future__ import annotations


import pytest

from netconsole.services.terminal_controls import QuickButtonStore, send_segments
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
