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
    assert "backend_commit -ne $head" in script
    assert "frontend_commit -ne $head" in script
    assert "$finalDirty" in script
    assert "$finalHead -ne $head" in script
    assert "$finalUpstream -ne $head" in script
    assert 'real_windows_install_status -ne "PENDING"' in script
    assert 'server_installation_status -ne "PENDING"' in script
    assert 'package_smoke -ne "PASS"' in script
    assert "build_commit -ne $releaseManifest.installer_git_commit" in script
    assert "build_timestamp -ne $releaseManifest.installer_build_time_utc" in script
    assert "Get-Sha256Hex -Path $artifactPath" in script
    assert "[System.Security.Cryptography.SHA256]::Create()" in script
    assert "artifact.Length -ne [int64]$releaseManifest.artifact_size" in script


def test_windows_package_script_scopes_parallel_gate_to_web_tests() -> None:
    script = (
        ROOT / "scripts" / "build" / "package_windows.ps1"
    ).read_text(encoding="utf-8-sig")

    web_step = script.index('Write-Step "运行 Web 测试"')
    capture_gate = script.index(
        "$hadVitestParallelGate = Test-Path Env:NETCONSOLE_VITEST_PARALLEL_GATE"
    )
    save_gate = script.index(
        "$previousVitestParallelGate = $env:NETCONSOLE_VITEST_PARALLEL_GATE"
    )
    enable_gate = script.index('$env:NETCONSOLE_VITEST_PARALLEL_GATE = "1"')
    web_test = script.index('Invoke-Native $pnpmPath @("test") $rendererRoot')
    finally_gate = script.index("finally {", web_test)
    restore_gate = script.index(
        "$env:NETCONSOLE_VITEST_PARALLEL_GATE = $previousVitestParallelGate"
    )
    remove_gate = script.index(
        "Remove-Item Env:NETCONSOLE_VITEST_PARALLEL_GATE -ErrorAction SilentlyContinue"
    )
    electron_step = script.index('Write-Step "运行 Electron 测试"')
    electron_test = script.index('Invoke-Native $pnpmPath @("test") $desktopRoot')

    assert web_step < capture_gate < save_gate < enable_gate < web_test
    assert web_test < finally_gate < restore_gate < electron_step < electron_test
    assert web_test < finally_gate < remove_gate < electron_step < electron_test


def test_local_release_publish_rechecks_source_and_inner_commits() -> None:
    script = (
        ROOT / "scripts" / "build" / "package_local.ps1"
    ).read_text(encoding="utf-8-sig")

    assert "$manifest.backend_commit -ne $Head" in script
    assert "$manifest.frontend_commit -ne $Head" in script
    assert "$finalDirty" in script
    assert "$finalHead -ne $head" in script
    assert "$finalUpstream -ne $head" in script
    assert "$publishDirty" in script
    assert script.index("$publishDirty") < script.index(
        "Publish-VerifiedArtifacts -ProjectRoot"
    )


def test_windows_package_launcher_only_calls_the_powershell_orchestrator() -> None:
    launcher = (
        ROOT / "scripts" / "build" / "package_windows.bat"
    ).read_text(encoding="utf-8").casefold()

    assert "powershell.exe" in launcher
    assert "package_windows.ps1" in launcher
    assert "%*" in launcher
    for forbidden in ("git reset", "git clean", "git push", "pnpm package"):
        assert forbidden not in launcher


def test_package_smoke_uses_the_same_default_edition_as_package_prepare() -> None:
    package_prepare = (
        ROOT / "apps" / "desktop_electron" / "scripts" / "package.mjs"
    ).read_text(encoding="utf-8")
    package_smoke = (
        ROOT / "apps" / "desktop_electron" / "scripts" / "package-smoke.mjs"
    ).read_text(encoding="utf-8")

    expected_default = "process.env.NETCONSOLE_BUILD_EDITION || 'full'"
    assert expected_default in package_prepare
    assert expected_default in package_smoke
    assert "const buildEdition =" in package_smoke
    assert "const edition = buildEdition" in package_smoke
