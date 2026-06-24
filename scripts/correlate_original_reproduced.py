#!/usr/bin/env python3
"""Correlate reproduced firm-level scores with original firm-quarter scores."""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


ORIGINAL_FILE = Path("data/original/scores/firmquarter_2022q1.csv")
DEFAULT_REPRODUCED_DIRS = (Path("data/reproduced_v2"), Path("data/reproduced_v2.1"))


@dataclass(frozen=True)
class SeriesSpec:
    series: str
    original_column: str
    raw_measure_col: str
    file_fragment: str

    @property
    def reproduced_value(self) -> str:
        return f"{self.raw_measure_col} / nr_of_words"


@dataclass(frozen=True)
class LoadedSeries:
    spec: SeriesSpec
    path: Path
    values: dict[tuple[str, str], float]


SERIES_SPECS = [
    SeriesSpec("PRisk", "PRisk", "risk", "prisk-and-psentiment"),
    SeriesSpec("PSentiment", "PSentiment", "sentiment", "prisk-and-psentiment"),
    SeriesSpec("PRiskT_economic", "PRiskT_economic", "risk", "topic-based-prisk-economy"),
    SeriesSpec("PRiskT_environment", "PRiskT_environment", "risk", "topic-based-prisk-environment"),
    SeriesSpec("PRiskT_trade", "PRiskT_trade", "risk", "topic-based-prisk-trade"),
    SeriesSpec(
        "PRiskT_institutions",
        "PRiskT_institutions",
        "risk",
        "topic-based-prisk-institutions",
    ),
    SeriesSpec("PRiskT_health", "PRiskT_health", "risk", "topic-based-prisk-health"),
    SeriesSpec("PRiskT_security", "PRiskT_security", "risk", "topic-based-prisk-security"),
    SeriesSpec("PRiskT_tax", "PRiskT_tax", "risk", "topic-based-prisk-tax"),
    SeriesSpec("PRiskT_technology", "PRiskT_technology", "risk", "topic-based-prisk-technology"),
]

GVKEY_DATEQ_FIELDS = [
    "series",
    "original_column",
    "reproduced_value",
    "reproduced_file",
    "first_dateQ",
    "last_dateQ",
    "level",
    "n_pairs",
    "n_dateQ",
    "pearson",
]

DATEQ_FIELDS = [
    "series",
    "original_column",
    "reproduced_value",
    "reproduced_file",
    "first_dateQ",
    "last_dateQ",
    "level",
    "n_pairs",
    "matched_gvkey_dateQ",
    "pearson",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reproduced-dir",
        action="append",
        type=Path,
        help=(
            "Directory containing *_firmlevel.csv files. Can be repeated. "
            "Defaults to available reproduced_v2 and reproduced_v2.1 directories."
        ),
    )
    parser.add_argument("--original-file", type=Path, default=ORIGINAL_FILE)
    parser.add_argument("--out-dir", type=Path, default=Path("data/correlations"))
    return parser.parse_args()


def parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def parse_dateq(timestamp: str | None) -> str | None:
    if not timestamp or len(timestamp) < 7:
        return None
    try:
        year = int(timestamp[0:4])
        month = int(timestamp[5:7])
    except ValueError:
        return None
    if month < 1 or month > 12:
        return None
    return f"{year}q{((month - 1) // 3) + 1}"


def pearson(pairs: list[tuple[float, float]]) -> float | None:
    n = len(pairs)
    if n < 2:
        return None

    mean_x = sum(x for x, _ in pairs) / n
    mean_y = sum(y for _, y in pairs) / n
    sxx = sum((x - mean_x) ** 2 for x, _ in pairs)
    syy = sum((y - mean_y) ** 2 for _, y in pairs)
    if sxx <= 0.0 or syy <= 0.0:
        return None
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in pairs)
    return sxy / math.sqrt(sxx * syy)


def mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def format_float(value: object) -> object:
    if isinstance(value, float):
        return f"{value:.15g}"
    return value


def available_reproduced_dirs(explicit_dirs: list[Path] | None) -> list[Path]:
    candidates = explicit_dirs if explicit_dirs else list(DEFAULT_REPRODUCED_DIRS)
    return [path for path in candidates if path.exists()]


def read_original(
    original_file: Path,
    columns: set[str],
) -> dict[str, dict[tuple[str, str], float]]:
    by_column: dict[str, dict[tuple[str, str], float]] = defaultdict(dict)
    sums: dict[tuple[str, tuple[str, str]], tuple[float, int]] = defaultdict(lambda: (0.0, 0))

    with original_file.open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames is None:
            raise ValueError(f"Missing header in {original_file}")
        missing = columns.difference(reader.fieldnames)
        if missing:
            raise ValueError(f"{original_file} is missing columns: {', '.join(sorted(missing))}")

        for row in reader:
            gvkey = (row.get("gvkey") or "").strip()
            dateq = (row.get("date") or "").strip()
            if not gvkey or not dateq:
                continue
            key = (gvkey, dateq)
            for column in columns:
                value = parse_float(row.get(column))
                if value is None:
                    continue
                agg_key = (column, key)
                total, count = sums[agg_key]
                sums[agg_key] = (total + value, count + 1)

    for (column, key), (total, count) in sums.items():
        by_column[column][key] = total / count

    return by_column


def resolve_reproduced_file(reproduced_dir: Path, spec: SeriesSpec) -> Path | None:
    candidates = sorted(reproduced_dir.glob(f"*{spec.file_fragment}*_firmlevel.csv"))
    if not candidates:
        return None
    if len(candidates) > 1:
        names = ", ".join(path.name for path in candidates)
        raise ValueError(f"Multiple files match {spec.file_fragment!r} under {reproduced_dir}: {names}")
    return candidates[0]


def load_reproduced_series(reproduced_file: Path, spec: SeriesSpec) -> LoadedSeries:
    accumulators: dict[tuple[str, str], dict[str, float]] = defaultdict(
        lambda: {"numerator": 0.0, "nr_of_words": 0.0}
    )

    with reproduced_file.open(newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"gvkey", "start_time", spec.raw_measure_col, "nr_of_words"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{reproduced_file} is missing columns: {', '.join(sorted(missing))}")

        for row in reader:
            gvkey = (row.get("gvkey") or "").strip()
            dateq = parse_dateq(row.get("start_time"))
            numerator = parse_float(row.get(spec.raw_measure_col))
            nr_of_words = parse_float(row.get("nr_of_words"))
            if not gvkey or dateq is None or numerator is None or nr_of_words is None:
                continue
            if nr_of_words <= 0:
                continue

            bucket = accumulators[(gvkey, dateq)]
            bucket["numerator"] += numerator
            bucket["nr_of_words"] += nr_of_words

    values = {
        key: bucket["numerator"] / bucket["nr_of_words"]
        for key, bucket in accumulators.items()
        if bucket["nr_of_words"] > 0
    }
    return LoadedSeries(spec=spec, path=reproduced_file, values=values)


def build_correlation_rows(
    version_dir: Path,
    original_by_column: dict[str, dict[tuple[str, str], float]],
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[str]]:
    gvkey_dateq_rows: list[dict[str, object]] = []
    dateq_rows: list[dict[str, object]] = []
    skipped: list[str] = []

    for spec in SERIES_SPECS:
        reproduced_file = resolve_reproduced_file(version_dir, spec)
        if reproduced_file is None:
            skipped.append(spec.series)
            continue

        loaded = load_reproduced_series(reproduced_file, spec)
        original_values = original_by_column[spec.original_column]
        common_keys = sorted(set(loaded.values).intersection(original_values))
        gvkey_dateq_pairs = [(loaded.values[key], original_values[key]) for key in common_keys]
        matched_dateqs = [key[1] for key in common_keys]

        dateq_reproduced_values: dict[str, list[float]] = defaultdict(list)
        dateq_original_values: dict[str, list[float]] = defaultdict(list)
        for key in common_keys:
            dateq_reproduced_values[key[1]].append(loaded.values[key])
            dateq_original_values[key[1]].append(original_values[key])

        dateq_pairs: list[tuple[float, float]] = []
        for dateq in sorted(set(dateq_reproduced_values).intersection(dateq_original_values)):
            reproduced_mean = mean(dateq_reproduced_values[dateq])
            original_mean = mean(dateq_original_values[dateq])
            if reproduced_mean is None or original_mean is None:
                continue
            dateq_pairs.append((reproduced_mean, original_mean))

        common_dateqs = sorted(set(matched_dateqs))
        base = {
            "series": spec.series,
            "original_column": spec.original_column,
            "reproduced_value": spec.reproduced_value,
            "reproduced_file": loaded.path.name,
            "first_dateQ": common_dateqs[0] if common_dateqs else "",
            "last_dateQ": common_dateqs[-1] if common_dateqs else "",
        }
        gvkey_dateq_rows.append(
            {
                **base,
                "level": "gvkey-dateQ",
                "n_pairs": len(gvkey_dateq_pairs),
                "n_dateQ": len(common_dateqs),
                "pearson": pearson(gvkey_dateq_pairs),
            }
        )
        dateq_rows.append(
            {
                **base,
                "level": "dateQ",
                "n_pairs": len(dateq_pairs),
                "matched_gvkey_dateQ": len(gvkey_dateq_pairs),
                "pearson": pearson(dateq_pairs),
            }
        )

    return gvkey_dateq_rows, dateq_rows, skipped


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: format_float(row.get(field, "")) for field in fieldnames})


def write_version_outputs(
    out_dir: Path,
    version_name: str,
    gvkey_dateq_rows: list[dict[str, object]],
    dateq_rows: list[dict[str, object]],
) -> tuple[Path, Path]:
    gvkey_dateq_path = out_dir / f"{version_name}_gvkey_dateq_correlations.csv"
    dateq_path = out_dir / f"{version_name}_dateq_correlations.csv"
    write_csv(gvkey_dateq_path, gvkey_dateq_rows, GVKEY_DATEQ_FIELDS)
    write_csv(dateq_path, dateq_rows, DATEQ_FIELDS)
    return gvkey_dateq_path, dateq_path


def with_version(rows: list[dict[str, object]], version_name: str) -> list[dict[str, object]]:
    return [{"reproduced_version": version_name, **row} for row in rows]


def main() -> None:
    args = parse_args()
    reproduced_dirs = available_reproduced_dirs(args.reproduced_dir)
    if not reproduced_dirs:
        raise SystemExit("No reproduced directories found.")

    original_columns = {spec.original_column for spec in SERIES_SPECS}
    original_by_column = read_original(args.original_file, original_columns)

    all_gvkey_dateq_rows: list[dict[str, object]] = []
    all_dateq_rows: list[dict[str, object]] = []
    for reproduced_dir in reproduced_dirs:
        version_name = reproduced_dir.name
        gvkey_dateq_rows, dateq_rows, skipped = build_correlation_rows(
            reproduced_dir,
            original_by_column,
        )
        if not gvkey_dateq_rows:
            print(f"Skipped {version_name}: no matching firmlevel files")
            continue

        gvkey_dateq_path, dateq_path = write_version_outputs(
            args.out_dir,
            version_name,
            gvkey_dateq_rows,
            dateq_rows,
        )
        print(f"Wrote {gvkey_dateq_path}")
        print(f"Wrote {dateq_path}")

        if skipped:
            print(f"{version_name}: skipped unavailable series: {', '.join(skipped)}")

        all_gvkey_dateq_rows.extend(with_version(gvkey_dateq_rows, version_name))
        all_dateq_rows.extend(with_version(dateq_rows, version_name))

    if all_gvkey_dateq_rows:
        write_csv(
            args.out_dir / "reproduced_versions_gvkey_dateq_correlations.csv",
            all_gvkey_dateq_rows,
            ["reproduced_version", *GVKEY_DATEQ_FIELDS],
        )
        write_csv(
            args.out_dir / "reproduced_versions_dateq_correlations.csv",
            all_dateq_rows,
            ["reproduced_version", *DATEQ_FIELDS],
        )
        print(f"Wrote {args.out_dir / 'reproduced_versions_gvkey_dateq_correlations.csv'}")
        print(f"Wrote {args.out_dir / 'reproduced_versions_dateq_correlations.csv'}")


if __name__ == "__main__":
    main()
