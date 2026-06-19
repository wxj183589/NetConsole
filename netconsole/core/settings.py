from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from netconsole.core.paths import PathResolver


DEFAULT_SETTINGS = {
    "theme": "dark",
    "last_export_path": "",
    "file_transfer_max_concurrency": 1,
}
VALID_THEMES = {"light", "dark"}


@dataclass
class SettingsStore:
    paths: PathResolver
    values: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.values = {**DEFAULT_SETTINGS, **self._read()}
        if self.theme not in VALID_THEMES:
            self.values["theme"] = DEFAULT_SETTINGS["theme"]

    @property
    def path(self) -> Path:
        return self.paths.settings_path

    @property
    def theme(self) -> str:
        return str(self.values.get("theme") or DEFAULT_SETTINGS["theme"])

    def set_theme(self, theme: str) -> None:
        if theme not in VALID_THEMES:
            raise ValueError(f"unsupported theme: {theme}")
        self.values["theme"] = theme
        self.save()

    @property
    def last_export_path(self) -> str:
        return str(self.values.get("last_export_path") or "")

    @property
    def file_transfer_max_concurrency(self) -> int:
        try:
            return max(1, int(self.values.get("file_transfer_max_concurrency") or 1))
        except (TypeError, ValueError):
            return 1

    def set_last_export_path(self, path: str | Path) -> None:
        self.values["last_export_path"] = str(path)
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.values, ensure_ascii=False, indent=2), encoding="utf-8")

    def _read(self) -> dict[str, object]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}
