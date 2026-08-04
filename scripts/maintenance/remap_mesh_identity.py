from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping

from netconsole.core.paths import PathResolver
from netconsole.core.runtime_environment import data_root as default_data_root
from netconsole.repositories.mesh_mr_repository import MeshMrRepository
from netconsole.services.ap_identity.normalizers import normalize_mac, normalize_mac_key
from netconsole.services.mesh_peer_mapping_service import MeshPeerMappingService
from netconsole.services.mesh_source_rebuild_service import MeshSourceRebuildService


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


def build_plan(
    paths: PathResolver,
    site_name: str,
    *,
    profile_filter: str = "",
    source_filter: int | None = None,
) -> list[MeshIdentityRemapPlanEntry]:
    profiles = _load_profiles_readonly(paths.mesh_catalog_path(site_name))
    entries: list[MeshIdentityRemapPlanEntry] = []
    mapping_service = MeshPeerMappingService(site_name, paths)
    revision = mapping_service.current_identity_revision()
    for profile in profiles:
        if profile_filter and profile_filter not in {
            profile["mr_id"],
            profile["display_name"],
            profile["safe_folder_name"],
        }:
            continue
        profile_root = paths.mesh_mr_root(
            site_name,
            profile["safe_folder_name"],
        ).resolve()
        source_index = paths.mesh_mr_db_path(
            site_name,
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
                entries.append(
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
                    )
                )
                continue
            try:
                repo = MeshMrRepository(detail_path, read_only=True)
                peers = repo.distinct_peer_macs()
                mappings = mapping_service.build_rows(peers)
                current = _current_status_counts(detail_path)
                expected, changed = _expected_projection(detail_path, mappings)
            except (OSError, RuntimeError, sqlite3.Error, ValueError) as exc:
                entries.append(
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
                    )
                )
                continue
            entries.append(
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
                )
            )
    return entries


def apply_plan(
    paths: PathResolver,
    site_name: str,
    entries: list[MeshIdentityRemapPlanEntry],
) -> dict[str, object]:
    service = MeshSourceRebuildService(paths)
    results: list[dict[str, object]] = []
    succeeded = failed = skipped = 0
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
            result = service.rebuild_source(site_name, entry.session_id)
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
        "site": site_name,
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
    return {
        "mode": "dry-run",
        "site": site_name,
        "sources_scanned": len(entries),
        "eligible_sources": sum(1 for entry in entries if entry.eligible),
        "distinct_peers": sum(entry.distinct_peers for entry in entries),
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
        "entries": [asdict(entry) for entry in entries],
    }


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
        rows = connection.execute(
            """
            SELECT peer_mac_normalized, peer_ap_name, peer_ap_mac, peer_site,
                   peer_section, peer_radio_id, peer_match_rule,
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
    args = parser.parse_args()
    if args.source is not None and not args.profile:
        parser.error("--source 必须与 --profile 一起使用")
    paths = PathResolver(data_root=(args.data_root or default_data_root()).resolve())
    planned = build_plan(
        paths,
        args.site,
        profile_filter=args.profile,
        source_filter=args.source,
    )
    if args.apply:
        result = apply_plan(paths, args.site, planned)
        _print(result)
        return 1 if result["failed"] else 0
    _print(manifest(planned, site_name=args.site))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
