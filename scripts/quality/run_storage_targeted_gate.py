"""Run the bounded database/storage governance regression suite and persist evidence."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TEST_ROOT = Path("D:/study/test-data/NetConsole")
DEFAULT_DEVELOPMENT_ROOT = Path("D:/study")
TARGETS = (
    "tests/test_history_store.py",
    "tests/test_history_legacy_migration.py",
    "tests/test_database_footprint_maintenance.py",
    "tests/test_task_repository_storage_governance.py",
    "tests/test_task_result_rollout.py",
    "tests/test_site_retention.py",
    "tests/test_site_storage.py",
    "tests/test_backup_lifecycle.py",
    "tests/test_database_functional_compatibility.py",
    "tests/test_finalize_functional_compatibility.py",
    "tests/test_benchmark_database_functional_queries.py",
    "tests/test_collect_functional_consumer_observations.py",
    "tests/test_collect_global_storage_inventory.py",
    "tests/test_finalize_site_storage_audit.py",
    "tests/test_build_site_storage_optimization_impact.py",
    "tests/test_validate_history_provenance.py",
    "tests/test_integrated_site_package_validation.py",
    "tests/test_storage_no_reinflation.py",
    "tests/test_validate_storage_no_reinflation.py",
    "tests/architecture/test_storage_registry_language_guards.py",
    "tests/architecture/test_architecture_guards.py",
)
Runner = Callable[..., Any]


class TargetedGateError(ValueError):
    """Raised when the targeted gate cannot establish a safe isolated boundary."""


def run_storage_targeted_gate(
    *,
    run_id: str,
    output_path: Path,
    repo_root: Path = ROOT,
    development_root: Path = DEFAULT_DEVELOPMENT_ROOT,
    test_base_root: Path = DEFAULT_TEST_ROOT,
    python_executable: str = sys.executable,
    inherited_environment: Mapping[str, str] | None = None,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    root = repo_root.resolve(strict=True)
    development = development_root.resolve(strict=True)
    policy_root = _development_policy_root(development)
    output = output_path.resolve()
    if output == development or not output.is_relative_to(development):
        raise TargetedGateError("targeted gate output must remain below D:/study")
    if output.exists():
        raise TargetedGateError(f"refusing to overwrite targeted gate evidence: {output}")
    safe_id = str(run_id).strip()
    if not safe_id or Path(safe_id).name != safe_id:
        raise TargetedGateError("run_id must be one safe path component")
    base = test_base_root.resolve()
    if base == policy_root or not base.is_relative_to(policy_root):
        raise TargetedGateError("targeted gate test base must remain below D:/study")
    run_root = (base / safe_id).resolve()
    if (
        run_root == base
        or not run_root.is_relative_to(base)
        or not run_root.is_relative_to(policy_root)
    ):
        raise TargetedGateError("targeted gate run root escapes its test base")
    if run_root.exists():
        raise TargetedGateError(f"targeted gate run root already exists: {run_root}")

    environment = dict(inherited_environment or os.environ)
    environment.update(
        {
            "PYTHONPATH": os.pathsep.join((str(root / "src"), str(root))),
            "NETCONSOLE_RUNTIME_MODE": "test",
            "NETCONSOLE_STORAGE_MODE": "persistent",
            "NETCONSOLE_DATA_ROOT": str(run_root / "data-root"),
        }
    )
    command = (
        python_executable,
        "-m",
        "pytest",
        *TARGETS,
        "-q",
        "--tb=short",
        "--basetemp",
        str(run_root / "pytest"),
    )
    started = time.perf_counter()
    run_root.mkdir(parents=True)
    try:
        completed = runner(command, cwd=root, env=environment, check=False)
        return_code = int(completed.returncode)
    finally:
        _remove_owned_root(run_root, base)
    report = {
        "mode": "targeted",
        "result": "PASS" if return_code == 0 else "FAIL",
        "head_sha": _git_head(root),
        "required_suites": ["storage-targeted"],
        "passed": ["storage-targeted"] if return_code == 0 else [],
        "failed": [] if return_code == 0 else ["storage-targeted"],
        "not_run": [],
        "duration_seconds": round(time.perf_counter() - started, 3),
        "targets": list(TARGETS),
        "command": list(command),
        "isolation": {
            "runtime_mode": "test",
            "test_root": str(run_root),
            "test_root_removed": not run_root.exists(),
            "production_data_root_used": False,
        },
    }
    _atomic_json(output, report)
    return report


def _development_policy_root(development: Path) -> Path:
    if os.name != "nt":
        return development
    fixed = DEFAULT_DEVELOPMENT_ROOT.resolve(strict=True)
    if not development.is_relative_to(fixed):
        raise TargetedGateError("development root must remain below D:/study")
    return fixed


def _remove_owned_root(path: Path, base: Path) -> None:
    resolved = path.resolve()
    policy_root = _development_policy_root(base)
    if (
        resolved == base
        or not resolved.is_relative_to(base)
        or not resolved.is_relative_to(policy_root)
    ):
        raise TargetedGateError("refusing to remove an unowned test path")
    shutil.rmtree(resolved)


def _git_head(repo_root: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--verify", "HEAD"],
        check=True,
        capture_output=True,
        encoding="utf-8",
        text=True,
    )
    return completed.stdout.strip().casefold()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(
                (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
            )
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        temporary.unlink()
    finally:
        temporary.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--development-root", type=Path, default=DEFAULT_DEVELOPMENT_ROOT)
    parser.add_argument("--test-base-root", type=Path, default=DEFAULT_TEST_ROOT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_storage_targeted_gate(
        run_id=args.run_id,
        output_path=args.output,
        repo_root=args.repo_root,
        development_root=args.development_root,
        test_base_root=args.test_base_root,
    )
    print(json.dumps({"status": report["result"], "output": str(args.output)}, ensure_ascii=False, indent=2))
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
