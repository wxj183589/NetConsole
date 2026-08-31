from __future__ import annotations

from typing import Literal

from pydantic import Field

from netconsole.models.api.common import ApiModel


class DatabaseUpgradeRequest(ApiModel):
    database_kind: Literal["mesh_derived"] = "mesh_derived"
    profile_id: str = Field(min_length=1, max_length=160)


class DatabaseBatchRequest(ApiModel):
    database_kind: Literal["mesh_derived"] = "mesh_derived"
    profile_ids: list[str] = Field(min_length=1, max_length=100)
    confirmed: bool = False


class DatabaseBackupActionRequest(ApiModel):
    confirmed: bool = False


class DatabaseTaskReferenceDTO(ApiModel):
    task_id: str
    task_type: str


__all__ = [
    "DatabaseBackupActionRequest",
    "DatabaseBatchRequest",
    "DatabaseTaskReferenceDTO",
    "DatabaseUpgradeRequest",
]
