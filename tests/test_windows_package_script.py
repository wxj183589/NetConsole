from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_windows_package_script_reuses_the_formal_release_entry() -> None:
    script_path = ROOT / "scripts" / "build" / "package_windows.ps1"
    script = script_path.read_text(encoding="utf-8-sig")

    assert script_path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert 'Resolve-NativeCommand "git.exe"' in script
    assert 'Resolve-NativeCommand "node.exe"' in script
    assert 'Resolve-NativeCommand "pnpm.cmd"' in script
    assert '".venv\\Scripts\\python.exe"' in script
    assert '@("status", "--porcelain", "--untracked-files=all")' in script
    assert '@("rev-parse", "@{upstream}")' in script
    assert '@("-m", "pip", "check")' in script
    assert script.count('@("install", "--frozen-lockfile")') == 2
    assert script.count('@("test")') == 2
    assert 'Invoke-Native $pnpmPath @("run", $packageScript) $desktopRoot' in script


def test_windows_package_script_rechecks_the_final_artifact() -> None:
    script = (
        ROOT / "scripts" / "build" / "package_windows.ps1"
    ).read_text(encoding="utf-8-sig")

    assert '"*.exe.release.json"' in script
    assert '"netconsole.installer-release.v1"' in script
    assert "installer_git_commit -eq $head" in script
    assert "packaged_dirty -ne $false" in script
    assert 'real_windows_install_status -ne "PENDING"' in script
    assert "Get-FileHash -LiteralPath $artifactPath -Algorithm SHA256" in script
    assert "artifact.Length -ne [int64]$releaseManifest.artifact_size" in script


def test_windows_package_launcher_only_calls_the_powershell_orchestrator() -> None:
    launcher = (
        ROOT / "scripts" / "build" / "package_windows.bat"
    ).read_text(encoding="utf-8").casefold()

    assert "powershell.exe" in launcher
    assert "package_windows.ps1" in launcher
    assert "%*" in launcher
    for forbidden in ("git reset", "git clean", "git push", "pnpm package"):
        assert forbidden not in launcher
