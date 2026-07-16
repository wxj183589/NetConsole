from __future__ import annotations

from pathlib import Path

from netconsole.core.paths import PathResolver
from netconsole.services.job_center.job_context import JobContext
from netconsole.services.rail_transit.car_network_diagnostic import CarNetworkNode, CarNetworkTrain
from netconsole.services.rail_transit import car_network_diagnostic_job


def test_car_network_diagnostic_job_calls_real_service_boundary(monkeypatch, tmp_path: Path) -> None:
    train = CarNetworkTrain("train-1", "01", "01车")
    node = CarNetworkNode("train-1", "TC1-MR", "MR", train_no="01")
    captured: dict[str, object] = {}
    progress_rows: list[tuple[str, int, int, str]] = []

    monkeypatch.setattr(car_network_diagnostic_job, "Database", lambda _path: object())
    monkeypatch.setattr(car_network_diagnostic_job, "DeviceRepository", lambda _database: object())
    monkeypatch.setattr(car_network_diagnostic_job, "build_car_network_trains", lambda _repository, _site: [train])
    monkeypatch.setattr(
        car_network_diagnostic_job,
        "CarNetworkPointTableStore",
        lambda _paths, _site: type("Store", (), {"load": lambda self: [node]})(),
    )
    monkeypatch.setattr(car_network_diagnostic_job, "discover_ac_devices", lambda _repository: ["ac"])
    monkeypatch.setattr(car_network_diagnostic_job, "discover_core_switch_candidates", lambda _repository, _site: [])

    class FakeResult:
        def to_json_dict(self) -> dict[str, object]:
            return {"status": "normal", "conclusion": "fixture"}

    class FakeDiagnosticService:
        def __init__(self, nodes, **kwargs) -> None:
            captured.update(nodes=nodes, **kwargs)

        def run(self, progress):
            progress("stage", "检测中")
            progress("progress_meta", {"completed": 2, "total": 3, "message": "跨TC通信"})
            return FakeResult()

    monkeypatch.setattr(car_network_diagnostic_job, "CarNetworkDiagnosticService", FakeDiagnosticService)
    context = JobContext(
        "task-1",
        "car_network_diagnostic",
        {"site_name": "demo", "train_id": "train-1", "db_path": str(tmp_path / "site.sqlite")},
        lambda stage, current, total, message: progress_rows.append((stage, current, total, message)),
        lambda: False,
        PathResolver(app_root=tmp_path, data_root=tmp_path),
    )

    result = car_network_diagnostic_job.run_car_network_diagnostic(context)

    assert result == {"status": "normal", "conclusion": "fixture"}
    assert captured["nodes"] == [node]
    assert captured["train"] == train
    assert captured["ac_devices"] == ["ac"]
    assert captured["site_name"] == "demo"
    assert progress_rows[-1] == ("progress_meta", 2, 3, "跨TC通信")


def test_car_network_diagnostic_job_rejects_missing_train(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(car_network_diagnostic_job, "Database", lambda _path: object())
    monkeypatch.setattr(car_network_diagnostic_job, "DeviceRepository", lambda _database: object())
    monkeypatch.setattr(car_network_diagnostic_job, "build_car_network_trains", lambda _repository, _site: [])
    context = JobContext(
        "task-1",
        "car_network_diagnostic",
        {"site_name": "demo", "train_id": "missing", "db_path": str(tmp_path / "site.sqlite")},
        None,
        None,
        PathResolver(app_root=tmp_path, data_root=tmp_path),
    )

    try:
        car_network_diagnostic_job.run_car_network_diagnostic(context)
    except ValueError as exc:
        assert "列车不存在" in str(exc)
    else:
        raise AssertionError("missing train must fail")
