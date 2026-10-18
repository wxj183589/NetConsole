from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
import venv
from pathlib import Path

import pytest

from netconsole.core import data_root_configuration
from scripts.maintenance.diagnostic_data_root_guard import (
    DIAGNOSTIC_PRODUCTION_DATA_ROOT_BLOCKED,
    DiagnosticDataRootBlockedError,
    create_diagnostic_path_resolver,
    require_diagnostic_test_root,
    require_diagnostic_path_resolver,
)
from netconsole.core.paths import PathResolver
from netconsole.core.runtime_mode import RuntimeMode
from netconsole.services.vehicle_mr_online import VehicleMrOnlineStore


def _roots(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    workspace = tmp_path / "workspace"
    repository = workspace / "NetConsole"
    test_base = workspace / "test-data" / "NetConsole"
    production = tmp_path / "NetConsoleData"
    repository.mkdir(parents=True)
    test_base.mkdir(parents=True)
    production.mkdir()
    (repository / "pyproject.toml").write_text("[project]\nname = 'fixture'\n", encoding="utf-8")
    (repository / "src" / "netconsole" / "core").mkdir(parents=True)
    (repository / "src" / "netconsole" / "tools").mkdir(parents=True)
    (repository / "src" / "netconsole" / "core" / "paths.py").write_text("", encoding="utf-8")
    (repository / "src" / "netconsole" / "tools" / "diagnostic_data_root_guard.py").write_text(
        "", encoding="utf-8"
    )
    subprocess.run(
        ["git", "init", "--quiet", str(repository)],
        check=True,
        capture_output=True,
        text=True,
    )
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


def test_safe_factory_binds_path_resolver_data_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, repository, test_base, production = _roots(tmp_path)
    monkeypatch.setenv("NETCONSOLE_RUNTIME_MODE", "test")
    monkeypatch.setenv("NETCONSOLE_DATA_ROOT", str(production))
    root = test_base / "factory-run"

    paths = create_diagnostic_path_resolver(
        root,
        repository_root=repository,
        runtime_mode=RuntimeMode.TEST,
        production_root=production,
    )

    assert paths.data_root == root.resolve()
    assert require_diagnostic_path_resolver(paths, root) is paths
    store = VehicleMrOnlineStore(paths, "demo")
    assert store.db_path.is_relative_to(root.resolve())
    assert store.db_path.is_file()


def test_positional_path_resolver_mismatch_is_blocked_before_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, repository, test_base, production = _roots(tmp_path)
    monkeypatch.setenv("NETCONSOLE_RUNTIME_MODE", "desktop")
    monkeypatch.setenv("NETCONSOLE_DATA_ROOT", str(production))
    root = test_base / "positional-run"
    validated = require_diagnostic_test_root(
        root,
        repository_root=repository,
        runtime_mode=RuntimeMode.TEST,
        production_root=production,
    )

    # This is the original incident shape: the positional argument is app_root
    # and the resolver falls back to the configured persistent data root.
    wrong_paths = PathResolver(validated)
    with pytest.raises(DiagnosticDataRootBlockedError) as error:
        require_diagnostic_path_resolver(wrong_paths, validated)
    assert error.value.code == DIAGNOSTIC_PRODUCTION_DATA_ROOT_BLOCKED
    assert wrong_paths.data_root == production.resolve()
    assert not (production / "sites").exists()


def test_missing_repository_root_is_blocked(tmp_path: Path) -> None:
    _, _, test_base, production = _roots(tmp_path)
    with pytest.raises(DiagnosticDataRootBlockedError) as error:
        require_diagnostic_test_root(
            test_base / "missing-repository",
            repository_root=None,
            runtime_mode=RuntimeMode.TEST,
            production_root=production,
        )
    assert error.value.code == DIAGNOSTIC_PRODUCTION_DATA_ROOT_BLOCKED


def test_misidentified_repository_root_is_blocked(tmp_path: Path) -> None:
    _, _, test_base, production = _roots(tmp_path)
    fake_repository = tmp_path / "fake-repository"
    fake_repository.mkdir()
    fake_root = test_base / "misidentified-run"
    with pytest.raises(DiagnosticDataRootBlockedError) as error:
        require_diagnostic_test_root(
            fake_root,
            repository_root=fake_repository,
            runtime_mode=RuntimeMode.TEST,
            production_root=production,
        )
    assert error.value.code == DIAGNOSTIC_PRODUCTION_DATA_ROOT_BLOCKED
    assert not (fake_repository / "src").exists()


def test_nested_test_root_is_blocked(tmp_path: Path) -> None:
    _, repository, test_base, production = _roots(tmp_path)
    _assert_blocked(test_base / "run-1" / "nested", repository, production)


def test_normal_path_resolver_remains_available_to_non_diagnostic_runtime(
    tmp_path: Path,
) -> None:
    paths = PathResolver(
        app_root=tmp_path / "app",
        data_root=tmp_path / "normal-data",
    )
    assert paths.data_root == (tmp_path / "normal-data").resolve()


def test_guard_is_importable_from_workspace_external_script(tmp_path: Path) -> None:
    _, repository, test_base, production = _roots(tmp_path)
    external_dir = tmp_path / "workspace-reports" / "diagnostic"
    external_dir.mkdir(parents=True)
    script = external_dir / "one_off_diagnostic.py"
    script.write_text(
        """
from pathlib import Path
import sys

from netconsole.tools.diagnostic_data_root_guard import require_diagnostic_test_root

root = require_diagnostic_test_root(
    sys.argv[1],
    repository_root=sys.argv[2],
    runtime_mode="test",
    production_root=sys.argv[3],
)
print(root)
""".strip(),
        encoding="utf-8",
    )
    environment = os.environ.copy()
    source_root = Path(__file__).parents[1] / "src"
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(source_root), environment.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            str(test_base / "external-run"),
            str(repository),
            str(production),
        ],
        cwd=external_dir,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(test_base / "external-run")


def test_guard_is_importable_from_a_real_wheel_install(
    tmp_path: Path,
) -> None:
    source_root = Path(__file__).parents[1]
    wheel_dir = tmp_path / "wheel"
    wheel_dir.mkdir()
    wheel_source = tmp_path / "wheel-source"
    wheel_source.mkdir()
    shutil.copy2(source_root / "pyproject.toml", wheel_source / "pyproject.toml")
    shutil.copytree(source_root / "src", wheel_source / "src")
    subprocess.run(
        ["git", "init", "--quiet", str(wheel_source)],
        check=True,
        capture_output=True,
        text=True,
    )
    test_base = wheel_source.parent / "test-data" / "NetConsole"
    test_base.mkdir(parents=True)
    production = tmp_path / "NetConsoleData"
    production.mkdir()
    wheel_build = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            ".",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheel_dir),
        ],
        cwd=wheel_source,
        env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert wheel_build.returncode == 0, wheel_build.stderr
    wheels = sorted(wheel_dir.glob("netconsole-*.whl"))
    assert len(wheels) == 1

    venv_dir = tmp_path / "installed-python"
    venv.EnvBuilder(with_pip=True, clear=True).create(venv_dir)
    installed_python = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    install = subprocess.run(
        [
            str(installed_python),
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--no-index",
            str(wheels[0]),
        ],
        cwd=tmp_path,
        env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert install.returncode == 0, install.stderr

    external_dir = tmp_path / "installed-external"
    external_dir.mkdir()
    script = external_dir / "wheel_diagnostic.py"
    script.write_text(
        """
import sys

from netconsole.tools.diagnostic_data_root_guard import (
    DIAGNOSTIC_PRODUCTION_DATA_ROOT_BLOCKED,
    create_diagnostic_path_resolver,
)

paths = create_diagnostic_path_resolver(
    sys.argv[1],
    repository_root=sys.argv[2],
    runtime_mode="test",
    production_root=sys.argv[3],
)
print(paths.data_root)
print(DIAGNOSTIC_PRODUCTION_DATA_ROOT_BLOCKED)
""".strip(),
        encoding="utf-8",
    )
    environment = {
        key: value for key, value in os.environ.items() if key != "PYTHONPATH"
    }
    environment["NETCONSOLE_RUNTIME_MODE"] = "test"
    environment["NETCONSOLE_PROJECT_ROOT"] = str(wheel_source)
    valid = subprocess.run(
        [
            str(installed_python),
            str(script),
            str(test_base / "wheel-run"),
            str(wheel_source),
            str(production),
        ],
        cwd=external_dir,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert valid.returncode == 0, valid.stderr
    assert str(test_base / "wheel-run") in valid.stdout

    blocked = subprocess.run(
        [
            str(installed_python),
            str(script),
            str(production),
            str(wheel_source),
            str(production),
        ],
        cwd=external_dir,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert blocked.returncode != 0
    assert DIAGNOSTIC_PRODUCTION_DATA_ROOT_BLOCKED in blocked.stderr
