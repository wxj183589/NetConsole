from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

from netconsole.core.resources import open_source_notices_path, runtime_base_dir


@dataclass(frozen=True)
class OpenSourceComponent:
    name: str
    version: str
    license: str
    purpose: str
    homepage: str
    note: str = ""


DEPENDENCY_NAME_MAP = {
    "netmiko": "netmiko",
    "openpyxl": "openpyxl",
    "matplotlib": "matplotlib",
    "numpy": "numpy",
    "pyinstaller": "PyInstaller",
    "pandas": "pandas",
    "paramiko": "paramiko",
    "pysnmp": "pysnmp",
    "cryptography": "cryptography",
    "requests": "requests",
}


class OpenSourceNoticeService:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = Path(base_dir or runtime_base_dir()).resolve()

    def list_components(self) -> list[OpenSourceComponent]:
        overrides = self._load_overrides()
        names = self._dependency_names(overrides)
        components: list[OpenSourceComponent] = []
        seen: set[str] = set()
        for name in names:
            normalized = _normalize_name(name)
            if normalized in seen:
                continue
            seen.add(normalized)
            override = overrides.get(normalized, {})
            components.append(self._component_for_name(name, override))
        return sorted(components, key=lambda item: item.name.casefold())

    def export_text(self, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["NetConsole 开源许可说明", ""]
        for component in self.list_components():
            lines.extend(
                [
                    f"组件名称：{component.name}",
                    f"版本：{component.version or '-'}",
                    f"许可证：{component.license or '-'}",
                    f"用途：{component.purpose or '-'}",
                    f"项目地址：{component.homepage or '-'}",
                    f"备注：{component.note or '-'}",
                    "",
                ]
            )
        output_path.write_text("\n".join(lines), encoding="utf-8")
        return output_path

    def _component_for_name(self, name: str, override: dict[str, str]) -> OpenSourceComponent:
        dist = self._distribution(name)
        version = ""
        license_text = ""
        homepage = ""
        note = ""
        display_name = override.get("name") or DEPENDENCY_NAME_MAP.get(_normalize_name(name), name)
        if dist is not None:
            meta = dist.metadata
            version = dist.version or ""
            display_name = override.get("name") or meta.get("Name") or display_name
            license_text = _metadata_license(meta)
            homepage = meta.get("Home-page") or _project_url(meta) or ""
        return OpenSourceComponent(
            name=display_name,
            version=version or override.get("version", ""),
            license=override.get("license") or license_text or "未在包元数据中声明",
            purpose=override.get("purpose", ""),
            homepage=override.get("homepage") or homepage,
            note=override.get("note") or note,
        )

    def _distribution(self, name: str):
        candidates = {name, DEPENDENCY_NAME_MAP.get(_normalize_name(name), name), _normalize_name(name)}
        for candidate in candidates:
            try:
                return metadata.distribution(candidate)
            except metadata.PackageNotFoundError:
                continue
        return None

    def _dependency_names(self, overrides: dict[str, dict[str, str]]) -> list[str]:
        names: list[str] = ["Python"]
        requirements = self.base_dir / "requirements.txt"
        if requirements.exists():
            for line in requirements.read_text(encoding="utf-8").splitlines():
                parsed = _requirement_name(line)
                if parsed:
                    names.append(parsed)
        names.extend(override.get("name") or key for key, override in overrides.items())
        return names

    def _load_overrides(self) -> dict[str, dict[str, str]]:
        path = open_source_notices_path(self.base_dir)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        result: dict[str, dict[str, str]] = {}
        if not isinstance(raw, list):
            return result
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            result[_normalize_name(name)] = {str(key): str(value) for key, value in item.items() if value is not None}
        return result


def _normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", str(name).strip().lower())


def _requirement_name(line: str) -> str:
    text = line.split("#", 1)[0].strip()
    if not text or text.startswith("-"):
        return ""
    return re.split(r"[<>=!~;\[]", text, maxsplit=1)[0].strip()


def _metadata_license(meta) -> str:
    license_text = str(meta.get("License") or "").strip()
    if license_text:
        return license_text
    classifiers = meta.get_all("Classifier") or []
    license_classifiers = [value.rsplit("::", 1)[-1].strip() for value in classifiers if "License ::" in value]
    return ", ".join(license_classifiers)


def _project_url(meta) -> str:
    for value in meta.get_all("Project-URL") or []:
        parts = str(value).split(",", 1)
        if len(parts) == 2 and parts[0].strip().casefold() in {"homepage", "source", "repository", "documentation"}:
            return parts[1].strip()
    return ""
