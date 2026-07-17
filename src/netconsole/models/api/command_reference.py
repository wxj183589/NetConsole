from __future__ import annotations

from pydantic import Field

from netconsole.models.api.common import ApiModel


class CommandReferenceDTO(ApiModel):
    id: str
    module: str
    device_scope: str
    vendor: str
    protocol: str
    category: str
    command_template: str
    parameters: list[dict[str, str]] = Field(default_factory=list)
    pre_commands: list[str] = Field(default_factory=list)
    purpose: str
    output_log: str
    parser: str
    consumer: str
    risk_level: str
    interactive_input: bool
    is_cli: bool
    read_only: bool | None
    modifies_device_config: bool
    requires_interactive_confirmation: bool
    source_locations: list[str] = Field(default_factory=list)
    zte_adaptation_status: str
    comware_command: str
    zte_command: str
    parser_status: str
    notes: str


class CommandReferenceFiltersDTO(ApiModel):
    modules: list[str]
    device_scopes: list[str]
    vendors: list[str]
    protocols: list[str]
    categories: list[str]
    risk_levels: list[str]


class CommandReferenceSummaryDTO(ApiModel):
    total: int
    shown: int
    switch_count: int
    non_cli_count: int


class CommandReferencePageDTO(ApiModel):
    items: list[CommandReferenceDTO]
    filters: CommandReferenceFiltersDTO
    summary: CommandReferenceSummaryDTO


class CommandReferenceExportRequestDTO(ApiModel):
    selected_ids: list[str] = Field(default_factory=list, max_length=500)


__all__ = [
    "CommandReferenceDTO",
    "CommandReferenceExportRequestDTO",
    "CommandReferenceFiltersDTO",
    "CommandReferencePageDTO",
    "CommandReferenceSummaryDTO",
]
