from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from netconsole.core.paths import PathResolver
from netconsole.repositories.command_template_repository import CommandTemplateRepository, TemplateRevisionConflict
from netconsole.services.h3c_command_template import (
    CommandParameter,
    CommandTemplatePreview,
    CommandTemplatePreviewRequest,
    preview_command_template,
    validate_command_template,
    validate_read_only_command_template,
)


class CommandTemplateDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    name: str = Field(min_length=1, max_length=100)
    category: str = Field(default="自定义", min_length=1, max_length=64)
    source: str = Field(min_length=1, max_length=16_384)
    schema_fields: dict[str, CommandParameter] = Field(default_factory=dict, max_length=64)
    vendor: Literal["h3c"] = "h3c"
    platform: Literal["comware"] = "comware"
    device_roles: list[Literal["switch", "wireless_controller", "mobile_router"]] = Field(default_factory=list, max_length=3)
    command_type: Literal["read_only", "configuration_change"] = "read_only"
    enabled: bool = True


class CommandTemplateRevision(CommandTemplateDefinition):
    template_id: str
    version: int
    updated_at: str


class SavedTemplateParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    version: int = Field(ge=1)
    values: dict[str, object] = Field(default_factory=dict, max_length=64)


class SavedTemplateExecution(SavedTemplateParameters):
    preview_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class SavedTemplatePreview(CommandTemplatePreview):
    template_id: str
    version: int
    preview_digest: str


class CommandTemplateLibrary:
    def __init__(self, paths: PathResolver, site: str) -> None:
        self.repository = CommandTemplateRepository(paths, site)

    def list(self) -> list[CommandTemplateRevision]:
        return sorted(
            (CommandTemplateRevision.model_validate(record) for record in self.repository.list_latest()),
            key=lambda record: (record.category, record.name, record.template_id),
        )

    def versions(self, template_id: str) -> list[CommandTemplateRevision]:
        return [CommandTemplateRevision.model_validate(record) for record in self.repository.list_versions(template_id)]

    def save(self, definition: CommandTemplateDefinition, *, template_id: str | None = None, expected_version: int | None = None, offline_configuration: bool = False) -> CommandTemplateRevision:
        if not definition.name.strip() or not definition.category.strip():
            raise ValueError("模板名称和分类不能为空")
        validate_command_template(definition.source, definition.schema_fields)
        if definition.command_type != "read_only" and not offline_configuration:
            raise ValueError("仅可保存只读查询模板")
        if definition.command_type == "read_only":
            validate_read_only_command_template(definition.source)
        record = self.repository.save(
            definition.model_dump(mode="json"), template_id=template_id, expected_version=expected_version,
        )
        return CommandTemplateRevision.model_validate(record)

    def preview(self, request: SavedTemplateParameters) -> tuple[CommandTemplateRevision, SavedTemplatePreview]:
        record = self.versions(request.template_id)[0]
        if record.version != request.version or not record.enabled:
            raise TemplateRevisionConflict("模板已停用或已有新版本，请重新选择")
        result = preview_command_template(CommandTemplatePreviewRequest(
            source=record.source, schema_fields=record.schema_fields, values=request.values,
        ))
        if result.risk != record.command_type:
            raise ValueError("模板渲染结果含白名单外命令")
        digest = hashlib.sha256(json.dumps(
            [record.template_id, record.version, request.values, result.commands],
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()
        return record, SavedTemplatePreview(
            template_id=record.template_id, version=record.version, preview_digest=digest,
            commands=result.commands, risk=result.risk,
        )
