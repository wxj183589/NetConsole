from __future__ import annotations

import ipaddress
import re

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices


HTTPS_PORT_PATTERN = re.compile(r"(?i)\bHTTPS\s+port\s*[:：]\s*(\d{1,5})\b")
DEFAULT_HTTPS_PORT = 443


def parse_https_port(output: str) -> int | None:
    text = clean_https_port_output(output)
    for match in HTTPS_PORT_PATTERN.finditer(text):
        try:
            port = int(match.group(1))
        except ValueError:
            continue
        if 1 <= port <= 65535:
            return port
    return None


def clean_https_port_output(output: str) -> str:
    text = _strip_ansi(str(output or ""))
    text = text.replace("\b", "").replace("\r", "\n")
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.casefold() in {"display ip https | include port", "display ip https"}:
            continue
        if re.fullmatch(r"[<\[].+[>\]]", stripped):
            continue
        lines.append(stripped)
    return "\n".join(lines)


def matching_https_port_lines(output: str) -> list[str]:
    text = clean_https_port_output(output)
    return [line for line in text.splitlines() if HTTPS_PORT_PATTERN.search(line)]


def build_https_url(host: object, port: object) -> str | None:
    host_text = str(host or "").strip()
    if not host_text:
        return None
    try:
        port_value = int(port)
    except (TypeError, ValueError):
        return None
    if not 1 <= port_value <= 65535:
        return None
    try:
        parsed = ipaddress.ip_address(host_text.strip("[]"))
        host_part = f"[{parsed.compressed}]" if parsed.version == 6 else parsed.compressed
    except ValueError:
        if any(char.isspace() for char in host_text):
            return None
        host_part = host_text
    return f"https://{host_part}:{port_value}"


def effective_https_port(stored_port: object) -> tuple[int, str]:
    try:
        port = int(stored_port)
    except (TypeError, ValueError):
        return DEFAULT_HTTPS_PORT, "default"
    if 1 <= port <= 65535:
        return port, "device"
    return DEFAULT_HTTPS_PORT, "default"


def open_https_url(host: object, port: object) -> bool:
    url = build_https_url(host, port)
    if not url:
        return False
    return bool(QDesktopServices.openUrl(QUrl(url)))


def _strip_ansi(value: str) -> str:
    return re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", value)
