from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import site
import sysconfig
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path, PurePosixPath
from typing import Any

from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version


SCHEMA_ID = "netconsole.pyinstaller-artifact-inventory.v1"
APPROVAL_SCHEMA_ID = "netconsole.pyinstaller-approved-distributions.v1"
_ANALYSIS_GROUP_INDEX = {
    "scripts": 13,
    "pure": 14,
    "binaries": 15,
    "datas": 18,
}
_DISTRIBUTION_NAME_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ArtifactInventoryError(RuntimeError):
    """Raised when packaged distribution evidence is incomplete or inconsistent."""


@dataclass(frozen=True)
class _AnalysisEntry:
    group: str
    destination: str
    source: Path


def collect_pyinstaller_distributions(
    analysis_toc: Path,
    app_dir: Path | None = None,
) -> dict[str, str]:
    """Map PyInstaller input files to their owning installed distributions.

    ``Analysis-00.toc`` proves which sources were selected by Analysis.  When
    ``app_dir`` is supplied, each reported distribution must additionally have
    at least one matching file in ``_internal`` or one module in the executable
    CArchive/PYZ.  The returned mapping is canonical distribution name to the
    exact installed version and never contains source paths.
    """

    toc_path = Path(analysis_toc)
    entries = _read_analysis_entries(toc_path)
    source_index, distribution_roots = _index_distribution_files(
        metadata.distributions()
    )
    owners: dict[str, str] = {}
    owned_entries: dict[str, list[_AnalysisEntry]] = {}

    for entry in entries:
        source_key = _path_key(entry.source)
        matched = source_index.get(source_key, ())
        if len(matched) > 1:
            names = sorted(_distribution_identity(dist)[0] for dist in matched)
            raise ArtifactInventoryError(
                f"PyInstaller source has ambiguous distribution ownership: {names}"
            )
        if not matched:
            if _is_under_any(entry.source, distribution_roots):
                raise ArtifactInventoryError(
                    "PyInstaller source is inside an installed distribution root "
                    "but has no RECORD ownership"
                )
            continue

        name, version = _distribution_identity(matched[0])
        previous = owners.setdefault(name, version)
        if previous != version:
            raise ArtifactInventoryError(
                f"Distribution {name!r} resolves to conflicting versions"
            )
        owned_entries.setdefault(name, []).append(entry)

    result = dict(sorted(owners.items()))
    _validate_distribution_mapping(result, label="collected distributions")
    if app_dir is not None:
        _verify_final_artifact(Path(app_dir), owned_entries)
    return result


def create_inventory(
    distributions: Mapping[str, str],
    *,
    executable: Path,
    expected: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Create and validate the path-free versioned JSON payload."""

    actual = _normalize_distribution_mapping(
        distributions, label="inventory distributions"
    )
    if expected is not None:
        _require_exact_distributions(actual, expected)
    return {
        "schema": SCHEMA_ID,
        "executable": _executable_record(Path(executable)),
        "distributions": [
            {"name": name, "version": version}
            for name, version in sorted(actual.items())
        ],
    }


def validate_inventory(
    payload: object,
    *,
    expected: Mapping[str, str] | None = None,
    executable: Path | None = None,
) -> dict[str, str]:
    """Validate an inventory payload and return its canonical mapping."""

    if not isinstance(payload, dict) or set(payload) != {
        "schema",
        "executable",
        "distributions",
    }:
        raise ArtifactInventoryError(
            "Inventory must contain only schema, executable and distributions"
        )
    if payload.get("schema") != SCHEMA_ID:
        raise ArtifactInventoryError("Unsupported artifact inventory schema")
    executable_record = _validate_executable_record(payload.get("executable"))
    if executable is not None:
        expected_executable = _executable_record(Path(executable))
        if executable_record != expected_executable:
            raise ArtifactInventoryError(
                "Inventory executable name or SHA-256 does not match final artifact"
            )
    records = payload.get("distributions")
    if not isinstance(records, list):
        raise ArtifactInventoryError("Inventory distributions must be a list")

    actual: dict[str, str] = {}
    for record in records:
        if not isinstance(record, dict) or set(record) != {"name", "version"}:
            raise ArtifactInventoryError(
                "Each inventory distribution must contain only name and version"
            )
        name, version = _normalize_distribution_pair(
            record.get("name"), record.get("version"), label="inventory record"
        )
        if name in actual:
            raise ArtifactInventoryError(f"Duplicate inventory distribution: {name}")
        actual[name] = version

    actual = dict(sorted(actual.items()))
    if expected is not None:
        _require_exact_distributions(actual, expected)
    return actual


def write_inventory(
    path: Path,
    distributions: Mapping[str, str],
    *,
    executable: Path,
    expected: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Write a deterministic UTF-8 inventory after exact validation."""

    payload = create_inventory(distributions, executable=executable, expected=expected)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    return payload


def load_inventory(
    path: Path,
    *,
    expected: Mapping[str, str] | None = None,
    executable: Path | None = None,
) -> dict[str, str]:
    """Load a JSON inventory with duplicate-key and exact-schema checks."""

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ArtifactInventoryError(f"Duplicate JSON field: {key}")
            result[key] = value
        return result

    try:
        payload = json.loads(
            Path(path).read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_keys,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ArtifactInventoryError("Cannot read artifact inventory JSON") from exc
    return validate_inventory(payload, expected=expected, executable=executable)


def load_approved_distributions(
    path: Path,
    *,
    platform: str,
    python_version: str,
) -> dict[str, str]:
    """Load the immutable, human-reviewed distribution approval baseline."""

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ArtifactInventoryError(f"Duplicate JSON field: {key}")
            result[key] = value
        return result

    try:
        payload = json.loads(
            Path(path).read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_keys,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ArtifactInventoryError("Cannot read approved distribution JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {
        "schema",
        "platform",
        "python_version",
        "distributions",
    }:
        raise ArtifactInventoryError("Approval must contain only the exact v1 fields")
    if payload.get("schema") != APPROVAL_SCHEMA_ID:
        raise ArtifactInventoryError("Unsupported distribution approval schema")
    if payload.get("platform") != platform:
        raise ArtifactInventoryError("Distribution approval platform does not match")
    if payload.get("python_version") != python_version:
        raise ArtifactInventoryError(
            "Distribution approval Python version does not match"
        )
    records = payload.get("distributions")
    if not isinstance(records, list):
        raise ArtifactInventoryError("Approval distributions must be a list")
    approved: dict[str, str] = {}
    for record in records:
        if not isinstance(record, dict) or set(record) != {"name", "version"}:
            raise ArtifactInventoryError(
                "Each approved distribution must contain only name and version"
            )
        name, version = _normalize_distribution_pair(
            record.get("name"), record.get("version"), label="approval record"
        )
        if name in approved:
            raise ArtifactInventoryError(f"Duplicate approved distribution: {name}")
        approved[name] = version
    approved = dict(sorted(approved.items()))
    expected_records = [
        {"name": name, "version": version} for name, version in approved.items()
    ]
    if records != expected_records:
        raise ArtifactInventoryError(
            "Approved distributions must be canonical and deterministically sorted"
        )
    return approved


def _executable_record(executable: Path) -> dict[str, str]:
    if not executable.is_file() or executable.suffix.casefold() != ".exe":
        raise ArtifactInventoryError("Final PyInstaller executable does not exist")
    return {"name": executable.name, "sha256": _sha256_file(executable)}


def _validate_executable_record(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"name", "sha256"}:
        raise ArtifactInventoryError(
            "Inventory executable must contain only name and sha256"
        )
    name = value.get("name")
    sha256 = value.get("sha256")
    if (
        not isinstance(name, str)
        or not name
        or name != Path(name).name
        or Path(name).suffix.casefold() != ".exe"
        or "/" in name
        or "\\" in name
        or ":" in name
    ):
        raise ArtifactInventoryError("Inventory has an invalid executable name")
    if not isinstance(sha256, str) or not _SHA256_PATTERN.fullmatch(sha256):
        raise ArtifactInventoryError("Inventory has an invalid executable SHA-256")
    return {"name": name, "sha256": sha256}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ArtifactInventoryError(
            "Cannot hash final PyInstaller executable"
        ) from exc
    return digest.hexdigest()


def _read_analysis_entries(path: Path) -> list[_AnalysisEntry]:
    try:
        raw = path.read_text(encoding="utf-8")
        toc = ast.literal_eval(raw)
    except (OSError, UnicodeError, SyntaxError, ValueError) as exc:
        raise ArtifactInventoryError("Cannot parse PyInstaller Analysis TOC") from exc
    if not isinstance(toc, (tuple, list)) or len(toc) <= max(
        _ANALYSIS_GROUP_INDEX.values()
    ):
        raise ArtifactInventoryError("Unsupported PyInstaller Analysis TOC structure")

    entries: list[_AnalysisEntry] = []
    for group, index in _ANALYSIS_GROUP_INDEX.items():
        group_entries = toc[index]
        if not isinstance(group_entries, (tuple, list)):
            raise ArtifactInventoryError(
                f"Analysis TOC group {group} is not a sequence"
            )
        for item in group_entries:
            if not isinstance(item, (tuple, list)) or len(item) < 2:
                raise ArtifactInventoryError(
                    f"Analysis TOC group {group} has an invalid entry"
                )
            destination, source = item[0], item[1]
            if not isinstance(destination, str) or not destination:
                raise ArtifactInventoryError(
                    f"Analysis TOC group {group} has an invalid destination"
                )
            if not isinstance(source, str) or not source:
                raise ArtifactInventoryError(
                    f"Analysis TOC group {group} has an invalid source"
                )
            source_path = Path(source)
            if not source_path.is_absolute():
                source_path = path.parent / source_path
            entries.append(
                _AnalysisEntry(
                    group=group,
                    destination=destination,
                    source=source_path.resolve(strict=False),
                )
            )
    return entries


def _index_distribution_files(
    installed: Iterable[metadata.Distribution],
) -> tuple[dict[str, list[metadata.Distribution]], tuple[Path, ...]]:
    index: dict[str, list[metadata.Distribution]] = {}
    roots = _standard_distribution_roots()
    for distribution in installed:
        try:
            root = Path(distribution.locate_file(".")).resolve(strict=False)
            files = distribution.files
        except (OSError, TypeError, ValueError) as exc:
            raise ArtifactInventoryError(
                "Cannot inspect installed distribution file ownership"
            ) from exc
        if any(
            part.casefold() in {"site-packages", "dist-packages"} for part in root.parts
        ):
            roots.add(root)
        if files is None:
            continue
        for relative in files:
            try:
                located = Path(distribution.locate_file(relative)).resolve(strict=False)
            except (OSError, TypeError, ValueError) as exc:
                raise ArtifactInventoryError(
                    "Cannot resolve an installed distribution file"
                ) from exc
            owners = index.setdefault(_path_key(located), [])
            if distribution not in owners:
                owners.append(distribution)
    return index, tuple(sorted(roots, key=lambda item: str(item).casefold()))


def _standard_distribution_roots() -> set[Path]:
    candidates: set[str] = set()
    paths = sysconfig.get_paths()
    candidates.update(
        str(paths[key]) for key in ("purelib", "platlib") if paths.get(key)
    )
    try:
        candidates.update(site.getsitepackages())
    except AttributeError:
        pass
    user_site = site.getusersitepackages()
    if isinstance(user_site, str):
        candidates.add(user_site)
    else:
        candidates.update(user_site)
    return {Path(candidate).resolve(strict=False) for candidate in candidates}


def _distribution_identity(distribution: metadata.Distribution) -> tuple[str, str]:
    try:
        raw_name = distribution.metadata["Name"]
        raw_version = distribution.version
    except (KeyError, TypeError) as exc:
        raise ArtifactInventoryError(
            "Distribution metadata has no name or version"
        ) from exc
    return _normalize_distribution_pair(
        raw_name, raw_version, label="distribution metadata"
    )


def _normalize_distribution_pair(
    raw_name: object,
    raw_version: object,
    *,
    label: str,
) -> tuple[str, str]:
    if not isinstance(raw_name, str) or not _DISTRIBUTION_NAME_PATTERN.fullmatch(
        raw_name
    ):
        raise ArtifactInventoryError(f"{label} has an invalid distribution name")
    if not isinstance(raw_version, str) or not raw_version:
        raise ArtifactInventoryError(f"{label} has an invalid distribution version")
    if Path(raw_version).is_absolute() or any(
        separator in raw_version for separator in ("/", "\\")
    ):
        raise ArtifactInventoryError(f"{label} version must not contain a path")
    try:
        Version(raw_version)
    except InvalidVersion as exc:
        raise ArtifactInventoryError(
            f"{label} has an invalid distribution version"
        ) from exc
    return canonicalize_name(raw_name), raw_version


def _normalize_distribution_mapping(
    value: Mapping[str, str],
    *,
    label: str,
) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ArtifactInventoryError(f"{label} must be a mapping")
    normalized: dict[str, str] = {}
    for raw_name, raw_version in value.items():
        name, version = _normalize_distribution_pair(raw_name, raw_version, label=label)
        if name in normalized:
            raise ArtifactInventoryError(f"{label} contains duplicate name: {name}")
        normalized[name] = version
    return dict(sorted(normalized.items()))


def _validate_distribution_mapping(value: Mapping[str, str], *, label: str) -> None:
    normalized = _normalize_distribution_mapping(value, label=label)
    if dict(value) != normalized:
        raise ArtifactInventoryError(f"{label} is not canonical and deterministic")


def _require_exact_distributions(
    actual: Mapping[str, str], expected: Mapping[str, str]
) -> None:
    approved = _normalize_distribution_mapping(expected, label="expected distributions")
    if dict(actual) == approved:
        return
    extra = sorted(set(actual) - set(approved))
    missing = sorted(set(approved) - set(actual))
    drift = sorted(
        name for name in set(actual) & set(approved) if actual[name] != approved[name]
    )
    raise ArtifactInventoryError(
        f"Artifact distributions differ from approval: extra={extra}, "
        f"missing={missing}, version_drift={drift}"
    )


def _verify_final_artifact(
    app_dir: Path, owned_entries: Mapping[str, Sequence[_AnalysisEntry]]
) -> None:
    if not app_dir.is_dir():
        raise ArtifactInventoryError("PyInstaller app directory does not exist")
    archive_names, pyz_names = _read_final_archive_names(app_dir)
    for distribution, entries in owned_entries.items():
        if any(
            _entry_exists_in_final_app(entry, app_dir, archive_names, pyz_names)
            for entry in entries
        ):
            continue
        raise ArtifactInventoryError(
            f"No final-artifact evidence found for distribution {distribution!r}"
        )


def _read_final_archive_names(app_dir: Path) -> tuple[set[str], set[str]]:
    executables = sorted(app_dir.glob("*.exe"))
    if len(executables) != 1:
        raise ArtifactInventoryError(
            "PyInstaller app directory must contain exactly one top-level executable"
        )
    try:
        from PyInstaller.archive.readers import (
            ArchiveReadError,
            CArchiveReader,
            NotAnArchiveError,
        )
    except ImportError as exc:
        raise ArtifactInventoryError(
            "PyInstaller archive reader is unavailable"
        ) from exc
    try:
        archive = CArchiveReader(str(executables[0]))
    except (ArchiveReadError, OSError, ValueError) as exc:
        raise ArtifactInventoryError(
            "Cannot inspect final PyInstaller CArchive"
        ) from exc

    archive_names = set(archive.toc)
    pyz_names: set[str] = set()
    for name in archive.toc:
        try:
            embedded = archive.open_embedded_archive(name)
        except (ArchiveReadError, KeyError, NotAnArchiveError):
            continue
        pyz_names.update(embedded.toc)
    return archive_names, pyz_names


def _entry_exists_in_final_app(
    entry: _AnalysisEntry,
    app_dir: Path,
    archive_names: set[str],
    pyz_names: set[str],
) -> bool:
    destination = PurePosixPath(entry.destination.replace("\\", "/"))
    if (
        destination.is_absolute()
        or ".." in destination.parts
        or (destination.parts and ":" in destination.parts[0])
    ):
        raise ArtifactInventoryError("Analysis TOC contains an unsafe destination")
    relative = Path(*destination.parts)
    if (app_dir / relative).is_file() or (app_dir / "_internal" / relative).is_file():
        return True

    archive_candidates = {
        entry.destination,
        entry.destination.removesuffix(".py"),
        entry.destination.replace("\\", "/"),
    }
    module_candidates = {
        entry.destination,
        entry.destination.removesuffix(".py").replace("/", ".").replace("\\", "."),
    }
    return bool(archive_candidates & archive_names or module_candidates & pyz_names)


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.normpath(str(path.resolve(strict=False))))


def _is_under_any(path: Path, roots: Sequence[Path]) -> bool:
    resolved = path.resolve(strict=False)
    for root in roots:
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        return True
    return False
