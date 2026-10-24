from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from netconsole import entrypoint
from netconsole.core import data_root_configuration, paths as paths_module, runtime_environment
from netconsole.services import site_storage


def _allow_isolated_install_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    application = tmp_path / "application"
    application.mkdir()
    def validate(value, mode=None):
        return Path(value).resolve()

    monkeypatch.setattr(runtime_environment, "validate_data_root", validate)
    monkeypatch.setattr(paths_module, "validate_data_root", validate)
    monkeypatch.setattr(runtime_environment, "app_root", lambda: application)
    monkeypatch.setattr(data_root_configuration, "_require_windows_fixed_drive", lambda _root: None)
    usage = type("Usage", (), {"free": 120 * 1024**3})()
    monkeypatch.setattr(data_root_configuration.shutil, "disk_usage", lambda _path: usage)


def _read_diagnostic(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _diagnostic_path(tmp_path: Path) -> Path:
    return Path(tempfile.gettempdir()) / f"netconsole-installer-{tmp_path.name}.jsonl"


def test_backend_diagnostic_records_success_and_install_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _allow_isolated_install_root(monkeypatch, tmp_path)
    root = tmp_path / "candidate"
    log = _diagnostic_path(tmp_path)

    assert (
        entrypoint._validate_data_root_from_installer(
            [
                str(root),
                "--mode",
                "clean-install",
                "--diagnostic-log-path",
                str(log),
                "--diagnostic-id",
                "test-success",
            ]
        )
        == 0
    )

    records = _read_diagnostic(log)
    assert records[-1]["result"] == "SUCCESS"
    assert records[-1]["installation_mode"] == "clean-install"
    assert records[-1]["diagnostic_id"] == "test-success"
    assert records[-1]["frozen_runtime"] is False
    log.unlink(missing_ok=True)


def test_backend_diagnostic_records_cli_argument_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _allow_isolated_install_root(monkeypatch, tmp_path)
    log = _diagnostic_path(tmp_path)
    assert (
        entrypoint._validate_data_root_from_installer(
            [
                str(tmp_path / "candidate"),
                "--mode",
                "not-a-mode",
                "--diagnostic-log-path",
                str(log),
                "--diagnostic-id",
                "test-cli-error",
            ]
        )
        == 1
    )
    failure = _read_diagnostic(log)[-1]
    assert failure["error_code"] == "CLI_ARGUMENT_INVALID"
    assert failure["failure_function"] == "argparse"
    assert failure["result"] == "FAILED_WITH_DIAGNOSTICS"
    log.unlink(missing_ok=True)


def test_backend_diagnostic_identifies_clean_install_business_data_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _allow_isolated_install_root(monkeypatch, tmp_path)
    root = tmp_path / "existing"
    (root / "config").mkdir(parents=True)
    (root / "config" / "storage-manifest.json").write_text("{}\n", encoding="utf-8")
    log = _diagnostic_path(tmp_path)

    assert (
        entrypoint._validate_data_root_from_installer(
            [
                str(root),
                "--mode",
                "clean-install",
                "--diagnostic-log-path",
                str(log),
                "--diagnostic-id",
                "test-conflict",
            ]
        )
        == 1
    )

    failure = _read_diagnostic(log)[-1]
    assert failure["result"] == "FAILED_WITH_DIAGNOSTICS"
    assert failure["stage"] == "clean-install-business-data-check"
    assert failure["exception_type"].endswith("DataRootConfigurationError")
    assert failure["error_code"] == ""
    assert "清洁安装目标包含" in str(failure["sanitized_message"])
    assert (root / "config" / "storage-manifest.json").read_text(encoding="utf-8") == "{}\n"
    log.unlink(missing_ok=True)


def test_backend_diagnostic_validates_reuse_mode_without_reinitializing_site(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _allow_isolated_install_root(monkeypatch, tmp_path)
    root = tmp_path / "reuse"
    assert (
        entrypoint._validate_data_root_from_installer(
            [str(root), "--mode", "clean-install"]
        )
        == 0
    )
    registry_before = (root / "config" / "site_registry.json").read_bytes()
    log = _diagnostic_path(tmp_path)

    assert (
        entrypoint._validate_data_root_from_installer(
            [
                str(root),
                "--mode",
                "reuse",
                "--diagnostic-log-path",
                str(log),
                "--diagnostic-id",
                "test-reuse",
            ]
        )
        == 0
    )
    records = _read_diagnostic(log)
    assert records[-1]["result"] == "SUCCESS"
    assert records[-1]["installation_mode"] == "reuse"
    assert (root / "config" / "site_registry.json").read_bytes() == registry_before
    log.unlink(missing_ok=True)


def test_failed_first_run_rolls_back_metadata_and_allows_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _allow_isolated_install_root(monkeypatch, tmp_path)
    root = tmp_path / "retry"
    log = _diagnostic_path(tmp_path)
    original = site_storage.SiteManager.init_site_database

    def fail_once(manager, site_name: str, with_demo_data: bool = False):
        original(manager, site_name, with_demo_data=with_demo_data)
        raise OSError("injected first-run SQLite failure")

    monkeypatch.setattr(site_storage.SiteManager, "init_site_database", fail_once)
    assert (
        entrypoint._validate_data_root_from_installer(
            [
                str(root),
                "--mode",
                "clean-install",
                "--diagnostic-log-path",
                str(log),
                "--diagnostic-id",
                "test-retry",
            ]
        )
        == 1
    )
    assert not (root / "config" / "storage-manifest.json").exists()
    assert not (root / "runtime_mode.json").exists()
    assert not (root / "sites" / "demo").exists()
    failure = _read_diagnostic(log)[-1]
    assert failure["failure_function"] == "SiteApplicationService.initialize_first_run_site"

    monkeypatch.setattr(site_storage.SiteManager, "init_site_database", original)
    retry_log = _diagnostic_path(tmp_path)
    retry_log.unlink(missing_ok=True)
    retry_result = entrypoint._validate_data_root_from_installer(
        [
            str(root),
            "--mode",
            "clean-install",
            "--diagnostic-log-path",
            str(retry_log),
            "--diagnostic-id",
            "test-retry-success",
        ]
    )
    retry_records = _read_diagnostic(retry_log)
    assert retry_result == 0, retry_records
    assert (root / "config" / "storage-manifest.json").is_file()
    assert (root / "runtime_mode.json").is_file()
    log.unlink(missing_ok=True)
