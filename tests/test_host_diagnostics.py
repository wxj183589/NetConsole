from types import SimpleNamespace

import pytest

from netconsole.services.network_tools import host_diagnostics


@pytest.mark.parametrize(
    ("kind", "target", "program", "args"),
    [
        ("traceroute", "127.0.0.1", "tracert.exe", ["-d", "-h", "12", "-w", "500", "127.0.0.1"]),
        ("dns", "localhost", "nslookup.exe", ["-timeout=2", "-retry=1", "localhost."]),
    ],
)
def test_diagnostic_uses_fixed_system_program(monkeypatch, kind, target, program, args):
    monkeypatch.setattr(host_diagnostics, "os", SimpleNamespace(name="nt", environ={}))
    monkeypatch.setattr(host_diagnostics.Path, "is_file", lambda _: True)

    def run(argv, **options):
        assert argv[0].endswith(program)
        assert argv[1:] == args
        assert options["timeout"] == 25
        return SimpleNamespace(stdout=b"fixture output")

    monkeypatch.setattr(host_diagnostics.subprocess, "run", run)
    assert host_diagnostics.run_host_diagnostic(kind, target) == "fixture output"


@pytest.mark.parametrize(("kind", "target"), [("traceroute", "127.0.0.0/24"), ("dns", "-option"), ("dns", "a.example b.example")])
def test_diagnostic_rejects_extra_targets_and_options(kind, target):
    with pytest.raises(ValueError):
        host_diagnostics.run_host_diagnostic(kind, target)
