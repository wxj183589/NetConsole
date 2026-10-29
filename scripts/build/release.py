from __future__ import annotations

import argparse
import re


APP_AUTHOR = "梦游"


class ReleaseAutomationDisabled(RuntimeError):
    """Raised when the retired script-based release flow is invoked."""


def get_release_version(explicit_version: str | None = None) -> str:
    if not explicit_version:
        raise ValueError("正式发布必须显式指定 --version，例如 --version v1.5.2")
    _version_numbers(explicit_version)
    return explicit_version


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


def release(version: str | None = None, dry_run: bool = False) -> None:
    selected_version = get_release_version(version)
    raise ReleaseAutomationDisabled(
        f"自动 Git 发布流程已停用（{selected_version}）。请先通过版本 PR 和全部门禁，"
        "再使用 scripts/build/package_windows.ps1 构建；Tag 与 GitHub Release 需在验证后单独创建。"
    )


def _version_numbers(version: str) -> tuple[int, int, int, int]:
    match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", version)
    if not match:
        raise ValueError(f"invalid version: {version}")
    return int(match.group(1)), int(match.group(2)), int(match.group(3)), 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Retired NetConsole release orchestration")
    parser.add_argument("--version", required=True, help="release version, e.g. v1.5.2")
    parser.add_argument("--dry-run", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        release(version=args.version, dry_run=args.dry_run)
    except (ReleaseAutomationDisabled, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
