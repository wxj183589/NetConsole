import pytest

from scripts.architecture.checks import device_command_findings
from scripts.maintenance.audit_commands import ROOT, is_expected_noise

from netconsole.services.command_guard import (
    CommandRejected,
    is_command_allowed,
    validate_operation_commands,
)
from netconsole.services.device_command_profile_service import (
    DEVICE_INVENTORY_OPERATION_ID,
    default_device_inventory_profile,
)


def test_profile_managed_context_requires_matching_operation_id() -> None:
    validate_operation_commands(
        default_device_inventory_profile().commands,
        context="device_collect",
        operation_id=DEVICE_INVENTORY_OPERATION_ID,
    )

    with pytest.raises(CommandRejected, match="operation does not match"):
        validate_operation_commands(
            ("display version",),
            context="device_collect",
            operation_id="device.config.save",
        )


def test_non_profile_context_cannot_claim_operation_id() -> None:
    with pytest.raises(CommandRejected, match="not profile-managed"):
        validate_operation_commands(
            ("display version",),
            context="ac_collect",
            operation_id=DEVICE_INVENTORY_OPERATION_ID,
        )


def test_operation_guard_uses_exact_registration_not_prefix_match() -> None:
    assert is_command_allowed("display interface", DEVICE_INVENTORY_OPERATION_ID)
    assert not is_command_allowed(
        "display interface GigabitEthernet1/0/1",
        DEVICE_INVENTORY_OPERATION_ID,
    )
    assert not is_command_allowed("save force", DEVICE_INVENTORY_OPERATION_ID)


def test_operation_guard_still_rejects_unsafe_commands() -> None:
    with pytest.raises(CommandRejected):
        validate_operation_commands(
            ("display version; reboot",),
            context="device_collect",
            operation_id=DEVICE_INVENTORY_OPERATION_ID,
        )


@pytest.mark.parametrize("mutation", ("subset", "reordered"))
def test_operation_guard_requires_the_exact_registered_sequence(mutation: str) -> None:
    commands = list(default_device_inventory_profile().commands)
    if mutation == "subset":
        commands.pop()
    else:
        commands[1], commands[2] = commands[2], commands[1]

    with pytest.raises(CommandRejected, match="sequence does not match"):
        validate_operation_commands(
            tuple(commands),
            context="device_collect",
            operation_id=DEVICE_INVENTORY_OPERATION_ID,
        )


def test_architecture_command_guard_reuses_strict_command_audit() -> None:
    assert device_command_findings() == []


def test_command_audit_ignores_only_the_exact_interface_sort_display_label() -> None:
    interface_sort = ROOT / "src/netconsole/utils/interface_sort.py"

    assert is_expected_noise("display name", interface_sort)
    assert not is_expected_noise("display name", ROOT / "src/netconsole/utils/other.py")
    assert not is_expected_noise("display names", interface_sort)
