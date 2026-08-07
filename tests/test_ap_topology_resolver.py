from netconsole.services.ap_topology import ApTopologyEvidence, resolve_ap_topology


def test_lldp_station_wins_and_fields_are_independent() -> None:
    result = resolve_ap_topology(
        ApTopologyEvidence(
            lldp_valid=True,
            lldp_switch_uuid="switch-1",
            lldp_station="B站",
            fit_ap_station="C站",
            base_station="A站",
            base_section="A-B区间",
            base_mileage="K10+200",
            base_direction="上行",
        )
    )

    assert result.station == result.station.__class__("B站", "lldp_switch", 100, "")
    assert result.section.value == "A-B区间"
    assert result.section.source == "base_data"
    assert result.mileage.source == "base_data"
    assert result.direction.source == "base_data"
    assert "topology_lldp_base_conflict" in result.warnings


def test_invalid_or_ambiguous_lldp_falls_back_without_name_guessing() -> None:
    result = resolve_ap_topology(
        ApTopologyEvidence(
            lldp_valid=True,
            lldp_conflict=True,
            lldp_switch_uuid="switch-1",
            lldp_station="B站",
            fit_ap_station="C站",
            base_station="A站",
        )
    )

    assert result.station.value == "C站"
    assert result.station.source == "fit_ap_runtime"
    assert "topology_lldp_ambiguous" in result.warnings


def test_multiple_switches_with_one_station_keep_station_and_warning() -> None:
    result = resolve_ap_topology(
        ApTopologyEvidence(
            lldp_valid=True,
            lldp_switch_conflict=True,
            lldp_switch_uuid="switch-hx-2",
            lldp_station_id="station:hengxi",
            lldp_station="横溪站",
        )
    )

    assert result.station.value == "横溪站"
    assert result.station.source == "lldp_switch"
    assert "topology_lldp_multiple_switches" in result.warnings


def test_base_only_data_is_valid_and_empty_values_do_not_block_fallback() -> None:
    result = resolve_ap_topology(
        ApTopologyEvidence(
            fit_ap_station="   ",
            fit_ap_section="",
            base_station="A站",
            base_section="A-B区间",
            base_belong_type="station",
        )
    )

    assert result.station.value == "A站"
    assert result.station.source == "base_data"
    assert result.section.value == "A-B区间"
    assert result.belong_type.value == "station"


def test_no_structured_evidence_stays_unresolved() -> None:
    result = resolve_ap_topology(
        ApTopologyEvidence(lldp_valid=True, lldp_switch_uuid="switch-1")
    )

    assert result.station.value == ""
    assert result.station.source == "unresolved"
    assert "switch_station_missing" in result.warnings


def test_lldp_station_id_without_display_name_remains_diagnostic_only() -> None:
    result = resolve_ap_topology(
        ApTopologyEvidence(
            lldp_valid=True,
            lldp_switch_uuid="switch-1",
            lldp_station_id="station:known-id",
        )
    )

    assert result.station.source == "unresolved"
    assert "switch_station_missing" in result.warnings
    assert "station_id_unresolved" in result.warnings
