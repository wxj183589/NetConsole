from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOL_SOURCE = ROOT / "resources" / "tools" / "windows-x64"
GUARD = ROOT / "scripts" / "build" / "validate_runtime_tools.ps1"
POWERSHELL = shutil.which("powershell.exe")


pytestmark = pytest.mark.skipif(
    POWERSHELL is None, reason="需要 Windows PowerShell 5.1"
)


def _copy_tools(tmp_path: Path) -> Path:
    target = tmp_path / "tools" / "windows-x64"
    shutil.copytree(TOOL_SOURCE, target)
    return target


def _run_guard(tool_root: Path) -> subprocess.CompletedProcess[str]:
    assert POWERSHELL is not None
    return subprocess.run(
        [
            POWERSHELL,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(GUARD),
            "-ToolRoot",
            str(tool_root),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _assert_guard_rejects(tool_root: Path) -> None:
    result = _run_guard(tool_root)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "Runtime tool validation failed" in result.stdout + result.stderr


def _rewrite_json(path: Path, mutate: Callable[[dict[str, object]], None]) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def test_runtime_tool_guard_accepts_the_versioned_local_bundle(tmp_path: Path) -> None:
    result = _run_guard(_copy_tools(tmp_path))

    assert result.returncode == 0, result.stdout + result.stderr
    assert "validated from local files only" in result.stdout


@pytest.mark.parametrize("change", ["extra", "hidden", "missing"])
def test_runtime_tool_guard_rejects_extra_or_missing_files(
    tmp_path: Path, change: str
) -> None:
    tool_root = _copy_tools(tmp_path)
    if change == "extra":
        (tool_root / "iperf3" / "unapproved.dll").write_bytes(b"not approved")
    elif change == "hidden":
        hidden = tool_root / "iperf3" / "hidden-unapproved.dll"
        hidden.write_bytes(b"not approved")
        subprocess.run(["attrib.exe", "+h", str(hidden)], check=True)
    else:
        (tool_root / "fping" / "README.txt").unlink()

    _assert_guard_rejects(tool_root)


@pytest.mark.parametrize(
    "relative_path",
    [
        "iperf3/iperf3.exe",
        "iperf3/licenses/GPL-3.0.txt",
        "iperf3/licenses/README.md",
        "fping/CORRESPONDING_SOURCE.md",
    ],
)
def test_runtime_tool_guard_rejects_binary_license_or_source_tampering(
    tmp_path: Path,
    relative_path: str,
) -> None:
    tool_root = _copy_tools(tmp_path)
    path = tool_root / relative_path
    path.write_bytes(path.read_bytes() + b"\ntampered\n")

    _assert_guard_rejects(tool_root)


@pytest.mark.parametrize("change", ["extra", "missing"])
def test_runtime_tool_guard_rejects_inexact_provenance_sets(
    tmp_path: Path, change: str
) -> None:
    tool_root = _copy_tools(tmp_path)
    provenance = tool_root / "iperf3" / "SOURCE_PROVENANCE.json"

    def mutate(payload: dict[str, object]) -> None:
        sources = payload["upstream_sources"]
        assert isinstance(sources, list)
        if change == "extra":
            sources.append({"name": "unapproved", "version": "0"})
        else:
            sources.pop()

    _rewrite_json(provenance, mutate)
    _assert_guard_rejects(tool_root)


def test_runtime_tool_guard_rejects_fixed_source_identity_tampering(
    tmp_path: Path,
) -> None:
    tool_root = _copy_tools(tmp_path)
    provenance = tool_root / "fping" / "SOURCE_PROVENANCE.json"

    def mutate(payload: dict[str, object]) -> None:
        sources = payload["upstream_sources"]
        assert isinstance(sources, list)
        source = sources[0]
        assert isinstance(source, dict)
        source["tag_commit"] = "0" * 40

    _rewrite_json(provenance, mutate)
    _assert_guard_rejects(tool_root)


@pytest.mark.parametrize(
    "change",
    [
        "extra_root",
        "extra_build",
        "verification_date",
        "boolean_string",
        "numeric_string",
    ],
)
def test_runtime_tool_guard_rejects_inexact_provenance_properties(
    tmp_path: Path,
    change: str,
) -> None:
    tool_root = _copy_tools(tmp_path)
    provenance = tool_root / "fping" / "SOURCE_PROVENANCE.json"

    def mutate(payload: dict[str, object]) -> None:
        if change == "extra_root":
            payload["unapproved"] = True
        elif change == "verification_date":
            payload["verified_at"] = "2099-01-01"
        elif change == "numeric_string":
            sources = payload["upstream_sources"]
            assert isinstance(sources, list)
            source = sources[1]
            assert isinstance(source, dict)
            source["source_archive_size"] = "9312760"
        elif change == "boolean_string":
            build = payload["build"]
            assert isinstance(build, dict)
            build["network_required_during_product_packaging"] = "False"
        else:
            build = payload["build"]
            assert isinstance(build, dict)
            build["unapproved"] = True

    _rewrite_json(provenance, mutate)
    _assert_guard_rejects(tool_root)


def test_agent_windows_build_runs_the_same_guard_before_and_after_copy() -> None:
    text = (ROOT / "apps" / "agent" / "scripts" / "build_windows.bat").read_text(
        encoding="utf-8"
    )
    invocation = (
        'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%TOOL_GUARD%" '
        "-ToolRoot "
    )

    assert text.count(invocation) == 2
    precheck = text.index(invocation + '"%TOOL_SOURCE%"')
    delivery_cleanup = text.index('if exist "%DELIVERY%" rmdir')
    copy_tools = text.index('xcopy /e /i /y "%TOOL_SOURCE%\\%%T"')
    postcheck = text.index(invocation + '"%DELIVERY%\\tools\\windows-x64"')
    collector_copy = text.index(
        'copy /y "%BUILD_ROOT%\\mr_collector\\dist\\netconsole-mr-collector.exe"'
    )

    assert precheck < delivery_cleanup < copy_tools < postcheck < collector_copy
    assert "[WARN] MR Collector build failed" not in text
    assert 'if not exist "%BUILD_ROOT%\\mr_collector\\dist\\netconsole-mr-collector.exe"' in text
    assert "Agent delivery cannot be completed" in text


def test_agent_mr_collector_prefers_project_venv_pyinstaller() -> None:
    text = (
        ROOT / "apps" / "agent" / "mr_collector_py" / "build_windows.bat"
    ).read_text(encoding="utf-8")

    assert 'if not defined NETCONSOLE_PYTHON_EXE set "NETCONSOLE_PYTHON_EXE=%REPO_ROOT%\\.venv\\Scripts\\python.exe"' in text
    assert 'set "PYTHON_EXE=%NETCONSOLE_PYTHON_EXE%"' in text
    assert 'set "PYINSTALLER_CONFIG_DIR=%BUILD_ROOT%\\pyinstaller-cache"' in text
    assert '"%PYTHON_EXE%" -m PyInstaller --version' in text
    assert '"%PYTHON_EXE%" -m PyInstaller --clean --onefile' in text
    assert text.index('set "PYINSTALLER_CONFIG_DIR=') < text.index('"%PYTHON_EXE%" -m PyInstaller --clean')
    assert text.index('if exist "%PYTHON_EXE%"') < text.index("where pyinstaller")
