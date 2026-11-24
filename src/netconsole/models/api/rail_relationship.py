from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from netconsole.models.api.common import ApiModel

RelationshipType = Literal[
    "node_project",
    "device_node",
    "device_section",
    "ac_service",
    "train_mr",
]
RelationshipAction = Literal["create", "update", "terminate", "replace"]


class RelationshipMutationRequest(ApiModel):
    site_id: str = ""
    relationship_type: RelationshipType
    action: RelationshipAction
    relationship_id: str = ""
    source_uid: str = ""
    target_uid: str = ""
    values: dict[str, Any] = Field(default_factory=dict)
    effective_from: str = ""
    effective_to: str = ""
    reason: str = ""
    actor: str = ""
    base_revision: str
    explicit_confirmation: bool = False


class RelationshipRecord(ApiModel):
    relationship_type: str
    relationship_id: str
    source_uid: str
    target_uid: str
    status: Literal["active", "terminated"]
    values: dict[str, Any] = Field(default_factory=dict)
    effective_from: str = ""
    effective_to: str = ""


class RelationshipHistoryRecord(ApiModel):
    event_id: str
    relationship_type: str
    relationship_id: str
    action: str
    source_uid: str
    target_uid: str
    before: dict[str, Any] = Field(default_factory=dict)
    after: dict[str, Any] = Field(default_factory=dict)
    effective_from: str = ""
    effective_to: str = ""
    reason: str = ""
    actor: str = ""
    changed_at: str
    revision: str


class RelationshipPage(ApiModel):
    items: list[RelationshipRecord] = Field(default_factory=list)
    total: int = 0
    revision: str


class RelationshipHistoryPage(ApiModel):
    items: list[RelationshipHistoryRecord] = Field(default_factory=list)
    total: int = 0


class RelationshipMutationResult(ApiModel):
    relationship: RelationshipRecord | None = None
    revision: str
    history_event_id: str
    warnings: list[str] = Field(default_factory=list)
