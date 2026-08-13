from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence
from uuid import uuid4

from scripts.quality.check_change_impact import DEFAULT_CONFIG, Impact, _load_config, classify


ROOT = Path(__file__).resolve().parents[2]
REPORT_ROOT = ROOT / ".local-reports"
TEST_BASE_ROOT = Path(r"D:\NetConsoleTestData")
MODES = ("auto", "fast", "consumer", "full")
FAST_SUITES = (
    "change-impact",
    "ruff-changed",
    "python-direct",
    "renderer-direct",
    "electron-direct",
    "architecture-targeted",
    "git-diff-check",
)
FULL_SUITES = (
    "renderer-full",
    "python-full",
    "electron-contract",
    "architecture-guards",
    "main-contract-smoke",
    "ruff-full",
    "docs-path-guards",
    "git-diff-check",
)
CONSUMER_SUITE_ORDER = (
    "renderer-full",
    "python-full",
    "electron-contract",
    "architecture-guards",
    "main-contract-smoke",
    "package-smoke",
)
PACKAGING_PREFIXES = (
    "scripts/build/",
    "apps/desktop_electron/scripts/package.mjs",
    "apps/desktop_electron/scripts/package-smoke.mjs",
    "apps/desktop_electron/build/",
    "requirements-",
    "constraints.txt",
)


@dataclass(frozen=True)
class CommandStep:
    label: str
    argv: tuple[str, ...]
    cwd: Path = ROOT


@dataclass(frozen=True)
class SuiteResult:
    suite_id: str
    label: str
    status: str
    duration_seconds: float
    detail: str


@dataclass(frozen=True)
class GateContext:
    base_sha: str
    head_sha: str
    changed_paths: tuple[str, ...]
    impact: Impact
    mode: str
    run_id: str
    run_root: Path
    environment: Mapping[str, str]


Executor = Callable[[GateContext], Sequence[CommandStep]]
StepRunner = Callable[[CommandStep, Mapping[str, str]], int]


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def resolve_revisions(base_sha: str = "", head_sha: str = "") -> tuple[str, str]:
    head = head_sha or _git("rev-parse", "HEAD")
    if base_sha:
        return base_sha, head
    try:
        upstream = _git("rev-parse", "@{upstream}")
    except subprocess.CalledProcessError:
        upstream = ""
        for candidate in ("github/main", "origin/main", "main"):
            try:
                upstream = _git("rev-parse", "--verify", candidate)
                break
            except subprocess.CalledProcessError:
                continue
        if not upstream:
            upstream = f"{head}^"
    return _git("merge-base", head, upstream), head


def changed_paths(base_sha: str, head_sha: str) -> tuple[str, ...]:
    values: set[str] = set()
    for args in (
        ("diff", "--name-only", base_sha, head_sha),
        ("diff", "--name-only"),
        ("diff", "--cached", "--name-only"),
        ("ls-files", "--others", "--exclude-standard"),
    ):
        values.update(line.replace("\\", "/") for line in _git(*args).splitlines() if line.strip())
    return tuple(sorted(values))


def select_mode(requested: str, risk_level: str) -> str:
    if requested != "auto":
        return requested
    return {"L1": "fast", "L2": "fast", "L3": "consumer", "L4": "full"}[risk_level]


def _test_root(run_id: str, *, base_root: Path = TEST_BASE_ROOT) -> Path:
    target = (base_root / run_id).resolve()
    base = base_root.resolve()
    if target == base or not target.is_relative_to(base):
        raise ValueError("Local Gate test root must be a unique child of the test base root")
    return target


def remove_owned_test_root(target: Path, *, base_root: Path = TEST_BASE_ROOT) -> None:
    resolved = target.resolve()
    base = base_root.resolve()
    if resolved == base or not resolved.is_relative_to(base):
        raise ValueError("Local Gate may only remove an owned child of the test base root")
    if not resolved.exists():
        return

    def clear_readonly_and_retry(function: Callable[[str], object], path: str, error: BaseException) -> None:
        if not isinstance(error, PermissionError):
            raise error
        os.chmod(path, stat.S_IWRITE)
        function(path)

    shutil.rmtree(resolved, onexc=clear_readonly_and_retry)
    if resolved.exists():
        raise OSError(f"Local Gate failed to remove its test root: {resolved}")


@contextmanager
def isolated_test_environment(
    run_id: str,
    *,
    inherited: Mapping[str, str] | None = None,
    base_root: Path = TEST_BASE_ROOT,
) -> Iterator[tuple[Path, dict[str, str]]]:
    run_root = _test_root(run_id, base_root=base_root)
    run_root.mkdir(parents=True, exist_ok=False)
    environment = dict(inherited or os.environ)
    environment.update(
        {
            "NETCONSOLE_RUNTIME_MODE": "test",
            "NETCONSOLE_STORAGE_MODE": "persistent",
            "NETCONSOLE_DATA_ROOT": str(run_root / "session"),
        }
    )
    try:
        yield run_root, environment
    finally:
        verified = _test_root(run_id, base_root=base_root)
        if verified == run_root.resolve():
            remove_owned_test_root(verified, base_root=base_root)


def _pytest_step(label: str, targets: Iterable[str], context: GateContext) -> CommandStep:
    return CommandStep(
        label,
        (
            sys.executable,
            "-m",
            "pytest",
            *targets,
            "-q",
            "--tb=short",
            "--basetemp",
            str(context.run_root / f"pytest-{label}"),
        ),
    )


def _pnpm_command(*args: str) -> tuple[str, ...]:
    executable = shutil.which("pnpm.cmd" if os.name == "nt" else "pnpm")
    if executable is None:
        executable = "pnpm.cmd" if os.name == "nt" else "pnpm"
    return (executable, *args)


def _workspace_command(workspace: str, executable: str, *args: str) -> tuple[str, ...]:
    suffix = ".cmd" if os.name == "nt" else ""
    path = ROOT / "apps" / workspace / "node_modules" / ".bin" / f"{executable}{suffix}"
    return (str(path), *args)


def _python_full(context: GateContext) -> Sequence[CommandStep]:
    return (_pytest_step("python-full", (), context),)


def _renderer_full(context: GateContext) -> Sequence[CommandStep]:
    del context
    cwd = ROOT / "apps" / "desktop_renderer"
    return (
        CommandStep("renderer-tests", _workspace_command("desktop_renderer", "vitest", "run"), cwd),
        CommandStep("renderer-typecheck", _workspace_command("desktop_renderer", "vue-tsc", "-b"), cwd),
        CommandStep("renderer-build", _workspace_command("desktop_renderer", "vite", "build"), cwd),
    )


def _electron_contract(context: GateContext) -> Sequence[CommandStep]:
    del context
    cwd = ROOT / "apps" / "desktop_electron"
    return (
        CommandStep("electron-tests", _workspace_command("desktop_electron", "vitest", "run"), cwd),
        CommandStep("electron-typecheck", _workspace_command("desktop_electron", "tsc", "--noEmit", "-p", "tsconfig.json"), cwd),
        CommandStep(
            "electron-main-preload-build",
            (shutil.which("node") or "node", "scripts/build.mjs"),
            cwd,
        ),
    )


def _architecture_guards(context: GateContext) -> Sequence[CommandStep]:
    del context
    return (CommandStep("architecture-guards", (sys.executable, "scripts/architecture/run_all.py")),)


def _main_contract_smoke(context: GateContext) -> Sequence[CommandStep]:
    return (
        CommandStep(
            "main-contract-smoke",
            (sys.executable, "-m", "scripts.quality.run_main_contract_smoke", "--run-id", f"{context.run_id}-main"),
        ),
    )


def _package_smoke(context: GateContext) -> Sequence[CommandStep]:
    del context
    return (CommandStep("package-smoke", _pnpm_command("run", "smoke:package"), ROOT / "apps" / "desktop_electron"),)


def _agent_go(context: GateContext) -> Sequence[CommandStep]:
    del context
    cwd = ROOT / "apps" / "agent"
    return (
        CommandStep("agent-go-tests", ("go", "test", "./..."), cwd),
        CommandStep("agent-go-build", ("go", "build", "./..."), cwd),
    )


def _change_impact(context: GateContext) -> Sequence[CommandStep]:
    return (
        CommandStep(
            "change-impact",
            (sys.executable, "-m", "scripts.quality.check_change_impact", "--paths", *context.changed_paths),
        ),
    )


def _ruff_changed(context: GateContext) -> Sequence[CommandStep]:
    paths = tuple(path for path in context.changed_paths if path.endswith(".py") and (ROOT / path).is_file())
    return (CommandStep("ruff-changed", (sys.executable, "-m", "ruff", "check", *paths)),) if paths else ()


def _direct_python_targets(paths: Iterable[str]) -> tuple[str, ...]:
    targets: set[str] = set()
    for path in paths:
        if path.startswith("tests/") and path.endswith(".py") and (ROOT / path).is_file():
            targets.add(path)
        if path.endswith(".py"):
            stem = Path(path).stem
            for test_path in (ROOT / "tests" / f"test_{stem}.py", ROOT / "tests" / "quality" / f"test_{stem}.py"):
                if test_path.is_file():
                    targets.add(test_path.relative_to(ROOT).as_posix())
    if "config/architecture/change_impact_matrix.json" in paths:
        targets.update(("tests/quality/test_change_impact.py", "tests/quality/test_local_gate.py"))
    if any(path.startswith(("scripts/architecture/", "config/architecture/")) for path in paths):
        targets.add("tests/architecture/test_architecture_guards.py")
    return tuple(sorted(targets))


def _python_direct(context: GateContext) -> Sequence[CommandStep]:
    targets = _direct_python_targets(context.changed_paths)
    return (_pytest_step("python-direct", targets, context),) if targets else ()


def _workspace_direct(context: GateContext, workspace: str) -> Sequence[CommandStep]:
    prefix = f"apps/{workspace}/"
    tests = tuple(
        path.removeprefix(prefix)
        for path in context.changed_paths
        if path.startswith(prefix) and (".test." in path or "/tests/" in path) and (ROOT / path).is_file()
    )
    if not tests:
        return ()
    return (
        CommandStep(
            f"{workspace}-direct",
            _workspace_command(workspace, "vitest", "run", *tests),
            ROOT / "apps" / workspace,
        ),
    )


def _renderer_direct(context: GateContext) -> Sequence[CommandStep]:
    return _workspace_direct(context, "desktop_renderer")


def _electron_direct(context: GateContext) -> Sequence[CommandStep]:
    return _workspace_direct(context, "desktop_electron")


def _architecture_targeted(context: GateContext) -> Sequence[CommandStep]:
    relevant = any(
        path.startswith(("scripts/architecture/", "config/architecture/", "tests/architecture/"))
        for path in context.changed_paths
    )
    return _architecture_guards(context) if relevant else ()


def _ruff_full(context: GateContext) -> Sequence[CommandStep]:
    del context
    return (CommandStep("ruff-full", (sys.executable, "-m", "ruff", "check", ".")),)


def _docs_path_guards(context: GateContext) -> Sequence[CommandStep]:
    return (
        _pytest_step(
            "docs-path-guards",
            ("tests/test_project_docs_layout.py", "tests/quality/test_directory_readmes.py"),
            context,
        ),
    )


def _git_diff_check(context: GateContext) -> Sequence[CommandStep]:
    return (CommandStep("git-diff-check", ("git", "diff", "--check", context.base_sha)),)


SUITE_EXECUTORS: dict[str, Executor] = {
    "python-full": _python_full,
    "renderer-full": _renderer_full,
    "electron-contract": _electron_contract,
    "architecture-guards": _architecture_guards,
    "main-contract-smoke": _main_contract_smoke,
    "package-smoke": _package_smoke,
    "agent-go": _agent_go,
    "change-impact": _change_impact,
    "ruff-changed": _ruff_changed,
    "python-direct": _python_direct,
    "renderer-direct": _renderer_direct,
    "electron-direct": _electron_direct,
    "architecture-targeted": _architecture_targeted,
    "ruff-full": _ruff_full,
    "docs-path-guards": _docs_path_guards,
    "git-diff-check": _git_diff_check,
}


def required_suites(context: GateContext) -> tuple[str, ...]:
    if context.mode == "fast":
        return FAST_SUITES
    if context.mode == "consumer":
        selected = set(context.impact.suites)
        ordered = [suite_id for suite_id in CONSUMER_SUITE_ORDER if suite_id in selected]
        ordered.extend(sorted(selected - set(CONSUMER_SUITE_ORDER)))
        return tuple((*FAST_SUITES, *ordered))
    suites = list(FULL_SUITES)
    if any(path.startswith("apps/agent/") for path in context.changed_paths):
        suites.append("agent-go")
    if any(path.startswith(PACKAGING_PREFIXES) for path in context.changed_paths):
        suites.append("package-smoke")
    return tuple(suites)


def _run_step(step: CommandStep, environment: Mapping[str, str]) -> int:
    print(f"  $ {' '.join(step.argv)}")
    try:
        return subprocess.run(step.argv, cwd=step.cwd, env=dict(environment), check=False).returncode
    except OSError as exc:
        print(f"  ! unable to start {step.label}: {exc}", file=sys.stderr)
        return 127


def execute_suites(
    suite_ids: Iterable[str],
    context: GateContext,
    config: Mapping[str, Any],
    *,
    executors: Mapping[str, Executor] = SUITE_EXECUTORS,
    step_runner: StepRunner = _run_step,
) -> list[SuiteResult]:
    results: list[SuiteResult] = []
    registered = config.get("consumer_suites", {})
    for suite_id in suite_ids:
        suite = registered.get(suite_id)
        executor_id = suite.get("executor") if isinstance(suite, dict) else suite_id
        label = suite.get("label", suite_id) if isinstance(suite, dict) else suite_id
        executor = executors.get(executor_id)
        started = monotonic()
        if executor is None:
            results.append(SuiteResult(suite_id, label, "NOT RUN", monotonic() - started, f"missing executor: {executor_id}"))
            continue
        try:
            steps = tuple(executor(context))
        except Exception as exc:
            results.append(SuiteResult(suite_id, label, "NOT RUN", monotonic() - started, f"executor error: {exc}"))
            continue
        failed_step = ""
        for step in steps:
            if step_runner(step, context.environment) != 0:
                failed_step = step.label
                break
        status = "FAIL" if failed_step else "PASS"
        detail = f"failed step: {failed_step}" if failed_step else (f"{len(steps)} step(s)" if steps else "not applicable")
        results.append(SuiteResult(suite_id, label, status, monotonic() - started, detail))
    return results


def _report_payload(
    context: GateContext,
    suites: Sequence[str],
    results: Sequence[SuiteResult],
    started: str,
    ended: str,
) -> dict[str, Any]:
    failed = [item.suite_id for item in results if item.status == "FAIL"]
    not_run = [item.suite_id for item in results if item.status == "NOT RUN"]
    return {
        "base_sha": context.base_sha,
        "head_sha": context.head_sha,
        "risk_level": context.impact.level,
        "contracts": list(context.impact.areas),
        "consumers": list(context.impact.consumers),
        "mode": context.mode,
        "required_suites": list(suites),
        "executed_suites": [asdict(item) for item in results],
        "passed": [item.suite_id for item in results if item.status == "PASS"],
        "failed": failed,
        "not_run": not_run,
        "started_at": started,
        "ended_at": ended,
        "result": "PASS" if not failed and not not_run else "FAIL",
    }


def write_reports(context: GateContext, payload: Mapping[str, Any], *, report_root: Path = REPORT_ROOT) -> None:
    report_root.mkdir(parents=True, exist_ok=True)
    impact_payload = {
        "base_sha": context.base_sha,
        "head_sha": context.head_sha,
        "risk_level": context.impact.level,
        "changed_paths": list(context.changed_paths),
        "contracts": list(context.impact.areas),
        "owners": list(context.impact.owners),
        "consumers": list(context.impact.consumers),
        "required_suites": list(context.impact.suites),
    }
    (report_root / "change-impact.json").write_text(
        json.dumps(impact_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (report_root / "local-gate.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# NetConsole Local Quality Gate",
        "",
        f"- Base: {payload['base_sha']}",
        f"- Head: {payload['head_sha']}",
        f"- Risk: {payload['risk_level']}",
        f"- Mode: {payload['mode']}",
        f"- Result: {payload['result']}",
        "",
        "## Suites",
        "",
        *[f"- [{item['status']}] {item['suite_id']}: {item['detail']}" for item in payload["executed_suites"]],
        "",
    ]
    (report_root / "local-gate.md").write_text("\n".join(lines), encoding="utf-8")


def run_gate(
    *,
    requested_mode: str,
    base_sha: str,
    head_sha: str,
    paths: Sequence[str] | None,
    config_path: Path = DEFAULT_CONFIG,
    executors: Mapping[str, Executor] = SUITE_EXECUTORS,
    step_runner: StepRunner = _run_step,
    report_root: Path = REPORT_ROOT,
    run_id: str | None = None,
    test_base_root: Path = TEST_BASE_ROOT,
) -> tuple[int, dict[str, Any]]:
    config = _load_config(config_path)
    base, head = resolve_revisions(base_sha, head_sha)
    selected_paths = tuple(paths) if paths is not None else changed_paths(base, head)
    impact = classify(selected_paths, config)
    mode = select_mode(requested_mode, impact.level)
    actual_run_id = run_id or f"local-gate-{uuid4().hex}"
    started = datetime.now(UTC).isoformat()
    with isolated_test_environment(actual_run_id, base_root=test_base_root) as (run_root, environment):
        context = GateContext(base, head, selected_paths, impact, mode, actual_run_id, run_root, environment)
        suites = required_suites(context)
        _print_header(context, suites)
        results = execute_suites(suites, context, config, executors=executors, step_runner=step_runner)
        payload = _report_payload(context, suites, results, started, datetime.now(UTC).isoformat())
        write_reports(context, payload, report_root=report_root)
    for item in results:
        print(f"[{item.status}] {item.suite_id}: {item.detail}")
    print(f"RESULT: {payload['result']}")
    return (0 if payload["result"] == "PASS" else 1), payload


def _print_header(context: GateContext, suites: Sequence[str]) -> None:
    print("NetConsole Local Quality Gate")
    print(f"Base: {context.base_sha}")
    print(f"Head: {context.head_sha}")
    print(f"Risk: {context.impact.level}")
    print(f"Contracts: {', '.join(context.impact.areas) or 'none'}")
    print(f"Consumers: {', '.join(context.impact.consumers) or 'direct'}")
    print(f"Mode: {context.mode}")
    print(f"Required Suites: {', '.join(suites)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the NetConsole local quality gate.")
    parser.add_argument("--mode", choices=MODES, default="auto")
    parser.add_argument("--base-sha", default="")
    parser.add_argument("--head-sha", default="")
    parser.add_argument("--paths", nargs="*")
    args = parser.parse_args()
    code, _ = run_gate(
        requested_mode=args.mode,
        base_sha=args.base_sha,
        head_sha=args.head_sha,
        paths=args.paths,
    )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
