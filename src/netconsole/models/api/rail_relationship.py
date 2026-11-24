from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

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
    relationship_id: str = Field(default="", max_length=512)
    source_uid: str = Field(default="", max_length=160)
    target_uid: str = Field(default="", max_length=160)
    values: dict[str, Any] = Field(default_factory=dict)
    effective_from: str = ""
    effective_to: str = ""
    reason: str = Field(default="", max_length=1000)
    actor: str = Field(default="", max_length=160)
    idempotency_key: str = Field(default="", max_length=128)
    target_uids: list[str] = Field(default_factory=list, max_length=200)
    base_revision: str
    explicit_confirmation: bool = False

    @model_validator(mode="after")
    def validate_values(self):
        allowed = {
            "device_node": {"engineering_role", "installation_location"},
            "device_section": {"engineering_role", "installation_location"},
            "train_mr": {"position"},
            "node_project": {"relationship_status"},
            "ac_service": {"relationship_status"},
        }[self.relationship_type]
        if set(self.values) - allowed:
            raise ValueError("关系属性包含未支持的字段")
        if any(not isinstance(v, str) or len(v) > 300 for v in self.values.values()):
            raise ValueError("关系属性必须是 300 字以内的文本")
        if self.target_uids and (
            self.relationship_type != "ac_service" or self.action != "create"
        ):
            raise ValueError("只有 AC 服务站点创建支持批量目标")
        return self


class EngineeringProjectRequest(ApiModel):
    site_id: str = ""
    project_id: str = ""
    name: str = Field(min_length=1, max_length=200)
    stage: str = Field(default="", max_length=100)
    reason: str = Field(default="", max_length=1000)
    base_revision: str
    idempotency_key: str = Field(min_length=1, max_length=128)
    explicit_confirmation: bool = False


class RelationshipRecord(ApiModel):
    relationship_type: str
    relationship_id: str
    source_uid: str
    target_uid: str
    source_name: str = ""
    target_name: str = ""
    status: Literal["active", "terminated"]
    values: dict[str, Any] = Field(default_factory=dict)
    effective_from: str = ""
    effective_to: str = ""
    created_at: str = ""
    updated_at: str = ""
    actor: str = ""
    reason: str = ""
    revision: str = ""


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
    preview: bool = False
    changes: list[dict[str, Any]] = Field(default_factory=list)
