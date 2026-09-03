from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Mapping, Sequence

from netconsole.models.device import Device
from netconsole.services.rail_transit.mr_end_role_service import mr_position
from netconsole.services.rail_transit.train_identity import canonical_train_id_for
from netconsole.services.vehicle_mr_online import (
    TrainIdentity,
    is_vehicle_mr_device,
    parse_train_identity,
    parse_train_identity_from_device,
)


VEHICLE_MR_TRAIN_UNRESOLVED = "VEHICLE_MR_TRAIN_UNRESOLVED"
VEHICLE_MR_POSITION_UNRESOLVED = "VEHICLE_MR_POSITION_UNRESOLVED"
VEHICLE_MR_DUPLICATE_POSITION = "VEHICLE_MR_DUPLICATE_POSITION"
VEHICLE_MR_DEVICE_DUPLICATE_BINDING = "VEHICLE_MR_DEVICE_DUPLICATE_BINDING"
VEHICLE_MR_TRAIN_AMBIGUOUS = "VEHICLE_MR_TRAIN_AMBIGUOUS"


@dataclass(frozen=True)
class VehicleMrReconciliationIssue:
    code: str
    severity: str
    device_binding_id: str
    device_name: str
    message: str


@dataclass(frozen=True)
class VehicleMrDeviceRelation:
    """The read-only Device -> VehicleMr -> Train projection facts."""

    device: Device
    group_name: str
    identity: TrainIdentity
    position_code: str
    physical_end: str
    car_number: int | None

    @property
    def device_binding_id(self) -> str:
        return str(self.device.device_uuid or f"device:{self.device.id}")

    @property
    def canonical_train_id(self) -> str:
        return canonical_train_id_for(self.identity.train_id, self.identity.train_no)


@dataclass(frozen=True)
class VehicleMrReconciliationResult:
    relations: tuple[VehicleMrDeviceRelation, ...] = ()
    issues: tuple[VehicleMrReconciliationIssue, ...] = ()


class VehicleMrReconciliationService:
    """Build the single deterministic MR relation projection for a site.

    The current rail base-data contract intentionally has no second persisted
    ``trains`` or ``vehicle_mrs`` table.  Reconciliation therefore means
    rebuilding this projection from the authoritative Device rows on every
    query.  It is idempotent by construction, immediately reflects writes, and
    cannot copy credentials or create duplicate derived records.
    """

    def reconcile(
        self,
        devices: Sequence[Device],
        group_names: Mapping[int, object] | None = None,
    ) -> VehicleMrReconciliationResult:
        groups = group_names or {}
        relations: list[VehicleMrDeviceRelation] = []
        issues: list[VehicleMrReconciliationIssue] = []

        for device in devices:
            group_name = self._group_name(groups, device.group_id)
            if not is_vehicle_mr_device(device, group_name):
                continue
            identity = parse_train_identity_from_device(device)
            binding_id = str(device.device_uuid or f"device:{device.id}")
            if identity is None or not identity.train_no:
                issues.append(
                    VehicleMrReconciliationIssue(
                        VEHICLE_MR_TRAIN_UNRESOLVED,
                        "error",
                        binding_id,
                        device.name,
                        "MR 无法解析列车号和 CT/CW 位置",
                    )
                )
                continue

            # Station is authoritative when it contains a train number.  A
            # conflict with the explicit name is not silently resolved.
            name_identity = parse_train_identity(device.name)
            if (
                name_identity is not None
                and name_identity.train_no
                and name_identity.train_no != identity.train_no
            ):
                issues.append(
                    VehicleMrReconciliationIssue(
                        VEHICLE_MR_TRAIN_AMBIGUOUS,
                        "warning",
                        binding_id,
                        device.name,
                        f"设备名称列车号 {name_identity.train_no} 与站点列车号 {identity.train_no} 冲突",
                    )
                )

            position_code, physical_end, car_number = mr_position(identity.car_end)
            if position_code == "unknown":
                issues.append(
                    VehicleMrReconciliationIssue(
                        VEHICLE_MR_POSITION_UNRESOLVED,
                        "error",
                        binding_id,
                        device.name,
                        "MR 无法解析 CT/CW 位置",
                    )
                )
                continue
            relations.append(
                VehicleMrDeviceRelation(
                    device=device,
                    group_name=group_name,
                    identity=identity,
                    position_code=position_code,
                    physical_end=physical_end,
                    car_number=car_number,
                )
            )

        by_position: dict[tuple[str, str], list[VehicleMrDeviceRelation]] = defaultdict(list)
        by_binding: dict[str, list[VehicleMrDeviceRelation]] = defaultdict(list)
        for relation in relations:
            by_position[(relation.canonical_train_id, relation.position_code)].append(relation)
            by_binding[relation.device_binding_id].append(relation)
        for duplicate_rows in by_position.values():
            if len(duplicate_rows) < 2:
                continue
            names = "、".join(row.device.name for row in duplicate_rows)
            for row in duplicate_rows:
                issues.append(
                    VehicleMrReconciliationIssue(
                        VEHICLE_MR_DUPLICATE_POSITION,
                        "error",
                        row.device_binding_id,
                        row.device.name,
                        f"同一列车同一位置存在多个 MR：{names}",
                    )
                )
        for duplicate_rows in by_binding.values():
            if len(duplicate_rows) < 2:
                continue
            for row in duplicate_rows:
                issues.append(
                    VehicleMrReconciliationIssue(
                        VEHICLE_MR_DEVICE_DUPLICATE_BINDING,
                        "error",
                        row.device_binding_id,
                        row.device.name,
                        "同一 Device 被重复绑定为 VehicleMr",
                    )
                )

        relations.sort(
            key=lambda row: (
                row.canonical_train_id,
                row.position_code,
                row.device.name.casefold(),
                row.device_binding_id,
            )
        )
        return VehicleMrReconciliationResult(tuple(relations), tuple(issues))

    @staticmethod
    def _group_name(groups: Mapping[int, object], group_id: int | None) -> str:
        if group_id is None:
            return ""
        try:
            return str(groups.get(int(group_id), "") or "")
        except (TypeError, ValueError):
            return ""


__all__ = [
    "VEHICLE_MR_TRAIN_UNRESOLVED",
    "VEHICLE_MR_POSITION_UNRESOLVED",
    "VEHICLE_MR_DUPLICATE_POSITION",
    "VEHICLE_MR_DEVICE_DUPLICATE_BINDING",
    "VEHICLE_MR_TRAIN_AMBIGUOUS",
    "VehicleMrDeviceRelation",
    "VehicleMrReconciliationIssue",
    "VehicleMrReconciliationResult",
    "VehicleMrReconciliationService",
]
