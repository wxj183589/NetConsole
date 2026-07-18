from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


TARGETS = {
    "legacy-qt-release": (Path("dist") / "v1.3.8",),
}


class CleanupError(RuntimeError):
    pass


@dataclass(frozen=True)
class CleanupItem:
    relative_path: str
    status: str
    file_count: int
    total_bytes: int


def clean_generated_artifacts(
    repo_root: Path,
    target: str,
    *,
    apply: bool = False,
) -> dict[str, object]:
    root = _validated_repo_root(repo_root)
    if target not in TARGETS:
        raise CleanupError(f"未知清理目标：{target}")

    items: list[CleanupItem] = []
    for relative in TARGETS[target]:
        candidate = root / relative
        if not candidate.exists():
            items.append(CleanupItem(relative.as_posix(), "absent", 0, 0))
            continue
        resolved = _validated_target(root, candidate, relative)
        file_count, total_bytes = _summarize_tree(resolved)
        status = "planned"
        if apply:
            shutil.rmtree(resolved)
            if resolved.exists():
                raise CleanupError(f"清理后目标仍存在：{relative.as_posix()}")
            status = "removed"
        items.append(CleanupItem(relative.as_posix(), status, file_count, total_bytes))

    return {
        "schema_version": 1,
        "target": target,
        "mode": "apply" if apply else "dry-run",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "items": [asdict(item) for item in items],
    }


def _validated_repo_root(value: Path) -> Path:
    root = Path(value).resolve()
    if not (root / "pyproject.toml").is_file() or not (root / "main.py").is_file():
        raise CleanupError(f"不是 NetConsole 仓库根：{root}")
    return root


def _validated_target(root: Path, candidate: Path, relative: Path) -> Path:
    if candidate.is_symlink():
        raise CleanupError(f"拒绝清理符号链接目标：{relative.as_posix()}")
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise CleanupError(f"拒绝清理仓库外路径：{relative.as_posix()}")
    if resolved != (root / relative).resolve():
        raise CleanupError(f"清理目标解析结果不一致：{relative.as_posix()}")
    if any(path.is_symlink() for path in resolved.rglob("*")):
        raise CleanupError(f"清理目标包含符号链接：{relative.as_posix()}")
    return resolved


def _summarize_tree(root: Path) -> tuple[int, int]:
    files = [path for path in root.rglob("*") if path.is_file()]
    return len(files), sum(path.stat().st_size for path in files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="安全回收 NetConsole 可再生成构建产物")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--target", choices=tuple(TARGETS), required=True)
    parser.add_argument("--apply", action="store_true", help="实际删除；默认仅生成计划")
    parser.add_argument("--manifest", type=Path, help="可选 JSON 清理清单输出路径")
    args = parser.parse_args(argv)

    try:
        report = clean_generated_artifacts(args.repo_root, args.target, apply=args.apply)
    except CleanupError as exc:
        parser.error(str(exc))
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    print(payload)
    if args.manifest:
        manifest = args.manifest.expanduser().resolve()
        manifest.parent.mkdir(parents=True, exist_ok=True)
        temporary = manifest.with_suffix(manifest.suffix + ".tmp")
        temporary.write_text(payload + "\n", encoding="utf-8")
        temporary.replace(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
