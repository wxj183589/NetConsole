from __future__ import annotations

from pathlib import Path
import tomllib

import pytest

from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.services.terminal_settings import (
    TerminalSettingsError,
    TerminalSettingsService,
)


def _service(tmp_path) -> TerminalSettingsService:
    return TerminalSettingsService(
        PathResolver(
            app_root=tmp_path / "app",
            data_root=tmp_path / "data",
            runtime_root=tmp_path / "runtime",
        )
    )


def test_terminal_rule_resources_preserve_attachment_counts_and_duplicates(tmp_path) -> None:
    service = _service(tmp_path)

    highlights = service.rule_document("highlight")
    dangerous = service.rule_document("dangerous")

    assert highlights["actual_rule_count"] == 22
    assert highlights["documented_rule_count"] == 23
    assert dangerous["actual_rule_count"] == 226
    assert highlights["source_file"] == "20261123_010953.xlsx"
    assert dangerous["source_file"] == "20261123_011457.xlsx"
    assert sum(1 for item in dangerous["rules"] if item["pattern"] == "reboot") == 3


def test_terminal_rule_resources_are_included_in_python_packages() -> None:
    root = Path(__file__).resolve().parents[1]
    with (root / "pyproject.toml").open("rb") as stream:
        package_data = tomllib.load(stream)["tool"]["setuptools"]["package-data"]["netconsole"]

    assert "resources/terminal_rules/*.json" in package_data


def test_terminal_settings_persist_and_validate_regex(tmp_path) -> None:
    service = _service(tmp_path)

    updated = service.update_settings({"font_family": "JetBrains Mono", "font_size": 17})
    assert updated["font_family"] == "JetBrains Mono"
    assert _service(tmp_path).settings()["font_size"] == 17

    rules = service.rule_document("highlight")["rules"]
    rules[0] = {**rules[0], "pattern": "["}
    with pytest.raises(TerminalSettingsError, match="正则无效"):
        service.replace_rules("highlight", rules)


def test_dangerous_command_scope_marks_but_does_not_decide_execution(tmp_path) -> None:
    service = _service(tmp_path)
    device = Device(device_vendor="H3C", device_type="SW")

    matches = service.match_dangerous_command("reboot", device)

    assert len(matches) == 2
    assert all(item["device_type"] == "交换机" for item in matches)
