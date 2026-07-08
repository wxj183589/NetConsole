from __future__ import annotations


def calc_numeric_stats(values, *, p10_ratio: float = 0.1, precision: int = 3) -> dict[str, object]:
    valid: list[float] = []
    for value in values:
        if value is None or value == "":
            continue
        try:
            valid.append(float(value))
        except (TypeError, ValueError):
            continue
    if not valid:
        return {"avg": None, "min": None, "max": None, "p10": None, "count": 0}
    ordered = sorted(valid)
    return {
        "avg": round(sum(valid) / len(valid), precision),
        "min": min(valid),
        "max": max(valid),
        "p10": _percentile(ordered, p10_ratio, precision),
        "count": len(valid),
    }


def _percentile(ordered: list[float], ratio: float, precision: int) -> float | None:
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    pos = max(min(float(ratio), 1.0), 0.0) * (len(ordered) - 1)
    lower = int(pos)
    upper = min(lower + 1, len(ordered) - 1)
    if lower == upper:
        return ordered[lower]
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (pos - lower), precision)

