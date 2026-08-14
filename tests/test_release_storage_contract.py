from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_packaging_uses_dist_only_for_regeneratable_outputs() -> None:
    package_script = (
        ROOT / "apps" / "desktop_electron" / "scripts" / "package.mjs"
    ).read_text(encoding="utf-8")

    assert "'dist', '_build', 'backend-release'" in package_script
    assert "'dist', `v${version}`" not in package_script


def test_formal_release_has_one_external_durable_root() -> None:
    local_script = (ROOT / "scripts" / "build" / "package_local.ps1").read_text(
        encoding="utf-8-sig"
    )

    assert '$script:DurableReleaseRoot = "D:\\study\\release\\NetConsole"' in local_script
    assert 'Join-Path $releaseRoot $AppVersion' in local_script
    assert 'Join-Path $ProjectRoot "dist\\release"' not in local_script
    assert "C:\\NetConsoleRelease" not in local_script
    assert "D:\\NetConsoleRelease" not in local_script
    assert "Get-Sha256Hex -Path $destination" in local_script
    assert "installer_git_commit -eq $Head" in local_script


def test_release_metadata_keeps_package_and_server_status_separate() -> None:
    installer = (ROOT / "scripts" / "build" / "build_installer.py").read_text(
        encoding="utf-8"
    )
    editions = (
        ROOT / "scripts" / "build" / "build_edition_installers.py"
    ).read_text(encoding="utf-8")

    assert '"server_installation_status": "PENDING"' in installer
    assert '"version": manifest["app_version"]' in installer
    assert '"build_commit": commit' in installer
    assert '"build_timestamp": manifest["installer_build_time_utc"]' in installer
    assert 'result["package_smoke"] = "PASS"' in editions
