"""Check the NetConsole Workspace and repository layout without changing files."""

from __future__ import annotations

import argparse
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


ROOT = Path(__file__).absolute().parents[1]
PROTECTED_DATA_ROOT = Path("D:/NetConsoleData")
WORKSPACE_NAME = "NetConsole-Workspace"
WORKSPACE_TOP_LEVEL = frozenset(
    {
        "NetConsole",
        "NetConsole-DevStatus",
        "worktrees",
        "test-data",
        "release",
        "reports",
        "temp",
        "archives",
        "backups",
        ".idea",
        "diagnostic",
        "field-validation-recovery-20260920-full",
        "field-validation-recovery-20260920-full-fixed",
    }
)
REPOSITORY_TOP_LEVEL = frozenset(
    {
        ".agents",
        ".codex",
        ".github",
        ".git",
        ".idea",
        ".local",
        ".local-reports",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "apps",
        "config",
        "docs",
        "dist",
        "resources",
        "scripts",
        "src",
        "tests",
        "tools",
    }
)
CONTAINER_LINK_CHECKS = ("worktrees", "test-data", "release", "reports", "temp", "archives", "backups")
INDEPENDENT_REPOSITORIES = {"NetConsole-Next": "https://github.com/wxj183589/NetConsole-Next.git"}
CONTAINER_CHILDREN = {
    "reports": frozenset({"build", "diagnostic", "maintenance", "tests", "workspace-cleanup"}),
    # git-pack-quarantine is a retained historical maintenance container; new
    # temporary work must use one of the task-scoped categories.
    "temp": frozenset({"analysis", "build", "git-pack-quarantine", "installer-test"}),
}
PROHIBITED_ROOT_NAMES = frozenset(
    {
        "package-worktrees",
        "devstatus-worktrees",
        "netconsole-copy",
        "netconsole-new",
        "netconsole-test",
        "netconsole-backup",
        "new-release",
        "test-data-copy",
        "temp-build-new",
    }
)
REPARSE_POINT_ATTRIBUTE = 0x400


@dataclass(frozen=True)
class Violation:
    kind: str
    path: str
    rule: str
    expected: str
    action: str


def _absolute(path: Path) -> Path:
    """Make a lexical absolute path without resolving links or junctions."""

    return Path(os.path.abspath(os.fspath(path)))


def _is_protected_data_path(path: Path) -> bool:
    candidate = _absolute(path).as_posix().casefold().rstrip("/")
    protected = _absolute(PROTECTED_DATA_ROOT).as_posix().casefold().rstrip("/")
    return candidate == protected or candidate.startswith(f"{protected}/")


def _is_reparse_point(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        attributes = int(getattr(path.lstat(), "st_file_attributes", 0))
    except OSError:
        return False
    return bool(attributes & REPARSE_POINT_ATTRIBUTE)


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))


def _inside(path: Path, parent: Path) -> bool:
    candidate = os.path.normcase(os.path.abspath(path))
    boundary = os.path.normcase(os.path.abspath(parent))
    try:
        return os.path.commonpath((candidate, boundary)) == boundary
    except ValueError:
        return False


def _direct_children(root: Path) -> tuple[Path, ...]:
    return tuple(sorted(root.iterdir(), key=lambda item: item.name.casefold()))


def _is_registered_independent_repository(path: Path) -> bool:
    """Recognize only the recorded independent project at its exact boundary."""

    expected_remote = INDEPENDENT_REPOSITORIES.get(path.name)
    git_marker = path / ".git"
    if expected_remote is None or _is_reparse_point(git_marker) or not git_marker.is_dir():
        return False
    try:
        remote = subprocess.run(
            ("git", "-C", os.fspath(path), "config", "--local", "--get", "remote.origin.url"),
            check=False, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        top = subprocess.run(
            ("git", "-C", os.fspath(path), "rev-parse", "--show-toplevel"),
            check=False, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except OSError:
        return False
    return (
        remote.returncode == 0
        and remote.stdout.strip() == expected_remote
        and top.returncode == 0
        and _same_path(Path(top.stdout.strip()), path)
    )


def _workspace_suggestion(name: str) -> str:
    lowered = name.casefold()
    if "package" in lowered or "build" in lowered:
        return "D:/study/NetConsole-Workspace/temp/build/<task-id> 或 worktrees/<task-id>"
    if "installer" in lowered:
        return "D:/study/NetConsole-Workspace/temp/installer-test/<task-id>"
    if "diagnostic" in lowered:
        return "D:/study/NetConsole-Workspace/reports/diagnostic/<task-id>"
    if "test" in lowered:
        return "D:/study/NetConsole-Workspace/test-data/<fixture-kind> 或 reports/tests/<task-id>"
    if "recovery" in lowered:
        return "已登记的历史例外；新任务使用 reports/ 或 temp/analysis/<task-id>"
    return "D:/study/NetConsole-Workspace/worktrees/<task-id>、temp/<kind>/<task-id> 或 reports/<kind>/<task-id>"


def check_workspace_root(workspace_root: Path, managed_worktrees: Iterable[Path] = ()) -> list[Violation]:
    """Check Workspace boundaries; never recurse through a Reparse Point."""

    workspace_root = _absolute(workspace_root)
    if _is_protected_data_path(workspace_root):
        return [
            Violation(
                "PROTECTED_DATA_PATH",
                str(workspace_root),
                "正式数据根不属于 Workspace 检查范围",
                "仅允许 D:/study/NetConsole-Workspace",
                "停止检查，不访问该路径。",
            )
        ]
    if _is_reparse_point(workspace_root):
        return [
            Violation(
                "WORKSPACE_ROOT_REPARSE",
                str(workspace_root),
                "Workspace 根不能是 Junction、Symlink 或其他 Reparse Point",
                "真实目录 D:/study/NetConsole-Workspace",
                "停止检查并请求人工确认，不解析目标。",
            )
        ]
    result: list[Violation] = []
    if not workspace_root.is_dir():
        return [
            Violation(
                "WORKSPACE_ROOT_MISSING",
                str(workspace_root),
                "Workspace 根必须存在",
                "D:/study/NetConsole-Workspace",
                "停止目录创建并修正 Workspace 配置。",
            )
        ]

    try:
        children = _direct_children(workspace_root)
    except OSError as exc:
        return [
            Violation(
                "WORKSPACE_READ_ERROR",
                str(workspace_root),
                f"Workspace 顶层只读枚举失败：{exc}",
                "可读的真实 Workspace 目录",
                "停止操作并人工检查权限或占用。",
            )
        ]

    for child in children:
        if _is_reparse_point(child):
            result.append(
                Violation(
                "UNSAFE_REPARSE_POINT",
                str(child),
                "不解析 Workspace 顶层或标准容器边界上的链接",
                "真实目录，且目标位于受批准容器内",
                "跳过该路径并人工确认；不要跟随或迁移。",
                )
            )
            continue
        if not child.is_dir() or child.name in WORKSPACE_TOP_LEVEL or _is_registered_independent_repository(child):
            continue
        kind = "PROHIBITED_WORKSPACE_TOP_LEVEL" if child.name.casefold() in PROHIBITED_ROOT_NAMES else "UNAPPROVED_WORKSPACE_TOP_LEVEL"
        result.append(
            Violation(
                kind,
                str(child),
                "Workspace 顶层只能使用标准目录或登记的历史例外",
                _workspace_suggestion(child.name),
                "停止创建；已有目录不自动删除，先登记用途和批准结果。",
            )
        )

    worktree_paths = {_absolute(path).as_posix().casefold() for path in managed_worktrees}
    for container_name in CONTAINER_LINK_CHECKS:
        container = workspace_root / container_name
        if _is_reparse_point(container) or not container.is_dir():
            continue
        try:
            container_children = _direct_children(container)
        except OSError as exc:
            result.append(
                Violation(
                    "CONTAINER_READ_ERROR",
                    str(container),
                    f"标准容器只读枚举失败：{exc}",
                    "可读的标准容器",
                    f"停止操作并人工检查：{exc}",
                )
            )
            continue
        for child in container_children:
            if _is_reparse_point(child):
                result.append(
                    Violation(
                        "UNSAFE_REPARSE_POINT",
                        str(child),
                        "不跟随标准容器内的 Junction、Symlink 或其他 Reparse Point",
                        "真实目录，且目标用途已登记",
                        "跳过该路径并人工确认；不要解析目标。",
                    )
                )
                continue
            if container_name in CONTAINER_CHILDREN and child.is_dir() and child.name not in CONTAINER_CHILDREN[container_name]:
                result.append(
                    Violation(
                        "NONSTANDARD_OUTPUT_CONTAINER",
                        str(child),
                        f"{container_name} 下只能使用已登记的职责容器",
                        "、".join(sorted(CONTAINER_CHILDREN[container_name])),
                        "停止创建；将任务目录放入对应职责容器，不自动删除既有目录。",
                    )
                )
        if container_name == "worktrees":
            for child in container_children:
                if _is_reparse_point(child) or not child.is_dir():
                    continue
                if _absolute(child).as_posix().casefold() not in worktree_paths:
                    result.append(
                        Violation(
                            "UNMANAGED_WORKTREE_DIRECTORY",
                            str(child),
                            "worktrees 只保留由 Git worktree 管理的工作树",
                            "git worktree add worktrees/<task-id>",
                            "不要用普通目录删除绕过 Git；先核验后使用 git worktree remove。",
                        )
                    )

    for child in children:
        if child.name in {"NetConsole", "NetConsole-DevStatus", "worktrees"} or _is_reparse_point(child) or _is_registered_independent_repository(child):
            continue
        git_marker = child / ".git"
        if os.path.lexists(os.fspath(git_marker)):
            result.append(
                Violation(
                    "DUPLICATE_WORKSPACE_REPOSITORY",
                    str(child),
                    "Workspace 不得新增平级项目仓库副本",
                    "唯一主仓库 D:/study/NetConsole-Workspace/NetConsole",
                    "停止使用该副本；不自动删除，先核验依赖并请求确认。",
                )
            )
    return result


def check_repository_root(repo_root: Path) -> list[Violation]:
    """Check repository direct top-level directories without recursion."""

    repo_root = _absolute(repo_root)
    if _is_protected_data_path(repo_root):
        return [
            Violation(
                "PROTECTED_DATA_PATH",
                str(repo_root),
                "正式数据根不属于仓库布局检查范围",
                "D:/study/NetConsole-Workspace/NetConsole",
                "停止检查，不访问该路径。",
            )
        ]
    if _is_reparse_point(repo_root) or not repo_root.is_dir():
        return [
            Violation(
                "REPOSITORY_ROOT_INVALID",
                str(repo_root),
                "仓库根必须是真实可读目录",
                "D:/study/NetConsole-Workspace/NetConsole",
                "停止操作并人工确认路径。",
            )
        ]
    try:
        children = _direct_children(repo_root)
    except OSError as exc:
        return [
            Violation(
                "REPOSITORY_READ_ERROR",
                str(repo_root),
                f"仓库顶层只读枚举失败：{exc}",
                "可读的 Git 仓库目录",
                f"停止操作并人工检查：{exc}",
            )
        ]
    result: list[Violation] = []
    for child in children:
        if child.name == ".git":
            continue
        if _is_reparse_point(child):
            result.append(
                Violation(
                    "REPOSITORY_REPARSE_POINT",
                    str(child),
                    "仓库顶层链接必须有明确的项目用途，检查器不解析其目标",
                    "现有标准目录或经评审的明确链接",
                    "跳过目标并人工确认，不把链接当作新源码目录。",
                )
            )
            continue
        if child.is_dir() and child.name not in REPOSITORY_TOP_LEVEL:
            result.append(
                Violation(
                    "UNAPPROVED_REPOSITORY_TOP_LEVEL",
                    str(child),
                    "主仓库顶层只能使用现有标准职责目录",
                    "apps/、src/、tests/、docs/、scripts/ 或已登记生成目录",
                    "停止创建；将内容归入现有模块，或先更新目录规范并请求批准。",
                )
            )
    git_marker = repo_root / ".git"
    if _is_reparse_point(git_marker):
        result.append(
            Violation(
                "GIT_METADATA_REPARSE_POINT",
                str(git_marker),
                "Git 元数据入口不能通过未核验链接指向其他数据根",
                "主仓库实际 Git common directory",
                "停止 Git 操作并人工确认，不解析目标。",
            )
        )
    return result


def _git_worktrees(repo_root: Path) -> tuple[tuple[Path, ...], list[Violation]]:
    if _is_reparse_point(repo_root / ".git"):
        return (), []
    try:
        completed = subprocess.run(
            ("git", "-C", os.fspath(repo_root), "worktree", "list", "--porcelain"),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        return (), [
            Violation(
                "GIT_WORKTREE_CHECK_ERROR",
                str(repo_root),
                f"无法读取 Git Worktree：{exc}",
                "git worktree list --porcelain",
                "停止创建新工作树并人工检查 Git 安装或仓库状态。",
            )
        ]
    if completed.returncode != 0:
        return (), [
            Violation(
                "GIT_WORKTREE_CHECK_ERROR",
                str(repo_root),
                completed.stderr.strip() or "git worktree list 返回非零状态",
                "git worktree list --porcelain 成功",
                "停止创建新工作树并人工检查 Git 元数据。",
            )
        ]
    paths = tuple(
        _absolute(Path(line.removeprefix("worktree ")))
        for line in completed.stdout.splitlines()
        if line.startswith("worktree ")
    )
    return paths, []


def _registered_independent_worktrees(workspace_root: Path) -> tuple[Path, ...]:
    """Return worktrees owned by independently registered repositories."""

    paths: list[Path] = []
    for name in INDEPENDENT_REPOSITORIES:
        repository = workspace_root / name
        if _is_reparse_point(repository):
            continue
        if not _is_registered_independent_repository(repository):
            continue
        independent_paths, _ = _git_worktrees(repository)
        paths.extend(independent_paths)
    return tuple(paths)


def check_worktree_locations(repo_root: Path, workspace_root: Path | None, worktree_paths: Iterable[Path]) -> list[Violation]:
    if workspace_root is None:
        return []
    workspace_root = _absolute(workspace_root)
    worktree_root = workspace_root / "worktrees"
    result: list[Violation] = []
    for path in worktree_paths:
        if _same_path(path, repo_root):
            continue
        if not _inside(path, worktree_root) or _absolute(path).parent.as_posix().casefold() != _absolute(worktree_root).as_posix().casefold():
            result.append(
                Violation(
                    "WORKTREE_OUTSIDE_CONTAINER",
                    str(path),
                    "所有新 Codex Worktree 必须位于 worktrees/<task-id>",
                    str(worktree_root / "<task-id>"),
                    "停止创建或切换，优先复用规范容器内已有工作树。",
                )
            )
        elif _is_reparse_point(path):
            result.append(
                Violation(
                    "WORKTREE_REPARSE_POINT",
                    str(path),
                    "不跟随 Worktree 路径上的 Reparse Point",
                    "真实 Git Worktree 目录",
                    "跳过并人工确认，不移动或删除。",
                )
            )
    return result


def _default_workspace(repo_root: Path) -> Path | None:
    candidate = _absolute(repo_root).parent
    return candidate if candidate.name.casefold() == WORKSPACE_NAME.casefold() else None


def _format_violation(violation: Violation) -> str:
    return "\n".join(
        (
            "VIOLATION:",
            f"KIND: {violation.kind}",
            f"PATH: {violation.path}",
            f"RULE: {violation.rule}",
            f"EXPECTED: {violation.expected}",
            f"ACTION: {violation.action}",
        )
    )


def run_checks(repo_root: Path, workspace_root: Path | None = None) -> list[Violation]:
    repo_root = _absolute(repo_root)
    workspace_root = _absolute(workspace_root) if workspace_root is not None else _default_workspace(repo_root)
    result = check_repository_root(repo_root)
    worktree_paths, git_result = _git_worktrees(repo_root)
    result.extend(git_result)
    if workspace_root is not None:
        managed_paths = (*worktree_paths, *_registered_independent_worktrees(workspace_root))
        result.extend(check_workspace_root(workspace_root, managed_paths))
        result.extend(check_worktree_locations(repo_root, workspace_root, worktree_paths))
        try:
            common_dir_process = subprocess.run(
                ("git", "-C", os.fspath(repo_root), "rev-parse", "--git-common-dir"),
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            common_dir_process = None
        if common_dir_process is not None and common_dir_process.returncode == 0:
            raw_common = common_dir_process.stdout.strip()
            common_dir = _absolute(Path(raw_common) if os.path.isabs(raw_common) else repo_root / raw_common)
            if _is_reparse_point(common_dir):
                result.append(
                    Violation(
                        "GIT_COMMON_DIR_REPARSE_POINT",
                        str(common_dir),
                        "Git Common Directory 必须可验证且不能通过未核验链接访问",
                        str(repo_root / ".git"),
                        "停止 Worktree 创建并人工确认 Git 元数据。",
                    )
                )
            elif not _inside(common_dir, workspace_root):
                result.append(
                    Violation(
                        "GIT_COMMON_DIR_OUTSIDE_WORKSPACE",
                        str(common_dir),
                        "主仓库 Git Common Directory 必须位于项目 Workspace 内",
                        str(workspace_root / "NetConsole" / ".git"),
                        "停止操作并人工确认仓库布局。",
                    )
                )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT, help="NetConsole Git repository to inspect")
    parser.add_argument("--workspace-root", type=Path, help="canonical Workspace root; inferred locally when applicable")
    parser.add_argument("--repo-only", action="store_true", help="skip Workspace container checks")
    args = parser.parse_args(argv)
    repo_root = _absolute(args.repo_root)
    workspace_root = None if args.repo_only else (_absolute(args.workspace_root) if args.workspace_root else _default_workspace(repo_root))
    if _is_protected_data_path(repo_root) or (workspace_root is not None and _is_protected_data_path(workspace_root)):
        print("WORKSPACE_LAYOUT_CHECK=ERROR")
        print("正式数据根不属于目录规则检查范围；未访问该路径。")
        return 2
    violations = run_checks(repo_root, workspace_root)
    print("WORKSPACE_SCOPE=" + ("WORKSPACE_AND_REPOSITORY" if workspace_root is not None else "REPOSITORY_ONLY"))
    if violations:
        print("WORKSPACE_LAYOUT_CHECK=FAIL")
        for violation in violations:
            print(_format_violation(violation))
            print()
        return 1
    print("WORKSPACE_LAYOUT_CHECK=PASS")
    print("REPARSE_POINTS=NOT_FOLLOWED")
    print("DESTRUCTIVE_ACTIONS=NONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
