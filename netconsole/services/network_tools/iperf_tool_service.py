from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from netconsole.core.paths import PathResolver
from netconsole.services.tool_path_resolver import resolve_tool_path


@dataclass(frozen=True)
class IperfToolStatus:
    found: bool
    path: Path | None = None
    version: str = ""
    output: str = ""


def find_iperf_tool(paths: PathResolver, custom_path: str | Path | None = None) -> Path | None:
    return resolve_tool_path("iperf3", paths, custom_path=custom_path)


def detect_iperf_version(
    iperf_path: Path,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> IperfToolStatus:
    try:
        result = runner(
            [str(iperf_path), "-v"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            cwd=iperf_path.parent,
            timeout=5,
        )
    except Exception as exc:
        return IperfToolStatus(False, iperf_path, output=str(exc))
    output = "\n".join(part for part in (getattr(result, "stdout", ""), getattr(result, "stderr", "")) if part)
    match = re.search(r"\biperf\s+(3(?:\.\d+)+)", output, re.IGNORECASE)
    if not match:
        return IperfToolStatus(False, iperf_path, output=output)
    return IperfToolStatus(True, iperf_path, match.group(1), output)
