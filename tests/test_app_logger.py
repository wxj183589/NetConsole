from __future__ import annotations

import errno
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

from netconsole.core import app_logger
from netconsole.core.paths import PathResolver


def configure(tmp_path):
    paths = PathResolver(tmp_path)
    app_logger.configure_path_resolver(paths)
    return paths


def test_app_logger_writes_and_reads_levels_keyword_and_export(tmp_path):
    paths = configure(tmp_path)

    app_logger.log_info("APP_START", "软件启动")
    app_logger.log_warning("WARN_EVENT", "check me")
    app_logger.log_error("ERROR_EVENT", "boom")

    assert paths.app_log_path.exists()
    assert [item["event"] for item in app_logger.read_logs()] == ["ERROR_EVENT", "WARN_EVENT", "APP_START"]
    assert [item["event"] for item in app_logger.read_logs(keyword="check")] == ["WARN_EVENT"]
    assert [item["event"] for item in app_logger.read_logs(level="ERROR")] == ["ERROR_EVENT"]

    target = tmp_path / "exported.txt"
    app_logger.export_logs(target)
    assert target.read_text(encoding="utf-8") == paths.app_log_path.read_text(encoding="utf-8")


def test_app_logger_clear_logs(tmp_path):
    paths = configure(tmp_path)
    app_logger.log_info("APP_START", "software started")

    app_logger.clear_logs()

    assert paths.app_log_path.read_text(encoding="utf-8") == ""
    assert app_logger.read_logs() == []


def test_app_logger_rotates_and_reads_across_runtime_log_files(tmp_path, monkeypatch):
    paths = configure(tmp_path)
    monkeypatch.setattr(app_logger, "APP_LOG_MAX_BYTES", 120)

    for index in range(8):
        app_logger.log_info(f"EVENT_{index}", "x" * 30)

    files = app_logger.log_files(paths.app_log_path)
    page = app_logger.get_logs(page=1, page_size=200)
    target = tmp_path / "all-runtime-logs.txt"
    app_logger.export_logs(target)

    assert len(files) > 1
    assert page.state.total_items == 8
    assert page.rows[0]["event"] == "EVENT_7"
    assert "EVENT_0" in target.read_text(encoding="utf-8")

    app_logger.clear_logs()
    assert app_logger.read_logs() == []
    assert not list(paths.logs_dir.glob("app-*.log"))


def test_app_logger_sanitizes_sensitive_detail(tmp_path):
    paths = configure(tmp_path)

    app_logger.log_info(
        "DEVICE_CREATED",
        "password=secret ssh_password=ssh123 telnet_password=tel123 snmpv3_auth_password=A1B2 snmpv3_priv_password=P9Q8 密码=中文密码",
    )

    content = paths.app_log_path.read_text(encoding="utf-8")
    assert "secret" not in content
    assert "ssh123" not in content
    assert "tel123" not in content
    assert "A1B2" not in content
    assert "P9Q8" not in content
    assert "中文密码" not in content
    assert "***" in content


def test_export_logs_creates_empty_file_when_log_missing(tmp_path):
    configure(tmp_path)
    target = Path(tmp_path) / "empty.txt"

    app_logger.export_logs(target)

    assert target.exists()
    assert target.read_text(encoding="utf-8") == ""


def test_get_logs_paginates_large_log_without_returning_all_rows(tmp_path):
    paths = configure(tmp_path)
    paths.app_log_path.parent.mkdir(parents=True, exist_ok=True)
    with paths.app_log_path.open("w", encoding="utf-8") as file:
        for index in range(100_000):
            level = "ERROR" if index % 1000 == 0 else "INFO"
            file.write(f"2026-06-18 10:00:00 | {level} | EVENT_{index:06d} | detail {index}\n")

    first_page = app_logger.get_logs(page=1, page_size=200)
    second_page = app_logger.get_logs(page=2, page_size=200)
    error_page = app_logger.get_logs(page=1, page_size=500, level="ERROR")

    assert len(first_page.rows) == 200
    assert first_page.state.total_items == 100_000
    assert first_page.state.total_pages == 500
    assert first_page.rows[0]["event"] == "EVENT_099999"
    assert second_page.rows[0]["event"] == "EVENT_099799"
    assert len(error_page.rows) == 100
    assert all(row["level"] == "ERROR" for row in error_page.rows)


def test_get_logs_supports_keyword_with_pagination(tmp_path):
    paths = configure(tmp_path)
    paths.app_log_path.parent.mkdir(parents=True, exist_ok=True)
    paths.app_log_path.write_text(
        "\n".join(
            [
                "2026-06-18 10:00:00 | INFO | APP_START | ready",
                "2026-06-18 10:00:01 | WARNING | DEVICE_WARN | check target",
                "2026-06-18 10:00:02 | ERROR | DEVICE_ERROR | target failed",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    page = app_logger.get_logs(page=1, page_size=200, keyword="target")

    assert [row["event"] for row in page.rows] == ["DEVICE_ERROR", "DEVICE_WARN"]
    assert page.state.total_items == 2


def test_app_logger_handles_concurrent_writes_without_line_corruption(tmp_path):
    paths = configure(tmp_path)
    total_threads = 100
    writes_per_thread = 50

    def write_logs(thread_index: int) -> None:
        for item_index in range(writes_per_thread):
            app_logger.log_info(f"THREAD_{thread_index}_{item_index}", "并发日志")

    with ThreadPoolExecutor(max_workers=total_threads) as executor:
        list(executor.map(write_logs, range(total_threads)))

    lines = paths.app_log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == total_threads * writes_per_thread
    assert all(len(line.split(" | ", 3)) == 4 for line in lines)
    assert all("并发日志" in line for line in lines)


def test_app_logger_write_failure_does_not_escape_to_caller(tmp_path, monkeypatch, capsys):
    paths = configure(tmp_path)

    @contextmanager
    def failing_lock(_path):
        raise OSError(errno.EDEADLK, "Resource deadlock avoided")
        yield

    monkeypatch.setattr(app_logger, "interprocess_file_lock", failing_lock)

    app_logger.log_info("LOCK_FAILED", "password=secret")

    captured = capsys.readouterr()
    assert "log_write_failed" in captured.err
    assert "Resource deadlock avoided" in captured.err
    assert "secret" not in captured.err
    assert not paths.app_log_path.exists()
