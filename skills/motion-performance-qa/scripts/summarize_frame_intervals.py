#!/usr/bin/env python3
"""Summarize frame timestamps or intervals from a JSON or CSV trace."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize frame intervals with deterministic nearest-rank percentiles."
    )
    parser.add_argument("trace", type=Path, help="JSON or CSV trace file")
    return parser.parse_args()


def _numbers(values: Any, label: str) -> list[float]:
    if not isinstance(values, list):
        raise ValueError(f"{label} must be a JSON array")
    result: list[float] = []
    for index, value in enumerate(values):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{label}[{index}] must be numeric")
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"{label}[{index}] must be finite")
        result.append(number)
    return result


def load_json(path: Path) -> tuple[str, list[float]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return "intervals", _numbers(data, "intervals")
    if not isinstance(data, dict):
        raise ValueError("JSON must be an array or object")
    if "intervals_ms" in data:
        return "intervals", _numbers(data["intervals_ms"], "intervals_ms")
    if "timestamps_ms" in data:
        return "timestamps", _numbers(data["timestamps_ms"], "timestamps_ms")
    raise ValueError("JSON object must contain intervals_ms or timestamps_ms")


def load_csv(path: Path) -> tuple[str, list[float]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        if "interval_ms" in fields:
            column, kind = "interval_ms", "intervals"
        elif "timestamp_ms" in fields:
            column, kind = "timestamp_ms", "timestamps"
        else:
            raise ValueError("CSV must contain interval_ms or timestamp_ms")
        values: list[float] = []
        for row_number, row in enumerate(reader, start=2):
            raw = row.get(column, "")
            try:
                number = float(raw)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{column} at row {row_number} must be numeric") from exc
            if not math.isfinite(number):
                raise ValueError(f"{column} at row {row_number} must be finite")
            values.append(number)
    return kind, values


def intervals_from(kind: str, values: list[float]) -> list[float]:
    if kind == "timestamps":
        if len(values) < 2:
            raise ValueError("at least two timestamps are required")
        intervals = [later - earlier for earlier, later in zip(values, values[1:])]
        if any(value <= 0 for value in intervals):
            raise ValueError("timestamps must be strictly increasing")
        return intervals
    if not values:
        raise ValueError("at least one interval is required")
    if any(value <= 0 for value in values):
        raise ValueError("intervals must be greater than zero")
    return values


def nearest_rank(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def summarize(intervals_ms: list[float]) -> dict[str, Any]:
    return {
        "method": "nearest-rank",
        "unit": "ms",
        "sample_count": len(intervals_ms),
        "mean_ms": round(statistics.fmean(intervals_ms), 4),
        "median_ms": round(statistics.median(intervals_ms), 4),
        "p95_ms": round(nearest_rank(intervals_ms, 0.95), 4),
        "max_ms": round(max(intervals_ms), 4),
        "over_33_4_ms": sum(value > 33.4 for value in intervals_ms),
        "over_50_ms": sum(value > 50.0 for value in intervals_ms),
    }


def main() -> int:
    args = parse_args()
    try:
        if not args.trace.is_file():
            raise ValueError("trace file does not exist")
        if args.trace.suffix.lower() == ".json":
            kind, values = load_json(args.trace)
        elif args.trace.suffix.lower() == ".csv":
            kind, values = load_csv(args.trace)
        else:
            raise ValueError("trace must use a .json or .csv extension")
        intervals_ms = intervals_from(kind, values)
        print(json.dumps(summarize(intervals_ms), indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
