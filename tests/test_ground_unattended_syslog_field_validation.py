from __future__ import annotations

import hashlib
import json
import socket
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.device import Device
from netconsole.parsers.h3c.info_center_parser import parse_info_center_runtime
from netconsole.repositories.ac_repository import AcRepository
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.repositories.ground_unattended_repository import GroundUnattendedRepository
from netconsole.services.ap_identity import ApIdentityQueryService
from netconsole.services.ground_unattended.boot_config import (
    MrBootSessionService,
    MrSyslogConfigService,
    analyze_syslog_config,
    sanitize_syslog_evidence,
    verify_syslog_profile,
)
from netconsole.services.ground_unattended.syslog_runtime import (
    SyslogUdpReceiver,
    UdpEnvelope,
    WmeshRealtimeParser,
)


TARGET_IP = "192.0.2.100"
FULL_CONFIG_514 = "\n".join(
    (
        "info-center enable",
        f"info-center loghost {TARGET_IP}",
        "info-center source default loghost deny",
        "info-center source WMESH loghost level notification",
        "info-center source IFNET loghost level notification",
        "info-center source CFGMAN loghost level notification",
    )
)
SOURCE_RULES_CONFIG = "\n".join(
    (
        "info-center source default loghost deny",
        "info-center source WMESH loghost level notification",
        "info-center source IFNET loghost level notification",
        "info-center source CFGMAN loghost level notification",
    )
)
DEFAULT_OMITTED_CONFIG_514 = "\n".join(
    (
        f"info-center loghost {TARGET_IP}",
        SOURCE_RULES_CONFIG,
    )
)
FULL_RUNTIME_514 = "\n".join(
    (
        "Information Center: Enabled",
        "Console: Disabled",
        "Monitor: Enabled",
        "Log host: Enabled",
        f"    {TARGET_IP},",
        "    port number: 514, host facility: local7",
        "Current messages 512",
        "dropped messages 0",
        "overwritten messages 7837",
        "Max buffer size 1024",
        "current buffer size 512",
        "Information timestamp format:",
        "    Log host: Date",
        "    Other output destination: Date",
    )
)
MULTI_RUNTIME_5514 = "\n".join(
    (
        "Information Center: Enabled",
        "Log host: Enabled",
        "    192.0.2.99, log output filter: loghost1,",
        "    port number: 4514, DSCP value:0, host facility: local7",
        f"    {TARGET_IP},",
        "    port number: 5514, host facility: local7",
        "Log buffer: Enabled",
    )
)


def test_info_center_runtime_parser_and_default_port_normalization() -> None:
    runtime = parse_info_center_runtime(FULL_RUNTIME_514)

    assert runtime.information_center_enabled is True
    assert runtime.console_enabled is False
    assert runtime.monitor_enabled is True
    assert runtime.loghost_enabled is True
    assert runtime.log_hosts[0].ip == TARGET_IP
    assert runtime.log_hosts[0].port == 514
    assert runtime.log_hosts[0].facility == "local7"
    assert runtime.current_messages == 512
    assert runtime.dropped_messages == 0
    assert runtime.overwritten_messages == 7837
    assert runtime.loghost_timestamp_format == "Date"
    assert runtime.other_output_timestamp_format == "Date"
    inline_metrics = FULL_RUNTIME_514.replace(
        "Current messages 512\ndropped messages 0\noverwritten messages 7837\nMax buffer size 1024\ncurrent buffer size 512",
        "Max buffer size 1024, current buffer size 512\n"
        "Current messages 512, dropped messages 0, overwritten messages 7837",
    )
    assert parse_info_center_runtime(inline_metrics).overwritten_messages == 7837
    config = analyze_syslog_config(
        SOURCE_RULES_CONFIG,
        target_ip=TARGET_IP,
        target_port=514,
    )
    assert config.complete
    assert config.source_rule_missing == ()
    wrong_runtime_target = verify_syslog_profile(
        FULL_RUNTIME_514,
        SOURCE_RULES_CONFIG,
        target_ip=TARGET_IP,
        target_port=5514,
    )
    assert wrong_runtime_target.runtime_missing == ("loghost_target",)
    assert wrong_runtime_target.target_statuses == ("TARGET_PORT_CONFLICT",)
    assert wrong_runtime_target.repair_commands == ()


def test_multiple_log_hosts_are_preserved_and_managed_target_uses_ip_and_port() -> None:
    runtime = parse_info_center_runtime(MULTI_RUNTIME_5514)

    assert [(host.ip, host.port, host.facility) for host in runtime.log_hosts] == [
        ("192.0.2.99", 4514, "local7"),
        (TARGET_IP, 5514, "local7"),
    ]
    present = verify_syslog_profile(
        MULTI_RUNTIME_5514,
        SOURCE_RULES_CONFIG,
        target_ip=TARGET_IP,
        target_port=5514,
    )
    assert present.complete
    assert present.target_statuses == (
        "TARGET_PRESENT",
        "OTHER_TARGETS_PRESENT",
    )
    assert present.repair_commands == ()


def test_same_ip_different_port_is_blocked_instead_of_treated_as_missing() -> None:
    conflict = verify_syslog_profile(
        MULTI_RUNTIME_5514,
        SOURCE_RULES_CONFIG,
        target_ip=TARGET_IP,
        target_port=514,
    )

    assert not conflict.complete
    assert conflict.target_statuses == (
        "TARGET_PORT_CONFLICT",
        "OTHER_TARGETS_PRESENT",
    )
    assert conflict.runtime_missing == ("loghost_target",)
    assert conflict.repair_commands == ()
    authorized = verify_syslog_profile(
        MULTI_RUNTIME_5514,
        SOURCE_RULES_CONFIG,
        target_ip=TARGET_IP,
        target_port=514,
        allow_target_port_change=True,
    )
    assert authorized.repair_commands == (
        f"info-center loghost {TARGET_IP} port 514",
    )


def test_missing_ip_can_be_added_without_removing_other_targets() -> None:
    missing = verify_syslog_profile(
        MULTI_RUNTIME_5514,
        SOURCE_RULES_CONFIG,
        target_ip="192.0.2.101",
        target_port=514,
    )

    assert missing.target_statuses == (
        "TARGET_MISSING",
        "OTHER_TARGETS_PRESENT",
    )
    assert missing.repair_commands == (
        "info-center loghost 192.0.2.101 port 514",
    )


def test_runtime_target_and_source_rules_are_both_required() -> None:
    incomplete_config = "\n".join(
        (
            "info-center enable",
            f"info-center loghost {TARGET_IP}",
            "info-center source default loghost deny",
        )
    )
    verification = verify_syslog_profile(
        FULL_RUNTIME_514,
        incomplete_config,
        target_ip=TARGET_IP,
        target_port=514,
    )

    assert verification.complete is False
    assert verification.runtime_missing == ()
    assert verification.source_rule_missing == (
        "info-center source wmesh loghost level notification",
        "info-center source ifnet loghost level notification",
        "info-center source cfgman loghost level notification",
    )
    assert verification.repair_commands == (
        "info-center source wmesh loghost level notification",
        "info-center source ifnet loghost level notification",
        "info-center source cfgman loghost level notification",
    )


def test_runtime_disabled_repairs_enable_and_missing_target() -> None:
    verification = verify_syslog_profile(
        "Information Center: Disabled\nLog host: Disabled\n",
        SOURCE_RULES_CONFIG,
        target_ip=TARGET_IP,
        target_port=514,
    )

    assert verification.runtime_missing == (
        "information_center_enabled",
        "loghost_enabled",
        "loghost_target",
    )
    assert verification.source_rule_missing == ()
    assert verification.repair_commands == (
        "info-center enable",
        f"info-center loghost {TARGET_IP} port 514",
    )


def test_runtime_without_target_repairs_only_loghost() -> None:
    verification = verify_syslog_profile(
        "Information Center: Enabled\nLog host: Enabled\n",
        SOURCE_RULES_CONFIG,
        target_ip=TARGET_IP,
        target_port=514,
    )

    assert verification.runtime_missing == ("loghost_target",)
    assert verification.repair_commands == (
        f"info-center loghost {TARGET_IP} port 514",
    )


@pytest.mark.parametrize(
    ("configuration", "expected_command"),
    (
        (
            "\n".join(
                (
                    "info-center source WMESH loghost level notification",
                    "info-center source IFNET loghost level notification",
                    "info-center source CFGMAN loghost level notification",
                )
            ),
            "info-center source default loghost deny",
        ),
        (
            "\n".join(
                (
                    "info-center source default loghost deny",
                    "info-center source IFNET loghost level notification",
                    "info-center source CFGMAN loghost level notification",
                )
            ),
            "info-center source wmesh loghost level notification",
        ),
    ),
)
def test_runtime_correct_repairs_only_missing_source_rule(
    configuration: str,
    expected_command: str,
) -> None:
    verification = verify_syslog_profile(
        FULL_RUNTIME_514,
        configuration,
        target_ip=TARGET_IP,
        target_port=514,
    )

    assert verification.runtime_missing == ()
    assert verification.source_rule_missing == (expected_command,)
    assert verification.repair_commands == (expected_command,)


def test_syslog_evidence_redacts_sensitive_configuration_lines() -> None:
    evidence = sanitize_syslog_evidence(
        {
            "configuration_before": (
                "info-center enable\n"
                "local-user operator password cipher super-secret\n"
                "snmp-agent community read example-community"
            ),
            "command_results": [{"command": "info-center enable", "output": ""}],
        }
    )

    serialized = json.dumps(evidence, ensure_ascii=False)
    assert "super-secret" not in serialized
    assert "example-community" not in serialized
    assert evidence["configuration_before"].splitlines()[0] == "info-center enable"
    assert serialized.count("[REDACTED sensitive configuration line]") == 2


def test_config_check_verifies_after_writes_and_records_evidence(tmp_path: Path) -> None:
    paths, repository, device_uuid = _context(tmp_path)
    after_config = FULL_CONFIG_514
    connection = _ConfigConnection(
        config_before="",
        config_after=after_config,
        info_before="Information Center: Disabled\nLog host: Disabled\n",
        info_after=FULL_RUNTIME_514,
    )

    result = _service(paths, repository, connection).check(
        run_id="run-1",
        run_date="2026-07-26",
        device_uuid=device_uuid,
        target_ip=TARGET_IP,
        target_port=514,
        boot_tolerance_seconds=120,
    )

    assert result.config_status == "CONFIG_SENT"
    assert connection.commands.count("display info-center") == 2
    assert connection.commands.count("display current-configuration | include info-center") == 2
    assert all(
        word not in " ".join(connection.commands).casefold()
        for word in ("save", "undo", "quit", "reboot", "reset", "delete")
    )
    audit = repository.latest_syslog_config_audit(device_uuid)
    assert audit is not None and audit["status"] == "CONFIG_SENT"
    evidence = json.loads((repository.db_path.parent / audit["evidence_path"]).read_text(encoding="utf-8"))
    assert {
        "display_version",
        "display_info_center_before",
        "configuration_before",
        "repair_commands",
        "applied_commands",
        "command_results",
        "display_info_center_after",
        "configuration_after",
        "missing_before",
        "missing_after",
        "checked_at",
        "verified_at",
    } <= set(evidence)
    assert evidence["configuration_after"] == after_config
    assert evidence["missing_before"] == {
        "runtime": [
            "information_center_enabled",
            "loghost_enabled",
            "loghost_target",
        ],
        "source_rules": [
            "info-center source default loghost deny",
            "info-center source wmesh loghost level notification",
            "info-center source ifnet loghost level notification",
            "info-center source cfgman loghost level notification",
        ],
        "target_statuses": ["TARGET_MISSING"],
    }
    assert evidence["repair_commands"] == [
        "info-center enable",
        f"info-center loghost {TARGET_IP} port 514",
        "info-center source default loghost deny",
        "info-center source wmesh loghost level notification",
        "info-center source ifnet loghost level notification",
        "info-center source cfgman loghost level notification",
    ]
    assert evidence["applied_commands"] == [
        "system-view",
        *evidence["repair_commands"],
        "return",
    ]
    assert evidence["missing_after"] == {
        "runtime": [],
        "source_rules": [],
        "target_statuses": ["TARGET_PRESENT"],
    }
    assert repository.latest_boot_session(device_uuid)["config_status"] == "WAITING_FIRST_LOG"
    raw_config_fingerprint = hashlib.sha256(
        f"{TARGET_IP}:514\n{after_config}".encode("utf-8")
    ).hexdigest()
    fingerprint = repository.latest_boot_session(device_uuid)["config_fingerprint"]
    assert len(fingerprint) == 64
    assert fingerprint != raw_config_fingerprint


def test_auto_repair_disabled_keeps_incomplete_profile_read_only(
    tmp_path: Path,
) -> None:
    paths, repository, device_uuid = _context(tmp_path)
    connection = _ConfigConnection(
        config_before="info-center source default loghost deny",
        config_after=FULL_CONFIG_514,
        info_before=FULL_RUNTIME_514,
        info_after=FULL_RUNTIME_514,
    )

    result = _service(paths, repository, connection).check(
        run_id="run-1",
        run_date="2026-07-26",
        device_uuid=device_uuid,
        target_ip=TARGET_IP,
        target_port=514,
        boot_tolerance_seconds=120,
        repair_enabled=False,
    )

    assert result.config_status == "AUTO_REPAIR_DISABLED"
    assert result.applied_commands == ()
    assert "system-view" not in connection.commands
    assert connection.commands.count("display info-center") == 1
    assert (
        connection.commands.count(
            "display current-configuration | include info-center"
        )
        == 1
    )
    audit = repository.latest_syslog_config_audit(device_uuid)
    assert audit is not None
    evidence = json.loads(
        (repository.db_path.parent / audit["evidence_path"]).read_text(
            encoding="utf-8"
        )
    )
    assert evidence["syslog_auto_repair_enabled"] is False
    assert evidence["managed_profile_version"] == 2


def test_expected_internal_change_uses_a_bounded_window(
    tmp_path: Path,
) -> None:
    _paths, repository, device_uuid = _context(tmp_path)
    _waiting_boot(repository, device_uuid)
    started_at = datetime.now().astimezone()
    expected_until = started_at.replace(
        microsecond=min(999_999, started_at.microsecond + 500_000)
    )
    repository.mark_expected_config_change(
        device_uuid=device_uuid,
        operation_id="operation-1",
        expected_started_at=started_at.isoformat(timespec="milliseconds"),
        expected_until=expected_until.isoformat(timespec="milliseconds"),
    )

    assert repository.expected_config_change_at(
        device_uuid=device_uuid,
        event_time=started_at.isoformat(timespec="milliseconds"),
    )
    assert not repository.expected_config_change_at(
        device_uuid=device_uuid,
        event_time=(
            started_at.replace(year=started_at.year - 1)
        ).isoformat(timespec="milliseconds"),
    )
    assert not repository.expected_config_change_at(
        device_uuid=device_uuid,
        event_time=(
            expected_until.replace(year=expected_until.year + 1)
        ).isoformat(timespec="milliseconds"),
    )


def test_device_clock_parse_failure_is_an_explicit_local_time_fallback(
    tmp_path: Path,
) -> None:
    paths, repository, device_uuid = _context(tmp_path)
    result = _service(
        paths,
        repository,
        _ConfigConnection(
            config_before=FULL_CONFIG_514,
            config_after=FULL_CONFIG_514,
            info_before=FULL_RUNTIME_514,
            info_after=FULL_RUNTIME_514,
            clock_output="clock output unavailable",
        ),
    ).check(
        run_id="run-1",
        run_date="2026-07-26",
        device_uuid=device_uuid,
        target_ip=TARGET_IP,
        target_port=514,
        boot_tolerance_seconds=120,
    )

    boot = repository.latest_boot_session(device_uuid)
    audit = repository.latest_syslog_config_audit(device_uuid)
    assert result.config_status == "CONFIG_PRESENT"
    assert boot is not None
    assert boot["time_quality"] == "LOCAL_FALLBACK"
    assert boot["device_clock_before"] == ""
    assert boot["device_clock_after"] == ""
    assert boot["boot_time_uncertainty_seconds"] == 120
    assert audit is not None
    evidence = json.loads(
        (repository.db_path.parent / audit["evidence_path"]).read_text(
            encoding="utf-8"
        )
    )
    assert evidence["device_time_quality"] == "LOCAL_FALLBACK"
    assert evidence["device_time_error"]


def test_config_check_repairs_partial_and_uses_full_config_fallback(tmp_path: Path) -> None:
    paths, repository, device_uuid = _context(tmp_path)
    partial = "\n".join(
        (
            "info-center enable",
            f"info-center loghost {TARGET_IP}",
        )
    )
    connection = _ConfigConnection(
        config_before=partial,
        config_after=FULL_CONFIG_514,
        info_before=FULL_RUNTIME_514,
        info_after=FULL_RUNTIME_514,
        filter_fails=True,
    )

    result = _service(paths, repository, connection).check(
        run_id="run-1",
        run_date="2026-07-26",
        device_uuid=device_uuid,
        target_ip=TARGET_IP,
        target_port=514,
        boot_tolerance_seconds=120,
    )

    assert result.config_status == "CONFIG_REPAIRED"
    assert connection.commands.count("display current-configuration") == 2
    assert "system-view" in connection.commands
    assert "info-center loghost 192.0.2.100 port 514" not in connection.commands


def test_config_write_failure_and_post_read_failure_never_report_success(tmp_path: Path) -> None:
    paths, repository, device_uuid = _context(tmp_path)
    command_failure = _ConfigConnection(
        config_before="",
        config_after=FULL_CONFIG_514,
        info_before="Information Center: Disabled\nLog host: Disabled\n",
        info_after=FULL_RUNTIME_514,
        write_results={"info-center enable": "% Wrong parameter"},
    )
    with pytest.raises(RuntimeError, match="配置命令执行失败"):
        _service(paths, repository, command_failure).check(
            run_id="run-1", run_date="2026-07-26", device_uuid=device_uuid,
            target_ip=TARGET_IP, target_port=514, boot_tolerance_seconds=120,
        )
    assert repository.latest_syslog_config_audit(device_uuid)["status"] == "CONFIG_FAILED"

    runtime_verification_failure = _ConfigConnection(
        config_before="",
        config_after=SOURCE_RULES_CONFIG,
        info_before="Information Center: Disabled\nLog host: Disabled\n",
        info_after="Information Center: Disabled\nLog host: Disabled\n",
    )
    result = _service(paths, repository, runtime_verification_failure).check(
        run_id="run-1", run_date="2026-07-26", device_uuid=device_uuid,
        target_ip=TARGET_IP, target_port=514, boot_tolerance_seconds=120,
    )
    assert result.config_status == "CONFIG_VERIFY_FAILED"
    assert repository.latest_boot_session(device_uuid)["config_status"] == "CONFIG_VERIFY_FAILED"


def test_source_rule_verification_failure_never_reports_success(tmp_path: Path) -> None:
    paths, repository, device_uuid = _context(tmp_path)
    connection = _ConfigConnection(
        config_before="info-center source default loghost deny",
        config_after="info-center source default loghost deny",
        info_before=FULL_RUNTIME_514,
        info_after=FULL_RUNTIME_514,
    )

    result = _service(paths, repository, connection).check(
        run_id="run-1",
        run_date="2026-07-26",
        device_uuid=device_uuid,
        target_ip=TARGET_IP,
        target_port=514,
        boot_tolerance_seconds=120,
    )

    assert result.config_status == "CONFIG_VERIFY_FAILED"
    audit = repository.latest_syslog_config_audit(device_uuid)
    evidence = json.loads(
        (repository.db_path.parent / audit["evidence_path"]).read_text(encoding="utf-8")
    )
    assert evidence["missing_after"] == {
        "runtime": [],
        "source_rules": [
            "info-center source wmesh loghost level notification",
            "info-center source ifnet loghost level notification",
            "info-center source cfgman loghost level notification",
        ],
        "target_statuses": ["TARGET_PRESENT"],
    }
    repository.touch_boot_syslog(
        device_uuid, datetime.now().astimezone().isoformat(timespec="milliseconds"),
        source_ip="192.0.2.10", hostname="TEST-MR-CT", identity_verified=True,
    )
    assert repository.latest_boot_session(device_uuid)["config_status"] == "CONFIG_VERIFY_FAILED"


def test_complete_config_skips_write_and_verified_log_becomes_active(tmp_path: Path) -> None:
    paths, repository, device_uuid = _context(tmp_path)
    connection = _ConfigConnection(
        config_before=FULL_CONFIG_514,
        config_after=FULL_CONFIG_514,
        info_before=FULL_RUNTIME_514,
        info_after=FULL_RUNTIME_514,
    )
    result = _service(paths, repository, connection).check(
        run_id="run-1", run_date="2026-07-26", device_uuid=device_uuid,
        target_ip=TARGET_IP, target_port=514, boot_tolerance_seconds=120,
    )
    assert result.config_status == "CONFIG_PRESENT"
    assert "system-view" not in connection.commands
    received_at = datetime.now().astimezone().isoformat(timespec="milliseconds")
    repository.touch_boot_syslog(
        device_uuid, received_at, source_ip="192.0.2.10", hostname="TEST-MR-CT", identity_verified=True,
    )
    boot = repository.latest_boot_session(device_uuid)
    endpoint = repository.get_inventory_endpoint(device_uuid)
    assert boot is not None and boot["config_status"] == "LOG_ACTIVE"
    assert endpoint is not None and endpoint["last_syslog_source_ip"] == "192.0.2.10"
    assert endpoint["syslog_hostname"] == "TEST-MR-CT"


def test_default_enable_and_port_omission_is_config_present_without_write(
    tmp_path: Path,
) -> None:
    paths, repository, device_uuid = _context(tmp_path)
    omitted_connection = _ConfigConnection(
        config_before=DEFAULT_OMITTED_CONFIG_514,
        config_after=DEFAULT_OMITTED_CONFIG_514,
        info_before=FULL_RUNTIME_514,
        info_after=FULL_RUNTIME_514,
    )

    omitted_result = _service(paths, repository, omitted_connection).check(
        run_id="run-1",
        run_date="2026-07-26",
        device_uuid=device_uuid,
        target_ip=TARGET_IP,
        target_port=514,
        boot_tolerance_seconds=120,
    )

    assert omitted_result.config_status == "CONFIG_PRESENT"
    assert omitted_result.applied_commands == ()
    assert "system-view" not in omitted_connection.commands
    assert "info-center enable" not in omitted_connection.commands
    first_fingerprint = repository.latest_boot_session(device_uuid)["config_fingerprint"]

    explicit_connection = _ConfigConnection(
        config_before=FULL_CONFIG_514,
        config_after=FULL_CONFIG_514,
        info_before=FULL_RUNTIME_514,
        info_after=FULL_RUNTIME_514,
    )
    explicit_result = _service(paths, repository, explicit_connection).check(
        run_id="run-1",
        run_date="2026-07-26",
        device_uuid=device_uuid,
        target_ip=TARGET_IP,
        target_port=514,
        boot_tolerance_seconds=120,
    )

    assert explicit_result.config_status == "CONFIG_PRESENT"
    assert repository.latest_boot_session(device_uuid)["config_fingerprint"] == first_fingerprint
    assert "system-view" not in explicit_connection.commands


def test_target_port_conflict_stays_read_only_until_explicitly_authorized(
    tmp_path: Path,
) -> None:
    paths, repository, device_uuid = _context(tmp_path)
    read_only = _ConfigConnection(
        config_before=SOURCE_RULES_CONFIG,
        config_after=SOURCE_RULES_CONFIG,
        info_before=MULTI_RUNTIME_5514,
        info_after=MULTI_RUNTIME_5514,
    )

    blocked = _service(paths, repository, read_only).check(
        run_id="run-1",
        run_date="2026-07-27",
        device_uuid=device_uuid,
        target_ip=TARGET_IP,
        target_port=514,
        boot_tolerance_seconds=120,
    )

    assert blocked.config_status == "TARGET_PORT_CONFLICT"
    assert blocked.applied_commands == ()
    assert "system-view" not in read_only.commands
    assert (
        f"info-center loghost {TARGET_IP} port 514"
        not in read_only.commands
    )
    audit = repository.latest_syslog_config_audit(device_uuid)
    assert audit is not None
    assert audit["status"] == "TARGET_PORT_CONFLICT"
    metrics = repository.latest_boot_session(device_uuid)["info_center_metrics"]
    assert metrics["managed_target"]["statuses"] == [
        "TARGET_PORT_CONFLICT",
        "OTHER_TARGETS_PRESENT",
    ]

    updated_runtime = MULTI_RUNTIME_5514.replace(
        "port number: 5514", "port number: 514"
    )
    authorized_connection = _ConfigConnection(
        config_before=SOURCE_RULES_CONFIG,
        config_after=SOURCE_RULES_CONFIG,
        info_before=MULTI_RUNTIME_5514,
        info_after=updated_runtime,
    )
    authorized = _service(
        paths, repository, authorized_connection
    ).check(
        run_id="run-1",
        run_date="2026-07-27",
        device_uuid=device_uuid,
        target_ip=TARGET_IP,
        target_port=514,
        boot_tolerance_seconds=120,
        allow_target_port_change=True,
    )

    assert authorized.config_status == "CONFIG_REPAIRED"
    assert f"info-center loghost {TARGET_IP} port 514" in authorized.applied_commands
    assert not any(
        command.casefold().startswith("undo ")
        for command in authorized_connection.commands
    )
    with sqlite3.connect(repository.db_path) as conn:
        event_types = {
            row[0]
            for row in conn.execute(
                "SELECT event_type FROM ground_unattended_events"
            ).fetchall()
        }
    assert "mr_loghost_port_changed" in event_types


def test_multi_target_order_does_not_change_configuration_fingerprint(
    tmp_path: Path,
) -> None:
    paths, repository, device_uuid = _context(tmp_path)
    reversed_runtime = "\n".join(
        (
            "Information Center: Enabled",
            "Log host: Enabled",
            f"    {TARGET_IP},",
            "    port number: 5514, host facility: local7",
            "    192.0.2.99, log output filter: loghost1,",
            "    port number: 4514, DSCP value:0, host facility: local7",
            "Log buffer: Enabled",
        )
    )
    fingerprints = []
    for runtime in (MULTI_RUNTIME_5514, reversed_runtime):
        connection = _ConfigConnection(
            config_before=SOURCE_RULES_CONFIG,
            config_after=SOURCE_RULES_CONFIG,
            info_before=runtime,
            info_after=runtime,
        )
        result = _service(paths, repository, connection).check(
            run_id="run-1",
            run_date="2026-07-27",
            device_uuid=device_uuid,
            target_ip=TARGET_IP,
            target_port=5514,
            boot_tolerance_seconds=120,
        )
        assert result.config_status == "CONFIG_PRESENT"
        fingerprints.append(
            repository.latest_boot_session(device_uuid)["config_fingerprint"]
        )
    assert fingerprints[0] == fingerprints[1]


def test_info_center_overwrite_is_not_reported_as_udp_loss(tmp_path: Path) -> None:
    paths, repository, device_uuid = _context(tmp_path)
    first_info = FULL_RUNTIME_514.replace("overwritten messages 7837", "overwritten messages 1")
    second_info = FULL_RUNTIME_514.replace("overwritten messages 7837", "overwritten messages 2")
    for info in (first_info, second_info):
        _service(
            paths,
            repository,
            _ConfigConnection(
                config_before=FULL_CONFIG_514,
                config_after=FULL_CONFIG_514,
                info_before=info,
                info_after=info,
            ),
        ).check(
            run_id="run-1", run_date="2026-07-26", device_uuid=device_uuid,
            target_ip=TARGET_IP, target_port=514, boot_tolerance_seconds=120,
        )
    with sqlite3.connect(repository.db_path) as conn:
        codes = [row[0] for row in conn.execute("SELECT code FROM ground_unattended_health_events").fetchall()]
    assert "INFO_CENTER_BUFFER_OVERWRITTEN_INCREASED" in codes
    assert not any("UDP" in code and "OVERWRITTEN" in code for code in codes)


def test_repository_additively_migrates_syslog_runtime_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy" / "index.sqlite"
    repository = GroundUnattendedRepository(db_path, site_id="site-a")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            ALTER TABLE ground_unattended_train_endpoints DROP COLUMN last_syslog_source_ip;
            ALTER TABLE ground_unattended_train_endpoints DROP COLUMN syslog_hostname;
            ALTER TABLE ground_unattended_train_endpoints DROP COLUMN last_syslog_identity_verified_at;
            ALTER TABLE ground_unattended_boot_sessions DROP COLUMN info_center_metrics_json;
            ALTER TABLE ground_unattended_wmesh_events DROP COLUMN clock_offset_ms;
            ALTER TABLE ground_unattended_profiles DROP COLUMN allow_external_syslog_address;
            """
        )
    repository.initialize()
    with sqlite3.connect(repository.db_path) as conn:
        profile_columns = {row[1] for row in conn.execute("PRAGMA table_info(ground_unattended_profiles)")}
        ping_summary_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(ground_unattended_ping_summaries)")
        }
        endpoint_columns = {row[1] for row in conn.execute("PRAGMA table_info(ground_unattended_train_endpoints)")}
        train_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(ground_unattended_train_runs)")
        }
        boot_columns = {row[1] for row in conn.execute("PRAGMA table_info(ground_unattended_boot_sessions)")}
        event_columns = {row[1] for row in conn.execute("PRAGMA table_info(ground_unattended_wmesh_events)")}
        table_names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        schema_version = conn.execute(
            "SELECT value FROM ground_unattended_schema WHERE key='schema_version'"
        ).fetchone()[0]
    assert {"last_syslog_source_ip", "syslog_hostname", "last_syslog_identity_verified_at"} <= endpoint_columns
    assert {
        "allow_external_syslog_address",
        "deep_collection_master_enabled",
        "fleet_ping_warmup_seconds",
        "ping_depot_trains_enabled",
    } <= profile_columns
    assert {"raw_sample_count", "warmup_ignored_count"} <= ping_summary_columns
    assert {
        "info_center_metrics_json",
        "device_clock_before",
        "device_clock_after",
        "boot_time_uncertainty_seconds",
        "reboot_reason",
        "timezone_name",
        "utc_offset_seconds",
        "time_quality",
            "clock_jump_seconds",
            "expected_change_started_at",
        } <= boot_columns
    assert "clock_offset_ms" in event_columns
    assert {
        "ground_unattended_ping_target_activations",
        "ground_unattended_operations",
    } <= table_names
    assert {
        "ground_unattended_radio_interface_states",
        "ground_unattended_mr_runtime_states",
        "ground_unattended_radio_correlations",
    } <= table_names
    assert {
        "event_family",
        "interface_name",
        "physical_state",
        "cfg_event_index",
        "cfg_command_source",
        "expected_internal_change",
    } <= event_columns
    assert {
        "location_class_source",
        "participates_in_mainline",
        "mainline_reason_code",
        "mainline_reason_text",
        "ping_reason_code",
        "ping_reason_text",
        "deep_collection_reason_code",
        "deep_collection_reason_text",
        "decision_revision",
        "decision_source",
    } <= train_columns
    assert schema_version == "10"


def test_real_syslog_shapes_keep_parser_fields_and_clock_semantics(tmp_path: Path) -> None:
    parser = WmeshRealtimeParser()
    receive_time = datetime(2026, 7, 26, 5, 35, 49, tzinfo=timezone.utc)
    lines = (Path(__file__).parent / "fixtures" / "ground_unattended" / "h3c_mr_syslog_3cd.txt").read_text(encoding="utf-8").splitlines()
    rows = [parser.parse(line, receive_time=receive_time) for line in lines]

    assert [row["event_type"] for row in rows if row] == [
        "IFNET_PHY_UPDOWN", "MESH_LINKUP", "MESH_ACTIVELINK_SWITCH", "MESH_LINKDOWN", "MESH_ACTIVELINK_SWITCH",
    ]
    assert rows[0]["details"] == {
        "interface": "WLAN-Radio1/0/1",
        "interface_name": "WLAN-Radio1/0/1",
        "interface_type": "RADIO",
        "physical_state": "UP",
    }
    assert rows[1]["details"]["peer_radio_mode"] == 3
    assert rows[1]["details"]["rssi"] == 25
    assert rows[2]["details"]["old_active_link_missing"] is True
    assert rows[3]["details"]["reason_code"] == "WEAK_RSSI_LOCAL"
    assert rows[4]["details"]["new_peer_radio_mac"] == "0200-0000-00b1"
    assert rows[4]["device_time"].endswith("05:25:36.000+00:00")

    receiver = SyslogUdpReceiver(
        repository=GroundUnattendedRepository(tmp_path / "unused.sqlite", site_id="test"),
        site_id="test",
    )
    endpoint = {"device_uuid": "mr-1"}
    quality, offset = receiver._quality(endpoint, "VERIFIED", "first", rows[1], receive_time)
    assert quality == "CLOCK_OFFSET" and offset is not None
    later = receive_time.replace(minute=36)
    quality, _offset = receiver._quality(endpoint, "VERIFIED", "second", rows[1], later)
    assert quality == "CLOCK_JUMP"


def test_udp_receiver_preserves_sequences_facility_and_identity_states(tmp_path: Path) -> None:
    repository = GroundUnattendedRepository(tmp_path / "ground" / "index.sqlite", site_id="site-a")
    identity_database = Database(tmp_path / "devices.sqlite")
    identity_database.initialize()
    AcRepository(identity_database).replace_fit_ap_resources(
        "ac-1",
        [
            {
                "ap_uuid": "ap-1",
                "ap_name": "AP-01",
                "ap_mac": "0100-0000-0001",
                "site": "站点A",
                "rid1_bbssid": "0200-0000-0001",
            }
        ],
    )
    identity_query = ApIdentityQueryService(identity_database)
    identity_query.rebuild_index("test_ac_refresh")
    repository.sync_inventory(
        trains=[{"train_id": "train-01", "train_no": "01", "train_name": "T01"}],
        endpoints=[{
            "device_uuid": "mr-ct-01", "device_id": 1, "train_id": "train-01", "mr_role": "CT",
            "device_name": "TEST-MR-CT", "source_hostname": "TEST-MR-CT", "management_ip": "127.0.0.1",
        }],
    )
    _waiting_boot(repository, "mr-ct-01")
    receiver = SyslogUdpReceiver(
        repository=repository,
        site_id="site-a",
        ap_identity_query_service=identity_query,
    )
    receiver.start(
        run_id="run-1", run_date="2026-07-26", active_dir=tmp_path / "ground" / "active" / "2026-07-26",
        listen_host="127.0.0.1", listen_port=0, queue_capacity=20, flush_records=1,
        flush_interval_seconds=0.1, event_batch_size=1, event_batch_interval_seconds=0.1,
    )
    port = int(receiver.health_snapshot()["udp_listen_address"].rsplit(":", 1)[1])
    payloads = [
        b"<189>Jul 26 05:25:35 2026 TEST-MR-CT %%10WMESH/5/MESH_LINKUP: Mesh Link on the interface WLAN-MeshLink841 is up: peer MAC = 0200-0000-0001, peer radio mode = 3, RSSI = 25",
        b"<189>Jul 26 05:25:35 2026 TEST-MR-CT %%10WMESH/5/MESH_LINKDOWN: Mesh link on interface WLAN-MeshLink841 is down: peer MAC = 0200-0000-0001, RSSI = 15, reason: Radio status change (local).",
    ]
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
        for payload in payloads:
            sender.sendto(payload, ("127.0.0.1", port))
    _wait_until(lambda: len(repository.list_wmesh_events(run_id="run-1")) == 2)
    receiver.stop()
    raw_path = repository.db_path.parent / repository.list_raw_files(data_type="syslog")[0]["relative_path"]
    raw_rows = [json.loads(line) for line in raw_path.read_text(encoding="utf-8").splitlines()]
    assert [row["global_receive_sequence"] for row in raw_rows] == [1, 2]
    assert [row["source_receive_sequence"] for row in raw_rows] == [1, 2]
    assert raw_rows[0]["facility"] == "local7" and raw_rows[0]["severity"] == "notice"
    assert raw_rows[0]["identity_status"] == "VERIFIED"
    assert raw_rows[0]["resolved_ap_name"] == "AP-01"
    assert raw_rows[0]["parsed_details"]["identity_entity_id"]
    assert raw_rows[0]["parsed_details"]["identity_revision"] == 1
    assert raw_rows[0]["raw_bytes_base64"]
    assert repository.latest_boot_session("mr-ct-01")["config_status"] == "LOG_ACTIVE"
    assert receiver._resolve_identity("127.0.0.1", "other-host")[1] == "UNCONFIRMED_SOURCE_IP"
    assert receiver._resolve_identity("203.0.113.9", "test-mr-ct")[1] == "UNCONFIRMED_HOSTNAME"
    receiver._endpoint_by_hostname["other-host"] = [{"device_uuid": "other"}]
    assert receiver._resolve_identity("127.0.0.1", "other-host") == (None, "IDENTITY_CONFLICT")


def test_udp_receiver_counts_unidentified_and_identity_conflict_separately(
    tmp_path: Path,
) -> None:
    receiver = SyslogUdpReceiver(
        repository=GroundUnattendedRepository(
            tmp_path / "ground" / "index.sqlite", site_id="site-a"
        ),
        site_id="site-a",
    )
    receiver._endpoint_by_ip["192.0.2.10"] = [{"device_uuid": "mr-a"}]
    receiver._endpoint_by_hostname["mr-b"] = [{"device_uuid": "mr-b"}]
    received_at = "2026-07-30T08:00:00+08:00"
    receiver._process(
        UdpEnvelope(
            source_ip="192.0.2.10",
            source_port=514,
            receive_time=received_at,
            global_receive_sequence=1,
            source_receive_sequence=1,
            payload=b"<189>Jul 30 08:00:00 2026 MR-B WMESH/5/MESH_LINKUP: peer AP-A_0000-0000-0001",
        )
    )
    receiver._process(
        UdpEnvelope(
            source_ip="192.0.2.11",
            source_port=514,
            receive_time=received_at,
            global_receive_sequence=2,
            source_receive_sequence=1,
            payload=b"<189>Jul 30 08:00:00 2026 UNKNOWN WMESH/5/MESH_LINKUP: peer AP-A_0000-0000-0001",
        )
    )

    health = receiver.health_snapshot()
    assert health["udp_identity_conflict_count"] == 1
    assert health["udp_unidentified_count"] == 1


def _context(tmp_path: Path) -> tuple[PathResolver, GroundUnattendedRepository, str]:
    paths = PathResolver(tmp_path / "app", tmp_path / "data")
    site_id = "site-a"
    database = Database(paths.site_db_path(site_id))
    database.initialize()
    device = DeviceRepository(database).create(
        Device(name="TEST-MR-CT", primary_address="192.0.2.10", ssh_enabled=1, ssh_username="admin", ssh_password="secret")
    )
    repository = GroundUnattendedRepository(paths.ground_unattended_db_path(site_id), site_id=site_id)
    repository.sync_inventory(
        trains=[{"train_id": "train-01", "train_no": "01", "train_name": "T01"}],
        endpoints=[{
            "device_uuid": str(device.device_uuid), "device_id": device.id, "train_id": "train-01", "mr_role": "CT",
            "device_name": device.name, "source_hostname": "TEST-MR-CT", "management_ip": device.primary_address,
        }],
    )
    return paths, repository, str(device.device_uuid)


def _service(paths: PathResolver, repository: GroundUnattendedRepository, connection: "_ConfigConnection") -> MrSyslogConfigService:
    return MrSyslogConfigService(paths, site_id="site-a", repository=repository, connection_factory=lambda _config: connection)


class _ConfigConnection:
    def __init__(
        self,
        *,
        config_before: str,
        config_after: str,
        info_before: str,
        info_after: str,
        filter_fails: bool = False,
        write_results: dict[str, str] | None = None,
        clock_output: str = (
            "11:26:48 BeiJing Mon 07/27/2026\n"
            "Time Zone : BeiJing add 08:00:00\n"
        ),
    ) -> None:
        self.config_before = config_before
        self.config_after = config_after
        self.info_before = info_before
        self.info_after = info_after
        self.filter_fails = filter_fails
        self.write_results = write_results or {}
        self.clock_output = clock_output
        self.commands: list[str] = []
        self._write_started = False

    def send_command(self, command: str, _timeout: int) -> str:
        self.commands.append(command)
        if command == "screen-length disable":
            return ""
        if command == "display clock":
            return self.clock_output
        if command == "display version":
            return (
                "H3C MR uptime is 1 day, 2 hours, 3 minutes\n"
                "Last reboot reason : Power on\n"
            )
        if command == "display info-center":
            return self.info_after if self._write_started else self.info_before
        if command == "display current-configuration | include info-center":
            if self.filter_fails:
                return "% Wrong parameter"
            return self.config_after if self._write_started else self.config_before
        if command == "display current-configuration":
            return self.config_after if self._write_started else self.config_before
        self._write_started = True
        return self.write_results.get(command, "")

    def close(self) -> None:
        return None


def _waiting_boot(repository: GroundUnattendedRepository, device_uuid: str) -> None:
    now = datetime.now().astimezone()
    row, _created = MrBootSessionService(repository=repository).observe(
        device_uuid=device_uuid, device_id=1, train_id="train-01", mr_role="CT", checked_at=now,
        uptime_seconds=3600, evidence_path="evidence/test.json",
    )
    row["config_status"] = "WAITING_FIRST_LOG"
    repository.upsert_boot_session(row)


def _wait_until(predicate, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not met")
