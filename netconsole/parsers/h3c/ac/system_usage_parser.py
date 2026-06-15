from __future__ import annotations

import re


def parse_cpu_usage(output: str) -> dict[str, object | None]:
    values = [int(value) for value in re.findall(r"(\d+)%\s+in\s+last\s+(?:5\s+seconds|1\s+minute|5\s+minutes)", output or "", flags=re.IGNORECASE)]
    return {
        "cpu_5s": values[0] if len(values) > 0 else None,
        "cpu_1m": values[1] if len(values) > 1 else None,
        "cpu_5m": values[2] if len(values) > 2 else None,
        "cpu_usage": f"{values[0]}%" if values else None,
    }


def parse_memory(output: str) -> dict[str, object | None]:
    lines = [line.strip() for line in (output or "").splitlines() if line.strip()]
    for line in lines:
        if line.lower().startswith("mem:") and len(re.findall(r"\d+(?:\.\d+)?%?", line)) >= 4:
            numbers = re.findall(r"\d+(?:\.\d+)?%?", line)
            total = _int_value(numbers[0])
            used = _int_value(numbers[1])
            free = _int_value(numbers[2])
            free_ratio = _float_value(numbers[-1])
            usage = round(100 - free_ratio) if free_ratio is not None else None
            return {
                "memory_total": total,
                "memory_used": used,
                "memory_free": free,
                "memory_free_ratio": free_ratio,
                "memory_usage": f"{usage}%" if usage is not None else None,
            }
    mem_index = next((index for index, line in enumerate(lines) if line.lower().startswith("mem")), -1)
    values: list[str] = []
    if mem_index >= 0:
        for line in lines[mem_index + 1 :]:
            if re.fullmatch(r"\d+(?:\.\d+)?%?", line):
                values.append(line)
            if len(values) >= 4:
                break
    if len(values) < 4:
        values = re.findall(r"\b\d+(?:\.\d+)?%?\b", output or "")[:4]
    total = _int_value(values[0]) if len(values) > 0 else None
    used = _int_value(values[1]) if len(values) > 1 else None
    free = _int_value(values[2]) if len(values) > 2 else None
    free_ratio = _float_value(values[3]) if len(values) > 3 else None
    usage = round(100 - free_ratio) if free_ratio is not None else None
    return {
        "memory_total": total,
        "memory_used": used,
        "memory_free": free,
        "memory_free_ratio": free_ratio,
        "memory_usage": f"{usage}%" if usage is not None else None,
    }


def _int_value(value: str) -> int | None:
    match = re.search(r"\d+", value or "")
    return int(match.group(0)) if match else None


def _float_value(value: str) -> float | None:
    match = re.search(r"\d+(?:\.\d+)?", value or "")
    return float(match.group(0)) if match else None
