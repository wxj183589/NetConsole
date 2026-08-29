"""Preview and hash-verified retirement of explicitly classified storage paths.

The tool is intentionally candidate-first. It never discovers files by age or
size, never treats UNKNOWN as removable, and never accepts a plan whose source
tree changed after preview. The first production action copies each candidate
to a sibling retirement directory, verifies the destination hash, and only then
removes the source file. A manifest is written only after all hashes pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping


ALLOWED_CLASSIFICATIONS = frozenset({"UNMANAGED_EXTERNAL", "LEGACY_MANAGED"})
PLAN_SCHEMA = "storage-retirement-plan/v2"
MANIFEST_SCHEMA = "storage-retirement-manifest/v1"
TARGET_SCOPE = "STORAGE_RETIREMENT_TARGET"


class StorageRetirementError(RuntimeError):
    """A retirement plan or apply gate failed closed."""


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _relative_path(value: str) -> str:
    normalized = str(value or "").replace("\\", "/").strip("/")
    if not normalized or Path(normalized).is_absolute():
        raise StorageRetirementError(f"candidate path must be relative: {value!r}")
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise StorageRetirementError(f"unsafe candidate path: {value!r}")
    return "/".join(parts)


def _is_reparse_or_symlink(path: Path) -> bool:
    if path.is_symlink():
        return True
    if os.name == "nt":
        try:
            attributes = int(path.stat().st_file_attributes)  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            return False
        return bool(attributes & 0x400)
    return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_record(root: Path, path: Path) -> dict[str, Any]:
    if _is_reparse_or_symlink(path) or not path.is_file():
        raise StorageRetirementError(f"candidate contains a non-regular file: {path}")
    stat = path.stat()
    relative = path.relative_to(root).as_posix()
    return {
        "relative_path": relative,
        "original_path": str(path),
        "size_bytes": int(stat.st_size),
        "mtime": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
        "mtime_ns": int(stat.st_mtime_ns),
        "sha256": _sha256(path),
    }


def _protection_file_record(path_value: object, *, role: str) -> dict[str, Any]:
    path = Path(str(path_value or "")).resolve(strict=True)
    if _is_reparse_or_symlink(path) or not path.is_file():
        raise StorageRetirementError(f"protected authority file is not regular: {path}")
    stat = path.stat()
    return {
        "role": str(role),
        "path": str(path),
        "size_bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "sha256": _sha256(path),
    }


def _validate_protection(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise StorageRetirementError(
            "retirement plan requires storage registry and authority protection"
        )
    registry = value.get("storage_registry")
    if not isinstance(registry, Mapping):
        raise StorageRetirementError("storage registry revision binding is required")
    registry_record = _protection_file_record(
        registry.get("path"), role="storage_registry"
    )
    authority = value.get("active_authority_manifest")
    if not isinstance(authority, Mapping) or not isinstance(authority.get("files"), list):
        raise StorageRetirementError("active authority protection manifest is required")
    authority_files = [
        _protection_file_record(item.get("path"), role=str(item.get("role") or "authority"))
        for item in authority["files"]
        if isinstance(item, Mapping)
    ]
    if not authority_files or len(authority_files) != len(authority["files"]):
        raise StorageRetirementError("active authority protection manifest is invalid")
    owner = value.get("current_rollback_owner")
    if not isinstance(owner, Mapping):
        raise StorageRetirementError("current rollback owner identity is required")
    for field in ("operation_id", "database", "status", "retire_state"):
        if not str(owner.get(field) or "").strip():
            raise StorageRetirementError(f"rollback owner field is required: {field}")
    if str(owner.get("status")).upper() != "VERIFIED" or str(owner.get("retire_state")).upper() != "PROTECT":
        raise StorageRetirementError("current rollback owner must be VERIFIED/PROTECT")
    owner_record = _protection_file_record(
        owner.get("owner_path") or owner.get("path"), role="rollback_owner"
    )
    return {
        "storage_registry": {
            **registry_record,
            "revision": str(registry_record["sha256"]),
        },
        "active_authority_manifest": {
            "scope": str(authority.get("scope") or "registered-authority-files"),
            "files": authority_files,
            "manifest_digest": _digest({"files": authority_files}),
        },
        "current_rollback_owner": {
            "operation_id": str(owner["operation_id"]),
            "database": str(owner["database"]),
            "status": str(owner["status"]),
            "retire_state": str(owner["retire_state"]),
            "owner_path": owner_record["path"],
            **owner_record,
        },
    }


def _verify_protection(protection: Mapping[str, Any]) -> None:
    expected = _validate_protection(protection)
    if expected != dict(protection):
        raise StorageRetirementError("RETIRE_PROTECTION_CHANGED: protection manifest drift")


def _expand_candidate(root: Path, relative: str) -> tuple[list[Path], list[str]]:
    source = (root / relative).resolve(strict=False)
    if not _is_relative_to(source, root) or source == root:
        raise StorageRetirementError(f"candidate escapes data root: {relative}")
    if _is_reparse_or_symlink(source):
        raise StorageRetirementError(f"candidate is a symlink or reparse point: {relative}")
    if not source.exists():
        raise StorageRetirementError(f"candidate does not exist: {relative}")
    if source.is_file():
        return [source], []
    if not source.is_dir():
        raise StorageRetirementError(f"candidate is not a file or directory: {relative}")
    files: list[Path] = []
    for item in sorted(source.rglob("*"), key=lambda value: value.as_posix().casefold()):
        if _is_reparse_or_symlink(item):
            raise StorageRetirementError(f"candidate contains a symlink or reparse point: {item}")
        if item.is_file():
            files.append(item)
    return files, [relative]


def _validate_spec_item(item: Mapping[str, Any]) -> tuple[str, str, str, str, str, list[Any]]:
    relative = _relative_path(str(item.get("path") or ""))
    classification = str(item.get("classification") or "").strip().upper()
    if classification not in ALLOWED_CLASSIFICATIONS:
        raise StorageRetirementError(
            f"only explicit external/legacy candidates may be retired: {relative}"
        )
    reason = str(item.get("reason") or "").strip()
    if not reason:
        raise StorageRetirementError(f"retirement reason is required: {relative}")
    writer = str(item.get("code_writer") or "").strip()
    reader = str(item.get("code_reader") or "").strip()
    active_references = item.get("active_references", [])
    if not isinstance(active_references, list) or active_references:
        raise StorageRetirementError(f"active reference blocks retirement: {relative}")
    return relative, classification, reason, writer, reader, active_references


def build_retirement_plan(
    data_root: str | Path,
    spec_path: str | Path,
    retirement_dir: str | Path,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    root = Path(data_root).resolve(strict=True)
    destination = Path(retirement_dir).resolve(strict=False)
    if destination.parent != root.parent or not destination.name.startswith(
        f"{root.name}-retired-"
    ):
        raise StorageRetirementError(
            "retirement directory must be a non-existing sibling named <root>-retired-<timestamp>"
        )
    if _is_relative_to(destination, root) or _is_relative_to(root, destination):
        raise StorageRetirementError("retirement directory overlaps the data root")
    if destination.exists():
        raise StorageRetirementError(f"retirement directory already exists: {destination}")
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    if not isinstance(spec, Mapping) or not isinstance(spec.get("candidates"), list):
        raise StorageRetirementError("retirement spec must contain a candidates list")
    protection = _validate_protection(spec.get("protection"))

    records: list[dict[str, Any]] = []
    candidate_roots: set[str] = set()
    seen: set[str] = set()
    for raw in spec["candidates"]:
        if not isinstance(raw, Mapping):
            raise StorageRetirementError("retirement candidate must be an object")
        relative, classification, reason, writer, reader, _references = _validate_spec_item(raw)
        files, roots = _expand_candidate(root, relative)
        candidate_roots.update(roots)
        for path in files:
            record = _file_record(root, path)
            if record["relative_path"] in seen:
                raise StorageRetirementError(f"duplicate retirement candidate: {record['relative_path']}")
            seen.add(str(record["relative_path"]))
            record.update(
                {
                    "classification": classification,
                    "reason": reason,
                    "code_writer": writer,
                    "code_reader": reader,
                    "retired_path": str(destination / record["relative_path"]),
                }
            )
            records.append(record)
    records.sort(key=lambda item: str(item["relative_path"]).casefold())
    body: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "data_root": str(root),
        "retirement_dir": str(destination),
        "digest_scope": TARGET_SCOPE,
        "protection": protection,
        "candidate_roots": sorted(candidate_roots),
        "candidates": records,
    }
    body["plan_digest"] = _digest(body)
    return body


def write_retirement_plan(plan: Mapping[str, Any], output: str | Path) -> Path:
    destination = Path(output).resolve()
    if destination.exists():
        raise StorageRetirementError(f"refusing to overwrite retirement plan: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(_canonical_bytes(plan))
    return destination


def _copy_verified(source: Path, destination: Path, expected_sha256: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.retire.part")
    temporary.unlink(missing_ok=True)
    try:
        with source.open("rb") as input_stream, temporary.open("xb") as output_stream:
            shutil.copyfileobj(input_stream, output_stream, length=8 * 1024 * 1024)
            output_stream.flush()
            os.fsync(output_stream.fileno())
        shutil.copystat(source, temporary)
        if _sha256(temporary) != expected_sha256:
            raise StorageRetirementError(f"retirement copy hash mismatch: {source}")
        os.replace(temporary, destination)
        if _sha256(destination) != expected_sha256:
            raise StorageRetirementError(f"retirement destination hash mismatch: {destination}")
    finally:
        temporary.unlink(missing_ok=True)


def _prune_empty_directories(root: Path, relative_roots: Iterable[str]) -> None:
    for relative in sorted(relative_roots, key=lambda value: value.count("/"), reverse=True):
        path = root / relative
        if not path.is_dir() or _is_reparse_or_symlink(path):
            continue
        current = path
        while current != root and _is_relative_to(current, root):
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent


def apply_retirement_plan(
    plan_path: str | Path,
    *,
    expected_plan_digest: str,
    retired_at: str | None = None,
) -> dict[str, Any]:
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    if not isinstance(plan, Mapping) or plan.get("schema") != PLAN_SCHEMA:
        raise StorageRetirementError("unsupported retirement plan")
    body = dict(plan)
    actual_digest = str(body.pop("plan_digest") or "")
    if actual_digest != expected_plan_digest or _digest(body) != actual_digest:
        raise StorageRetirementError("RETIRE_PLAN_DIGEST_MISMATCH")
    root = Path(str(plan["data_root"])).resolve(strict=True)
    destination = Path(str(plan["retirement_dir"])).resolve(strict=False)
    if destination.parent != root.parent or not destination.name.startswith(f"{root.name}-retired-"):
        raise StorageRetirementError("invalid retirement sibling")
    if destination.exists():
        raise StorageRetirementError("retirement destination already exists")
    protection = plan.get("protection")
    if not isinstance(protection, Mapping):
        raise StorageRetirementError("retirement plan protection is missing")
    _verify_protection(protection)
    candidates = plan.get("candidates")
    if not isinstance(candidates, list):
        raise StorageRetirementError("retirement plan candidates are invalid")

    timestamp = retired_at or datetime.now(UTC).isoformat()
    moved: list[tuple[Path, Path]] = []
    manifest_rows: list[dict[str, Any]] = []
    destination.mkdir(parents=True)
    try:
        for item in candidates:
            if not isinstance(item, Mapping):
                raise StorageRetirementError("retirement candidate is invalid")
            relative = _relative_path(str(item.get("relative_path") or ""))
            source = (root / relative).resolve(strict=False)
            target = (destination / relative).resolve(strict=False)
            if not _is_relative_to(source, root) or not _is_relative_to(target, destination):
                raise StorageRetirementError("retirement candidate path traversal detected")
            if _is_reparse_or_symlink(source) or not source.is_file():
                raise StorageRetirementError(f"retirement source changed or disappeared: {source}")
            stat = source.stat()
            expected_size = int(item.get("size_bytes") or -1)
            expected_mtime_ns = int(item.get("mtime_ns") or -1)
            expected_sha256 = str(item.get("sha256") or "")
            if (
                stat.st_size != expected_size
                or stat.st_mtime_ns != expected_mtime_ns
                or _sha256(source) != expected_sha256
            ):
                raise StorageRetirementError(f"RETIRE_SOURCE_CHANGED: {source}")
            if target.exists():
                raise StorageRetirementError(f"retirement target already exists: {target}")
            _copy_verified(source, target, expected_sha256)
            moved.append((source, target))
            source.unlink()
            if source.exists() or _sha256(target) != expected_sha256:
                raise StorageRetirementError(f"retirement postcondition failed: {source}")
            manifest_rows.append(
                {
                    "original_path": str(source),
                    "retired_path": str(target),
                    "size_bytes": expected_size,
                    "sha256": expected_sha256,
                    "mtime": str(item.get("mtime") or ""),
                    "classification": str(item.get("classification") or ""),
                    "reason": str(item.get("reason") or ""),
                    "code_writer": str(item.get("code_writer") or ""),
                    "code_reader": str(item.get("code_reader") or ""),
                    "retired_at": timestamp,
                }
            )
        _prune_empty_directories(root, plan.get("candidate_roots", []))
        manifest = {
            "schema": MANIFEST_SCHEMA,
            "plan_digest": actual_digest,
            "retired_at": timestamp,
            "data_root": str(root),
            "retirement_dir": str(destination),
            "hash_verify": "PASS",
            "files": manifest_rows,
        }
        (destination / "retirement-manifest.json").write_bytes(_canonical_bytes(manifest))
    except Exception:
        for source, target in reversed(moved):
            if source.exists():
                continue
            _copy_verified(target, source, _sha256(target))
            target.unlink(missing_ok=True)
        shutil.rmtree(destination, ignore_errors=False)
        raise
    return {
        "status": "PASS",
        "plan_digest": actual_digest,
        "retirement_dir": str(destination),
        "manifest": str(destination / "retirement-manifest.json"),
        "retired_files": len(manifest_rows),
        "retired_bytes": sum(int(item["size_bytes"]) for item in manifest_rows),
        "hash_verify": "PASS",
        "source_absent": all(not Path(item["original_path"]).exists() for item in manifest_rows),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    preview = subparsers.add_parser("preview")
    preview.add_argument("--data-root", type=Path, required=True)
    preview.add_argument("--spec", type=Path, required=True)
    preview.add_argument("--retirement-dir", type=Path, required=True)
    preview.add_argument("--output", type=Path, required=True)
    apply = subparsers.add_parser("apply")
    apply.add_argument("--plan", type=Path, required=True)
    apply.add_argument("--expected-plan-digest", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "preview":
        plan = build_retirement_plan(args.data_root, args.spec, args.retirement_dir)
        output = write_retirement_plan(plan, args.output)
        print(json.dumps({"status": "PASS", "plan": str(output), **plan}, ensure_ascii=False, indent=2))
        return 0
    print(json.dumps(apply_retirement_plan(args.plan, expected_plan_digest=args.expected_plan_digest), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
