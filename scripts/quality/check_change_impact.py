from __future__ import annotations

import argparse
import fnmatch
import glob
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config" / "architecture" / "change_impact_matrix.json"
LEVEL_ORDER = {"L1": 1, "L2": 2, "L3": 3, "L4": 4}
CRITICAL_PATHS = {
    "apps/desktop_renderer/src/api/client.ts": ("renderer-api-client", "L3"),
    "apps/desktop_renderer/src/components/table/NcDataTable.vue": ("nc-data-table", "L3"),
    "src/netconsole/background_worker.py": ("task-center", "L3"),
    "src/netconsole/export_worker.py": ("export-framework", "L3"),
    "src/netconsole/repositories/ap_identity_repository.py": ("ap-identity", "L3"),
    "src/netconsole/core/feature_registry.py": ("feature-registry", "L4"),
    "src/netconsole/core/paths.py": ("data-root-and-migration", "L4"),
    "apps/desktop_electron/src/main/index.ts": ("electron-runtime", "L4"),
}


@dataclass(frozen=True)
class Impact:
    level: str
    changed_paths: tuple[str, ...]
    areas: tuple[str, ...]
    owners: tuple[str, ...]
    consumers: tuple[str, ...]
    compatibility_risks: tuple[str, ...]
    suites: tuple[str, ...]

    @property
    def requires_post_merge(self) -> bool:
        return LEVEL_ORDER[self.level] >= LEVEL_ORDER["L3"]


def _normalize_path(value: str) -> str:
    normalized = value.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _matches(path: str, pattern: str) -> bool:
    normalized_pattern = _normalize_path(pattern)
    if normalized_pattern.endswith("/**"):
        return path.startswith(normalized_pattern[:-2])
    if normalized_pattern.startswith("**/") and fnmatch.fnmatchcase(path, normalized_pattern[3:]):
        return True
    return fnmatch.fnmatchcase(path, normalized_pattern)


def _load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        config = json.load(stream)
    if config.get("schema_version") != 1:
        raise ValueError("change impact matrix schema_version must be 1")
    default_level = config.get("default_level")
    if default_level not in LEVEL_ORDER:
        raise ValueError(f"invalid default_level: {default_level!r}")
    suites = config.get("consumer_suites")
    areas = config.get("risk_areas")
    domains = config.get("domains")
    if not isinstance(domains, dict) or not domains or not all(
        isinstance(domain_id, str) and domain_id and isinstance(label, str) and label
        for domain_id, label in domains.items()
    ):
        raise ValueError("domains must be a non-empty mapping of stable IDs to labels")
    if not isinstance(suites, dict) or not suites:
        raise ValueError("consumer_suites must be a non-empty object")
    if not isinstance(areas, list) or not areas:
        raise ValueError("risk_areas must be a non-empty array")
    known_suite_ids = set(suites)
    known_domain_ids = set(domains)
    for suite_id, suite in suites.items():
        if not isinstance(suite, dict) or not suite.get("label") or not suite.get("command"):
            raise ValueError(f"consumer suite {suite_id!r} must declare label and command")
        evidence = suite.get("evidence")
        if not isinstance(evidence, list) or not evidence or any(not isinstance(item, str) or not item for item in evidence):
            raise ValueError(f"consumer suite {suite_id!r} must declare evidence paths")
        missing_evidence = [item for item in evidence if not (ROOT / item).is_file()]
        if missing_evidence:
            raise ValueError(f"consumer suite {suite_id!r} references missing evidence: {missing_evidence}")
    known_area_ids: set[str] = set()
    for area in areas:
        area_id = area.get("id")
        if not isinstance(area_id, str) or not area_id or area_id in known_area_ids:
            raise ValueError(f"invalid or duplicate risk area id: {area_id!r}")
        known_area_ids.add(area_id)
        if area.get("owner") not in known_domain_ids:
            raise ValueError(f"risk area {area_id!r} references unknown owner: {area.get('owner')!r}")
        if area.get("level") not in {"L3", "L4"}:
            raise ValueError(f"risk area {area_id!r} must be L3 or L4")
        if (
            not area.get("patterns")
            or not area.get("consumers")
            or not area.get("compatibility_risks")
            or not area.get("suites")
        ):
            raise ValueError(f"risk area {area_id!r} has an empty contract")
        for pattern in area["patterns"]:
            if not glob.glob(str(ROOT / pattern), recursive=True):
                raise ValueError(f"risk area {area_id!r} pattern matches no current path: {pattern!r}")
        unknown_suites = set(area["suites"]) - known_suite_ids
        if unknown_suites:
            raise ValueError(f"risk area {area_id!r} references unknown suites: {sorted(unknown_suites)}")
        unknown_consumers = set(area["consumers"]) - known_domain_ids
        if unknown_consumers:
            raise ValueError(f"risk area {area_id!r} references unknown consumers: {sorted(unknown_consumers)}")
    areas_by_id = {area["id"]: area for area in areas}
    for critical_path, (expected_area, minimum_level) in CRITICAL_PATHS.items():
        if not (ROOT / critical_path).is_file():
            raise ValueError(f"critical shared path is missing: {critical_path!r}")
        area = areas_by_id.get(expected_area)
        if area is None or not any(_matches(critical_path, pattern) for pattern in area["patterns"]):
            raise ValueError(f"critical shared path {critical_path!r} is not registered in {expected_area!r}")
        if LEVEL_ORDER[area["level"]] < LEVEL_ORDER[minimum_level]:
            raise ValueError(f"critical shared path {critical_path!r} is below {minimum_level}")
    return config


def _git_changed_paths(base_sha: str, head_sha: str) -> tuple[str, ...]:
    if not head_sha:
        raise ValueError("head SHA is required when --paths is not used")
    base_is_empty = not base_sha or set(base_sha) == {"0"}
    command = ["git", "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", head_sha]
    if not base_is_empty:
        command = ["git", "diff", "--name-only", base_sha, head_sha]
    completed = subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8")
    return tuple(sorted({_normalize_path(line) for line in completed.stdout.splitlines() if line.strip()}))


def classify(paths: Iterable[str], config: dict[str, Any]) -> Impact:
    changed_paths = tuple(sorted({_normalize_path(path) for path in paths if path.strip()}))
    low_risk_patterns = tuple(config.get("low_risk_patterns", ()))
    only_low_risk = bool(changed_paths) and all(
        any(_matches(path, pattern) for pattern in low_risk_patterns) for path in changed_paths
    )
    level = "L1" if only_low_risk or not changed_paths else config["default_level"]
    areas: list[str] = []
    owners: set[str] = set()
    consumers: set[str] = set()
    compatibility_risks: set[str] = set()
    suites: set[str] = set()
    for area in config["risk_areas"]:
        if not any(_matches(path, pattern) for path in changed_paths for pattern in area["patterns"]):
            continue
        areas.append(area["id"])
        owners.add(area["owner"])
        consumers.update(area["consumers"])
        compatibility_risks.update(area["compatibility_risks"])
        suites.update(area["suites"])
        if LEVEL_ORDER[area["level"]] > LEVEL_ORDER[level]:
            level = area["level"]
    return Impact(
        level=level,
        changed_paths=changed_paths,
        areas=tuple(sorted(areas)),
        owners=tuple(sorted(owners)),
        consumers=tuple(sorted(consumers)),
        compatibility_risks=tuple(sorted(compatibility_risks)),
        suites=tuple(sorted(suites)),
    )


def _csv(values: Iterable[str]) -> str:
    return ",".join(values)


def _write_github_output(path: Path, impact: Impact) -> None:
    entries = {
        "risk_level": impact.level,
        "risk_areas": _csv(impact.areas),
        "owners": _csv(impact.owners),
        "consumers": _csv(impact.consumers),
        "compatibility_risks": " | ".join(impact.compatibility_risks),
        "consumer_suites": _csv(impact.suites),
        "requires_post_merge": str(impact.requires_post_merge).lower(),
    }
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        for key, value in entries.items():
            stream.write(f"{key}={value}\n")


def _summary(impact: Impact, config: dict[str, Any]) -> str:
    area_text = ", ".join(f"`{value}`" for value in impact.areas) or "无共享高风险区域命中"
    owner_text = ", ".join(f"`{value}`" for value in impact.owners) or "当前模块 owner"
    consumer_text = "、".join(
        f"{value} ({config['domains'][value]})" for value in impact.consumers
    ) or "按当前模块定向验证"
    risk_text = "；".join(impact.compatibility_risks) or "当前模块局部契约"
    suite_lines = [
        (
            f"- `{suite_id}`: {config['consumer_suites'][suite_id]['label']}"
            f"；命令：`{config['consumer_suites'][suite_id]['command']}`"
        )
        for suite_id in impact.suites
    ] or ["- 按当前模块运行定向测试"]
    return "\n".join(
        [
            "## Change Impact Audit",
            "",
            f"- 风险等级：`{impact.level}`",
            f"- 高风险区域：{area_text}",
            f"- 契约 Owner：{owner_text}",
            f"- 影响消费者：{consumer_text}",
            f"- 兼容性风险：{risk_text}",
            f"- 合并后 main 复验：`{'required' if impact.requires_post_merge else 'normal baseline'}`",
            "- 并行修改：CI 无法判断本地 worktree 并行状态，开发者必须在任务报告中单独审计",
            "",
            "最低消费者套件：",
            "",
            *suite_lines,
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify NetConsole changes and print required consumer regression suites.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--base-sha", default="")
    parser.add_argument("--head-sha", default="")
    parser.add_argument("--paths", nargs="*")
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--github-summary", type=Path)
    args = parser.parse_args()

    config = _load_config(args.config)
    paths = tuple(args.paths) if args.paths is not None else _git_changed_paths(args.base_sha, args.head_sha)
    impact = classify(paths, config)
    summary = _summary(impact, config)
    print(summary)
    if args.github_output:
        _write_github_output(args.github_output, impact)
    if args.github_summary:
        with args.github_summary.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
