from __future__ import annotations

from pathlib import Path

from netconsole.backend.web_build import frontend_build_id, read_frontend_build_meta


def validate_web_frontend_meta(
    frontend_root: Path,
    *,
    expected_version: str,
    expected_commit: str,
    expected_build_time: str | None = None,
    expected_dirty: bool | None = None,
) -> None:
    if not (frontend_root / "index.html").is_file():
        raise ValueError("Web 前端缺少 dist/index.html，请重新构建 Web 资源。")
    metadata = read_frontend_build_meta(frontend_root)
    required = {
        "app_version",
        "git_commit",
        "build_time",
        "navigation_schema_version",
        "build_id",
        "git_commit_full",
        "git_commit_short",
        "build_time_utc",
        "build_dirty",
        "build_source",
        "frontend_commit",
        "backend_commit",
    }
    missing = sorted(required.difference(metadata))
    if missing:
        raise ValueError(f"Web 前端构建元数据不完整：{', '.join(missing)}")
    expected_identity = (
        f"{expected_commit}-dirty" if expected_dirty else expected_commit
    )
    expected_id = f"{expected_version}+{expected_identity}"
    if (
        str(metadata["app_version"]) != expected_version
        or str(metadata["git_commit"]) != expected_identity
        or str(metadata["git_commit_full"]) != expected_commit
        or str(metadata["frontend_commit"]) != expected_commit
        or str(metadata["backend_commit"]) != expected_commit
        or frontend_build_id(metadata) != expected_id
    ):
        raise ValueError(
            "Web 前端构建身份与后端不一致，"
            f"expected={expected_id} actual={frontend_build_id(metadata) or 'missing'}"
        )
    if not str(metadata["build_time"]).strip() or str(metadata["build_time"]) != str(metadata["build_time_utc"]):
        raise ValueError("Web 前端构建时间为空，请重新构建 Web 资源。")
    if expected_build_time is not None and str(metadata["build_time_utc"]) != expected_build_time:
        raise ValueError("Web 前端构建时间与统一构建元数据不一致。")
    if expected_dirty is not None and bool(metadata["build_dirty"]) is not expected_dirty:
        raise ValueError("Web 前端 dirty 状态与统一构建元数据不一致。")
    if str(metadata["git_commit_short"]) != expected_commit[:8]:
        raise ValueError("Web 前端短提交号与完整提交号不一致。")
    schema_version = metadata["navigation_schema_version"]
    if not isinstance(schema_version, int) or isinstance(schema_version, bool) or schema_version < 1:
        raise ValueError("Web 前端导航 schema 版本无效，请重新构建 Web 资源。")


__all__ = ["validate_web_frontend_meta"]
