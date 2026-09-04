from __future__ import annotations

import inspect
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest

from netconsole.services.interface_discovery_shadow import (
    CAPABILITY_NAME,
    COMPARE_DIFFERENT,
    COMPARE_MATCH,
    COMPARE_SHADOW_FAILED,
    SHADOW_EMPTY,
    SHADOW_FAILED,
    SHADOW_TIMEOUT,
    InterfaceDiscoveryShadowRunner,
    ShadowAuditRecorder,
    compare_interface_discovery_normalized,
)
from tests.support.device_inventory_equivalence import (
    compare_normalized_device_inventory,
)
from tests.support.device_inventory_replay import replay_fixture

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "device_cli"
REPLAY_FIXTURES = (
    FIXTURE_ROOT / "h3c_comware7_synthetic.json",
    FIXTURE_ROOT / "h3c_comware9_synthetic.json",
    FIXTURE_ROOT / "zte_zxr10_5960x_synthetic.json",
)
FIXED_EXECUTION_TIME = datetime(2026, 9, 4, tzinfo=timezone.utc)


@pytest.mark.parametrize("fixture_path", REPLAY_FIXTURES, ids=lambda path: path.stem)
def test_replay_shadow_matches_for_h3c_comware7_9_and_zte(
    fixture_path: Path,
) -> None:
    legacy = replay_fixture(fixture_path)
    recorder = ShadowAuditRecorder()
    calls: list[str] = []

    def shadow_capability() -> dict:
        calls.append(fixture_path.name)
        return replay_fixture(fixture_path)

    report = InterfaceDiscoveryShadowRunner(
        audit_sink=recorder.record,
        clock=lambda: FIXED_EXECUTION_TIME,
    ).run(
        execution_id=f"shadow-{fixture_path.stem}",
        device_identity={
            "device_uuid": "device-1",
            "vendor": legacy["device"]["vendor"],
            "role": legacy["device"]["role"],
        },
        legacy_status="SUCCESS",
        legacy_result=legacy,
        shadow_capability=shadow_capability,
    )

    assert calls == [fixture_path.name]
    assert report.status == "SUCCESS"
    assert report.shadow_status == "SUCCESS"
    assert report.compare_status == COMPARE_MATCH
    assert not report.added
    assert not report.removed
    assert not report.changed
    assert compare_normalized_device_inventory(legacy, replay_fixture(fixture_path))
    assert compare_interface_discovery_normalized(legacy, replay_fixture(fixture_path))
    assert len(recorder.records) == 1
    assert recorder.records[0].compare_status == COMPARE_MATCH
    assert recorder.records[0].execution_time == "2026-09-04T00:00:00Z"


def test_shadow_failure_keeps_legacy_success_and_redacts_error() -> None:
    legacy = replay_fixture(REPLAY_FIXTURES[0])

    def failed_shadow() -> dict:
        raise RuntimeError("connection failed password=do-not-leak")

    report = InterfaceDiscoveryShadowRunner(
        clock=lambda: FIXED_EXECUTION_TIME,
    ).run(
        execution_id="shadow-failed",
        device_identity={"device_uuid": "device-1", "password": "do-not-leak"},
        legacy_status="SUCCESS",
        legacy_result=legacy,
        shadow_capability=failed_shadow,
    )

    assert report.status == "SUCCESS"
    assert report.legacy_status == "SUCCESS"
    assert report.shadow_status == SHADOW_FAILED
    assert report.compare_status == COMPARE_SHADOW_FAILED
    assert report.error is not None
    assert "do-not-leak" not in report.error
    assert "password" not in json.dumps(report.to_dict(), ensure_ascii=False).lower()
    assert report.to_dict()["authoritative_result"] == "LEGACY"
    assert report.to_dict()["repository_write"] == "FORBIDDEN"


def test_shadow_difference_generates_machine_readable_diff_without_autofix() -> None:
    legacy = replay_fixture(REPLAY_FIXTURES[1])
    shadow = deepcopy(legacy)
    original_legacy = deepcopy(legacy)
    shadow["interfaces"][0]["speed"] = "shadow-only-speed"

    report = InterfaceDiscoveryShadowRunner(
        clock=lambda: FIXED_EXECUTION_TIME,
    ).run(
        execution_id="shadow-different",
        device_identity={"device_uuid": "device-1", "vendor": "H3C"},
        legacy_status="SUCCESS",
        legacy_result=legacy,
        shadow_capability=lambda: shadow,
    )

    payload = json.loads(report.to_json())
    assert report.status == "SUCCESS"
    assert report.shadow_status == "SUCCESS"
    assert report.compare_status == COMPARE_DIFFERENT
    assert len(report.changed) == 1
    assert report.changed[0]["fields"]["speed"] == {
        "legacy": {"missing": False, "value": legacy["interfaces"][0]["speed"]},
        "shadow": {"missing": False, "value": "shadow-only-speed"},
    }
    assert payload["capability"] == CAPABILITY_NAME
    assert {
        "device_identity",
        "execution_id",
        "legacy_status",
        "shadow_status",
    } <= payload.keys()
    assert {
        "compare_status",
        "added",
        "removed",
        "changed",
        "error",
    } <= payload.keys()
    assert legacy == original_legacy
    assert shadow["interfaces"][0]["speed"] == "shadow-only-speed"


def test_shadow_timeout_is_diagnostic_only() -> None:
    legacy = replay_fixture(REPLAY_FIXTURES[2])

    def timed_out() -> dict:
        raise TimeoutError("shadow budget exceeded")

    report = InterfaceDiscoveryShadowRunner().run(
        execution_id="shadow-timeout",
        device_identity={"device_uuid": "device-1", "vendor": "ZTE"},
        legacy_status="SUCCESS",
        legacy_result=legacy,
        shadow_capability=timed_out,
    )

    assert report.status == "SUCCESS"
    assert report.shadow_status == SHADOW_TIMEOUT
    assert report.compare_status == COMPARE_SHADOW_FAILED
    assert report.added == ()
    assert report.removed == ()
    assert report.changed == ()


def test_shadow_empty_result_does_not_write_or_pollute_production_state() -> None:
    legacy = replay_fixture(REPLAY_FIXTURES[0])
    report = InterfaceDiscoveryShadowRunner(
        clock=lambda: FIXED_EXECUTION_TIME,
    ).run(
        execution_id="shadow-empty",
        device_identity={"device_uuid": "device-1", "vendor": "H3C"},
        legacy_status="SUCCESS",
        legacy_result=legacy,
        shadow_capability=lambda: {"interfaces": []},
    )

    assert report.status == "SUCCESS"
    assert report.shadow_status == SHADOW_EMPTY
    assert report.compare_status == COMPARE_DIFFERENT
    assert len(report.removed) == len(legacy["interfaces"])
    assert report.to_dict()["repository_write"] == "FORBIDDEN"


def test_shadow_runtime_fields_are_not_normalized_differences() -> None:
    legacy = replay_fixture(REPLAY_FIXTURES[0])
    shadow = deepcopy(legacy)
    shadow["interfaces"][0]["timestamp"] = "shadow-runtime"
    shadow["interfaces"][0]["raw_output"] = "raw CLI must not be compared"

    report = InterfaceDiscoveryShadowRunner().run(
        execution_id="shadow-runtime",
        device_identity={"device_uuid": "device-1"},
        legacy_status="SUCCESS",
        legacy_result=legacy,
        shadow_capability=lambda: shadow,
    )

    assert report.compare_status == COMPARE_MATCH


def test_shadow_runner_has_no_repository_transport_or_feature_flag_boundary() -> None:
    from netconsole.services import interface_discovery_shadow

    source = inspect.getsource(interface_discovery_shadow)
    for forbidden in (
        "DeviceFactRepository",
        "replace_device_interfaces",
        "append_interface_history",
        "netmiko",
        "paramiko",
        "socket",
        "FeatureFlag",
    ):
        assert forbidden not in source
