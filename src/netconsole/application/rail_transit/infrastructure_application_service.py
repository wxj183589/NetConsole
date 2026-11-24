"""Read-only infrastructure entry; shared authorities retain their ownership."""

from netconsole.core.database import Database
from netconsole.core.site_identity import validate_site_name
from netconsole.models.api.rail_infrastructure import (
    InfrastructureDTO,
    InfrastructureSwitchApContextDTO,
    InfrastructureSwitchApContextPageDTO,
)
from netconsole.repositories.rail_infrastructure_repository import RailInfrastructureRepository
from netconsole.repositories.rail_relationship_repository import RelationshipError


class RailInfrastructureApplicationService:
    def __init__(self, base_query, trackside_query):
        self.base_query = base_query
        self.trackside_query = trackside_query

    def site_id(self, supplied: str) -> str:
        return validate_site_name(supplied or self.base_query.current_site_id())

    def infrastructure(self, site_id: str) -> InfrastructureDTO:
        return self.base_query.infrastructure(self.site_id(site_id))

    def initialize(self, site_id: str) -> InfrastructureDTO:
        site = self.site_id(site_id)
        repository = RailInfrastructureRepository(Database(self.base_query.paths.site_db_path(site)))
        if not repository.database.exists():
            raise RelationshipError("RELATION_REFERENCE_MISSING", "局点数据库不存在")
        revision = repository.base_revision()
        snapshot = self.base_query.infrastructure(site)
        if snapshot.organization_initialized:
            return snapshot
        if not snapshot.schema_available:
            raise RelationshipError("RELATION_MIGRATION_REQUIRED", "局点数据库需要升级")
        stations = {
            key: {"uid": node.uid, "kind": node.kind, "code": node.code, "name": node.name}
            for node in snapshot.nodes
            if node.station is not None and node.kind in {"station", "depot", "parking_yard"}
            for key in (node.station.id, node.uid)
        }
        repository.initialize_organization(site, stations, revision)
        return self.base_query.infrastructure(site)

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
