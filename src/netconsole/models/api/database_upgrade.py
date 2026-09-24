from __future__ import annotations

from typing import Literal

from pydantic import Field

from netconsole.models.api.common import ApiModel


class DatabaseUpgradeRequest(ApiModel):
    database_kind: Literal["mesh_derived"] = "mesh_derived"
    profile_id: str = Field(min_length=1, max_length=160)
    authorization_token: str = Field(default="", max_length=128)


class DatabaseBatchRequest(ApiModel):
    database_kind: Literal["mesh_derived"] = "mesh_derived"
    profile_ids: list[str] = Field(min_length=1, max_length=100)
    confirmed: bool = False
    authorization_token: str = Field(default="", max_length=128)


class DatabaseBackupActionRequest(ApiModel):
    confirmed: bool = False
    authorization_token: str = Field(default="", max_length=128)


class DatabaseBackupBatchDeleteRequest(ApiModel):
    backup_ids: list[str] = Field(min_length=1, max_length=500)
    confirmed: bool = False
    authorization_token: str = Field(default="", max_length=128)


class DatabaseTaskReferenceDTO(ApiModel):
    task_id: str
    task_type: str


__all__ = [
    "DatabaseBackupActionRequest",
    "DatabaseBackupBatchDeleteRequest",
    "DatabaseBatchRequest",
    "DatabaseTaskReferenceDTO",
    "DatabaseUpgradeRequest",
]
