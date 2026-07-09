from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from netconsole.core.paths import PathResolver


REFERENCE_FILENAME = "command_reference.json"


@dataclass(frozen=True)
class CommandReference:
    id: str
    module: str
    device_scope: str
    vendor: str
    protocol: str
    category: str
    command_template: str
    parameters: list[dict[str, str]] = field(default_factory=list)
    pre_commands: list[str] = field(default_factory=list)
    purpose: str = ""
    output_log: str = ""
    parser: str = ""
    consumer: str = ""
    risk_level: str = "unknown"
    interactive_input: bool = False
    is_cli: bool = True
    source_locations: list[str] = field(default_factory=list)
    zte_adaptation_status: str = "not_applicable"
    comware_command: str = ""
    zte_command: str = ""
    parser_status: str = ""
    notes: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "CommandReference":
        data = {field_name: payload.get(field_name) for field_name in cls.__dataclass_fields__}
        return cls(
            id=str(data.get("id") or ""),
            module=str(data.get("module") or ""),
            device_scope=str(data.get("device_scope") or ""),
            vendor=str(data.get("vendor") or ""),
            protocol=str(data.get("protocol") or ""),
            category=str(data.get("category") or ""),
            command_template=str(data.get("command_template") or ""),
            parameters=_list_of_dicts(data.get("parameters")),
            pre_commands=_list_of_strings(data.get("pre_commands")),
            purpose=str(data.get("purpose") or ""),
            output_log=str(data.get("output_log") or ""),
            parser=str(data.get("parser") or ""),
            consumer=str(data.get("consumer") or ""),
            risk_level=str(data.get("risk_level") or "unknown"),
            interactive_input=bool(data.get("interactive_input")),
            is_cli=bool(data.get("is_cli", True)),
            source_locations=_list_of_strings(data.get("source_locations")),
            zte_adaptation_status=str(data.get("zte_adaptation_status") or "not_applicable"),
            comware_command=str(data.get("comware_command") or ""),
            zte_command=str(data.get("zte_command") or ""),
            parser_status=str(data.get("parser_status") or ""),
            notes=str(data.get("notes") or ""),
        )

    def to_markdown_row(self) -> list[str]:
        return [
            self.category,
            self.command_template,
            self.purpose,
            self.module,
            self.device_scope,
            self.vendor,
            ", ".join(self.pre_commands),
            self.risk_level,
            self.notes,
        ]


def command_reference_path(paths: PathResolver | None = None) -> Path:
    resolver = paths or PathResolver()
    return resolver.app_root / "resources" / REFERENCE_FILENAME


def load_command_references(paths: PathResolver | None = None) -> list[CommandReference]:
    path = command_reference_path(paths)
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = payload.get("items", payload) if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise ValueError("command_reference.json must contain an items list")
    references = [CommandReference.from_dict(item) for item in items if isinstance(item, dict)]
    return sorted(references, key=lambda item: (item.module, item.category, item.command_template, item.id))


def unique_values(items: Iterable[CommandReference], field_name: str) -> list[str]:
    values = sorted({str(getattr(item, field_name, "") or "") for item in items if str(getattr(item, field_name, "") or "").strip()})
    return values


def export_command_references_markdown(items: Iterable[CommandReference]) -> str:
    rows = list(items)
    lines = [
        "# 软件使用命令清单导出",
        "",
        "| 类别 | 命令/接口 | 当前用途 | 模块 | 设备类型 | 厂商 | 前置条件 | 风险级别 | 备注 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in rows:
        lines.append("| " + " | ".join(_escape_markdown(cell) for cell in item.to_markdown_row()) + " |")
    lines.extend(
        [
            "",
            "## 非 CLI 接口说明",
            "",
        ]
    )
    non_cli = [item for item in rows if not item.is_cli]
    if not non_cli:
        lines.append("当前导出范围内没有非 CLI 接口。")
    else:
        for item in non_cli:
            lines.append(f"- `{_escape_markdown(item.command_template)}`：{_escape_markdown(item.purpose)}")
    return "\n".join(lines) + "\n"


def _list_of_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _list_of_dicts(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, str]] = []
    for item in value:
        if isinstance(item, dict):
            rows.append({str(key): str(val) for key, val in item.items()})
    return rows


def _escape_markdown(value: object) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", "<br>")
