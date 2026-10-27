from __future__ import annotations

import csv
import gzip
import sys
from pathlib import Path

import pytest

import correlate_original_reproduced as script

ORIGINAL_ROWS = [
    # gvkey, date, PRisk, PSentiment
    ("001004", "2020q1", 1.0, 4.0),
    ("001004", "2020q2", 2.0, 3.0),
    ("012345", "2020q1", 3.0, 2.0),
    ("012345", "2020q2", 5.0, 1.0),
]
CALLS = [
    # earningscallID, gvkey, start_time, risk, sentiment, nr_of_words
    ("call-1", "001004", "2020-01-20 13:30:00.000000000Z", 10.0, 40.0, 1000),
    ("call-2", "001004", "2020-04-20 13:30:00.000000000Z", 25.0, 30.0, 1000),
    ("call-3", "012345", "2020-01-21 13:30:00.000000000Z", 30.0, 20.0, 1000),
    ("call-4", "012345", "2020-04-21 13:30:00.000000000Z", 20.0, 10.0, 500),
    ("call-5", "012345", "2020-05-21 13:30:00.000000000Z", 40.0, 15.0, 1500),
    ("call-6", "", "2020-04-22 13:30:00.000000000Z", 99.0, 99.0, 1000),
]
SERIES_PAGE_PREFIX = "NLA_2026-10-22T000000_prisk-and-psentiment-v21_67e91380"
LAYOUTS = ["series_page_with_gvkey", "dataset_zip", "series_page_gzip"]


def write_text(path: Path, text: str, *, gzip_bytes: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if gzip_bytes:
        path.write_bytes(gzip.compress(text.encode()))
    else:
        path.write_text(text)


def csv_text(header: list[str], rows: list[list[object]], delimiter: str = ",") -> str:
    lines = [delimiter.join(header)]
    lines.extend(delimiter.join(str(value) for value in row) for row in rows)
    return "\n".join(lines) + "\n"


def write_original(path: Path) -> None:
    columns = [spec.original_column for spec in script.SERIES_SPECS]
    rows = []
    for gvkey, date, prisk, psentiment in ORIGINAL_ROWS:
        values = {"PRisk": prisk, "PSentiment": psentiment}
        rows.append([gvkey, date, *(values.get(column, "") for column in columns)])
    write_text(path, csv_text(["gvkey", "date", *columns], rows, delimiter="\t"))


def write_firmlevel(path: Path, *, with_gvkey: bool, gzip_bytes: bool = False) -> None:
    id_column = "gvkey" if with_gvkey else "earningscallID"
    rows = [
        [gvkey if with_gvkey else call_id, start_time, risk, sentiment, words]
        for call_id, gvkey, start_time, risk, sentiment, words in CALLS
    ]
    header = [id_column, "start_time", "risk", "sentiment", "nr_of_words"]
    write_text(path, csv_text(header, rows), gzip_bytes=gzip_bytes)


def write_crosswalk(path: Path, gvkeys: dict[str, str], *, gzip_bytes: bool = False) -> None:
    header = ["earningscallID", "gvkey_compustat", "sic_compustat", "sic_compustat_description"]
    rows = [[call_id, gvkey, "7372", "Prepackaged Software"] for call_id, gvkey in gvkeys.items()]
    write_text(path, csv_text(header, rows), gzip_bytes=gzip_bytes)


def crosswalk_gvkeys() -> dict[str, str]:
    return {call_id: gvkey for call_id, gvkey, *_ in CALLS}


def write_layout(reproduced_dir: Path, layout: str, gvkeys: dict[str, str] | None = None) -> None:
    gvkeys = crosswalk_gvkeys() if gvkeys is None else gvkeys
    if layout == "series_page_with_gvkey":
        # Files downloaded before the October 2026 refresh still carry gvkey.
        path = reproduced_dir / "NLA_2026-06-24T114811_prisk-and-psentiment-v21_67e91380_firmlevel.csv"
        write_firmlevel(path, with_gvkey=True)
    elif layout == "dataset_zip":
        # The unzipped "Download dataset (ZIP)" bundle: gvkeys.csv.gz sits at its root.
        series_dir = reproduced_dir / "series" / "01-prisk-and-psentiment-v21-67e91380"
        write_firmlevel(series_dir / "firmlevel.csv.gz", with_gvkey=False, gzip_bytes=True)
        write_crosswalk(reproduced_dir / "gvkeys.csv.gz", gvkeys, gzip_bytes=True)
    elif layout == "series_page_gzip":
        # Series-page downloads can hold gzip bytes under a plain .csv name; GVKEYs
        # without zero padding still match the original's six-digit gvkey.
        write_firmlevel(reproduced_dir / f"{SERIES_PAGE_PREFIX}_firmlevel.csv", with_gvkey=False, gzip_bytes=True)
        unpadded = {call_id: gvkey.lstrip("0") for call_id, gvkey in gvkeys.items()}
        write_crosswalk(reproduced_dir / f"{SERIES_PAGE_PREFIX}_gvkeys.csv", unpadded, gzip_bytes=True)
    else:
        raise ValueError(f"Unknown layout: {layout}")


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def run_script(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, reproduced_dir: Path, *extra_args: str
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    original_file = tmp_path / "original" / "firmquarter_2022q1.csv"
    write_original(original_file)
    out_dir = tmp_path / "correlations"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "correlate_original_reproduced.py",
            "--original-file",
            str(original_file),
            "--reproduced-dir",
            str(reproduced_dir),
            "--out-dir",
            str(out_dir),
            *extra_args,
        ],
    )
    script.main()
    return (
        read_rows(out_dir / "firm_quarter_correlations.csv"),
        read_rows(out_dir / "quarterly_mean_correlations.csv"),
    )


def without_file(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [{key: value for key, value in row.items() if key != "reproduced_file"} for row in rows]


def test_layouts_produce_identical_correlations(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    results = {}
    for layout in LAYOUTS:
        reproduced_dir = tmp_path / layout / "reproduced"
        write_layout(reproduced_dir, layout)
        results[layout] = run_script(monkeypatch, tmp_path / layout, reproduced_dir)

    firm_quarter_rows, quarter_rows = results["series_page_with_gvkey"]
    assert [row["series"] for row in firm_quarter_rows] == ["PRisk", "PSentiment"]
    assert [row["n_pairs"] for row in firm_quarter_rows] == ["4", "4"]
    assert [row["n_pairs"] for row in quarter_rows] == ["2", "2"]
    assert {row["first_dateQ"] for row in firm_quarter_rows} == {"2020q1"}
    assert {row["last_dateQ"] for row in firm_quarter_rows} == {"2020q2"}
    assert results["dataset_zip"][0][0]["reproduced_file"] == "01-prisk-and-psentiment-v21-67e91380/firmlevel.csv.gz"
    assert results["series_page_gzip"][0][0]["reproduced_file"] == f"{SERIES_PAGE_PREFIX}_firmlevel.csv"
    for layout in LAYOUTS[1:]:
        assert without_file(results[layout][0]) == without_file(firm_quarter_rows)
        assert without_file(results[layout][1]) == without_file(quarter_rows)


def test_calls_missing_from_crosswalk_drop_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    gvkeys = crosswalk_gvkeys()
    del gvkeys["call-3"]
    reproduced_dir = tmp_path / "reproduced"
    write_layout(reproduced_dir, "dataset_zip", gvkeys)

    firm_quarter_rows, _ = run_script(monkeypatch, tmp_path, reproduced_dir)

    assert [row["n_pairs"] for row in firm_quarter_rows] == ["3", "3"]
    assert "2 calls without a GVKEY" in capsys.readouterr().out


def test_crosswalk_from_another_download_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    reproduced_dir = tmp_path / "reproduced"
    write_layout(reproduced_dir, "dataset_zip", {"other-call": "001004"})

    with pytest.raises(ValueError, match="No earningscallID in .* has a GVKEY in the crosswalk"):
        run_script(monkeypatch, tmp_path, reproduced_dir)


def test_missing_crosswalk_is_reported(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    reproduced_dir = tmp_path / "reproduced"
    write_layout(reproduced_dir, "dataset_zip")
    (reproduced_dir / "gvkeys.csv.gz").unlink()

    with pytest.raises(FileNotFoundError, match="No GVKEY crosswalk found"):
        run_script(monkeypatch, tmp_path, reproduced_dir)


def test_crosswalk_is_found_from_series_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    reproduced_dir = tmp_path / "reproduced"
    write_layout(reproduced_dir, "dataset_zip")

    firm_quarter_rows, _ = run_script(monkeypatch, tmp_path, reproduced_dir / "series")

    assert [row["n_pairs"] for row in firm_quarter_rows] == ["4", "4"]


def test_gvkeys_file_overrides_discovery(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    reproduced_dir = tmp_path / "reproduced"
    write_layout(reproduced_dir, "dataset_zip")
    gvkeys_file = tmp_path / "elsewhere" / "gvkeys.csv.gz"
    gvkeys_file.parent.mkdir()
    (reproduced_dir / "gvkeys.csv.gz").rename(gvkeys_file)

    firm_quarter_rows, _ = run_script(monkeypatch, tmp_path, reproduced_dir, "--gvkeys-file", str(gvkeys_file))

    assert [row["n_pairs"] for row in firm_quarter_rows] == ["4", "4"]


def test_multiple_crosswalks_are_rejected(tmp_path: Path) -> None:
    write_crosswalk(tmp_path / "gvkeys.csv", crosswalk_gvkeys())
    write_crosswalk(tmp_path / f"{SERIES_PAGE_PREFIX}_gvkeys.csv", crosswalk_gvkeys())

    with pytest.raises(ValueError, match="Multiple GVKEY crosswalks found"):
        script.resolve_gvkey_crosswalk(tmp_path, None)


def test_read_gvkey_crosswalk_rejects_conflicting_gvkeys(tmp_path: Path) -> None:
    path = tmp_path / "gvkeys.csv"
    write_text(
        path,
        csv_text(["earningscallID", "gvkey_compustat"], [["call-1", "001004"], ["call-1", "001005"]]),
    )

    with pytest.raises(ValueError, match="maps earningscallID call-1 to more than one gvkey"):
        script.read_gvkey_crosswalk(path)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("001004", "001004"), ("1004", "001004"), ("1004.0", "001004"), (" 012345 ", "012345"), ("", ""), (None, "")],
)
def test_normalize_gvkey(value: str | None, expected: str) -> None:
    assert script.normalize_gvkey(value) == expected
