from __future__ import annotations

import ctypes
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from netconsole.core.paths import PathResolver
from netconsole.services.tool_path_resolver import resolve_tool_path


SEM_FAILCRITICALERRORS = 0x0001
SEM_NOGPFAULTERRORBOX = 0x0002
SEM_NOOPENFILEERRORBOX = 0x8000


@dataclass(frozen=True)
class ToolSmokeResult:
    name: str
    path: Path
    ok: bool
    output: str


def set_windows_quiet_error_mode() -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.kernel32.SetErrorMode(  # type: ignore[attr-defined]
            SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX
        )
    except Exception:
        return


def run_tool_smoke_tests(paths: PathResolver | None = None) -> list[ToolSmokeResult]:
    set_windows_quiet_error_mode()
    paths = paths or PathResolver()
    checks = (
        ("fping_v3", ("-v",), ("Fast pinger version 3.00", "Wouter Dhondt")),
        ("iperf3", ("-v",), ("iperf 3.",)),
    )
    results: list[ToolSmokeResult] = []
    failures: list[str] = []
    for name, args, markers in checks:
        tool_path = resolve_tool_path(name, paths)
        if tool_path is None:
            failures.append(f"{name}: executable not found")
            continue
        result = _run_one(name, tool_path, args, markers)
        results.append(result)
        if not result.ok:
            failures.append(f"{name}: {result.output.strip() or 'version command failed'}")
    if failures:
        raise RuntimeError("External tool smoke test failed:\n" + "\n".join(failures))
    return results


def _run_one(name: str, tool_path: Path, args: tuple[str, ...], markers: tuple[str, ...]) -> ToolSmokeResult:
    try:
        completed = subprocess.run(
            [str(tool_path), *args],
            cwd=tool_path.parent,
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except OSError as exc:
        return ToolSmokeResult(name, tool_path, False, str(exc))
    output = f"{completed.stdout or ''}\n{completed.stderr or ''}"
    ok = any(marker in output for marker in markers)
    return ToolSmokeResult(name, tool_path, ok, output)
