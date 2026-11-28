from __future__ import annotations

import ipaddress
import locale
import os
from pathlib import Path
import re
import subprocess
from typing import Literal

from netconsole.utils.text_encoding import decode_bytes_with_fallback


def run_host_diagnostic(kind: Literal["traceroute", "dns"], target: str) -> str:
    target = target.strip()
    if kind == "traceroute":
        try:
            address = ipaddress.ip_address(target)
            if "%" in target:
                raise ValueError
            target = str(address)
        except ValueError as exc:
            raise ValueError("请输入单个 IPv4 或 IPv6 地址") from exc
        program, arguments = "tracert.exe", ["-d", "-h", "12", "-w", "500", target]
    else:
        target = target.rstrip(".").encode("idna").decode("ascii")
        if len(target) > 253 or not all(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label) for label in target.split(".")):
            raise ValueError("请输入单个 DNS 主机名")
        program, arguments = "nslookup.exe", ["-timeout=2", "-retry=1", target + "."]
    root = Path(os.environ.get("SystemRoot", "C:/Windows"))
    executable = root / "System32" / program
    if os.name != "nt" or not executable.is_file():
        raise ValueError("当前系统缺少该网络诊断组件")
    try:
        result = subprocess.run(
            [str(executable), *arguments], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=25,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("网络诊断未能在时限内完成") from exc
    return decode_bytes_with_fallback(result.stdout, encodings=("utf-8", "oem", locale.getpreferredencoding(False))).text.strip()
