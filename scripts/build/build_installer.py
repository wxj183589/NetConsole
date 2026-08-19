from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from netconsole.core.version import APP_VERSION as PYTHON_APP_VERSION

ROOT = Path(__file__).resolve().parents[2]
DESKTOP_ROOT = ROOT / "apps" / "desktop_electron"
ELECTRON_DIST = ROOT / "dist" / "electron"
BUILD_TEMP_ROOT = ROOT / "dist" / "_build"
INSTALLER_BUILD_ROOT = DESKTOP_ROOT / "dist" / "installer-build"
INSTALLER_IDENTITY_PATH = INSTALLER_BUILD_ROOT / "installer-build-identity.nsh"
INSTALLER_BUILD_MANIFEST_PATH = INSTALLER_BUILD_ROOT / "installer-build.json"
INSTALLER_POLICY_SOURCE = DESKTOP_ROOT / "build" / "installer-data-root.nsh"

POLICY_VERSION = "allow-nonconflicting-files-v3"
REQUIRED_INSTALLER_TEXT = (
    "目录包含现有普通文件：安装器将保留这些文件；"
    "仅在 NetConsole 必需路径发生真实冲突时停止。"
)
FORBIDDEN_INSTALLER_TEXTS = (
    "所选目录非空且不是已识别的 NetConsole 数据根",
    "请选择空目录或已有 NetConsole 数据根",
    "安装器不会创建嵌套目录",
)
EMBEDDED_MANIFEST_NAME = "netconsole-installer-build.json"
EMBEDDED_SOURCE_NAME = "netconsole-installer-data-root.nsh"


class InstallerBuildError(RuntimeError):
    pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build and verify the NetConsole NSIS installer"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prepare-identity", action="store_true")
    mode.add_argument("--verify", type=Path)
    args = parser.parse_args()

    try:
        if args.prepare_identity:
            manifest = prepare_installer_identity(require_synced=True)
            print(f"INSTALLER_BUILD_ID={manifest['installer_build_id']}")
            print(f"INSTALLER_ARTIFACT_NAME={manifest['artifact_name']}")
            return 0
        if args.verify is not None:
            result = verify_installer_artifact(args.verify)
            _print_result(result)
            return 0
        result = build_installer()
        _print_result(result)
        return 0
    except InstallerBuildError as exc:
        print("INSTALLER BUILD FAILED", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 1


def build_installer() -> dict[str, Any]:
    require_clean_synced_git()
    clean_installer_outputs()

    temp_root = BUILD_TEMP_ROOT / f"electron-builder-{time.time_ns()}"
    temp_root.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy()
    env["TEMP"] = str(temp_root)
    env["TMP"] = str(temp_root)

    pnpm = shutil.which("pnpm.cmd") or shutil.which("pnpm")
    node = shutil.which("node.exe") or shutil.which("node")
    if pnpm is None or node is None:
        raise InstallerBuildError("构建安装器需要项目环境中的 pnpm 和 Node.js")

    _run([pnpm, "run", "package:prepare"], cwd=DESKTOP_ROOT, env=env)
    manifest = _read_json(INSTALLER_BUILD_MANIFEST_PATH)
    artifact_name = str(manifest.get("artifact_name") or "")
    if not artifact_name:
        raise InstallerBuildError("安装器身份清单缺少 artifact_name")
    artifact = ELECTRON_DIST / artifact_name
    standard = ELECTRON_DIST / str(manifest.get("standard_artifact_name") or "")
    if artifact.exists() or standard.exists():
        raise InstallerBuildError("electron-builder 启动前安装包已存在，拒绝复用旧制品")

    _run(
        [
            pnpm,
            "exec",
            "electron-builder",
            "--win",
            "nsis",
            "--x64",
            f"--config.win.artifactName={artifact_name}",
        ],
        cwd=DESKTOP_ROOT,
        env=env,
    )
    if standard.exists():
        raise InstallerBuildError(f"本轮唯一测试包不得生成固定名称：{standard.name}")
    _run([node, "scripts/package-smoke.mjs"], cwd=DESKTOP_ROOT, env=env)
    return verify_installer_artifact(artifact)


def prepare_installer_identity(*, require_synced: bool) -> dict[str, Any]:
    if require_synced:
        require_clean_synced_git()
    package = _read_json(DESKTOP_ROOT / "package.json")
    app_version = str(package.get("version") or "")
    if not app_version:
        raise InstallerBuildError("Electron package.json 缺少 version")
    expected_version = PYTHON_APP_VERSION.removeprefix("v")
    if app_version != expected_version:
        raise InstallerBuildError(
            "Electron package.json version 与 Python APP_VERSION 不一致："
            f"{app_version!r} != {expected_version!r}"
        )

    commit = _git("rev-parse", "HEAD")
    short = commit[:8]
    now = datetime.now(UTC)
    build_time = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    build_number = _read_build_number()
    product_version = app_version
    file_version = f"{product_version}.{build_number}"
    build_id = f"netconsole-{app_version}-{short}-{now.strftime('%Y%m%dT%H%M%SZ')}"
    artifact_name = f"NetConsole-{app_version}.{build_number}-{short}-x64-setup.exe"
    standard_name = f"NetConsole-{app_version}-x64-setup.exe"
    policy_bytes = INSTALLER_POLICY_SOURCE.read_bytes()
    policy_text = policy_bytes.decode("utf-8")
    validate_embedded_policy_source(policy_text)

    manifest = {
        "schema": "netconsole.installer-build.v1",
        "app_version": app_version,
        "product_version": product_version,
        "build_number": build_number,
        "file_version": file_version,
        "published": os.environ.get("NETCONSOLE_PUBLISHED") == "1",
        "installer_git_commit": commit,
        "installer_git_short": short,
        "installer_build_time_utc": build_time,
        "installer_build_started_ns": time.time_ns(),
        "installer_build_id": build_id,
        "installer_policy": POLICY_VERSION,
        "installer_policy_source": "apps/desktop_electron/build/installer-data-root.nsh",
        "installer_policy_source_sha256": hashlib.sha256(policy_bytes).hexdigest(),
        "installer_policy_source_mtime_ns": INSTALLER_POLICY_SOURCE.stat().st_mtime_ns,
        "required_policy_text": REQUIRED_INSTALLER_TEXT,
        "artifact_name": artifact_name,
        "standard_artifact_name": standard_name,
        "expected_artifact_absent_before_build": not (
            ELECTRON_DIST / artifact_name
        ).exists(),
        "standard_artifact_absent_before_build": not (
            ELECTRON_DIST / standard_name
        ).exists(),
    }
    if not manifest["expected_artifact_absent_before_build"]:
        raise InstallerBuildError(f"唯一安装包在构建前已存在：{artifact_name}")
    if not manifest["standard_artifact_absent_before_build"]:
        raise InstallerBuildError(f"固定名称安装包在构建前仍存在：{standard_name}")

    INSTALLER_BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(INSTALLER_BUILD_MANIFEST_PATH, manifest)
    identity = "\n".join(
        (
            f'!define NETCONSOLE_INSTALLER_APP_VERSION "{app_version}"',
            f'!define NETCONSOLE_INSTALLER_GIT_COMMIT "{commit}"',
            f'!define NETCONSOLE_INSTALLER_GIT_SHORT "{short}"',
            f'!define NETCONSOLE_INSTALLER_BUILD_TIME "{build_time}"',
            f'!define NETCONSOLE_INSTALLER_BUILD_ID "{build_id}"',
            '!define NETCONSOLE_INSTALLER_EDITION "unscoped"',
            '!define NETCONSOLE_INSTALLER_FEATURE_PROFILE "unscoped"',
            f'!define NETCONSOLE_INSTALLER_POLICY "{POLICY_VERSION}"',
            f'!define NETCONSOLE_INSTALLER_POLICY_SHA256 "{manifest["installer_policy_source_sha256"]}"',
            f'!define NETCONSOLE_INSTALLER_MANIFEST_PATH "{_nsis_path(INSTALLER_BUILD_MANIFEST_PATH)}"',
            f'!define NETCONSOLE_INSTALLER_POLICY_SOURCE_PATH "{_nsis_path(INSTALLER_POLICY_SOURCE)}"',
            "",
        )
    )
    _write_text_atomic(INSTALLER_IDENTITY_PATH, identity)
    return manifest


def verify_installer_artifact(path: Path) -> dict[str, Any]:
    artifact = Path(path).resolve()
    if not artifact.is_file():
        raise InstallerBuildError(f"最终安装器不存在：{artifact}")
    manifest = _read_json(INSTALLER_BUILD_MANIFEST_PATH)
    expected_name = str(manifest.get("artifact_name") or "")
    if artifact.name != expected_name:
        raise InstallerBuildError(
            f"安装包文件名不匹配：{artifact.name} != {expected_name}"
        )
    if _git("rev-parse", "HEAD") != manifest.get("installer_git_commit"):
        raise InstallerBuildError("外层 Installer commit 与当前 Git HEAD 不一致")
    if not manifest.get("expected_artifact_absent_before_build"):
        raise InstallerBuildError("身份清单未证明唯一安装包在构建前不存在")
    if not manifest.get("standard_artifact_absent_before_build"):
        raise InstallerBuildError("身份清单未证明固定名称安装包在构建前不存在")

    artifact_stat = artifact.stat()
    if artifact_stat.st_mtime_ns <= int(manifest["installer_policy_source_mtime_ns"]):
        raise InstallerBuildError("最终 EXE 生成时间不晚于 installer-data-root.nsh")
    if artifact_stat.st_mtime_ns <= int(manifest["installer_build_started_ns"]):
        raise InstallerBuildError("最终 EXE 生成时间不晚于本轮构建开始时间")

    first_hash = _sha256(artifact)
    second_hash = _sha256(artifact)
    if first_hash != second_hash:
        raise InstallerBuildError("最终 EXE 两次 SHA-256 读取结果不一致")

    version_strings = _read_pe_version_strings(artifact)
    expected_version_strings = {
        "InstallerGitCommit": str(manifest["installer_git_commit"]),
        "InstallerGitShort": str(manifest["installer_git_short"]),
        "InstallerBuildTime": str(manifest["installer_build_time_utc"]),
        "InstallerBuildId": str(manifest["installer_build_id"]),
        "InstallerPolicy": str(manifest["installer_policy"]),
        "InstallerPolicySHA256": str(manifest["installer_policy_source_sha256"]),
    }
    if manifest.get("edition"):
        expected_version_strings["InstallerEdition"] = str(
            manifest["edition"]
        )
        expected_version_strings["InstallerFeatureProfile"] = str(
            manifest.get("feature_profile") or ""
        )
    for key, expected in expected_version_strings.items():
        if version_strings.get(key) != expected:
            raise InstallerBuildError(f"最终 EXE 版本资源 {key} 不匹配")

    seven_zip = discover_full_7zip()
    listing = _run_capture(
        [seven_zip, "l", "-slt", "-tNsis", str(artifact)], encoding="utf-8"
    )
    if "SubType = NSIS-3 Unicode" not in listing:
        raise InstallerBuildError("最终 EXE 不是 NSIS-3 Unicode 安装器")

    embedded_manifest_bytes = _extract_stdout(
        seven_zip, artifact, rf"$PLUGINSDIR\{EMBEDDED_MANIFEST_NAME}"
    )
    embedded_source_bytes = _extract_stdout(
        seven_zip, artifact, rf"$PLUGINSDIR\{EMBEDDED_SOURCE_NAME}"
    )
    embedded_manifest = json.loads(embedded_manifest_bytes.decode("utf-8"))
    if embedded_manifest != manifest:
        raise InstallerBuildError("最终 EXE 内嵌 Installer 身份清单与构建清单不一致")
    source_sha = hashlib.sha256(embedded_source_bytes).hexdigest()
    if source_sha != manifest.get("installer_policy_source_sha256"):
        raise InstallerBuildError("最终 EXE 内嵌数据根脚本 SHA-256 不匹配")
    if source_sha != _sha256(INSTALLER_POLICY_SOURCE):
        raise InstallerBuildError("最终 EXE 内嵌数据根脚本不是当前源码")
    embedded_source = embedded_source_bytes.decode("utf-8")
    scan = validate_embedded_policy_source(embedded_source)

    backend_metadata, frontend_metadata = _read_nested_build_metadata(
        seven_zip, artifact
    )
    commit = str(manifest["installer_git_commit"])
    if str(backend_metadata.get("git_commit_full") or "") != commit:
        raise InstallerBuildError(
            "最终 EXE 内 Backend commit 与 Installer commit 不一致"
        )
    if str(frontend_metadata.get("git_commit_full") or "") != commit:
        raise InstallerBuildError(
            "最终 EXE 内 Frontend commit 与 Installer commit 不一致"
        )
    if backend_metadata.get("build_dirty") is not False:
        raise InstallerBuildError("最终 EXE 内 Backend 标记为 dirty")
    if frontend_metadata.get("build_dirty") is not False:
        raise InstallerBuildError("最终 EXE 内 Frontend 标记为 dirty")
    for nested in (backend_metadata, frontend_metadata):
        if str(nested.get("product_version") or "") != str(manifest["product_version"]):
            raise InstallerBuildError("最终 EXE 内 ProductVersion 与 Installer 不一致")
        if int(nested.get("build_number", -1)) != int(manifest["build_number"]):
            raise InstallerBuildError("最终 EXE 内 Build Number 与 Installer 不一致")
        if str(nested.get("file_version") or "") != str(manifest["file_version"]):
            raise InstallerBuildError("最终 EXE 内 FileVersion 与 Installer 不一致")
        if bool(nested.get("published", False)) is not bool(manifest.get("published", False)):
            raise InstallerBuildError("最终 EXE 内 published 状态与 Installer 不一致")

    require_clean_synced_git()
    if _git("rev-parse", "HEAD") != commit:
        raise InstallerBuildError("最终校验时 Git HEAD 已偏离冻结的 Installer commit")

    result = {
        "schema": "netconsole.installer-release.v1",
        "version": manifest["app_version"],
        "product_version": manifest["product_version"],
        "build_number": manifest["build_number"],
        "file_version": manifest["file_version"],
        "published": bool(manifest.get("published", False)),
        "artifact_name": artifact.name,
        "artifact_sha256": first_hash,
        "artifact_size": artifact_stat.st_size,
        "installer_git_commit": commit,
        "build_commit": commit,
        "installer_git_short": manifest["installer_git_short"],
        "installer_build_time_utc": manifest["installer_build_time_utc"],
        "build_timestamp": manifest["installer_build_time_utc"],
        "installer_build_id": manifest["installer_build_id"],
        "installer_policy": manifest["installer_policy"],
        "installer_policy_source_sha256": source_sha,
        "backend_commit": backend_metadata["git_commit_full"],
        "frontend_commit": frontend_metadata["git_commit_full"],
        "packaged_dirty": False,
        "nsis_subtype": "NSIS-3 Unicode",
        "required_policy_text_present": scan["required_policy_text_present"],
        "forbidden_policy_texts_present": scan["forbidden_policy_texts_present"],
        "artifact_newer_than_policy_source": True,
        "artifact_absent_before_build": True,
        "hash_recheck_matches": True,
        "verified_at_utc": datetime.now(UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "real_windows_install_status": "PENDING",
        "server_installation_status": "PENDING",
    }
    _write_json_atomic(artifact.with_suffix(".exe.release.json"), result)
    return result


def validate_embedded_policy_source(source: str) -> dict[str, Any]:
    if REQUIRED_INSTALLER_TEXT not in source:
        raise InstallerBuildError("安装器数据根脚本缺少允许普通文件的新文案")
    found = [text for text in FORBIDDEN_INSTALLER_TEXTS if text in source]
    if found:
        raise InstallerBuildError(f"安装器数据根脚本仍包含旧阻止文案：{found[0]}")
    if "kernel32::GetFullPathNameW" not in source:
        raise InstallerBuildError("安装器数据根脚本未使用 Win32 GetFullPathNameW")
    if "GetFullPathName $NetConsoleDataRootNormalized" in source:
        raise InstallerBuildError("安装器数据根脚本仍使用 NSIS 内置 GetFullPathName")
    return {
        "required_policy_text_present": True,
        "forbidden_policy_texts_present": found,
    }


def clean_installer_outputs() -> None:
    allowed = (
        ELECTRON_DIST.resolve(),
        (DESKTOP_ROOT / "dist").resolve(),
        BUILD_TEMP_ROOT.resolve(),
    )
    for path in allowed:
        _remove_generated_tree(path, allowed=allowed)


def _remove_generated_tree(path: Path, *, allowed: tuple[Path, ...]) -> None:
    resolved = path.resolve()
    if resolved not in allowed or ROOT.resolve() not in resolved.parents:
        raise InstallerBuildError(f"拒绝清理非白名单构建目录：{resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)


def require_clean_synced_git() -> None:
    status = _git("status", "--porcelain", "--untracked-files=normal")
    if status:
        raise InstallerBuildError("正式安装器要求 Git 工作区干净")
    head = _git("rev-parse", "HEAD")
    try:
        upstream = _git("rev-parse", "@{upstream}")
    except InstallerBuildError as exc:
        raise InstallerBuildError("正式安装器要求当前分支已设置远端 upstream") from exc
    if upstream != head:
        raise InstallerBuildError("正式安装器必须在最终提交推送到 upstream 后构建")


def discover_full_7zip() -> Path:
    candidates: list[Path] = []
    configured = os.environ.get("NETCONSOLE_7Z")
    if configured:
        candidates.append(Path(configured))
    located = shutil.which("7z.exe") or shutil.which("7z")
    if located:
        candidates.append(Path(located))
    for base in (
        os.environ.get("ProgramW6432"),
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
    ):
        if base:
            candidates.append(Path(base) / "7-Zip" / "7z.exe")
    candidates.extend(
        (
            Path(r"C:\Program Files\AMD\AMDInstallManager\7z.exe"),
            Path(r"C:\Program Files\NVIDIA Corporation\NVIDIA App\7z.exe"),
        )
    )
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        result = subprocess.run(
            [str(resolved), "i"],
            capture_output=True,
            timeout=15,
            check=False,
        )
        output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
        if result.returncode == 0 and "Nsis" in output:
            return resolved
    raise InstallerBuildError(
        "最终 EXE Gate 需要支持 NSIS handler 的完整 7-Zip；可通过 NETCONSOLE_7Z 显式指定 7z.exe"
    )


def _read_nested_build_metadata(
    seven_zip: Path, artifact: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    BUILD_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="installer-verify-", dir=BUILD_TEMP_ROOT
    ) as temporary:
        temp_root = Path(temporary)
        _run(
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
            raise InstallerBuildError("最终 EXE 缺少内嵌 app-64.7z")
        backend = _extract_archive_json(
            seven_zip,
            app_archive,
            r"resources\backend\_internal\netconsole\assets\runtime\build-metadata.json",
        )
        frontend = _extract_archive_json(
            seven_zip,
            app_archive,
            r"resources\backend\_internal\netconsole\assets\desktop_renderer\desktop-renderer-build-meta.json",
        )
        return backend, frontend


def _read_build_number() -> int:
    raw = os.environ.get("NETCONSOLE_BUILD_NUMBER", "0")
    try:
        value = int(raw)
    except ValueError as exc:
        raise InstallerBuildError("NETCONSOLE_BUILD_NUMBER 必须是非负整数") from exc
    if value < 0 or value > 65535:
        raise InstallerBuildError("NETCONSOLE_BUILD_NUMBER 必须位于 0..65535")
    return value


def _extract_stdout(seven_zip: Path, artifact: Path, member: str) -> bytes:
    result = subprocess.run(
        [str(seven_zip), "e", "-so", "-tNsis", str(artifact), member],
        capture_output=True,
        timeout=120,
        check=False,
    )
    if result.returncode != 0 or not result.stdout:
        error = result.stderr.decode("utf-8", errors="replace").strip()
        raise InstallerBuildError(f"无法从最终 EXE 提取 {member}：{error}")
    return result.stdout


def _extract_archive_json(
    seven_zip: Path, archive: Path, member: str
) -> dict[str, Any]:
    result = subprocess.run(
        [str(seven_zip), "e", "-so", str(archive), member],
        capture_output=True,
        timeout=120,
        check=False,
    )
    if result.returncode != 0 or not result.stdout:
        raise InstallerBuildError(f"安装包应用载荷缺少 {member}")
    payload = json.loads(result.stdout.decode("utf-8"))
    if not isinstance(payload, dict):
        raise InstallerBuildError(f"安装包应用载荷 {member} 不是 JSON 对象")
    return payload


def _read_pe_version_strings(path: Path) -> dict[str, str]:
    try:
        import pefile
    except ImportError as exc:
        raise InstallerBuildError("最终 EXE Gate 需要构建依赖 pefile") from exc

    pe = pefile.PE(str(path), fast_load=False)
    try:
        result: dict[str, str] = {}
        for group in getattr(pe, "FileInfo", []) or []:
            for entry in group if isinstance(group, list) else [group]:
                for table in getattr(entry, "StringTable", []) or []:
                    for key, value in table.entries.items():
                        result[key.decode("utf-8")] = value.decode("utf-8")
        return result
    finally:
        pe.close()


def _print_result(result: dict[str, Any]) -> None:
    for key in (
        "artifact_name",
        "artifact_sha256",
        "artifact_size",
        "installer_git_commit",
        "installer_build_id",
        "installer_policy_source_sha256",
        "backend_commit",
        "frontend_commit",
        "packaged_dirty",
        "nsis_subtype",
        "real_windows_install_status",
    ):
        print(f"{key.upper()}={result[key]}")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InstallerBuildError(f"无法读取 JSON：{path}") from exc
    if not isinstance(payload, dict):
        raise InstallerBuildError(f"JSON 顶层必须是对象：{path}")
    return payload


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    _write_text_atomic(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{time.time_ns()}.tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _nsis_path(path: Path) -> str:
    value = str(path.resolve())
    if '"' in value or "$" in value:
        raise InstallerBuildError(f"NSIS 构建路径包含不支持的字符：{path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(ROOT), *args],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=20,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise InstallerBuildError(f"Git 命令失败：{' '.join(args)}") from exc


def _run(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> None:
    try:
        subprocess.run(
            command,
            cwd=cwd or ROOT,
            env=env,
            check=True,
            timeout=1800,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise InstallerBuildError(
            f"构建命令失败：{subprocess.list2cmdline(command)}"
        ) from exc


def _run_capture(command: list[Path | str], *, encoding: str) -> str:
    try:
        return subprocess.run(
            [str(item) for item in command],
            check=True,
            capture_output=True,
            text=True,
            encoding=encoding,
            errors="replace",
            timeout=120,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise InstallerBuildError(
            f"制品检查命令失败：{subprocess.list2cmdline([str(item) for item in command])}"
        ) from exc


if __name__ == "__main__":
    raise SystemExit(main())
