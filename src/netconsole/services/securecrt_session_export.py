from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re

from netconsole.models.device import Device
from netconsole.services.netmiko_connection import connection_targets


WINDOWS_INVALID_CHARS = re.compile(r'[\\/:*?"<>|]+')


@dataclass(frozen=True)
class SecureCrtSessionExportResult:
    output_dir: Path
    generated: int
    skipped: int
    skipped_rows: list[dict[str, object]]


def export_securecrt_sessions(
    devices: list[Device],
    site_name: str,
    output_parent: Path,
    group_names: dict[int, str] | None = None,
    template_ini: Path | None = None,
) -> SecureCrtSessionExportResult:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    site = sanitize_path_part(site_name or "NetConsole")
    output_dir = Path(output_parent) / "NetConsole_CRT_Sessions" / f"{site}_{timestamp}"
    root_dir = output_dir / site
    root_dir.mkdir(parents=True, exist_ok=True)
    group_names = group_names or {}
    generated_rows: list[dict[str, object]] = []
    skipped_rows: list[dict[str, object]] = []
    used_names: set[Path] = set()
    template_text = _read_template(template_ini)
    for device in devices:
        targets = [target for target in connection_targets(device) if not target.via_tunnel]
        if not targets:
            skipped_rows.append(_skipped_row(device, "未启用 SSH/Telnet 或仅配置内部临时隧道"))
            continue
        target = targets[0]
        group = group_names.get(int(device.group_id or 0), "未分组")
        station = str(device.station or "未归属").strip() or "未归属"
        device_dir = root_dir / sanitize_path_part(group) / sanitize_path_part(station)
        device_dir.mkdir(parents=True, exist_ok=True)
        filename = unique_session_filename(device_dir, device, used_names)
        session_path = device_dir / filename
        session_path.write_text(_session_ini_text(device, target, session_path.stem, template_text), encoding="utf-8")
        generated_rows.append(
            {
                "device_name": device.name,
                "host": target.host,
                "port": target.port,
                "protocol": _securecrt_protocol(target.protocol),
                "path": str(session_path.relative_to(output_dir)),
            }
        )
    _write_csv(output_dir / "sessions_index.csv", generated_rows, ["device_name", "host", "port", "protocol", "path"])
    _write_csv(output_dir / "skipped.csv", skipped_rows, ["device_name", "host", "reason"])
    (output_dir / "README_导入说明.txt").write_text(_readme(site), encoding="utf-8")
    return SecureCrtSessionExportResult(output_dir, len(generated_rows), len(skipped_rows), skipped_rows)


def sanitize_path_part(value: object) -> str:
    text = WINDOWS_INVALID_CHARS.sub("_", str(value or "").strip()).strip(" .")
    return text or "未命名"


def unique_session_filename(directory: Path, device: Device, used_names: set[Path] | None = None) -> str:
    used_names = used_names if used_names is not None else set()
    base = sanitize_path_part(f"{device.name or device.system_name or 'device'}__{device.primary_address or 'no_ip'}")
    candidate = f"{base}.ini"
    index = 2
    while directory / candidate in used_names or (directory / candidate).exists():
        candidate = f"{base}_{index}.ini"
        index += 1
    used_names.add(directory / candidate)
    return candidate


def _read_template(template_ini: Path | None) -> str:
    if template_ini and template_ini.is_file():
        return template_ini.read_text(encoding="utf-8", errors="ignore")
    return ""


def _session_ini_text(device: Device, target, session_name: str, template_text: str) -> str:
    protocol = _securecrt_protocol(target.protocol)
    replacements = {
        "S:\"Hostname\"": f'S:"Hostname"={target.host}',
        "D:\"Port\"": f'D:"Port"={int(target.port)}',
        "S:\"Protocol Name\"": f'S:"Protocol Name"={protocol}',
        "S:\"Username\"": f'S:"Username"={target.username}',
        "S:\"Session Name\"": f'S:"Session Name"={session_name}',
        "S:\"Description\"": f'S:"Description"={device.name or session_name}',
    }
    if template_text:
        lines = template_text.splitlines()
        seen: set[str] = set()
        output: list[str] = []
        for line in lines:
            key = next((prefix for prefix in replacements if line.startswith(prefix)), "")
            if key:
                output.append(replacements[key])
                seen.add(key)
            else:
                output.append(line)
        output.extend(value for key, value in replacements.items() if key not in seen)
        return "\n".join(output) + "\n"
    return "\n".join(
        [
            'S:"Protocol Name"=' + protocol,
            'S:"Hostname"=' + target.host,
            'D:"Port"=' + str(int(target.port)),
            'S:"Username"=' + target.username,
            'S:"Session Name"=' + session_name,
            'S:"Description"=' + str(device.name or session_name),
            "",
        ]
    )


def _securecrt_protocol(protocol: object) -> str:
    return "SSH2" if str(protocol or "").casefold() == "ssh" else "Telnet"


def _write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _skipped_row(device: Device, reason: str) -> dict[str, object]:
    return {"device_name": device.name, "host": device.primary_address, "reason": reason}


def _readme(site_name: str) -> str:
    return (
        f"请将整个 {site_name} 文件夹复制到 SecureCRT Sessions 目录。\n"
        "SecureCRT Sessions 目录可在 SecureCRT Global Options 中查看。\n"
        "NetConsole 默认不写入密码，建议由 SecureCRT 自己保存密码。\n"
        "如生成的最小会话无法识别，请在设置中选择一个已有 SecureCRT .ini 作为模板后重新生成。\n"
    )
