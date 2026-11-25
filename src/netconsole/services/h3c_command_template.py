"""Bounded preview of Jinja2 templates for H3C CLI commands."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from jinja2 import StrictUndefined, TemplateError, nodes
from jinja2.sandbox import ImmutableSandboxedEnvironment
from pydantic import BaseModel, ConfigDict, Field


_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}")
_INTERFACE = re.compile(r"[A-Za-z][A-Za-z0-9/-]{0,63}(?:-[A-Za-z0-9/-]+)*(?: [0-9][A-Za-z0-9/.:_-]{0,63})?")
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")
_READ_ONLY = re.compile(
    r"display (?:version|device(?: manuinfo)?|cpu-usage|memory(?: summary)?|interface(?: brief)?"
    r"|lldp neighbor-information(?: list| verbose)?|transceiver(?: diagnosis| interface)?)"
    r"|display (?:transceiver(?: diagnosis)?|lldp neighbor-information) interface "
    r"[A-Za-z][A-Za-z0-9/-]{0,63}(?:-[A-Za-z0-9/-]+)*(?: [0-9][A-Za-z0-9/.:_-]{0,63})?",
    re.IGNORECASE,
)
_NODES = (
    nodes.Template, nodes.Output, nodes.TemplateData, nodes.Name, nodes.Const,
    nodes.Getattr, nodes.Getitem, nodes.For, nodes.If, nodes.Filter, nodes.Compare,
    nodes.Operand, nodes.And, nodes.Or, nodes.Not, nodes.List, nodes.Tuple,
)


class TemplatePreviewError(ValueError):
    pass


class CommandParameter(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    type: Literal["string", "interface", "integer", "boolean", "list", "object"]
    required: bool = True
    default: object = None
    description: str = Field(default="", max_length=400)


class CommandTemplatePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Annotated[str, Field(min_length=1, max_length=16_384)]
    schema_fields: dict[str, CommandParameter] = Field(default_factory=dict, max_length=64)
    values: dict[str, object] = Field(default_factory=dict, max_length=64)


class CommandTemplatePreview(BaseModel):
    commands: list[str]
    risk: Literal["read_only", "configuration_change"]


class _CliSandbox(ImmutableSandboxedEnvironment):
    def is_safe_attribute(self, obj, attr, value):
        return False

    def is_safe_callable(self, obj):
        return False


def preview_command_template(request: CommandTemplatePreviewRequest) -> CommandTemplatePreview:
    values = _validated_values(request)
    try:
        chunks = []
        total = 0
        for chunk in _compiled_template(request.source).generate(values):
            total += len(chunk)
            if total > 32_768:
                raise TemplatePreviewError("渲染结果超出长度上限")
            chunks.append(chunk)
    except (TemplateError, RecursionError, TypeError, ValueError) as exc:
        if isinstance(exc, TemplatePreviewError):
            raise
        raise TemplatePreviewError(f"模板渲染失败：{exc}") from exc
    rendered = "".join(chunks).replace("\r\n", "\n")
    commands = [line.strip() for line in rendered.split("\n") if line.strip()]
    if not commands or len(commands) > 512:
        raise TemplatePreviewError("模板必须生成 1 至 512 条命令")
    if any(len(line) > 512 or _CONTROL.search(line) for line in commands):
        raise TemplatePreviewError("命令含控制字符或超过长度上限")
    return CommandTemplatePreview(
        commands=commands,
        risk="read_only" if all(is_read_only_h3c_command(line) for line in commands) else "configuration_change",
    )


def validate_command_template(source: str, schema_fields: dict[str, CommandParameter]) -> None:
    _compiled_template(source)
    for name, parameter in schema_fields.items():
        if not _IDENTIFIER.fullmatch(name):
            raise TemplatePreviewError("参数名必须使用字母、数字或下划线，以字母开头")
        if parameter.default is not None:
            _validated_values(CommandTemplatePreviewRequest(source=source, schema_fields={name: parameter}))


def validate_read_only_command_template(source: str) -> None:
    """Check every control-flow branch with dynamic output kept in argument positions.

    Dynamic values never establish a command's verb. Actual rendered commands
    still pass the execution whitelist before any connection is opened.
    """
    environment = _CliSandbox(undefined=StrictUndefined, autoescape=False)
    tree = environment.parse(source)
    _validate_template_node(tree)

    def variants(statements) -> list[str]:
        outputs = [""]
        for statement in statements:
            if isinstance(statement, nodes.Output):
                alternatives = ["".join(
                    item.data if isinstance(item, nodes.TemplateData) else "GigabitEthernet1/0/1"
                    for item in statement.nodes
                )]
            elif isinstance(statement, nodes.If):
                alternatives = variants(statement.body) + variants(statement.else_)
                for branch in statement.elif_:
                    alternatives.extend(variants(branch.body))
            elif isinstance(statement, nodes.For):
                # Two iterations expose a missing line separator between commands.
                body = variants(statement.body)
                otherwise = variants(statement.else_)
                if len(otherwise) + len(body) + len(body) ** 2 > 512:
                    raise TemplatePreviewError("模板分支组合超出只读检查上限")
                alternatives = otherwise + body + [left + right for left in body for right in body]
            else:
                raise TemplatePreviewError("只读模板存在无法静态检查的语法")
            if len(outputs) * len(alternatives) > 512:
                raise TemplatePreviewError("模板分支组合超出只读检查上限")
            outputs = [prefix + suffix for prefix in outputs for suffix in alternatives]
            if any(len(output) > 32768 for output in outputs):
                raise TemplatePreviewError("模板静态检查结果超出长度上限")
        return outputs

    has_command = False
    for output in variants(tree.body):
        for command in output.splitlines():
            if not command.strip():
                continue
            has_command = True
            if not is_read_only_h3c_command(command.strip()):
                raise TemplatePreviewError("仅可保存只读查询模板，命令名称必须固定，变量只能用于查询参数")
    if not has_command:
        raise TemplatePreviewError("只读模板必须包含查询命令")


def _compiled_template(source: str):
    environment = _CliSandbox(undefined=StrictUndefined, autoescape=False)
    environment.globals.clear()
    environment.tests.clear()
    environment.filters = {name: environment.filters[name] for name in ("default", "join", "lower", "upper", "trim")}
    try:
        tree = environment.parse(source)
        _validate_template_node(tree)
        return environment.from_string(tree)
    except (TemplateError, RecursionError) as exc:
        raise TemplatePreviewError(f"模板语法错误：{exc}") from exc


def is_read_only_h3c_command(command: str) -> bool:
    return _READ_ONLY.fullmatch(command) is not None


def _validated_values(request: CommandTemplatePreviewRequest) -> dict[str, object]:
    if request.values.keys() - request.schema_fields.keys():
        raise TemplatePreviewError("参数值存在未声明字段")
    values: dict[str, object] = {}
    valid_types = {"string": str, "interface": str, "integer": int, "boolean": bool, "list": list, "object": dict}
    for name, field in request.schema_fields.items():
        if not _IDENTIFIER.fullmatch(name):
            raise TemplatePreviewError("参数名必须使用字母、数字或下划线，以字母开头")
        value = request.values.get(name, field.default)
        if value is None and not field.required:
            continue
        if type(value) is not valid_types[field.type]:
            raise TemplatePreviewError(f"参数 {name} 缺失或类型不正确")
        if field.type == "interface" and not _INTERFACE.fullmatch(value):
            raise TemplatePreviewError(f"参数 {name} 的接口名称无效")
        _validate_value(value)
        values[name] = value
    return values


def _validate_value(value: object, depth: int = 0) -> None:
    if depth > 5:
        raise TemplatePreviewError("参数嵌套过深")
    if isinstance(value, str):
        if len(value) > 512 or _CONTROL.search(value):
            raise TemplatePreviewError("文本参数含换行或控制字符，或超过长度上限")
    elif type(value) is int:
        if abs(value) > 2**53 - 1:
            raise TemplatePreviewError("整数参数超出范围")
    elif isinstance(value, dict):
        if len(value) > 64 or any(not isinstance(k, str) or not _IDENTIFIER.fullmatch(k) for k in value):
            raise TemplatePreviewError("对象参数超出字段限制或存在无效字段名")
        for item in value.values():
            _validate_value(item, depth + 1)
    elif isinstance(value, list):
        if len(value) > 64:
            raise TemplatePreviewError("列表参数至多包含 64 项")
        for item in value:
            _validate_value(item, depth + 1)
    elif type(value) is not bool:
        raise TemplatePreviewError("参数包含不支持的值类型")


def _validate_template_node(node: nodes.Node, *, depth: int = 0, loops: int = 0) -> None:
    if depth > 24 or not isinstance(node, _NODES):
        raise TemplatePreviewError(f"模板语法不受支持：{type(node).__name__}")
    if isinstance(node, nodes.For):
        loops += 1
        if node.recursive or loops > 2:
            raise TemplatePreviewError("模板循环层级超出限制")
    if isinstance(node, nodes.Filter):
        if node.name not in {"default", "join", "lower", "upper", "trim"} or node.kwargs or node.dyn_args or node.dyn_kwargs:
            raise TemplatePreviewError("过滤器或过滤器参数不受支持")
        if node.name == "join" and (len(node.args) > 1 or any(not isinstance(arg, nodes.Const) for arg in node.args)):
            raise TemplatePreviewError("join 只接受固定分隔符")
    for child in node.iter_child_nodes():
        _validate_template_node(child, depth=depth + 1, loops=loops)
