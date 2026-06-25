from __future__ import annotations

from pathlib import Path

from netconsole.core.version import APP_VERSION
from project.build_nuitka_release import build_nuitka_command, read_version_info


ROOT = Path(__file__).resolve().parents[1]


def test_nuitka_release_reads_unified_version() -> None:
    version = read_version_info()

    assert version.app_name == "NetConsole"
    assert version.app_version == APP_VERSION == "v1.3.1"
    assert version.zip_name == "NetConsole_v1.3.1_nuitka.zip"


def test_nuitka_command_uses_standalone_and_required_resources() -> None:
    command_text = " ".join(build_nuitka_command(read_version_info(), "8"))

    assert "--standalone" in command_text
    assert "--onefile" not in command_text
    assert "main.py" in command_text
    assert "netconsole\\ui\\icons" in command_text
    assert "netconsole\\docs\\changelog.md" in command_text
    assert "tools/iperf/iperf3.exe=tools/iperf/iperf3.exe" in command_text
    assert "tools/fping_v3/Fping_v3.exe=tools/fping_v3/Fping_v3.exe" in command_text
    assert "tools=tools" in command_text
    assert "data\\sites" not in command_text
    assert "data\\runtime" not in command_text
    assert "data\\shared" not in command_text


def test_nuitka_scripts_do_not_call_publish_flow() -> None:
    script_text = (ROOT / "build_nuitka_release.bat").read_text(encoding="utf-8")
    helper_text = (ROOT / "project" / "build_nuitka_release.py").read_text(encoding="utf-8")
    combined = f"{script_text}\n{helper_text}".lower()

    forbidden_tokens = (
        "project\\release.py",
        "project/release.py",
        "git commit",
        "git tag",
        "git push",
        "git remote",
        "v1.2.",
        "network_toolkit",
        "tasks_v2",
    )
    for token in forbidden_tokens:
        assert token not in combined
