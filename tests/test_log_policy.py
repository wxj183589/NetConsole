from __future__ import annotations

from netconsole.core import app_logger
from netconsole.core.log_policy import LOG_POLICY


def test_log_policy_limits_have_distinct_controlled_semantics() -> None:
    application = LOG_POLICY.application_log

    assert application.max_event_bytes == 16 * 1024
    assert application.max_context_bytes == 32 * 1024
    assert application.max_traceback_bytes == 256 * 1024
    assert application.max_event_bytes < application.max_context_bytes
    assert application.max_context_bytes < application.max_traceback_bytes
    assert LOG_POLICY.raw_collection_truncate is False


def test_context_and_diagnostic_traceback_helpers_enforce_their_own_caps() -> None:
    context = app_logger.truncate_application_context("x" * (64 * 1024))
    try:
        raise RuntimeError("x" * (512 * 1024))
    except RuntimeError as exc:
        diagnostic = app_logger.format_diagnostic_traceback(exc)

    assert len(context.encode("utf-8")) <= LOG_POLICY.application_log.max_context_bytes
    assert len(diagnostic.encode("utf-8")) <= LOG_POLICY.application_log.max_traceback_bytes
    assert "payload_truncated=true" in context
    assert "payload_truncated=true" in diagnostic
