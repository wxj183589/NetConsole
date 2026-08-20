from __future__ import annotations

import json
import platform
import re
from pathlib import Path

import pytest

from scripts.build.python_runtime_contract import (
    assert_current_python_runtime,
    load_python_runtime_version,
)


ROOT = Path(__file__).resolve().parents[1]
EXACT_VERSION = re.compile(r"^\d+\.\d+\.\d+$")


def test_release_consumers_use_the_authoritative_runtime_contract() -> None:
    version = load_python_runtime_version(ROOT)
    assert version == "3.13.9"
    assert EXACT_VERSION.fullmatch(version)

    approval = json.loads(
        (ROOT / "config" / "pyinstaller-approved-distributions.json").read_text(
            encoding="utf-8"
        )
    )
    assert approval["python_version"] == version

    for workflow in (
        ROOT / ".github" / "workflows" / "quality-gate.yml",
        ROOT / ".github" / "workflows" / "python-full-regression.yml",
    ):
        text = workflow.read_text(encoding="utf-8")
        assert "python-version: \"3.13\"" not in text
        assert text.count(f'python-version: "{version}"') >= 1

    for notice_path in (
        ROOT / "src" / "netconsole" / "assets" / "open_source_notices.json",
        ROOT / "docs" / "open_source_notices.json",
    ):
        notices = json.loads(notice_path.read_text(encoding="utf-8"))
        python_notice = next(
            item for item in notices if item["name"] == "Python"
        )
        assert python_notice["version"] == version
        assert python_notice["purl"] == f"pkg:generic/python@{version}"

    package_smoke = (
        ROOT / "apps" / "desktop_electron" / "scripts" / "package-smoke.mjs"
    ).read_text(encoding="utf-8")
    assert "approval.python_version !== '3.13'" not in package_smoke
    assert "python_version" in package_smoke

    package_script = (ROOT / "scripts" / "build" / "package_windows.ps1").read_text(
        encoding="utf-8-sig"
    )
    assert "scripts.build.python_runtime_contract" in package_script
    assert "--check-current" in package_script

    package_metadata = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert f'requires-python = "=={version}"' in package_metadata

    for path in (
        ROOT / "README.md",
        ROOT / "README_EN.md",
        ROOT / "constraints.txt",
        ROOT / "docs" / "release" / "BUILD_AND_RELEASE.md",
        ROOT / "docs" / "release" / "THIRD_PARTY_DEPENDENCIES.md",
        ROOT / "docs" / "development" / "repository-layout.md",
        ROOT / "docs" / "development" / "SELF_HOSTED_CI.md",
    ):
        text = path.read_text(encoding="utf-8")
        assert "CPython 3.13 /" not in text
        assert "CPython 3.13。" not in text
        assert "CPython 3.13、" not in text


def test_current_runtime_contract_checks_implementation_and_architecture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "python_version", lambda: "3.13.9")
    monkeypatch.setattr(platform, "python_implementation", lambda: "CPython")
    monkeypatch.setattr(platform, "architecture", lambda: ("64bit", "WindowsPE"))

    assert assert_current_python_runtime(ROOT) == "3.13.9"


def test_current_runtime_contract_rejects_wrong_patch_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform, "python_version", lambda: "3.13.15")
    monkeypatch.setattr(platform, "python_implementation", lambda: "CPython")
    monkeypatch.setattr(platform, "architecture", lambda: ("64bit", "WindowsPE"))

    with pytest.raises(RuntimeError, match="expected=3.13.9, actual=3.13.15"):
        assert_current_python_runtime(ROOT)
