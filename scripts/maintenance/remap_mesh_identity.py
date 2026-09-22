from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Mapping

from netconsole.core.paths import PathResolver
from netconsole.core.runtime_environment import (
    data_root as default_data_root,
)
from netconsole.repositories.mesh_mr_repository import PARSER_VERSION, MeshMrRepository
from netconsole.services.ap_identity.normalizers import normalize_mac, normalize_mac_key
from netconsole.services.mesh_peer_mapping_service import MeshPeerMappingService
from netconsole.services.mesh_source_rebuild_service import MeshSourceRebuildService
from netconsole.services.mesh_write_authority import (
    MESH_IDENTITY_REMAP_AUTHORIZED,
    MESH_IDENTITY_REMAP_OPERATION,
    MeshProductionSiteScope,
    mesh_operation_lock,
    require_mesh_profile_scope,
    require_mesh_write_authority,
    resolve_mesh_production_scope,
)


@dataclass(frozen=True)
class MeshIdentityRemapPlanEntry:
    session_id: str
    profile_id: str
    profile_name: str
    source_file_id: int
    eligible: bool
    detail: str
    distinct_peers: int
    current_matched: int
    current_unresolved: int
    current_ambiguous: int
    expected_matched: int
    expected_unresolved: int
    expected_ambiguous: int
    expected_changed_link_rows: int
    identity_index_revision: int
    peer_keys: frozenset[str]
    peer_set_digest: str = ""
    canonical_site_id: str = ""
    site_directory_name: str = ""
    index_sha256: str = ""
    index_schema: str = ""
    source_revision: str = ""
    parsed_db_sha256: str = ""
    parsed_schema: str = ""
    parser_schema: str = PARSER_VERSION
    operation: str = MESH_IDENTITY_REMAP_OPERATION
    plan_digest: str = ""


def build_plan(
    paths: PathResolver,
    site_name: str,
    *,
    profile_filter: str = "",
    source_filter: int | None = None,
) -> list[MeshIdentityRemapPlanEntry]:
    scope = resolve_mesh_production_scope(paths, site_name)
    site_directory_name = scope.directory_name
    profiles = _load_profiles_readonly(paths.mesh_catalog_path(site_directory_name))
    entries: list[MeshIdentityRemapPlanEntry] = []
    mapping_service = MeshPeerMappingService(site_directory_name, paths)
    revision = mapping_service.current_identity_revision()
    for profile in profiles:
        if profile_filter and profile_filter not in {
            profile["mr_id"],
            profile["display_name"],
            profile["safe_folder_name"],
        }:
            continue
        require_mesh_profile_scope(paths, scope, profile["safe_folder_name"])
        profile_root = paths.mesh_mr_root(
            site_directory_name,
            profile["safe_folder_name"],
        ).resolve()
        source_index = paths.mesh_mr_db_path(
            site_directory_name,
            profile["safe_folder_name"],
        ).resolve()
        _require_inside(source_index, profile_root, "source index")
        for source in _load_sources_readonly(source_index):
            source_id = int(source["id"])
            if source_filter is not None and source_id != source_filter:
                continue
            session_id = f"{profile['mr_id']}:{source_id}"
            detail_path = _detail_path(profile_root, source)
            if detail_path is None:
                entries.append(_bind_entry(
                    MeshIdentityRemapPlanEntry(
                        session_id=session_id,
                        profile_id=profile["mr_id"],
                        profile_name=profile["display_name"],
                        source_file_id=source_id,
                        eligible=False,
                        detail="parsed detail 不存在或越过 Profile 目录",
                        distinct_peers=0,
                        current_matched=0,
                        current_unresolved=0,
                        current_ambiguous=0,
                        expected_matched=0,
                        expected_unresolved=0,
                        expected_ambiguous=0,
                        expected_changed_link_rows=0,
                        identity_index_revision=revision,
                        peer_keys=frozenset(),
                    ),
                    scope=scope,
                    source_index=source_index,
                    source=source,
                    detail_path=None,
                ))
                continue
            try:
                repo = MeshMrRepository(detail_path, read_only=True)
                peers = repo.distinct_peer_macs()
                mappings = mapping_service.build_rows(peers)
                current = _current_status_counts(detail_path)
                expected, changed = _expected_projection(detail_path, mappings)
            except (OSError, RuntimeError, sqlite3.Error, ValueError) as exc:
                entries.append(_bind_entry(
                    MeshIdentityRemapPlanEntry(
                        session_id=session_id,
                        profile_id=profile["mr_id"],
                        profile_name=profile["display_name"],
                        source_file_id=source_id,
                        eligible=False,
                        detail=str(exc),
                        distinct_peers=0,
                        current_matched=0,
                        current_unresolved=0,
                        current_ambiguous=0,
                        expected_matched=0,
                        expected_unresolved=0,
                        expected_ambiguous=0,
                        expected_changed_link_rows=0,
                        identity_index_revision=revision,
                        peer_keys=frozenset(),
                    ),
                    scope=scope,
                    source_index=source_index,
                    source=source,
                    detail_path=detail_path,
                ))
                continue
            entries.append(_bind_entry(
                MeshIdentityRemapPlanEntry(
                    session_id=session_id,
                    profile_id=profile["mr_id"],
                    profile_name=profile["display_name"],
                    source_file_id=source_id,
                    eligible=True,
                    detail="",
                    distinct_peers=len(
                        {
                            key
                            for peer in peers
                            if (key := normalize_mac_key(peer))
                        }
                    ),
                    current_matched=current["matched"],
                    current_unresolved=current["unresolved"],
                    current_ambiguous=current["ambiguous"],
                    expected_matched=expected["matched"],
                    expected_unresolved=expected["unresolved"],
                    expected_ambiguous=expected["ambiguous"],
                    expected_changed_link_rows=changed,
                    identity_index_revision=revision,
                    peer_keys=frozenset(
                        key
                        for peer in peers
                        if (key := normalize_mac_key(peer))
                    ),
                ),
                scope=scope,
                source_index=source_index,
                source=source,
                detail_path=detail_path,
            ))
    return entries


def apply_plan(
    paths: PathResolver,
    site_name: str,
    entries: list[MeshIdentityRemapPlanEntry],
    *,
    allow_production_write: bool = False,
    authorization_token: str = "",
) -> dict[str, object]:
    scope = require_mesh_write_authority(
        paths,
        site_name,
        operation=MESH_IDENTITY_REMAP_OPERATION,
        allow_production_write=allow_production_write,
        authorization_token=authorization_token,
    )
    service = MeshSourceRebuildService(paths)
    results: list[dict[str, object]] = []
    succeeded = failed = skipped = 0
    with mesh_operation_lock(
        paths,
        scope,
        MESH_IDENTITY_REMAP_OPERATION,
    ):
        _validate_plan(paths, scope, entries)
        for entry in entries:
            if not entry.eligible:
                skipped += 1
                results.append(
                    {
                        "session_id": entry.session_id,
                        "status": "skipped",
                        "detail": entry.detail,
                    }
                )
                continue
            try:
                result = service.remap_identity_only(
                    scope.directory_name,
                    entry.session_id,
                    expected_identity_index_revision=entry.identity_index_revision,
                    expected_peer_keys=entry.peer_keys,
                )
            except Exception as exc:
                failed += 1
                results.append(
                    {
                        "session_id": entry.session_id,
                        "status": "failed",
                        "detail": str(exc),
                    }
                )
                continue
            succeeded += 1
            results.append(
                {
                    "session_id": entry.session_id,
                    "status": "succeeded",
                    "identity_remap": result.get("identity_remap") or {},
                }
            )
    return {
        "mode": "applied",
        "site": scope.canonical_site_id,
        "sources_scanned": len(entries),
        "succeeded": succeeded,
        "failed": failed,
        "skipped": skipped,
        "results": results,
    }


def manifest(
    entries: list[MeshIdentityRemapPlanEntry],
    *,
    site_name: str,
) -> dict[str, object]:
    distinct_peer_keys = {
        peer
        for entry in entries
        for peer in entry.peer_keys
    }
    return {
        "schema_version": 2,
        "mode": "dry-run",
        "site": next((entry.canonical_site_id for entry in entries if entry.canonical_site_id), site_name),
        "operation": MESH_IDENTITY_REMAP_OPERATION,
        "sources_scanned": len(entries),
        "eligible_sources": sum(1 for entry in entries if entry.eligible),
        "distinct_peers": len(distinct_peer_keys),
        "distinct_peer_occurrences": sum(
            entry.distinct_peers for entry in entries
        ),
        "current": {
            "matched": sum(entry.current_matched for entry in entries),
            "unresolved": sum(entry.current_unresolved for entry in entries),
            "ambiguous": sum(entry.current_ambiguous for entry in entries),
        },
        "expected": {
            "matched": sum(entry.expected_matched for entry in entries),
            "unresolved": sum(entry.expected_unresolved for entry in entries),
            "ambiguous": sum(entry.expected_ambiguous for entry in entries),
            "changed_link_rows": sum(
                entry.expected_changed_link_rows for entry in entries
            ),
        },
        "entries": [
            {
                key: value
                for key, value in asdict(entry).items()
                if key != "peer_keys"
            }
            for entry in entries
        ],
    }


def _bind_entry(
    entry: MeshIdentityRemapPlanEntry,
    *,
    scope: MeshProductionSiteScope,
    source_index: Path,
    source: Mapping[str, object],
    detail_path: Path | None,
) -> MeshIdentityRemapPlanEntry:
    bound = replace(
        entry,
        canonical_site_id=scope.canonical_site_id,
        site_directory_name=scope.directory_name,
        index_sha256=_sha256(source_index),
        index_schema=_sqlite_schema(source_index),
        source_revision=_source_revision(source_index, source),
        parsed_db_sha256=_sha256(detail_path) if detail_path is not None and detail_path.is_file() else "",
        parsed_schema=_sqlite_schema(detail_path) if detail_path is not None else "",
        parser_schema=PARSER_VERSION,
        operation=MESH_IDENTITY_REMAP_OPERATION,
        peer_set_digest=_peer_set_digest(entry.peer_keys),
        plan_digest="",
    )
    return replace(bound, plan_digest=_plan_digest(bound))


def _validate_plan(
    paths: PathResolver,
    scope: MeshProductionSiteScope,
    entries: list[MeshIdentityRemapPlanEntry],
) -> None:
    mapping_service = MeshPeerMappingService(scope.directory_name, paths)
    for entry in entries:
        if entry.operation != MESH_IDENTITY_REMAP_OPERATION:
            raise RuntimeError("MESH identity remap plan operation mismatch")
        if entry.parser_schema != PARSER_VERSION:
            raise RuntimeError("MESH identity remap parser schema changed")
        if entry.canonical_site_id != scope.canonical_site_id:
            raise RuntimeError("MESH identity remap plan canonical site changed")
        if entry.site_directory_name != scope.directory_name:
            raise RuntimeError("MESH identity remap plan site directory changed")
        if not entry.plan_digest or _plan_digest(entry) != entry.plan_digest:
            raise RuntimeError("MESH identity remap plan digest invalid or changed")
        profile_root = paths.mesh_mr_root(scope.directory_name, entry.profile_name).resolve()
        source_index = paths.mesh_mr_db_path(scope.directory_name, entry.profile_name).resolve()
        # Profile display names are not filesystem identities.  Resolve the
        # profile from the catalog/index and use the stored safe folder name.
        profiles = _load_profiles_readonly(paths.mesh_catalog_path(scope.directory_name))
        profile = next((item for item in profiles if item["mr_id"] == entry.profile_id), None)
        if profile is None:
            raise RuntimeError("MESH identity remap Profile changed")
        profile_root = paths.mesh_mr_root(scope.directory_name, profile["safe_folder_name"]).resolve()
        source_index = paths.mesh_mr_db_path(scope.directory_name, profile["safe_folder_name"]).resolve()
        if not profile_root.is_relative_to(scope.site_root):
            raise RuntimeError("MESH identity remap Profile crossed canonical site")
        sources = _load_sources_readonly(source_index)
        source = next((item for item in sources if int(item.get("id") or 0) == entry.source_file_id), None)
        if source is None or _source_revision(source_index, source) != entry.source_revision:
            raise RuntimeError(f"MESH identity remap source revision changed: {entry.session_id}")
        detail_path = _detail_path(profile_root, source)
        if not entry.eligible or detail_path is None:
            continue
        actual_keys = _peer_keys(detail_path)
        if (
            _sha256(source_index) != entry.index_sha256
            or _sqlite_schema(source_index) != entry.index_schema
            or _sha256(detail_path) != entry.parsed_db_sha256
            or _sqlite_schema(detail_path) != entry.parsed_schema
            or actual_keys != set(entry.peer_keys)
            or _peer_set_digest(actual_keys) != entry.peer_set_digest
        ):
            raise RuntimeError(f"MESH identity remap parsed/index identity changed: {entry.session_id}")
        if mapping_service.current_identity_revision() != entry.identity_index_revision:
            raise RuntimeError("MESH identity remap expected identity revision changed")


def _peer_keys(path: Path) -> set[str]:
    repo = MeshMrRepository(path, read_only=True)
    return {
        key
        for peer in repo.distinct_peer_macs()
        if (key := normalize_mac_key(peer))
    }


def _sha256(path: Path) -> str:
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sqlite_schema(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True) as connection:
            rows = connection.execute(
                "SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type, name"
            ).fetchall()
            return hashlib.sha256(json.dumps(rows, default=str, sort_keys=True).encode()).hexdigest()
    except sqlite3.Error:
        return "invalid"


def _source_revision(path: Path, source: Mapping[str, object]) -> str:
    values = {
        key: source.get(key)
        for key in (
            "id",
            "sha256",
            "raw_sha256",
            "content_sha256",
            "parsed_db_path",
            "parsed_relative_path",
            "parser_version",
            "identity_index_revision",
            "identity_mapped_at",
            "identity_mapping_status",
        )
    }
    values["index_sha256"] = _sha256(path)
    return hashlib.sha256(
        json.dumps(values, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


def _plan_digest(entry: MeshIdentityRemapPlanEntry) -> str:
    payload = asdict(entry)
    payload["peer_keys"] = sorted(entry.peer_keys)
    payload["plan_digest"] = ""
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


def _peer_set_digest(peer_keys: set[str] | frozenset[str]) -> str:
    return hashlib.sha256(
        json.dumps(sorted(peer_keys), ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def _load_profiles_readonly(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with _readonly_connection(path) as connection:
        rows = connection.execute(
            """
            SELECT mr_id, display_name, safe_folder_name
            FROM mr_profiles ORDER BY display_name COLLATE NOCASE
            """
        ).fetchall()
    return [
        {
            "mr_id": str(row["mr_id"]),
            "display_name": str(row["display_name"]),
            "safe_folder_name": str(row["safe_folder_name"]),
        }
        for row in rows
    ]


def _load_sources_readonly(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        return []
    with _readonly_connection(path) as connection:
        rows = connection.execute("SELECT * FROM source_files ORDER BY id").fetchall()
    return [dict(row) for row in rows]


def _detail_path(
    profile_root: Path,
    source: Mapping[str, object],
) -> Path | None:
    raw_value = str(
        source.get("parsed_db_path") or source.get("parsed_relative_path") or ""
    ).strip()
    if not raw_value:
        return None
    candidate = Path(raw_value)
    if not candidate.is_absolute():
        candidate = profile_root / candidate
    candidate = candidate.resolve()
    _require_inside(candidate, profile_root, "parsed detail")
    return candidate if candidate.is_file() else None


def _current_status_counts(path: Path) -> dict[str, int]:
    counts = {"matched": 0, "unresolved": 0, "ambiguous": 0}
    with _readonly_connection(path) as connection:
        rows = connection.execute(
            """
            SELECT COALESCE(NULLIF(peer_identity_status, ''), 'unresolved') AS status,
                   COUNT(*) AS row_count
            FROM mesh_links
            GROUP BY COALESCE(NULLIF(peer_identity_status, ''), 'unresolved')
            """
        ).fetchall()
    for row in rows:
        counts[str(row["status"])] = int(row["row_count"] or 0)
    return counts


def _expected_projection(
    path: Path,
    mappings: list[dict[str, object]],
) -> tuple[dict[str, int], int]:
    by_key = {
        key: mapping
        for mapping in mappings
        if (key := normalize_mac_key(mapping.get("peer_mac_normalized")))
    }
    counts = {"matched": 0, "unresolved": 0, "ambiguous": 0}
    changed = 0
    with _readonly_connection(path) as connection:
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(mesh_links)")
        }

        def projection(column: str) -> str:
            return column if column in columns else f"NULL AS {column}"

        rows = connection.execute(
            f"""
            SELECT peer_mac_normalized, peer_ap_name, peer_ap_mac, peer_site,
                   {projection("peer_section")}, peer_radio_id, peer_match_rule,
                   peer_identity_status, peer_identity_source,
                   peer_identity_reason
            FROM mesh_links
            """
        )
        for row in rows:
            mapping = by_key.get(str(row["peer_mac_normalized"] or ""))
            if mapping is None:
                continue
            status = str(mapping.get("identity_status") or "unresolved")
            counts[status] = counts.get(status, 0) + 1
            expected = (
                str(mapping.get("peer_ap_name") or ""),
                normalize_mac(mapping.get("peer_ap_mac")) or "",
                str(mapping.get("peer_site") or ""),
                str(mapping.get("peer_section") or mapping.get("belong_section") or ""),
                mapping.get("peer_radio_id"),
                str(mapping.get("match_rule") or "unresolved"),
                status,
                str(mapping.get("identity_source") or ""),
                str(mapping.get("identity_reason") or ""),
            )
            current = tuple(row[index] for index in range(1, 10))
            if current != expected:
                changed += 1
    return counts, changed


def _readonly_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        f"{path.resolve().as_uri()}?mode=ro",
        uri=True,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _require_inside(candidate: Path, root: Path, label: str) -> None:
    if candidate != root and not candidate.is_relative_to(root):
        raise RuntimeError(f"{label} 越过允许目录")


def _print(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="对历史 MESH parsed 来源执行已验证的 AP Identity-only remap"
    )
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument("--site", required=True)
    parser.add_argument("--profile", default="")
    parser.add_argument("--source", type=int)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--allow-production-write",
        action="store_true",
        help="明确授权对 production 数据根执行身份重建",
    )
    parser.add_argument(
        "--authorization-token",
        default="",
        help=(
            "MESH operation-specific production capability token "
            f"(expected: {MESH_IDENTITY_REMAP_AUTHORIZED})"
        ),
    )
    args = parser.parse_args()
    if args.source is not None and not args.profile:
        parser.error("--source 必须与 --profile 一起使用")
    paths = PathResolver(data_root=(args.data_root or default_data_root()).resolve())
    if args.apply:
        scope = require_mesh_write_authority(
            paths,
            args.site,
            operation=MESH_IDENTITY_REMAP_OPERATION,
            allow_production_write=args.allow_production_write,
            authorization_token=args.authorization_token,
        )
    else:
        scope = resolve_mesh_production_scope(paths, args.site)
    planned = build_plan(
        paths,
        args.site,
        profile_filter=args.profile,
        source_filter=args.source,
    )
    if args.apply:
        result = apply_plan(
            paths,
            args.site,
            planned,
            allow_production_write=args.allow_production_write,
            authorization_token=args.authorization_token,
        )
        _print(result)
        return 1 if result["failed"] else 0
    _print(manifest(planned, site_name=scope.canonical_site_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
