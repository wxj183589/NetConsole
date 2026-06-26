from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
ROOT = PROJECT_DIR.parent


@dataclass(frozen=True)
class BuildConfig:
    app_name: str
    app_version: str
    app_author: str
    root: Path = ROOT
    entry_file: Path = ROOT / "main.py"
    icon_file: Path = ROOT / "netconsole" / "ui" / "icons" / "love.ico"
    changelog_file: Path = ROOT / "netconsole" / "docs" / "changelog.md"
    tools_dir: Path = ROOT / "tools"
    release_dir: Path = ROOT / "release"

    @property
    def release_version_dir(self) -> Path:
        return self.release_dir / self.app_version

    def backend_release_dir(self, backend: str) -> Path:
        return self.release_version_dir / backend

    def backend_build_dir(self, backend: str) -> Path:
        return self.release_dir / "_build" / backend

    def zip_path(self, backend: str) -> Path:
        return self.backend_release_dir(backend) / f"{self.app_name}_{self.app_version}_{backend}.zip"

    @property
    def required_tool_files(self) -> tuple[Path, ...]:
        return (
            self.tools_dir / "fping_v3" / "Fping_v3.exe",
            self.tools_dir / "iperf" / "iperf3.exe",
        )


def load_config() -> BuildConfig:
    from netconsole.core.version import APP_AUTHOR, APP_NAME, APP_VERSION

    return BuildConfig(
        app_name=APP_NAME,
        app_version=APP_VERSION,
        app_author=APP_AUTHOR,
    )
