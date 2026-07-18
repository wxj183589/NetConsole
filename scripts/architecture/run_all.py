from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.architecture.cli import CHECKS
from scripts.architecture.guard_core import finish, load_exceptions


def main() -> int:
    failed: list[str] = []
    all_findings = []
    for name, check in CHECKS.items():
        findings = check()
        all_findings.extend(findings)
        if finish(name, findings) != 0:
            failed.append(name)
    finding_keys = {(item.rule_id, item.path) for item in all_findings}
    unused = [
        item
        for item in load_exceptions()
        if (item.rule_id, item.path) not in finding_keys
    ]
    if unused:
        failed.append("stale-exceptions")
        print(f"[FAIL] stale-exceptions: {len(unused)} unused exception(s)")
        for item in unused:
            print(f"ARCH_EXCEPTION_UNUSED {item.rule_id} {item.path}")
    if failed:
        print(f"[FAIL] architecture guard summary: {len(failed)}/{len(CHECKS)} failed: {', '.join(failed)}")
        return 1
    print(f"[PASS] architecture guard summary: {len(CHECKS)}/{len(CHECKS)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
