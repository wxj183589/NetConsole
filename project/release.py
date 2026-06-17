from __future__ import annotations

import argparse
import re
import subprocess
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
VERSION_FILE = ROOT / "netconsole" / "core" / "version.py"
VERSION_INFO_FILE = ROOT / "project" / "version_info.txt"
INTERNAL_REMOTE = "https://nas.love-ok.com:3021/mengyou/NetConsole.git"
GITHUB_REMOTE = "https://github.com/wxj183589/NetConsole.git"
REMOTE_URLS = {
    "origin": INTERNAL_REMOTE,
    "github": GITHUB_REMOTE,
}


def run_git(args: list[str], check: bool = True) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, check=check, text=True, capture_output=True)
    return result.stdout.strip()


def next_patch_version(tags: list[str]) -> str:
    max_patch = -1
    for tag in tags:
        match = re.fullmatch(r"v1\.0\.(\d+)", tag.strip())
        if match:
            max_patch = max(max_patch, int(match.group(1)))
    return f"v1.0.{max_patch + 1 if max_patch >= 0 else 0}"


def get_next_version() -> str:
    output = run_git(["tag", "--list", "v1.0.*"])
    return next_patch_version(output.splitlines())


def render_version_py(version: str, build_time: str, git_commit: str) -> str:
    return f'''from __future__ import annotations


APP_VERSION = "{version}"
BUILD_TIME = "{build_time}"
GIT_COMMIT = "{git_commit}"
APP_AUTHOR = "梦游"
REPOSITORY_URLS = (
    "{INTERNAL_REMOTE}",
    "{GITHUB_REMOTE}",
)
'''


def render_version_info(version: str) -> str:
    numbers = _version_numbers(version)
    number_text = ", ".join(str(item) for item in numbers)
    dotted = ".".join(str(item) for item in numbers)
    return f'''# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({number_text}),
    prodvers=({number_text}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
          StringStruct('CompanyName', '梦游'),
          StringStruct('FileDescription', 'NetConsole Windows Desktop Network Device Management Tool'),
          StringStruct('FileVersion', '{dotted}'),
          StringStruct('InternalName', 'NetConsole'),
          StringStruct('OriginalFilename', 'NetConsole.exe'),
          StringStruct('ProductName', 'NetConsole'),
          StringStruct('ProductVersion', '{dotted}')
        ]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
'''


def write_release_files(version: str, build_time: str, git_commit: str) -> None:
    VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)  # ⭐关键修复
    VERSION_FILE.write_text(
        render_version_py(version, build_time, git_commit),
        encoding="utf-8"
    )

    VERSION_INFO_FILE.parent.mkdir(parents=True, exist_ok=True)
    VERSION_INFO_FILE.write_text(render_version_info(version), encoding="utf-8")


def ensure_remotes(dry_run: bool) -> None:
    existing = _remote_map()
    for name, url in REMOTE_URLS.items():
        if existing.get(name) == url:
            continue
        if dry_run:
            action = "set-url" if name in existing else "add"
            print(f"DRY-RUN git remote {action} {name} {url}")
            continue
        if name in existing:
            run_git(["remote", "set-url", name, url])
        else:
            run_git(["remote", "add", name, url])


def release(version: str | None = None, dry_run: bool = False) -> str:
    selected_version = version or get_next_version()
    build_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    git_commit = run_git(["rev-parse", "--short", "HEAD"])
    if dry_run:
        print(render_version_py(selected_version, build_time, git_commit))
    else:
        write_release_files(selected_version, build_time, git_commit)

    commands = [
        ["git", "add", "."],
        ["git", "commit", "--allow-empty", "-m", "auto release build"],
        ["git", "tag", "-a", selected_version, "-m", f"Release {selected_version}"],
        ["git", "push", "origin", "main"],
        ["git", "push", "github", "main"],
        ["git", "push", "origin", selected_version],
        ["git", "push", "github", selected_version],
    ]
    ensure_remotes(dry_run)
    for command in commands:
        if dry_run:
            print("DRY-RUN " + " ".join(command))
        else:
            subprocess.run(command, cwd=ROOT, check=True)
    return selected_version


def _remote_map() -> dict[str, str]:
    output = run_git(["remote", "-v"], check=False)
    remotes: dict[str, str] = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] not in remotes:
            remotes[parts[0]] = parts[1]
    return remotes


def _version_numbers(version: str) -> tuple[int, int, int, int]:
    match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", version)
    if not match:
        raise ValueError(f"invalid version: {version}")
    return int(match.group(1)), int(match.group(2)), int(match.group(3)), 0


def main() -> int:
    parser = argparse.ArgumentParser(description="NetConsole release automation")
    parser.add_argument("--version", help="release version, e.g. v1.0.0")
    parser.add_argument("--dry-run", action="store_true", help="print actions without changing git")
    args = parser.parse_args()
    version = release(version=args.version, dry_run=args.dry_run)
    print(f"release version: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
