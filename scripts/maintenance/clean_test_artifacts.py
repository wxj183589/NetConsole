from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path


ALLOWED_DIRECTORY_NAMES = {"__pycache__", "qt-webengine-debug", "qt-webengine-inspect"}
ALLOWED_DIRECTORY_PREFIXES = ("pytest-", "qt-final-acceptance-", "qt-package-")
ALLOWED_FILE_PREFIXES = ("qt-final-acceptance", "qt-package-")
ALLOWED_FILE_SUFFIXES = {".json", ".log", ".png", ".txt"}
PROTECTED_NAMES = {"acceptance", "agent", "agent_team", "data", "logs", "runtime", "tmp"}


@dataclass(frozen=True)
class CleanupEntry:
    name: str
    kind: str
    bytes: int
    action: str
    detail: str | None = None


def build_cleanup_plan(repo_root: Path) -> list[CleanupEntry]:
    repo = repo_root.resolve()
    local_root = (repo / ".local").resolve()
    if not local_root.exists():
        return []
    if _is_reparse_point(local_root):
        raise RuntimeError(".local must not be a link or reparse point")
    entries: list[CleanupEntry] = []
    for child in sorted(local_root.iterdir(), key=lambda item: item.name.casefold()):
        if child.name.casefold() in PROTECTED_NAMES:
            continue
        if not _is_allowed_candidate(child):
            continue
        if _is_reparse_point(child):
            entries.append(CleanupEntry(child.name, "link", 0, "unsafe", "link or reparse point"))
            continue
        entries.append(
            CleanupEntry(
                name=child.name,
                kind="directory" if child.is_dir() else "file",
                bytes=_path_size(child),
                action="delete",
            )
        )
    return entries


def apply_cleanup(repo_root: Path, entries: list[CleanupEntry]) -> list[CleanupEntry]:
    repo = repo_root.resolve()
    local_root = (repo / ".local").resolve()
    if any(entry.action == "unsafe" for entry in entries):
        raise RuntimeError("cleanup plan contains unsafe entries")
    completed: list[CleanupEntry] = []
    for entry in entries:
        target = (local_root / entry.name).resolve()
        if target.parent != local_root or not _is_allowed_candidate(target):
            raise RuntimeError(f"cleanup target escaped allowlist: {entry.name}")
        if not target.exists():
            completed.append(CleanupEntry(entry.name, entry.kind, 0, "missing"))
            continue
        if _is_reparse_point(target):
            raise RuntimeError(f"cleanup target changed into a link: {entry.name}")
        if target.is_dir():
            shutil.rmtree(target)
        elif target.is_file():
            target.unlink()
        else:
            raise RuntimeError(f"cleanup target is not a regular path: {entry.name}")
        completed.append(CleanupEntry(entry.name, entry.kind, entry.bytes, "deleted"))
    return completed


def cleanup_manifest(entries: list[CleanupEntry], *, applied: bool) -> dict[str, object]:
    return {
        "schema_version": 1,
        "mode": "applied" if applied else "dry-run",
        "summary": {
            "items": len(entries),
            "bytes": sum(entry.bytes for entry in entries if entry.action in {"delete", "deleted"}),
        },
        "entries": [asdict(entry) for entry in entries],
    }


def _is_allowed_candidate(path: Path) -> bool:
    name = path.name.casefold()
    if name in PROTECTED_NAMES:
        return False
    if path.is_dir():
        return name in ALLOWED_DIRECTORY_NAMES or name.startswith(ALLOWED_DIRECTORY_PREFIXES)
    return name.startswith(ALLOWED_FILE_PREFIXES) and path.suffix.casefold() in ALLOWED_FILE_SUFFIXES


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        return bool(path.lstat().st_file_attributes & 0x400)  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return False


def _path_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file() and not _is_reparse_point(item))


def _write_manifest(payload: dict[str, object], path: Path | None) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if path is None:
        print(text)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="清理仓库 .local 顶层的明确测试与 Qt 临时产物")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--apply", action="store_true", help="执行白名单删除；默认仅生成计划")
    args = parser.parse_args()
    plan = build_cleanup_plan(args.repo_root)
    if args.apply:
        result = apply_cleanup(args.repo_root, plan)
        _write_manifest(cleanup_manifest(result, applied=True), args.manifest)
        return 0
    _write_manifest(cleanup_manifest(plan, applied=False), args.manifest)
    return 2 if any(entry.action == "unsafe" for entry in plan) else 0


if __name__ == "__main__":
    raise SystemExit(main())
