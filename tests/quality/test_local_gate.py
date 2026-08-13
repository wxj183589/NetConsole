from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

import scripts.quality.local_gate as local_gate
from scripts.quality.check_change_impact import DEFAULT_CONFIG, _load_config, classify
from scripts.quality.local_gate import (
    FAST_SUITES,
    FULL_SUITES,
    CommandStep,
    GateContext,
    _pnpm_command,
    _run_step,
    _workspace_command,
    execute_suites,
    isolated_test_environment,
    resolve_revisions,
    required_suites,
    run_gate,
    select_mode,
)
from scripts.quality.run_main_contract_smoke import MAIN_CONTRACT_TESTS


@pytest.mark.parametrize(
    ("risk", "expected"),
    (("L1", "fast"), ("L2", "fast"), ("L3", "consumer"), ("L4", "full")),
)
def test_auto_mode_uses_risk_level(risk: str, expected: str) -> None:
    assert select_mode("auto", risk) == expected


def test_revision_resolution_prefers_github_main_without_upstream(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_git(*args: str) -> str:
        calls.append(args)
        if args == ("rev-parse", "HEAD"):
            return "head-sha"
        if args == ("rev-parse", "@{upstream}"):
            raise local_gate.subprocess.CalledProcessError(128, args)
        if args == ("rev-parse", "--verify", "github/main"):
            return "github-main-sha"
        if args == ("merge-base", "head-sha", "github-main-sha"):
            return "base-sha"
        raise AssertionError(args)

    monkeypatch.setattr(local_gate, "_git", fake_git)

    assert resolve_revisions() == ("base-sha", "head-sha")
    assert ("rev-parse", "--verify", "origin/main") not in calls


def test_windows_pnpm_command_uses_cmd_resolved_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(local_gate.os, "name", "nt")
    monkeypatch.setattr(local_gate.shutil, "which", lambda name: r"C:\tools\pnpm.cmd" if name == "pnpm.cmd" else None)

    assert _pnpm_command("test") == (r"C:\tools\pnpm.cmd", "test")


def test_workspace_command_uses_installed_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(local_gate.os, "name", "nt")

    command = _workspace_command("desktop_electron", "vitest", "run")

    assert Path(command[0]).name == "vitest.cmd"
    assert command[1:] == ("run",)


def test_consumer_and_full_build_renderer_before_python(tmp_path: Path) -> None:
    context = _context(tmp_path)
    consumer = replace(
        context,
        mode="consumer",
        impact=replace(context.impact, suites=("python-full", "renderer-full", "electron-contract")),
    )

    suites = required_suites(consumer)

    assert suites.index("renderer-full") < suites.index("python-full")
    assert FULL_SUITES.index("renderer-full") < FULL_SUITES.index("python-full")


def test_unstartable_subprocess_returns_nonzero(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def unavailable(*args, **kwargs):
        raise FileNotFoundError(2, "missing")

    monkeypatch.setattr(local_gate.subprocess, "run", unavailable)

    assert _run_step(CommandStep("missing", ("missing",), tmp_path), {}) == 127


def _context(tmp_path: Path) -> GateContext:
    impact = classify(("docs/README.md",), _load_config(DEFAULT_CONFIG))
    return GateContext(
        base_sha="base",
        head_sha="head",
        changed_paths=("docs/README.md",),
        impact=impact,
        mode="fast",
        run_id="unit",
        run_root=tmp_path,
        environment={"NETCONSOLE_RUNTIME_MODE": "test"},
    )


def test_unknown_suite_is_not_run_and_fails_closed(tmp_path: Path) -> None:
    results = execute_suites(("unknown-suite",), _context(tmp_path), _load_config(DEFAULT_CONFIG), executors={})

    assert [(item.status, item.detail) for item in results] == [("NOT RUN", "missing executor: unknown-suite")]


def test_registry_suite_with_missing_executor_is_not_run(tmp_path: Path) -> None:
    config = _load_config(DEFAULT_CONFIG)
    results = execute_suites(("python-full",), _context(tmp_path), config, executors={})

    assert results[0].status == "NOT RUN"
    assert results[0].detail == "missing executor: python-full"


def test_failed_subprocess_marks_suite_failed(tmp_path: Path) -> None:
    def executor(context: GateContext) -> tuple[CommandStep, ...]:
        return (CommandStep("broken", ("broken",), context.run_root),)

    results = execute_suites(
        ("custom",),
        _context(tmp_path),
        _load_config(DEFAULT_CONFIG),
        executors={"custom": executor},
        step_runner=lambda step, env: 7,
    )

    assert results[0].status == "FAIL"
    assert results[0].detail == "failed step: broken"


def test_isolation_overrides_formal_root_and_cleans_only_owned_run(tmp_path: Path) -> None:
    base = tmp_path / "NetConsoleTestData"
    formal = tmp_path / "NetConsoleData"
    formal.mkdir()

    with isolated_test_environment(
        "local-gate-unit",
        inherited={"NETCONSOLE_DATA_ROOT": str(formal), "NETCONSOLE_RUNTIME_MODE": "desktop-packaged"},
        base_root=base,
    ) as (run_root, environment):
        assert environment["NETCONSOLE_RUNTIME_MODE"] == "test"
        assert Path(environment["NETCONSOLE_DATA_ROOT"]).is_relative_to(run_root)
        (run_root / "owned.txt").write_text("owned", encoding="utf-8")

    assert not run_root.exists()
    assert formal.is_dir()


def test_isolation_rejects_test_base_itself(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unique child"):
        with isolated_test_environment(".", base_root=tmp_path):
            pass


def test_path_override_base_head_exit_code_and_json_report(tmp_path: Path) -> None:
    executors = {
        suite_id: (lambda context, suite_id=suite_id: (CommandStep(suite_id, ("ok",), context.run_root),))
        for suite_id in FAST_SUITES
    }
    observed_roots: list[Path] = []

    def pass_step(step: CommandStep, environment: dict[str, str]) -> int:
        del step
        observed_roots.append(Path(environment["NETCONSOLE_DATA_ROOT"]))
        return 0

    report_root = tmp_path / "reports"
    code, payload = run_gate(
        requested_mode="auto",
        base_sha="base-sha",
        head_sha="head-sha",
        paths=("docs/README.md",),
        executors=executors,
        step_runner=pass_step,
        report_root=report_root,
        run_id="report-unit",
        test_base_root=tmp_path / "test-data",
    )

    assert code == 0
    assert payload["base_sha"] == "base-sha"
    assert payload["head_sha"] == "head-sha"
    assert payload["risk_level"] == "L1"
    assert payload["mode"] == "fast"
    assert payload["result"] == "PASS"
    assert all("report-unit" in str(path) for path in observed_roots)
    saved = json.loads((report_root / "local-gate.json").read_text(encoding="utf-8"))
    assert saved == payload
    assert json.loads((report_root / "change-impact.json").read_text(encoding="utf-8"))["changed_paths"] == [
        "docs/README.md"
    ]


def test_not_run_required_suite_returns_nonzero(tmp_path: Path) -> None:
    executors = {
        suite_id: (lambda context: (CommandStep("ok", ("ok",), context.run_root),))
        for suite_id in FAST_SUITES
        if suite_id != "python-direct"
    }
    code, payload = run_gate(
        requested_mode="fast",
        base_sha="base-sha",
        head_sha="head-sha",
        paths=("docs/README.md",),
        executors=executors,
        step_runner=lambda step, env: 0,
        report_root=tmp_path / "reports",
        run_id="not-run-unit",
        test_base_root=tmp_path / "test-data",
    )

    assert code == 1
    assert payload["not_run"] == ["python-direct"]
    assert payload["result"] == "FAIL"


def test_main_contract_smoke_has_one_stable_test_per_entry() -> None:
    assert len(MAIN_CONTRACT_TESTS) == 12
    assert len(set(MAIN_CONTRACT_TESTS)) == 12
    assert all((Path(__file__).resolve().parents[2] / target.split("::", maxsplit=1)[0]).is_file() for target in MAIN_CONTRACT_TESTS)
