from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import tomllib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from netconsole.backend.api.terminal_router import router
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


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16", "gb18030"])
def test_legacy_rule_array_loads_and_exports_without_mutating_source(tmp_path, encoding) -> None:
    service = _service(tmp_path)
    config = service.root / "highlight_rules.json"
    config.parent.mkdir(parents=True)
    source = json.dumps([{"pattern": "接口", "color": "#123456"}], ensure_ascii=False).encode(encoding)
    config.write_bytes(source)

    document = service.rule_document("highlight")

    assert document["rules"][0]["id"] == "highlight-001"
    assert document["rules"][0]["pattern"] == "接口"
    assert json.loads(service.export_rules("highlight")) == document
    assert config.read_bytes() == source


def test_invalid_rule_file_requires_explicit_repair_and_preserves_original(tmp_path) -> None:
    service = _service(tmp_path)
    config = service.root / "highlight_rules.json"
    config.parent.mkdir(parents=True)
    original = b'{"rules": [{"pattern": "ok", "source_row": "invalid"}]}'
    config.write_bytes(original)
    rules = [{"pattern": "new value", "color": "#123456"}]

    with pytest.raises(TerminalSettingsError, match=r"highlight_rules\.json rules\[1\]\.source_row"):
        service.replace_rules("highlight", rules)
    assert config.read_bytes() == original
    assert not list(service.root.glob("*.invalid-*.json"))

    assert service.replace_rules("highlight", rules, repair_invalid=True)["actual_rule_count"] == 1
    backup, = service.root.glob("highlight_rules.invalid-*.json")
    assert backup.read_bytes() == original
    assert service.rule_document("highlight")["rules"][0]["pattern"] == "new value"


def test_invalid_import_reports_file_and_field_without_writing(tmp_path) -> None:
    service = _service(tmp_path)

    with pytest.raises(TerminalSettingsError, match=r"rules-export\.json rules\[1\]\.color"):
        service.read_rule_file(
            "highlight", b'[{"pattern": "error", "color": "red"}]', filename="rules-export.json",
        )
    with pytest.raises(TerminalSettingsError, match="rules-export.json JSON 第 1 行"):
        service.read_rule_file("dangerous", b'{"rules": [}', filename="rules-export.json")
    assert not service.root.exists()


def test_rule_import_previews_and_export_returns_saved_document(tmp_path) -> None:
    service = _service(tmp_path)
    app = FastAPI()
    app.state.terminal_session_manager = SimpleNamespace(settings=service)
    app.include_router(router, prefix="/api")
    client = TestClient(app)

    preview = client.post(
        "/api/terminal/rules/import", data={"kind": "highlight"},
        files={"file": ("legacy.json", '[{"pattern": "接口"}]'.encode("utf-8-sig"))},
    )
    assert preview.status_code == 200, preview.text
    rules = preview.json()["rules"]
    assert rules[0]["pattern"] == "接口"
    assert not service.root.exists()

    saved = client.put("/api/terminal/rules/highlight", json={"rules": rules})
    assert saved.status_code == 200
    exported = client.get("/api/terminal/rules/highlight/export")
    assert exported.status_code == 200
    assert 'filename="terminal-highlight-rules.json"' in exported.headers["content-disposition"]
    assert exported.json() == saved.json()


def test_dangerous_command_scope_marks_but_does_not_decide_execution(tmp_path) -> None:
    service = _service(tmp_path)
    device = Device(device_vendor="H3C", device_type="SW")

    matches = service.match_dangerous_command("reboot", device)

    assert len(matches) == 2
    assert all(item["device_type"] == "交换机" for item in matches)


def test_invalid_advisory_rules_do_not_prevent_command_input(tmp_path) -> None:
    service = _service(tmp_path)
    config = service.root / "dangerous_command_rules.json"
    config.parent.mkdir(parents=True)
    original = b'{"rules": null}'
    config.write_bytes(original)

    assert service.match_dangerous_command("display version", Device()) == []
    with pytest.raises(TerminalSettingsError, match="dangerous_command_rules.json rules"):
        service.rule_document("dangerous")
    assert config.read_bytes() == original
