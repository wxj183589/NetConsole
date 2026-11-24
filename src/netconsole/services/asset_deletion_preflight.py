"""Asset deletion inspection, always fail closed; no authorization tokens or cache."""

from datetime import datetime, timedelta, timezone
import sqlite3
import time
from netconsole.core.site_identity import validate_site_name
from netconsole.repositories.asset_reference_repository import AssetReferenceRepository
from netconsole.repositories.rail_relationship_repository import (
    RailRelationshipRepository,
)


class AssetDeletionPreflightService:
    def __init__(self, paths, *, budget_seconds=0.25):
        self.paths = paths
        self.references = AssetReferenceRepository(paths)
        self.relationships = RailRelationshipRepository(paths)
        self.budget_seconds = budget_seconds

    def inspect(self, site_id, request):
        site_id = validate_site_name(site_id)
        checked = datetime.now(timezone.utc)
        result = dict(
            request_id=request.request_id,
            source=request.source,
            device_uuid=request.device_uuid,
            device=None,
            current_asset_state="unknown",
            current_relationships=0,
            historical_relationships=0,
            external_reference_checks={},
            can_delete=False,
            status="PREFLIGHT_FAILED",
            blockers=[],
            revision="",
            checked_at=checked.isoformat(),
            expires_at=(checked + timedelta(seconds=30)).isoformat(),
            separate_authorization_required=True,
            historical_evidence_check="NOT_VERIFIED",
            result_reusable_for_deletion=False,
        )
        try:
            self.references.identity(
                site_id
            )  # Validate path before opening revision authority.
            revision = self.relationships.revision(site_id)
            result["revision"] = revision
            if revision != request.base_revision:
                result.update(
                    status="BLOCKED_BY_REVISION_CONFLICT",
                    blockers=["revision changed; repeat preflight"],
                )
                return result
            device = self.references.device(site_id, request.device_uuid)
            if not device:
                result["blockers"].append("device missing")
                return result
            result["device"] = device
            result["current_asset_state"] = device["work_scope_status"]
            current = self.relationships.list_current(
                site_id, entity_uid=request.device_uuid
            )
            historical = self.relationships.list_history(
                site_id, entity_uid=request.device_uuid, page_size=1
            )
            result.update(
                current_relationships=current.total,
                historical_relationships=historical.total,
            )
            deadline = time.monotonic() + self.budget_seconds
            checks = result["external_reference_checks"]
            sources = {
                "site_facts": self.paths.site_db_path(site_id),
                "tasks": self.paths.site_tasks_db_path(site_id),
                "ground": self.paths.ground_unattended_db_path(site_id),
                "mesh_index": self.paths.mesh_catalog_path(site_id),
            }
            for domain, path in sources.items():
                try:
                    checks[domain] = self.references.sql_references(
                        path, device, deadline
                    )
                except (OSError, ValueError, sqlite3.Error, TimeoutError):
                    checks[domain] = dict(
                        status="NOT_VERIFIED",
                        matches=[],
                        reason="reference query failed or exceeded budget",
                    )
            try:
                checks["online_mr"] = self.references.session_references(
                    site_id, device, deadline
                )
            except (OSError, ValueError, sqlite3.Error, TimeoutError):
                checks["online_mr"] = dict(
                    status="NOT_VERIFIED",
                    matches=[],
                    reason="session index failed or exceeded budget",
                )
            checks["archives_reports_mac_aliases"] = dict(
                status="NOT_VERIFIED",
                matches=[],
                reason="raw logs, JSON payloads, MAC/SN aliases, exported files and archived evidence are not exhaustively indexed",
            )
            if self.relationships.revision(site_id) != revision:
                result.update(
                    status="BLOCKED_BY_REVISION_CONFLICT",
                    blockers=["concurrent relationship or asset change"],
                )
                return result
            if time.monotonic() >= deadline:
                result.update(
                    status="PREFLIGHT_FAILED",
                    blockers=["preflight deadline exceeded; sources incomplete"],
                )
            elif current.total:
                result.update(
                    status="BLOCKED_BY_ACTIVE_RELATION",
                    blockers=["active engineering references"],
                )
            elif historical.total:
                result.update(
                    status="BLOCKED_BY_HISTORY_REFERENCE",
                    blockers=["engineering history retained"],
                )
            elif any(v["matches"] for v in checks.values()):
                result.update(
                    status="BLOCKED_BY_EXTERNAL_REFERENCE",
                    blockers=["known external evidence exists"],
                )
            else:
                result.update(
                    status="BLOCKED_BY_UNVERIFIED_SOURCE",
                    blockers=["external evidence coverage incomplete"],
                )
        except (OSError, ValueError, RuntimeError, sqlite3.Error):
            result["blockers"].append(
                "identity, revision or engineering reference inspection failed"
            )
        return result
