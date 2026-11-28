from netconsole.services.log_display import display_log_event, display_log_row, matches_log_filters


def test_known_runtime_events_have_chinese_names() -> None:
    assert display_log_event("UI_STARTUP") == "应用界面启动"
    assert display_log_event("TEST_CONNECTION_STARTED") == "开始测试设备连接"
    assert display_log_event("TEST_CONNECTION_ATTEMPT_FAILED") == "设备连接尝试失败"
    assert display_log_event("API_REQUEST_COMPLETED") == "接口请求完成"
    assert display_log_event("DESKTOP_ACTION_COMPLETED") == "桌面动作完成"


def test_unclassified_event_keeps_raw_code_separate() -> None:
    row = display_log_row(
        {
            "time": "2026-07-21 10:00:00",
            "level": "INFO",
            "event": "FUTURE_EVENT_CODE",
            "detail": "raw detail",
        }
    )

    assert row["category"] == "other"
    assert row["display_event"] == "FUTURE_EVENT_CODE"
    assert row["raw_event"] == "FUTURE_EVENT_CODE"


def test_common_request_details_are_localized() -> None:
    row = display_log_row(
        {
            "time": "2026-07-21 10:00:00",
            "level": "INFO",
            "event": "API_REQUEST_COMPLETED",
            "detail": "request_id=abc path=/api/rail-transit site_id=demo",
        }
    )

    assert row["display_event"] == "接口请求完成"
    assert "请求ID=abc" in row["display_detail"]
    assert "接口路径=/api/rail-transit" in row["display_detail"]
    assert "局点=demo" in row["display_detail"]
    assert row["request_id"] == "abc"
    assert row["category"] == "api_request"


def test_important_filter_keeps_errors_and_filters_context_and_time() -> None:
    row = {"time": "2026-07-21 10:00:00", "level": "INFO", "event": "API_REQUEST_COMPLETED",
           "detail": "request_id=abc site_id=demo"}
    assert not matches_log_filters(row, {"important": True})
    assert matches_log_filters({**row, "level": "ERROR"}, {"important": True})
    assert matches_log_filters(row, {"request_id": "abc", "site_id": "demo", "start_time": "2026-07-21T09:00:00"})
    assert not matches_log_filters(row, {"end_time": "2026-07-21T09:00:00"})
