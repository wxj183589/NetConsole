from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from scripts.build import build_installer as installer
from scripts.build.prepare_electron_edition import (
    BUILD_EDITIONS,
    CUSTOMER_PASSWORD_ENV,
    EditionPreparationError,
    prepare_electron_edition,
)

EDITION_SELECTIONS = (*BUILD_EDITIONS, "both")
EDITION_LABELS = {"full": "Full", "customer": "Customer"}
BACKEND_STAGING = installer.DESKTOP_ROOT / "dist" / "package-resources" / "backend"
PNPM_PATH_ENV = "NETCONSOLE_PNPM_PATH"


class EditionInstallerError(RuntimeError):
    pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build verified NetConsole Full and Customer NSIS installers"
    )
    parser.add_argument("--editions", choices=EDITION_SELECTIONS, default="both")
    args = parser.parse_args()
    try:
        results = build_edition_installers(args.editions)
        for result in results:
            print(f"{result['edition'].upper()}_ARTIFACT={result['artifact_path']}")
            print(f"{result['edition'].upper()}_SHA256={result['artifact_sha256']}")
        return 0
    except (EditionInstallerError, EditionPreparationError, installer.InstallerBuildError) as exc:
        print("EDITION INSTALLER BUILD FAILED")
        print(str(exc))
        return 1


def build_edition_installers(selection: str) -> list[dict[str, Any]]:
    editions = _selected_editions(selection)
    customer_password = os.environ.get(CUSTOMER_PASSWORD_ENV, "")
    if "customer" in editions and not customer_password:
        raise EditionInstallerError(
            f"构建客户版前必须设置环境变量 {CUSTOMER_PASSWORD_ENV}"
        )

    installer.require_clean_synced_git()
    installer.clean_installer_outputs()
    pnpm = _resolve_pnpm_command()
    node = shutil.which("node.exe") or shutil.which("node")
    if pnpm is None or node is None:
        raise EditionInstallerError("构建安装器需要项目环境中的 pnpm 和 Node.js")

    initial_edition = editions[0]
    prepare_env = os.environ.copy()
    prepare_env["NETCONSOLE_BUILD_EDITION"] = initial_edition
    if initial_edition == "customer":
        prepare_env[CUSTOMER_PASSWORD_ENV] = customer_password
    else:
        prepare_env.pop(CUSTOMER_PASSWORD_ENV, None)
    _configure_temporary_directory(prepare_env, suffix="prepare")
    installer._run(
        [pnpm, "run", "package:prepare"],
        cwd=installer.DESKTOP_ROOT,
        env=prepare_env,
    )
    base_manifest = installer._read_json(installer.INSTALLER_BUILD_MANIFEST_PATH)

    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="netconsole-edition-installers-") as staging:
        staging_root = Path(staging)
        for edition in editions:
            prepare_electron_edition(
                BACKEND_STAGING,
                edition=edition,
                customer_password=customer_password if edition == "customer" else None,
            )
            manifest = _write_edition_identity(base_manifest, edition)
            _clear_electron_output()
            artifact = installer.ELECTRON_DIST / str(manifest["artifact_name"])
            standard = installer.ELECTRON_DIST / str(
                manifest["standard_artifact_name"]
            )
            if artifact.exists() or standard.exists():
                raise EditionInstallerError(
                    f"electron-builder 启动前版本制品已存在：{edition}"
                )

            build_env = os.environ.copy()
            build_env["NETCONSOLE_BUILD_EDITION"] = edition
            build_env.pop(CUSTOMER_PASSWORD_ENV, None)
            _configure_temporary_directory(build_env, suffix=edition)
            installer._run(
                [
                    pnpm,
                    "exec",
                    "electron-builder",
                    "--win",
                    "nsis",
                    "--x64",
                    f"--config.win.artifactName={artifact.name}",
                ],
                cwd=installer.DESKTOP_ROOT,
                env=build_env,
            )
            installer._run(
                [node, "scripts/package-smoke.mjs"],
                cwd=installer.DESKTOP_ROOT,
                env=build_env,
            )
            result = installer.verify_installer_artifact(artifact)
            result.update(
                _verify_packaged_edition(
                    artifact,
                    edition=edition,
                    customer_password=(
                        customer_password if edition == "customer" else ""
                    ),
                )
            )
            release_path = artifact.with_suffix(".exe.release.json")
            installer._write_json_atomic(release_path, result)
            staged_artifact = staging_root / artifact.name
            staged_release = staging_root / release_path.name
            shutil.copy2(artifact, staged_artifact)
            shutil.copy2(release_path, staged_release)
            results.append(
                {
                    **result,
                    "artifact_path": str(
                        (installer.ELECTRON_DIST / artifact.name).resolve()
                    ),
                }
            )

        _clear_electron_output()
        installer.ELECTRON_DIST.mkdir(parents=True, exist_ok=True)
        for path in staging_root.iterdir():
            shutil.copy2(path, installer.ELECTRON_DIST / path.name)

    return results


def _resolve_pnpm_command() -> str | None:
    configured = os.environ.get(PNPM_PATH_ENV, "").strip()
    if configured:
        candidate = Path(configured)
        if not candidate.is_file():
            raise EditionInstallerError(
                f"{PNPM_PATH_ENV} 指向的 pnpm 不存在：{candidate}"
            )
        return str(candidate.resolve())
    return shutil.which("pnpm.cmd") or shutil.which("pnpm")


def _selected_editions(selection: str) -> tuple[str, ...]:
    if selection == "both":
        return ("full", "customer")
    if selection not in BUILD_EDITIONS:
        raise EditionInstallerError(f"不支持的版本选择：{selection}")
    return (selection,)


def _write_edition_identity(
    base_manifest: dict[str, Any], edition: str
) -> dict[str, Any]:
    manifest = copy.deepcopy(base_manifest)
    app_version = str(manifest.get("app_version") or "")
    commit = str(manifest.get("installer_git_commit") or "")
    short = str(manifest.get("installer_git_short") or "")
    build_time = str(manifest.get("installer_build_time_utc") or "")
    if not all((app_version, commit, short, build_time)):
        raise EditionInstallerError("基础 Installer 身份清单不完整")

    label = EDITION_LABELS[edition]
    profile = edition
    artifact_name = f"NetConsole-{label}-{app_version}-{short}-x64-setup.exe"
    standard_name = f"NetConsole-{label}-{app_version}-x64-setup.exe"
    manifest.update(
        {
            "schema": "netconsole.installer-build.v2",
            "edition": edition,
            "feature_profile": profile,
            "installer_build_id": (
                f"{manifest['installer_build_id']}-{edition}"
            ),
            "artifact_name": artifact_name,
            "standard_artifact_name": standard_name,
            "expected_artifact_absent_before_build": not (
                installer.ELECTRON_DIST / artifact_name
            ).exists(),
            "standard_artifact_absent_before_build": not (
                installer.ELECTRON_DIST / standard_name
            ).exists(),
        }
    )
    if not manifest["expected_artifact_absent_before_build"]:
        raise EditionInstallerError(f"版本安装包在构建前已存在：{artifact_name}")
    if not manifest["standard_artifact_absent_before_build"]:
        raise EditionInstallerError(f"固定名称版本安装包仍存在：{standard_name}")

    identity = "\n".join(
        (
            f'!define NETCONSOLE_INSTALLER_APP_VERSION "{app_version}"',
            f'!define NETCONSOLE_INSTALLER_GIT_COMMIT "{commit}"',
            f'!define NETCONSOLE_INSTALLER_GIT_SHORT "{short}"',
            f'!define NETCONSOLE_INSTALLER_BUILD_TIME "{build_time}"',
            f'!define NETCONSOLE_INSTALLER_BUILD_ID "{manifest["installer_build_id"]}"',
            f'!define NETCONSOLE_INSTALLER_POLICY "{manifest["installer_policy"]}"',
            f'!define NETCONSOLE_INSTALLER_POLICY_SHA256 "{manifest["installer_policy_source_sha256"]}"',
            f'!define NETCONSOLE_INSTALLER_EDITION "{edition}"',
            f'!define NETCONSOLE_INSTALLER_FEATURE_PROFILE "{profile}"',
            f'!define NETCONSOLE_INSTALLER_MANIFEST_PATH "{installer._nsis_path(installer.INSTALLER_BUILD_MANIFEST_PATH)}"',
            f'!define NETCONSOLE_INSTALLER_POLICY_SOURCE_PATH "{installer._nsis_path(installer.INSTALLER_POLICY_SOURCE)}"',
            "",
        )
    )
    installer._write_json_atomic(installer.INSTALLER_BUILD_MANIFEST_PATH, manifest)
    installer._write_text_atomic(installer.INSTALLER_IDENTITY_PATH, identity)
    return manifest


def _verify_packaged_edition(
    artifact: Path,
    *,
    edition: str,
    customer_password: str,
) -> dict[str, Any]:
    seven_zip = installer.discover_full_7zip()
    installer.BUILD_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f"edition-verify-{edition}-",
        dir=installer.BUILD_TEMP_ROOT,
    ) as temporary:
        temp_root = Path(temporary)
        installer._run(
            [
                str(seven_zip),
                "e",
                "-y",
                "-tNsis",
                str(artifact),
                f"-o{temp_root}",
                r"$PLUGINSDIR\app-64.7z",
            ]
        )
        app_archive = temp_root / "app-64.7z"
        if not app_archive.is_file():
            raise EditionInstallerError("版本安装包缺少内嵌 app-64.7z")
        build_info = installer._extract_archive_json(
            seven_zip,
            app_archive,
            r"resources\backend\_internal\netconsole\assets\runtime\build_info.json",
        )
        feature_flags = installer._extract_archive_json(
            seven_zip,
            app_archive,
            r"resources\backend\_internal\netconsole\assets\runtime\feature_flags.json",
        )

    if build_info.get("edition") != edition:
        raise EditionInstallerError("最终安装包的 Backend edition 不匹配")
    if build_info.get("feature_profile") != edition:
        raise EditionInstallerError("最终安装包的 Backend feature_profile 不匹配")
    if feature_flags.get("profile") != edition:
        raise EditionInstallerError("最终安装包的 Feature Profile 不匹配")
    serialized = json.dumps(build_info, ensure_ascii=False)
    if customer_password and customer_password in serialized:
        raise EditionInstallerError("最终安装包身份文件包含明文维护密码")
    admin_unlock_configured = bool(build_info.get("admin_unlock_enabled"))
    if edition == "customer" and not admin_unlock_configured:
        raise EditionInstallerError("最终客户版未配置维护密码哈希")
    if edition == "full" and admin_unlock_configured:
        raise EditionInstallerError("最终完整版不应配置客户维护密码")
    return {
        "edition": edition,
        "feature_profile": edition,
        "admin_unlock_configured": admin_unlock_configured,
        "edition_payload_verified": True,
    }


def _configure_temporary_directory(env: dict[str, str], *, suffix: str) -> None:
    temp_root = installer.BUILD_TEMP_ROOT / f"electron-builder-{suffix}-{time.time_ns()}"
    temp_root.mkdir(parents=True, exist_ok=False)
    env["TEMP"] = str(temp_root)
    env["TMP"] = str(temp_root)


def _clear_electron_output() -> None:
    target = installer.ELECTRON_DIST.resolve()
    if installer.ROOT.resolve() not in target.parents:
        raise EditionInstallerError(f"拒绝清理非仓库构建目录：{target}")
    if target.exists():
        shutil.rmtree(target)


if __name__ == "__main__":
    raise SystemExit(main())
