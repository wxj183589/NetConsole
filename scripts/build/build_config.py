from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
ROOT = PROJECT_DIR.parents[1]


@dataclass(frozen=True)
class BuildConfig:
    app_name: str
    app_version: str
    app_author: str
    root: Path = ROOT
    entry_file: Path = ROOT / "main.py"
    icon_file: Path = ROOT / "resources" / "branding" / "netconsole.ico"
    changelog_file: Path = ROOT / "src" / "netconsole" / "docs" / "changelog.md"
    tools_dir: Path = ROOT / "resources" / "tools"
    release_dir: Path = ROOT / "dist"

    @property
    def ipop_notice(self) -> Path:
        return self.root / "docs" / "release" / "IPOP_v4.1_NOTICE.md"

    @property
    def release_version_dir(self) -> Path:
        return self.release_dir / self.app_version

    def backend_release_dir(self, backend: str) -> Path:
        return self.release_version_dir / backend

    def backend_build_dir(self, backend: str) -> Path:
        return self.release_dir / "_build" / backend

    def zip_path(self, backend: str) -> Path:
        return (
            self.backend_release_dir(backend)
            / f"{self.app_name}_{self.app_version}_{backend}.zip"
        )

    @property
    def required_tool_files(self) -> tuple[Path, ...]:
        return (
            self.tools_dir / "windows-x64" / "fping" / "fping.exe",
            self.tools_dir / "windows-x64" / "fping" / "cygwin1.dll",
            self.tools_dir / "windows-x64" / "iperf3" / "iperf3.exe",
            self.tools_dir / "windows-x64" / "iperf3" / "cygwin1.dll",
            self.tools_dir / "windows-x64" / "iperf3" / "cygcrypto-3.dll",
            self.tools_dir / "windows-x64" / "iperf3" / "cygz.dll",
            self.tools_dir / "windows-x64" / "iperf3" / "SOURCE_PROVENANCE.json",
            self.ipop_notice,
        )

    @property
    def renderer_dir(self) -> Path:
        return self.root / "apps" / "desktop_renderer"


def load_config() -> BuildConfig:
    from netconsole.core.version import APP_AUTHOR, APP_NAME, APP_VERSION

    return BuildConfig(
        app_name=APP_NAME,
        app_version=APP_VERSION,
        app_author=APP_AUTHOR,
    )
