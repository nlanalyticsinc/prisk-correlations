#!/usr/bin/env python3
"""Correlate reproduced firm-level scores with original firm-quarter scores."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import TextIO

ORIGINAL_DIR = Path("data/original")
REPRODUCED_DIR = Path("data/reproduced")
ORIGINAL_FILE_PATTERNS = ("firmquarter_*.csv", "firmlevel_*.csv")
REPRODUCED_FILE_PREFIX = "NLA_"
# Series pages download flat NLA_*_firmlevel.csv files; the measure's
# "Download dataset (ZIP)" bundle has series/<NN>-<series>-<id>/firmlevel.csv.gz.
REPRODUCED_FILE_PATTERNS = (
    REPRODUCED_FILE_PREFIX + "*{fragment}*_firmlevel.csv",
    REPRODUCED_FILE_PREFIX + "*{fragment}*_firmlevel.csv.gz",
    "*{fragment}*/firmlevel.csv",
    "*{fragment}*/firmlevel.csv.gz",
    "series/*{fragment}*/firmlevel.csv",
    "series/*{fragment}*/firmlevel.csv.gz",
)
# Firm-level files downloaded since October 2026 have no gvkey column. GVKEY is in the
# measure's crosswalk, joined on earningscallID: gvkeys.csv(.gz) at the root of the ZIP,
# or NLA_*_gvkeys.csv from a series page.
GVKEY_CROSSWALK_PATTERNS = (
    "gvkeys.csv",
    "gvkeys.csv.gz",
    REPRODUCED_FILE_PREFIX + "*_gvkeys.csv",
    REPRODUCED_FILE_PREFIX + "*_gvkeys.csv.gz",
)
CALL_ID_COLUMN = "earningscallID"
CROSSWALK_GVKEY_COLUMN = "gvkey_compustat"
GZIP_MAGIC = b"\x1f\x8b"
MISSING_GVKEY_VALUES = {"", ".", "na", "n/a", "nan", "null", "none", "<na>"}


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
    calls_without_gvkey: int


SERIES_SPECS = [
    SeriesSpec("PRisk", "PRisk", "risk", "prisk-and-psentiment"),
    SeriesSpec("PSentiment", "PSentiment", "sentiment", "prisk-and-psentiment"),
    SeriesSpec("PRiskT_economic", "PRiskT_economic", "risk", "topic-based-prisk-economy"),
    SeriesSpec(
        "PRiskT_environment",
        "PRiskT_environment",
        "risk",
        "topic-based-prisk-environment",
    ),
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
        type=Path,
        default=REPRODUCED_DIR,
        help=(
            "Directory containing NLA *_firmlevel.csv files or an unzipped NLA dataset ZIP. "
            f"Defaults to {REPRODUCED_DIR}."
        ),
    )
    parser.add_argument(
        "--gvkeys-file",
        type=Path,
        help=(
            "GVKEY crosswalk (gvkeys.csv) for NLA files without a gvkey column. Defaults to the "
            "one gvkeys.csv(.gz) or NLA_*_gvkeys.csv in the reproduced-data directory."
        ),
    )
    parser.add_argument(
        "--original-dir",
        type=Path,
        default=ORIGINAL_DIR,
        help=(
            "Directory containing exactly one original score CSV matching "
            f"{', '.join(ORIGINAL_FILE_PATTERNS)}. Defaults to {ORIGINAL_DIR}."
        ),
    )
    parser.add_argument(
        "--original-file",
        type=Path,
        help="Explicit original score CSV. Overrides --original-dir.",
    )
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


def normalize_gvkey(
    value: str | None,
    *,
    source: Path | None = None,
    row: int | None = None,
    column: str = "gvkey",
) -> str:
    """Return a numeric GVKEY as six digits, so 1004, 1004.0 and 001004 match."""
    text = (value or "").strip()
    if text.lower() in MISSING_GVKEY_VALUES:
        return ""
    if re.fullmatch(r"[0-9]+(?:\.0+)?", text):
        number = int(text.partition(".")[0])
        if number < 2**63:
            return f"{number:06d}"
    location = f"{source}: row {row}: " if source is not None else ""
    raise ValueError(
        f"{location}invalid {column} {value!r}; expected a nonnegative integer GVKEY "
        "within the signed 64-bit range"
    )


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


def format_float(value: object) -> object:
    if isinstance(value, float):
        return f"{value:.15g}"
    return value


def format_pearson(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.6f}"


def format_elapsed(start: float) -> str:
    return f"{perf_counter() - start:.1f}s"


def open_csv(path: Path) -> TextIO:
    """Open a CSV as text, decompressing gzip bytes whatever the file name says.

    Files downloaded from a series page can be gzip-encoded under a plain .csv name.
    """
    with path.open("rb") as handle:
        is_gzip = handle.read(2) == GZIP_MAGIC
    if is_gzip:
        return gzip.open(path, "rt", newline="")
    return path.open(newline="")


def resolve_original_file(original_dir: Path, explicit_file: Path | None) -> Path:
    if explicit_file is not None:
        if not explicit_file.exists():
            raise FileNotFoundError(f"Original file not found: {explicit_file}")
        return explicit_file

    candidates: list[Path] = []
    for pattern in ORIGINAL_FILE_PATTERNS:
        candidates.extend(sorted(original_dir.glob(pattern)))

    if not candidates:
        patterns = ", ".join(ORIGINAL_FILE_PATTERNS)
        raise FileNotFoundError(f"No original score CSV matching {patterns} under {original_dir}")
    if len(candidates) > 1:
        names = ", ".join(path.name for path in candidates)
        raise ValueError(f"Multiple original score CSVs found under {original_dir}: {names}")
    return candidates[0]


def resolve_reproduced_dir(reproduced_dir: Path) -> Path:
    if not reproduced_dir.exists():
        raise FileNotFoundError(f"Reproduced directory not found: {reproduced_dir}")
    if not reproduced_dir.is_dir():
        raise NotADirectoryError(f"Reproduced path is not a directory: {reproduced_dir}")
    return reproduced_dir


def resolve_gvkey_crosswalk(reproduced_dir: Path, explicit_file: Path | None) -> Path:
    if explicit_file is not None:
        if not explicit_file.exists():
            raise FileNotFoundError(f"GVKEY crosswalk not found: {explicit_file}")
        return explicit_file

    search_dirs = [reproduced_dir]
    if reproduced_dir.name == "series":
        search_dirs.append(reproduced_dir.parent)
    candidates = sorted(
        {
            path
            for directory in search_dirs
            for pattern in GVKEY_CROSSWALK_PATTERNS
            for path in directory.glob(pattern)
        }
    )
    if not candidates:
        raise FileNotFoundError(
            f"No GVKEY crosswalk found under {reproduced_dir}. NLA files without a gvkey column need the "
            "measure's gvkeys.csv: it is at the root of the dataset ZIP, and a series page offers it as "
            "NLA_*_gvkeys.csv. Put it in the reproduced-data directory or pass --gvkeys-file."
        )
    if len(candidates) > 1:
        names = ", ".join(str(path) for path in candidates)
        raise ValueError(f"Multiple GVKEY crosswalks found: {names}. Keep one or pass --gvkeys-file.")
    return candidates[0]


def read_gvkey_crosswalk(crosswalk_file: Path) -> dict[str, str]:
    """Map nonblank earningscallID to GVKEY, retaining calls without a GVKEY as ''."""
    gvkeys: dict[str, str] = {}
    with open_csv(crosswalk_file) as handle:
        reader = csv.DictReader(handle)
        required = {CALL_ID_COLUMN, CROSSWALK_GVKEY_COLUMN}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{crosswalk_file} is missing columns: {', '.join(sorted(missing))}")

        for row in reader:
            call_id = (row.get(CALL_ID_COLUMN) or "").strip()
            if not call_id:
                continue
            gvkey = normalize_gvkey(
                row.get(CROSSWALK_GVKEY_COLUMN),
                source=crosswalk_file,
                row=reader.line_num,
                column=CROSSWALK_GVKEY_COLUMN,
            )
            known = gvkeys.get(call_id, "")
            if known and gvkey and known != gvkey:
                raise ValueError(
                    f"{crosswalk_file} maps earningscallID {call_id} to more than one gvkey: {known}, {gvkey}"
                )
            gvkeys[call_id] = known or gvkey

    return gvkeys


def read_original(
    original_file: Path,
    columns: set[str],
) -> dict[str, dict[tuple[str, str], float]]:
    by_column: dict[str, dict[tuple[str, str], float]] = defaultdict(dict)
    seen_keys: set[tuple[str, str]] = set()

    with original_file.open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames is None:
            raise ValueError(f"Missing header in {original_file}")
        missing = (columns | {"gvkey", "date"}).difference(reader.fieldnames)
        if missing:
            raise ValueError(f"{original_file} is missing columns: {', '.join(sorted(missing))}")

        for row in reader:
            gvkey = normalize_gvkey(row.get("gvkey"), source=original_file, row=reader.line_num)
            dateq = (row.get("date") or "").strip()
            if not gvkey or not dateq:
                continue
            key = (gvkey, dateq)
            if key in seen_keys:
                raise ValueError(
                    f"{original_file} contains duplicate original firm-quarter row: "
                    f"gvkey={gvkey}, date={dateq}"
                )
            seen_keys.add(key)

            for column in columns:
                value = parse_float(row.get(column))
                if value is None:
                    continue
                by_column[column][key] = value

    return by_column


def resolve_reproduced_file(reproduced_dir: Path, spec: SeriesSpec) -> Path | None:
    candidates = sorted(
        {
            path
            for pattern in REPRODUCED_FILE_PATTERNS
            for path in reproduced_dir.glob(pattern.format(fragment=spec.file_fragment))
        }
    )
    if not candidates:
        return None
    if len(candidates) > 1:
        names = ", ".join(reproduced_file_label(path) for path in candidates)
        raise ValueError(f"Multiple files match {spec.file_fragment!r} under {reproduced_dir}: {names}")
    return candidates[0]


def reproduced_file_label(path: Path) -> str:
    if path.name.startswith(REPRODUCED_FILE_PREFIX):
        return path.name
    return f"{path.parent.name}/{path.name}"


def has_gvkey_column(reproduced_file: Path) -> bool:
    with open_csv(reproduced_file) as handle:
        return "gvkey" in next(csv.reader(handle), [])


def needs_gvkey_crosswalk(reproduced_dir: Path) -> bool:
    for spec in SERIES_SPECS:
        reproduced_file = resolve_reproduced_file(reproduced_dir, spec)
        if reproduced_file is not None and not has_gvkey_column(reproduced_file):
            return True
    return False


def load_reproduced_series(
    reproduced_file: Path,
    spec: SeriesSpec,
    gvkey_crosswalk: dict[str, str] | None = None,
) -> LoadedSeries:
    accumulators: dict[tuple[str, str], dict[str, float]] = defaultdict(
        lambda: {"numerator": 0.0, "nr_of_words": 0.0}
    )
    calls_with_id = 0
    crosswalk_matches = 0
    calls_without_gvkey = 0

    with open_csv(reproduced_file) as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        uses_crosswalk = "gvkey" not in fieldnames
        missing = {"start_time", spec.raw_measure_col, "nr_of_words"}.difference(fieldnames)
        if uses_crosswalk and CALL_ID_COLUMN not in fieldnames:
            missing.add(f"gvkey or {CALL_ID_COLUMN}")
        if missing:
            raise ValueError(f"{reproduced_file} is missing columns: {', '.join(sorted(missing))}")
        if uses_crosswalk and gvkey_crosswalk is None:
            raise ValueError(f"{reproduced_file} has no gvkey column and no GVKEY crosswalk was given.")

        for row in reader:
            if uses_crosswalk and gvkey_crosswalk is not None:
                call_id = (row.get(CALL_ID_COLUMN) or "").strip()
                if call_id:
                    calls_with_id += 1
                    crosswalk_matches += int(call_id in gvkey_crosswalk)
                gvkey = gvkey_crosswalk.get(call_id, "") if call_id else ""
            else:
                gvkey = normalize_gvkey(row.get("gvkey"), source=reproduced_file, row=reader.line_num)
            if not gvkey:
                calls_without_gvkey += 1
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

    if uses_crosswalk and calls_with_id and not crosswalk_matches:
        raise ValueError(
            f"No earningscallID in {reproduced_file} is present in the crosswalk; "
            "use the crosswalk that came with the firm-level files."
        )
    values = {
        key: bucket["numerator"] / bucket["nr_of_words"]
        for key, bucket in accumulators.items()
        if bucket["nr_of_words"] > 0
    }
    return LoadedSeries(
        spec=spec,
        path=reproduced_file,
        values=values,
        calls_without_gvkey=calls_without_gvkey,
    )


@dataclass(frozen=True)
class SeriesComparison:
    n_pairs: int
    n_quarters: int
    first_dateq: str
    last_dateq: str
    firm_pearson: float | None
    quarter_pearson: float | None


def compare_series(
    original: dict[tuple[str, str], float],
    reproduced: dict[tuple[str, str], float],
) -> SeriesComparison:
    """Compare firm-quarters and quarterly means on the same matched sample."""
    common_keys = sorted(original.keys() & reproduced.keys())
    pairs = [(reproduced[key], original[key]) for key in common_keys]
    by_quarter: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for key, pair in zip(common_keys, pairs):
        by_quarter[key[1]].append(pair)
    quarters = sorted(by_quarter)
    quarter_pairs = [
        (
            sum(x for x, _ in by_quarter[q]) / len(by_quarter[q]),
            sum(y for _, y in by_quarter[q]) / len(by_quarter[q]),
        )
        for q in quarters
    ]
    return SeriesComparison(
        n_pairs=len(pairs),
        n_quarters=len(quarters),
        first_dateq=quarters[0] if quarters else "",
        last_dateq=quarters[-1] if quarters else "",
        firm_pearson=pearson(pairs),
        quarter_pearson=pearson(quarter_pairs),
    )


def build_correlation_rows(
    version_dir: Path,
    original_by_column: dict[str, dict[tuple[str, str], float]],
    gvkey_crosswalk: dict[str, str] | None = None,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[str]]:
    gvkey_dateq_rows: list[dict[str, object]] = []
    dateq_rows: list[dict[str, object]] = []
    skipped: list[str] = []

    for index, spec in enumerate(SERIES_SPECS, start=1):
        step_start = perf_counter()
        print(
            f"[{index}/{len(SERIES_SPECS)}] {spec.series}: locating NLA file...",
            flush=True,
        )
        reproduced_file = resolve_reproduced_file(version_dir, spec)
        if reproduced_file is None:
            print(
                f"[{index}/{len(SERIES_SPECS)}] {spec.series}: no matching file found; skipping",
                flush=True,
            )
            skipped.append(spec.series)
            continue

        reproduced_label = reproduced_file_label(reproduced_file)
        print(
            f"[{index}/{len(SERIES_SPECS)}] {spec.series}: loading {reproduced_label}",
            flush=True,
        )
        loaded = load_reproduced_series(reproduced_file, spec, gvkey_crosswalk)
        comparison = compare_series(original_by_column[spec.original_column], loaded.values)
        base = {
            "series": spec.series,
            "original_column": spec.original_column,
            "reproduced_value": spec.reproduced_value,
            "reproduced_file": reproduced_label,
            "first_dateQ": comparison.first_dateq,
            "last_dateQ": comparison.last_dateq,
        }
        gvkey_dateq_rows.append(
            {
                **base,
                "level": "gvkey-dateQ",
                "n_pairs": comparison.n_pairs,
                "n_dateQ": comparison.n_quarters,
                "pearson": comparison.firm_pearson,
            }
        )
        dateq_rows.append(
            {
                **base,
                "level": "dateQ",
                "n_pairs": comparison.n_quarters,
                "matched_gvkey_dateQ": comparison.n_pairs,
                "pearson": comparison.quarter_pearson,
            }
        )
        print(
            f"[{index}/{len(SERIES_SPECS)}] {spec.series}: matched "
            f"{comparison.n_pairs:,} firm-quarters across {comparison.n_quarters:,} quarters "
            f"(firm-quarter r={format_pearson(comparison.firm_pearson)}, "
            f"quarter r={format_pearson(comparison.quarter_pearson)}, "
            f"{loaded.calls_without_gvkey:,} calls without a GVKEY, {format_elapsed(step_start)})",
            flush=True,
        )

    return gvkey_dateq_rows, dateq_rows, skipped


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: format_float(row.get(field, "")) for field in fieldnames})


def write_manifest(
    path: Path,
    original_file: Path,
    reproduced_files: list[Path],
    crosswalk_file: Path | None,
) -> None:
    """Identify the exact inputs, including a crosswalk only when it was used."""
    inputs = [("original_csv", original_file)]
    inputs.extend(("reproduced_csv", file) for file in sorted(set(reproduced_files)))
    if crosswalk_file is not None:
        inputs.append(("gvkey_crosswalk", crosswalk_file))
    rows = []
    for role, file in inputs:
        digest = hashlib.sha256()
        with file.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        with open_csv(file) as handle:
            reader = csv.reader(handle, delimiter="\t" if role == "original_csv" else ",")
            next(reader, None)
            count = sum(1 for _ in reader)
        rows.append(
            {
                "role": role,
                "path": str(file),
                "bytes": file.stat().st_size,
                "rows": count,
                "sha256": digest.hexdigest(),
            }
        )
    write_csv(path, rows, ["role", "path", "bytes", "rows", "sha256"])


def main() -> None:
    run_start = perf_counter()
    args = parse_args()
    reproduced_dir = resolve_reproduced_dir(args.reproduced_dir)
    original_file = resolve_original_file(args.original_dir, args.original_file)

    print(f"Original file: {original_file}", flush=True)
    print(f"Reproduced directory: {reproduced_dir}", flush=True)

    gvkey_crosswalk = None
    crosswalk_file = None
    if needs_gvkey_crosswalk(reproduced_dir):
        crosswalk_file = resolve_gvkey_crosswalk(reproduced_dir, args.gvkeys_file)
        gvkey_crosswalk = read_gvkey_crosswalk(crosswalk_file)
        mapped_calls = sum(bool(gvkey) for gvkey in gvkey_crosswalk.values())
        print(
            f"GVKEY crosswalk: {crosswalk_file} ({mapped_calls:,} calls with a GVKEY)",
            flush=True,
        )

    original_columns = {spec.original_column for spec in SERIES_SPECS}
    print("Reading original firm-quarter scores...", flush=True)
    original_by_column = read_original(original_file, original_columns)
    original_key_count = len({key for values in original_by_column.values() for key in values})
    print(
        f"Loaded original scores for {original_key_count:,} firm-quarters "
        f"across {len(original_columns)} series ({format_elapsed(run_start)}).",
        flush=True,
    )

    print("Reading reproduced NLA files and computing correlations...", flush=True)
    gvkey_dateq_rows, dateq_rows, skipped = build_correlation_rows(
        reproduced_dir,
        original_by_column,
        gvkey_crosswalk,
    )
    if not gvkey_dateq_rows:
        raise SystemExit(f"No matching NLA firmlevel files found under {reproduced_dir}.")

    gvkey_dateq_path = args.out_dir / "firm_quarter_correlations.csv"
    dateq_path = args.out_dir / "quarterly_mean_correlations.csv"
    print(f"Writing correlation outputs to {args.out_dir}...", flush=True)
    write_csv(gvkey_dateq_path, gvkey_dateq_rows, GVKEY_DATEQ_FIELDS)
    write_csv(dateq_path, dateq_rows, DATEQ_FIELDS)
    reproduced_files = [
        file for spec in SERIES_SPECS if (file := resolve_reproduced_file(reproduced_dir, spec)) is not None
    ]
    manifest_path = args.out_dir / "data_manifest.csv"
    write_manifest(manifest_path, original_file, reproduced_files, crosswalk_file)
    print(f"Wrote {manifest_path}")
    print(f"Wrote {gvkey_dateq_path}")
    print(f"Wrote {dateq_path}")

    if skipped:
        print(f"Skipped unavailable series: {', '.join(skipped)}")
    print(f"Done in {format_elapsed(run_start)}.", flush=True)


if __name__ == "__main__":
    main()
