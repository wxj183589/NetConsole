from __future__ import annotations

import argparse
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
ROOT = PROJECT_DIR.parent
VERSION_FILE = ROOT / "netconsole" / "core" / "version.py"
VERSION_INFO_FILE = ROOT / "release" / "_build" / "release" / "version_info.txt"
INTERNAL_REMOTE = "ssh://git@nas.love-ok.com:3022/mengyou/NetConsole.git"
GITHUB_REMOTE = "git@github.com:wxj183589/NetConsole.git"
REMOTE_URLS = {
    "github": GITHUB_REMOTE,
    "nas": INTERNAL_REMOTE,
}
APP_AUTHOR = "梦游"
ONLINE_RELEASE = "ONLINE_RELEASE"
LOCAL_BUILD_ONLY = "LOCAL_BUILD_ONLY"
OFFLINE_RELEASE = "OFFLINE_RELEASE"
COMMIT_FAILED = "COMMIT_FAILED"
RELEASE_STATUS = LOCAL_BUILD_ONLY

GIT_AUTH_NOTE = """
Remote nas is a self-hosted Gitea repository:
ssh://git@nas.love-ok.com:3022/mengyou/NetConsole.git

Authentication requires:
- SSH key

Git push requires authentication:
- SSH key authentication is required
- Release system should not block on auth failure
"""


@dataclass(frozen=True)
class ReleaseResult:
    version: str
    build_success: bool
    commit_success: bool
    tag_success: bool
    push_nas_success: bool
    push_github_success: bool
    push_nas_tag_success: bool
    push_github_tag_success: bool
    final_status: str


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    return env


def run_git(args: list[str], check: bool = True) -> str:
    cmd = ["git", *args]
    try:
        result = subprocess.run(cmd, cwd=ROOT, check=check, text=True, capture_output=True, env=_git_env())
        return result.stdout.strip()
    except Exception as exc:
        print("[WARN] Git command failed:", cmd)
        print("[WARN] Reason:", str(exc))
        return ""


def safe_run(cmd: list[str]) -> bool:
    try:
        subprocess.run(cmd, cwd=ROOT, check=True, env=_git_env())
        return True
    except Exception as exc:
        print("[WARN] Git command failed:", cmd)
        print("[WARN] Reason:", str(exc))
        return False


def check_git_remote(remote: str = "nas") -> bool:
    try:
        subprocess.run(["git", "ls-remote", remote], cwd=ROOT, check=True, env=_git_env(), stdout=subprocess.DEVNULL)
        return True
    except Exception as exc:
        print("[WARN] Git remote check failed: Git remote authentication or network is unavailable")
        print("[WARN] Reason:", str(exc))
        return False


def get_release_version(explicit_version: str | None = None) -> str:
    if explicit_version:
        return explicit_version
    from netconsole.core.version import APP_VERSION

    return APP_VERSION


def render_version_py(version: str, build_time: str, git_commit: str) -> str:
    return f'''from __future__ import annotations


APP_NAME = "NetConsole"
APP_VERSION = "{version}"
APP_VERSION_DISPLAY = APP_VERSION
BUILD_TIME = "{build_time}"
GIT_COMMIT = "{git_commit}"
APP_AUTHOR = "{APP_AUTHOR}"
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
          StringStruct('CompanyName', '{APP_AUTHOR}'),
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
    VERSION_FILE.write_text(render_version_py(version, build_time, git_commit), encoding="utf-8")
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
            safe_run(["git", "remote", "set-url", name, url])
        else:
            safe_run(["git", "remote", "add", name, url])


def release(version: str | None = None, dry_run: bool = False) -> ReleaseResult:
    global RELEASE_STATUS
    selected_version = get_release_version(version)
    build_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    git_commit = run_git(["rev-parse", "--short", "HEAD"]) or "unknown"
    if dry_run:
        print(render_version_py(selected_version, build_time, git_commit))
    else:
        write_release_files(selected_version, build_time, git_commit)

    ensure_remotes(dry_run)
    if dry_run:
        check_remote_success = True
        print("DRY-RUN git ls-remote nas")
    else:
        check_remote_success = check_git_remote("nas")

    commit_success = _run_required_git(["git", "add", "."], dry_run)
    commit_success = _run_required_git(["git", "commit", "--allow-empty", "-m", "自动发布：更新版本、更新日志与构建文件"], dry_run) and commit_success
    tag_success = _run_optional_git(["git", "tag", "-a", selected_version, "-m", f"发布 {selected_version}"], dry_run)

    push_github_success = _run_optional_git(["git", "push", "github", "HEAD"], dry_run)
    push_nas_success = _run_optional_git(["git", "push", "nas", "HEAD"], dry_run)
    push_github_tag_success = _run_optional_git(["git", "push", "github", selected_version], dry_run)
    push_nas_tag_success = _run_optional_git(["git", "push", "nas", selected_version], dry_run)

    push_results = [push_github_success, push_nas_success, push_github_tag_success, push_nas_tag_success]
    if not commit_success:
        RELEASE_STATUS = COMMIT_FAILED
    elif tag_success and all(push_results):
        RELEASE_STATUS = ONLINE_RELEASE
    elif not any(push_results) or not check_remote_success:
        RELEASE_STATUS = OFFLINE_RELEASE
    else:
        RELEASE_STATUS = LOCAL_BUILD_ONLY

    result = ReleaseResult(
        version=selected_version,
        build_success=True,
        commit_success=commit_success,
        tag_success=tag_success,
        push_nas_success=push_nas_success,
        push_github_success=push_github_success,
        push_nas_tag_success=push_nas_tag_success,
        push_github_tag_success=push_github_tag_success,
        final_status=RELEASE_STATUS,
    )
    print_release_summary(result)
    return result


def _run_required_git(cmd: list[str], dry_run: bool) -> bool:
    if dry_run:
        print("DRY-RUN " + " ".join(cmd))
        return True
    return safe_run(cmd)


def _run_optional_git(cmd: list[str], dry_run: bool) -> bool:
    if dry_run:
        print("DRY-RUN " + " ".join(cmd))
        return True
    return safe_run(cmd)


def print_release_summary(result: ReleaseResult) -> None:
    print("Build:", "success" if result.build_success else "fail")
    print("Commit:", "success" if result.commit_success else "fail")
    print("Push github:", "success" if result.push_github_success else "fail")
    print("Push nas:", "success" if result.push_nas_success else "fail")
    print("Push github tag:", "success" if result.push_github_tag_success else "fail")
    print("Push nas tag:", "success" if result.push_nas_tag_success else "fail")
    print("Tag:", "success" if result.tag_success else "fail")
    print("Final status:", result.final_status)


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
    parser.add_argument("--version", help="release version, e.g. v1.2.0")
    parser.add_argument("--dry-run", action="store_true", help="print actions without changing git")
    args = parser.parse_args()
    result = release(version=args.version, dry_run=args.dry_run)
    print(f"release version: {result.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
