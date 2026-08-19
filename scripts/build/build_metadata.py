from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


BUILD_METADATA_ENV = "NETCONSOLE_BUILD_METADATA_JSON"
BUILD_METADATA_FIELDS = frozenset(
    {
        "app_version",
        "git_commit_full",
        "git_commit_short",
        "build_time_utc",
        "build_dirty",
        "build_source",
        "frontend_commit",
        "backend_commit",
        "product_version",
        "build_number",
        "file_version",
        "published",
    }
)


class BuildMetadataError(RuntimeError):
    pass


def collect_build_metadata(
    root: Path,
    *,
    app_version: str,
    release: bool,
    build_time_utc: str | None = None,
    build_number: int | None = None,
    published: bool | None = None,
) -> dict[str, Any]:
    project_root = Path(root).resolve()
    full = _git(project_root, "rev-parse", "HEAD")
    dirty = bool(
        _git(project_root, "status", "--porcelain", "--untracked-files=normal")
    )
    if release and dirty:
        raise BuildMetadataError("正式 release 构建要求 Git 工作区干净")
    timestamp = build_time_utc or datetime.now(UTC).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )
    normalized_version = str(app_version).removeprefix("v")
    selected_build_number = _build_number(build_number)
    payload = {
        "app_version": str(app_version),
        "product_version": normalized_version,
        "build_number": selected_build_number,
        "file_version": f"{normalized_version}.{selected_build_number}",
        "git_commit_full": full,
        "git_commit_short": full[:8],
        "build_time_utc": timestamp,
        "build_dirty": dirty,
        "build_source": "git-release" if release else "git-development",
        "frontend_commit": full,
        "backend_commit": full,
        "published": bool(release) if published is None else bool(published),
    }
    validate_build_metadata(payload, release=release)
    return payload


def validate_build_metadata(payload: dict[str, Any], *, release: bool) -> None:
    missing = sorted(BUILD_METADATA_FIELDS.difference(payload))
    if missing:
        raise BuildMetadataError(f"构建元数据缺少字段：{', '.join(missing)}")
    full = str(payload.get("git_commit_full") or "")
    if len(full) != 40 or any(char not in "0123456789abcdef" for char in full.casefold()):
        raise BuildMetadataError("构建元数据 Git commit 不是完整 40 位 SHA")
    if str(payload.get("git_commit_short") or "") != full[:8]:
        raise BuildMetadataError("构建元数据短提交号与完整提交号不一致")
    if any(str(payload.get(key) or "") != full for key in ("frontend_commit", "backend_commit")):
        raise BuildMetadataError("Frontend、Backend 与源码提交号不一致")
    if not str(payload.get("build_time_utc") or "").endswith("Z"):
        raise BuildMetadataError("构建时间必须使用 ISO 8601 UTC")
    if release and bool(payload.get("build_dirty")):
        raise BuildMetadataError("正式 release 构建不能标记为 dirty")
    product_version = str(payload.get("product_version") or "")
    if not re.fullmatch(r"\d+\.\d+\.\d+", product_version):
        raise BuildMetadataError("ProductVersion 必须是三段正式版本号")
    if str(payload.get("app_version") or "").removeprefix("v") != product_version:
        raise BuildMetadataError("ProductVersion 与 APP_VERSION 不一致")
    try:
        build_number = int(payload.get("build_number"))
    except (TypeError, ValueError) as exc:
        raise BuildMetadataError("Build Number 必须是非负整数") from exc
    if build_number < 0 or build_number > 65535:
        raise BuildMetadataError("Build Number 必须位于 0..65535")
    if str(payload.get("file_version") or "") != f"{product_version}.{build_number}":
        raise BuildMetadataError("FileVersion 与 ProductVersion/Build Number 不一致")
    if not isinstance(payload.get("published"), bool):
        raise BuildMetadataError("published 必须是布尔值")


def encode_build_metadata(payload: dict[str, Any]) -> str:
    validate_build_metadata(payload, release=False)
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def decode_build_metadata(value: str) -> dict[str, Any]:
    try:
        payload = json.loads(str(value or ""))
    except json.JSONDecodeError as exc:
        raise BuildMetadataError("构建元数据环境变量不是有效 JSON") from exc
    if not isinstance(payload, dict):
        raise BuildMetadataError("构建元数据环境变量不是对象")
    result = dict(payload)
    validate_build_metadata(result, release=False)
    return result


def write_build_metadata(path: Path, payload: dict[str, Any]) -> Path:
    validate_build_metadata(payload, release=False)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def _git(root: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise BuildMetadataError(f"无法读取 Git 构建事实：{' '.join(args)}") from exc


def _build_number(value: int | None) -> int:
    raw = os.environ.get("NETCONSOLE_BUILD_NUMBER", "0") if value is None else value
    try:
        result = int(raw)
    except (TypeError, ValueError) as exc:
        raise BuildMetadataError("NETCONSOLE_BUILD_NUMBER 必须是非负整数") from exc
    if result < 0 or result > 65535:
        raise BuildMetadataError("NETCONSOLE_BUILD_NUMBER 必须位于 0..65535")
    return result


__all__ = [
    "BUILD_METADATA_ENV",
    "BUILD_METADATA_FIELDS",
    "BuildMetadataError",
    "collect_build_metadata",
    "decode_build_metadata",
    "encode_build_metadata",
    "validate_build_metadata",
    "write_build_metadata",
]
