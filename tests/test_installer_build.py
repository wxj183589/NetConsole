from __future__ import annotations

import inspect
import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from netconsole.core.version import APP_VERSION
from scripts.build import build_edition_installers, build_installer


def test_final_installer_verification_rechecks_frozen_git_state() -> None:
    source = inspect.getsource(build_installer.verify_installer_artifact)

    assert source.index("require_clean_synced_git()") < source.index(
        '"schema": "netconsole.installer-release.v1"'
    )
    assert '_git("rev-parse", "HEAD") != commit' in source


def test_installer_pe_identity_includes_edition_and_feature_profile() -> None:
    source = build_installer.INSTALLER_POLICY_SOURCE.read_text(encoding="utf-8")
    verification = inspect.getsource(build_installer.verify_installer_artifact)

    assert '"InstallerEdition" "${NETCONSOLE_INSTALLER_EDITION}"' in source
    assert (
        '"InstallerFeatureProfile" "${NETCONSOLE_INSTALLER_FEATURE_PROFILE}"'
        in source
    )
    assert 'expected_version_strings["InstallerEdition"]' in verification
    assert 'expected_version_strings["InstallerFeatureProfile"]' in verification


def test_edition_installer_prefers_explicit_pnpm_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pnpm = tmp_path / "pnpm.cmd"
    pnpm.write_text("@echo off\r\n", encoding="utf-8")
    monkeypatch.setenv(build_edition_installers.PNPM_PATH_ENV, str(pnpm))
    monkeypatch.setattr(build_edition_installers.shutil, "which", lambda _name: None)

    assert build_edition_installers._resolve_pnpm_command() == str(pnpm.resolve())


def test_edition_installer_rejects_missing_explicit_pnpm_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "missing-pnpm.cmd"
    monkeypatch.setenv(build_edition_installers.PNPM_PATH_ENV, str(missing))

    with pytest.raises(
        build_edition_installers.EditionInstallerError,
        match=build_edition_installers.PNPM_PATH_ENV,
    ):
        build_edition_installers._resolve_pnpm_command()


def test_policy_source_requires_new_text_and_rejects_old_text() -> None:
    result = build_installer.validate_embedded_policy_source(
        "prefix "
        f"{build_installer.REQUIRED_INSTALLER_TEXT} "
        "kernel32::GetFullPathNameW suffix"
    )

    assert result == {
        "required_policy_text_present": True,
        "forbidden_policy_texts_present": [],
    }

    with pytest.raises(build_installer.InstallerBuildError, match="旧阻止文案"):
        build_installer.validate_embedded_policy_source(
            build_installer.REQUIRED_INSTALLER_TEXT
            + " kernel32::GetFullPathNameW "
            + build_installer.FORBIDDEN_INSTALLER_TEXTS[0]
        )


def test_prepare_identity_uses_unique_commit_artifact_and_source_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    desktop = tmp_path / "apps" / "desktop_electron"
    policy = desktop / "build" / "installer-data-root.nsh"
    policy.parent.mkdir(parents=True)
    policy.write_text(
        build_installer.REQUIRED_INSTALLER_TEXT + "\nkernel32::GetFullPathNameW\n",
        encoding="utf-8",
    )
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
    monkeypatch.setattr(build_installer, "PYTHON_APP_VERSION", "v1.4.3")
    monkeypatch.setattr(build_installer, "_git", lambda *args: "a" * 40)

    manifest = build_installer.prepare_installer_identity(require_synced=False)

    assert manifest["artifact_name"] == "NetConsole-1.4.3-aaaaaaaa-x64-setup.exe"
    assert manifest["standard_artifact_name"] == "NetConsole-1.4.3-x64-setup.exe"
    assert manifest["installer_git_commit"] == "a" * 40
    assert manifest["expected_artifact_absent_before_build"] is True
    assert manifest["standard_artifact_absent_before_build"] is True
    identity = build_installer.INSTALLER_IDENTITY_PATH.read_text(encoding="utf-8")
    assert '!define NETCONSOLE_INSTALLER_GIT_SHORT "aaaaaaaa"' in identity
    assert '!define NETCONSOLE_INSTALLER_EDITION "unscoped"' in identity
    assert manifest["installer_policy_source_sha256"] in identity


def test_prepare_identity_rejects_version_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    desktop = tmp_path / "apps" / "desktop_electron"
    policy = desktop / "build" / "installer-data-root.nsh"
    policy.parent.mkdir(parents=True)
    policy.write_text(
        build_installer.REQUIRED_INSTALLER_TEXT + "\nkernel32::GetFullPathNameW\n",
        encoding="utf-8",
    )
    (desktop / "package.json").write_text(
        json.dumps({"version": "9.9.9"}), encoding="utf-8"
    )

    monkeypatch.setattr(build_installer, "DESKTOP_ROOT", desktop)
    monkeypatch.setattr(build_installer, "INSTALLER_POLICY_SOURCE", policy)
    monkeypatch.setattr(build_installer, "PYTHON_APP_VERSION", APP_VERSION)

    with pytest.raises(build_installer.InstallerBuildError, match="APP_VERSION"):
        build_installer.prepare_installer_identity(require_synced=False)


def test_generated_tree_cleanup_rejects_paths_outside_whitelist(tmp_path: Path) -> None:
    allowed = (tmp_path / "dist",)
    allowed[0].mkdir()

    with pytest.raises(build_installer.InstallerBuildError, match="非白名单"):
        build_installer._remove_generated_tree(tmp_path / "other", allowed=allowed)


def test_nsis_location_validation_accepts_missing_paths_without_creating_them(
    tmp_path: Path,
) -> None:
    if os.name != "nt" or not Path("D:/").is_dir():
        pytest.skip("需要 Windows D: 固定磁盘执行 NSIS 规范化行为测试")

    makensis, plugin_dir = _find_nsis_runtime()
    target_parent = Path("D:/study/test-data/NetConsole") / f"nsis-normalize-{uuid4().hex}"
    missing = target_parent / "missing"
    chinese_missing = target_parent / "网络设备采集数据"
    trailing_missing = f"{missing}\\"
    invalid = target_parent / "bad|name"
    system_drive_missing = (
        Path("C:/NetConsoleTestData") / f"nsis-normalize-{uuid4().hex}"
    )
    for target in (
        missing,
        chinese_missing,
        Path(trailing_missing),
        invalid,
        system_drive_missing,
    ):
        assert not target.exists()

    script = tmp_path / "normalization-test.nsi"
    executable = tmp_path / "normalization-test.exe"
    result_path = tmp_path / "normalization-results.txt"
    normalizer = _extract_nsis_function("NetConsoleNormalizeDataRootPath")
    validator = _extract_nsis_function("NetConsoleValidateDataRootLocation")
    script.write_text(
        rf'''Unicode true
RequestExecutionLevel user
OutFile "{executable}"
SilentInstall silent
!addplugindir "{plugin_dir}"
!include "LogicLib.nsh"
Var NetConsoleDataRoot
Var NetConsoleDataRootProbeResult
Var NetConsoleDataRootProbeErrorCode
Var NetConsoleDataRootProbeErrorSource
Var NetConsoleDataRootNormalized
Var NetConsoleDataRootDriveRoot
Var NetConsoleDataRootDriveType
Var NetConsoleDataRootExists

{normalizer}

{validator}

Function .onInit
  FileOpen $9 "{result_path}" w
  StrCpy $NetConsoleDataRoot "{missing}"
  Call NetConsoleValidateDataRootLocation
  FileWrite $9 "missing|$NetConsoleDataRootProbeResult|$NetConsoleDataRootProbeErrorCode|$NetConsoleDataRootProbeErrorSource|$NetConsoleDataRootNormalized|$NetConsoleDataRootExists$\r$\n"
  StrCpy $NetConsoleDataRoot "{chinese_missing}"
  Call NetConsoleValidateDataRootLocation
  FileWrite $9 "chinese|$NetConsoleDataRootProbeResult|$NetConsoleDataRootProbeErrorCode|$NetConsoleDataRootProbeErrorSource|$NetConsoleDataRootNormalized|$NetConsoleDataRootExists$\r$\n"
  StrCpy $NetConsoleDataRoot "{trailing_missing}"
  Call NetConsoleValidateDataRootLocation
  FileWrite $9 "trailing|$NetConsoleDataRootProbeResult|$NetConsoleDataRootProbeErrorCode|$NetConsoleDataRootProbeErrorSource|$NetConsoleDataRootNormalized|$NetConsoleDataRootExists$\r$\n"
  StrCpy $NetConsoleDataRoot "{invalid}"
  Call NetConsoleValidateDataRootLocation
  FileWrite $9 "invalid|$NetConsoleDataRootProbeResult|$NetConsoleDataRootProbeErrorCode|$NetConsoleDataRootProbeErrorSource|$NetConsoleDataRootNormalized|$NetConsoleDataRootExists$\r$\n"
  StrCpy $NetConsoleDataRoot "{system_drive_missing}"
  Call NetConsoleValidateDataRootLocation
  FileWrite $9 "system|$NetConsoleDataRootProbeResult|$NetConsoleDataRootProbeErrorCode|$NetConsoleDataRootProbeErrorSource|$NetConsoleDataRootNormalized|$NetConsoleDataRootExists$\r$\n"
  FileClose $9
  SetErrorLevel 0
  Quit
FunctionEnd

Section
SectionEnd
''',
        encoding="utf-8-sig",
    )

    compilation = subprocess.run(
        [str(makensis), "/V2", str(script)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    assert compilation.returncode == 0, compilation.stdout + compilation.stderr
    execution = subprocess.run(
        [str(executable), "/S"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    assert execution.returncode == 0, execution.stdout + execution.stderr

    records = {
        values[0]: values[1:]
        for values in (
            line.split("|")
            for line in result_path.read_text(encoding="gb18030").splitlines()
        )
    }
    for label in ("missing", "chinese", "trailing"):
        result, error, source, normalized, exists = records[label]
        assert result == "ok"
        assert error == "0"
        assert source == "无"
        assert normalized.rstrip("\\")
        assert exists == "0"
    assert records["missing"][3].rstrip("\\") == str(missing)
    assert records["chinese"][3].rstrip("\\") == str(chinese_missing)
    assert records["trailing"][3].rstrip("\\") == str(missing)
    assert records["invalid"][:3] == [
        "数据目录包含非法路径字符",
        "NC_PATH_INVALID_CHARACTER",
        "NSIS 参数",
    ]
    assert records["system"][:3] == [
        "当前配置禁止将业务数据存放在系统盘",
        "NC_PATH_SYSTEM_DRIVE",
        "NSIS 参数",
    ]
    for target in (
        missing,
        chinese_missing,
        Path(trailing_missing),
        invalid,
        system_drive_missing,
    ):
        assert not target.exists()


def test_nsis_installer_include_compiles_with_strfunc_calls(tmp_path: Path) -> None:
    if os.name != "nt":
        pytest.skip("需要 Windows NSIS 编译器执行安装器 include 回归")

    makensis, plugin_dir = _find_nsis_runtime()
    build_installer.prepare_installer_identity(require_synced=False)
    installer_include = (
        build_installer.DESKTOP_ROOT / "build" / "installer-data-root.nsh"
    )
    for label, define in (("installer", ""), ("uninstaller", "!define BUILD_UNINSTALLER")):
        script = tmp_path / f"{label}-include-test.nsi"
        executable = tmp_path / f"{label}-include-test.exe"
        script.write_text(
            f'''Unicode true
RequestExecutionLevel user
OutFile "{executable}"
SilentInstall silent
!addplugindir "{plugin_dir}"
{define}
!include "{installer_include}"

Section
SectionEnd
''',
            encoding="utf-8-sig",
        )

        compilation = subprocess.run(
            [str(makensis), "/V2", str(script)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        assert compilation.returncode == 0, compilation.stdout + compilation.stderr
        assert executable.is_file()


def _find_nsis_runtime() -> tuple[Path, Path]:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        pytest.skip("未配置 LOCALAPPDATA，无法执行 NSIS 规范化行为测试")
    cache_root = Path(local_app_data) / "electron-builder" / "Cache"
    compilers = sorted(cache_root.glob("nsis-*/*/Bin/makensis.exe"))
    plugins = sorted(
        (
            *cache_root.glob("nsis-*/*/Plugins/x86-unicode/System.dll"),
            *cache_root.glob("nsis-resources-*/*/plugins/x86-unicode/System.dll"),
        )
    )
    if not compilers or not plugins:
        pytest.skip("缺少 electron-builder NSIS 编译器或 System Unicode 插件")
    return compilers[-1], plugins[-1].parent


def _extract_nsis_function(name: str) -> str:
    source = (
        build_installer.DESKTOP_ROOT / "build" / "installer-data-root.nsh"
    ).read_text(encoding="utf-8")
    start = source.index(f"Function {name}\n")
    end = source.index("\nFunctionEnd", start) + len("\nFunctionEnd")
    return source[start:end]
