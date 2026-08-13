from __future__ import annotations

import json
from pathlib import Path

from netconsole.core.runtime_profile import (
    HostEnvironmentProfile,
    ProfileValue,
    RuntimeCapabilityPolicy,
    collect_host_environment_profile,
    read_host_environment_profile,
    write_host_environment_profile,
    RuntimePerformanceMode,
    read_runtime_performance_mode,
)


def test_profile_atomic_round_trip_and_fail_safe_schema(tmp_path: Path) -> None:
    path = tmp_path / "runtime" / "environment" / "host-profile.json"
    profile = HostEnvironmentProfile(cpu={"logical_processors": ProfileValue(2, "test", "high")})
    write_host_environment_profile(path, profile)
    assert read_host_environment_profile(path) == profile
    path.write_text(json.dumps({"schema_version": 999}), encoding="utf-8")
    assert read_host_environment_profile(path) is None
    path.write_text("{broken", encoding="utf-8")
    assert read_host_environment_profile(path) is None


def test_opaque_raid_does_not_infer_level() -> None:
    def runner(command, _timeout):
        if command[:2] == ["wmic", "diskdrive"]:
            return "Model=DELL PERC H730\r\nMediaType=Fixed hard disk media\r\n"
        if command[:2] == ["wmic", "computersystem"]:
            return "TotalPhysicalMemory=8589934592\r\n"
        if command[:2] == ["wmic", "os"]:
            return "Caption=Windows Server 2012 R2\r\nProductType=3\r\n"
        if command[:2] == ["wmic", "cpu"]:
            return "Name=Intel Xeon\r\nNumberOfCores=4\r\nNumberOfLogicalProcessors=8\r\n"
        raise AssertionError(command)

    # Simulate Windows without changing the host running the test.
    import netconsole.core.runtime_profile as module

    original = module.os.name
    try:
        module.os.name = "nt"
        profile = collect_host_environment_profile(command_runner=runner)
    finally:
        module.os.name = original
    assert profile.storage["hardware_raid"].value == "likely"
    assert profile.storage["raid_level"].value == "unknown"


def test_windows_fallback_and_bounded_timeout() -> None:
    commands = []

    def runner(command, timeout):
        commands.append((list(command), timeout))
        raise TimeoutError("simulated slow WMI")

    import netconsole.core.runtime_profile as module

    original = module.os.name
    try:
        module.os.name = "nt"
        profile = collect_host_environment_profile(command_runner=runner, timeout_seconds=60)
    finally:
        module.os.name = original
    assert profile.memory == {}
    assert all(timeout <= 15 for _, timeout in commands)
    assert any(command[0] == "wmic" for command, _ in commands)


def test_low_host_policy_clamps_noncritical_concurrency() -> None:
    profile = HostEnvironmentProfile(
        cpu={"logical_processors": ProfileValue(2, "test", "high")},
        memory={"bytes": ProfileValue(4 * 1024**3, "test", "high")},
    )
    policy = RuntimeCapabilityPolicy.from_profile(profile)
    assert policy.cpu_worker_limit == 1
    assert policy.network_concurrency == 2
    assert policy.disk_maintenance_concurrency == 1
    assert policy.cache_warmup_enabled is False


def test_server_unattended_mode_reserves_noncritical_capacity(tmp_path: Path) -> None:
    profile = HostEnvironmentProfile(cpu={"logical_processors": ProfileValue(8, "test", "high")})
    policy = RuntimeCapabilityPolicy.from_profile(
        profile,
        mode=RuntimePerformanceMode.SERVER_UNATTENDED,
    )
    assert policy.unattended_priority is True
    assert policy.low_priority_work_enabled is False
    assert policy.cache_warmup_enabled is False
    assert policy.cpu_worker_limit == 2

    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"app/runtime_performance_mode": "server_unattended"}), encoding="utf-8")
    assert read_runtime_performance_mode(settings) is RuntimePerformanceMode.SERVER_UNATTENDED
    assert read_runtime_performance_mode(tmp_path / "missing.json") is RuntimePerformanceMode.STANDARD


def test_runtime_policy_caps_noncritical_cpu_workers() -> None:
    policy = RuntimeCapabilityPolicy(cpu_worker_limit=2)

    assert policy.clamp_cpu_workers(8) == 2
    assert policy.clamp_cpu_workers(1) == 1
