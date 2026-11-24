from types import SimpleNamespace
from netconsole.application.rail_transit.infrastructure_application_service import (
    RailInfrastructureApplicationService,
)
from netconsole.models.api.trackside_ap_business import TracksideApBusinessRowDTO
from netconsole.models.api.device_detail import DeviceEngineeringContextDTO
from netconsole.models.api.rail_infrastructure import InfrastructureSwitchApDTO


def test_infrastructure_preserves_ap_identity_and_incomplete_query_without_changing_legacy_dto():
    class Trackside:
        def list_rows(self, site_id, **kwargs):
            assert site_id == "ordinary-site"
            assert kwargs == dict(page=2, confirmed_switch_uuid="switch-stable")
            return SimpleNamespace(
                items=[
                    TracksideApBusinessRowDTO(
                        row_id="row-stable",
                        ap_uuid="ap-stable",
                        ap_name="AP",
                        interface_name="GE1",
                        identity_match_status="conflict",
                        primary_reason_label="身份冲突",
                        point_engineering_context=DeviceEngineeringContextDTO(
                            section_ids=["section-stable"]
                        ),
                    )
                ],
                total=1,
                page=2,
                page_size=50,
                partial_data=True,
                unavailable_sources=[],
            )

    result = RailInfrastructureApplicationService(None, Trackside()).switch_aps(
        "ordinary-site", "switch-stable", 2
    )
    assert result.partial_data is True
    assert result.items[0].identity_match_status == "conflict"
    assert result.items[0].section_ids == ["section-stable"]
    assert result.items[0].primary_reason_label == "身份冲突"
    legacy = InfrastructureSwitchApDTO(
        row_id="r", ap_uuid="a", ap_name="A", interface_name="", link_status=""
    )
    assert set(legacy.model_dump()) == {
        "row_id",
        "ap_uuid",
        "ap_name",
        "interface_name",
        "link_status",
    }
