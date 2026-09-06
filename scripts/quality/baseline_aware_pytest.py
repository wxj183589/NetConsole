from __future__ import annotations

import argparse
import subprocess
import sys
import uuid
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.architecture.guard_core import ROOT
from scripts.quality.baseline_debt_audit import _load_manifest, _test_root


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the full Python regression while deselecting only exact baseline node IDs."
    )
    parser.add_argument(
        "--manifest",
        default=str(ROOT / "config" / "ci" / "baseline_failures.yaml"),
    )
    args = parser.parse_args()
    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = ROOT / manifest_path
    manifest = _load_manifest(manifest_path.resolve())
    nodeids = [str(item["nodeid"]) for item in manifest["python"]]
    basetemp = _test_root() / f"python-regression-{uuid.uuid4().hex}"
    basetemp.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--tb=short",
        "--basetemp",
        str(basetemp),
    ]
    for nodeid in nodeids:
        command.extend(("--deselect", nodeid))
    print("BASELINE_EXCLUSIONS=" + str(len(nodeids)))
    for nodeid in nodeids:
        print(f"BASELINE_EXCLUDE_EXACT {nodeid}")
    result = subprocess.run(command, cwd=ROOT, check=False)
    if result.returncode == 0:
        print("PYTHON_REGRESSION_NEW_FAILURES=0")
        print("NEW_FAILURES=0")
    else:
        print(f"PYTHON_REGRESSION_NEW_FAILURES=UNKNOWN exit={result.returncode}")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
