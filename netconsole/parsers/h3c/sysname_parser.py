from __future__ import annotations

import re


def parse_sysname(output: str) -> str | None:
    for line in (output or "").splitlines():
        match = re.match(r"^\s*sysname\s+(\S+)\s*$", line)
        if match:
            return match.group(1).strip()
    return None
