import pytest

from netconsole.services.device_command_profile_service import DeviceCommandProfileError
from scripts.maintenance import audit_commands
from scripts.maintenance.audit_commands import (
    load_device_profile_commands,
    main,
    matches_reference,
    placeholder_template_match,
)


def test_audit_loads_versioned_device_profile_commands() -> None:
    commands = load_device_profile_commands()

    assert "screen-length disable" in commands
    assert "display version" in commands
    assert "display lldp neighbor-information verbose" in commands


def test_audit_fails_closed_when_profile_catalog_is_unavailable(monkeypatch) -> None:
    def unavailable():
        raise DeviceCommandProfileError("profile missing")

    monkeypatch.setattr(audit_commands, "load_device_command_profiles", unavailable)

    with pytest.raises(DeviceCommandProfileError, match="profile missing"):
        load_device_profile_commands()


def test_placeholder_matching_requires_the_whole_command() -> None:
    assert placeholder_template_match("display ar5drv 1 channelbusy", "display ar5drv <radio_id> channelbusy")
    assert not placeholder_template_match(
        "display ar5drv 1 channelbusy extra",
        "display ar5drv <radio_id> channelbusy",
    )
    assert not matches_reference("display interface all", {"display interface"})


def test_expected_noise_does_not_hide_arbitrary_failed_display_command() -> None:
    path = audit_commands.ROOT / "src/netconsole/services/example.py"

    assert not audit_commands.is_expected_noise("display version failed", path)


def test_strict_audit_blocks_known_deferred_profile_migrations(
    monkeypatch,
) -> None:
    candidate = audit_commands.Candidate(
        "display interface all",
        audit_commands.ROOT / "src/netconsole/services/example.py",
        1,
    )
    monkeypatch.setattr(audit_commands, "scan_candidates", lambda: [candidate])
    monkeypatch.setattr(audit_commands, "load_reference", lambda: [])
    monkeypatch.setattr(audit_commands, "load_device_profile_commands", lambda: set())
    monkeypatch.setattr(
        audit_commands,
        "DEFERRED_PROFILE_MIGRATION_COMMANDS",
        {("src/netconsole/services/example.py", "display interface all")},
    )
    monkeypatch.setattr("sys.argv", ["audit_commands.py", "--json", "--strict"])

    assert main() == 1
