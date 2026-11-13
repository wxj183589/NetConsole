from __future__ import annotations

from netconsole.services.ground_unattended.position_engine import PositionEngine


def _event(
    event_type: str,
    event_time: str,
    *,
    ap_id: str = "ap-a",
    ap_name: str = "AP-A",
    ap_mac: str = "aa:aa:aa:aa:aa:01",
    sequence: int = 1,
    identity_status: str = "matched",
    resolution_status: str = "PHYSICAL_AP",
    device_uuid: str = "mr-ct",
) -> dict[str, object]:
    return {
        "event_type": event_type,
        "event_family": "WMESH",
        "event_time": event_time,
        "event_time_source": "DEVICE_TIME",
        "device_uuid": device_uuid,
        "run_id": "run-1",
        "train_id": "train-1",
        "mr_role": "CT",
        "receive_time": event_time,
        "peer_name": ap_name,
        "peer_mac": ap_mac,
        "details": {
            "identity_status": identity_status,
            "resolution_status": resolution_status,
            "peer_ap_id": ap_id,
            "peer_ap_name": ap_name,
            "peer_ap_mac": ap_mac,
            "global_receive_sequence": sequence,
        },
        "raw_text": f"{event_type}:{ap_id}:{event_time}",
    }


def test_position_engine_keeps_last_valid_transition_and_previous_ap() -> None:
    engine = PositionEngine()

    first = engine.apply(_event("MESH_LINKUP", "2026-11-10T10:00:00+08:00"))
    second = engine.apply(
        _event(
            "MESH_ACTIVELINK_SWITCH",
            "2026-11-10T10:00:05+08:00",
            ap_id="ap-b",
            ap_name="AP-B",
            ap_mac="aa:aa:aa:aa:aa:02",
            sequence=2,
        )
    )
    third = engine.apply(
        _event(
            "MESH_ACTIVELINK_SWITCH",
            "2026-11-10T10:00:10+08:00",
            ap_id="ap-a",
            ap_name="AP-A",
            ap_mac="aa:aa:aa:aa:aa:01",
            sequence=3,
        )
    )

    assert first.position_changed is True
    assert second.state["current_ap_name"] == "AP-B"
    assert second.state["previous_ap_name"] == "AP-A"
    assert third.state["current_ap_name"] == "AP-A"
    assert third.state["previous_ap_name"] == "AP-B"
    assert third.state["last_switch_time"] == "2026-11-10T10:00:10+08:00"


def test_duplicate_does_not_repeat_position_transition() -> None:
    engine = PositionEngine()
    event = _event("MESH_LINKUP", "2026-11-10T10:00:00+08:00")

    first = engine.apply(event)
    duplicate = engine.apply(event)

    assert first.accepted is True
    assert duplicate.duplicate is True
    assert duplicate.position_changed is False
    assert duplicate.state["current_ap_name"] == "AP-A"
    assert duplicate.state["duplicate_event_count"] == 1


def test_duplicate_after_another_event_does_not_switch_back() -> None:
    engine = PositionEngine()
    first = _event("MESH_LINKUP", "2026-11-10T10:00:00+08:00")
    first["event_time_source"] = "RECEIVE_TIME"
    first["raw_text"] = "same-received-payload"
    engine.apply(first)
    engine.apply(
        _event(
            "MESH_ACTIVELINK_SWITCH",
            "2026-11-10T10:00:02+08:00",
            ap_id="ap-b",
            ap_name="AP-B",
            ap_mac="aa:aa:aa:aa:aa:02",
            sequence=2,
        )
    )

    duplicate = _event("MESH_LINKUP", "2026-11-10T10:00:03+08:00", sequence=3)
    duplicate["event_time_source"] = "RECEIVE_TIME"
    duplicate["raw_text"] = "same-received-payload"
    result = engine.apply(duplicate)

    assert result.duplicate is True
    assert result.position_changed is False
    assert result.state["current_ap_name"] == "AP-B"


def test_old_event_cannot_overwrite_newer_position() -> None:
    engine = PositionEngine()
    engine.apply(_event("MESH_LINKUP", "2026-11-10T10:00:10+08:00", sequence=2))

    late = engine.apply(
        _event(
            "MESH_ACTIVELINK_SWITCH",
            "2026-11-10T10:00:05+08:00",
            ap_id="ap-b",
            ap_name="AP-B",
            ap_mac="aa:aa:aa:aa:aa:02",
            sequence=1,
        )
    )

    assert late.out_of_order is True
    assert late.state["current_ap_name"] == "AP-A"
    assert late.state["out_of_order_event_count"] == 1


def test_unknown_ap_and_linkdown_preserve_last_known_location() -> None:
    engine = PositionEngine()
    engine.apply(_event("MESH_LINKUP", "2026-11-10T10:00:00+08:00"))

    unknown = engine.apply(
        _event(
            "MESH_ACTIVELINK_SWITCH",
            "2026-11-10T10:00:05+08:00",
            ap_id="unknown",
            ap_name="UNKNOWN-AP",
            ap_mac="aa:aa:aa:aa:aa:99",
            sequence=2,
            identity_status="unresolved",
            resolution_status="UNRESOLVED",
        )
    )
    disconnected = engine.apply(
        _event(
            "MESH_LINKDOWN",
            "2026-11-10T10:00:10+08:00",
            sequence=3,
        )
    )

    assert unknown.state["current_ap_name"] == "AP-A"
    assert unknown.state["position_status"] == "STALE"
    assert disconnected.state["current_ap_name"] == "AP-A"
    assert disconnected.state["position_status"] == "DISCONNECTED"


def test_unresolved_event_does_not_advance_last_valid_position_anchor() -> None:
    engine = PositionEngine()
    engine.apply(_event("MESH_LINKUP", "2026-11-10T10:00:00+08:00", sequence=1))

    unresolved = engine.apply(
        _event(
            "MESH_ACTIVELINK_SWITCH",
            "2026-11-10T10:00:05+08:00",
            ap_id="unknown",
            ap_name="UNKNOWN-AP",
            ap_mac="aa:aa:aa:aa:aa:99",
            sequence=2,
            identity_status="unresolved",
            resolution_status="UNRESOLVED",
        )
    )

    assert unresolved.state["current_ap_name"] == "AP-A"
    assert unresolved.state["last_event_time"] == "2026-11-10T10:00:00+08:00"
    assert unresolved.state["last_receive_time"] == "2026-11-10T10:00:00+08:00"
    assert unresolved.state["last_position_sequence"] == 1
    assert unresolved.state["last_observed_ap_name"] == "UNKNOWN-AP"


def test_old_ap_linkdown_does_not_disconnect_newer_current_ap() -> None:
    engine = PositionEngine()
    engine.apply(_event("MESH_LINKUP", "2026-11-10T10:00:00+08:00", sequence=1))
    engine.apply(
        _event(
            "MESH_ACTIVELINK_SWITCH",
            "2026-11-10T10:00:05+08:00",
            ap_id="ap-b",
            ap_name="AP-B",
            ap_mac="aa:aa:aa:aa:aa:02",
            sequence=2,
        )
    )

    late_down = engine.apply(
        _event(
            "MESH_LINKDOWN",
            "2026-11-10T10:00:06+08:00",
            ap_id="ap-a",
            ap_name="AP-A",
            ap_mac="aa:aa:aa:aa:aa:01",
            sequence=3,
        )
    )

    assert late_down.state["current_ap_name"] == "AP-B"
    assert late_down.state["position_status"] == "VALID"
    assert late_down.state["position_quality"] == "EXACT_IDENTITY"
    assert late_down.position_changed is False


def test_state_can_be_restored_after_backend_restart() -> None:
    source = PositionEngine()
    source.apply(_event("MESH_LINKUP", "2026-11-10T10:00:00+08:00"))
    source.apply(
        _event(
            "MESH_ACTIVELINK_SWITCH",
            "2026-11-10T10:00:05+08:00",
            ap_id="ap-b",
            ap_name="AP-B",
            ap_mac="aa:aa:aa:aa:aa:02",
            sequence=2,
        )
    )

    restored = PositionEngine()
    restored.restore(source.states().values())
    late = restored.apply(
        _event(
            "MESH_LINKUP",
            "2026-11-10T10:00:01+08:00",
            sequence=3,
        )
    )

    assert late.out_of_order is True
    assert late.state["current_ap_name"] == "AP-B"
    assert late.state["previous_ap_name"] == "AP-A"
