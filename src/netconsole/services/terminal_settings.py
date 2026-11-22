from __future__ import annotations

import json
import os
import re
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal

from netconsole.core.paths import PathResolver
from netconsole.models.device import Device


RuleKind = Literal["highlight", "dangerous"]

_RESOURCE_ROOT = Path(__file__).resolve().parents[1] / "resources" / "terminal_rules"
_RESOURCE_FILES: dict[RuleKind, str] = {
    "highlight": "highlight_rules.json",
    "dangerous": "dangerous_command_rules.json",
}
_DEFAULT_SETTINGS: dict[str, Any] = {
    "schema_version": 1,
    "font_family": "Consolas",
    "font_size": 14,
    "foreground": "#d7dae0",
    "background": "#101318",
    "cursor_color": "#f2c94c",
    "encoding": "utf-8",
    "automatic_recording": True,
    "automatic_log_retention_days": 90,
    "automatic_log_max_bytes": 2 * 1024 * 1024 * 1024,
    "manual_log_recent_directory": "",
    "dangerous_command_warning": True,
}
_ENCODINGS = {"utf-8", "gbk", "ansi", "big5", "gb2312", "gb18030"}
_DEVICE_TYPE_SCOPE = {
    "AC": "无线",
    "CLOUD-AP": "无线",
    "FAT-AP": "无线",
    "SW": "交换机",
    "FW": "安全",
    "ROUTE": "路由器",
    "MR": "路由器",
}


class TerminalSettingsError(ValueError):
    pass


class TerminalSettingsService:
    def __init__(self, paths: PathResolver) -> None:
        self.paths = paths
        self.root = paths.config_dir / "terminal"
        self.settings_path = self.root / "console-settings.json"
        self._rule_paths: dict[RuleKind, Path] = {
            kind: self.root / filename for kind, filename in _RESOURCE_FILES.items()
        }
        self._lock = threading.RLock()

    def settings(self) -> dict[str, Any]:
        with self._lock:
            loaded = self._read_json(self.settings_path, {})
            result = {**_DEFAULT_SETTINGS, **loaded}
            return self._validate_settings(result)

    def update_settings(self, values: dict[str, Any]) -> dict[str, Any]:
        allowed = set(_DEFAULT_SETTINGS)
        unknown = set(values) - allowed
        if unknown:
            raise TerminalSettingsError(f"未知终端设置: {', '.join(sorted(unknown))}")
        with self._lock:
            updated = self._validate_settings({**self.settings(), **values})
            self._write_json(self.settings_path, updated)
            return updated

    def rule_document(self, kind: RuleKind) -> dict[str, Any]:
        path = self._rule_path(kind)
        with self._lock:
            if path.is_file():
                value = self._read_json(path, {})
            else:
                value = self._read_json(_RESOURCE_ROOT / _RESOURCE_FILES[kind], {})
            return self._validate_rule_document(kind, value)

    def replace_rules(self, kind: RuleKind, rules: list[dict[str, Any]]) -> dict[str, Any]:
        with self._lock:
            current = self.rule_document(kind)
            payload = {
                **{key: value for key, value in current.items() if key != "rules"},
                "actual_rule_count": len(rules),
                "rules": deepcopy(rules),
            }
            validated = self._validate_rule_document(kind, payload)
            self._write_json(self._rule_path(kind), validated)
            return validated

    def match_dangerous_command(self, command: str, device: Device) -> list[dict[str, Any]]:
        text = str(command or "").strip()
        if not text:
            return []
        device_scope = _DEVICE_TYPE_SCOPE.get(str(device.device_type or "").strip().upper(), "")
        vendor = str(device.device_vendor or "").strip().casefold()
        matches: list[dict[str, Any]] = []
        for rule in self.rule_document("dangerous")["rules"]:
            if not rule["enabled"]:
                continue
            if rule["device_type"] not in {"", "通用", device_scope}:
                continue
            rule_vendor = str(rule["vendor"] or "通用").strip().casefold()
            if rule_vendor not in {"", "通用", vendor} and rule_vendor not in vendor:
                continue
            pattern = str(rule["pattern"])
            if rule["match_type"] == "REGEX":
                matched = re.search(pattern, text, flags=re.IGNORECASE) is not None
            else:
                matched = pattern.casefold() in text.casefold()
            if matched:
                matches.append(deepcopy(rule))
        return matches

    def _validate_rule_document(self, kind: RuleKind, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict) or not isinstance(value.get("rules"), list):
            raise TerminalSettingsError("终端规则文件格式无效")
        rules: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for index, raw in enumerate(value["rules"], start=1):
            if not isinstance(raw, dict):
                raise TerminalSettingsError(f"第 {index} 条终端规则格式无效")
            rule = self._validate_rule(kind, raw, index)
            if rule["id"] in seen_ids:
                raise TerminalSettingsError(f"终端规则 ID 重复: {rule['id']}")
            seen_ids.add(rule["id"])
            rules.append(rule)
        result = deepcopy(value)
        result["schema_version"] = 1
        result["actual_rule_count"] = len(rules)
        result["rules"] = rules
        return result

    @staticmethod
    def _validate_rule(kind: RuleKind, raw: dict[str, Any], index: int) -> dict[str, Any]:
        pattern = str(raw.get("pattern") or "").strip()
        if not pattern:
            raise TerminalSettingsError(f"第 {index} 条终端规则缺少匹配内容")
        match_type = str(raw.get("match_type") or "TEXT").strip().upper()
        if match_type not in {"TEXT", "REGEX"}:
            raise TerminalSettingsError(f"第 {index} 条终端规则匹配类型无效")
        if match_type == "REGEX":
            try:
                re.compile(pattern)
            except re.error as exc:
                raise TerminalSettingsError(f"第 {index} 条正则无效: {exc}") from exc
        prefix = "highlight" if kind == "highlight" else "danger"
        rule: dict[str, Any] = {
            "id": str(raw.get("id") or f"{prefix}-{index:03d}"),
            "pattern": pattern,
            "match_type": match_type,
            "enabled": bool(raw.get("enabled", True)),
            "source_row": int(raw.get("source_row") or 0),
        }
        if kind == "highlight":
            color = str(raw.get("color") or "#ffffff").strip()
            if re.fullmatch(r"#[0-9a-fA-F]{6}", color) is None:
                raise TerminalSettingsError(f"第 {index} 条高亮规则颜色无效")
            rule["color"] = color.lower()
        else:
            rule["device_type"] = str(raw.get("device_type") or "通用").strip()
            rule["vendor"] = str(raw.get("vendor") or "通用").strip()
        return rule

    @staticmethod
    def _validate_settings(value: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(value)
        result["font_family"] = str(result.get("font_family") or "Consolas").strip()[:128]
        result["font_size"] = max(8, min(int(result.get("font_size") or 14), 32))
        for key in ("foreground", "background", "cursor_color"):
            color = str(result.get(key) or _DEFAULT_SETTINGS[key]).strip()
            if re.fullmatch(r"#[0-9a-fA-F]{6}", color) is None:
                raise TerminalSettingsError(f"终端颜色设置无效: {key}")
            result[key] = color.lower()
        encoding = str(result.get("encoding") or "utf-8").strip().casefold()
        if encoding not in _ENCODINGS:
            raise TerminalSettingsError("终端编码设置无效")
        result["encoding"] = encoding
        result["automatic_recording"] = bool(result.get("automatic_recording", True))
        result["dangerous_command_warning"] = bool(
            result.get("dangerous_command_warning", True)
        )
        result["automatic_log_retention_days"] = max(
            1, min(int(result.get("automatic_log_retention_days") or 90), 3650)
        )
        result["automatic_log_max_bytes"] = max(
            64 * 1024 * 1024,
            min(int(result.get("automatic_log_max_bytes") or 0), 100 * 1024 * 1024 * 1024),
        )
        result["manual_log_recent_directory"] = str(
            result.get("manual_log_recent_directory") or ""
        )
        result["schema_version"] = 1
        return result

    def _rule_path(self, kind: RuleKind) -> Path:
        if kind not in self._rule_paths:
            raise TerminalSettingsError("未知终端规则类型")
        return self._rule_paths[kind]

    @staticmethod
    def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
        if not path.is_file():
            return deepcopy(default)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise TerminalSettingsError(f"无法读取终端配置: {path.name}") from exc
        if not isinstance(value, dict):
            raise TerminalSettingsError(f"终端配置格式无效: {path.name}")
        return value

    def _write_json(self, path: Path, value: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)


__all__ = ["RuleKind", "TerminalSettingsError", "TerminalSettingsService"]
