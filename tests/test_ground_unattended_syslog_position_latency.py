from __future__ import annotations

from pathlib import Path

import netconsole.services.ground_unattended.syslog_runtime as syslog_runtime
from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)
from netconsole.services.ground_unattended.syslog_runtime import (
    SyslogUdpReceiver,
    UdpEnvelope,
)


def test_position_projection_records_stage_times_and_restores_current_state(
    tmp_path: Path,
) -> None:
    repository = GroundUnattendedRepository(tmp_path / "index.sqlite", site_id="site-a")
    receiver = SyslogUdpReceiver(repository=repository, site_id="site-a")
    receiver._run_id = "run-1"
    endpoint = {
        "device_uuid": "mr-ct",
        "device_id": 1,
        "device_name": "MR-CT-01",
        "train_id": "train-1",
        "train_no": "01",
        "mr_role": "CT",
    }
    receiver._endpoint_by_ip["192.0.2.1"] = [endpoint]

    def enrich(parsed: dict[str, object]) -> dict[str, object]:
        result = dict(parsed)
        details = dict(result.get("details") or {})
        result.update(
            {
                "peer_name": "AP-1",
                "peer_mac": "0000-0000-0001",
                "station": "站点 A",
                "section": "区间 1",
            }
        )
        details.update(
            {
                "peer_ap_id": "ap-1",
                "peer_ap_name": "AP-1",
                "peer_ap_mac": "00:00:00:00:00:01",
                "identity_status": "matched",
                "resolution_status": "PHYSICAL_AP",
            }
        )
        result["details"] = details
        return result

    receiver._ap_resolver.enrich_parsed = enrich  # type: ignore[method-assign]
    raw_text = (
        "%Jul  3 19:19:27:496 2026 MR-CT-01 "
        "WMESH/5/MESH_LINKUP: Mesh link on interface WLAN-Radio1 is up: "
        "peer MAC = 0000-0000-0001, peer radio mode = 1, RSSI = -55"
    )
    envelope = UdpEnvelope(
        source_ip="192.0.2.1",
        source_port=514,
        receive_time="2026-07-03T19:19:29.496+00:00",
        global_receive_sequence=1,
        source_receive_sequence=1,
        payload=raw_text.encode("utf-8"),
    )
    persisted = syslog_runtime._PersistedEnvelope(
        envelope=envelope,
        record={
            "source_ip": envelope.source_ip,
            "source_port": envelope.source_port,
            "hostname": "MR-CT-01",
            "system_name": "MR-CT-01",
            "facility": "local0",
            "severity": "info",
            "raw_text": raw_text,
            "raw_bytes_base64": "",
            "receive_time": envelope.receive_time,
            "global_receive_sequence": 1,
            "source_receive_sequence": 1,
            "device_time": "",
            "device_id": 1,
            "device_uuid": "mr-ct",
            "mr_name": "MR-CT-01",
            "train_id": "train-1",
            "train_no": "01",
            "mr_role": "CT",
            "site_id": "site-a",
            "identity_status": "VERIFIED",
        },
        raw_file_id="raw-1",
        raw_line_number=1,
        raw_persist_time="2026-07-03T19:19:29.600+00:00",
    )

    receiver._process(envelope, persisted)

    assert receiver._position_batch["mr-ct"]["current_ap_name"] == "AP-1"
    assert receiver._position_batch["mr-ct"]["position_quality"] == "EXACT_IDENTITY"
    assert receiver._flush_events() is True

    state = repository.get_syslog_position_state("mr-ct")
    assert state is not None
    assert state["current_ap_name"] == "AP-1"
    assert state["station"] == "站点 A"
    assert state["last_raw_persist_time"] == "2026-07-03T19:19:29.600+00:00"
    assert state["last_position_commit_time"]

    event = repository.list_wmesh_events(mr_id="mr-ct", limit=1)[0]
    details = event["details"]
    assert details["event_time"] == "2026-07-03T19:19:27.496+00:00"
    assert details["receive_time"] == envelope.receive_time
    assert details["raw_persist_time"] == "2026-07-03T19:19:29.600+00:00"
    assert details["parse_complete_time"]
    assert details["position_commit_time"]
    assert details["event_time_precision"] == "DEVICE_TIMESTAMP"

    health = receiver.health_snapshot()
    assert health["position_update_count"] == 1
    assert health["position_latency_p50_ms"] is not None
    assert health["stage_receive_to_raw_p50_ms"] is not None
    assert health["stage_raw_to_parse_p50_ms"] is not None
    assert health["stage_parse_to_position_p50_ms"] is not None


def test_structured_position_dedup_keeps_one_projection_for_distinct_raw_lines(
    tmp_path: Path,
) -> None:
    repository = GroundUnattendedRepository(tmp_path / "index.sqlite", site_id="site-a")
    base = {
        "run_id": "run-1",
        "device_uuid": "mr-ct",
        "train_id": "train-1",
        "mr_role": "CT",
        "event_type": "MESH_LINKUP",
        "event_family": "WMESH",
        "receive_time": "2026-07-03T19:19:29.496+00:00",
        "event_time": "2026-07-03T19:19:27.496+00:00",
        "event_time_source": "DEVICE_TIME",
        "raw_file_id": "raw-1",
        "raw_line_number": 1,
        "dedup_key": "position:same-event",
        "details": {"position_dedup_key": "same-event"},
    }
    assert repository.commit_wmesh_projection_batch([base], []) == 1

    duplicate = dict(base)
    duplicate.update({"raw_file_id": "raw-2", "raw_line_number": 1})
    assert repository.commit_wmesh_projection_batch([duplicate], []) == 0

    rows = repository.list_wmesh_events(mr_id="mr-ct", limit=10)
    assert len(rows) == 1
    assert rows[0]["duplicate_count"] == 1
