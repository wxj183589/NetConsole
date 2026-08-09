from __future__ import annotations

import logging

from netconsole.services.ground_unattended import supervisor as supervisor_module
from netconsole.services.ground_unattended.supervisor import GroundUnattendedSupervisor


def test_repeated_tick_error_emits_first_summary_and_recovery(monkeypatch, caplog) -> None:
    supervisor = object.__new__(GroundUnattendedSupervisor)
    supervisor.site_id = "test-site"
    supervisor._tick_error_fingerprint = ""
    supervisor._tick_error_last_at = 0.0
    supervisor._tick_error_summary_at = 0.0
    supervisor._tick_error_count = 0
    clock = iter(float(value) for value in range(101))
    monkeypatch.setattr(supervisor_module.time, "monotonic", lambda: next(clock))
    caplog.set_level(logging.INFO, logger=supervisor_module.LOGGER.name)

    emitted: list[bool] = []
    for _index in range(100):
        try:
            raise ValueError("profile contains future fields")
        except ValueError as exc:
            emitted.append(supervisor._record_tick_failure(exc))
    supervisor._record_tick_recovery()

    messages = [record.getMessage() for record in caplog.records]
    assert sum(emitted) == 2
    assert sum("调度周期失败：" in message for message in messages) == 1
    assert sum("调度周期失败重复" in message for message in messages) == 1
    assert any("repeated=60" in message for message in messages)
    assert sum("调度周期已恢复" in message for message in messages) == 1


def test_same_tick_error_logs_again_after_suppression_window(monkeypatch, caplog) -> None:
    supervisor = object.__new__(GroundUnattendedSupervisor)
    supervisor.site_id = "test-site"
    supervisor._tick_error_fingerprint = ""
    supervisor._tick_error_last_at = 0.0
    supervisor._tick_error_summary_at = 0.0
    supervisor._tick_error_count = 0
    clock = iter([100.0, 111.0])
    monkeypatch.setattr(supervisor_module.time, "monotonic", lambda: next(clock))
    caplog.set_level(logging.ERROR, logger=supervisor_module.LOGGER.name)

    assert supervisor._record_tick_failure(RuntimeError("offline")) is True
    assert supervisor._record_tick_failure(RuntimeError("offline")) is True

    messages = [record.getMessage() for record in caplog.records]
    assert sum("调度周期失败：" in message for message in messages) == 2
