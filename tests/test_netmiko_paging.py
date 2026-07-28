from __future__ import annotations

import pytest

from netconsole.services.netmiko_connection import (
    CommandCancelled,
    CommandOutputLimitExceeded,
    safe_send_command_with_paging,
)


class _PagedConnection:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = list(outputs)
        self.commands: list[str] = []
        self.interrupts: list[str] = []
        self.kwargs: list[dict[str, object]] = []

    def send_command_timing(self, command: str, **kwargs) -> str:
        self.commands.append(command)
        self.kwargs.append(kwargs)
        return self.outputs.pop(0) if self.outputs else ""

    def write_channel(self, value: str) -> None:
        self.interrupts.append(value)


def test_paged_command_sends_space_and_preserves_raw_output() -> None:
    connection = _PagedConnection(
        [
            "header\r\nrow-1\r\n--More--\x08\x08        ",
            "\r\nrow-2\r\n---- More ----",
            "\r\nrow-3\r\nZXR10#",
        ]
    )

    result = safe_send_command_with_paging(connection, "show opticalinfo brief")

    assert connection.commands == ["show opticalinfo brief", " ", " "]
    assert all(item["read_timeout"] == 120 for item in connection.kwargs)
    assert all(item["last_read"] == 10 for item in connection.kwargs)
    assert result.page_count == 3
    assert "--More--" in result.raw_output
    assert "More" not in result.output
    assert "row-1" in result.output
    assert "row-2" in result.output
    assert "row-3" in result.output


def test_paged_command_stops_at_page_limit_and_interrupts() -> None:
    connection = _PagedConnection(["page-1 --More--", "page-2 --More--"])

    with pytest.raises(CommandOutputLimitExceeded) as exc_info:
        safe_send_command_with_paging(
            connection,
            "show interface brief",
            max_pages=2,
        )

    assert exc_info.value.code == "OUTPUT_LIMIT_EXCEEDED"
    assert connection.interrupts == ["\x03"]


def test_paged_command_stops_at_byte_limit_and_interrupts() -> None:
    connection = _PagedConnection(["x" * 20])

    with pytest.raises(CommandOutputLimitExceeded):
        safe_send_command_with_paging(
            connection,
            "show interface brief",
            max_output_bytes=10,
        )

    assert connection.interrupts == ["\x03"]


def test_paged_command_honors_cancellation_and_interrupts() -> None:
    connection = _PagedConnection(["page-1 --More--"])

    with pytest.raises(CommandCancelled):
        safe_send_command_with_paging(
            connection,
            "show interface brief",
            cancel_check=lambda: True,
        )

    assert connection.interrupts == ["\x03"]
