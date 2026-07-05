from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MibSource:
    id: int | None = None
    vendor: str = ""
    source_name: str = "用户手动导入"
    source_type: str = "manual"
    source_url: str = ""
    product_line: str = ""
    product_name: str = ""
    software_version: str = ""
    description: str = ""


@dataclass(frozen=True)
class MibFileRecord:
    id: int | None = None
    source_id: int | None = None
    file_name: str = ""
    raw_path: str = ""
    compiled_path: str = ""
    module_name: str = ""
    file_hash: str = ""
    file_size: int = 0
    compile_status: str = "pending"
    missing_dependencies_json: str = "[]"
    error_message: str = ""


@dataclass(frozen=True)
class MibModuleRecord:
    id: int | None = None
    file_id: int | None = None
    module_name: str = ""
    module_version: str = ""
    vendor: str = ""
    status: str = "pending"
    compiled_path: str = ""
    object_count: int = 0
    table_count: int = 0
    trap_count: int = 0
    notification_count: int = 0
    error_message: str = ""


@dataclass(frozen=True)
class MibObjectRecord:
    id: int | None = None
    module_id: int | None = None
    name: str = ""
    oid: str = ""
    parent_oid: str = ""
    syntax: str = ""
    access: str = ""
    status: str = ""
    description: str = ""
    is_scalar: int = 0
    is_table: int = 0
    is_table_entry: int = 0
    is_column: int = 0
    is_trap: int = 0
    is_notification: int = 0
    table_name: str = ""
    entry_name: str = ""
    index_def: str = ""
    enum_map_json: str = "{}"


@dataclass(frozen=True)
class DictionarySetRecord:
    id: int | None = None
    source_package_id: int | None = None
    name: str = ""
    vendor: str = ""
    device_type: str = ""
    model_pattern: str = ""
    os_pattern: str = ""
    sysobjectid_prefix: str = ""
    description: str = ""
    is_builtin: int = 0
    enabled_by_default: int = 0


@dataclass(frozen=True)
class MibCompileResult:
    module_name: str
    status: str
    objects: list[MibObjectRecord] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    missing_dependencies: list[str] = field(default_factory=list)
    error_message: str = ""
