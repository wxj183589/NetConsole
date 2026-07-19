from pathlib import Path

import pytest

from netconsole.services.settings_tool_validation import (
    SettingsToolPathError,
    validate_settings_tool_path,
)


def test_tool_path_requires_matching_regular_executable(tmp_path: Path) -> None:
    executable = tmp_path / "iperf3.exe"
    executable.write_bytes(b"MZ")
    assert validate_settings_tool_path("iperf3", executable) == executable.resolve()

    disguised = tmp_path / "cmd.exe"
    disguised.write_bytes(b"MZ")
    with pytest.raises(SettingsToolPathError, match="iperf3.exe"):
        validate_settings_tool_path("iperf3", disguised)
    with pytest.raises(SettingsToolPathError, match="绝对路径"):
        validate_settings_tool_path("iperf3", Path("iperf3.exe"))


def test_tool_path_rejects_directory_and_symlink(tmp_path: Path) -> None:
    directory = tmp_path / "IPOP.EXE"
    directory.mkdir()
    with pytest.raises(SettingsToolPathError, match="普通文件"):
        validate_settings_tool_path("ipop", directory)

    target = tmp_path / "real" / "IPOP.EXE"
    target.parent.mkdir()
    target.write_bytes(b"MZ")
    link = tmp_path / "IPOP-link" / "IPOP.EXE"
    link.parent.mkdir()
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("当前环境不允许创建符号链接")
    with pytest.raises(SettingsToolPathError, match="符号链接"):
        validate_settings_tool_path("ipop", link)


@pytest.mark.parametrize("name", ["putty.exe", "PuTTY.exe", "putty64.exe", "PuTTY64.exe", "PUTTY64.EXE"])
def test_putty_accepts_32_and_64_bit_executable_names_case_insensitively(tmp_path: Path, name: str) -> None:
    executable = tmp_path / name
    executable.write_bytes(b"MZ")

    assert validate_settings_tool_path("putty", executable) == executable.resolve()


@pytest.mark.parametrize("name", ["puttygen.exe", "plink.exe", "psftp.exe", "putty.exe.bak", "putty.bat"])
def test_putty_rejects_other_programs_and_disguised_files(tmp_path: Path, name: str) -> None:
    executable = tmp_path / name
    executable.write_bytes(b"MZ")

    with pytest.raises(SettingsToolPathError, match="putty.exe 或 putty64.exe"):
        validate_settings_tool_path("putty", executable)


@pytest.mark.parametrize(
    ("terminal_type", "name"),
    [("putty", "SecureCRT.exe"), ("securecrt", "PuTTY64.exe"), ("xshell", "putty.exe")],
)
def test_terminal_type_rejects_another_terminal_executable(tmp_path: Path, terminal_type: str, name: str) -> None:
    executable = tmp_path / name
    executable.write_bytes(b"MZ")

    with pytest.raises(SettingsToolPathError, match="类型不匹配"):
        validate_settings_tool_path(terminal_type, executable)
