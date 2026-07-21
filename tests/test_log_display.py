from netconsole.services.log_display import display_log_event, display_log_row


def test_known_runtime_events_have_chinese_names() -> None:
    assert display_log_event("UI_STARTUP") == "应用界面启动"
    assert display_log_event("TEST_CONNECTION_STARTED") == "开始测试设备连接"
    assert display_log_event("TEST_CONNECTION_ATTEMPT_FAILED") == "设备连接尝试失败"


def test_unclassified_event_keeps_raw_code_separate() -> None:
    row = display_log_row(
        {
            "time": "2026-07-21 10:00:00",
            "level": "INFO",
            "event": "FUTURE_EVENT_CODE",
            "detail": "raw detail",
        }
    )

    assert row["display_event"] == "未分类事件"
    assert row["raw_event"] == "FUTURE_EVENT_CODE"
