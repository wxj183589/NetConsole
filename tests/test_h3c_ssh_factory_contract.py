from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

MAIN_H3C_CLI_MODULES = (
    "src/netconsole/services/h3c_ac_collect_service.py",
    "src/netconsole/services/h3c_collect_service.py",
    "src/netconsole/services/h3c_optical_refresh_service.py",
    "src/netconsole/services/online_mr_collector.py",
    "src/netconsole/services/file_transfer_service.py",
    "src/netconsole/services/rail_transit/trackside_optical_collection.py",
    "src/netconsole/services/rail_transit/switch_vendor_sample_job.py",
)


def test_h3c_cli_collectors_use_the_shared_compatibility_entrypoint() -> None:
    for relative_path in MAIN_H3C_CLI_MODULES:
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "netmiko_connection.ConnectHandler" in source, relative_path
    assert "SSHClient(" not in source, relative_path


def test_car_network_cli_compatibility_wrapper_delegates_to_shared_factory() -> None:
    source = (
        ROOT / "src" / "netconsole" / "services" / "rail_transit"
        / "car_network_diagnostic.py"
    ).read_text(encoding="utf-8")

    assert "from netconsole.services.netmiko_connection import" in source
    assert "ssh_connection_context(" in source
    assert "return connect_handler(**kwargs)" in source
    assert "paramiko.SSHClient(" not in source


def test_direct_paramiko_clients_are_limited_to_non_cli_boundaries() -> None:
    direct_clients = sorted(
        path.relative_to(ROOT).as_posix()
        for path in ROOT.joinpath("src", "netconsole").rglob("*.py")
        if "paramiko.SSHClient(" in path.read_text(encoding="utf-8")
    )

    assert direct_clients == [
        "src/netconsole/services/file_transfer_service.py",
        "src/netconsole/services/ssh_tunnel.py",
    ]


def test_mr_sidecar_has_the_same_normal_then_legacy_ssh_rsa_contract() -> None:
    source = (
        ROOT / "apps" / "agent" / "mr_collector_py" / "collector_cli.py"
    ).read_text(encoding="utf-8")

    assert "def ssh_connection_factory(" in source
    assert 'record("normal", 1, "starting")' in source
    assert 'record("legacy_ssh_rsa", 2, "success")' in source
    assert "_legacy_ssh_rsa_params" in source
