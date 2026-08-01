from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from netconsole.core.paths import PathResolver
from netconsole.repositories.ground_unattended_repository import (
    GroundUnattendedRepository,
)
from netconsole.services.ground_unattended.radio_control import (
    GroundRadioControlCorrelationService,
    control_event_dedup_key,
)
from netconsole.services.ground_unattended.application_service import (
    GroundUnattendedApplicationService,
)
from netconsole.services.ground_unattended.raw_query import (
    GroundRawStreamQueryService,
)
from netconsole.services.ground_unattended.syslog_runtime import (
    WmeshRealtimeParser,
)


BASE_TIME = datetime.fromisoformat("2026-07-31T11:12:43.500+08:00")


def _repository(tmp_path: Path) -> GroundUnattendedRepository:
    return GroundUnattendedRepository(
        tmp_path / "ground" / "index.sqlite", site_id="site-a"
    )


def _cfg_event(
    *,
    event_time: datetime = BASE_TIME,
    device_uuid: str = "mr-ct-01",
    command_source: str = "snmp",
    event_index: str = "70",
    raw_line_number: int = 1,
) -> dict[str, object]:
    raw_text = (
        "CFGMAN_CFGCHANGED: "
        f"-EventIndex={event_index}-CommandSource={command_source}"
        "-ConfigSource=startup-ConfigDestination=running"
    )
    timestamp = event_time.isoformat(timespec="milliseconds")
    return {
        "run_id": "run-1",
        "device_uuid": device_uuid,
        "train_id": "train-06",
        "mr_role": "CT",
        "event_type": "CFGMAN_CFGCHANGED",
        "event_family": "CFGMAN",
        "device_time": timestamp,
        "receive_time": timestamp,
        "event_time": timestamp,
        "event_time_source": "DEVICE_TIME",
        "source_ip": "192.0.2.10",
        "hostname": "NBL12-LC06-MR-CT",
        "cfg_event_index": event_index,
        "cfg_command_source": command_source,
        "cfg_source": "startup",
        "cfg_destination": "running",
        "raw_file_id": "raw-syslog-1",
        "raw_line_number": raw_line_number,
        "dedup_key": control_event_dedup_key(
            device_uuid=device_uuid,
            event_type="CFGMAN_CFGCHANGED",
            device_time=timestamp,
            raw_text=raw_text,
            cfg_event_index=event_index,
            cfg_command_source=command_source,
        ),
        "details": {"message": "Configuration changed"},
    }


def _ifnet_event(
    *,
    event_time: datetime,
    state: str,
    device_uuid: str = "mr-ct-01",
    interface_name: str = "WLAN-Radio1/0/1",
    raw_line_number: int = 2,
) -> dict[str, object]:
    timestamp = event_time.isoformat(timespec="milliseconds")
    interface_type = (
        "RADIO" if interface_name.casefold().startswith("wlan-radio") else "OTHER"
    )
    raw_text = f"{interface_name} changed to {state}"
    return {
        "run_id": "run-1",
        "device_uuid": device_uuid,
        "train_id": "train-06",
        "mr_role": "CT",
        "event_type": "IFNET_PHY_UPDOWN",
        "event_family": "IFNET",
        "device_time": timestamp,
        "receive_time": timestamp,
        "event_time": timestamp,
        "event_time_source": "DEVICE_TIME",
        "source_ip": "192.0.2.10",
        "hostname": "NBL12-LC06-MR-CT",
        "interface_name": interface_name,
        "interface_type": interface_type,
        "physical_state": state.upper(),
        "raw_file_id": "raw-syslog-1",
        "raw_line_number": raw_line_number,
        "dedup_key": control_event_dedup_key(
            device_uuid=device_uuid,
            event_type="IFNET_PHY_UPDOWN",
            device_time=timestamp,
            raw_text=raw_text,
            interface_name=interface_name,
            physical_state=state,
        ),
        "details": {
            "interface_name": interface_name,
            "interface_type": interface_type,
            "physical_state": state.upper(),
        },
    }


def test_cfgman_parser_is_order_and_case_insensitive() -> None:
    parser = WmeshRealtimeParser()
    parsed = parser.parse(
        "%Jun 28 00:44:28:230 2026 NBL12-LC06-MR-CT "
        "CFGMAN/5/CFGMAN_CFGCHANGED: "
        "-configdestination=RUNNING-commandsource=SNMP"
        "-EventIndex=70-ConfigSource=STARTUP; Configuration changed.",
        receive_time=BASE_TIME,
    )

    assert parsed is not None
    assert parsed["event_family"] == "CFGMAN"
    assert parsed["cfg_event_index"] == "70"
    assert parsed["cfg_command_source"] == "snmp"
    assert parsed["cfg_source"] == "startup"
    assert parsed["cfg_destination"] == "running"
    assert parsed["details"]["message"] == "Configuration changed"


def test_standalone_snmp_cfgman_is_informational_and_unconfirmed(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    service = GroundRadioControlCorrelationService(repository)

    service.process(_cfg_event())

    runtime = repository.get_mr_runtime_state("mr-ct-01")
    events = repository.list_events("run-1")
    assert runtime is not None
    assert runtime["snmp_radio_control_state"] == "RECENT_CHANGE"
    assert runtime["last_command_source"] == "snmp"
    assert [row["event_type"] for row in events] == ["cfgman_snmp_change"]
    assert events[0]["severity"] == "info"
    assert repository.list_radio_correlations(event_ids=[1]) == []
    assert repository.control_event_raw_positions(
        correlation_status="UNCORRELATED"
    ) == {("raw-syslog-1", 1)}


def test_down_up_359ms_projects_bounce_and_one_snmp_control(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    service = GroundRadioControlCorrelationService(repository)
    down_time = BASE_TIME + timedelta(milliseconds=109)
    up_time = BASE_TIME + timedelta(milliseconds=468)

    cfg = service.process(_cfg_event())
    down = service.process(
        _ifnet_event(event_time=down_time, state="down", raw_line_number=2)
    )
    up = service.process(
        _ifnet_event(event_time=up_time, state="up", raw_line_number=3)
    )

    state = repository.get_radio_interface_state(
        "mr-ct-01", "WLAN-Radio1/0/1"
    )
    runtime = repository.get_mr_runtime_state("mr-ct-01")
    correlations = repository.list_radio_correlations(
        event_ids=[cfg["id"], down["id"], up["id"]]
    )
    timeline_types = {
        row["event_type"] for row in repository.list_events("run-1")
    }
    stats = repository.radio_runtime_statistics(
        run_id="run-1",
        day_start=BASE_TIME.replace(hour=0, minute=0).isoformat(),
    )

    assert state is not None
    assert state["stable_state"] == "UP"
    assert state["previous_state"] == "DOWN"
    assert state["latest_outage_duration_ms"] == 359
    assert state["correlation_confidence"] == "HIGH"
    assert runtime is not None
    assert runtime["snmp_radio_control_state"] == "RADIO_RECOVERED"
    assert len(correlations) == 2
    assert {row["confidence"] for row in correlations} == {"HIGH"}
    assert "radio_interface_bounce" in timeline_types
    assert "radio_snmp_bounce" in timeline_types
    assert stats["radio_bounce_today_count"] == 1
    assert stats["snmp_radio_control_today_count"] == 1
    assert repository.control_event_raw_positions(
        correlation_confidence="HIGH"
    ) == {
        ("raw-syslog-1", 1),
        ("raw-syslog-1", 2),
        ("raw-syslog-1", 3),
    }


def test_correlation_accepts_reverse_arrival_and_applies_time_windows(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    service = GroundRadioControlCorrelationService(repository)

    high_ifnet = service.process(
        _ifnet_event(
            event_time=BASE_TIME + timedelta(seconds=2),
            state="down",
            raw_line_number=2,
        )
    )
    high_cfg = service.process(_cfg_event(raw_line_number=1))
    medium_cfg = service.process(
        _cfg_event(
            event_time=BASE_TIME + timedelta(minutes=1),
            event_index="71",
            raw_line_number=3,
        )
    )
    medium_ifnet = service.process(
        _ifnet_event(
            event_time=BASE_TIME + timedelta(minutes=1, seconds=6),
            state="up",
            raw_line_number=4,
        )
    )
    far_cfg = service.process(
        _cfg_event(
            event_time=BASE_TIME + timedelta(minutes=2),
            event_index="72",
            raw_line_number=5,
        )
    )
    far_ifnet = service.process(
        _ifnet_event(
            event_time=BASE_TIME + timedelta(minutes=2, seconds=11),
            state="down",
            raw_line_number=6,
        )
    )

    correlations = repository.list_radio_correlations(
        event_ids=[
            high_ifnet["id"],
            high_cfg["id"],
            medium_cfg["id"],
            medium_ifnet["id"],
            far_cfg["id"],
            far_ifnet["id"],
        ]
    )
    by_pair = {
        (row["cfg_event_id"], row["ifnet_event_id"]): row["confidence"]
        for row in correlations
    }
    assert by_pair[(high_cfg["id"], high_ifnet["id"])] == "HIGH"
    assert by_pair[(medium_cfg["id"], medium_ifnet["id"])] == "MEDIUM"
    assert all(
        far_cfg["id"] not in pair and far_ifnet["id"] not in pair
        for pair in by_pair
    )


def test_non_radio_other_device_and_cli_are_not_correlated(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    service = GroundRadioControlCorrelationService(repository)
    cfg = service.process(_cfg_event())
    other_device = service.process(
        _ifnet_event(
            event_time=BASE_TIME + timedelta(seconds=1),
            state="down",
            device_uuid="mr-cw-01",
            raw_line_number=2,
        )
    )
    non_radio = service.process(
        _ifnet_event(
            event_time=BASE_TIME + timedelta(seconds=1),
            state="down",
            interface_name="GigabitEthernet1/0/1",
            raw_line_number=3,
        )
    )
    cli_cfg = service.process(
        _cfg_event(
            event_time=BASE_TIME + timedelta(minutes=1),
            command_source="cli",
            event_index="71",
            raw_line_number=4,
        )
    )
    cli_ifnet = service.process(
        _ifnet_event(
            event_time=BASE_TIME + timedelta(minutes=1, seconds=1),
            state="up",
            raw_line_number=5,
        )
    )

    assert repository.list_radio_correlations(
        event_ids=[
            cfg["id"],
            other_device["id"],
            non_radio["id"],
            cli_cfg["id"],
            cli_ifnet["id"],
        ]
    ) == []
    assert repository.get_radio_interface_state(
        "mr-ct-01", "GigabitEthernet1/0/1"
    ) is None


def test_unknown_to_up_does_not_create_false_outage(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    service = GroundRadioControlCorrelationService(repository)

    service.process(
        _ifnet_event(
            event_time=BASE_TIME,
            state="up",
            raw_line_number=1,
        )
    )

    state = repository.get_radio_interface_state(
        "mr-ct-01", "WLAN-Radio1/0/1"
    )
    event_types = [
        row["event_type"] for row in repository.list_events("run-1")
    ]
    assert state is not None
    assert state["previous_state"] == "UNKNOWN"
    assert state["latest_outage_duration_ms"] is None
    assert event_types == ["radio_interface_up"]


def test_duplicate_events_do_not_repeat_projection_or_timeline(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    service = GroundRadioControlCorrelationService(repository)
    cfg_values = _cfg_event()
    down_values = _ifnet_event(
        event_time=BASE_TIME + timedelta(seconds=1),
        state="down",
        raw_line_number=2,
    )

    cfg_first = service.process(cfg_values)
    cfg_duplicate = service.process(cfg_values)
    down_first = service.process(down_values)
    down_duplicate = service.process(down_values)

    assert cfg_duplicate["id"] == cfg_first["id"]
    assert down_duplicate["id"] == down_first["id"]
    assert cfg_duplicate["duplicate_count"] == 1
    assert down_duplicate["duplicate_count"] == 1
    assert len(
        repository.list_radio_correlations(
            event_ids=[cfg_first["id"], down_first["id"]]
        )
    ) == 1
    event_types = [
        row["event_type"] for row in repository.list_events("run-1")
    ]
    assert event_types.count("cfgman_snmp_change") == 1
    assert event_types.count("radio_interface_down") == 1
    assert event_types.count("radio_snmp_down") == 1


def test_raw_query_filters_control_events_and_correlation(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    service = GroundRadioControlCorrelationService(repository)
    cfg_values = _cfg_event()
    down_values = _ifnet_event(
        event_time=BASE_TIME + timedelta(milliseconds=500),
        state="down",
        raw_line_number=2,
    )
    cli_values = _cfg_event(
        event_time=BASE_TIME + timedelta(seconds=20),
        command_source="cli",
        event_index="71",
        raw_line_number=3,
    )
    service.process(cfg_values)
    service.process(down_values)
    service.process(cli_values)

    path = repository.db_path.parent / "active" / "syslog.ndjson"
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {
            "receive_time": str(values["receive_time"]),
            "device_time": str(values["device_time"]),
            "device_uuid": "mr-ct-01",
            "train_id": "train-06",
            "mr_role": "CT",
            "event_type": str(values["event_type"]),
            "event_family": str(values["event_family"]),
            "cfg_command_source": str(
                values.get("cfg_command_source") or ""
            ),
            "physical_state": str(values.get("physical_state") or ""),
            "raw_text": str(values["event_type"]),
        }
        for values in (cfg_values, down_values, cli_values)
    ]
    path.write_text(
        "".join(
            json.dumps(record, ensure_ascii=False) + "\n"
            for record in records
        ),
        encoding="utf-8",
    )
    repository.upsert_raw_file(
        {
            "file_id": "raw-syslog-1",
            "run_id": "run-1",
            "train_id": "train-06",
            "device_uuid": "mr-ct-01",
            "mr_role": "CT",
            "data_type": "syslog",
            "relative_path": path.relative_to(
                repository.db_path.parent
            ).as_posix(),
            "start_time": BASE_TIME.isoformat(timespec="milliseconds"),
            "end_time": (
                BASE_TIME + timedelta(seconds=20)
            ).isoformat(timespec="milliseconds"),
            "record_count": 3,
            "size_bytes": path.stat().st_size,
            "status": "CLOSED",
            "archive_status": "PENDING",
            "parse_status": "PARSED",
        }
    )
    query = GroundRawStreamQueryService(repository)
    common = {
        "run_id": "run-1",
        "start_time": (
            BASE_TIME - timedelta(seconds=1)
        ).isoformat(timespec="milliseconds"),
        "end_time": (
            BASE_TIME + timedelta(seconds=21)
        ).isoformat(timespec="milliseconds"),
    }

    correlated = query.syslog_records(
        **common,
        correlation_status="CORRELATED",
    )
    high = query.syslog_records(
        **common,
        correlation_confidence="HIGH",
    )
    uncorrelated = query.syslog_records(
        **common,
        correlation_status="UNCORRELATED",
    )
    impossible = query.syslog_records(
        **common,
        correlation_status="UNCORRELATED",
        correlation_confidence="HIGH",
    )
    cfgman_snmp = query.syslog_records(
        **common,
        event_family="CFGMAN",
        cfg_command_source="snmp",
    )

    assert correlated["total"] == high["total"] == 2
    assert {
        item["event_family"] for item in correlated["items"]
    } == {"CFGMAN", "IFNET"}
    assert uncorrelated["total"] == 1
    assert uncorrelated["items"][0]["cfg_command_source"] == "cli"
    assert impossible["total"] == 0
    assert cfgman_snmp["total"] == 1
    assert cfgman_snmp["items"][0]["event_type"] == "CFGMAN_CFGCHANGED"

    application = GroundUnattendedApplicationService(
        PathResolver(tmp_path / "app", tmp_path / "data"),
        site_id="site-a",
        repository=repository,
        supervisor=cast(Any, SimpleNamespace()),
        network_service=cast(Any, SimpleNamespace()),
    )
    enriched = application.syslog_records(
        "site-a",
        **common,
        correlation_status="CORRELATED",
    )
    assert enriched.total == 2
    assert {
        item.composite_event_type for item in enriched.items
    } == {"RADIO_SNMP_DOWN"}
    assert {
        tuple(item.correlated_event_ids) for item in enriched.items
    } == {(1, 2)}
    assert {
        item.correlation_confidence for item in enriched.items
    } == {"HIGH"}


def test_flapping_and_projection_rebuild_are_deterministic(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    service = GroundRadioControlCorrelationService(repository)
    states = ("down", "up", "down")
    for index, state in enumerate(states, start=1):
        event_time = BASE_TIME + timedelta(seconds=index * 2)
        service.process(
            _cfg_event(
                event_time=event_time - timedelta(milliseconds=100),
                event_index=str(70 + index),
                raw_line_number=index * 2 - 1,
            )
        )
        service.process(
            _ifnet_event(
                event_time=event_time,
                state=state,
                raw_line_number=index * 2,
            )
        )

    before = repository.get_radio_interface_state(
        "mr-ct-01", "WLAN-Radio1/0/1"
    )
    runtime_before = repository.get_mr_runtime_state("mr-ct-01")
    timeline_count = len(repository.list_events("run-1"))
    rebuilt_count = service.rebuild(device_uuid="mr-ct-01")
    after = repository.get_radio_interface_state(
        "mr-ct-01", "WLAN-Radio1/0/1"
    )
    runtime_after = repository.get_mr_runtime_state("mr-ct-01")

    assert before is not None and after is not None
    assert before["current_state"] == after["current_state"] == "FLAPPING"
    assert before["stable_state"] == after["stable_state"] == "DOWN"
    assert runtime_before is not None and runtime_after is not None
    assert (
        runtime_before["snmp_radio_control_state"]
        == runtime_after["snmp_radio_control_state"]
        == "FREQUENT_SWITCHING"
    )
    assert rebuilt_count == 6
    assert len(repository.list_events("run-1")) == timeline_count
    event_types = {
        row["event_type"] for row in repository.list_events("run-1")
    }
    assert "radio_interface_flapping" in event_types
    assert "radio_snmp_flapping" in event_types
