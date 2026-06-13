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
