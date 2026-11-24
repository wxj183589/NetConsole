"""Read-only infrastructure entry; shared authorities retain their ownership."""

from netconsole.core.site_identity import validate_site_name
from netconsole.models.api.rail_infrastructure import (
    InfrastructureDTO,
    InfrastructureSwitchApDTO,
    InfrastructureSwitchApsDTO,
)


class RailInfrastructureApplicationService:
    def __init__(self, base_query, trackside_query):
        self.base_query = base_query
        self.trackside_query = trackside_query

    def site_id(self, supplied: str) -> str:
        return validate_site_name(supplied or self.base_query.current_site_id())

    def infrastructure(self, site_id: str) -> InfrastructureDTO:
        return self.base_query.infrastructure(self.site_id(site_id))

    def switch_aps(
        self, site_id: str, device_uuid: str, page: int
    ) -> InfrastructureSwitchApsDTO:
        result = self.trackside_query.list_rows(
            self.site_id(site_id),
            page=page,
            confirmed_switch_uuid=device_uuid,
        )
        return InfrastructureSwitchApsDTO(
            items=[
                InfrastructureSwitchApDTO(
                    row_id=item.row_id,
                    ap_uuid=item.ap_uuid,
                    ap_name=item.ap_name,
                    interface_name=item.interface_name,
                    link_status=item.link_status,
                )
                for item in result.items
            ],
            total=result.total,
            page=result.page,
            page_size=result.page_size,
        )
