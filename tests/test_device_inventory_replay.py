from __future__ import annotations

import inspect
import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

from netconsole.models.api.device_detail import (
    DeviceInterfaceDTO,
    DeviceLldpNeighborDTO,
    DeviceTransceiverDTO,
)
from netconsole.models.api.device_management import DeviceFactDTO
from tests.support.device_inventory_replay import (
    load_fixture,
    replay_case,
    replay_fixture,
)
from tests.support.device_inventory_snapshot_contract import (
    validate_snapshot_contract,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "device_cli"
GOLDEN_ROOT = Path(__file__).parent / "golden" / "device_inventory"
CASE_PATHS = tuple(sorted(FIXTURE_ROOT.glob("*.json")))
FORBIDDEN_FIXTURE_TOKENS = re.compile(
    r"(?i)\b(password|community|token|secret|username)\b"
)
EXPECTED_CASES = {
    "h3c_comware7_synthetic.json": "SYNTHETIC",
    "h3c_comware9_synthetic.json": "SYNTHETIC",
    "zte_zxr10_5960x_synthetic.json": "SYNTHETIC",
    "zte_zxr10_c89e4_real_redacted.json": "REAL_CAPTURE",
}


@pytest.mark.parametrize("fixture_path", CASE_PATHS, ids=lambda path: path.stem)
def test_device_inventory_replay_matches_golden(fixture_path: Path) -> None:
    golden_path = GOLDEN_ROOT / fixture_path.name
    assert golden_path.is_file()
    expected = json.loads(golden_path.read_text(encoding="utf-8"))
    assert replay_fixture(fixture_path) == expected


@pytest.mark.parametrize("golden_path", sorted(GOLDEN_ROOT.glob("*.json")))
def test_golden_snapshot_follows_field_contract(golden_path: Path) -> None:
    snapshot = json.loads(golden_path.read_text(encoding="utf-8"))
    validate_snapshot_contract(snapshot)


@pytest.mark.parametrize(
    ("model", "required_fields"),
    (
        (DeviceFactDTO, set()),
        (DeviceInterfaceDTO, {"name", "normalized_name", "category"}),
        (
            DeviceTransceiverDTO,
            {"interface_name", "normalized_interface_name", "severity"},
        ),
        (DeviceLldpNeighborDTO, {"local_interface", "normalized_local_interface"}),
    ),
)
def test_golden_contract_uses_actual_dto_required_fields(model, required_fields) -> None:
    actual = {
        name for name, field in model.model_fields.items() if field.is_required()
    }
    assert actual == required_fields


def test_golden_contract_rejects_runtime_fields(tmp_path: Path) -> None:
    snapshot = json.loads(
        (GOLDEN_ROOT / "h3c_comware9_synthetic.json").read_text(encoding="utf-8")
    )
    snapshot["facts"]["collected_at"] = "runtime-only"
    path = tmp_path / "runtime-field.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    with pytest.raises(ValueError, match="ignored runtime fields"):
        validate_snapshot_contract(json.loads(path.read_text(encoding="utf-8")))


@pytest.mark.parametrize("fixture_path", CASE_PATHS, ids=lambda path: path.stem)
def test_device_inventory_replay_is_deterministic(fixture_path: Path) -> None:
    first = replay_fixture(fixture_path)
    second = replay_fixture(fixture_path)
    assert first == second
    assert json.dumps(first, ensure_ascii=False, sort_keys=True) == json.dumps(
        second,
        ensure_ascii=False,
        sort_keys=True,
    )


def test_first_batch_fixture_scope_and_source_counts() -> None:
    assert {path.name for path in CASE_PATHS} == set(EXPECTED_CASES)
    cases = [load_fixture(path) for path in CASE_PATHS]
    assert {case.fixture_type for case in cases} == {"REAL_CAPTURE", "SYNTHETIC"}
    assert sum(case.fixture_type == "REAL_CAPTURE" for case in cases) == 1
    assert sum(case.fixture_type == "SYNTHETIC" for case in cases) == 3
    assert {case.vendor for case in cases} == {"H3C", "ZTE"}
    assert {case.software_version.split(".", 1)[0] for case in cases[:2]} == {
        "7",
        "9",
    }
    assert all(case.operation_id == "device.inventory.collect" for case in cases)
    assert all("trackside" not in key.casefold() for case in cases for key in case.outputs)


def test_fixture_text_has_no_credential_tokens() -> None:
    for fixture_path in CASE_PATHS:
        case = load_fixture(fixture_path)
        text = "\n".join(case.outputs.values())
        assert FORBIDDEN_FIXTURE_TOKENS.search(text) is None, fixture_path


def test_empty_h3c_output_preserves_parser_contract_without_crashing() -> None:
    original = load_fixture(FIXTURE_ROOT / "h3c_comware7_synthetic.json")
    empty = replace(original, outputs={selector: "" for selector in original.outputs})
    result = replay_case(empty)
    assert result["facts"]["vendor"] == "H3C"
    assert result["facts"]["model"] is None
    assert result["interfaces"] == []
    assert result["optical_modules"] == []
    assert result["lldp_neighbors"] == []
    assert result["statuses"] == {
        "facts": "OK",
        "interfaces": "EMPTY",
        "optical": "EMPTY",
        "lldp": "EMPTY",
    }


def test_empty_zte_output_keeps_explicit_parser_statuses() -> None:
    original = load_fixture(FIXTURE_ROOT / "zte_zxr10_5960x_synthetic.json")
    empty = replace(original, outputs={selector: "" for selector in original.outputs})
    result = replay_case(empty)
    assert result["facts"]["vendor"] is None
    assert result["interfaces"] == []
    assert result["optical_modules"] == []
    assert result["lldp_neighbors"] == []
    assert result["statuses"] == {
        "identity": "NOT_RECOGNIZED",
        "interfaces": "PARSE_FAILED",
        "optical": "PARSE_FAILED",
        "switchvlan": "NOT_RECOGNIZED",
        "vlan_table": "NOT_RECOGNIZED",
        "lldp_brief": "NO_NEIGHBOR",
        "lldp_entry": "NO_NEIGHBOR",
    }


def test_command_error_output_is_reported_as_parser_failure() -> None:
    original = load_fixture(FIXTURE_ROOT / "zte_zxr10_5960x_synthetic.json")
    command_error = replace(
        original,
        outputs={
            selector: "% Invalid input detected at ^ marker."
            for selector in original.outputs
        },
    )
    result = replay_case(command_error)
    assert result["facts"]["vendor"] is None
    assert result["interfaces"] == []
    assert result["optical_modules"] == []
    assert result["lldp_neighbors"] == []
    assert result["statuses"] == {
        "identity": "NOT_RECOGNIZED",
        "interfaces": "PARSE_FAILED",
        "optical": "PARSE_FAILED",
        "switchvlan": "NOT_RECOGNIZED",
        "vlan_table": "NOT_RECOGNIZED",
        "lldp_brief": "COMMAND_UNSUPPORTED",
        "lldp_entry": "COMMAND_UNSUPPORTED",
    }


def test_partial_output_keeps_available_facts_without_fabricating_missing_fields() -> None:
    original = load_fixture(FIXTURE_ROOT / "h3c_comware9_synthetic.json")
    partial_outputs = dict(original.outputs)
    for selector in (
        "inventory.version",
        "inventory.manuinfo",
        "inventory.interfaces",
        "inventory.lldp_list",
        "inventory.lldp_verbose",
    ):
        partial_outputs[selector] = ""

    result = replay_case(replace(original, outputs=partial_outputs))
    assert result["facts"]["model"] == "S9850"
    assert result["facts"]["software_version"] is None
    assert result["facts"]["serial_number"] is None
    assert result["interfaces"] == []
    assert result["lldp_neighbors"] == []
    assert result["optical_modules"]
    assert result["statuses"] == {
        "facts": "OK",
        "interfaces": "EMPTY",
        "optical": "OK",
        "lldp": "EMPTY",
    }


def test_malformed_cli_output_does_not_escape_replay_runner() -> None:
    original = load_fixture(FIXTURE_ROOT / "h3c_comware9_synthetic.json")
    malformed = replace(
        original,
        outputs={
            **original.outputs,
            "inventory.version": "% Unrecognized command",
            "inventory.interfaces": "garbled interface output",
            "inventory.transceiver_diagnosis": "unexpected fields",
            "inventory.lldp_list": "unknown columns",
        },
    )
    result = replay_case(malformed)
    assert result["interfaces"] == []
    assert result["optical_modules"]
    assert result["lldp_neighbors"][0]["neighbor_sysname"] == "H3C9-TEST-PEER"


def test_unknown_cli_field_does_not_change_known_normalized_result() -> None:
    original = load_fixture(FIXTURE_ROOT / "h3c_comware9_synthetic.json")
    baseline = replay_case(original)
    with_unknown_field = replace(
        original,
        outputs={
            selector: f"{value}\nFuture parser field: ignored-{selector}"
            for selector, value in original.outputs.items()
        },
    )
    assert replay_case(with_unknown_field) == baseline


def test_truncated_cli_output_remains_a_deterministic_partial_result() -> None:
    original = load_fixture(FIXTURE_ROOT / "zte_zxr10_5960x_synthetic.json")
    truncated_outputs = dict(original.outputs)
    for selector in (
        "inventory.version",
        "inventory.interface_brief",
        "inventory.optical_brief",
        "inventory.lldp_list",
        "inventory.lldp_verbose",
    ):
        lines = truncated_outputs[selector].splitlines()
        truncated_outputs[selector] = (
            "\n".join(lines[: max(1, len(lines) // 2)]) + "\n--More--"
        )

    first = replay_case(replace(original, outputs=truncated_outputs))
    second = replay_case(replace(original, outputs=truncated_outputs))
    assert first == second
    assert first["facts"]["model"] == "5960X-ES"
    assert first["interfaces"]
    assert first["optical_modules"]
    assert first["lldp_neighbors"]
    assert all(isinstance(value, int) for value in first["warning_counts"].values())
    assert "--More--" not in json.dumps(first, ensure_ascii=False)


def test_unknown_selector_does_not_change_known_normalized_result() -> None:
    original = load_fixture(FIXTURE_ROOT / "h3c_comware7_synthetic.json")
    baseline = replay_case(original)
    with_unknown = replace(
        original,
        outputs={
            **original.outputs,
            "inventory.future_unknown_selector": "future output ignored by this replay contract",
        },
    )
    assert replay_case(with_unknown) == baseline


def test_invalid_fixture_metadata_is_rejected(tmp_path: Path) -> None:
    source = json.loads(
        (FIXTURE_ROOT / "h3c_comware7_synthetic.json").read_text(encoding="utf-8")
    )
    source["fixture_type"] = "UNDECLARED"
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported fixture_type"):
        load_fixture(path)


def test_replay_runner_has_no_network_or_production_collector_imports() -> None:
    from tests.support import device_inventory_replay

    source = inspect.getsource(device_inventory_replay)
    for forbidden in (
        "netmiko",
        "paramiko",
        "h3c_collect_service",
        "DeviceFactRepository",
        "Trackside",
        "FIT_AP",
    ):
        assert forbidden not in source
