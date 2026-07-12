from __future__ import annotations

from dataclasses import dataclass

from netconsole.repositories.device_group_repository import DeviceGroupRepository
from netconsole.repositories.device_repository import DeviceRepository


ALL_GROUPS = "__all_groups__"
UNGROUPED = "__ungrouped__"


@dataclass(frozen=True)
class AssignGroupResult:
    success: int
    failed: int


class DeviceGroupService:
    def __init__(self, device_repository: DeviceRepository, group_repository: DeviceGroupRepository) -> None:
        self.device_repository = device_repository
        self.group_repository = group_repository

    def assign_devices(self, device_ids: list[int], group_id: int | None) -> AssignGroupResult:
        success = 0
        failed = 0
        for device_id in device_ids:
            try:
                self.device_repository.update_group(device_id, group_id)
                success += 1
            except Exception:
                failed += 1
        return AssignGroupResult(success, failed)

    def delete_and_unassign(self, group_id: int) -> None:
        self.group_repository.delete(group_id)


def group_filter_to_repository_value(value: object) -> int | str | None:
    if value == ALL_GROUPS:
        return None
    if value == UNGROUPED:
        return UNGROUPED
    if value is None:
        return None
    return int(value)
