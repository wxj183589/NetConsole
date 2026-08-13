from __future__ import annotations

import copy
import io
import json
import sys
from pathlib import Path

import pytest

from scripts.quality.check_change_impact import (
    DEFAULT_CONFIG,
    _load_config,
    _write_github_output,
    classify,
    main,
)


def _write_config(path: Path, config: dict[str, object]) -> Path:
    path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    return path


def test_registry_loads_and_references_current_evidence() -> None:
    config = _load_config(DEFAULT_CONFIG)

    assert config["schema_version"] == 2
    assert "renderer-api-client" in {area["id"] for area in config["risk_areas"]}
    assert "main-contract-smoke" in config["consumer_suites"]


@pytest.mark.parametrize(
    ("paths", "expected_level"),
    [
        (("docs/README.md",), "L1"),
        (("src/netconsole/services/device_operation_service.py",), "L2"),
        (("apps/desktop_renderer/src/components/table/NcDataTable.vue",), "L3"),
        (("src/netconsole/core/feature_registry.py",), "L4"),
    ],
)
def test_classify_uses_highest_registered_risk(paths: tuple[str, ...], expected_level: str) -> None:
    impact = classify(paths, _load_config(DEFAULT_CONFIG))

    assert impact.level == expected_level


def test_shared_change_reports_stable_consumers_and_post_merge_gate() -> None:
    impact = classify(
        ("apps/desktop_renderer/src/api/client.ts",),
        _load_config(DEFAULT_CONFIG),
    )

    assert impact.areas == ("renderer-api-client",)
    assert "devices" in impact.consumers
    assert "ground_unattended" in impact.consumers
    assert impact.requires_post_merge is True
    assert impact.suites == ("electron-contract", "renderer-full")


def test_multiple_paths_take_l4_and_union_consumers() -> None:
    impact = classify(
        (
            "apps/desktop_renderer/src/api/client.ts",
            "src/netconsole/core/feature_registry.py",
        ),
        _load_config(DEFAULT_CONFIG),
    )

    assert impact.level == "L4"
    assert impact.areas == ("feature-registry", "renderer-api-client")
    assert "main-contract-smoke" in impact.suites
    assert "release_engineering" in impact.consumers


def test_registry_rejects_unknown_consumer_id(tmp_path: Path) -> None:
    config = copy.deepcopy(_load_config(DEFAULT_CONFIG))
    config["risk_areas"][0]["consumers"].append("unknown-domain")

    with pytest.raises(ValueError, match="unknown consumers"):
        _load_config(_write_config(tmp_path / "unknown-consumer.json", config))


def test_registry_rejects_missing_suite_evidence(tmp_path: Path) -> None:
    config = copy.deepcopy(_load_config(DEFAULT_CONFIG))
    config["consumer_suites"]["renderer-full"]["required_evidence"].append("tests/does-not-exist.py")

    with pytest.raises(ValueError, match="missing evidence"):
        _load_config(_write_config(tmp_path / "missing-evidence.json", config))


def test_registry_rejects_stale_shared_pattern(tmp_path: Path) -> None:
    config = copy.deepcopy(_load_config(DEFAULT_CONFIG))
    config["risk_areas"][0]["patterns"] = ["src/netconsole/does-not-exist/**"]

    with pytest.raises(ValueError, match="pattern matches no current path"):
        _load_config(_write_config(tmp_path / "stale-pattern.json", config))


def test_github_output_is_stable_and_machine_readable(tmp_path: Path) -> None:
    impact = classify(
        ("src/netconsole/core/paths.py",),
        _load_config(DEFAULT_CONFIG),
    )
    output = tmp_path / "github-output.txt"

    _write_github_output(output, impact)

    entries = dict(
        line.split("=", maxsplit=1)
        for line in output.read_text(encoding="utf-8").splitlines()
    )
    assert entries["risk_level"] == "L4"
    assert entries["risk_areas"] == "data-root-and-migration"
    assert entries["requires_post_merge"] == "true"
    assert "main-contract-smoke" in entries["consumer_suites"]


def test_main_reconfigures_legacy_stdio_and_preserves_utf8_github_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stdout_bytes = io.BytesIO()
    stderr_bytes = io.BytesIO()
    stdout = io.TextIOWrapper(stdout_bytes, encoding="cp1252")
    stderr = io.TextIOWrapper(stderr_bytes, encoding="cp1252")
    github_output = tmp_path / "github-output.txt"
    github_summary = tmp_path / "github-summary.md"
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_change_impact",
            "--paths",
            "README.md",
            "--github-output",
            str(github_output),
            "--github-summary",
            str(github_summary),
        ],
    )

    assert main() == 0
    stdout.flush()

    console_summary = stdout_bytes.getvalue().decode("utf-8")
    assert "风险等级：`L1`" in console_summary
    assert "Change Impact Audit" in console_summary
    assert github_output.read_text(encoding="utf-8").startswith("risk_level=L1\n")
    assert "风险等级：`L1`" in github_summary.read_text(encoding="utf-8")


def test_main_keeps_stringio_stdout_compatible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "argv", ["check_change_impact", "--paths", "README.md"])

    assert main() == 0
    assert "风险等级：`L1`" in stdout.getvalue()
