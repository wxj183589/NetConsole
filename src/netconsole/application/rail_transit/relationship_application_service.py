from __future__ import annotations

from netconsole.core.paths import PathResolver
from netconsole.core.site_identity import validate_site_name
from netconsole.models.api.rail_relationship import RelationshipMutationRequest
from netconsole.repositories.rail_relationship_repository import (
    RailRelationshipRepository,
    RelationshipError,
)
from netconsole.services.rail_transit.base_data_write_guard import (
    BaseDataWriteGuard,
    BaseDataWriteGuardError,
)

RelationshipApplicationError = RelationshipError


class RailRelationshipApplicationService:
    """Authorize mutations; the Repository owns transactions and persisted facts."""

    def __init__(
        self, paths: PathResolver, guard: BaseDataWriteGuard, query=None
    ) -> None:
        self.paths = paths
        self.guard = guard
        self.repository = RailRelationshipRepository(paths)
        self.query = query

    def list_current(self, site_id: str, **filters):
        return self.repository.list_current(validate_site_name(site_id), **filters)

    def list_history(self, site_id: str, **filters):
        return self.repository.list_history(validate_site_name(site_id), **filters)

    def catalog(self, site_id: str):
        site_id = validate_site_name(site_id)
        # Canonical IDs are copied from formal base data only, never inferred from names.
        before = self.repository.revision(site_id)
        nodes = []
        sections = []
        if self.query is not None:
            nodes = [
                n.model_dump(mode="json")
                for n in self.query.infrastructure(site_id).nodes if n.kind != "section"
            ]
            page = 1
            while True:
                result = self.query.list_sections(site_id, page=page, page_size=200)
                sections.extend(
                    s.model_dump(mode="json")
                    for s in result.items
                    if s.source_kind != "legacy_ap_derived"
                )
                if page * 200 >= result.total:
                    break
                page += 1
        result = self.repository.catalog(site_id, nodes=nodes, sections=sections)
        if result["revision"] != before:
            raise RelationshipError(
                "BASE_DATA_REVISION_CONFLICT", "基础资料读取期间发生变化，请刷新"
            )
        state = self.guard.status(site_id)
        code, reason = self.guard.write_denial(state)
        result.update(can_write=not code, write_denial_reason=reason)
        return result

    def mutate(self, request: RelationshipMutationRequest, *, preview: bool = False):
        site_id = validate_site_name(request.site_id)
        try:
            self.guard.authorize_apply(
                site_id, explicit_confirmation=preview or request.explicit_confirmation
            )
        except BaseDataWriteGuardError as exc:
            raise RelationshipError(exc.code, str(exc)) from exc
        context = self.catalog(site_id)
        return self.repository.mutate(request, context=context, preview=preview)

    def deletion_preflight(self, site_id: str, entity_uid: str):
        return self.repository.deletion_preflight(
            validate_site_name(site_id), entity_uid
        )

    def fit_ap_overview(self, site_id: str, ac_uuid: str):
        return self.repository.fit_ap_overview(validate_site_name(site_id), ac_uuid)

    def save_project(self, site_id: str, payload: dict, *, preview: bool = False):
        site_id = validate_site_name(site_id)
        try:
            self.guard.authorize_apply(
                site_id,
                explicit_confirmation=preview
                or bool(payload.get("explicit_confirmation")),
            )
        except BaseDataWriteGuardError as exc:
            raise RelationshipError(exc.code, str(exc)) from exc
        return self.repository.save_project(site_id, payload, preview=preview)
