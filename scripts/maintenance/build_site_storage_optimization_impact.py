"""Build measured whole-site storage impact evidence from isolated rehearsal outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from scripts.maintenance.finalize_site_storage_audit import _STORAGE_REPORT_SECTIONS


DEFAULT_DEVELOPMENT_ROOT = Path("D:/study")


class StorageImpactError(ValueError):
    """Raised when isolated storage-impact evidence cannot be reconciled."""


def build_site_storage_optimization_impact(
    *,
    baseline_footprint_path: Path,
    site_inventory_path: Path,
    global_inventory_path: Path,
    before_devices_path: Path,
    after_devices_path: Path,
    before_tasks_path: Path,
    after_tasks_path: Path,
    after_history_root: Path,
    task_authority_report_path: Path,
    provenance_report_path: Path,
    output_path: Path,
    development_root: Path = DEFAULT_DEVELOPMENT_ROOT,
) -> dict[str, Any]:
    """Create the finalizer overlay without opening or mutating a database."""

    development = development_root.resolve(strict=True)
    baseline_path = _input_file(baseline_footprint_path, development)
    site_inventory = _input_file(site_inventory_path, development)
    global_inventory = _input_file(global_inventory_path, development)
    before_devices = _input_file(before_devices_path, development)
    after_devices = _input_file(after_devices_path, development)
    before_tasks = _input_file(before_tasks_path, development)
    after_tasks = _input_file(after_tasks_path, development)
    history_root = _input_directory(after_history_root, development)
    task_report_path = _input_file(task_authority_report_path, development)
    provenance_report = _input_file(provenance_report_path, development)
    output = _output_file(output_path, development)
    if output.exists():
        raise StorageImpactError(f"refusing to overwrite storage impact evidence: {output}")

    baseline = _load_object(baseline_path, "baseline footprint")
    site_raw = _load_object(site_inventory, "site inventory")
    global_raw = _load_object(global_inventory, "global inventory")
    task_report = _load_object(task_report_path, "task authority report")

    storage = baseline.get("all_databases_storage")
    raw_sections = storage.get("sections") if isinstance(storage, Mapping) else None
    if not isinstance(raw_sections, Mapping) or set(raw_sections) != set(
        _STORAGE_REPORT_SECTIONS
    ):
        raise StorageImpactError("baseline footprint does not contain every storage section")
    if baseline.get("measurement_scope") != (
        "entire recursive site plus data-root global inventory"
    ):
        raise StorageImpactError("baseline footprint is not a complete recursive inventory")

    baseline_total = _inventory_bytes(site_raw, "site inventory") + _inventory_bytes(
        global_raw, "global inventory"
    )
    summary = baseline.get("summary")
    if not isinstance(summary, Mapping) or int(summary.get("site_total_bytes") or -1) != baseline_total:
        raise StorageImpactError("baseline footprint total does not match source inventories")

    before_device_bytes = before_devices.stat().st_size
    before_task_bytes = before_tasks.stat().st_size
    _verify_registered_baseline_bytes(
        raw_sections,
        store_id="site.devices.current",
        measured_bytes=before_device_bytes,
    )
    _verify_registered_baseline_bytes(
        raw_sections,
        store_id="site.tasks.current",
        measured_bytes=before_task_bytes,
    )

    logical_duplicates = task_report.get("logical_result_bytes_removed")
    if (
        isinstance(logical_duplicates, bool)
        or not isinstance(logical_duplicates, int)
        or logical_duplicates < 0
    ):
        raise StorageImpactError(
            "task authority report lacks non-negative logical_result_bytes_removed"
        )
    if int(task_report.get("event_full_results_removed") or 0) <= 0:
        raise StorageImpactError("task authority report has no removed event full results")

    history_evidence = _directory_evidence(history_root)
    history_bytes = sum(int(item["size_bytes"]) for item in history_evidence)
    if history_bytes <= 0:
        raise StorageImpactError("after History root is empty")

    sections: dict[str, dict[str, Any]] = {}
    for name in _STORAGE_REPORT_SECTIONS:
        raw_section = raw_sections[name]
        if not isinstance(raw_section, Mapping):
            raise StorageImpactError(f"baseline section {name} is invalid")
        before_bytes = _non_negative_int(raw_section.get("before_bytes"), f"{name}.before_bytes")
        protected_bytes = _non_negative_int(
            raw_section.get("protected_bytes"), f"{name}.protected_bytes"
        )
        sections[name] = {
            "before_bytes": before_bytes,
            "after_operational_bytes": before_bytes,
            "history_moved_bytes": 0,
            "duplicates_removed_bytes": 0,
            "protected_bytes": protected_bytes,
            "evidence": [str(baseline_path)],
        }

    operational = sections["Operational DBs"]
    operational["after_operational_bytes"] = (
        int(operational["before_bytes"])
        - before_device_bytes
        - before_task_bytes
        + after_devices.stat().st_size
        + after_tasks.stat().st_size
    )
    if int(operational["after_operational_bytes"]) < 0:
        raise StorageImpactError("operational overlay produced a negative byte count")
    operational["duplicates_removed_bytes"] = logical_duplicates
    operational["evidence"] = [
        str(before_devices),
        str(after_devices),
        str(before_tasks),
        str(after_tasks),
        str(task_report_path),
    ]

    history = sections["History DBs/shards"]
    history["after_operational_bytes"] = int(history["before_bytes"]) + history_bytes
    history["history_moved_bytes"] = history_bytes
    history["evidence"] = [str(history_root), str(provenance_report)]

    before_site_bytes = sum(int(item["before_bytes"]) for item in sections.values())
    if before_site_bytes != baseline_total:
        raise StorageImpactError("baseline storage sections do not reconcile")
    after_site_bytes = sum(
        int(item["after_operational_bytes"]) for item in sections.values()
    )
    report = {
        "format": "netconsole-site-storage-impact-v1",
        "schema_version": 1,
        "source_inventory_sha256": _combined_inventory_digest(
            site_inventory, global_inventory
        ),
        "measurement_scope": "entire recursive site plus data-root global inventory",
        "measurement_status": "ISOLATED_REHEARSAL_OVERLAY",
        "before_site_bytes": before_site_bytes,
        "after_site_bytes": after_site_bytes,
        "after_operational_bytes": after_site_bytes,
        "history_moved_bytes": sum(
            int(item["history_moved_bytes"]) for item in sections.values()
        ),
        "duplicates_removed_bytes": sum(
            int(item["duplicates_removed_bytes"]) for item in sections.values()
        ),
        "protected_bytes": sum(
            int(item["protected_bytes"]) for item in sections.values()
        ),
        "sections": sections,
        "measured_inputs": {
            "baseline_footprint": _file_evidence(baseline_path),
            "site_inventory": _file_evidence(site_inventory),
            "global_inventory": _file_evidence(global_inventory),
            "before_devices": _file_evidence(before_devices),
            "after_devices": _file_evidence(after_devices),
            "before_tasks": _file_evidence(before_tasks),
            "after_tasks": _file_evidence(after_tasks),
            "after_history": {
                "root": str(history_root),
                "size_bytes": history_bytes,
                "files": history_evidence,
            },
            "task_authority_report": _file_evidence(task_report_path),
            "provenance_report": _file_evidence(provenance_report),
        },
    }
    _atomic_json(output, report)
    return report


def _verify_registered_baseline_bytes(
    sections: Mapping[str, Any], *, store_id: str, measured_bytes: int
) -> None:
    operational = sections.get("Operational DBs")
    authorities = operational.get("authority") if isinstance(operational, Mapping) else None
    if not isinstance(authorities, list):
        raise StorageImpactError("baseline operational authority list is missing")
    matches = [
        item
        for item in authorities
        if isinstance(item, Mapping) and item.get("store_id") == store_id
    ]
    if len(matches) != 1 or int(matches[0].get("before_bytes") or -1) != measured_bytes:
        raise StorageImpactError(
            f"baseline authority {store_id} does not match measured source bytes"
        )


def _inventory_bytes(value: Mapping[str, Any], label: str) -> int:
    totals = value.get("totals")
    if not isinstance(totals, Mapping):
        raise StorageImpactError(f"{label} has no totals")
    return _non_negative_int(totals.get("bytes"), f"{label}.totals.bytes")


def _non_negative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise StorageImpactError(f"{label} must be a non-negative integer")
    return value


def _combined_inventory_digest(site_inventory: Path, global_inventory: Path) -> str:
    binding = json.dumps(
        {
            "global_inventory_sha256": _sha256_file(global_inventory),
            "site_inventory_sha256": _sha256_file(site_inventory),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(binding).hexdigest()


def _directory_evidence(root: Path) -> list[dict[str, Any]]:
    candidates = list(root.rglob("*"))
    unsafe = [
        path
        for path in candidates
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())
    ]
    if unsafe:
        raise StorageImpactError(
            f"after History root contains a link or junction: {unsafe[0]}"
        )
    return [
        {
            "relative_path": path.relative_to(root).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
        }
        for path in sorted(candidate for candidate in candidates if candidate.is_file())
    ]


def _file_evidence(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StorageImpactError(f"invalid {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise StorageImpactError(f"{label} must be a JSON object")
    return value


def _input_file(path: Path, development_root: Path) -> Path:
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or not resolved.is_relative_to(development_root):
        raise StorageImpactError(f"input file must remain below D:/study: {resolved}")
    return resolved


def _input_directory(path: Path, development_root: Path) -> Path:
    original = path.absolute()
    if original.is_symlink() or (
        hasattr(original, "is_junction") and original.is_junction()
    ):
        raise StorageImpactError(f"input directory cannot be a link or junction: {original}")
    resolved = original.resolve(strict=True)
    if not resolved.is_dir() or not resolved.is_relative_to(development_root):
        raise StorageImpactError(f"input directory must remain below D:/study: {resolved}")
    return resolved


def _output_file(path: Path, development_root: Path) -> Path:
    resolved = path.resolve()
    if resolved == development_root or not resolved.is_relative_to(development_root):
        raise StorageImpactError(f"output must remain below D:/study: {resolved}")
    return resolved


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(
                (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
                    "utf-8"
                )
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
        temporary.unlink()
    finally:
        temporary.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-footprint", type=Path, required=True)
    parser.add_argument("--site-inventory", type=Path, required=True)
    parser.add_argument("--global-inventory", type=Path, required=True)
    parser.add_argument("--before-devices", type=Path, required=True)
    parser.add_argument("--after-devices", type=Path, required=True)
    parser.add_argument("--before-tasks", type=Path, required=True)
    parser.add_argument("--after-tasks", type=Path, required=True)
    parser.add_argument("--after-history-root", type=Path, required=True)
    parser.add_argument("--task-authority-report", type=Path, required=True)
    parser.add_argument("--provenance-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--development-root", type=Path, default=DEFAULT_DEVELOPMENT_ROOT
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = build_site_storage_optimization_impact(
        baseline_footprint_path=args.baseline_footprint,
        site_inventory_path=args.site_inventory,
        global_inventory_path=args.global_inventory,
        before_devices_path=args.before_devices,
        after_devices_path=args.after_devices,
        before_tasks_path=args.before_tasks,
        after_tasks_path=args.after_tasks,
        after_history_root=args.after_history_root,
        task_authority_report_path=args.task_authority_report,
        provenance_report_path=args.provenance_report,
        output_path=args.output,
        development_root=args.development_root,
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "before_site_bytes": report["before_site_bytes"],
                "after_site_bytes": report["after_site_bytes"],
                "output": str(args.output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
