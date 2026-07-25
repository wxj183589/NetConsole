from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.build import build_installer


def test_policy_source_requires_new_text_and_rejects_old_text() -> None:
    result = build_installer.validate_embedded_policy_source(
        f"prefix {build_installer.REQUIRED_INSTALLER_TEXT} suffix"
    )

    assert result == {
        "required_policy_text_present": True,
        "forbidden_policy_texts_present": [],
    }

    with pytest.raises(build_installer.InstallerBuildError, match="旧阻止文案"):
        build_installer.validate_embedded_policy_source(
            build_installer.REQUIRED_INSTALLER_TEXT
            + build_installer.FORBIDDEN_INSTALLER_TEXTS[0]
        )


def test_prepare_identity_uses_unique_commit_artifact_and_source_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    desktop = tmp_path / "apps" / "desktop_electron"
    policy = desktop / "build" / "installer-data-root.nsh"
    policy.parent.mkdir(parents=True)
    policy.write_text(build_installer.REQUIRED_INSTALLER_TEXT, encoding="utf-8")
    (desktop / "package.json").write_text(
        json.dumps({"version": "1.4.3"}), encoding="utf-8"
    )
    electron_dist = tmp_path / "dist" / "electron"
    identity_root = desktop / "dist" / "installer-build"

    monkeypatch.setattr(build_installer, "DESKTOP_ROOT", desktop)
    monkeypatch.setattr(build_installer, "ELECTRON_DIST", electron_dist)
    monkeypatch.setattr(build_installer, "INSTALLER_BUILD_ROOT", identity_root)
    monkeypatch.setattr(
        build_installer,
        "INSTALLER_IDENTITY_PATH",
        identity_root / "installer-build-identity.nsh",
    )
    monkeypatch.setattr(
        build_installer,
        "INSTALLER_BUILD_MANIFEST_PATH",
        identity_root / "installer-build.json",
    )
    monkeypatch.setattr(build_installer, "INSTALLER_POLICY_SOURCE", policy)
    monkeypatch.setattr(build_installer, "_git", lambda *args: "a" * 40)

    manifest = build_installer.prepare_installer_identity(require_synced=False)

    assert manifest["artifact_name"] == "NetConsole-1.4.3-aaaaaaaa-x64-setup.exe"
    assert manifest["standard_artifact_name"] == "NetConsole-1.4.3-x64-setup.exe"
    assert manifest["installer_git_commit"] == "a" * 40
    assert manifest["expected_artifact_absent_before_build"] is True
    assert manifest["standard_artifact_absent_before_build"] is True
    identity = build_installer.INSTALLER_IDENTITY_PATH.read_text(encoding="utf-8")
    assert '!define NETCONSOLE_INSTALLER_GIT_SHORT "aaaaaaaa"' in identity
    assert manifest["installer_policy_source_sha256"] in identity


def test_generated_tree_cleanup_rejects_paths_outside_whitelist(tmp_path: Path) -> None:
    allowed = (tmp_path / "dist",)
    allowed[0].mkdir()

    with pytest.raises(build_installer.InstallerBuildError, match="非白名单"):
        build_installer._remove_generated_tree(tmp_path / "other", allowed=allowed)
