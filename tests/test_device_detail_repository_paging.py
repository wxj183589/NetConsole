from __future__ import annotations

from pathlib import Path

from netconsole.core.database import Database
from netconsole.core.paths import PathResolver
from netconsole.models.api.config_collection import ConfigSnapshotDTO
from netconsole.models.device import Device
from netconsole.models.task_snapshot import TaskSnapshot
from netconsole.models.task_state import TaskState
from netconsole.repositories.config_snapshot_repository import (
    ConfigSnapshot,
    ConfigSnapshotRepository,
)
from netconsole.repositories.device_repository import DeviceRepository
from netconsole.repositories.task_repository import TaskRepository
from netconsole.services.config_collection_web_service import (
    ConfigCollectionApplicationService,
)
from netconsole.services.job_center.task_application_service import (
    TaskApplicationService,
)


def test_config_snapshot_repository_and_application_service_page_in_sql(
    tmp_path: Path,
) -> None:
    paths = PathResolver(app_root=Path(__file__).parents[1], data_root=tmp_path)
    database = Database(paths.site_db_path("demo"))
    database.initialize()
    device = DeviceRepository(database).create(
        Device(
            name="SW-PAGE",
            primary_address="192.0.2.10",
            device_vendor="H3C",
            device_type="SW",
        )
    )
    repository = ConfigSnapshotRepository(database, ensure_schema=False)
    for index in range(3):
        relative = f"files/config_center/snapshots/SW-PAGE/running-{index}.txt"
        path = paths.site_dir("demo") / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"snapshot-{index}", encoding="utf-8")
        repository.create(
            ConfigSnapshot(
                id=None,
                device_id=device.id,
                device_uuid=str(device.device_uuid),
                timestamp=f"2026-07-19T12:0{index}:00",
                type="running",
                file_path=relative,
                hash=str(index) * 64,
            )
        )

    page = repository.list_for_device_page(
        str(device.device_uuid), "running", limit=1, offset=1
    )
    assert repository.count_for_device(str(device.device_uuid), "running") == 3
    assert [item.timestamp for item in page] == ["2026-07-19T12:01:00"]

    repository.create(
        ConfigSnapshot(
            id=None,
            device_id=device.id,
            device_uuid=str(device.device_uuid),
            timestamp="2026-07-19T13:00:00",
            type="running",
            file_path="files/config_center/snapshots/missing.txt",
            hash="f" * 64,
        )
    )

    service = ConfigCollectionApplicationService(
        paths,
        TaskApplicationService(paths=paths, site_name="demo"),
    )
    items, total = service.list_snapshots_page(
        "demo", int(device.id or 0), "running", limit=1, offset=0
    )
    assert total == 4
    assert len(items) == 1
    assert isinstance(items[0], ConfigSnapshotDTO)
    assert items[0].timestamp == "2026-07-19T13:00:00"
    assert items[0].size_bytes is None
    second_page, second_total = service.list_snapshots_page(
        "demo", int(device.id or 0), "running", limit=1, offset=1
    )
    assert second_total == 4
    assert second_page[0].timestamp == "2026-07-19T12:02:00"
    service.close()


def test_task_repository_filters_device_aliases_status_and_count_in_sql(
    tmp_path: Path,
) -> None:
    repository = TaskRepository(tmp_path / "tasks.db")
    rows = (
        ("task-a", "device-a", TaskState.COMPLETED),
        ("task-b", "device-b", TaskState.FAILED),
        ("task-c", "device-c", TaskState.FAILED),
    )
    for index, (task_id, device, status) in enumerate(rows):
        repository.save(
            TaskSnapshot(
                task_id=task_id,
                task_type="device_detail_collect",
                task_name=task_id,
                status=status,
                created_time=f"2026-07-19T12:0{index}:00",
                updated_time=f"2026-07-19T12:0{index}:00",
                device=device,
            )
        )

    page = repository.list_filtered(
        statuses={TaskState.FAILED},
        device_aliases={"device-a", "device-b"},
        limit=1,
        offset=0,
    )
    assert [item.task_id for item in page] == ["task-b"]
    assert (
        repository.count_filtered(
            statuses={TaskState.FAILED},
            device_aliases={"device-a", "device-b"},
        )
        == 1
    )
