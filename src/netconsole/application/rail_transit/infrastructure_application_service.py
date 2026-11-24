"""Organization and switch context over the shared engineering authorities."""

from collections.abc import Callable

from netconsole.core.database import Database
from netconsole.core.site_identity import validate_site_name
from netconsole.models.api.rail_infrastructure import (
    InfrastructureDTO,
    InfrastructureSwitchApContextDTO,
    InfrastructureSwitchApContextPageDTO,
    OrganizationBatchRequest,
    OrganizationNodeRequest,
)
from netconsole.repositories.rail_infrastructure_repository import RailInfrastructureRepository
from netconsole.repositories.rail_relationship_repository import RelationshipError
from netconsole.services.rail_transit.base_data_write_guard import BaseDataWriteGuard, BaseDataWriteGuardError

RelationshipApplicationError = RelationshipError


class RailInfrastructureApplicationService:
    def __init__(
        self, base_query, trackside_query, *,
        guard: BaseDataWriteGuard | None = None,
        resolve_site: Callable[[str], str] | None = None,
    ):
        self.base_query = base_query
        self.trackside_query = trackside_query
        self.guard = guard
        self.resolve_site = resolve_site
    def site_id(self, supplied: str) -> str:
        site = validate_site_name(supplied or self.base_query.current_site_id())
        return self.resolve_site(site) if self.resolve_site is not None else site

    def infrastructure(self, site_id: str) -> InfrastructureDTO:
        site = self.site_id(site_id)
        result = self.base_query.infrastructure(site)
        if self.guard is not None:
            denial, _ = self.guard.write_denial(self.guard.status(site))
            result.organization_writable = result.schema_available and not denial
        return result

    def _authorize_write(self, site: str, *, confirmed: bool) -> None:
        if self.guard is None:
            raise RelationshipError("BASE_DATA_WRITE_DISABLED", "组织结构写入未启用")
        try:
            self.guard.authorize_apply(site, explicit_confirmation=confirmed)
        except BaseDataWriteGuardError as exc:
            raise RelationshipError(exc.code, str(exc)) from exc

    def initialize(self, site_id: str) -> InfrastructureDTO:
        site = self.site_id(site_id)
        self._authorize_write(site, confirmed=True)
        repository = self._organization_repository(site)
        revision = repository.base_revision()
        snapshot = self.base_query.infrastructure(site)
        if snapshot.organization_initialized:
            return self.infrastructure(site)
        if not snapshot.schema_available:
            raise RelationshipError("RELATION_MIGRATION_REQUIRED", "局点数据库需要升级")
        stations = {
            key: {"uid": node.uid, "kind": node.kind, "code": node.code, "name": node.name}
            for node in snapshot.nodes
            if node.station is not None and node.kind in {"station", "depot", "parking_yard"}
            for key in (node.station.id, node.uid)
        }
        repository.initialize_organization(site, stations, revision)
        return self.infrastructure(site)

    def organization_catalog(self, site_id: str):
        site = self.site_id(site_id)
        return self._organization_repository(site).organization_catalog(site)

    def change_organization_assets(self, site_id: str, payload: OrganizationBatchRequest, *, preview: bool):
        site = self.site_id(site_id)
        repository = self._organization_repository(site)
        try:
            self._authorize_write(
                site, confirmed=preview or payload.explicit_confirmation
            )
            return repository.change_organization_assets(site, payload, preview=preview)
        except BaseDataWriteGuardError as exc:
            raise RelationshipError(exc.code, str(exc)) from exc

    def _organization_repository(self, site: str) -> RailInfrastructureRepository:
        database = Database(self.base_query.paths.site_db_path(site))
        if not database.exists():
            raise RelationshipError("RELATION_REFERENCE_MISSING", "局点数据库不存在")
        return RailInfrastructureRepository(database)

    def save_organization_node(self, site_id: str, payload: OrganizationNodeRequest) -> str:
        site = self.site_id(site_id)
        repository = self._organization_repository(site)
        try:
            self._authorize_write(site, confirmed=payload.explicit_confirmation)
            return repository.save_organization_node(site, payload)
        except BaseDataWriteGuardError as exc:
            raise RelationshipError(exc.code, str(exc)) from exc

    def switch_aps(
        self, site_id: str, device_uuid: str, page: int
    ) -> InfrastructureSwitchApContextPageDTO:
        result = self.trackside_query.list_rows(
            self.site_id(site_id),
            page=page,
            confirmed_switch_uuid=device_uuid,
        )
        return InfrastructureSwitchApContextPageDTO(
            items=[
                InfrastructureSwitchApContextDTO(
                    row_id=item.row_id,
                    ap_uuid=item.ap_uuid,
                    ap_name=item.ap_name,
                    interface_name=item.interface_name,
                    link_status=item.link_status,
                    identity_match_status=item.identity_match_status,
                    recognition_status=item.recognition_status,
                    primary_reason_label=item.primary_reason_label,
                    section_ids=item.point_engineering_context.section_ids,
                )
                for item in result.items
            ],
            total=result.total,
            page=result.page,
            page_size=result.page_size,
            partial_data=result.partial_data,
            unavailable_sources=[
                item.label or item.source for item in result.unavailable_sources
            ],
        )
