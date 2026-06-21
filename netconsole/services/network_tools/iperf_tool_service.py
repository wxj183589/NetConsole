from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from netconsole.core.paths import PathResolver
from netconsole.core.settings import SettingsStore


@dataclass(frozen=True)
class IperfToolStatus:
    found: bool
    path: Path | None = None
    version: str = ""
    output: str = ""


def find_iperf_tool(paths: PathResolver, custom_path: str | Path | None = None) -> Path | None:
    candidates: list[Path] = []
    if custom_path:
        candidates.append(Path(custom_path))
    try:
        configured = SettingsStore(paths).get_value("network_tools/iperf_path", "")
    except Exception:
        configured = ""
    if configured:
        candidates.append(Path(str(configured)))
    candidates.extend(
        [
            paths.app_root / "tools" / "iperf" / "iperf3.exe",
            paths.project_dir / "tools" / "iperf" / "iperf3.exe",
        ]
    )
    path_candidate = shutil.which("iperf3.exe") or shutil.which("iperf3")
    if path_candidate:
        candidates.append(Path(path_candidate))
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate
        if resolved.exists() and resolved.is_file():
            return resolved
    return None


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
            timeout=5,
        )
    except Exception as exc:
        return IperfToolStatus(False, iperf_path, output=str(exc))
    output = "\n".join(part for part in (getattr(result, "stdout", ""), getattr(result, "stderr", "")) if part)
    match = re.search(r"\biperf\s+(3(?:\.\d+)+)", output, re.IGNORECASE)
    if not match:
        return IperfToolStatus(False, iperf_path, output=output)
    return IperfToolStatus(True, iperf_path, match.group(1), output)
