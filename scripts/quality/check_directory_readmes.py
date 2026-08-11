"""检查 Git 跟踪的受维护目录是否有直接 README.md。"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable


ROOT = Path(__file__).resolve().parents[2]
README_NAME = "README.md"

GENERATED_DIRECTORY_NAMES = frozenset(
    {
        "node_modules",
        "build",
        "dist",
        "release",
        "coverage",
        "__pycache__",
        ".pytest_cache",
        "generated",
    }
)
SOURCE_BUILD_DIRECTORIES = frozenset({"scripts/build", "src/netconsole/build"})
PURE_FIXTURE_SUFFIXES = frozenset(
    {".csv", ".json", ".log", ".pcap", ".txt", ".xml", ".yaml", ".yml"}
)
BINARY_SUFFIXES = frozenset(
    {
        ".7z",
        ".bin",
        ".cab",
        ".class",
        ".dll",
        ".exe",
        ".gif",
        ".ico",
        ".jpg",
        ".jpeg",
        ".jar",
        ".mp3",
        ".mp4",
        ".msi",
        ".otf",
        ".pdb",
        ".pdf",
        ".png",
        ".pyc",
        ".so",
        ".ttf",
        ".wasm",
        ".webp",
        ".woff",
        ".woff2",
        ".zip",
    }
)
THIRD_PARTY_TOOL_ROOTS = frozenset(
    {
        "resources/tools/windows-x64/fping",
        "resources/tools/windows-x64/iperf3",
    }
)
PROTECTED_DIRECTORY_ROOTS = frozenset({"docs/investigations"})
REQUIRED_MAJOR_SECTIONS = (
    "## 用途与边界",
    "## 主要入口",
    "## 依赖关系",
    "## 数据与状态",
    "## 测试与修改",
    "## 生成与清理",
    "## 相关文档",
)
MAJOR_DIRECTORIES = frozenset(
    {
        "apps",
        "apps/agent/internal",
        "apps/desktop_electron",
        "apps/desktop_renderer",
        "apps/desktop_renderer/src",
        "apps/desktop_renderer/src/api",
        "apps/desktop_renderer/src/components",
        "apps/desktop_renderer/src/views",
        "config",
        "config/profiles",
        "docs/architecture",
        "docs/development",
        "resources",
        "scripts",
        "scripts/build",
        "scripts/quality",
        "src/netconsole/adapters",
        "src/netconsole/application",
        "src/netconsole/assets",
        "src/netconsole/backend",
        "src/netconsole/core",
        "src/netconsole/models/api",
        "src/netconsole/parsers",
        "src/netconsole/repositories",
        "src/netconsole/services/ac",
        "src/netconsole/services/agent",
        "src/netconsole/services/ap_identity",
        "src/netconsole/services/export",
        "src/netconsole/services/job_center",
        "src/netconsole/services/network_tools",
        "src/netconsole/services/rail_transit",
        "src/netconsole/services/traffic",
        "src/netconsole/storage",
        "src/netconsole/utils",
        "tests/smoke",
        "tools/windows-x64",
    }
)


@dataclass(frozen=True)
class ReadmeReport:
    tracked_file_count: int
    maintained_directories: tuple[str, ...]
    missing_directories: tuple[str, ...]
    missing_sections: tuple[tuple[str, str], ...]
    excluded_files: tuple[tuple[str, str], ...]


def _normalize(path: str) -> str:
    return path.replace("\\", "/").strip("/")


def _parts(path: str) -> tuple[str, ...]:
    return PurePosixPath(path).parts


def _is_generated_directory(path: str) -> bool:
    parts = _parts(path)
    directory_parts = parts[:-1]
    normalized = "/".join(parts)
    if normalized in SOURCE_BUILD_DIRECTORIES or normalized.startswith(
        tuple(f"{item}/" for item in SOURCE_BUILD_DIRECTORIES)
    ):
        return False
    return any(part.casefold() in GENERATED_DIRECTORY_NAMES for part in directory_parts)


def _is_skill_package(path: str) -> bool:
    parts = _parts(path)
    return len(parts) >= 3 and parts[:2] == (".agents", "skills")


def _is_pure_fixture(path: str) -> bool:
    parts = _parts(path)
    return len(parts) >= 3 and parts[:2] == ("tests", "fixtures") and Path(path).suffix.lower() in PURE_FIXTURE_SUFFIXES


def _is_third_party_tool(path: str) -> bool:
    return any(path == root or path.startswith(f"{root}/") for root in THIRD_PARTY_TOOL_ROOTS)


def _is_protected_directory(path: str) -> bool:
    return any(path == root or path.startswith(f"{root}/") for root in PROTECTED_DIRECTORY_ROOTS)


def _is_binary(path: str) -> bool:
    return Path(path).suffix.lower() in BINARY_SUFFIXES


def _exclusion_reason(path: str) -> str | None:
    if _is_generated_directory(path):
        return "generated/dependency directory"
    if _is_skill_package(path):
        return ".agents skill package (SKILL.md contract)"
    if _is_pure_fixture(path):
        return "pure-data test fixture"
    if _is_third_party_tool(path):
        return "third-party tool internal directory"
    if _is_protected_directory(path):
        return "protected investigation material"
    if _is_binary(path):
        return "binary file"
    return None


def scan_tracked_files(tracked_files: Iterable[str], root: Path) -> ReadmeReport:
    """根据已提供的 Git 跟踪路径生成检查报告。

    未跟踪路径不会进入目录集合；README 本身只通过当前文件系统检查是否存在，
    这样新补充的文档可以在暂存前先验证，而不会把其他 Worker 的未跟踪源码纳入基线。
    """

    normalized_files = tuple(sorted({_normalize(path) for path in tracked_files if path}))
    excluded: list[tuple[str, str]] = []
    maintained_files: list[str] = []
    for path in normalized_files:
        reason = _exclusion_reason(path)
        if reason:
            excluded.append((path, reason))
        else:
            maintained_files.append(path)

    directories: set[str] = set()
    for path in maintained_files:
        path_parts = _parts(path)
        for index in range(1, len(path_parts)):
            directories.add("/".join(path_parts[:index]))

    maintained_directories = tuple(sorted(directories))
    missing = tuple(
        directory
        for directory in maintained_directories
        if not (root / Path(directory) / README_NAME).is_file()
    )
    missing_sections: list[tuple[str, str]] = []
    for directory in sorted(MAJOR_DIRECTORIES.intersection(directories)):
        readme = root / Path(directory) / README_NAME
        if not readme.is_file():
            continue
        content = readme.read_text(encoding="utf-8")
        missing_sections.extend(
            (directory, heading)
            for heading in REQUIRED_MAJOR_SECTIONS
            if heading not in content
        )
    return ReadmeReport(
        tracked_file_count=len(normalized_files),
        maintained_directories=maintained_directories,
        missing_directories=missing,
        missing_sections=tuple(missing_sections),
        excluded_files=tuple(excluded),
    )


def tracked_files_from_git(root: Path) -> tuple[str, ...]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return tuple(item for item in result.stdout.decode("utf-8").split("\0") if item)


def scan_project(root: Path = ROOT) -> ReadmeReport:
    return scan_tracked_files(tracked_files_from_git(root), root)


def format_report(report: ReadmeReport) -> str:
    lines = [
        "目录 README 门禁",
        f"Git 跟踪文件: {report.tracked_file_count}",
        f"受维护目录: {len(report.maintained_directories)}",
        f"缺失 README: {len(report.missing_directories)}",
        f"重大目录缺失小节: {len(report.missing_sections)}",
        "",
        "固定排除:",
        "- 依赖/生成目录: node_modules、build、dist、release、coverage、__pycache__、.pytest_cache、generated（规范源码 scripts/build 与 src/netconsole/build 保留）",
        "- .agents/skills/<skill>: SKILL.md 是该 Skill 包契约",
        "- tests/fixtures 下的纯数据文件目录",
        "- resources/tools/windows-x64/fping 与 iperf3 的第三方内部目录",
        "- 已识别的二进制文件",
    ]
    if report.missing_directories:
        lines.extend(["", "缺失目录:"])
        lines.extend(f"- {directory} -> {directory}/README.md" for directory in report.missing_directories)
    if report.missing_sections:
        lines.extend(["", "重大目录缺失小节:"])
        lines.extend(f"- {directory}: {heading}" for directory, heading in report.missing_sections)
    if not report.missing_directories and not report.missing_sections:
        lines.extend(["", "结果: 通过"])
    return "\n".join(lines)


def main() -> int:
    try:
        report = scan_project()
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"目录 README 门禁无法执行: {exc}", file=sys.stderr)
        return 2
    print(format_report(report))
    return 1 if report.missing_directories or report.missing_sections else 0


if __name__ == "__main__":
    raise SystemExit(main())
