from __future__ import annotations

import hashlib
import io
from pathlib import Path
from zipfile import ZipFile

import pytest

from netconsole.services.terminal_transcript import InputEditor, render_colored_preview, render_events
from test_terminal_workspace import _manager_fixture, _wait_until


def test_colored_preview_preserves_text_and_leaves_plain_transcript_unchanged():
    events = [{"event_type": "OUTPUT", "data": "\x1b[31mDisplay\x1b[0m Version\r\n"}]
    colored, truncated = render_colored_preview(events)
    assert not truncated
    assert colored == "\x1b[31;49mDisplay\x1b[39;49m Version\x1b[0m\n"
    plain = io.StringIO()
    render_events(events, plain)
    assert plain.getvalue() == "Display Version\n"
    assert render_colored_preview(events, limit=8)[1]


def transcript(*events):
    output = io.StringIO()
    summary = render_events(
        ({"event_type": kind, "data": data} for kind, data in events), output
    )
    return output.getvalue(), summary


def test_character_echo_commands_paging_and_sensitive_output_are_preserved():
    events = [("OUTPUT", "<AC1>")]
    for char in "display current-configuration":
        events.extend([("INPUT", char), ("OUTPUT", char)])
    events.extend(
        [
            ("INPUT", "\r"),
            (
                "OUTPUT",
                "\r\n#\r\npassword hash $abc\r\nsnmp-agent community public\r\n---- Mo",
            ),
            ("OUTPUT", "re ----"),
            ("INPUT", " "),
            (
                "OUTPUT",
                "\r               \rinterface Vlan-interface1\r\n 中文配置\r\n<AC1>",
            ),
        ]
    )
    text, info = transcript(*events)
    assert text.count("display current-configuration") == 1
    assert "More" not in text
    assert "interface Vlan-interface1" in text and "中文配置" in text
    assert "password hash $abc" in text and "snmp-agent community public" in text
    assert info["pagers_removed"] >= 1


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("dispaly\b\b\b\bplay", "display"),
        ("bad\x15display", "display"),
        ("display wrong\x17version", "display version"),
        ("displa\x1b[Dy", "displya"),
    ],
)
def test_input_editor_handles_edits(typed, expected):
    assert InputEditor().feed(typed + "\r") == [(expected, True)]


def test_echo_off_repeated_and_multiline_commands_not_deduplicated():
    text, _ = transcript(
        ("OUTPUT", "<AC>"),
        ("INPUT", "display version\r\ndisplay version\r"),
        ("OUTPUT", "version one\r\n<AC>\r\nversion two\r\n<AC>"),
    )
    assert text.count("display version") == 2
    assert "version one" in text and "version two" in text


def test_history_and_tab_use_authoritative_echo_or_explicit_uncertainty():
    text, _ = transcript(
        ("OUTPUT", "<AC>"),
        ("INPUT", "dis\t\r"),
        ("OUTPUT", "display current-configuration\r\n#\r\n<AC>"),
    )
    assert text.count("display current-configuration") == 1
    text, info = transcript(
        ("OUTPUT", "<AC>"), ("INPUT", "\x1b[A\r"), ("OUTPUT", "actual result\r\n<AC>")
    )
    assert "无法可靠还原" in text and "actual result" in text
    assert info["uncertain_commands"] == 1


def test_recording_zip_names_crc_content_and_exact_deletion(tmp_path, monkeypatch):
    manager, device, transport = _manager_fixture(tmp_path, monkeypatch)
    item, _ = manager.create_session(str(device.device_uuid))
    session_id = item["session_id"]
    try:
        _wait_until(lambda: manager.get_runtime(session_id).snapshot.state == "RUNNING")
        with pytest.raises(ValueError, match="活动"):
            manager.delete_recording(session_id)
        manager.input(session_id, "display version\r")
        _wait_until(lambda: bool(transport.writes))
    finally:
        manager.close()
    detail = manager.session_detail(session_id)
    log, _ = manager.export_path(session_id, "log")
    archive, _ = manager.export_path(session_id, "zip")
    assert log.stem == archive.stem
    assert log.name.startswith("LAB-SW_192.0.2.10_22_")
    assert detail["recording_status"] == "COMPLETED"
    with ZipFile(archive) as zipped:
        assert zipped.namelist() == [log.name] and zipped.testzip() is None
        assert zipped.read(log.name) == log.read_bytes()
    unrelated = manager.recording_root / "unrelated.log"
    unrelated.write_text("keep", encoding="utf-8")
    assert manager.delete_recording(session_id)["deleted"]
    assert manager.delete_recording(session_id)["deleted"]
    assert not log.exists() and not archive.exists() and unrelated.exists()


def test_history_delete_failure_is_recoverable_and_retryable(tmp_path, monkeypatch):
    manager, device, _ = _manager_fixture(tmp_path, monkeypatch)
    item, _ = manager.create_session(str(device.device_uuid))
    manager.close()
    original = __import__("shutil").rmtree

    def fail(path):
        raise PermissionError("locked")

    monkeypatch.setattr("netconsole.services.terminal_workspace.shutil.rmtree", fail)
    with pytest.raises(ValueError, match="可重试"):
        manager.delete_recording(item["session_id"])
    assert manager.history()[0]["deletion_pending"] is True
    assert (manager.recording_root / f".deleting-{item['session_id']}").exists()
    monkeypatch.setattr(
        "netconsole.services.terminal_workspace.shutil.rmtree", original
    )
    assert manager.delete_recording(item["session_id"])["deleted"]


def test_compression_failure_preserves_log_and_raw_events(tmp_path, monkeypatch):
    manager, device, _ = _manager_fixture(tmp_path, monkeypatch)
    item, _ = manager.create_session(str(device.device_uuid))
    _wait_until(
        lambda: manager.get_runtime(item["session_id"]).snapshot.state == "RUNNING"
    )

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("netconsole.services.terminal_workspace.ZipFile", fail)
    manager.close()
    metadata = manager.session_detail(item["session_id"])
    assert metadata["recording_status"] == "FAILED"
    assert manager.export_path(item["session_id"], "log")[0].exists()
    assert manager.export_path(item["session_id"], "jsonl")[0].exists()
    with pytest.raises(ValueError):
        manager.export_path(item["session_id"], "zip")


@pytest.mark.parametrize(
    ("filename", "sha", "minimum"),
    [
        (
            "terminal-31fb5afbb2754b01bf09e22819c39984.txt",
            "f3a01abfa66d600922452723d59cfb25749c0fe320be7739d0ce73c4eda686ad",
            10,
        ),
        (
            "AC_192.168.56.2_22_20261123011912.zip",
            "fde186a59a74972cf971ef5e164a3f220a161f36d41cf0cdfcba0da419b56ed0",
            12,
        ),
    ],
)
def test_original_user_samples_are_read_only_and_real_configuration_survives(
    filename, sha, minimum
):
    path = Path("D:/下载") / filename
    if not path.exists():
        pytest.skip("原始用户样本不在当前主机")
    data = path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == sha
    if path.suffix == ".zip":
        with ZipFile(io.BytesIO(data)) as zipped:
            raw = zipped.read(zipped.namelist()[0]).decode("utf-8-sig")
        text, info = transcript(("OUTPUT", raw))
        # Legacy output-only samples cannot prove which intermediate edits ran.
    else:
        raw = data.decode("utf-8-sig")
        import re

        events, start = [], 0
        for match in re.finditer(r"\n> ([^\n]*)\n", raw):
            events.append(("OUTPUT", raw[start : match.start()]))
            events.append(("INPUT", match[1]))
            start = match.end()
        events.append(("OUTPUT", raw[start:]))
        text, info = transcript(*events)
    assert "---- More ----" not in text
    assert "version 7.1.064, Alpha 7165" in text
    assert "ip address 192.168.56.2 255.255.255.0" in text
    assert "interface GigabitEthernet1/0/0" in text
    assert raw.count("More") >= minimum
    assert hashlib.sha256(path.read_bytes()).hexdigest() == sha
