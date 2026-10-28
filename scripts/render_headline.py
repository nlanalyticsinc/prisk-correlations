"""Render the README and notebook headline table from generated correlation CSVs."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

START = "<!-- headline-table:start -->"
END = "<!-- headline-table:end -->"


def render_headline_table(directory: Path = Path("data/correlations")) -> str:
    def read(name: str) -> list[dict[str, str]]:
        with (directory / name).open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        return rows

    firms = read("firm_quarter_correlations.csv")
    quarters = {row["series"]: row for row in read("quarterly_mean_correlations.csv")}
    lines = [
        "| Series | Firm-quarter Pearson | Quarter Pearson | Matched firm-quarters | Quarters |",
        "|---|---:|---:|---:|---:|",
    ]
    firm_values: list[float] = []
    quarter_values: list[float] = []
    for row in firms:
        qrow = quarters[row["series"]]
        firm_value = float(row["pearson"]) if row["pearson"] else None
        quarter_value = float(qrow["pearson"]) if qrow["pearson"] else None
        if firm_value is not None:
            firm_values.append(firm_value)
        if quarter_value is not None:
            quarter_values.append(quarter_value)
        firm_text = f"{firm_value:.2f}" if firm_value is not None else "n/a"
        quarter_text = f"{quarter_value:.2f}" if quarter_value is not None else "n/a"
        lines.append(
            f"| `{row['series']}` | {firm_text} | {quarter_text} | "
            f"{int(row['n_pairs']):,} | {int(qrow['n_pairs']):,} |"
        )
    firm_average = f"{sum(firm_values) / len(firm_values):.2f}" if firm_values else "n/a"
    quarter_average = f"{sum(quarter_values) / len(quarter_values):.2f}" if quarter_values else "n/a"
    lines.append(f"| Average | {firm_average} | {quarter_average} | - | - |")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--correlations-dir", type=Path, default=Path("data/correlations"))
    parser.add_argument(
        "--readme",
        type=Path,
        help="Update only the marked headline table in this file.",
    )
    args = parser.parse_args()
    table = render_headline_table(args.correlations_dir)
    if args.readme is None:
        print(table)
        return
    text = args.readme.read_text()
    if text.count(START) != 1 or text.count(END) != 1 or text.index(START) >= text.index(END):
        raise ValueError(f"{args.readme} must contain one ordered pair of headline-table markers")
    before, rest = text.split(START)
    _, after = rest.split(END)
    args.readme.write_text(f"{before}{START}\n{table}\n{END}{after}")


if __name__ == "__main__":
    main()
