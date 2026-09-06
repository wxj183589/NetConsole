from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.architecture.cli import CHECKS
from scripts.architecture.guard_core import finish


STABLE_GATES = (
    "architecture-boundaries",
    "forbidden-imports",
    "dynamic-chart-stability",
    "device-command-hardcoding",
    "removed-features",
    "orphan-modules",
    "product-architecture",
    "production-database-boundary",
)


def main() -> int:
    failed: list[str] = []
    for name in STABLE_GATES:
        if finish(name, CHECKS[name]()) != 0:
            failed.append(name)
    if failed:
        print(f"ARCHITECTURE_GREEN_GATES=FAIL gates={','.join(failed)}")
        return 1
    print(f"ARCHITECTURE_GREEN_GATES=PASS count={len(STABLE_GATES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
