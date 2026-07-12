from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from netconsole.core.paths import PathResolver
from netconsole.core.settings import SettingsStore
from netconsole.services import external_tool_service as service


def _context(tmp_path: Path) -> tuple[PathResolver, SettingsStore]:
    paths = PathResolver(app_root=tmp_path, data_root=tmp_path / "data")
    return paths, SettingsStore(paths)


def _exe(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"MZ")
    return path


def test_valid_configured_ipop_path_has_priority(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(service.sys, "platform", "win32")
    paths, settings = _context(tmp_path)
    configured = _exe(tmp_path / "用户 工具" / "IPOP.EXE")
    local_file = _exe(service.get_local_ipop_path(paths))
    service.save_ipop_path(f'  "{configured}"  ', settings, paths=paths)

    assert service.resolve_ipop_executable(paths, settings=settings) == configured.resolve()
    assert service.get_configured_ipop_path(settings, paths=paths) == configured.resolve()
    assert local_file.exists()


def test_invalid_config_does_not_get_overwritten_when_local_path_is_used(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(service.sys, "platform", "win32")
    paths, settings = _context(tmp_path)
    missing = tmp_path / "已移动" / "IPOP.EXE"
    local_file = _exe(service.get_local_ipop_path(paths))
    service.save_ipop_path(missing, settings, paths=paths)

    assert service.resolve_ipop_executable(paths, settings=settings) == local_file.resolve()
    assert SettingsStore(paths).get_value(service.IPOP_SETTINGS_KEY) == str(missing.resolve())


def test_empty_config_uses_local_path_and_missing_paths_return_none(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(service.sys, "platform", "win32")
    paths, settings = _context(tmp_path)
    local_file = _exe(service.get_local_ipop_path(paths))
    assert service.resolve_ipop_executable(paths, settings=settings) == local_file.resolve()

    local_file.unlink()
    assert service.resolve_ipop_executable(paths, settings=settings) is None


def test_missing_ipop_reports_new_path_and_does_not_use_old_directory(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(service.sys, "platform", "win32")
    paths, settings = _context(tmp_path)
    _exe(tmp_path / "tools" / ("IPOP_" + "v4.1") / "IPOP.EXE")

    assert service.resolve_ipop_executable(paths, settings=settings) is None
    result = service.launch_ipop(paths, settings=settings)
    assert not result.success
    assert result.error_code == "not_configured"
    assert "tools\\windows-x64\\ipop\\IPOP.EXE" in result.message


def test_ipop_validation_rejects_directory_and_non_exe_on_windows(tmp_path: Path) -> None:
    directory = tmp_path / "IPOP.EXE"
    directory.mkdir()
    text_file = tmp_path / "IPOP.txt"
    text_file.write_text("not exe", encoding="utf-8")

    assert service.validate_ipop_executable(directory, platform_name="win32").error_code == "is_directory"
    assert service.validate_ipop_executable(text_file, platform_name="win32").error_code == "not_exe"


def test_save_clear_and_reload_ipop_path(tmp_path: Path) -> None:
    paths, settings = _context(tmp_path)
    target = tmp_path / "中文 目录" / "IPOP.EXE"

    normalized = service.save_ipop_path(f' "{target}" ', settings, paths=paths)

    assert normalized == target.resolve()
    assert SettingsStore(paths).get_value(service.IPOP_SETTINGS_KEY) == str(target.resolve())
    service.clear_ipop_path(settings, paths=paths)
    assert SettingsStore(paths).get_value(service.IPOP_SETTINGS_KEY) == ""


def test_launch_ipop_uses_detached_process_arguments_and_working_directory(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(service.sys, "platform", "win32")
    paths, settings = _context(tmp_path)
    executable = _exe(tmp_path / "中文 路径 (测试)" / "IPOP.EXE")
    service.save_ipop_path(executable, settings, paths=paths)
    calls: list[tuple[str, list[str], str]] = []
    monkeypatch.setattr(
        service,
        "QProcess",
        SimpleNamespace(startDetached=lambda program, arguments, working_directory: calls.append((program, arguments, working_directory)) or (True, 1234)),
    )

    result = service.launch_ipop(paths, settings=settings)

    assert result.success
    assert calls == [(str(executable.resolve()), [], str(executable.parent.resolve()))]


def test_launch_ipop_converts_qprocess_failures_to_readable_results(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(service.sys, "platform", "win32")
    paths, settings = _context(tmp_path)
    executable = _exe(tmp_path / "IPOP.EXE")
    service.save_ipop_path(executable, settings, paths=paths)
    monkeypatch.setattr(service, "QProcess", SimpleNamespace(startDetached=lambda *_args: (False, 0)))

    result = service.launch_ipop(paths, settings=settings)

    assert not result.success
    assert result.error_code == "qprocess_failed"
    assert "QProcess" in result.message


def test_launch_ipop_reports_permission_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(service.sys, "platform", "win32")
    paths, settings = _context(tmp_path)
    executable = _exe(tmp_path / "IPOP.EXE")
    service.save_ipop_path(executable, settings, paths=paths)

    def denied(*_args):
        raise PermissionError("Access is denied")

    monkeypatch.setattr(service, "QProcess", SimpleNamespace(startDetached=denied))

    result = service.launch_ipop(paths, settings=settings)

    assert not result.success
    assert result.error_code == "permission_denied"
    assert "权限不足" in result.message


def test_launch_ipop_reports_unsupported_platform(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(service.sys, "platform", "linux")

    result = service.launch_ipop(PathResolver(app_root=tmp_path, data_root=tmp_path))

    assert not result.success
    assert result.error_code == "unsupported_platform"
    assert result.message == "不支持当前平台"
