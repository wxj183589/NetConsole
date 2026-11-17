"""Immutable, secret-free values shared by Site inventory readers."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from types import MappingProxyType

from netconsole.models.api.ground_unattended import GroundInventorySummaryDTO


def freeze_inventory(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: freeze_inventory(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze_inventory(item) for item in value)
    return value


def thaw_inventory(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: thaw_inventory(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_inventory(item) for item in value]
    return value


@dataclass(frozen=True)
class DeviceInventoryMetadata:
    backup_address: str
    system_name: str
    connection_eligible: bool
    connection_ready: bool


@dataclass(frozen=True)
class InventoryCollection:
    site_id: str
    trains: tuple[Mapping[str, Any], ...]
    endpoints: tuple[Mapping[str, Any], ...]
    summary: Mapping[str, Any]
    conflicts: tuple[str, ...]
    revision: str
    generated_at: str
    mrs: tuple[Mapping[str, Any], ...]
    source_revision: str = ""

    def __iter__(self):
        # Existing callers may unpack a collection; give them independent values.
        yield thaw_inventory(self.trains)
        yield thaw_inventory(self.endpoints)
        yield GroundInventorySummaryDTO.model_validate(thaw_inventory(self.summary))
        yield list(self.conflicts)


@dataclass(frozen=True)
class SiteInventorySnapshot:
    site_id: str
    trains: tuple[Mapping[str, Any], ...]
    active_trains: tuple[Mapping[str, Any], ...]
    state: Mapping[str, Any]
    revision: str
    generated_at: str
    loaded_at: float

    def inventory(self, *, include_removed: bool = False):
        return self.trains if include_removed else self.active_trains
