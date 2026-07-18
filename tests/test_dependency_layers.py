from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from scripts.build.check_runtime_deps import (
    check_locked_environment,
    check_python_environment,
)
from scripts.architecture.checks import architecture_boundary_findings
from scripts.architecture.guard_core import apply_exceptions, load_exceptions


ROOT = Path(__file__).resolve().parents[1]
REQUIREMENT_NAME = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)")


@dataclass
class _Distribution:
    name: str
    version: str
    requires: tuple[str, ...] = ()

    @property
    def metadata(self) -> dict[str, str]:
        return {"Name": self.name}


def _names(relative: str) -> set[str]:
    result: set[str] = set()
    for raw_line in (ROOT / relative).read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        match = REQUIREMENT_NAME.match(line)
        if match:
            result.add(match.group(1).casefold().replace("_", "-"))
    return result


def _constraint_names() -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_line in (ROOT / "constraints.txt").read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or "==" not in line:
            continue
        name, version = line.split("==", 1)
        result[name.casefold().replace("_", "-")] = version
    return result


def test_runtime_layer_excludes_test_build_and_dev_tools() -> None:
    runtime = _names("requirements-runtime.txt")
    assert not runtime & {
        "pytest",
        "pyinstaller",
        "pip-licenses",
        "cyclonedx-bom",
        "ruff",
        "mypy",
    }
    assert {
        "fastapi",
        "pydantic",
        "uvicorn",
        "netmiko",
        "paramiko",
        "openpyxl",
        "xlsxwriter",
        "matplotlib",
        "numpy",
    } <= runtime


def test_test_build_and_dev_layers_have_explicit_ownership() -> None:
    assert "pytest" in _names("requirements-test.txt")
    assert {"pyinstaller", "pip-licenses", "cyclonedx-bom"} <= _names(
        "requirements-build.txt"
    )
    assert {"ruff", "mypy"} <= _names("requirements-dev.txt")
    assert (ROOT / "requirements.txt").read_text(encoding="utf-8").count(
        "requirements-build.txt"
    ) == 1


def test_direct_requirements_are_pinned_by_constraints() -> None:
    constraints = _constraint_names()
    for relative in (
        "requirements-runtime.txt",
        "requirements-test.txt",
        "requirements-build.txt",
        "requirements-dev.txt",
    ):
        for name in _names(relative):
            assert name in constraints, f"{relative} 的 {name} 未进入 constraints.txt"
            assert constraints[name]


def test_pyproject_declares_runtime_only() -> None:
    with (ROOT / "pyproject.toml").open("rb") as stream:
        project = tomllib.load(stream)["project"]
    names = {
        REQUIREMENT_NAME.match(str(item)).group(1).casefold().replace("_", "-")
        for item in project["dependencies"]
        if REQUIREMENT_NAME.match(str(item))
    }
    assert {
        "fastapi",
        "pydantic",
        "uvicorn",
        "netmiko",
        "paramiko",
        "openpyxl",
        "xlsxwriter",
        "matplotlib",
        "numpy",
    } <= names
    assert not names & {
        "pytest",
        "pyinstaller",
        "pip-licenses",
        "cyclonedx-bom",
        "ruff",
        "mypy",
    }


def test_current_python_environment_is_qt_free() -> None:
    result = check_python_environment()
    assert result.ok, result.messages


def test_locked_environment_validates_the_transitive_closure(tmp_path: Path) -> None:
    requirements = tmp_path / "requirements.txt"
    constraints = tmp_path / "constraints.txt"
    requirements.write_text("root>=1\n", encoding="utf-8")
    constraints.write_text("root==1.2\ndependency==2.3\n", encoding="utf-8")
    distributions = (
        _Distribution("root", "1.2", ("dependency>=2",)),
        _Distribution("dependency", "2.3"),
    )

    result = check_locked_environment(
        requirements,
        constraints,
        distributions=distributions,
    )

    assert result.ok, result.messages


def test_locked_environment_fails_closed_on_version_drift(tmp_path: Path) -> None:
    requirements = tmp_path / "requirements.txt"
    constraints = tmp_path / "constraints.txt"
    requirements.write_text("root>=1\n", encoding="utf-8")
    constraints.write_text("root==1.2\ndependency==2.3\n", encoding="utf-8")
    distributions = (
        _Distribution("root", "1.2", ("dependency>=2",)),
        _Distribution("dependency", "2.2"),
    )

    result = check_locked_environment(
        requirements,
        constraints,
        distributions=distributions,
    )

    assert not result.ok
    assert any(
        "dependency expected=2.3, actual=2.2" in message for message in result.messages
    )


def test_locked_environment_rejects_unsatisfied_dependency_specifier(
    tmp_path: Path,
) -> None:
    requirements = tmp_path / "requirements.txt"
    constraints = tmp_path / "constraints.txt"
    requirements.write_text("root==1.2\n", encoding="utf-8")
    constraints.write_text("root==1.2\ndependency==2.3\n", encoding="utf-8")
    distributions = (
        _Distribution("root", "1.2", ("dependency>=3",)),
        _Distribution("dependency", "2.3"),
    )

    result = check_locked_environment(
        requirements, constraints, distributions=distributions
    )

    assert not result.ok
    assert any("dependency>=3" in message for message in result.messages)


def test_locked_environment_rechecks_a_later_stricter_requirement(
    tmp_path: Path,
) -> None:
    requirements = tmp_path / "requirements.txt"
    constraints = tmp_path / "constraints.txt"
    requirements.write_text("shared>=1\nroot==1.0\n", encoding="utf-8")
    constraints.write_text("shared==2.0\nroot==1.0\n", encoding="utf-8")
    distributions = (
        _Distribution("shared", "2.0"),
        _Distribution("root", "1.0", ("shared>=3",)),
    )

    result = check_locked_environment(
        requirements, constraints, distributions=distributions
    )

    assert not result.ok
    assert any("shared>=3" in message for message in result.messages)


def test_release_installer_applies_constraints() -> None:
    source = (ROOT / "scripts" / "build" / "build_release.py").read_text(
        encoding="utf-8"
    )

    assert '"constraints.txt"' in source
    assert "check_locked_environment" in source


def test_python_and_typescript_layer_guards_have_no_unwaived_debt() -> None:
    active, _ = apply_exceptions(
        architecture_boundary_findings(), load_exceptions()
    )
    assert active == ()
