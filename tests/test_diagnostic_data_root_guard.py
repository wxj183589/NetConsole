from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from netconsole.core import data_root_configuration
from scripts.maintenance.diagnostic_data_root_guard import (
    DIAGNOSTIC_PRODUCTION_DATA_ROOT_BLOCKED,
    DiagnosticDataRootBlockedError,
    require_diagnostic_test_root,
)
from netconsole.core.runtime_mode import RuntimeMode


def _roots(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    workspace = tmp_path / "workspace"
    repository = workspace / "NetConsole"
    test_base = workspace / "test-data" / "NetConsole"
    production = tmp_path / "NetConsoleData"
    repository.mkdir(parents=True)
    test_base.mkdir(parents=True)
    production.mkdir()
    return workspace, repository, test_base, production


def _guarded_entrypoint(
    value: object,
    *,
    repository: Path,
    production: Path,
    mkdir_calls: list[Path],
    sqlite_calls: list[Path],
) -> Path:
    root = require_diagnostic_test_root(
        value,
        repository_root=repository,
        runtime_mode=RuntimeMode.TEST,
        production_root=production,
    )
    mkdir_calls.append(root)
    sqlite_path = root / "fixture.sqlite"
    sqlite_calls.append(sqlite_path)
    root.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(sqlite_path) as connection:
        connection.execute("CREATE TABLE probe (value INTEGER)")
    return root


def _assert_blocked(value: object, repository: Path, production: Path) -> None:
    with pytest.raises(DiagnosticDataRootBlockedError) as error:
        require_diagnostic_test_root(
            value,
            repository_root=repository,
            runtime_mode=RuntimeMode.TEST,
            production_root=production,
        )
    assert error.value.code == DIAGNOSTIC_PRODUCTION_DATA_ROOT_BLOCKED


@pytest.mark.parametrize("value", [None, "", "   ", "relative\\run"])
def test_missing_empty_or_relative_root_is_blocked(
    value: object, tmp_path: Path
) -> None:
    _, repository, _, production = _roots(tmp_path)
    _assert_blocked(value, repository, production)


@pytest.mark.parametrize("runtime_mode", [None, "", "desktop", "server", "invalid"])
def test_runtime_mode_must_be_explicit_test(tmp_path: Path, runtime_mode: object) -> None:
    _, repository, test_base, production = _roots(tmp_path)
    with pytest.raises(DiagnosticDataRootBlockedError):
        require_diagnostic_test_root(
            test_base / "run-1",
            repository_root=repository,
            runtime_mode=runtime_mode,
            production_root=production,
        )


@pytest.mark.parametrize("suffix", ["", "\\sites\\demo", "\\runtime"])
def test_production_root_and_children_are_blocked(tmp_path: Path, suffix: str) -> None:
    _, repository, _, production = _roots(tmp_path)
    _assert_blocked(Path(f"{production}{suffix}"), repository, production)


def test_production_parent_and_test_base_are_blocked(tmp_path: Path) -> None:
    _, repository, test_base, production = _roots(tmp_path)
    _assert_blocked(production.parent, repository, production)
    _assert_blocked(test_base, repository, production)


def test_path_traversal_and_normalisation_variants_are_blocked(tmp_path: Path) -> None:
    _, repository, test_base, production = _roots(tmp_path)
    _assert_blocked(production / "run-1" / "..", repository, production)
    _assert_blocked(Path(str(production).upper()), repository, production)
    _assert_blocked(Path(str(production).replace("\\", "/")), repository, production)


def test_production_write_authorization_cannot_bypass_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, repository, test_base, production = _roots(tmp_path)
    monkeypatch.setenv("NETCONSOLE_ALLOW_PRODUCTION_WRITE", "1")
    _assert_blocked(test_base / "run-1", repository, production)


def test_unknown_production_root_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, repository, test_base, _ = _roots(tmp_path)
    monkeypatch.setattr(data_root_configuration, "read_machine_data_root", lambda: None)
    with pytest.raises(DiagnosticDataRootBlockedError):
        require_diagnostic_test_root(
            test_base / "run-1",
            repository_root=repository,
            runtime_mode=RuntimeMode.TEST,
        )


def test_symlink_to_production_is_blocked_without_touching_target(tmp_path: Path) -> None:
    _, repository, test_base, production = _roots(tmp_path)
    link = test_base / "link-to-production"
    try:
        link.symlink_to(production, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"directory symlink unavailable on this host: {exc}")
    _assert_blocked(link, repository, production)
    assert not (production / "fixture.sqlite").exists()


def test_block_happens_before_mkdir_or_sqlite_connect(tmp_path: Path) -> None:
    _, repository, _, production = _roots(tmp_path)
    mkdir_calls: list[Path] = []
    sqlite_calls: list[Path] = []
    with pytest.raises(DiagnosticDataRootBlockedError):
        _guarded_entrypoint(
            production,
            repository=repository,
            production=production,
            mkdir_calls=mkdir_calls,
            sqlite_calls=sqlite_calls,
        )
    assert mkdir_calls == []
    assert sqlite_calls == []
    assert not (production / "fixture.sqlite").exists()


def test_normal_test_root_and_sqlite_initialization_are_allowed(tmp_path: Path) -> None:
    _, repository, test_base, production = _roots(tmp_path)
    root = test_base / "run-1"
    mkdir_calls: list[Path] = []
    sqlite_calls: list[Path] = []
    assert (
        _guarded_entrypoint(
            root,
            repository=repository,
            production=production,
            mkdir_calls=mkdir_calls,
            sqlite_calls=sqlite_calls,
        )
        == root
    )
    assert mkdir_calls == [root]
    assert sqlite_calls == [root / "fixture.sqlite"]
    assert (root / "fixture.sqlite").is_file()
